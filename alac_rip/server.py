import asyncio
import base64
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

# ── Wrapper / downloader state ────────────────────────────────────────────────

CONTAINER_NAME = "alac-rip-wrapper"
IMAGE_NAME = "alac-rip-wrapper"

wrapper_process: Optional[subprocess.Popen] = None
wrapper_running: bool = False
wrapper_needs_2fa: bool = False
wrapper_logs: list[str] = []

download_process: Optional[subprocess.Popen] = None
download_running: bool = False
downloader_logs: list[str] = []


def _credentials_path() -> Path:
    return Path.home() / ".config" / "pies-alac-rip" / ".credentials"


def save_credentials(email: str, password: str) -> bool:
    try:
        data = {
            "email": base64.b64encode(email.encode()).decode(),
            "password": base64.b64encode(password.encode()).decode(),
        }
        _credentials_path().write_text(json.dumps(data))
        return True
    except Exception:
        return False


def load_credentials() -> tuple[Optional[str], Optional[str]]:
    try:
        path = _credentials_path()
        if path.exists():
            data = json.loads(path.read_text())
            return (
                base64.b64decode(data["email"]).decode(),
                base64.b64decode(data["password"]).decode(),
            )
    except Exception:
        pass
    return None, None


def delete_credentials() -> None:
    try:
        path = _credentials_path()
        if path.exists():
            path.unlink()
    except Exception:
        pass


