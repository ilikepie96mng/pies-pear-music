import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from alac_rip.metadata import write_tags
from alac_rip.state import StateManager
from alac_rip.sync import IntegrityError, SyncEngine


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


def make_valid_flac(path: Path, title: str = "Valid Track", artist: str = "Artist", album: str = "Album") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
            "-c:a", "flac", "-y", str(path),
        ],
        check=True,
        capture_output=True,
    )
    write_tags(path, title=title, artist=artist, album=album, track_num=1)
    return path


def make_corrupt_flac(path: Path) -> Path:
    """Generate a file with valid FLAC header ('fLaC') followed by garbage audio frames."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write FLAC magic followed by corrupted random bytes
    path.write_bytes(b"fLaC\x00\x00\x00\x22" + b"\xff\x00\xaa\x55" * 64)
    return path


def test_verify_flac_integrity_valid_file(music_dir, sync_state, tmp_path):
    flac_file = make_valid_flac(tmp_path / "valid.flac")
    engine = SyncEngine(state=sync_state, music_dir=music_dir)
    valid, msg = engine._verify_flac_integrity(flac_file)
    assert valid is True
    assert msg == "OK"


def test_verify_flac_integrity_corrupt_file(music_dir, sync_state, tmp_path):
    flac_file = make_corrupt_flac(tmp_path / "corrupt.flac")
    engine = SyncEngine(state=sync_state, music_dir=music_dir)
    valid, msg = engine._verify_flac_integrity(flac_file)
    assert valid is False
    assert len(msg) > 0


def test_verify_flac_integrity_missing_binary(music_dir, sync_state, tmp_path):
    flac_file = make_valid_flac(tmp_path / "valid.flac")
    engine = SyncEngine(state=sync_state, music_dir=music_dir)
    with patch("shutil.which", return_value=None):
        valid, msg = engine._verify_flac_integrity(flac_file)
        assert valid is True
        assert "skipped" in msg.lower() or "not found" in msg.lower()


def test_sync_aborts_on_corrupted_flac_stream(music_dir, staging_dir, sync_state):
    corrupt_staging = staging_dir / "Artist" / "Album" / "01 - Bad Track.flac"
    make_corrupt_flac(corrupt_staging)

    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Integrity")
    result = engine.sync(staging_dir)

    assert result.error_count == 1
    assert result.new_count == 0
    # Ensure corrupt file was not placed into final destination
    dest = music_dir / "artists" / "Artist" / "Album" / "01 - Bad Track.flac"
    assert not dest.exists()
    # Ensure temporary files were cleaned up
    album_dir = music_dir / "artists" / "Artist" / "Album"
    if album_dir.exists():
        tmp_files = list(album_dir.glob(".tmp_*"))
        assert len(tmp_files) == 0


def test_sync_succeeds_on_valid_flac(music_dir, staging_dir, sync_state):
    valid_staging = staging_dir / "Artist" / "Album" / "01 - Good Track.flac"
    make_valid_flac(valid_staging, title="Good Track", artist="Artist", album="Album")

    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Test Integrity")
    result = engine.sync(staging_dir)

    assert result.error_count == 0
    assert result.new_count == 1
    dest = music_dir / "artists" / "Artist" / "Album" / "01 - Good Track.flac"
    assert dest.exists()
