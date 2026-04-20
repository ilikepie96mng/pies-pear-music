from datetime import datetime
import sqlite3
from alac_rip.state import StateManager, Track, Playlist


def test_new_track_is_not_downloaded(state):
    assert state.is_downloaded("track-abc-123") is False


def test_add_track_marks_it_downloaded(state):
    track = Track(
        track_id="track-abc-123",
        title="Bohemian Rhapsody",
        artist="Queen",
        album="A Night at the Opera",
        local_path="/Music/Queen/A Night at the Opera/01 - Bohemian Rhapsody.m4a",
        downloaded_at=datetime.now().isoformat(),
    )
    state.add_track(track)
    assert state.is_downloaded("track-abc-123") is True


def test_add_track_idempotent(state):
    track = Track(
        track_id="track-abc-123",
        title="Bohemian Rhapsody",
        artist="Queen",
        album="A Night at the Opera",
        local_path="/Music/Queen/A Night at the Opera/01 - Bohemian Rhapsody.m4a",
        downloaded_at=datetime.now().isoformat(),
    )
    state.add_track(track)
    state.add_track(track)  # second add should not raise
    assert state.is_downloaded("track-abc-123") is True


def test_add_playlist(state):
    state.add_playlist("My Mega Playlist", "https://music.apple.com/playlist/xyz")
    playlists = state.get_playlists()
    assert len(playlists) == 1
    assert playlists[0].name == "My Mega Playlist"
    assert playlists[0].url == "https://music.apple.com/playlist/xyz"
    assert playlists[0].last_synced is None


def test_add_playlist_idempotent(state):
    state.add_playlist("My Mega Playlist", "https://music.apple.com/playlist/xyz")
    state.add_playlist("My Mega Playlist", "https://music.apple.com/playlist/xyz")
    assert len(state.get_playlists()) == 1


def test_add_playlist_with_migrated_paused_column(tmp_path):
    db_path = tmp_path / "downloaded.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE playlists (
                name TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                last_synced TEXT,
                paused INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE tracks (
                track_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT NOT NULL,
                local_path TEXT NOT NULL,
                downloaded_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE playlist_tracks (
                playlist_name TEXT NOT NULL,
                track_id TEXT NOT NULL,
                PRIMARY KEY (playlist_name, track_id)
            )
            """
        )

    state = StateManager(db_path)
    state.add_playlist("Classic Rock", "https://music.apple.com/playlist/test")

    playlists = state.get_playlists()
    assert len(playlists) == 1
    assert playlists[0].name == "Classic Rock"
    assert playlists[0].paused is False


def test_update_playlist_synced(state):
    state.add_playlist("My Mega Playlist", "https://music.apple.com/playlist/xyz")
    state.update_playlist_synced("My Mega Playlist")
    playlists = state.get_playlists()
    assert playlists[0].last_synced is not None


def test_downloaded_count(state):
    assert state.get_downloaded_count() == 0
    for i in range(3):
        state.add_track(Track(
            track_id=f"track-{i}",
            title=f"Track {i}",
            artist="Artist",
            album="Album",
            local_path=f"/Music/track-{i}.m4a",
            downloaded_at=datetime.now().isoformat(),
        ))
    assert state.get_downloaded_count() == 3


def test_rename_playlist(state):
    state.add_playlist("Old Name", "https://music.apple.com/playlist/abc")
    state.add_track(Track(
        track_id="track-x1",
        title="Song",
        artist="Artist",
        album="Album",
        local_path="/Music/song.m4a",
        downloaded_at=datetime.now().isoformat(),
    ))
    state.add_track_to_playlist("Old Name", "track-x1")

    state.rename_playlist("Old Name", "New Name")

    playlists = state.get_playlists()
    names = [p.name for p in playlists]
    assert "New Name" in names
    assert "Old Name" not in names

    tracks = state.get_playlist_tracks("New Name")
    assert any(t.track_id == "track-x1" for t in tracks)


def test_set_playlist_paused(state):
    state.add_playlist("Toggle PL", "https://music.apple.com/playlist/toggle")

    playlists = state.get_playlists()
    assert playlists[0].paused is False

    state.set_playlist_paused("Toggle PL", True)
    playlists = state.get_playlists()
    assert playlists[0].paused is True

    state.set_playlist_paused("Toggle PL", False)
    playlists = state.get_playlists()
    assert playlists[0].paused is False
