import time
import pytest
from pathlib import Path
from starlette.testclient import TestClient
from alac_rip.config import Config, save_config_file
from alac_rip.organizer import track_path
from alac_rip.server import (
    app,
    _create_session_token,
    _verify_session_token,
    _sessions,
    _login_failed_attempts,
    _MAX_SESSIONS,
)
import alac_rip.server as server_mod


@pytest.fixture
def auth_client(tmp_path: Path, monkeypatch):
    music_dir = tmp_path / "music"
    state_dir = tmp_path / "state"
    alac_rip_dir = tmp_path / "alac_rip"
    config_file = tmp_path / "config.yaml"
    music_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    alac_rip_dir.mkdir(parents=True)

    config_data = {
        "music_dir": str(music_dir),
        "state_dir": str(state_dir),
        "alac_rip_dir": str(alac_rip_dir),
        "auth_password": "correct-horse-battery",
        "api_token": "test-api-token-secret-123",
    }
    save_config_file(config_file, config_data)
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", config_file)
    monkeypatch.setattr(server_mod, "_api_capability", "")
    _sessions.clear()
    _login_failed_attempts.clear()

    with TestClient(app) as client:
        yield client, config_data


def test_fail_closed_unauthenticated_requests(auth_client):
    client, cfg_data = auth_client

    # Public routes should succeed without credentials
    assert client.get("/health").status_code == 200
    assert client.get("/auth/status").status_code == 200

    # Protected routes must fail with 401 when no auth provided
    protected_paths = [
        ("GET", "/config"),
        ("PUT", "/config"),
        ("GET", "/library/summary"),
        ("GET", "/diagnostics"),
        ("POST", "/sync"),
        ("POST", "/library/deduplicate"),
    ]

    for method, path in protected_paths:
        if method == "GET":
            res = client.get(path)
        elif method == "POST":
            res = client.post(path)
        elif method == "PUT":
            res = client.put(path, json={})
        assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}"


def test_headless_fail_closed_with_empty_secrets(tmp_path: Path, monkeypatch):
    """Verify headless mode fails closed (401) on protected routes even when both auth_password and api_token are empty."""
    music_dir = tmp_path / "music"
    state_dir = tmp_path / "state"
    alac_rip_dir = tmp_path / "alac_rip"
    config_file = tmp_path / "config.yaml"
    music_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    alac_rip_dir.mkdir(parents=True)

    config_data = {
        "music_dir": str(music_dir),
        "state_dir": str(state_dir),
        "alac_rip_dir": str(alac_rip_dir),
        "auth_password": "",
        "api_token": "",
    }
    save_config_file(config_file, config_data)
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", config_file)
    monkeypatch.setattr(server_mod, "_is_headless", True)
    monkeypatch.setattr(server_mod, "_api_capability", "")
    _sessions.clear()
    _login_failed_attempts.clear()

    with TestClient(app) as client:
        # Public health endpoint is 200
        assert client.get("/health").status_code == 200

        # Protected endpoints must fail with 401 in headless mode
        res = client.get("/config")
        assert res.status_code == 401

        res = client.get("/library/summary")
        assert res.status_code == 401


def test_auth_login_sets_cookie_and_protects_routes(auth_client):
    client, cfg_data = auth_client

    # 1. Failed login
    fail_res = client.post("/auth/login", json={"password": "wrong-password"})
    assert fail_res.status_code == 401

    # 2. Successful login
    login_res = client.post("/auth/login", json={"password": "correct-horse-battery"})
    assert login_res.status_code == 200
    data = login_res.json()
    assert data["authenticated"] is True
    # Bearer token should NOT be in json response
    assert "token" not in data
    # Cookie should be set
    assert "pies_session" in client.cookies

    # 3. Protected route works with cookie
    status_res = client.get("/auth/status")
    assert status_res.status_code == 200
    assert status_res.json()["authenticated"] is True

    # 4. Logout works and clears session
    logout_res = client.post("/auth/logout")
    assert logout_res.status_code == 200

    # 5. Subsequent access to protected route returns 401
    assert client.get("/config").status_code == 401


def test_api_token_header_and_bearer_auth(auth_client):
    client, cfg_data = auth_client

    # Test with X-Pies-Api-Token header
    res1 = client.get("/config", headers={"X-Pies-Api-Token": "test-api-token-secret-123"})
    assert res1.status_code == 200

    # Test with Authorization: Bearer <token>
    res2 = client.get("/config", headers={"Authorization": "Bearer test-api-token-secret-123"})
    assert res2.status_code == 200

    # Test with wrong token
    res3 = client.get("/config", headers={"X-Pies-Api-Token": "wrong-token"})
    assert res3.status_code == 401


def test_login_rate_limiting(auth_client):
    client, cfg_data = auth_client

    for i in range(5):
        r = client.post("/auth/login", json={"password": "bad"})
        assert r.status_code == 401

    # 6th attempt should be blocked with 429
    blocked_res = client.post("/auth/login", json={"password": "bad"})
    assert blocked_res.status_code == 429
    assert "Too many failed login attempts" in blocked_res.text


def test_session_lifecycle_ttl_and_lru():
    _sessions.clear()
    token = _create_session_token()
    assert _verify_session_token(token) is True

    # Test TTL expiration
    _sessions[token] = time.time() - 1.0  # expired
    assert _verify_session_token(token) is False
    assert token not in _sessions

    # Test LRU eviction cap
    _sessions.clear()
    tokens = []
    for i in range(_MAX_SESSIONS + 10):
        t = _create_session_token()
        tokens.append(t)

    assert len(_sessions) <= _MAX_SESSIONS
    # Oldest token should be evicted
    assert tokens[0] not in _sessions


def test_track_path_strict_extension_and_containment(tmp_path: Path):
    music_dir = tmp_path / "music"
    music_dir.mkdir()

    # Valid extension
    p = track_path(music_dir, "Artist", "Album", 1, "Track", ext=".flac")
    assert p.suffix == ".flac"
    assert p.is_relative_to(music_dir)

    # Invalid extension must raise ValueError
    with pytest.raises(ValueError, match="Invalid or disallowed file extension"):
        track_path(music_dir, "Artist", "Album", 1, "Track", ext=".exe")

    with pytest.raises(ValueError, match="Invalid or disallowed file extension"):
        track_path(music_dir, "Artist", "Album", 1, "Track", ext=".sh")
