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


def _make_staging_file(playlist_name: str) -> None:
    """Create a dummy staging FLAC so the pre-flight check passes."""
    # Staging dir is no longer used (endpoint is stubbed with 501)
    # This helper is kept for backwards compatibility but does nothing
    pass


def test_sync_streams_done_event(client, monkeypatch):
    from alac_rip import sync as sync_mod
    from alac_rip.sync import SyncResult
    from pathlib import Path

    # Add a real playlist first
    client.post("/playlists", json={"name": "SSE Test", "url": "https://music.apple.com/fake"})
    _make_staging_file("SSE Test")

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
    for expected in ("ffmpeg", "Config file", "Music directory", "State directory", "Systemd timer"):
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


def test_playlist_has_no_staging_folder(client):
    resp = client.post("/playlists", json={"name": "SF Test", "url": "https://music.apple.com/x"})
    assert resp.status_code == 201
    assert "staging_folder" not in resp.json()
    client.delete("/playlists/SF Test")


def test_delete_playlist_cleans_sync_history(client, monkeypatch):
    from alac_rip import sync as sync_mod
    from alac_rip.sync import SyncResult

    client.post("/playlists", json={"name": "Delete Me", "url": "https://music.apple.com/fake"})
    _make_staging_file("Delete Me")

    monkeypatch.setattr(
        sync_mod.SyncEngine, "sync",
        lambda self, url: SyncResult(new_count=1, skipped_count=0, error_count=0),
    )

    with client.stream("GET", "/sync/Delete Me") as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                if json.loads(line[5:].strip())["status"] != "running":
                    break

    # confirm run was recorded
    assert len(client.get("/sync-history/Delete Me").json()) == 1

    client.delete("/playlists/Delete Me")

    # run should be gone from global history too
    names = {r["playlist_name"] for r in client.get("/sync-history").json()}
    assert "Delete Me" not in names


def test_sync_history_empty_initially(client):
    resp = client.get("/sync-history")
    assert resp.status_code == 200
    assert resp.json() == []


def test_sync_history_per_playlist_empty_initially(client):
    client.post("/playlists", json={"name": "History PL", "url": "https://music.apple.com/x"})
    resp = client.get("/sync-history/History PL")
    assert resp.status_code == 200
    assert resp.json() == []
    client.delete("/playlists/History PL")


def test_sync_records_run_on_success(client, monkeypatch):
    from alac_rip import sync as sync_mod
    from alac_rip.sync import SyncResult

    client.post("/playlists", json={"name": "History Test", "url": "https://music.apple.com/fake"})
    _make_staging_file("History Test")

    monkeypatch.setattr(
        sync_mod.SyncEngine,
        "sync",
        lambda self, url: SyncResult(new_count=4, skipped_count=1, error_count=0),
    )

    with client.stream("GET", "/sync/History Test") as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                event = json.loads(line[5:].strip())
                if event["status"] != "running":
                    break

    resp = client.get("/sync-history/History Test")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "success"
    assert runs[0]["new_count"] == 4
    assert runs[0]["skipped_count"] == 1
    assert runs[0]["playlist_name"] == "History Test"

    client.delete("/playlists/History Test")


def test_sync_records_run_on_error(client, monkeypatch):
    from alac_rip import sync as sync_mod

    client.post("/playlists", json={"name": "Error Hist", "url": "https://music.apple.com/fake"})
    _make_staging_file("Error Hist")

    def _raise(self, url):
        raise RuntimeError("downstream tool failed")

    monkeypatch.setattr(sync_mod.SyncEngine, "sync", _raise)

    with client.stream("GET", "/sync/Error Hist") as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                event = json.loads(line[5:].strip())
                if event["status"] != "running":
                    break

    resp = client.get("/sync-history/Error Hist")
    runs = resp.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert "downstream tool failed" in runs[0]["error_message"]

    client.delete("/playlists/Error Hist")


def test_sync_history_global_aggregates_playlists(client, monkeypatch):
    from alac_rip import sync as sync_mod
    from alac_rip.sync import SyncResult

    for name in ("Global A", "Global B"):
        client.post("/playlists", json={"name": name, "url": "https://music.apple.com/fake"})
        _make_staging_file(name)

    monkeypatch.setattr(
        sync_mod.SyncEngine,
        "sync",
        lambda self, url: SyncResult(new_count=1, skipped_count=0, error_count=0),
    )

    for name in ("Global A", "Global B"):
        with client.stream("GET", f"/sync/{name}") as r:
            for line in r.iter_lines():
                if line.startswith("data:"):
                    event = json.loads(line[5:].strip())
                    if event["status"] != "running":
                        break

    resp = client.get("/sync-history")
    names = {r["playlist_name"] for r in resp.json()}
    assert "Global A" in names
    assert "Global B" in names

    for name in ("Global A", "Global B"):
        client.delete(f"/playlists/{name}")


def test_put_config_roundtrip(client):
    resp = client.put("/config", json={"github_remote": "git@github.com:user/repo.git"})
    assert resp.status_code == 200

    resp = client.get("/config")
    assert resp.status_code == 200
    assert resp.json().get("github_remote") == "git@github.com:user/repo.git"


def test_download_one_off_requires_wrapper(client):
    resp = client.get("/download/one-off?url=https://music.apple.com/album/test&format=ALAC")
    assert resp.status_code == 409
    assert "Wrapper" in resp.json()["detail"]


def test_download_one_off_requires_url(client, monkeypatch):
    import alac_rip.server as server_mod
    monkeypatch.setattr(server_mod, "wrapper_running", True)
    resp = client.get("/download/one-off?url=&format=ALAC")
    assert resp.status_code == 400


def test_download_one_off_rejects_concurrent(client, monkeypatch):
    import alac_rip.server as server_mod
    monkeypatch.setattr(server_mod, "wrapper_running", True)
    monkeypatch.setattr(server_mod, "download_running", True)
    resp = client.get("/download/one-off?url=https://music.apple.com/album/test&format=ALAC")
    assert resp.status_code == 409
    assert "already in progress" in resp.json()["detail"]
