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
        f"state_dir: {tmp_path}/state\n"
    )
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", cfg_file)
    with TestClient(app) as c:
        yield c


def _fake_run_job_success(new=2, skipped=1, errors=0):
    """Returns a _run_job replacement that emits done immediately and records sync run."""
    from datetime import datetime
    def _run(job):
        import alac_rip.server as _srv
        job["log_q"].put({"status": "running", "phase": "downloading",
                           "message": "fake dl", "log_path": ""})
        job["log_q"].put({"status": "done", "new": new, "skipped": skipped,
                           "errors": errors, "log_path": ""})
        if job.get("playlist_name") and _srv.state:
            now = datetime.now().isoformat()
            _srv.state.record_sync_run(
                job["playlist_name"], now, now, "success",
                new, skipped, errors, "",
            )
            _srv.state.update_playlist_synced(job["playlist_name"])
    return _run


def _fake_run_job_error(message="downstream tool failed"):
    """Returns a _run_job replacement that emits an error and records it."""
    from datetime import datetime
    def _run(job):
        import alac_rip.server as _srv
        job["log_q"].put({"status": "error", "message": message, "log_path": ""})
        if job.get("playlist_name") and _srv.state:
            now = datetime.now().isoformat()
            _srv.state.record_sync_run(
                job["playlist_name"], now, now, "error",
                0, 0, 0, "", message,
            )
    return _run


def _drain_sse(r) -> list[dict]:
    """Consume SSE response lines until done/error event, return all parsed events."""
    events = []
    for line in r.iter_lines():
        if line.startswith("data:"):
            e = json.loads(line[5:].strip())
            events.append(e)
            if e.get("status") in ("done", "error"):
                break
    return events


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
    client.post("/playlists", json={"name": "SSE Test", "url": "https://music.apple.com/fake"})
    monkeypatch.setattr(server_mod, "wrapper_running", True)
    monkeypatch.setattr(server_mod, "_run_job", _fake_run_job_success(new=3, skipped=1))

    with client.stream("GET", "/sync/SSE Test") as r:
        assert r.status_code == 200
        events = _drain_sse(r)

    done = next(e for e in events if e["status"] == "done")
    assert done["new"] == 3
    assert done["skipped"] == 1
    assert done["errors"] == 0
    client.delete("/playlists/SSE Test")


def test_library_returns_dict(client):
    resp = client.get("/library")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    for tracks in data.values():
        assert isinstance(tracks, list)


def test_track_art_unknown_path_is_forbidden(client):
    resp = client.get("/track-art", params={"path": "/tmp/nonexistent.m4a"})
    assert resp.status_code == 403


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
    for expected in ("FFmpeg", "Config file", "Music directory", "State directory"):
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
    client.post("/playlists", json={"name": "Delete Me", "url": "https://music.apple.com/fake"})
    monkeypatch.setattr(server_mod, "wrapper_running", True)
    monkeypatch.setattr(server_mod, "_run_job", _fake_run_job_success(new=1))

    with client.stream("GET", "/sync/Delete Me") as r:
        _drain_sse(r)

    assert len(client.get("/sync-history/Delete Me").json()) == 1
    client.delete("/playlists/Delete Me")

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
    client.post("/playlists", json={"name": "History Test", "url": "https://music.apple.com/fake"})
    monkeypatch.setattr(server_mod, "wrapper_running", True)
    monkeypatch.setattr(server_mod, "_run_job", _fake_run_job_success(new=4, skipped=1))

    with client.stream("GET", "/sync/History Test") as r:
        _drain_sse(r)

    runs = client.get("/sync-history/History Test").json()
    assert len(runs) == 1
    assert runs[0]["status"] == "success"
    assert runs[0]["new_count"] == 4
    assert runs[0]["skipped_count"] == 1
    client.delete("/playlists/History Test")


def test_sync_records_run_on_error(client, monkeypatch):
    client.post("/playlists", json={"name": "Error Hist", "url": "https://music.apple.com/fake"})
    monkeypatch.setattr(server_mod, "wrapper_running", True)
    monkeypatch.setattr(server_mod, "_run_job", _fake_run_job_error("downstream tool failed"))

    with client.stream("GET", "/sync/Error Hist") as r:
        _drain_sse(r)

    runs = client.get("/sync-history/Error Hist").json()
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert "downstream tool failed" in runs[0]["error_message"]
    client.delete("/playlists/Error Hist")


def test_sync_history_global_aggregates_playlists(client, monkeypatch):
    for name in ("Global A", "Global B"):
        client.post("/playlists", json={"name": name, "url": "https://music.apple.com/fake"})
    monkeypatch.setattr(server_mod, "wrapper_running", True)
    monkeypatch.setattr(server_mod, "_run_job", _fake_run_job_success(new=1))

    for name in ("Global A", "Global B"):
        with client.stream("GET", f"/sync/{name}") as r:
            _drain_sse(r)

    names = {r["playlist_name"] for r in client.get("/sync-history").json()}
    assert "Global A" in names
    assert "Global B" in names
    for name in ("Global A", "Global B"):
        client.delete(f"/playlists/{name}")


def test_put_config_roundtrip(client):
    resp = client.put("/config", json={"alac_rip_dir": "/opt/pies-tools"})
    assert resp.status_code == 200

    resp = client.get("/config")
    assert resp.status_code == 200
    assert resp.json().get("alac_rip_dir") == "/opt/pies-tools"


def test_download_one_off_requires_wrapper(client):
    resp = client.get("/download/one-off?url=https://music.apple.com/album/test&format=ALAC")
    assert resp.status_code == 409
    assert "Wrapper" in resp.json()["detail"]


