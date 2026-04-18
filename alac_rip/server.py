import asyncio
import json
import queue
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from mutagen.mp4 import MP4, MP4Cover
from pydantic import BaseModel

from alac_rip.config import DEFAULT_CONFIG_PATH, Config, load_config
from alac_rip.organizer import sanitize
from alac_rip.state import StateManager
from alac_rip.sync import SyncEngine

cfg: Optional[Config] = None
state: Optional[StateManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global cfg, state
    cfg = load_config(DEFAULT_CONFIG_PATH)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    state = StateManager(cfg.state_dir / "downloaded.db")
    yield


app = FastAPI(title="pies-alac-rip", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/diagnostics")
def get_diagnostics():
    def check(label: str, ok: bool, detail: str = "") -> dict:
        return {"label": label, "ok": ok, "detail": detail}

    results: list[dict] = []

    ffmpeg = shutil.which("ffmpeg")
    results.append(check("ffmpeg", ffmpeg is not None, ffmpeg or "not found in PATH"))

    git = shutil.which("git")
    results.append(check("Git", git is not None, git or "not found in PATH"))

    config_exists = DEFAULT_CONFIG_PATH.exists()
    results.append(check("Config file", config_exists, str(DEFAULT_CONFIG_PATH)))

    if cfg is not None:
        music_ok = cfg.music_dir.exists()
        results.append(check("Music directory", music_ok, str(cfg.music_dir)))

        state_ok = cfg.state_dir.exists()
        results.append(check("State directory", state_ok, str(cfg.state_dir)))

        staging_ok = cfg.staging_dir.exists()
        results.append(check("Staging directory", staging_ok, str(cfg.staging_dir)))
    else:
        for label in ("Music directory", "State directory", "Staging directory"):
            results.append(check(label, False, "Config not loaded"))

    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", "pies-alac-rip.timer"],
            capture_output=True, text=True, timeout=5,
        )
        timer_active = proc.stdout.strip() == "active"
        results.append(check("Systemd timer", timer_active, proc.stdout.strip() or "inactive"))
    except Exception as exc:
        results.append(check("Systemd timer", False, str(exc)))

    return results


class PlaylistIn(BaseModel):
    name: str
    url: str


def _playlist_dict(p) -> dict:
    return {"name": p.name, "url": p.url, "last_synced": p.last_synced, "paused": p.paused}


@app.get("/playlists")
def get_playlists():
    return [_playlist_dict(p) for p in state.get_playlists()]


@app.post("/playlists", status_code=201)
def add_playlist(body: PlaylistIn):
    state.add_playlist(body.name, body.url)
    return {"name": body.name, "url": body.url, "last_synced": None, "paused": False}


@app.delete("/playlists/{name}", status_code=204)
def delete_playlist(name: str):
    with sqlite3.connect(cfg.state_dir / "downloaded.db") as conn:
        conn.execute("DELETE FROM playlist_tracks WHERE playlist_name = ?", (name,))
        conn.execute("DELETE FROM playlists WHERE name = ?", (name,))
    return None


class PlaylistPatch(BaseModel):
    name: Optional[str] = None
    paused: Optional[bool] = None


@app.patch("/playlists/{name}")
def patch_playlist(name: str, body: PlaylistPatch):
    playlists = {p.name: p for p in state.get_playlists()}
    if name not in playlists:
        raise HTTPException(404, f"Playlist '{name}' not found")
    if body.name is not None and body.name != name:
        if body.name in playlists:
            raise HTTPException(409, f"Playlist '{body.name}' already exists")
        state.rename_playlist(name, body.name)
        name = body.name
    if body.paused is not None:
        state.set_playlist_paused(name, body.paused)
    updated = {p.name: p for p in state.get_playlists()}[name]
    return _playlist_dict(updated)


_active_syncs: set[str] = set()
_active_syncs_lock = threading.Lock()


def _log_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return slug or "playlist"


@app.get("/sync/{name}")
async def sync_playlist(name: str):
    playlists = {p.name: p for p in state.get_playlists()}
    if name not in playlists:
        raise HTTPException(404, f"Playlist '{name}' not found")
    if playlists[name].paused:
        raise HTTPException(409, f"Playlist '{name}' is paused")

    with _active_syncs_lock:
        if name in _active_syncs:
            raise HTTPException(409, f"Playlist '{name}' is already syncing")
        _active_syncs.add(name)

    log_q: queue.Queue = queue.Queue()
    logs_dir = cfg.state_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now()
    log_path = logs_dir / f"{started_at.strftime('%Y%m%d-%H%M%S')}-{_log_slug(name)}.log"

    staging_dir = cfg.staging_dir / sanitize(name)

    def run_sync():
        def write_log_line(line: str) -> None:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat()} {line}\n")

        write_log_line(f"[session] playlist={name}")

        def on_log(msg: str, phase: str) -> None:
            write_log_line(f"[{phase}] {msg}")
            log_q.put({"type": "log", "phase": phase, "message": msg, "log_path": str(log_path)})

        try:
            if not staging_dir.exists() or not any(staging_dir.rglob("*.m4a")):
                raise RuntimeError(
                    f"No .m4a files found in {staging_dir}. "
                    "Place downloaded files there and try again."
                )

            engine = SyncEngine(
                state=state,
                music_dir=cfg.music_dir,
                playlist_name=name,
                on_log=on_log,
            )
            result = engine.sync(staging_dir)
            state.update_playlist_synced(name)
            write_log_line(
                f"[done] Sync complete: {result.new_count} new, "
                f"{result.skipped_count} skipped, {result.error_count} errors"
            )
            log_q.put({
                "type": "done",
                "new": result.new_count,
                "skipped": result.skipped_count,
                "errors": result.error_count,
                "log_path": str(log_path),
            })
        except Exception as exc:
            write_log_line(f"[error] {exc}")
            log_q.put({"type": "error", "message": str(exc), "log_path": str(log_path)})
        finally:
            with _active_syncs_lock:
                _active_syncs.discard(name)

    thread = threading.Thread(target=run_sync, daemon=True)
    thread.start()

    async def event_stream():
        while True:
            try:
                event = log_q.get_nowait()
            except queue.Empty:
                if not thread.is_alive():
                    yield f"data: {json.dumps({'status': 'error', 'message': 'Sync thread exited unexpectedly', 'log_path': str(log_path)})}\n\n"
                    break
                await asyncio.sleep(0.05)
                continue

            if event["type"] == "log":
                yield f"data: {json.dumps({'status': 'running', 'phase': event['phase'], 'message': event['message'], 'log_path': event['log_path']})}\n\n"
            elif event["type"] == "done":
                yield f"data: {json.dumps({'status': 'done', 'new': event['new'], 'skipped': event['skipped'], 'errors': event['errors'], 'log_path': event['log_path']})}\n\n"
                break
            elif event["type"] == "error":
                yield f"data: {json.dumps({'status': 'error', 'message': event['message'], 'log_path': event['log_path']})}\n\n"
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/stats")
def get_stats():
    playlists = state.get_playlists()
    total_tracks = 0
    playlist_stats = []
    for pl in playlists:
        tracks = state.get_playlist_tracks(pl.name)
        count = len(tracks)
        total_tracks += count
        playlist_stats.append({
            "name": pl.name,
            "track_count": count,
            "last_synced": pl.last_synced,
        })
    synced = [p for p in playlist_stats if p["last_synced"]]
    last_sync = max((p["last_synced"] for p in synced), default=None)
    return {
        "playlist_count": len(playlists),
        "total_tracks": total_tracks,
        "last_sync": last_sync,
        "playlists": playlist_stats,
    }


