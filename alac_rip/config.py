import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "pies-alac-rip" / "config.yaml"


@dataclass
class Config:
    music_dir: Path
    state_dir: Path
    alac_rip_dir: Path
    log_retention_days: int = 2
    lastfm_api_key: str = ""


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    def p(key: str, default: str = "") -> Path:
        val = data.get(key, default)
        return Path(val).expanduser().resolve() if val else Path("")

    return Config(
        music_dir=p("music_dir", "~/Music/pies-alac-rip"),
        state_dir=p("state_dir", str(Path.home() / ".local/share/pies-alac-rip")),
        alac_rip_dir=p("alac_rip_dir", ""),
        log_retention_days=int(data.get("log_retention_days", 2)),
        lastfm_api_key=data.get("lastfm_api_key", ""),
    )


def save_config_file(path: Path, data: dict) -> None:
    """Atomically write configuration YAML with private 0600 permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(tmp_path), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
        try:
            os.chmod(str(path), 0o600)
        except OSError:
            pass
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

