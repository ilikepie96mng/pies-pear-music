from fastapi.testclient import TestClient
from unittest.mock import patch
import alac_rip.server as server
from alac_rip.config import Config


def test_scheduler_api_endpoints(tmp_path):
    server.cfg = Config(
        music_dir=tmp_path / "music",
        state_dir=tmp_path / "state",
        alac_rip_dir=tmp_path / "alac",
    )
    client = TestClient(server.app)

    # Status endpoint
    resp = client.get("/api/v1/scheduler/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "interval_minutes" in data

    # Trigger endpoint
    resp = client.post("/api/v1/scheduler/trigger")
    assert resp.status_code in (200, 503)


@patch("alac_rip.integrations.send_discord_webhook")
def test_test_webhook_endpoint(mock_discord, tmp_path):
    mock_discord.return_value = (True, "Delivered successfully")
    server.cfg = Config(
        music_dir=tmp_path / "music",
        state_dir=tmp_path / "state",
        alac_rip_dir=tmp_path / "alac",
    )
    client = TestClient(server.app)

    resp = client.post("/api/v1/integrations/test-webhook", json={
        "service": "discord",
        "url": "https://discord.com/api/webhooks/123/abc"
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_api_token_protection(tmp_path):
    server.cfg = Config(
        music_dir=tmp_path / "music",
        state_dir=tmp_path / "state",
        alac_rip_dir=tmp_path / "alac",
        api_token="super-secret-token-123",
    )
    client = TestClient(server.app)

    # Unauthorized request without token
    resp = client.get("/api/v1/queue")
    assert resp.status_code == 401

    # Authorized request with Bearer header
    resp = client.get("/api/v1/queue", headers={"Authorization": "Bearer super-secret-token-123"})
    assert resp.status_code in (200, 503)

    # Authorized request with query parameter
    resp = client.get("/api/v1/queue?token=super-secret-token-123")
    assert resp.status_code in (200, 503)

    # Clean up token
    server.cfg.api_token = ""


def test_spa_frontend_route_serving(tmp_path):
    from alac_rip.state import StateManager
    # Create fake web dir with index.html
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<!DOCTYPE html><html><body>Pies Pear Music Web</body></html>")
    (web_dir / "custom.js").write_text("console.log('test');")

    server.cfg = Config(
        music_dir=tmp_path / "music",
        state_dir=tmp_path / "state",
        alac_rip_dir=tmp_path / "alac",
        web_dir=web_dir,
    )
    server.state = StateManager(tmp_path / "test.db")
    server._web_dir = web_dir

    client = TestClient(server.app)

    # Root route should return index.html
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Pies Pear Music Web" in resp.text

    # Client-side SPA navigation routes should return index.html
    for route in ["/download", "/explore", "/about", "/app/view"]:
        resp = client.get(route)
        assert resp.status_code == 200
        assert "Pies Pear Music Web" in resp.text

    # Static file asset should return exact file
    resp = client.get("/custom.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


