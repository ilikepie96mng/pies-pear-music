import json
import socket
import sqlite3
import threading
from pathlib import Path
from typing import Optional

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from mutagen.mp4 import MP4, MP4Cover
from pydantic import BaseModel

from alac_rip.config import DEFAULT_CONFIG_PATH, load_config
from alac_rip.downloader import Downloader
from alac_rip.state import StateManager
from alac_rip.sync import SyncEngine

app = FastAPI(title="pies-alac-rip")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

cfg = load_config(DEFAULT_CONFIG_PATH)
cfg.state_dir.mkdir(parents=True, exist_ok=True)
state = StateManager(cfg.state_dir / "downloaded.db")


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    Path("/tmp/pies-alac-rip.port").write_text(str(port))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