def test_sync_requires_wrapper(client):
    client.post("/playlists", json={"name": "NW Test", "url": "https://music.apple.com/x"})
    resp = client.get("/sync/NW Test")
    assert resp.status_code == 409
    assert "Wrapper" in resp.json()["detail"]
    client.delete("/playlists/NW Test")


def test_sync_queue_empty_initially(client):
    resp = client.get("/sync/queue")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is None
    assert data["pending"] == []


def test_download_one_off_requires_url(client, monkeypatch):
    monkeypatch.setattr(server_mod, "wrapper_running", True)
    resp = client.get("/download/one-off?url=&format=ALAC")
    assert resp.status_code == 400


def test_sync_duplicate_playlist_rejected(client, monkeypatch):
    import threading
    client.post("/playlists", json={"name": "Dup PL", "url": "https://music.apple.com/x"})
    monkeypatch.setattr(server_mod, "wrapper_running", True)

    # Simulate a job already active for this playlist
    fake_job = {"id": "fake", "type": "playlist", "playlist_name": "Dup PL",
                "log_q": __import__("queue").Queue(), "started": threading.Event()}
    monkeypatch.setattr(server_mod, "active_job", fake_job)

    resp = client.get("/sync/Dup PL")
    assert resp.status_code == 409
    assert "already queued" in resp.json()["detail"]

    monkeypatch.setattr(server_mod, "active_job", None)
    client.delete("/playlists/Dup PL")


def test_streaming_graveyard_endpoint(client):
    resp = client.get("/streaming-graveyard")
    assert resp.status_code == 200
    data = resp.json()
    assert "tracks" in data
    assert "count" in data
    assert isinstance(data["tracks"], list)


def test_track_lyrics_not_found(client):
    resp = client.get("/tracks/nonexistent_999999/lyrics")
    assert resp.status_code == 404


def test_track_lyrics_with_lrc(client, tmp_path, monkeypatch):
    from alac_rip.state import Track
    # Create test track and .lrc file in music_dir
    music_dir = server_mod.cfg.music_dir
    track_file = music_dir / "Artist" / "Album" / "01 Track.flac"
    track_file.parent.mkdir(parents=True, exist_ok=True)
    track_file.write_bytes(b"dummy flac content")
    lrc_file = track_file.with_suffix(".lrc")
    lrc_content = "[00:12.34] Hello world\n[00:15.50] Second line\n"
    lrc_file.write_text(lrc_content, encoding="utf-8")

    server_mod.state.add_track(Track(
        track_id="lyrics_test_123",
        title="Hello Track",
        artist="Artist",
        album="Album",
        local_path=str(track_file),
        downloaded_at="2026-08-16T12:00:00",
        artwork_url=None,
    ))

    resp = client.get("/tracks/lyrics_test_123/lyrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["track_id"] == "lyrics_test_123"
    assert data["title"] == "Hello Track"
    assert data["synced"] is True
    assert data["source"] == "lrc"
    assert len(data["lines"]) == 2
    assert data["lines"][0]["text"] == "Hello world"
    assert data["lines"][0]["time_ms"] == 12340
    assert data["lines"][1]["text"] == "Second line"


def test_integrations_health(client):
    resp = client.get("/system/integrations-health")
    assert resp.status_code == 200
    data = resp.json()
    assert "gemini" in data
    assert "lastfm" in data
    assert "jellyfin" in data
    assert "navidrome" in data
    assert "strawberry" in data


def test_playlist_duplicates_and_deduplicate(client):
    from alac_rip.state import Track
    server_mod.state.add_track(Track("d1", "Duplicate Song", "Band", "Album 1", "/fake/1.flac", "2026-08-17T00:00:00"))
    server_mod.state.add_track(Track("d2", "Duplicate Song", "Band", "Album 2", "/fake/2.flac", "2026-08-17T00:00:00"))
    server_mod.state.add_track(Track("u1", "Unique Song", "Band", "Album 1", "/fake/3.flac", "2026-08-17T00:00:00"))

    client.post("/playlists", json={"name": "Dedup Test", "url": "https://music.apple.com/us/playlist/dedup/pl.999"})
    server_mod.state.add_track_to_playlist("Dedup Test", "d1")
    server_mod.state.add_track_to_playlist("Dedup Test", "d2")
    server_mod.state.add_track_to_playlist("Dedup Test", "u1")

    # Check duplicates endpoint
    resp = client.get("/playlists/Dedup Test/duplicates")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["duplicates"][0]["title"] == "Duplicate Song"
    assert data["duplicates"][0]["count"] == 2

    # Deduplicate endpoint
    resp_dedup = client.post("/playlists/Dedup Test/deduplicate")
    assert resp_dedup.status_code == 200
    dedup_data = resp_dedup.json()
    assert dedup_data["status"] == "ok"
    assert dedup_data["duplicates_found"] == 1
    assert dedup_data["removed_count"] == 1

    # Check that duplicates are now 0
    resp_after = client.get("/playlists/Dedup Test/duplicates")
    assert resp_after.json()["count"] == 0


def test_post_gemini_curate_endpoint(client, monkeypatch):
    from alac_rip import gemini_ai
    monkeypatch.setattr(
        gemini_ai,
        "generate_smart_playlist",
        lambda **kwargs: {
            "playlist_title": "Synthwave Sunset",
            "description": "Retro drive",
            "vibe_tags": ["synthwave"],
            "tracks": [{"title": "Nightcall", "artist": "Kavinsky", "album": "OutRun", "rationale": "Classic"}]
        }
    )
    # Set mock api key on config
    server_mod.cfg.gemini_api_key = "test-key"

    resp = client.post("/gemini/curate", json={"prompt": "retro synthwave", "track_count": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["playlist_title"] == "Synthwave Sunset"
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["title"] == "Nightcall"



