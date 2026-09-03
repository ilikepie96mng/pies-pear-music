import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
import alac_rip.server as server_mod
from alac_rip.server import app
from alac_rip.lastfm_api import LastFmError


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


@pytest.fixture
def client_with_lastfm(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        f"music_dir: {tmp_path}/Music\n"
        f"state_dir: {tmp_path}/state\n"
        "lastfm_api_key: 'test-lfm-key'\n"
    )
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", cfg_file)
    with TestClient(app) as c:
        yield c


def _seed_tracks(state, tracks):
    """Insert tracks directly into DB for test setup."""
    import sqlite3
    with state._conn() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO tracks (track_id, title, artist, album, local_path, downloaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            tracks,
        )


def test_home_empty_library(client):
    r = client.get("/home")
    assert r.status_code == 200
    data = r.json()
    assert data["recent_tracks"] == []
    assert data["recommendations"] == []
    assert data["last_sync"] is None
    assert data["recommendations_available"] is False


def test_home_returns_recent_tracks(client):
    state = server_mod.state
    _seed_tracks(state, [
        ("t1", "Song A", "Artist X", "Album 1", "/music/a.m4a", "2026-05-01T10:00:00"),
        ("t2", "Song B", "Artist Y", "Album 2", "/music/b.m4a", "2026-05-02T10:00:00"),
    ])
    r = client.get("/home")
    assert r.status_code == 200
    tracks = r.json()["recent_tracks"]
    assert len(tracks) == 2
    assert tracks[0]["title"] == "Song B"  # most recent first
    assert tracks[1]["title"] == "Song A"


def test_home_recent_tracks_capped_at_5(client):
    state = server_mod.state
    _seed_tracks(state, [
        (f"t{i}", f"Song {i}", "Artist", "Album", f"/m/{i}.m4a", f"2026-05-0{i}T10:00:00")
        for i in range(1, 8)
    ])
    r = client.get("/home")
    assert len(r.json()["recent_tracks"]) == 5


def test_home_no_lastfm_key_recommendations_unavailable(client):
    r = client.get("/home")
    data = r.json()
    assert data["recommendations_available"] is False
    assert data["recommendations"] == []


def test_home_with_lastfm_key_recommendations_available(client_with_lastfm):
    state = server_mod.state
    _seed_tracks(state, [
        ("t1", "Song A", "C418", "OST", "/m/a.m4a", "2026-05-01T10:00:00"),
    ])
    similar = [{"name": "David Wise", "match": 0.87, "url": "https://www.last.fm/music/David+Wise"}]
    with patch("alac_rip.server.lastfm_api.get_similar_artists", return_value=similar):
        r = client_with_lastfm.get("/home")
    data = r.json()
    assert data["recommendations_available"] is True
    assert len(data["recommendations"]) == 1
    assert data["recommendations"][0]["artist"] == "David Wise"
    assert data["recommendations"][0]["similar_to"] == "C418"
    assert data["recommendations"][0]["match"] == 0.87


def test_home_filters_library_artists_from_recommendations(client_with_lastfm):
    state = server_mod.state
    _seed_tracks(state, [
        ("t1", "Song A", "C418", "OST", "/m/a.m4a", "2026-05-01T10:00:00"),
        ("t2", "Song B", "David Wise", "OST2", "/m/b.m4a", "2026-05-01T11:00:00"),
    ])
    similar = [
        {"name": "David Wise", "match": 0.87, "url": "https://last.fm/David+Wise"},
        {"name": "Jake Kaufman", "match": 0.72, "url": "https://last.fm/Jake+Kaufman"},
    ]
    with patch("alac_rip.server.lastfm_api.get_similar_artists", return_value=similar):
        r = client_with_lastfm.get("/home")
    recs = r.json()["recommendations"]
    names = [rec["artist"] for rec in recs]
    assert "David Wise" not in names  # already in library
    assert "Jake Kaufman" in names


def test_home_lastfm_failure_returns_empty_recommendations(client_with_lastfm):
    state = server_mod.state
    _seed_tracks(state, [
        ("t1", "Song A", "C418", "OST", "/m/a.m4a", "2026-05-01T10:00:00"),
    ])
    with patch("alac_rip.server.lastfm_api.get_similar_artists", side_effect=LastFmError("network")):
        r = client_with_lastfm.get("/home")
    data = r.json()
    assert data["recommendations_available"] is True
    assert data["recommendations"] == []


def test_home_last_sync_populated_after_sync_run(client):
    state = server_mod.state
    from datetime import datetime
    now = datetime.now().isoformat()
    state.add_playlist("Test PL", "https://music.apple.com/pl.test")
    state.record_sync_run("Test PL", now, now, "success", 3, 0, 0, "")
    r = client.get("/home")
    last_sync = r.json()["last_sync"]
    assert last_sync is not None
    assert last_sync["playlist_name"] == "Test PL"
    assert last_sync["new_tracks"] == 3
