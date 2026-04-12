from pathlib import Path
from alac_rip.config import load_config, Config


def test_load_config_returns_config_dataclass(tmp_config):
    cfg = load_config(tmp_config)
    assert isinstance(cfg, Config)


def test_load_config_reads_token(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.media_user_token == "test-token-abc"


def test_load_config_expands_home_in_music_dir(tmp_config):
    cfg = load_config(tmp_config)
    assert not str(cfg.music_dir).startswith("~")
    assert cfg.music_dir.is_absolute()


def test_load_config_expands_home_in_staging_dir(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.staging_dir.is_absolute()


def test_load_config_expands_home_in_downloader_repo(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.downloader_repo.is_absolute()


def test_load_config_expands_home_in_wrapper_bin(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.wrapper_bin.is_absolute()


def test_load_config_reads_github_remote(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.github_remote == "git@github.com:user/pies-alac-rip-tool.git"
