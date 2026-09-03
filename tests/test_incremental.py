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


def test_manifest_processing_updates_am_ids(state):
    """After SyncEngine runs, manifest entries update am_track_id in DB."""
    staging_dir = Path("/tmp/fake-staging")

    # Simulate state after SyncEngine has run — track exists in DB
    state.add_track(Track(
        track_id="Artist/Album/01 - Song.flac",
        title="Song", artist="Artist", album="Album",
        local_path="/music/artists/Artist/Album/01 - Song.flac",
        downloaded_at="2026-01-01T00:00:00",
    ))

    # Manifest from Go downloader (absolute staging path)
    manifest_entries = [
        {
            "am_track_id": "9876543210",
            "local_path": str(staging_dir / "Artist" / "Album" / "01 - Song.flac"),
        }
    ]

    # Derive track_id from manifest entry (same logic as server.py)
    for entry in manifest_entries:
        rel = Path(entry["local_path"]).relative_to(staging_dir)
        track_id = str(rel.with_suffix(".flac"))
        state.update_track_am_id(track_id, entry["am_track_id"])

    import sqlite3
    with sqlite3.connect(state.db_path) as conn:
        row = conn.execute(
            "SELECT am_track_id FROM tracks WHERE track_id = ?",
            ("Artist/Album/01 - Song.flac",)
        ).fetchone()
    assert row[0] == "9876543210"


def test_manifest_processing_handles_m4a_source(state):
    """Manifest entry with .m4a extension normalises to .flac track_id."""
    staging_dir = Path("/tmp/fake-staging2")

    state.add_track(Track(
        track_id="Artist/Album/01 - Song.flac",
        title="Song", artist="Artist", album="Album",
        local_path="/music/artists/Artist/Album/01 - Song.flac",
        downloaded_at="2026-01-01T00:00:00",
    ))

    # Go downloader produces .m4a before FLAC conversion
    entry_path = str(staging_dir / "Artist" / "Album" / "01 - Song.m4a")
    rel = Path(entry_path).relative_to(staging_dir)
    track_id = str(rel.with_suffix(".flac"))  # normalised to .flac
    state.update_track_am_id(track_id, "1111111111")

    import sqlite3
    with sqlite3.connect(state.db_path) as conn:
        row = conn.execute(
            "SELECT am_track_id FROM tracks WHERE track_id = ?",
            ("Artist/Album/01 - Song.flac",)
        ).fetchone()
    assert row[0] == "1111111111"


def test_get_playlist_tracks_without_am_id_returns_only_null(tmp_path):
    state = StateManager(tmp_path / "test.db")
    state.add_playlist("My PL", "https://example.com")
    state.add_track(Track(
        track_id="a/track.flac", title="Song A", artist="Artist",
        album="Album", local_path="/music/a.flac", downloaded_at="2026-01-01",
    ))
    state.add_track(Track(
        track_id="b/track.flac", title="Song B", artist="Artist",
        album="Album", local_path="/music/b.flac", downloaded_at="2026-01-01",
    ))
    state.add_track_to_playlist("My PL", "a/track.flac")
    state.add_track_to_playlist("My PL", "b/track.flac")
    state.update_track_am_id("a/track.flac", "am-111")  # has AM ID

    result = state.get_playlist_tracks_without_am_id("My PL")

    assert len(result) == 1
    assert result[0].track_id == "b/track.flac"


def test_get_playlist_tracks_without_am_id_empty_when_all_matched(tmp_path):
    state = StateManager(tmp_path / "test.db")
    state.add_playlist("My PL", "https://example.com")
    state.add_track(Track(
        track_id="a/track.flac", title="Song A", artist="Artist",
        album="Album", local_path="/music/a.flac", downloaded_at="2026-01-01",
    ))
    state.add_track_to_playlist("My PL", "a/track.flac")
    state.update_track_am_id("a/track.flac", "am-111")

    result = state.get_playlist_tracks_without_am_id("My PL")

    assert result == []


def test_retroactive_matching_populates_am_id(tmp_path):
    """Pre-flight with an existing DB track (null AM ID) matches it by title/artist."""
    from alac_rip.server import _normalize

    state = StateManager(tmp_path / "test.db")
    state.add_playlist("My PL", "https://example.com")
    state.add_track(Track(
        track_id="Artist/Album/01 - Song.flac", title="Song", artist="Artist",
        album="Album", local_path="/music/song.flac", downloaded_at="2026-01-01",
    ))
    state.add_track_to_playlist("My PL", "Artist/Album/01 - Song.flac")

    am_tracks = [{"id": "am-999", "title": "Song", "artist": "Artist"}]
    unmatched = state.get_playlist_tracks_without_am_id("My PL")
    am_by_key = {
        (_normalize(t["title"]), _normalize(t["artist"])): t["id"]
        for t in am_tracks
    }
    matched_count = 0
    for db_track in unmatched:
        key = (_normalize(db_track.title), _normalize(db_track.artist))
        if key in am_by_key:
            state.update_track_am_id(db_track.track_id, am_by_key[key])
            matched_count += 1

    owned = state.get_playlist_am_ids("My PL")
    assert "am-999" in owned
    assert matched_count == 1


def test_normalize_strips_punctuation_and_lowercases():
    from alac_rip.server import _normalize
    assert _normalize("Don't Stop Me Now!") == "dont stop me now"
    assert _normalize("  Bohemian  Rhapsody  ") == "bohemian rhapsody"
    assert _normalize("SONG (feat. Artist)") == "song feat artist"


def test_retroactive_matching_no_false_positives(tmp_path):
    """A track with a different artist should not match."""
    from alac_rip.server import _normalize

    state = StateManager(tmp_path / "test.db")
    state.add_playlist("My PL", "https://example.com")
    state.add_track(Track(
        track_id="Artist/Album/01 - Song.flac", title="Song", artist="Artist A",
        album="Album", local_path="/music/song.flac", downloaded_at="2026-01-01",
    ))
    state.add_track_to_playlist("My PL", "Artist/Album/01 - Song.flac")

    am_tracks = [{"id": "am-999", "title": "Song", "artist": "Artist B"}]
    unmatched = state.get_playlist_tracks_without_am_id("My PL")
    am_by_key = {
        (_normalize(t["title"]), _normalize(t["artist"])): t["id"]
        for t in am_tracks
    }
    for db_track in unmatched:
        key = (_normalize(db_track.title), _normalize(db_track.artist))
        if key in am_by_key:
            state.update_track_am_id(db_track.track_id, am_by_key[key])

    owned = state.get_playlist_am_ids("My PL")
    assert "am-999" not in owned


def test_streaming_graveyard_records_and_retrieves_delisted_tracks(state):
    state.add_playlist("Oldies", "https://music.apple.com/us/playlist/oldies/pl.123")
    _add_track(state, "Artist/Album/01 - Classic.flac", "am-100")
    state.add_track_to_playlist("Oldies", "Artist/Album/01 - Classic.flac")

    # Record delisted
    state.record_delisted_track("Oldies", "Artist/Album/01 - Classic.flac", "2026-08-16T12:00:00")
    delisted = state.get_delisted_tracks("Oldies")

    assert len(delisted) == 1
    assert delisted[0]["track_id"] == "Artist/Album/01 - Classic.flac"
    assert delisted[0]["playlist_name"] == "Oldies"
    assert delisted[0]["title"] == "Title"

    # Re-adding clears delisted
    state.clear_delisted_track("Oldies", "Artist/Album/01 - Classic.flac")
    assert state.get_delisted_tracks("Oldies") == []

