import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from alac_rip.metadata import embed_cover_art
from alac_rip.state import StateManager, Track
from alac_rip.sync import SyncEngine

FAKE_COVER = b"\xff\xd8\xff\xe0" + b"\x00" * 12 + b"fake-cover-data"


@pytest.fixture
def music_dir(tmp_path):
    d = tmp_path / "Music"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def staging_dir(tmp_path):
    d = tmp_path / "staging"
    d.mkdir()
    return d


@pytest.fixture
def sync_state(tmp_path):
    return StateManager(tmp_path / "downloaded.db")


def make_fake_m4a(path: Path, title: str, artist: str, album: str, track_num: int,
                   album_artist: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
         "-c:a", "alac", "-y", str(path)],
        check=True, capture_output=True,
    )
    from alac_rip.metadata import write_tags
    write_tags(path, title=title, artist=artist, album_artist=album_artist or artist,
               album=album, track_num=track_num, playlist_name="Test Playlist")
    return path


def make_fake_flac(path: Path, title: str, artist: str, album: str, track_num: int,
                   album_artist: str = "", cover_data: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
         "-c:a", "flac", "-y", str(path)],
        check=True, capture_output=True,
    )
    from alac_rip.metadata import write_tags
    write_tags(path, title=title, artist=artist, album_artist=album_artist or artist,
               album=album, track_num=track_num, playlist_name="Test Playlist")
    if cover_data is not None:
        embed_cover_art(path, cover_data)
    return path


def test_sync_moves_new_tracks_to_music_dir(music_dir, staging_dir, sync_state):
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)
    dest = music_dir / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac"
    assert dest.exists()


def test_sync_records_track_in_db(music_dir, staging_dir, sync_state):
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)
    assert sync_state.get_downloaded_count() == 1


def test_sync_skips_already_downloaded_tracks(music_dir, staging_dir, sync_state):
    track_relative = "Queen/A Night at the Opera/01 - Bohemian Rhapsody.flac"
    sync_state.add_track(Track(
        track_id=track_relative,
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera",
        local_path=str(music_dir / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac"),
        downloaded_at=datetime.now().isoformat(),
    ))
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    result = engine.sync(staging_dir)
    assert result.new_count == 0
    assert result.skipped_count == 1


def test_sync_returns_summary(music_dir, staging_dir, sync_state):
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    result = engine.sync(staging_dir)
    assert result.new_count == 1
    assert result.skipped_count == 0
    assert result.error_count == 0


def test_sync_writes_m3u8_playlist(music_dir, staging_dir, sync_state):
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)
    m3u8 = music_dir / "playlists" / "Test Playlist.m3u8"
    assert m3u8.exists()
    content = m3u8.read_text()
    assert "#EXTM3U" in content
    assert "Bohemian Rhapsody" in content
    assert "Queen" in content


def test_sync_m3u8_includes_skipped_tracks(music_dir, staging_dir, sync_state):
    local_path = str(music_dir / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac")
    track_relative = "Queen/A Night at the Opera/01 - Bohemian Rhapsody.flac"
    sync_state.add_track(Track(
        track_id=track_relative,
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera",
        local_path=local_path,
        downloaded_at=datetime.now().isoformat(),
    ))
    sync_state.add_track_to_playlist("Test Playlist", track_relative)

    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)
    m3u8 = music_dir / "playlists" / "Test Playlist.m3u8"
    assert "Bohemian Rhapsody" in m3u8.read_text()


def test_sync_converts_m4a_to_flac(music_dir, staging_dir, sync_state):
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)
    dest = music_dir / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac"
    assert dest.exists()
    # Source M4A should be deleted
    assert not (staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a").exists()


def test_sync_moves_lrc_alongside_flac(music_dir, staging_dir, sync_state):
    src_m4a = staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a"
    make_fake_m4a(src_m4a, title="Bohemian Rhapsody", artist="Queen",
                  album="A Night at the Opera", track_num=1)
    lrc_src = src_m4a.with_suffix(".lrc")
    lrc_src.write_text("[00:00.00] Test lyric line\n")

    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)

    lrc_dest = music_dir / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.lrc"
    assert lrc_dest.exists()
    assert not lrc_src.exists()


