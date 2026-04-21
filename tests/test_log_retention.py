from pathlib import Path
from alac_rip.config import Config, load_config


def test_config_defaults_log_retention_to_2():
    cfg = Config(
        music_dir=Path("/music"),
        state_dir=Path("/state"),
        github_remote="",
        alac_rip_dir=Path("/amd"),
    )
    assert cfg.log_retention_days == 2


def test_load_config_reads_log_retention_days(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "music_dir: /music\n"
        "state_dir: /state\n"
        "github_remote: ''\n"
        "alac_rip_dir: /amd\n"
        "log_retention_days: 7\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.log_retention_days == 7


def test_load_config_defaults_log_retention_when_absent(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "music_dir: /music\n"
        "state_dir: /state\n"
        "github_remote: ''\n"
        "alac_rip_dir: /amd\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.log_retention_days == 2
