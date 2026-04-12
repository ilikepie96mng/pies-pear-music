from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "pies-alac-rip" / "config.yaml"


@dataclass
class Config:
    media_user_token: str
    music_dir: Path
    staging_dir: Path
    downloader_repo: Path
    wrapper_bin: Path
    state_dir: Path
    github_remote: str


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)

    def p(key: str) -> Path:
        return Path(data[key]).expanduser().resolve()

    return Config(
        media_user_token=data["media_user_token"],
        music_dir=p("music_dir"),
        staging_dir=p("staging_dir"),
        downloader_repo=p("downloader_repo"),
        wrapper_bin=p("wrapper_bin"),
        state_dir=p("state_dir"),
        github_remote=data.get("github_remote", ""),
    )
