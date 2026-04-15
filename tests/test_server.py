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
