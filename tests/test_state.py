from datetime import datetime
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
