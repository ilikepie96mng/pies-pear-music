from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "pies-alac-rip" / "config.yaml"


@dataclass
class Config:
    music_dir: Path
    staging_dir: Path
    state_dir: Path
    github_remote: str


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    def p(key: str, default: str = "") -> Path:
        val = data.get(key, default)
        return Path(val).expanduser().resolve()

    return Config(
        music_dir=p("music_dir", "~/Music/pies-alac-rip"),
        staging_dir=p("staging_dir", "~/Music/pies-alac-rip-staging"),
        state_dir=p("state_dir", str(Path.home() / ".local/share/pies-alac-rip")),
        github_remote=data.get("github_remote", ""),
    )
