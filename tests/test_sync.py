import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from alac_rip.state import StateManager, Track
from alac_rip.sync import SyncEngine


@pytest.fixture
def music_dir(tmp_path):
    d = tmp_path / "Music" / "Apple Music"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def downloads_dir(tmp_path):
    """Simulate the ./downloads/ dir the Go downloader produces."""
    d = tmp_path / "downloads"
    d.mkdir()
    return d


@pytest.fixture
def sync_state(tmp_path):
    return StateManager(tmp_path / "downloaded.db")


@pytest.fixture
def mock_downloader(downloads_dir):
    dl = MagicMock()
    dl.download_playlist.return_value = downloads_dir
    dl.start_wrapper = MagicMock()
    dl.stop_wrapper = MagicMock()
    return dl


def make_fake_m4a(path: Path, title: str, artist: str, album: str, track_num: int) -> Path:
    """Write a tiny but valid ALAC M4A via ffmpeg and tag it."""
    import subprocess
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
         "-c:a", "alac", "-y", str(path)],
        check=True, capture_output=True,
    )
    from alac_rip.metadata import write_tags
    write_tags(path, title=title, artist=artist, album=album,
               track_num=track_num, playlist_name="Test Playlist")
    return path


def test_sync_moves_new_tracks_to_music_dir(music_dir, downloads_dir, sync_state, mock_downloader):
    make_fake_m4a(
        downloads_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(
        downloader=mock_downloader,
        state=sync_state,
        music_dir=music_dir,
        playlist_name="Test Playlist",
    )
    engine.sync("https://music.apple.com/playlist/xyz")
    dest = music_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a"
    assert dest.exists()


def test_sync_records_track_in_db(music_dir, downloads_dir, sync_state, mock_downloader):
    make_fake_m4a(
        downloads_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(
        downloader=mock_downloader,
        state=sync_state,
        music_dir=music_dir,
        playlist_name="Test Playlist",
    )
    engine.sync("https://music.apple.com/playlist/xyz")
    assert sync_state.get_downloaded_count() == 1


def test_sync_skips_already_downloaded_tracks(music_dir, downloads_dir, sync_state, mock_downloader):
    track_relative = "Queen/A Night at the Opera/01 - Bohemian Rhapsody.m4a"
    sync_state.add_track(Track(
        track_id=track_relative,
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera",
        local_path=str(music_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a"),
        downloaded_at=datetime.now().isoformat(),
    ))
    make_fake_m4a(
        downloads_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(
        downloader=mock_downloader,
        state=sync_state,
        music_dir=music_dir,
        playlist_name="Test Playlist",
    )
    result = engine.sync("https://music.apple.com/playlist/xyz")
    assert result.new_count == 0
    assert result.skipped_count == 1


def test_sync_returns_summary(music_dir, downloads_dir, sync_state, mock_downloader):
    make_fake_m4a(
        downloads_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(
        downloader=mock_downloader,
        state=sync_state,
        music_dir=music_dir,
        playlist_name="Test Playlist",
    )
    result = engine.sync("https://music.apple.com/playlist/xyz")
    assert result.new_count == 1
    assert result.skipped_count == 0
    assert result.error_count == 0


def test_sync_writes_m3u8_playlist(music_dir, downloads_dir, sync_state, mock_downloader):
    make_fake_m4a(
        downloads_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(
        downloader=mock_downloader,
        state=sync_state,
        music_dir=music_dir,
        playlist_name="Test Playlist",
    )
    engine.sync("https://music.apple.com/playlist/xyz")
    m3u8 = music_dir / "Playlists" / "Test Playlist.m3u8"
    assert m3u8.exists()
    content = m3u8.read_text()
    assert "#EXTM3U" in content
    assert "Bohemian Rhapsody" in content
    assert "Queen" in content


def test_sync_m3u8_includes_skipped_tracks(music_dir, downloads_dir, sync_state, mock_downloader):
    """Tracks downloaded in a previous sync still appear in the M3U8."""
    local_path = str(music_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a")
    track_relative = "Queen/A Night at the Opera/01 - Bohemian Rhapsody.m4a"
    sync_state.add_track(Track(
        track_id=track_relative,
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera",
        local_path=local_path,
        downloaded_at=datetime.now().isoformat(),
    ))
    sync_state.add_track_to_playlist("Test Playlist", track_relative)

    make_fake_m4a(
        downloads_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(
        downloader=mock_downloader,
        state=sync_state,
        music_dir=music_dir,
        playlist_name="Test Playlist",
    )
    engine.sync("https://music.apple.com/playlist/xyz")
    m3u8 = music_dir / "Playlists" / "Test Playlist.m3u8"
    assert "Bohemian Rhapsody" in m3u8.read_text()
