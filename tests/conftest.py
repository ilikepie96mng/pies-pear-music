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