def test_sync_without_playlist_moves_files(music_dir, staging_dir, sync_state):
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name=None)
    result = engine.sync(staging_dir)
    dest = music_dir / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac"
    assert dest.exists()
    assert result.new_count == 1


def test_sync_without_playlist_records_in_db(music_dir, staging_dir, sync_state):
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name=None)
    engine.sync(staging_dir)
    assert sync_state.get_downloaded_count() == 1


def test_sync_without_playlist_does_not_write_m3u8(music_dir, staging_dir, sync_state):
    make_fake_m4a(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name=None)
    engine.sync(staging_dir)
    playlists_dir = music_dir / "playlists"
    assert not playlists_dir.exists() or not list(playlists_dir.glob("*.m3u8"))


# ── FLAC input path ───────────────────────────────────────────────────────────

def test_sync_moves_flac_directly(music_dir, staging_dir, sync_state):
    make_fake_flac(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    result = engine.sync(staging_dir)
    dest = music_dir / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac"
    assert dest.exists()
    assert result.new_count == 1
    assert result.error_count == 0


def test_sync_flac_input_recorded_in_db(music_dir, staging_dir, sync_state):
    make_fake_flac(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)
    assert sync_state.get_downloaded_count() == 1


def test_sync_flac_input_skipped_on_second_run(music_dir, staging_dir, sync_state):
    src = staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac"
    make_fake_flac(src, title="Bohemian Rhapsody", artist="Queen",
                   album="A Night at the Opera", track_num=1)
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)

    make_fake_flac(src, title="Bohemian Rhapsody", artist="Queen",
                   album="A Night at the Opera", track_num=1)
    result = engine.sync(staging_dir)
    assert result.new_count == 0
    assert result.skipped_count == 1


def test_sync_flac_lrc_moved(music_dir, staging_dir, sync_state):
    src = staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac"
    make_fake_flac(src, title="Bohemian Rhapsody", artist="Queen",
                   album="A Night at the Opera", track_num=1)
    src.with_suffix(".lrc").write_text("[00:00.00] Test lyric\n")

    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)

    lrc_dest = music_dir / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.lrc"
    assert lrc_dest.exists()
    assert not src.with_suffix(".lrc").exists()


# ── Cover art ─────────────────────────────────────────────────────────────────

def test_sync_flac_with_cover_saves_cover_jpg(music_dir, staging_dir, sync_state):
    make_fake_flac(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
        cover_data=FAKE_COVER,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)
    cover_jpg = music_dir / "artists" / "Queen" / "A Night at the Opera" / "cover.jpg"
    assert cover_jpg.exists()
    assert cover_jpg.read_bytes() == FAKE_COVER


def test_sync_flac_without_cover_no_cover_jpg(music_dir, staging_dir, sync_state):
    make_fake_flac(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
    )
    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)
    cover_jpg = music_dir / "artists" / "Queen" / "A Night at the Opera" / "cover.jpg"
    assert not cover_jpg.exists()


def test_sync_flac_does_not_overwrite_existing_cover_jpg(music_dir, staging_dir, sync_state):
    make_fake_flac(
        staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac",
        title="Bohemian Rhapsody", artist="Queen",
        album="A Night at the Opera", track_num=1,
        cover_data=FAKE_COVER,
    )
    existing_cover = b"original-cover"
    album_dir = music_dir / "artists" / "Queen" / "A Night at the Opera"
    album_dir.mkdir(parents=True)
    (album_dir / "cover.jpg").write_bytes(existing_cover)

    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)
    assert (album_dir / "cover.jpg").read_bytes() == existing_cover


def test_sync_m4a_with_cover_saves_cover_jpg(music_dir, staging_dir, sync_state):
    src = staging_dir / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a"
    make_fake_m4a(src, title="Bohemian Rhapsody", artist="Queen",
                  album="A Night at the Opera", track_num=1)
    embed_cover_art(src, FAKE_COVER)

    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Playlist")
    engine.sync(staging_dir)
    cover_jpg = music_dir / "artists" / "Queen" / "A Night at the Opera" / "cover.jpg"
    assert cover_jpg.exists()
    assert cover_jpg.read_bytes() == FAKE_COVER
