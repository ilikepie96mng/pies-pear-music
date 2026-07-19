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
