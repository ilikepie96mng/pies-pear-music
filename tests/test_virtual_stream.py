from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from alac_rip import server
from alac_rip.config import Config
from alac_rip.state import StateManager, Track


@pytest.fixture
def client(tmp_path, monkeypatch):
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    cfg = Config(
        music_dir=music_dir,
        state_dir=state_dir,
        alac_rip_dir=tmp_path,
    )
    state = StateManager(state_dir / "downloaded.db")

    monkeypatch.setattr(server, "cfg", cfg)
    monkeypatch.setattr(server, "state", state)

    return TestClient(server.app), music_dir, state


def test_stream_full_file(client):
    test_client, music_dir, state = client
    audio_file = music_dir / "test.flac"
    audio_file.write_bytes(b"FLAC_TEST_AUDIO_STREAM_DATA_" * 10)

    track = Track(
        track_id="12345",
        title="Stream Song",
        artist="Stream Artist",
        album="Stream Album",
        local_path=str(audio_file),
        downloaded_at="2026-08-16T12:00:00",
        artwork_url=None,
    )
    state.add_track(track)

    resp = test_client.get("/api/v1/stream/12345")
    assert resp.status_code == 200
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.headers["content-type"] == "audio/flac"
    assert resp.content == b"FLAC_TEST_AUDIO_STREAM_DATA_" * 10


def test_stream_range_request(client):
    test_client, music_dir, state = client
    audio_file = music_dir / "test.m4a"
    content = b"0123456789ABCDEF" * 100
    audio_file.write_bytes(content)

    track = Track(
        track_id="range-track",
        title="Range Song",
        artist="Range Artist",
        album="Range Album",
        local_path=str(audio_file),
        downloaded_at="2026-08-16T12:00:00",
        artwork_url=None,
    )
    state.add_track(track)

    headers = {"Range": "bytes=10-29"}
    resp = test_client.get("/api/v1/stream/range-track", headers=headers)
    assert resp.status_code == 206
    assert resp.headers["content-range"] == f"bytes 10-29/{len(content)}"
    assert resp.headers["content-length"] == "20"
    assert resp.content == content[10:30]


def test_stream_security_boundary(client, tmp_path):
    test_client, music_dir, state = client
    outside_file = tmp_path / "secret.flac"
    outside_file.write_bytes(b"SECRET_DATA")

    track = Track(
        track_id="escaped-track",
        title="Escaped Song",
        artist="Escaped Artist",
        album="Escaped Album",
        local_path=str(outside_file),
        downloaded_at="2026-08-16T12:00:00",
        artwork_url=None,
    )
    state.add_track(track)

    resp = test_client.get("/api/v1/stream/escaped-track")
    assert resp.status_code in (403, 404)
