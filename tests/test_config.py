from pathlib import Path
from alac_rip.config import load_config, Config


def test_load_config_returns_config_dataclass(tmp_config):
    cfg = load_config(tmp_config)
    assert isinstance(cfg, Config)


def test_load_config_expands_home_in_music_dir(tmp_config):
    cfg = load_config(tmp_config)
    assert not str(cfg.music_dir).startswith("~")
    assert cfg.music_dir.is_absolute()



def test_load_config_uses_local_state_directory(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.state_dir.is_absolute()