def ensure_wrapper_image(wrapper_dir: Path) -> tuple[bool, Optional[str]]:
    check = subprocess.run(["podman", "image", "exists", IMAGE_NAME], capture_output=True)
    if check.returncode != 0:
        result = subprocess.run(
            ["podman", "build", "-t", IMAGE_NAME, str(wrapper_dir)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False, result.stderr
    return True, None


def stream_wrapper_logs(pipe, target_list, email=None, password=None, auto_login=False):
    global wrapper_running, wrapper_process, wrapper_needs_2fa
    login_successful = False
    try:
        for line in iter(pipe.readline, ""):
            line = line.strip()
            if not line:
                continue
            target_list.append(line)
            if "credentialHandler:" in line and "2FA: true" in line:
                wrapper_needs_2fa = True
                target_list.append("2FA required — please enter your code")
            if "[.] response type 6" in line:
                wrapper_running = True
                wrapper_needs_2fa = False
                login_successful = True
                if auto_login:
                    target_list.append("Auto-login successful. Ready for downloads.")
                else:
                    target_list.append("Login successful. Ready for downloads.")
                    if email and password:
                        if save_credentials(email, password):
                            target_list.append("Credentials saved for auto-login")
    except Exception as e:
        target_list.append(f"Error reading wrapper logs: {e}")
    finally:
        if wrapper_process and wrapper_process.poll() is not None:
            exit_code = wrapper_process.poll()
            if not login_successful:
                target_list.append(f"Login failed — wrapper exited with code {exit_code}")
                wrapper_running = False
                wrapper_needs_2fa = False
                if auto_login:
                    target_list.append("Auto-login failed, removing saved credentials")
                    delete_credentials()
            elif exit_code != 0:
                target_list.append(f"Wrapper ended unexpectedly (exit {exit_code})")
                wrapper_running = False
            else:
                target_list.append("Wrapper ended normally")
                wrapper_running = False
        pipe.close()


def stream_download_logs(pipe, target_list):
    global download_running, download_process
    try:
        for line in iter(pipe.readline, ""):
            line = line.strip()
            if line:
                target_list.append(line)
    except Exception as e:
        target_list.append(f"Error reading download logs: {e}")
    finally:
        if download_process and download_process.poll() is not None:
            exit_code = download_process.poll()
            target_list.append(
                "Download completed successfully." if exit_code == 0
                else f"Download failed with exit code {exit_code}"
            )
            download_running = False
        pipe.close()


def start_wrapper_login(email: str, password: str, auto_login: bool = False) -> bool:
    global wrapper_process, wrapper_running, wrapper_logs

    if wrapper_process and wrapper_process.poll() is None:
        if not auto_login:
            wrapper_logs.append("Wrapper already running")
        return False

    if not auto_login:
        wrapper_logs = []

    prefix = "Auto-login: " if auto_login else ""
    wrapper_logs.append(f"{prefix}Starting wrapper login for {email}...")

    if cfg is None or not cfg.alac_rip_dir or not cfg.alac_rip_dir.exists():
        wrapper_logs.append(f"{prefix}alac_rip_dir not configured — set it in Settings")
        return False

    wrapper_dir = cfg.alac_rip_dir / "wrapper"

    subprocess.run(["podman", "stop", CONTAINER_NAME], capture_output=True)
    subprocess.run(["podman", "rm", CONTAINER_NAME], capture_output=True)

    ok, err = ensure_wrapper_image(wrapper_dir)
    if not ok:
        wrapper_logs.append(f"{prefix}Failed to build wrapper image: {err}")
        return False

    cmd = [
        "podman", "run", "--rm",
        "--name", CONTAINER_NAME,
        "-i",
        "--network", "host",
        "--volume", "/dev/urandom:/app/rootfs/dev/urandom:ro",
        "-e", f"args=-L {email}:{password}",
        IMAGE_NAME,
    ]
    wrapper_logs.append(f"{prefix}Launching container: {CONTAINER_NAME}")

    try:
        wrapper_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
        )
        threading.Thread(
            target=stream_wrapper_logs,
            args=(wrapper_process.stdout, wrapper_logs, email, password, auto_login),
            daemon=True,
        ).start()
        wrapper_logs.append(f"{prefix}Container started, waiting for login confirmation...")
        return True
    except Exception as e:
        wrapper_logs.append(f"{prefix}Error starting container: {e}")
        if auto_login:
            delete_credentials()
        return False


def attempt_auto_login() -> bool:
    email, password = load_credentials()
    if email and password:
        wrapper_logs.append("Found saved credentials, attempting auto-login...")
        return start_wrapper_login(email, password, auto_login=True)
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global cfg, state
    cfg = load_config(DEFAULT_CONFIG_PATH)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    state = StateManager(cfg.state_dir / "downloaded.db")
    threading.Thread(target=attempt_auto_login, daemon=True).start()
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

        alac_ok = bool(cfg.alac_rip_dir) and cfg.alac_rip_dir.exists()
        results.append(check("alac-rip directory", alac_ok, str(cfg.alac_rip_dir) if alac_ok else "not configured — set in Settings"))
    else:
        for label in ("Music directory", "State directory", "Staging directory", "alac-rip directory"):
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
    return {"name": p.name, "url": p.url, "last_synced": p.last_synced, "paused": p.paused, "staging_folder": p.staging_folder}


@app.get("/playlists")
def get_playlists():
    return [_playlist_dict(p) for p in state.get_playlists()]


@app.post("/playlists", status_code=201)
def add_playlist(body: PlaylistIn):
    state.add_playlist(body.name, body.url)
    return {"name": body.name, "url": body.url, "last_synced": None, "paused": False, "staging_folder": None}


@app.delete("/playlists/{name}", status_code=204)
def delete_playlist(name: str):
    with sqlite3.connect(cfg.state_dir / "downloaded.db") as conn:
        conn.execute("DELETE FROM playlist_tracks WHERE playlist_name = ?", (name,))
        conn.execute("DELETE FROM sync_runs WHERE playlist_name = ?", (name,))
        conn.execute("DELETE FROM playlists WHERE name = ?", (name,))
    return None


class PlaylistPatch(BaseModel):
    name: Optional[str] = None
    paused: Optional[bool] = None
    staging_folder: Optional[str] = None


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
    if body.staging_folder is not None:
        folder = body.staging_folder.strip() or None
        state.set_playlist_staging_folder(name, folder)
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

    playlist_obj = playlists[name]
    folder_name = playlist_obj.staging_folder if playlist_obj.staging_folder else sanitize(name)
    staging_dir = cfg.staging_dir / folder_name

    def run_sync():
        def write_log_line(line: str) -> None:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat()} {line}\n")

        write_log_line(f"[session] playlist={name}")

        def on_log(msg: str, phase: str) -> None:
            write_log_line(f"[{phase}] {msg}")
            log_q.put({"type": "log", "phase": phase, "message": msg, "log_path": str(log_path)})

        try:
            audio_exts = {".flac", ".m4a"}
            if not staging_dir.exists() or not any(f for f in staging_dir.rglob("*") if f.suffix.lower() in audio_exts):
                raise RuntimeError(
                    f"No audio files found in {staging_dir}. "
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
            ended = datetime.now().isoformat()
            state.record_sync_run(
                name, started_at.isoformat(), ended, "success",
                result.new_count, result.skipped_count, result.error_count, str(log_path),
            )
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
            state.record_sync_run(
                name, started_at.isoformat(), datetime.now().isoformat(), "error",
                0, 0, 0, str(log_path), str(exc),
            )
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


@app.get("/sync-history")
def get_sync_history(limit: int = 30):
    runs = state.get_recent_runs(limit=limit)
    return [
        {
            "id": r.id,
            "playlist_name": r.playlist_name,
            "started_at": r.started_at,
            "ended_at": r.ended_at,
            "status": r.status,
            "new_count": r.new_count,
            "skipped_count": r.skipped_count,
            "error_count": r.error_count,
            "log_path": r.log_path,
            "error_message": r.error_message,
        }
        for r in runs
    ]


@app.get("/sync-history/{name}")
def get_playlist_sync_history(name: str, limit: int = 20):
    runs = state.get_recent_runs(playlist_name=name, limit=limit)
    return [
        {
            "id": r.id,
            "playlist_name": r.playlist_name,
            "started_at": r.started_at,
            "ended_at": r.ended_at,
            "status": r.status,
            "new_count": r.new_count,
            "skipped_count": r.skipped_count,
            "error_count": r.error_count,
            "log_path": r.log_path,
            "error_message": r.error_message,
        }
        for r in runs
    ]


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
    alac_rip_dir: Optional[str] = None


_CONFIG_OMIT = {"apple_id_password", "media_user_token"}


@app.get("/config")
def get_config():
    try:
        with open(DEFAULT_CONFIG_PATH) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise HTTPException(503, "Config file not found")
    return {k: v for k, v in data.items() if k not in _CONFIG_OMIT}


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


# ── Wrapper routes ────────────────────────────────────────────────────────────

class WrapperLoginRequest(BaseModel):
    email: str
    password: str


@app.post("/wrapper/login")
def login_wrapper(body: WrapperLoginRequest):
    if wrapper_process and wrapper_process.poll() is None:
        return {"status": "error", "msg": "Wrapper already running"}
    if start_wrapper_login(body.email, body.password, auto_login=False):
        return {"status": "ok", "msg": "Wrapper process started, waiting for login..."}
    return {"status": "error", "msg": wrapper_logs[-1] if wrapper_logs else "Failed to start wrapper"}


@app.post("/wrapper/stop")
def stop_wrapper():
    global wrapper_process, wrapper_running, wrapper_logs, wrapper_needs_2fa
    if wrapper_process and wrapper_process.poll() is None:
        subprocess.run(["podman", "stop", CONTAINER_NAME], capture_output=True)
        wrapper_process.terminate()
        wrapper_logs.append("Wrapper stopped by user")
        wrapper_running = False
        wrapper_needs_2fa = False
        return {"status": "ok", "msg": "Wrapper stopped"}
    return {"status": "error", "msg": "Wrapper not running"}


class TwoFARequest(BaseModel):
    code: str


@app.post("/wrapper/2fa")
def submit_2fa(body: TwoFARequest):
    global wrapper_needs_2fa
    if not wrapper_needs_2fa:
        return {"status": "error", "msg": "2FA not required"}
    if not wrapper_process or wrapper_process.poll() is not None:
        return {"status": "error", "msg": "Wrapper not running"}
    try:
        wrapper_process.stdin.write(f"{body.code}\n")
        wrapper_process.stdin.flush()
        wrapper_logs.append("2FA code submitted")
        wrapper_needs_2fa = False
        return {"status": "ok", "msg": "2FA code submitted"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


@app.get("/wrapper/status")
def get_wrapper_status():
    global wrapper_running, wrapper_process, wrapper_needs_2fa
    if wrapper_process and wrapper_process.poll() is not None and wrapper_running:
        wrapper_running = False
    return {
        "running": wrapper_running,
        "needs_2fa": wrapper_needs_2fa,
        "logs": wrapper_logs[-200:],
    }


# ── Download routes ───────────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    link: str
    format: str = "ALAC"


@app.post("/download")
def start_download(body: DownloadRequest):
    global download_process, download_running, downloader_logs

    # Auto-reset stuck state if process already exited
    if download_running and download_process and download_process.poll() is not None:
        download_running = False

    if not wrapper_running:
        raise HTTPException(409, "Wrapper not running — log in to Apple Music first")
    if download_running:
        raise HTTPException(409, "Download already in progress")
    if not body.link:
        raise HTTPException(400, "No URL provided")
    if cfg is None or not cfg.alac_rip_dir or not cfg.alac_rip_dir.exists():
        raise HTTPException(503, "alac_rip_dir not configured")

    amd_dir = cfg.alac_rip_dir / "apple-music-downloader"
    downloader_logs = []

    linuxbrew_bin = "/var/home/linuxbrew/.linuxbrew/bin"
    import os as _os
    env = _os.environ.copy()
    env["PATH"] = f"{linuxbrew_bin}:{env.get('PATH', '')}"

    go_bin = shutil.which("go", path=env["PATH"]) or f"{linuxbrew_bin}/go"

    if body.format == "ATMOS":
        cmd = [go_bin, "run", "main.go", "--atmos", body.link]
    elif body.format == "AAC":
        cmd = [go_bin, "run", "main.go", "--aac", body.link]
    else:
        cmd = [go_bin, "run", "main.go", body.link]

    downloader_logs.append(f"Starting {body.format} download: {body.link}")

    try:
        download_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
            cwd=str(amd_dir),
            env=env,
        )
        download_running = True
        threading.Thread(
            target=stream_download_logs,
            args=(download_process.stdout, downloader_logs),
            daemon=True,
        ).start()
        return {"status": "ok", "msg": "Download started"}
    except Exception as e:
        downloader_logs.append(f"Error: {e}")
        raise HTTPException(500, str(e))


@app.get("/download/logs")
def get_download_logs():
    global download_running, download_process
    if download_process and download_process.poll() is not None and download_running:
        download_running = False
    return {
        "running": download_running,
        "logs": downloader_logs[-200:],
    }


@app.get("/download/one-off")
async def download_one_off(url: str = "", format: str = "ALAC"):
    if not wrapper_running:
        raise HTTPException(409, "Wrapper not running — log in to Apple Music first")
    if download_running:
        raise HTTPException(409, "Download already in progress")
    if not url:
        raise HTTPException(400, "No URL provided")
    if cfg is None or not cfg.alac_rip_dir or not cfg.alac_rip_dir.exists():
        raise HTTPException(503, "alac_rip_dir not configured")

    amd_dir = cfg.alac_rip_dir / "apple-music-downloader"
    save_folder_key = {"ATMOS": "atmos-save-folder", "AAC": "aac-save-folder"}.get(format, "alac-save-folder")
    try:
        with open(amd_dir / "config.yaml") as f:
            amd_cfg = yaml.safe_load(f) or {}
        save_folder = Path(amd_cfg.get(save_folder_key, "")).expanduser()
    except Exception as exc:
        raise HTTPException(503, f"Cannot read downloader config: {exc}")
    if not save_folder or not save_folder.is_absolute():
        raise HTTPException(503, f"Downloader save folder not configured ({save_folder_key})")

    import os as _os
    linuxbrew_bin = "/var/home/linuxbrew/.linuxbrew/bin"
    env = _os.environ.copy()
    env["PATH"] = f"{linuxbrew_bin}:{env.get('PATH', '')}"
    go_bin = shutil.which("go", path=env["PATH"]) or f"{linuxbrew_bin}/go"

    if format == "ATMOS":
        cmd = [go_bin, "run", "main.go", "--atmos", url]
    elif format == "AAC":
        cmd = [go_bin, "run", "main.go", "--aac", url]
    else:
        cmd = [go_bin, "run", "main.go", url]

    async def event_stream():
        global download_running, download_process

        # ── Phase 1: download ──────────────────────────────────────────────
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                cwd=str(amd_dir),
                env=env,
            )
        except Exception as exc:
            yield f"data: {json.dumps({'status': 'error', 'message': str(exc)})}\n\n"
            return

        download_running = True
        download_process = proc
        dl_q: queue.Queue = queue.Queue()

        def _read_dl():
            try:
                for line in iter(proc.stdout.readline, ""):
                    line = line.strip()
                    if line:
                        dl_q.put(line)
            except Exception:
                pass
            finally:
                dl_q.put(None)

        threading.Thread(target=_read_dl, daemon=True).start()

        while True:
            try:
                item = dl_q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if item is None:
                break
            yield f"data: {json.dumps({'status': 'running', 'phase': 'downloading', 'message': item})}\n\n"

        exit_code = proc.wait()
        download_running = False
        download_process = None

        if exit_code != 0:
            yield f"data: {json.dumps({'status': 'error', 'message': f'Download failed (exit code {exit_code})'})}\n\n"
            return

        # ── Phase 2: organize ──────────────────────────────────────────────
        org_q: queue.Queue = queue.Queue()

        def on_log(msg: str, _phase: str) -> None:
            org_q.put(msg)

        org_result = None
        org_error = None

        def _run_organize():
            nonlocal org_result, org_error
            try:
                engine = SyncEngine(
                    state=state,
                    music_dir=cfg.music_dir,
                    playlist_name=None,
                    on_log=on_log,
                )
                org_result = engine.sync(save_folder)
            except Exception as exc:
                org_error = str(exc)
            finally:
                org_q.put(None)

        threading.Thread(target=_run_organize, daemon=True).start()

        while True:
            try:
                item = org_q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if item is None:
                break
            yield f"data: {json.dumps({'status': 'running', 'phase': 'organizing', 'message': item})}\n\n"

        if org_error:
            yield f"data: {json.dumps({'status': 'error', 'message': org_error})}\n\n"
        else:
            yield f"data: {json.dumps({'status': 'done', 'new': org_result.new_count, 'skipped': org_result.skipped_count, 'errors': org_result.error_count})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    Path("/tmp/pies-alac-rip.port").write_text(str(port))
    uvicorn.run(app, fd=sock.fileno(), log_level="warning")
