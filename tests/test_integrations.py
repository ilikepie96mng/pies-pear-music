from unittest.mock import patch, MagicMock
from alac_rip import integrations
from alac_rip.requests import RequestStore


def test_jellyfin_connection_success():
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ServerName": "HomeJelly", "Version": "10.8.13"}
        mock_get.return_value = mock_resp

        ok, msg = integrations.test_jellyfin_connection("http://localhost:8096", "apikey123")
        assert ok is True
        assert "HomeJelly" in msg


def test_jellyfin_connection_failure():
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp

        ok, msg = integrations.test_jellyfin_connection("http://localhost:8096", "badkey")
        assert ok is False
        assert "Authentication failed" in msg


def test_jellyfin_refresh_trigger():
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_post.return_value = mock_resp

        ok, msg = integrations.trigger_jellyfin_refresh("http://localhost:8096", "apikey123")
        assert ok is True


def test_navidrome_connection_success():
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"subsonic-response": {"status": "ok", "version": "1.16.1"}}
        mock_get.return_value = mock_resp

        ok, msg = integrations.test_navidrome_connection("http://localhost:4533", "admin", "tok", "salt")
        assert ok is True
        assert "Subsonic/Navidrome" in msg


def test_navidrome_refresh_trigger():
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"subsonic-response": {"status": "ok"}}
        mock_get.return_value = mock_resp

        ok, msg = integrations.trigger_navidrome_refresh("http://localhost:4533", "admin", "tok", "salt")
        assert ok is True


def test_dispatch_webhooks():
    config = {
        "integrations": {
            "jellyfin": {"enabled": True, "auto_refresh": True, "server_url": "http://jf:8096", "api_key": "key"},
            "navidrome": {"enabled": False},
        }
    }
    with patch("alac_rip.integrations.trigger_jellyfin_refresh") as mock_jf:
        mock_jf.return_value = (True, "Refreshed")
        results = integrations.dispatch_media_webhooks(config)
        assert len(results) == 1
        assert results[0]["service"] == "jellyfin"


def test_download_request_store(tmp_path):
    store = RequestStore(tmp_path / "requests.db")
    req = store.add_request("https://music.apple.com/us/playlist/test/pl.123", requester="alice", notes="Lossless pls")
    assert req.status == "pending"
    assert req.requester == "alice"

    all_reqs = store.list_requests()
    assert len(all_reqs) == 1

    store.update_request_status(req.id, "completed")
    completed = store.list_requests(status="completed")
    assert len(completed) == 1
    assert completed[0].status == "completed"

    store.delete_request(req.id)
    assert len(store.list_requests()) == 0
