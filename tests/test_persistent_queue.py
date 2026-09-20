import pytest
from pathlib import Path
from alac_rip.state import StateManager


@pytest.fixture
def state(tmp_path: Path) -> StateManager:
    return StateManager(tmp_path / "test.db")


def test_enqueue_and_get_pending(state: StateManager):
    job_id = state.enqueue_download_job(
        url="https://music.apple.com/us/album/test/123",
        title="Test Album",
        artist="Test Artist",
        album="Test Album",
        format="ALAC",
        total_tracks=10,
    )
    assert job_id == 1

    pending = state.get_next_pending_job()
    assert pending is not None
    assert pending["id"] == 1
    assert pending["title"] == "Test Album"
    assert pending["status"] == "pending"
    assert pending["total_tracks"] == 10


def test_bulk_enqueue_discography(state: StateManager):
    jobs = [
        {
            "batch_id": "batch-1",
            "batch_title": "RADWIMPS — Discography Batch",
            "url": f"https://music.apple.com/us/album/{i}",
            "title": f"Album {i}",
            "artist": "RADWIMPS",
            "album": f"Album {i}",
            "total_tracks": 12,
        }
        for i in range(1, 5)
    ]
    ids = state.bulk_enqueue_download_jobs(jobs)
    assert len(ids) == 4

    summary = state.get_queue_summary()
    assert summary["counts"]["pending"] == 4
    assert len(summary["pending"]) == 4
    assert summary["pending"][0]["title"] == "Album 1"
    assert summary["pending"][3]["title"] == "Album 4"


def test_update_status_and_summary(state: StateManager):
    job_id = state.enqueue_download_job(
        url="https://music.apple.com/us/album/test/123",
        title="Active Album",
    )
    # Start job
    assert state.update_job_status(job_id, "running", started_at="2026-08-23T12:00:00")

    summary = state.get_queue_summary()
    assert summary["active"] is not None
    assert summary["active"]["id"] == job_id
    assert summary["active"]["status"] == "running"
    assert summary["counts"]["running"] == 1
    assert summary["counts"]["pending"] == 0

    # Finish job
    assert state.update_job_status(
        job_id,
        "done",
        completed_at="2026-08-23T12:01:00",
        new_tracks=10,
        skipped_tracks=2,
        error_count=0,
        log_path="/path/to/log.txt",
    )

    summary = state.get_queue_summary()
    assert summary["active"] is None
    assert summary["counts"]["done"] == 1
    assert len(summary["completed"]) == 1
    assert summary["completed"][0]["new_tracks"] == 10


def test_cancel_and_retry(state: StateManager):
    j1 = state.enqueue_download_job(url="url1", title="Job 1")
    j2 = state.enqueue_download_job(url="url2", title="Job 2")

    # Cancel j1
    assert state.cancel_queue_job(j1)
    summary = state.get_queue_summary()
    assert summary["counts"]["cancelled"] == 1
    assert summary["counts"]["pending"] == 1

    # Retry j1
    assert state.retry_failed_jobs([j1]) == 1
    summary = state.get_queue_summary()
    assert summary["counts"]["pending"] == 2


def test_reset_interrupted_jobs_on_crash_recovery(state: StateManager):
    j1 = state.enqueue_download_job(url="url1", title="Interrupted Job")
    state.update_job_status(j1, "running", started_at="2026-08-23T12:00:00")

    # Server restarts / recovers
    recovered = state.reset_interrupted_jobs()
    assert recovered == 1

    job = state.get_queue_job(j1)
    assert job["status"] == "pending"
    assert job["started_at"] is None


def test_reorder_jobs(state: StateManager):
    j1 = state.enqueue_download_job(url="url1", title="Job 1")
    j2 = state.enqueue_download_job(url="url2", title="Job 2")

    state.reorder_queue_job(j2, 0)
    next_job = state.get_next_pending_job()
    assert next_job["id"] == j2

from fastapi.testclient import TestClient
import alac_rip.server as srv


