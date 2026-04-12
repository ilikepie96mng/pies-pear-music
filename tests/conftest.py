import pytest
from pathlib import Path


@pytest.fixture
def tmp_config(tmp_path):
    """Write a minimal config.yaml to a temp dir and return its path."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "media_user_token: 'test-token-abc'\n"
        "music_dir: '~/Music/Apple Music'\n"
        "staging_dir: '~/Music/.staging'\n"
        "downloader_repo: '~/.local/share/pies-alac-rip/apple-music-downloader'\n"
        "wrapper_bin: '~/.local/share/pies-alac-rip/wrapper'\n"
        "state_dir: '~/Music/Apple Music/.state'\n"
        "github_remote: 'git@github.com:user/pies-alac-rip-tool.git'\n"
    )
    return config_file


from alac_rip.state import StateManager


@pytest.fixture
def state(tmp_path):
    """Return a StateManager backed by a temp SQLite DB."""
    db_path = tmp_path / "downloaded.db"
    return StateManager(db_path)


import subprocess


@pytest.fixture
def sample_m4a(tmp_path):
    """Generate a minimal valid M4A file using ffmpeg for metadata operation tests."""
    m4a_path = tmp_path / "test_track.m4a"
    subprocess.run(
        [
            "/home/linuxbrew/.linuxbrew/bin/ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "alac", "-y", str(m4a_path),
        ],
        check=True,
        capture_output=True,
    )
    return m4a_path