@app.get("/library")
def get_library():
    result: dict = {}
    for pl in state.get_playlists():
        tracks = state.get_playlist_tracks(pl.name)
        result[pl.name] = [
            {
                "track_id": t.track_id,
                "title": t.title,
                "artist": t.artist,
                "album": t.album,
                "local_path": t.local_path,
                "downloaded_at": t.downloaded_at,
            }
            for t in tracks
        ]
    return result


@app.get("/track-art")
def get_track_art(path: str):
    track_path = Path(path)
    if not track_path.exists():
        raise HTTPException(404, "File not found")
    try:
        tags = MP4(track_path)
        covers = tags.get("covr", [])
        if not covers:
            raise HTTPException(404, "No cover art embedded")
        cover = covers[0]
        fmt = "image/jpeg" if cover.imageformat == MP4Cover.FORMAT_JPEG else "image/png"
        return Response(content=bytes(cover), media_type=fmt)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


class ConfigUpdate(BaseModel):
    music_dir: Optional[str] = None
    staging_dir: Optional[str] = None
    state_dir: Optional[str] = None
    github_remote: Optional[str] = None


@app.get("/config")
def get_config():
    try:
        with open(DEFAULT_CONFIG_PATH) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise HTTPException(503, "Config file not found")
    return data


@app.put("/config")
def update_config(body: ConfigUpdate):
    current: dict = {}
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH) as f:
            current = yaml.safe_load(f) or {}
    current.update(body.model_dump(exclude_none=True))
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_CONFIG_PATH, "w") as f:
        yaml.dump(current, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    global cfg
    cfg = load_config(DEFAULT_CONFIG_PATH)
    return {"status": "ok"}


if __name__ == "__main__":
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    Path("/tmp/pies-alac-rip.port").write_text(str(port))
    uvicorn.run(app, fd=sock.fileno(), log_level="warning")
