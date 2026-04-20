import socket
from pathlib import Path
from typing import Optional

import uvicorn
import yaml
from fastapi import FastAPI
from pydantic import BaseModel

from alac_rip.config import DEFAULT_CONFIG_PATH, load_config

PORT_FILE = Path("/tmp/pies-alac-rip.port")

app = FastAPI(title="pies-alac-rip sidecar")
cfg = load_config(DEFAULT_CONFIG_PATH) if DEFAULT_CONFIG_PATH.exists() else None


class ConfigUpdate(BaseModel):
    music_dir: Optional[str] = None
    staging_dir: Optional[str] = None
    media_user_token: Optional[str] = None
    apple_id_email: Optional[str] = None
    apple_id_password: Optional[str] = None
    downloader_repo: Optional[str] = None
    wrapper_bin: Optional[str] = None
    state_dir: Optional[str] = None
    github_remote: Optional[str] = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def get_config() -> dict:
    if not DEFAULT_CONFIG_PATH.exists():
        return {}

    with open(DEFAULT_CONFIG_PATH) as f:
        data = yaml.safe_load(f) or {}

    data.pop("apple_id_password", None)
    return data


@app.put("/config")
def update_config(body: ConfigUpdate) -> dict[str, str]:
    current = {}
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH) as f:
            current = yaml.safe_load(f) or {}

    current.update(body.model_dump(exclude_none=True))

    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_CONFIG_PATH, "w") as f:
        yaml.safe_dump(current, f, default_flow_style=False, sort_keys=False)

    global cfg
    cfg = load_config(DEFAULT_CONFIG_PATH)
    return {"status": "ok"}


def _pick_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def main() -> None:
    port = _pick_port()
    PORT_FILE.write_text(str(port))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
