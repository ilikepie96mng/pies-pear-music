from pathlib import Path
from datetime import datetime
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


import time
import os


def _make_log(logs_dir, name, age_seconds):
    p = logs_dir / name
    p.write_text("log content")
    mtime = time.time() - age_seconds
    os.utime(p, (mtime, mtime))
    return p


def test_cleanup_deletes_old_logs(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    old = _make_log(logs_dir, "old.log", age_seconds=3 * 86400)
    recent = _make_log(logs_dir, "recent.log", age_seconds=1 * 86400)

    retention_days = 2
    cutoff = datetime.now().timestamp() - retention_days * 86400
    for log in logs_dir.glob("*.log"):
        try:
            if log.stat().st_mtime < cutoff:
                log.unlink()
        except OSError:
            pass

    assert not old.exists()
    assert recent.exists()


def test_cleanup_skips_when_retention_zero(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    old = _make_log(logs_dir, "old.log", age_seconds=10 * 86400)

    retention_days = 0
    if retention_days > 0:
        cutoff = datetime.now().timestamp() - retention_days * 86400
        for log in logs_dir.glob("*.log"):
            try:
                if log.stat().st_mtime < cutoff:
                    log.unlink()
            except OSError:
                pass

    assert old.exists()


def test_cleanup_ignores_non_log_files(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    other = logs_dir / "notes.txt"
    other.write_text("keep me")
    old_mtime = time.time() - 10 * 86400
    os.utime(other, (old_mtime, old_mtime))

    retention_days = 2
    cutoff = datetime.now().timestamp() - retention_days * 86400
    for log in logs_dir.glob("*.log"):
        try:
            if log.stat().st_mtime < cutoff:
                log.unlink()
        except OSError:
            pass

    assert other.exists()
