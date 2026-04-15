import asyncio
import json
import socket
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from mutagen.mp4 import MP4, MP4Cover
from pydantic import BaseModel

from alac_rip.config import DEFAULT_CONFIG_PATH, Config, load_config
from alac_rip.downloader import Downloader
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


class PlaylistIn(BaseModel):
    name: str
    url: str


@app.get("/playlists")
def get_playlists():
    return [
        {"name": p.name, "url": p.url, "last_synced": p.last_synced}
        for p in state.get_playlists()
    ]


@app.post("/playlists", status_code=201)
def add_playlist(body: PlaylistIn):
    state.add_playlist(body.name, body.url)
    return {"name": body.name, "url": body.url, "last_synced": None}


@app.delete("/playlists/{name}", status_code=204)
def delete_playlist(name: str):
    with sqlite3.connect(cfg.state_dir / "downloaded.db") as conn:
        conn.execute("DELETE FROM playlist_tracks WHERE playlist_name = ?", (name,))
        conn.execute("DELETE FROM playlists WHERE name = ?", (name,))
    return None


_active_syncs: set[str] = set()
_active_syncs_lock = threading.Lock()


@app.get("/sync/{name}")
async def sync_playlist(name: str):
    playlists = {p.name: p for p in state.get_playlists()}
    if name not in playlists:
        raise HTTPException(404, f"Playlist '{name}' not found")

    with _active_syncs_lock:
        if name in _active_syncs:
            raise HTTPException(409, f"Playlist '{name}' is already syncing")
        _active_syncs.add(name)

    playlist = playlists[name]
    pre_count = state.get_downloaded_count()
    result_holder: dict = {}
    error_holder: dict = {}

    def run_sync():
        try:
            downloader = Downloader(
                downloader_repo=cfg.downloader_repo,
                wrapper_bin=cfg.wrapper_bin,
                media_user_token=cfg.media_user_token,
                apple_id_email=cfg.apple_id_email,
                apple_id_password=cfg.apple_id_password,
            )
            engine = SyncEngine(
                downloader=downloader,
                state=state,
                music_dir=cfg.music_dir,
                playlist_name=name,
            )
            result_holder["result"] = engine.sync(playlist.url)
            state.update_playlist_synced(name)
        except Exception as exc:
            error_holder["error"] = str(exc)
        finally:
            with _active_syncs_lock:
                _active_syncs.discard(name)

    thread = threading.Thread(target=run_sync, daemon=True)
    thread.start()

    async def event_stream():
        while thread.is_alive():
            current = max(state.get_downloaded_count() - pre_count, 0)
            yield f"data: {json.dumps({'status': 'running', 'new_so_far': current})}\n\n"
            await asyncio.sleep(1)

        if "error" in error_holder:
            yield f"data: {json.dumps({'status': 'error', 'message': error_holder['error']})}\n\n"
        else:
            r = result_holder.get("result")
            if r is None:
                yield f"data: {json.dumps({'status': 'error', 'message': 'sync thread terminated unexpectedly'})}\n\n"
            else:
                yield f"data: {json.dumps({'status': 'done', 'new': r.new_count, 'skipped': r.skipped_count, 'errors': r.error_count})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


if __name__ == "__main__":
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    Path("/tmp/pies-alac-rip.port").write_text(str(port))
    uvicorn.run(app, fd=sock.fileno(), log_level="warning")
