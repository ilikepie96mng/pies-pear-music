import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock
import pytest
from alac_rip.state import StateManager, Track


@pytest.fixture
def state(tmp_path):
    return StateManager(tmp_path / "test.db")


def _add_track(state, track_id, am_track_id=None):
    state.add_track(Track(
        track_id=track_id,
        title="Title",
        artist="Artist",
        album="Album",
        local_path=f"/music/{track_id}",
        downloaded_at=datetime.now().isoformat(),
    ))
    if am_track_id:
        state.update_track_am_id(track_id, am_track_id)


def test_am_track_id_column_exists(state):
    # DB should have am_track_id column after migration
    import sqlite3
    with sqlite3.connect(state.db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tracks)")}
    assert "am_track_id" in cols


def test_update_track_am_id_stores_value(state):
    state.add_playlist("My Playlist", "https://music.apple.com/us/playlist/test/pl.xxx")
    _add_track(state, "Artist/Album/01 - Song.flac")
    state.add_track_to_playlist("My Playlist", "Artist/Album/01 - Song.flac")
    state.update_track_am_id("Artist/Album/01 - Song.flac", "1234567890")
    ids = state.get_playlist_am_ids("My Playlist")
    assert ids == {"1234567890"}


def test_get_playlist_am_ids_returns_owned_ids(state):
    state.add_playlist("My Playlist", "https://music.apple.com/us/playlist/test/pl.xxx")
    _add_track(state, "Artist/Album/01 - Song.flac", "111")
    _add_track(state, "Artist/Album/02 - Song.flac", "222")
    state.add_track_to_playlist("My Playlist", "Artist/Album/01 - Song.flac")
    state.add_track_to_playlist("My Playlist", "Artist/Album/02 - Song.flac")

    ids = state.get_playlist_am_ids("My Playlist")
    assert ids == {"111", "222"}


def test_get_playlist_am_ids_excludes_null(state):
    state.add_playlist("My Playlist", "https://music.apple.com/us/playlist/test/pl.xxx")
    # Track with no AM ID (downloaded before incremental feature)
    _add_track(state, "Artist/Album/01 - Song.flac")
    state.add_track_to_playlist("My Playlist", "Artist/Album/01 - Song.flac")

    ids = state.get_playlist_am_ids("My Playlist")
    assert ids == set()


def test_get_playlist_am_ids_only_for_named_playlist(state):
    state.add_playlist("Playlist A", "https://music.apple.com/us/playlist/a/pl.aaa")
    state.add_playlist("Playlist B", "https://music.apple.com/us/playlist/b/pl.bbb")
    _add_track(state, "Artist/Album/01 - Song.flac", "111")
    _add_track(state, "Artist/Album/02 - Song.flac", "222")
    state.add_track_to_playlist("Playlist A", "Artist/Album/01 - Song.flac")
    state.add_track_to_playlist("Playlist B", "Artist/Album/02 - Song.flac")

    assert state.get_playlist_am_ids("Playlist A") == {"111"}
    assert state.get_playlist_am_ids("Playlist B") == {"222"}


def test_preflight_writes_skip_file(state):
    """Pre-flight diff produces skip.json with already-owned IDs."""
    state.add_playlist("Game OST", "https://music.apple.com/us/playlist/game-ost/pl.abc")
    state.add_track(Track(
        track_id="Artist/Album/01 - Song.flac",
        title="Song", artist="Artist", album="Album",
        local_path="/music/song.flac", downloaded_at="2026-01-01T00:00:00",
    ))
    state.update_track_am_id("Artist/Album/01 - Song.flac", "111")
    state.add_track_to_playlist("Game OST", "Artist/Album/01 - Song.flac")

    # AM playlist has track 111 (owned) and 222 (new)
    am_ids = ["111", "222"]
    owned = state.get_playlist_am_ids("Game OST")
    skip_ids = owned & set(am_ids)
    new_ids = set(am_ids) - owned

    assert skip_ids == {"111"}
    assert new_ids == {"222"}

    with tempfile.TemporaryDirectory() as tmp:
        skip_file = Path(tmp) / "skip.json"
        skip_file.write_text(json.dumps({"skip_ids": list(skip_ids)}))
        data = json.loads(skip_file.read_text())
        assert data["skip_ids"] == ["111"]