def test_api_queue_lifecycle(tmp_path: Path, monkeypatch):
    test_state = StateManager(tmp_path / "server_test.db")
    monkeypatch.setattr(srv, "_run_job", lambda job: None)
    monkeypatch.setattr(srv, "state", test_state)
    client = TestClient(srv.app)

    # 1. Add batch to queue
    resp = client.post("/api/v1/queue/add", json={
        "items": [
            {
                "url": "https://music.apple.com/us/album/test-album-1/111",
                "title": "Album One",
                "artist": "Artist X",
                "total_tracks": 10
            },
            {
                "url": "https://music.apple.com/us/album/test-album-2/222",
                "title": "Album Two",
                "artist": "Artist X",
                "total_tracks": 12
            }
        ],
        "format": "ALAC",
        "batch_title": "Artist X Batch"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["queued"] == 2
    assert len(data["job_ids"]) == 2

    # 2. Get queue
    get_resp = client.get("/api/v1/queue")
    assert get_resp.status_code == 200
    q_data = get_resp.json()
    assert q_data["counts"]["total"] >= 2

    # 3. Cancel second job
    cancel_resp = client.post("/api/v1/queue/cancel", json={"job_id": data["job_ids"][1]})
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["cancelled"] in (0, 1)

    # 4. Retry jobs
    retry_resp = client.post("/api/v1/queue/retry", json={"job_ids": [data["job_ids"][1]]})
    assert retry_resp.status_code == 200
    assert retry_resp.json()["retried"] in (0, 1)


def test_universal_preflight_album_short_circuit(tmp_path: Path, monkeypatch):
    from alac_rip.state import Track
    from alac_rip.config import Config
    import queue

    test_state = StateManager(tmp_path / "preflight_test.db")
    music_dir = tmp_path / "music"
    state_dir = tmp_path / "state"
    alac_rip_dir = tmp_path / "tools"
    music_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    alac_rip_dir.mkdir(parents=True)

    test_state.add_track(Track(
        track_id="album_track_1.flac",
        title="Song One",
        artist="Artist A",
        album="Album Alpha",
        local_path=str(music_dir / "Song1.flac"),
        downloaded_at="2026-08-23T12:00:00",
        am_track_id="101",
    ))
    test_state.add_track(Track(
        track_id="album_track_2.flac",
        title="Song Two",
        artist="Artist A",
        album="Album Alpha",
        local_path=str(music_dir / "Song2.flac"),
        downloaded_at="2026-08-23T12:00:00",
        am_track_id="102",
    ))

    db_job_id = test_state.enqueue_download_job(
        url="https://music.apple.com/us/album/album-alpha/999",
        title="Album Alpha",
        artist="Artist A",
        album="Album Alpha",
    )

    monkeypatch.setattr(srv, "state", test_state)
    monkeypatch.setattr(srv, "cfg", Config(music_dir=music_dir, state_dir=state_dir, alac_rip_dir=alac_rip_dir))
    monkeypatch.setattr(srv.am_api, "fetch_bearer_token", lambda: "fake-bearer")
    monkeypatch.setattr(srv.am_api, "fetch_album_details", lambda url, bearer, storefront="us": {
        "id": "999",
        "title": "Album Alpha",
        "artist": "Artist A",
        "tracks": [
            {"id": "101", "title": "Song One", "artist": "Artist A", "album": "Album Alpha"},
            {"id": "102", "title": "Song Two", "artist": "Artist A", "album": "Album Alpha"},
        ]
    })

    # If downloader is launched, raise exception
    def forbidden_popen(*args, **kwargs):
        raise AssertionError("Downloader Popen should never be launched when all tracks already exist locally!")

    monkeypatch.setattr(srv.subprocess, "Popen", forbidden_popen)

    job = {
        "id": "job-short-circuit-1",
        "db_id": db_job_id,
        "type": "one-off",
        "url": "https://music.apple.com/us/album/album-alpha/999",
        "format": "ALAC",
        "playlist_name": None,
        "log_q": queue.Queue(),
    }

    srv._run_job(job)

    db_job = test_state.get_queue_job(db_job_id)
    assert db_job["status"] == "done"
    assert db_job["new_tracks"] == 0
    assert db_job["skipped_tracks"] == 2
    assert db_job["error_count"] == 0


def test_queue_autopause_and_job_preservation_on_auth_failure(tmp_path: Path, monkeypatch):
    from alac_rip.config import Config
    import queue

    test_state = StateManager(tmp_path / "autopause_test.db")
    music_dir = tmp_path / "music"
    state_dir = tmp_path / "state"
    alac_rip_dir = tmp_path / "tools"
    music_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    alac_rip_dir.mkdir(parents=True)

    monkeypatch.setattr(srv, "wrapper_running", False)
    monkeypatch.setattr(srv, "state", test_state)
    monkeypatch.setattr(srv, "cfg", Config(music_dir=music_dir, state_dir=state_dir, alac_rip_dir=alac_rip_dir))
    monkeypatch.setattr(srv, "_is_wrapper_port_alive", lambda: False)

    j1 = test_state.enqueue_download_job(
        url="https://music.apple.com/us/album/album-one/111",
        title="Album One",
    )
    j2 = test_state.enqueue_download_job(
        url="https://music.apple.com/us/album/album-two/222",
        title="Album Two",
    )

    job = {
        "id": "job-fail-1",
        "db_id": j1,
        "type": "one-off",
        "url": "https://music.apple.com/us/album/album-one/111",
        "format": "ALAC",
        "playlist_name": None,
        "log_q": queue.Queue(),
    }

    srv._run_job(job)

    # Wrapper running should be False
    assert srv.wrapper_running is False

    # Failed job should be reset to 'pending' to be picked up after re-auth
    job1_row = test_state.get_queue_job(j1)
    assert job1_row["status"] == "pending"
    assert "offline" in (job1_row["error_message"] or "").lower() or "wrapper" in (job1_row["error_message"] or "").lower()

    # Second job should still be 'pending'
    job2_row = test_state.get_queue_job(j2)
    assert job2_row["status"] == "pending"

