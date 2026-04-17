import json
import pytest
from fastapi.testclient import TestClient
import alac_rip.server as server_mod
from alac_rip.server import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        f"music_dir: {tmp_path}/Music\n"
        f"staging_dir: {tmp_path}/staging\n"
        f"state_dir: {tmp_path}/state\n"
        "media_user_token: fake_token\n"
        "apple_id_email: test@example.com\n"
        "apple_id_password: fake_pass\n"
        "downloader_repo: /tmp/dl\n"
        "wrapper_bin: /tmp/wrapper\n"
        "github_remote: ''\n"
    )
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", cfg_file)
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_get_playlists_returns_list(client):
    resp = client.get("/playlists")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_add_and_delete_playlist(client):
    resp = client.post("/playlists", json={"name": "Test PL", "url": "https://music.apple.com/test"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Test PL"

    resp = client.delete("/playlists/Test PL")
    assert resp.status_code == 204

    names = [p["name"] for p in client.get("/playlists").json()]
    assert "Test PL" not in names


def test_sync_unknown_playlist_returns_404(client):
    resp = client.get("/sync/Nonexistent Playlist")
    assert resp.status_code == 404


def test_sync_streams_done_event(client, monkeypatch):
    from alac_rip import sync as sync_mod
    from alac_rip.sync import SyncResult
    from pathlib import Path

    # Add a real playlist first
    client.post("/playlists", json={"name": "SSE Test", "url": "https://music.apple.com/fake"})

    # Patch SyncEngine.sync to return immediately without touching the downloader
    monkeypatch.setattr(
        sync_mod.SyncEngine,
        "sync",
        lambda self, url: SyncResult(new_count=3, skipped_count=1, error_count=0),
    )

    events = []
    with client.stream("GET", "/sync/SSE Test") as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
                if events[-1]["status"] != "running":
                    break

    done = next(e for e in events if e["status"] == "done")
    assert done["new"] == 3
    assert done["skipped"] == 1
    assert done["errors"] == 0
    assert "log_path" in done
    assert Path(done["log_path"]).exists()
    assert "playlist=SSE Test" in Path(done["log_path"]).read_text()

    # Cleanup
    client.delete("/playlists/SSE Test")


def test_library_returns_dict(client):
    resp = client.get("/library")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    for tracks in data.values():
        assert isinstance(tracks, list)


def test_track_art_missing_path_returns_404(client):
    resp = client.get("/track-art", params={"path": "/tmp/nonexistent.m4a"})
    assert resp.status_code == 404


def test_get_config_omits_password(client):
    resp = client.get("/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "music_dir" in data
    assert "apple_id_password" not in data


def test_diagnostics_returns_list(client):
    resp = client.get("/diagnostics")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    for check in data:
        assert "label" in check
        assert "ok" in check
        assert isinstance(check["ok"], bool)


def test_diagnostics_includes_expected_checks(client):
    resp = client.get("/diagnostics")
    labels = {c["label"] for c in resp.json()}
    for expected in ("ffmpeg", "Podman", "Config file", "Media user token", "Systemd timer"):
        assert expected in labels


def test_stats_returns_expected_shape(client):
    resp = client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "playlist_count" in data
    assert "total_tracks" in data
    assert "last_sync" in data
    assert "playlists" in data
    assert isinstance(data["playlists"], list)


def test_stats_reflects_added_playlist(client):
    client.post("/playlists", json={"name": "Stats PL", "url": "https://music.apple.com/test"})
    resp = client.get("/stats")
    data = resp.json()
    assert data["playlist_count"] == 1
    names = [p["name"] for p in data["playlists"]]
    assert "Stats PL" in names
    client.delete("/playlists/Stats PL")


def test_patch_playlist_pause(client):
    client.post("/playlists", json={"name": "Pausable", "url": "https://music.apple.com/x"})

    resp = client.patch("/playlists/Pausable", json={"paused": True})
    assert resp.status_code == 200
    assert resp.json()["paused"] is True

    resp = client.patch("/playlists/Pausable", json={"paused": False})
    assert resp.status_code == 200
    assert resp.json()["paused"] is False

    client.delete("/playlists/Pausable")


def test_patch_playlist_rename(client):
    client.post("/playlists", json={"name": "Old Name", "url": "https://music.apple.com/x"})

    resp = client.patch("/playlists/Old Name", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"

    names = [p["name"] for p in client.get("/playlists").json()]
    assert "New Name" in names
    assert "Old Name" not in names

    client.delete("/playlists/New Name")


def test_patch_playlist_rename_conflict(client):
    client.post("/playlists", json={"name": "Alpha", "url": "https://music.apple.com/a"})
    client.post("/playlists", json={"name": "Beta",  "url": "https://music.apple.com/b"})

    resp = client.patch("/playlists/Alpha", json={"name": "Beta"})
    assert resp.status_code == 409

    client.delete("/playlists/Alpha")
    client.delete("/playlists/Beta")


def test_patch_playlist_not_found(client):
    resp = client.patch("/playlists/Ghost", json={"paused": True})
    assert resp.status_code == 404


def test_sync_paused_playlist_returns_409(client, monkeypatch):
    client.post("/playlists", json={"name": "Paused PL", "url": "https://music.apple.com/x"})
    client.patch("/playlists/Paused PL", json={"paused": True})

    resp = client.get("/sync/Paused PL")
    assert resp.status_code == 409

    client.delete("/playlists/Paused PL")


def test_add_playlist_response_includes_paused(client):
    resp = client.post("/playlists", json={"name": "Paused Field", "url": "https://music.apple.com/x"})
    assert resp.status_code == 201
    assert "paused" in resp.json()
    assert resp.json()["paused"] is False
    client.delete("/playlists/Paused Field")


def test_put_config_roundtrip(client, tmp_path, monkeypatch):
    import alac_rip.server as server_mod

    fake_cfg_path = tmp_path / "config2.yaml"
    fake_cfg_path.write_text(
        "music_dir: ~/Music\nmedia_user_token: tok\napple_id_email: a@b.com\n"
        "apple_id_password: secret\nstaging_dir: /tmp/s\n"
        "downloader_repo: /tmp/d\nwrapper_bin: /tmp/w\nstate_dir: /tmp/st\n"
        "github_remote: ''\n"
    )
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", fake_cfg_path)

    resp = client.put("/config", json={"apple_id_email": "new@email.com"})
    assert resp.status_code == 200
    data = fake_cfg_path.read_text()
    assert "new@email.com" in data
