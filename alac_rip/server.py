import asyncio
import json
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
from collections import deque

import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Query, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from mutagen.mp4 import MP4, MP4Cover
from pydantic import BaseModel, field_validator

from alac_rip import am_api, audit, gemini_ai, integrations, lastfm_api, lyrics, metadata_editor, playlist_import, smart_playlists, strawberry_sync, waveform
from alac_rip.requests import RequestStore
from alac_rip.am_api import AMApiError
from alac_rip.config import DEFAULT_CONFIG_PATH, Config, load_config, save_config_file
from alac_rip.dap_export import DapExportError, export_dap_playlist
from alac_rip.metadata import read_tags
from alac_rip.organizer import sanitize

from alac_rip.state import StateManager
from alac_rip.sync import StagingValidationError, SyncEngine, validate_staging_dir



def _normalize(s: str) -> str:
    """Normalize title/artist for matching: lowercase, strip punctuation, collapse whitespace."""
    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


_DOWNLOAD_FORMATS = frozenset({"ALAC", "AAC", "ATMOS"})
_MAX_PLAYLIST_NAME_LENGTH = 120
_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w:])/(?:[^\s:'\"]+/?)+")
_TRACK_PROGRESS_RE = re.compile(r"^Track\s+(\d+)\s+of\s+(\d+):\s*(.*)$")


def _validate_apple_music_url(value: str) -> str:
    """Accept only absolute Apple Music HTTPS URLs suitable for the downloader."""
    url = value.strip()
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "music.apple.com"
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.strip("/")
    ):
        raise ValueError("URL must be an HTTPS music.apple.com link")
    return url


def _validate_download_format(value: str) -> str:
    format_ = value.upper()
    if format_ not in _DOWNLOAD_FORMATS:
        raise ValueError(f"Format must be one of: {', '.join(sorted(_DOWNLOAD_FORMATS))}")
    return format_


def _validate_playlist_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("Playlist name is required")
    if len(name) > _MAX_PLAYLIST_NAME_LENGTH:
        raise ValueError(f"Playlist name must be at most {_MAX_PLAYLIST_NAME_LENGTH} characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("Playlist name cannot contain control characters")
    return name


def _redact_runtime_paths(message: str) -> str:
    """Keep unexpected errors actionable without exposing local filesystem paths."""
    return _ABSOLUTE_PATH_RE.sub("<local path>", message)


cfg: Optional[Config] = None
state: Optional[StateManager] = None


def _resolve_library_file(path: str) -> Path:
    """Resolve a user-supplied path only when it is a recorded library track."""
    if cfg is None or state is None:
        raise HTTPException(503, "Library is not ready")

    try:
        track_path = Path(path).expanduser().resolve()
        music_dir = cfg.music_dir.expanduser().resolve()
        track_path.relative_to(music_dir)
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(403, "Path is outside the music library")

    if not state.has_track_path(track_path):
        raise HTTPException(403, "Path is not a known library track")
    return track_path

# ── Wrapper / downloader state ────────────────────────────────────────────────

CONTAINER_NAME = "alac-rip-wrapper"
IMAGE_NAME = "alac-rip-wrapper"

wrapper_process: Optional[subprocess.Popen] = None
wrapper_running: bool = False
wrapper_needs_2fa: bool = False
wrapper_2fa_type: str = ""  # "device" | "sms" | ""
wrapper_logs: deque[str] = deque(maxlen=200)
_session_credentials: Optional[tuple[str, str]] = None


_SECRET_SERVICE_ATTRIBUTES = ("application", "pies-pear-music", "purpose", "apple-wrapper")
_SECRET_SERVICE_LABEL = "Pies Pear Music Apple wrapper credentials"
_SECRET_SERVICE_TIMEOUT_SECONDS = 5
_API_CAPABILITY_HEADER = "x-pies-api-token"
_api_capability: Optional[str] = None

job_queue: queue.Queue = queue.Queue()
active_job: Optional[dict] = None
pending_jobs: list[dict] = []
pending_jobs_lock: threading.Lock = threading.Lock()


def _credentials_path() -> Path:
    """Legacy path, retained only for one-way cleanup after keyring migration."""
    return Path.home() / ".config" / "pies-alac-rip" / ".credentials"


def _secret_service_available() -> bool:
    return shutil.which("secret-tool") is not None


def _secret_service_store(email: str, password: str) -> bool:
    if not _secret_service_available():
        return False
    try:
        result = subprocess.run(
            ["secret-tool", "store", f"--label={_SECRET_SERVICE_LABEL}", *_SECRET_SERVICE_ATTRIBUTES],
            input=json.dumps({"email": email, "password": password}),
            capture_output=True,
            text=True,
            timeout=_SECRET_SERVICE_TIMEOUT_SECONDS,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _secret_service_load() -> tuple[Optional[str], Optional[str]]:
    if not _secret_service_available():
        return None, None
    try:
        result = subprocess.run(
            ["secret-tool", "lookup", *_SECRET_SERVICE_ATTRIBUTES],
            capture_output=True,
            text=True,
            timeout=_SECRET_SERVICE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0 or not result.stdout:
            return None, None
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            return None, None
        email = data.get("email")
        password = data.get("password")
        if isinstance(email, str) and isinstance(password, str):
            return email, password
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None, None


def _secret_service_clear() -> None:
    if not _secret_service_available():
        return
    try:
        subprocess.run(
            ["secret-tool", "clear", *_SECRET_SERVICE_ATTRIBUTES],
            capture_output=True,
            text=True,
            timeout=_SECRET_SERVICE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def save_credentials(email: str, password: str) -> bool:
    """Store credentials in Secret Service, retaining only a session fallback."""
    global _session_credentials
    _session_credentials = (email, password)
    persisted = _secret_service_store(email, password)
    if persisted:
        try:
            _credentials_path().unlink(missing_ok=True)
        except OSError:
            pass
    return persisted


def load_credentials() -> tuple[Optional[str], Optional[str]]:
    if _session_credentials is not None:
        return _session_credentials
    return _secret_service_load()


def delete_credentials() -> None:
    global _session_credentials
    _session_credentials = None
    _secret_service_clear()
    try:
        _credentials_path().unlink(missing_ok=True)
    except OSError:
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


def _redact_wrapper_log(value: str, email: Optional[str] = None, password: Optional[str] = None) -> str:
    """Keep submitted credentials out of user-visible wrapper logs.

    Parsing uses the original wrapper output, so this display-only redaction
    cannot change the known-good login and 2FA markers.
    """
    redacted = value
    for secret in (email, password):
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def stream_wrapper_logs(pipe, target_list, email=None, password=None, auto_login=False):
    global wrapper_running, wrapper_process, wrapper_needs_2fa, wrapper_2fa_type
    login_successful = False
    try:
        for line in iter(pipe.readline, ""):
            line = line.strip()
            if not line:
                continue
            target_list.append(_redact_wrapper_log(line, email, password))
            if "credentialHandler:" in line and "2FA: true" in line:
                wrapper_needs_2fa = True
                wrapper_2fa_type = "sms"
                target_list.append("2FA required — please enter your code")
            if "[.] response type 4" in line:
                wrapper_needs_2fa = True
                wrapper_2fa_type = "device"
                target_list.append("2FA required — Apple sent a code to your trusted device")
            if "[.] response type 6" in line:
                wrapper_running = True
                wrapper_needs_2fa = False
                wrapper_2fa_type = ""
                login_successful = True
                if auto_login:
                    target_list.append("Auto-login successful. Ready for downloads.")
                else:
                    target_list.append("Login successful. Ready for downloads.")
                    if email and password:
                        if save_credentials(email, password):
                            target_list.append("Credentials saved for auto-login")
                        else:
                            target_list.append("Credentials kept for this session only")
    except Exception as e:
        target_list.append(f"Error reading wrapper logs: {e}")
    finally:
        if wrapper_process and wrapper_process.poll() is not None:
            exit_code = wrapper_process.poll()
            if not login_successful:
                target_list.append(f"Login failed — wrapper exited with code {exit_code}")
                wrapper_running = False
                wrapper_needs_2fa = False
                wrapper_2fa_type = ""
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



def start_wrapper_login(email: str, password: str, auto_login: bool = False) -> bool:
    global wrapper_process, wrapper_running, wrapper_logs

    if wrapper_process and wrapper_process.poll() is None:
        if not auto_login:
            wrapper_logs.append("Wrapper already running")
        return False

    if not auto_login:
        wrapper_logs.clear()


    prefix = "Auto-login: " if auto_login else ""
    wrapper_logs.append(f"{prefix}Starting wrapper login...")

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
        "--env", "args",
        IMAGE_NAME,
    ]
    wrapper_logs.append(f"{prefix}Launching container: {CONTAINER_NAME}")

    child_env = os.environ.copy()
    child_env["args"] = f"-L {email}:{password}"

    try:
        wrapper_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
            env=child_env,
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
    threading.Thread(target=_queue_worker, daemon=True).start()
    yield


app = FastAPI(title="pies-alac-rip", lifespan=lifespan)


@app.middleware("http")
async def require_api_capability(request: Request, call_next):
    """Require the Tauri-generated capability when running as a sidecar."""
    if request.method != "OPTIONS" and _api_capability:
        supplied = request.headers.get(_API_CAPABILITY_HEADER) or request.query_params.get("token")
        if not supplied or not secrets.compare_digest(supplied, _api_capability):
            return Response(status_code=401)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    # Tauri's Linux webview uses http://tauri.localhost. Keep the Vite origin
    # only for local development; do not expose the loopback API to arbitrary
    # browser origins.
    allow_origins=["http://tauri.localhost", "http://localhost:1420"],
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["content-type", _API_CAPABILITY_HEADER],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/diagnostics")
def get_diagnostics():
    def check(label: str, ok: bool, detail: str = "") -> dict:
        return {"label": label, "ok": ok, "detail": detail}

    results: list[dict] = []

    for command, label, optional in (
        ("podman", "Podman", False),
        ("go", "Go", False),
        ("ffmpeg", "FFmpeg", False),
        ("flac", "FLAC", True),
        ("MP4Box", "MP4Box", False),
        ("mp4decrypt", "mp4decrypt", True),
    ):
        available = shutil.which(command) is not None
        if available:
            detail = "available"
        elif optional:
            detail = "optional — not found in PATH"
        else:
            detail = "not found in PATH"
        results.append(check(label, available, detail))

    config_exists = DEFAULT_CONFIG_PATH.exists()
    results.append(check("Config file", config_exists, "available" if config_exists else "not found"))

    if cfg is not None:
        music_ok = cfg.music_dir.exists()
        results.append(check("Music directory", music_ok, "available" if music_ok else "not found"))

        state_ok = cfg.state_dir.exists()
        results.append(check("State directory", state_ok, "available" if state_ok else "not found"))

        alac_ok = bool(cfg.alac_rip_dir) and cfg.alac_rip_dir.exists()
        results.append(check("alac-rip directory", alac_ok, "available" if alac_ok else "not configured — set in Settings"))
        downloader_ok = alac_ok and (cfg.alac_rip_dir / "apple-music-downloader").is_dir()
        results.append(check(
            "Downloader source",
            downloader_ok,
            "available" if downloader_ok else "not found under alac-rip directory",
        ))
        wrapper_ok = alac_ok and (cfg.alac_rip_dir / "wrapper").is_dir()
        results.append(check(
            "Wrapper source",
            wrapper_ok,
            "available" if wrapper_ok else "not found under alac-rip directory",
        ))
    else:
        for label in (
            "Music directory", "State directory", "alac-rip directory",
            "Downloader source", "Wrapper source",
        ):
            results.append(check(label, False, "Config not loaded"))

    return results


@app.get("/system/integrations-health")
def get_integrations_health():
    jellyfin_cfg = cfg.integrations.get("jellyfin", {}) if cfg and isinstance(cfg.integrations, dict) else {}
    navidrome_cfg = cfg.integrations.get("navidrome", {}) if cfg and isinstance(cfg.integrations, dict) else {}
    return {
        "gemini": bool(cfg.gemini_api_key) if cfg else False,
        "lastfm": bool(cfg.lastfm_api_key) if cfg else False,
        "jellyfin": bool(jellyfin_cfg.get("enabled") and jellyfin_cfg.get("server_url")),
        "navidrome": bool(navidrome_cfg.get("enabled") and navidrome_cfg.get("server_url")),
        "strawberry": bool(strawberry_sync.find_strawberry_db() is not None),
    }


class PlaylistIn(BaseModel):
    name: str
    url: str


def _playlist_dict(p) -> dict:
    return {
        "name": p.name,
        "url": p.url,
        "last_synced": p.last_synced,
        "paused": p.paused,
        "thumbnail_url": state.get_playlist_thumbnail(p.name),
    }


@app.get("/playlists")
def get_playlists():
    return [_playlist_dict(p) for p in state.get_playlists()]


@app.post("/playlists", status_code=201)
def add_playlist(body: PlaylistIn):
    try:
        name = _validate_playlist_name(body.name)
        url = _validate_apple_music_url(body.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    state.add_playlist(name, url)
    # Fetch the newly added playlist and return via _playlist_dict for consistency
    from alac_rip.state import Playlist
    playlist = Playlist(name=name, url=url, last_synced=None, paused=False)
    return _playlist_dict(playlist)


@app.delete("/playlists/{name}", status_code=204)
def delete_playlist(name: str):
    state.delete_playlist(name)
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
        try:
            new_name = _validate_playlist_name(body.name)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if new_name in playlists:
            raise HTTPException(409, f"Playlist '{new_name}' already exists")
        state.rename_playlist(name, new_name)
        name = new_name
    if body.paused is not None:
        state.set_playlist_paused(name, body.paused)
    updated = {p.name: p for p in state.get_playlists()}[name]
    return _playlist_dict(updated)


def _log_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return slug or "playlist"


def _run_job(job: dict) -> None:
    url: str = job["url"]
    format_: str = job["format"]
    playlist_name: Optional[str] = job["playlist_name"]
    log_q: queue.Queue = job["log_q"]
    started_at = datetime.now()

    def emit(event: dict) -> None:
        log_q.put(event)

    if cfg is None or not cfg.alac_rip_dir or not cfg.alac_rip_dir.exists():
        emit({"status": "error", "message": "alac_rip_dir not configured"})
        return
    if not cfg.music_dir or not cfg.music_dir.is_absolute():
        emit({"status": "error", "message": "music_dir not configured"})
        return

    amd_dir = cfg.alac_rip_dir / "apple-music-downloader"
    logs_dir = cfg.state_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    if cfg.log_retention_days > 0:
        cutoff = datetime.now().timestamp() - cfg.log_retention_days * 86400
        for _log in logs_dir.glob("*.log"):
            try:
                if _log.stat().st_mtime < cutoff:
                    _log.unlink()
            except OSError:
                pass
    label = _log_slug(playlist_name or "one-off")
    log_path = logs_dir / f"{started_at.strftime('%Y%m%d-%H%M%S')}-{label}.log"

    def write_log(line: str) -> None:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {line}\n")

    def emit_log(phase: str, message: str) -> None:
        write_log(f"[{phase}] {message}")
        emit({"status": "running", "phase": phase, "message": message, "log_path": str(log_path)})

    write_log(f"[session] type={job['type']} url={url}")

    save_folder_key = {"ATMOS": "atmos-save-folder", "AAC": "aac-save-folder"}.get(format_, "alac-save-folder")
    try:
        with open(amd_dir / "config.yaml") as f:
            amd_cfg = yaml.safe_load(f) or {}
        save_folder = Path(amd_cfg.get(save_folder_key, "")).expanduser()
    except Exception as exc:
        msg = _redact_runtime_paths(f"Cannot read downloader config: {exc}")
        emit({"status": "error", "message": msg, "log_path": str(log_path)})
        if playlist_name:
            state.record_sync_run(playlist_name, started_at.isoformat(), datetime.now().isoformat(),
                                  "error", 0, 0, 0, str(log_path), msg)
        return
    if not save_folder or not save_folder.is_absolute():
        msg = f"Downloader save folder not configured ({save_folder_key})"
        emit({"status": "error", "message": msg, "log_path": str(log_path)})
        if playlist_name:
            state.record_sync_run(playlist_name, started_at.isoformat(), datetime.now().isoformat(),
                                  "error", 0, 0, 0, str(log_path), msg)
        return

    try:
        save_folder = validate_staging_dir(
            save_folder,
            cfg.music_dir,
            cfg.state_dir,
            cfg.alac_rip_dir,
        )
    except StagingValidationError as sve:
        msg = _redact_runtime_paths(f"Invalid downloader staging folder: {sve}")
        emit({"status": "error", "message": msg, "log_path": str(log_path)})
        if playlist_name:
            state.record_sync_run(playlist_name, started_at.isoformat(), datetime.now().isoformat(),
                                  "error", 0, 0, 0, str(log_path), msg)
        return


    env = os.environ.copy()
    # Ensure linuxbrew is in PATH for MP4Box and other tools
    linuxbrew_bin = "/home/linuxbrew/.linuxbrew/bin"
    current_path = env.get("PATH", "")
    if linuxbrew_bin not in current_path:
        env["PATH"] = f"{linuxbrew_bin}:{current_path}" if current_path else linuxbrew_bin
    go_bin = shutil.which("go", path=env.get("PATH")) or "go"
    _tmp = tempfile.mkdtemp()
    manifest_path = Path(_tmp) / "manifest.json"

    # ── Pre-flight: diff AM playlist against local DB ─────────────────────────
    skip_file_path: Optional[Path] = None
    _artwork_map: dict[str, str] = {}  # saved for post-manifest artwork backfill

    if playlist_name:
        try:
            emit_log("preflight", "Checking playlist for new tracks…")
            bearer = am_api.fetch_bearer_token()
            storefront = amd_cfg.get("storefront", "us")
            am_tracks = am_api.fetch_public_playlist_tracks(url, bearer, storefront)
            am_ids_set = {t["id"] for t in am_tracks}

            # Retroactive: populate am_track_id for pre-1.5 tracks by title/artist match
            unmatched = state.get_playlist_tracks_without_am_id(playlist_name)
            if unmatched:
                am_by_key: dict[tuple[str, str], str] = {}
                for t in am_tracks:
                    k = (_normalize(t["title"]), _normalize(t["artist"]))
                    if k not in am_by_key:
                        am_by_key[k] = t["id"]
                matched_count = 0
                for db_track in unmatched:
                    key = (_normalize(db_track.title), _normalize(db_track.artist))
                    if key in am_by_key:
                        state.update_track_am_id(db_track.track_id, am_by_key[key])
                        matched_count += 1
                if matched_count:
                    emit_log("preflight", f"Matched {matched_count} existing tracks to AM IDs")

            artwork_map = {
                t["id"]: t["artwork_url"]
                for t in am_tracks
                if t.get("artwork_url") and t.get("id")
            }
            if artwork_map:
                state.bulk_store_artwork(artwork_map)
                _artwork_map = artwork_map

            owned = state.get_playlist_am_ids(playlist_name)
            new_ids = am_ids_set - owned
            skip_ids = owned & am_ids_set
            delisted_ids = owned - am_ids_set

            if delisted_ids:
                playlist_tracks = state.get_playlist_tracks(playlist_name)
                delisted_recorded = 0
                now_str = datetime.now().isoformat()
                for pt in playlist_tracks:
                    # Lookup track AM ID
                    track_obj = state.get_track(pt.track_id)
                    # If this track was mapped to an AM ID that is no longer in upstream playlist
                    # or if track itself is in delisted_ids
                    if track_obj and getattr(track_obj, "am_track_id", None) in delisted_ids:
                        state.record_delisted_track(playlist_name, pt.track_id, now_str)
                        delisted_recorded += 1
                if delisted_recorded:
                    emit_log("preflight", f"Preserved {delisted_recorded} delisted track(s) in streaming graveyard")

            # If tracks were restored/re-added upstream, clear their delisted mark
            for sid in skip_ids:
                # Find track with this AM ID
                for pt in state.get_playlist_tracks(playlist_name):
                    track_obj = state.get_track(pt.track_id)
                    if track_obj and getattr(track_obj, "am_track_id", None) == sid:
                        state.clear_delisted_track(playlist_name, pt.track_id)

            skip_file_path = Path(_tmp) / "skip.json"
            skip_file_path.write_text(json.dumps({"skip_ids": list(skip_ids)}))

            delisted_msg = f", {len(delisted_ids)} unlisted upstream (preserved locally)" if delisted_ids else ""
            emit_log("preflight",
                f"Pre-flight: {len(am_tracks)} tracks in playlist, "
                f"{len(new_ids)} new, {len(skip_ids)} already owned{delisted_msg}"
            )

        except Exception as e:
            owned = state.get_playlist_am_ids(playlist_name)
            if owned:
                skip_file_path = Path(_tmp) / "skip.json"
                skip_file_path.write_text(json.dumps({"skip_ids": list(owned)}))
                emit_log("preflight",
                    f"Pre-flight check failed ({e}), using {len(owned)} locally known IDs as skip list"
                )
            else:
                skip_file_path = None
                emit_log("preflight",
                    f"Pre-flight check failed ({e}), falling back to full download"
                )

    patched_bin = Path.home() / ".local" / "share" / "pies-alac-rip" / "amd-main"
    if patched_bin.exists() and os.access(patched_bin, os.X_OK):
        _amd_bin: list[str] = [str(patched_bin)]
    else:
        _amd_bin = [go_bin, "run", "main.go"]

    if format_ == "ATMOS":
        cmd = _amd_bin + ["--atmos", url]
    elif format_ == "AAC":
        cmd = _amd_bin + ["--aac", url]
    else:
        cmd = _amd_bin + [url]

    if skip_file_path:
        cmd += ["--skip-ids-file", str(skip_file_path)]
    cmd += ["--manifest-out", str(manifest_path)]

    # ── Phase 1: download ──────────────────────────────────────────────────────
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=1, universal_newlines=True,
            cwd=str(amd_dir), env=env,
        )
    except Exception as exc:
        msg = _redact_runtime_paths(str(exc))
        write_log(f"[error] {msg}")
        emit({"status": "error", "message": msg, "log_path": str(log_path)})
        if playlist_name:
            state.record_sync_run(playlist_name, started_at.isoformat(), datetime.now().isoformat(),
                                  "error", 0, 0, 0, str(log_path), msg)
        return

    for line in iter(proc.stdout.readline, ""):
        line = line.strip()
        if line:
            m = _TRACK_PROGRESS_RE.match(line)
            if m:
                current, total, rest = m.groups()
                emit_log("downloading", f"[{current}/{total}] {rest}".rstrip())
            else:
                emit_log("downloading", line)

    exit_code = proc.wait()
    downloader_had_errors = exit_code != 0
    if downloader_had_errors:
        msg = f"Downloader reported errors (exit code {exit_code}); organizing tracks that downloaded successfully anyway"
        write_log(f"[warning] {msg}")
        emit_log("downloading", msg)

    # ── Phase 2: organize ─────────────────────────────────────────────────────
    def on_log(msg: str, _phase: str) -> None:
        emit_log("organizing", msg)

    manifest_files = None
    manifest_entries = []
    if manifest_path.exists():
        try:
            raw_entries = json.loads(manifest_path.read_text())
            if isinstance(raw_entries, list):
                manifest_entries = raw_entries
                manifest_files = [
                    Path(e["local_path"])
                    for e in raw_entries
                    if isinstance(e, dict) and "local_path" in e
                ]
        except Exception as exc:
            write_log(f"[manifest] warning: could not pre-parse manifest: {exc}")

    try:
        engine = SyncEngine(
            state=state,
            music_dir=cfg.music_dir,
            playlist_name=playlist_name,
            on_log=on_log,
            state_dir=cfg.state_dir,
        )
        result = engine.sync(save_folder, manifest_files=manifest_files)
    except Exception as exc:
        msg = _redact_runtime_paths(str(exc))
        write_log(f"[error] {msg}")
        emit({"status": "error", "message": msg, "log_path": str(log_path)})
        if playlist_name:
            state.record_sync_run(playlist_name, started_at.isoformat(), datetime.now().isoformat(),
                                  "error", 0, 0, 0, str(log_path), msg)
        shutil.rmtree(_tmp, ignore_errors=True)
        return

    # ── Process manifest: update am_track_id in DB ────────────────────────────
    if manifest_entries:
        try:
            for entry in manifest_entries:
                rel = Path(entry["local_path"]).relative_to(save_folder)
                track_id = str(rel.with_suffix(".flac"))
                state.update_track_am_id(track_id, entry["am_track_id"])
            write_log(f"[manifest] updated AM IDs for {len(manifest_entries)} tracks")
        except Exception as exc:
            write_log(f"[manifest] warning: could not process manifest: {exc}")


    # Backfill artwork for tracks that just got their am_track_id set by manifest
    if _artwork_map:
        state.bulk_store_artwork(_artwork_map)

    shutil.rmtree(_tmp, ignore_errors=True)

    if playlist_name:
        state.update_playlist_synced(playlist_name)
        state.record_sync_run(
            playlist_name, started_at.isoformat(), datetime.now().isoformat(), "success",
            result.new_count, result.skipped_count, result.error_count, str(log_path),
        )

    # Trigger media server webhooks (Jellyfin / Navidrome) asynchronously
    try:
        if DEFAULT_CONFIG_PATH.exists():
            with open(DEFAULT_CONFIG_PATH) as f_cfg:
                raw_cfg = yaml.safe_load(f_cfg) or {}
            threading.Thread(
                target=integrations.dispatch_media_webhooks,
                args=(raw_cfg,),
                daemon=True
            ).start()
    except Exception as e:
        write_log(f"[integrations] Webhook dispatch warning: {e}")

    write_log(f"[done] {result.new_count} new, {result.skipped_count} skipped, {result.error_count} errors"
              f"{' (downloader reported errors on some tracks; see log)' if downloader_had_errors else ''}")
    emit({"status": "done",
          "new": result.new_count, "skipped": result.skipped_count,
          "errors": result.error_count, "log_path": str(log_path)})


def _queue_worker() -> None:
    global active_job
    while True:
        job = job_queue.get()
        with pending_jobs_lock:
            try:
                pending_jobs.remove(job)
            except ValueError:
                pass
        active_job = job
        job["started"].set()
        try:
            sys.modules[__name__]._run_job(job)
        except Exception as exc:
            job["log_q"].put({"status": "error", "message": _redact_runtime_paths(f"Internal error: {exc}")})
        finally:
            job["log_q"].put(None)  # sentinel: tells _job_event_stream to stop
            active_job = None
            job_queue.task_done()


async def _job_event_stream(job: dict):
    # Phase 0: queued — send position updates until worker picks this job up
    while not job["started"].is_set():
        with pending_jobs_lock:
            try:
                position = pending_jobs.index(job) + 1
            except ValueError:
                position = 0
        yield f"data: {json.dumps({'status': 'queued', 'position': position})}\n\n"
        await asyncio.sleep(0.5)

    # Phase 1+2: drain log_q until sentinel (None)
    while True:
        try:
            event = job["log_q"].get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.05)
            continue
        if event is None:
            break
        yield f"data: {json.dumps(event)}\n\n"


@app.get("/sync/queue")
def get_queue():
    with pending_jobs_lock:
        pending = [
            {
                "id": j["id"],
                "type": j["type"],
                "playlist_name": j.get("playlist_name"),
                "url": j.get("url") if j["type"] == "one-off" else None,
            }
            for j in list(pending_jobs)
        ]
        active = None
        if active_job:
            active = {
                "id": active_job["id"],
                "type": active_job["type"],
                "playlist_name": active_job.get("playlist_name"),
                "url": active_job.get("url") if active_job["type"] == "one-off" else None,
            }
    return {"active": active, "pending": pending}


@app.get("/sync/{name}")
async def sync_playlist(name: str, format: str = "ALAC"):
    try:
        format = _validate_download_format(format)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    playlists = {p.name: p for p in state.get_playlists()}
    if name not in playlists:
        raise HTTPException(404, f"Playlist '{name}' not found")
    if playlists[name].paused:
        raise HTTPException(409, f"Playlist '{name}' is paused")
    if not wrapper_running:
        raise HTTPException(409, "Wrapper not running — log in to Apple Music first")

    with pending_jobs_lock:
        already = any(
            j.get("playlist_name") == name
            for j in list(pending_jobs) + ([active_job] if active_job else [])
        )
    if already:
        raise HTTPException(409, f"'{name}' is already queued or running")

    job: dict = {
        "id": str(uuid.uuid4()),
        "type": "playlist",
        "url": playlists[name].url,
        "format": format,
        "playlist_name": name,
        "log_q": queue.Queue(),
        "started": threading.Event(),
    }
    with pending_jobs_lock:
        pending_jobs.append(job)
    job_queue.put(job)

    return StreamingResponse(
        _job_event_stream(job),
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


@app.get("/home")
def get_home():
    recent_tracks = state.get_recent_tracks(limit=5)
    runs = state.get_recent_runs(limit=1)
    last_sync = None
    if runs:
        r = runs[0]
        last_sync = {
            "run_id": r.id,
            "playlist_name": r.playlist_name,
            "started_at": r.started_at,
            "synced_at": r.ended_at,
            "new_tracks": r.new_count,
        }

    api_key = cfg.lastfm_api_key if cfg else ""
    recommendations: list[dict] = []
    cached_recommendations = state.get_recommendation_cache()
    recommendations_available = bool(api_key or cached_recommendations)
    recommendation_source = "unavailable"
    recommendations_live = False

    if api_key:
        try:
            top_artists = state.get_top_artists(limit=10)
            library_lower = {a.lower() for a in state.get_all_artists()}
            excluded_lower = {a.lower() for a in state.get_recommendation_exclusions()}
            seen: dict[str, float] = {}
            for artist in top_artists:
                try:
                    for s in lastfm_api.get_similar_artists(artist, api_key, limit=5):
                        recommendations_live = True
                        name_lower = s["name"].lower()
                        if name_lower not in library_lower and name_lower not in excluded_lower and name_lower not in seen:
                            seen[name_lower] = s["match"]
                            recommendations.append({
                                "artist": s["name"],
                                "similar_to": artist,
                                "reason": f"Similar to {artist} in your library",
                                "match": s["match"],
                                "lastfm_url": s["url"],
                            })
                except Exception:
                    pass
            for genre in state.get_recommendation_genres():
                try:
                    for tagged_artist in lastfm_api.get_tag_top_artists(genre, api_key, limit=5):
                        recommendations_live = True
                        name_lower = tagged_artist["name"].lower()
                        if name_lower not in library_lower and name_lower not in excluded_lower and name_lower not in seen:
                            seen[name_lower] = 0.35
                            recommendations.append({
                                "artist": tagged_artist["name"],
                                "similar_to": genre,
                                "reason": f"Matches your {genre} preference",
                                "match": 0.35,
                                "lastfm_url": tagged_artist["url"],
                            })
                except Exception:
                    pass
            recommendations.sort(key=lambda x: x["match"], reverse=True)
            recommendations = recommendations[:10]
        except Exception:
            pass

    # Fetch top tracks + albums for the top 3 recommended artists
    recommended_tracks: list[dict] = []
    recommended_albums: list[dict] = []
    if api_key and recommendations:
        for rec in recommendations[:3]:
            try:
                for t in lastfm_api.get_artist_top_tracks(rec["artist"], api_key, limit=3):
                    recommended_tracks.append(t)
            except Exception:
                pass
            try:
                for a in lastfm_api.get_artist_top_albums(rec["artist"], api_key, limit=2):
                    recommended_albums.append(a)
            except Exception:
                pass

    if recommendations_live:
        state.set_recommendation_cache({
            "recommendations": recommendations,
            "recommended_tracks": recommended_tracks,
            "recommended_albums": recommended_albums,
        })
        recommendation_source = "live"
    elif cached_recommendations:
        recommendations = cached_recommendations.get("recommendations", [])
        recommended_tracks = cached_recommendations.get("recommended_tracks", [])
        recommended_albums = cached_recommendations.get("recommended_albums", [])
        recommendation_source = "cached"
    return {
        "recent_tracks": recent_tracks,
        "recommendations": recommendations,
        "recommended_tracks": recommended_tracks,
        "recommended_albums": recommended_albums,
        "recommendations_available": recommendations_available,
        "recommendation_source": recommendation_source,
        "recommendations_updated_at": (
            cached_recommendations.get("updated_at") if recommendation_source == "cached" and cached_recommendations else None
        ),
        "last_sync": last_sync,
    }


class RecommendationExclusionRequest(BaseModel):
    artist: str


@app.post("/recommendations/exclusions")
def exclude_recommendation_artist(body: RecommendationExclusionRequest):
    artist = body.artist.strip()
    if not artist or len(artist) > 200:
        raise HTTPException(422, "Artist name must be between 1 and 200 characters")
    state.exclude_recommendation_artist(artist)
    return {"status": "ok"}


@app.get("/recommendations/exclusions")
def get_recommendation_exclusions():
    return {"artists": state.get_recommendation_exclusions()}


@app.delete("/recommendations/exclusions")
def clear_recommendation_exclusions():
    state.clear_recommendation_exclusions()
    return {"status": "ok"}


@app.delete("/recommendations/exclusions/{artist}")
def include_recommendation_artist(artist: str):
    artist = artist.strip()
    if not artist:
        raise HTTPException(422, "Artist name is required")
    state.include_recommendation_artist(artist)
    return {"status": "ok"}


class RecommendationPreferencesRequest(BaseModel):
    genres: list[str]


@app.get("/recommendations/preferences")
def get_recommendation_preferences():
    return {"genres": state.get_recommendation_genres()}


@app.put("/recommendations/preferences")
def set_recommendation_preferences(body: RecommendationPreferencesRequest):
    genres: list[str] = []
    for value in body.genres:
        genre = value.strip().lower()
        if not genre or len(genre) > 60:
            raise HTTPException(422, "Each genre must be between 1 and 60 characters")
        if genre not in genres:
            genres.append(genre)
    if len(genres) > 10:
        raise HTTPException(422, "Choose at most 10 genre preferences")
    state.set_recommendation_genres(genres)
    return {"genres": genres}


@app.get("/library-profile")
def library_profile():
    return {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "library": state.get_library_profile(),
        "privacy": "Contains artist, album, and aggregate track counts only; no paths, URLs, credentials, or tokens.",
    }


class RevealRequest(BaseModel):
    local_path: str


class StrawberryExportRequest(BaseModel):
    playlist_name: str


class M3uSaveRequest(BaseModel):
    path: str


def _playlist_m3u(tracks) -> str:
    """Return a portable extended-M3U playlist for the local track paths."""
    lines = ["#EXTM3U"]
    for track in tracks:
        artist = track.artist.replace("\n", " ").replace("\r", " ")
        title = track.title.replace("\n", " ").replace("\r", " ")
        lines.append(f"#EXTINF:-1,{artist} - {title}")
        lines.append(track.local_path)
    return "\n".join(lines) + "\n"


def _m3u_save_target(value: str) -> Path:
    target = Path(value).expanduser()
    if not target.is_absolute() or target.suffix.lower() not in {".m3u", ".m3u8"}:
        raise ValueError("Choose an absolute .m3u or .m3u8 file path")
    if not target.parent.is_dir():
        raise ValueError("The selected folder does not exist")
    return target


@app.get("/playlists/{name}/duplicates")
def get_playlist_duplicates(name: str):
    try:
        name = _validate_playlist_name(name)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if state is None:
        raise HTTPException(503, "Library is not ready")
    duplicates = state.get_duplicate_tracks_in_playlist(name)
    return {"playlist_name": name, "duplicates": duplicates, "count": len(duplicates)}


@app.post("/playlists/{name}/deduplicate")
def deduplicate_playlist(name: str):
    try:
        name = _validate_playlist_name(name)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if state is None:
        raise HTTPException(503, "Library is not ready")
    result = state.deduplicate_playlist(name)
    return result


@app.get("/playlists/{name}/m3u")
def export_playlist_m3u(name: str):
    try:
        name = _validate_playlist_name(name)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    tracks = state.get_playlist_tracks(name)
    if not tracks:
        raise HTTPException(status_code=404, detail="Playlist has no downloaded tracks")
    return PlainTextResponse(
        _playlist_m3u(tracks),
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": 'attachment; filename="playlist.m3u8"'},
    )


@app.post("/playlists/{name}/m3u/save")
def save_playlist_m3u(name: str, body: M3uSaveRequest):
    try:
        name = _validate_playlist_name(name)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    try:
        target = _m3u_save_target(body.path)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    tracks = state.get_playlist_tracks(name)
    if not tracks:
        raise HTTPException(status_code=404, detail="Playlist has no downloaded tracks")
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as file:
            file.write(_playlist_m3u(tracks))
            temporary_path = Path(file.name)
        temporary_path.replace(target)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise HTTPException(500, "Could not save the M3U file") from None
    return {"status": "ok"}


@app.post("/strawberry/export")
def strawberry_export(req: StrawberryExportRequest):
    """Replace (or create) the playlist of this name in Strawberry's DB."""
    db_path = strawberry_sync.find_strawberry_db()
    if db_path is None:
        raise HTTPException(
            status_code=404,
            detail="Strawberry's database wasn't found. Install Strawberry (flatpak or native) and run it once.",
        )
    if strawberry_sync.is_strawberry_running():
        raise HTTPException(
            status_code=409,
            detail="Strawberry is open — close it first so its database can be updated.",
        )
    tracks = state.get_playlist_tracks(req.playlist_name)
    if not tracks:
        raise HTTPException(status_code=400, detail=f"playlist '{req.playlist_name}' has no tracks")
    try:
        result = strawberry_sync.export_playlist(db_path, req.playlist_name, tracks)
    except strawberry_sync.StrawberryBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_redact_runtime_paths(f"export failed: {exc}"))
    return result


class DapExportRequest(BaseModel):
    playlist_name: str
    target_dir: str
    format: str = "opus"
    bitrate: Optional[str] = None


@app.post("/export/dap")
def dap_export(req: DapExportRequest):
    if cfg is None or state is None:
        raise HTTPException(503, "Library is not ready")

    try:
        playlist_name = _validate_playlist_name(req.playlist_name)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    target_path = Path(req.target_dir).expanduser()
    if not target_path.is_absolute():
        raise HTTPException(422, "Target directory must be an absolute path")

    try:
        result = export_dap_playlist(
            music_dir=cfg.music_dir,
            playlist_name=playlist_name,
            target_dir=target_path,
            format=req.format,
            bitrate=req.bitrate,
            state=state,
        )
    except DapExportError as exc:
        msg = str(exc)
        if "has no tracks" in msg:
            raise HTTPException(404, msg)
        raise HTTPException(422, _redact_runtime_paths(msg))
    except Exception as exc:
        raise HTTPException(500, _redact_runtime_paths(f"DAP export failed: {exc}"))

    return result


@app.post("/reveal-track")
def reveal_track(req: RevealRequest):
    """Open the track in the file manager with the file selected.

    Tries the standard org.freedesktop.FileManager1 D-Bus interface (Files,
    Dolphin, Caja, etc. all implement this and will highlight the specific
    file). Falls back to xdg-open on the parent directory if D-Bus fails.
    """
    from urllib.parse import quote
    p = _resolve_library_file(req.local_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"file not found: {req.local_path}")

    file_uri = "file://" + quote(str(p.absolute()), safe="/")

    if shutil.which("gdbus"):
        try:
            r = subprocess.run(
                ["gdbus", "call", "--session",
                 "--dest", "org.freedesktop.FileManager1",
                 "--object-path", "/org/freedesktop/FileManager1",
                 "--method", "org.freedesktop.FileManager1.ShowItems",
                 f"['{file_uri}']", ""],
                capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                return {"ok": True, "method": "filemanager-d-bus"}
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    if shutil.which("xdg-open"):
        try:
            subprocess.Popen(
                ["xdg-open", str(p.parent)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return {"ok": True, "method": "xdg-open-parent"}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=_redact_runtime_paths(str(exc)))

    raise HTTPException(status_code=501, detail="No file manager found (install xdg-utils)")


@app.get("/sync-runs/{run_id}/tracks")
def get_run_tracks(run_id: int):
    runs = [r for r in state.get_recent_runs(limit=200) if r.id == run_id]
    if not runs:
        return {"tracks": []}
    r = runs[0]
    return {
        "run_id": r.id,
        "playlist_name": r.playlist_name,
        "tracks": state.get_tracks_in_run(r.playlist_name, r.started_at, r.ended_at),
    }


@app.get("/sync-history")
def get_sync_history(limit: int = Query(default=30, ge=1, le=100)):
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
def get_playlist_sync_history(name: str, limit: int = Query(default=20, ge=1, le=100)):
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


class VerifyIntegrityRequest(BaseModel):
    limit: Optional[int] = None


class LibraryRepairRequest(BaseModel):
    action: str  # "regenerate_m3u8" | "prune_missing" | "adopt_orphans"
    track_ids: Optional[list[str]] = None
    file_paths: Optional[list[str]] = None


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
                "artwork_url": t.artwork_url,
                "has_lyrics": Path(t.local_path).with_suffix(".lrc").is_file() if t.local_path else False,
            }
            for t in tracks
        ]
    return result


@app.get("/library/tracks")
def get_library_tracks():
    if state is None or cfg is None:
        raise HTTPException(503, "Library is not ready")
    tracks = state.get_all_tracks_with_provenance()
    result = []
    for t in tracks:
        lp = t.get("local_path", "")
        p = Path(lp).expanduser().resolve() if lp else None
        exists = p.is_file() if p else False
        has_lyrics = (p.with_suffix(".lrc").is_file()) if (p and exists) else False
        size = p.stat().st_size if (p and exists) else 0
        fmt = p.suffix.lstrip(".").upper() if (p and p.suffix) else "UNKNOWN"
        result.append({
            **t,
            "exists_on_disk": exists,
            "has_lyrics": has_lyrics,
            "file_size": size,
            "format": fmt,
        })
    return result


@app.get("/library/stats")
def get_library_stats():
    if state is None or cfg is None:
        raise HTTPException(503, "Library is not ready")
    return state.get_library_stats()


@app.get("/library/audit")
def get_library_audit():
    if state is None or cfg is None:
        raise HTTPException(503, "Library is not ready")
    return audit.audit_library(cfg.music_dir, state)


@app.post("/library/verify-integrity")
def post_verify_integrity(req: Optional[VerifyIntegrityRequest] = None):
    if state is None or cfg is None:
        raise HTTPException(503, "Library is not ready")
    limit = req.limit if req else None
    return audit.verify_library_flac_integrity(cfg.music_dir, state, limit=limit)


@app.post("/library/repair")
def post_library_repair(req: LibraryRepairRequest):
    if state is None or cfg is None:
        raise HTTPException(503, "Library is not ready")

    if req.action == "regenerate_m3u8":
        return audit.repair_playlists(cfg.music_dir, state)
    elif req.action == "prune_missing":
        track_ids = req.track_ids
        if track_ids is None:
            audit_res = audit.audit_library(cfg.music_dir, state)
            track_ids = [m["track_id"] for m in audit_res["missing_files"]]
        pruned_count = state.prune_missing_tracks(track_ids)
        return {"status": "ok", "action": req.action, "pruned_count": pruned_count}
    elif req.action == "adopt_orphans":
        return audit.adopt_orphaned_files(cfg.music_dir, state, req.file_paths)
    else:
        raise HTTPException(400, f"Unsupported repair action: {req.action}")


@app.get("/streaming-graveyard")
def get_streaming_graveyard(playlist_name: Optional[str] = None):
    tracks = state.get_delisted_tracks(playlist_name)
    return {"tracks": tracks, "count": len(tracks)}


@app.get("/tracks/{track_id:path}/lyrics")
@app.get("/api/v1/tracks/lyrics")
@app.get("/track-lyrics")
def get_track_lyrics(track_id: Optional[str] = None):
    if state is None:
        raise HTTPException(503, "Library is not ready")

    if not track_id:
        raise HTTPException(400, "Missing track_id parameter")

    track = state.get_track(track_id)
    if not track:
        raise HTTPException(404, f"Track {track_id} not found")

    lyrics_text = ""
    source = "none"
    track_path = None

    if track.local_path:
        try:
            track_path = _resolve_library_file(track.local_path)
            lrc_path = track_path.with_suffix(".lrc")
            if lrc_path.is_file() and not lrc_path.is_symlink():
                lyrics_text = lrc_path.read_text(encoding="utf-8", errors="replace")
                source = "lrc"
            elif track_path.is_file():
                tags = read_tags(track_path)
                if tags.get("lyrics"):
                    lyrics_text = tags["lyrics"]
                    source = "embedded"
        except Exception:
            pass

    # Phase 6: LRCLIB fallback if no lyrics found locally
    if not lyrics_text and track.title and track.artist:
        try:
            lrclib_res = lyrics.fetch_lrclib_lyrics(track.title, track.artist, track.album)
            if lrclib_res:
                if lrclib_res.get("syncedLyrics"):
                    lyrics_text = lrclib_res["syncedLyrics"]
                    source = "lrclib"
                elif lrclib_res.get("plainLyrics"):
                    lyrics_text = lrclib_res["plainLyrics"]
                    source = "lrclib"

                # Persist to .lrc sidecar file next to track if local path resolved
                if lyrics_text and track_path and track_path.is_file():
                    lyrics.save_lrc_file(track_path.with_suffix(".lrc"), lyrics_text)
        except Exception:
            pass

    is_synced = bool(re.search(r"\[\d{2}:\d{2}", lyrics_text)) if lyrics_text else False

    parsed_lines = []
    if lyrics_text:
        lrc_pattern = re.compile(r"^\[(\d{2}):(\d{2})(?:\.(\d{2,3}))?\](.*)$")
        for line in lyrics_text.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            m = lrc_pattern.match(line_str)
            if m:
                mins = int(m.group(1))
                secs = int(m.group(2))
                frac = m.group(3) or "0"
                ms = int(frac.ljust(3, "0")[:3])
                total_ms = (mins * 60 + secs) * 1000 + ms
                parsed_lines.append({
                    "time_ms": total_ms,
                    "timestamp": f"{m.group(1)}:{m.group(2)}.{frac}",
                    "text": m.group(4).strip(),
                })
            else:
                parsed_lines.append({
                    "text": line_str,
                })

    return {
        "track_id": track_id,
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "lyrics": lyrics_text,
        "synced": is_synced,
        "source": source,
        "lines": parsed_lines,
    }



@app.get("/track-art")
def get_track_art(path: str):
    track_path = _resolve_library_file(path)
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
        raise HTTPException(500, _redact_runtime_paths(str(exc)))


class ConfigUpdate(BaseModel):
    music_dir: Optional[str] = None
    state_dir: Optional[str] = None
    alac_rip_dir: Optional[str] = None
    log_retention_days: Optional[int] = None
    lastfm_api_key: Optional[str] = None
    lastfm_shared_secret: Optional[str] = None
    lastfm_username: Optional[str] = None
    gemini_api_key: Optional[str] = None
    integrations: Optional[dict] = None

    @field_validator("music_dir", "state_dir", "alac_rip_dir")
    @classmethod
    def paths_must_be_absolute(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if "\x00" in value:
            raise ValueError("Path cannot contain a null byte")
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("Path must be absolute (or begin with ~)")
        return value

    @field_validator("log_retention_days")
    @classmethod
    def log_retention_must_be_reasonable(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and not 0 <= value <= 3650:
            raise ValueError("Log retention must be between 0 and 3650 days")
        return value


_CONFIG_OMIT = {"apple_id_password", "media_user_token", "lastfm_api_key", "lastfm_shared_secret", "gemini_api_key", "github_remote"}


def _sanitize_config_dict(data: dict) -> dict:
    """Recursively redact sensitive API tokens, passwords, and integration secrets."""
    sanitized = {}
    for k, v in data.items():
        if k in _CONFIG_OMIT:
            continue
        if k == "integrations" and isinstance(v, dict):
            san_integ = {}
            for s_name, s_cfg in v.items():
                if isinstance(s_cfg, dict):
                    copied = dict(s_cfg)
                    for secret_field in ("api_key", "token", "password", "salt"):
                        if secret_field in copied and copied[secret_field]:
                            copied[secret_field] = "********"
                            copied[f"{secret_field}_configured"] = True
                    san_integ[s_name] = copied
                else:
                    san_integ[s_name] = s_cfg
            sanitized[k] = san_integ
        else:
            sanitized[k] = v
    return sanitized


@app.get("/config")
def get_config():
    try:
        with open(DEFAULT_CONFIG_PATH) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise HTTPException(503, "Config file not found")
    sanitized = _sanitize_config_dict(data)
    sanitized["gemini_api_key_configured"] = bool(data.get("gemini_api_key"))
    sanitized["lastfm_api_key_configured"] = bool(data.get("lastfm_api_key"))
    sanitized["lastfm_shared_secret_configured"] = bool(data.get("lastfm_shared_secret"))
    return sanitized


@app.put("/config")
def update_config(body: ConfigUpdate):
    current: dict = {}
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH) as f:
            current = yaml.safe_load(f) or {}
    current.pop("github_remote", None)

    updates = body.model_dump(exclude_none=True)
    # Preserve existing secrets if masked values were sent back
    if "integrations" in updates and isinstance(updates["integrations"], dict):
        cur_integ = current.get("integrations", {})
        for s_name, s_cfg in updates["integrations"].items():
            if isinstance(s_cfg, dict) and s_name in cur_integ:
                cur_s = cur_integ[s_name]
                for secret_field in ("api_key", "token", "password", "salt"):
                    if s_cfg.get(secret_field) == "********":
                        s_cfg[secret_field] = cur_s.get(secret_field, "")
                    s_cfg.pop(f"{secret_field}_configured", None)

    current.update(updates)
    save_config_file(DEFAULT_CONFIG_PATH, current)
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
    global wrapper_process, wrapper_running, wrapper_logs, wrapper_needs_2fa, wrapper_2fa_type
    if wrapper_process and wrapper_process.poll() is None:
        subprocess.run(["podman", "stop", CONTAINER_NAME], capture_output=True)
        wrapper_process.terminate()
        wrapper_logs.append("Wrapper stopped by user")
        wrapper_running = False
        wrapper_needs_2fa = False
        wrapper_2fa_type = ""
        return {"status": "ok", "msg": "Wrapper stopped"}
    return {"status": "error", "msg": "Wrapper not running"}


class TwoFARequest(BaseModel):
    code: str


@app.post("/wrapper/2fa")
def submit_2fa(body: TwoFARequest):
    global wrapper_needs_2fa, wrapper_2fa_type
    if not wrapper_needs_2fa:
        return {"status": "error", "msg": "2FA not required"}
    if not wrapper_process or wrapper_process.poll() is not None:
        return {"status": "error", "msg": "Wrapper not running"}
    try:
        wrapper_process.stdin.write(f"{body.code}\n")
        wrapper_process.stdin.flush()
        wrapper_logs.append("2FA code submitted")
        wrapper_needs_2fa = False
        wrapper_2fa_type = ""
        return {"status": "ok", "msg": "2FA code submitted"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


@app.get("/wrapper/status")
def get_wrapper_status():
    global wrapper_running, wrapper_process, wrapper_needs_2fa, wrapper_2fa_type
    if wrapper_process and wrapper_process.poll() is not None and wrapper_running:
        wrapper_running = False
    return {
        "running": wrapper_running,
        "needs_2fa": wrapper_needs_2fa,
        "2fa_type": wrapper_2fa_type,
        "logs": list(wrapper_logs),
    }


@app.get("/download/one-off")
async def download_one_off(url: str = "", format: str = "ALAC"):
    try:
        url = _validate_apple_music_url(url)
        format = _validate_download_format(format)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not wrapper_running:
        raise HTTPException(409, "Wrapper not running — log in to Apple Music first")

    job: dict = {
        "id": str(uuid.uuid4()),
        "type": "one-off",
        "url": url,
        "format": format,
        "playlist_name": None,
        "log_q": queue.Queue(),
        "started": threading.Event(),
    }
    with pending_jobs_lock:
        pending_jobs.append(job)
    job_queue.put(job)

    return StreamingResponse(
        _job_event_stream(job),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Audio Streaming & Media Integrations ──────────────────────────────────────

@app.get("/api/v1/stream/{track_id:path}")
@app.get("/api/v1/stream")
@app.get("/stream/{track_id:path}")
@app.get("/stream")
def stream_audio_track(track_id: Optional[str] = None, range_header: Optional[str] = Header(None, alias="Range")):
    """
    HTTP Range-capable audio streaming endpoint for local ALAC/FLAC track auditioning.
    Guarantees strict path isolation inside music_dir and strict Range parsing.
    """
    if state is None or cfg is None:
        raise HTTPException(503, "Library is not ready")

    if not track_id:
        raise HTTPException(400, "Missing track_id parameter")

    track = state.get_track(track_id)
    if not track or not track.local_path:
        raise HTTPException(404, f"Track {track_id} not found")

    try:
        file_path = _resolve_library_file(track.local_path)
    except Exception:
        raise HTTPException(404, "Track file could not be found or resolved")

    if not file_path.is_file():
        raise HTTPException(404, "Track audio file does not exist on disk")

    file_size = file_path.stat().st_size
    suffix = file_path.suffix.lower()
    media_type = "audio/mp4" if suffix in (".m4a", ".alac") else ("audio/flac" if suffix == ".flac" else "application/octet-stream")

    # If no range header is requested, stream entire file
    if not range_header:
        def iterfile():
            with open(file_path, mode="rb") as f:
                while chunk := f.read(65536):
                    yield chunk
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": media_type,
        }
        return StreamingResponse(iterfile(), headers=headers, media_type=media_type)

    # Parse Range: bytes=start-end strictly with fullmatch
    range_match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header.strip())
    if not range_match:
        raise HTTPException(416, "Invalid Range header", headers={"Content-Range": f"bytes */{file_size}"})

    start = int(range_match.group(1))
    end = int(range_match.group(2)) if range_match.group(2) else file_size - 1

    if start >= file_size or end >= file_size or start > end:
        raise HTTPException(416, "Range Not Satisfiable", headers={"Content-Range": f"bytes */{file_size}"})

    chunk_length = end - start + 1

    def iter_range(start_pos: int, length: int):
        with open(file_path, mode="rb") as f:
            f.seek(start_pos)
            bytes_left = length
            while bytes_left > 0:
                chunk_to_read = min(65536, bytes_left)
                data = f.read(chunk_to_read)
                if not data:
                    break
                bytes_left -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_length),
        "Content-Type": media_type,
    }
    return StreamingResponse(iter_range(start, chunk_length), status_code=206, headers=headers, media_type=media_type)


@app.get("/api/v1/waveform/{track_id:path}")
@app.get("/api/v1/waveform")
@app.get("/waveform/{track_id:path}")
@app.get("/waveform")
def get_track_waveform(track_id: Optional[str] = None, points: int = Query(100, ge=10, le=1000)):
    """
    Returns downsampled audio waveform amplitude peaks and duration for a library track.
    Cached in SQLite state for instant retrieval on repeat plays.
    """
    if state is None or cfg is None:
        raise HTTPException(503, "Library is not ready")

    if not track_id:
        raise HTTPException(400, "Missing track_id parameter")

    track = state.get_track(track_id)
    if not track or not track.local_path:
        raise HTTPException(404, f"Track {track_id} not found")

    try:
        file_path = _resolve_library_file(track.local_path)
    except Exception:
        raise HTTPException(404, "Track file could not be found or resolved")

    if not file_path.is_file():
        raise HTTPException(404, "Track audio file does not exist on disk")

    try:
        result = waveform.get_or_extract_waveform(
            track_id=track_id,
            file_path=file_path,
            state_mgr=state,
            points=points,
        )
        return result
    except waveform.WaveformExtractionError as e:
        raise HTTPException(500, f"Waveform extraction error: {e}")
    except Exception as e:
        raise HTTPException(500, f"Failed to extract waveform: {e}")


# ── Metadata Editing & Batch Tagging ──────────────────────────────────────────

class BatchTagFields(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    album_artist: Optional[str] = None
    genre: Optional[str] = None
    year: Optional[str] = None
    track_num: Optional[int] = None
    disc_num: Optional[int] = None
    lyrics: Optional[str] = None
    comment: Optional[str] = None


class BatchTagRequest(BaseModel):
    track_ids: list[str]
    fields: BatchTagFields
    cover_art_base64: Optional[str] = None
    cover_art_mime: Optional[str] = "image/jpeg"
    remove_cover: bool = False
    reorganize_files: bool = True


@app.post("/api/v1/tracks/batch-tag")
@app.post("/tracks/batch-tag")
def post_batch_tag_tracks(req: BatchTagRequest):
    """
    Applies batch metadata updates and/or cover art replacement across multiple tracks.
    Safely reorganizes directories and synchronizes SQLite database state records.
    """
    if state is None or cfg is None:
        raise HTTPException(503, "Library is not ready")

    if not req.track_ids:
        raise HTTPException(400, "No track_ids specified")

    # Validate that track_ids exist in library and resolve music directory
    fields_dict = req.fields.model_dump(exclude_unset=True, exclude_none=True)

    try:
        result = metadata_editor.batch_update_tracks(
            state=state,
            music_dir=cfg.music_dir,
            track_ids=req.track_ids,
            fields=fields_dict,
            cover_art_base64=req.cover_art_base64,
            cover_art_mime=req.cover_art_mime or "image/jpeg",
            remove_cover=req.remove_cover,
            reorganize_files=req.reorganize_files,
        )
        return result
    except metadata_editor.MetadataEditorError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Batch metadata update failed: {e}")


@app.get("/api/v1/tracks/cover")
@app.get("/tracks/{track_id:path}/cover")
@app.get("/tracks/cover")
def get_track_embedded_cover(track_id: Optional[str] = None):
    """Extract and return embedded cover artwork for a track."""
    if state is None or cfg is None:
        raise HTTPException(503, "Library is not ready")

    if not track_id:
        raise HTTPException(400, "Missing track_id parameter")

    track = state.get_track(track_id)
    if not track or not track.local_path:
        raise HTTPException(404, f"Track {track_id} not found")

    file_path = Path(track.local_path).expanduser().resolve()
    if not file_path.is_file():
        raise HTTPException(404, f"Audio file not found on disk for track {track_id}")

    # Check path isolation
    try:
        file_path.relative_to(cfg.music_dir)
    except ValueError:
        raise HTTPException(403, "Access denied: audio file outside library root")

    cover_info = metadata_editor.extract_embedded_cover(file_path)
    if not cover_info:
        raise HTTPException(404, "No embedded cover artwork found")

    cover_bytes, mime = cover_info
    return Response(content=cover_bytes, media_type=mime)


class JellyfinTestRequest(BaseModel):
    server_url: str
    api_key: str


@app.post("/integrations/jellyfin/test")
def post_test_jellyfin(req: JellyfinTestRequest):
    ok, msg = integrations.test_jellyfin_connection(req.server_url, req.api_key)
    return {"success": ok, "message": msg}


class NavidromeTestRequest(BaseModel):
    server_url: str
    user: str
    token: str
    salt: str


@app.post("/integrations/navidrome/test")
def post_test_navidrome(req: NavidromeTestRequest):
    ok, msg = integrations.test_navidrome_connection(req.server_url, req.user, req.token, req.salt)
    return {"success": ok, "message": msg}


class DownloadRequestIn(BaseModel):
    url: str
    format: str = "ALAC"
    requester: str = "local"
    notes: str = ""


def _get_request_store() -> RequestStore:
    if cfg is None:
        raise HTTPException(503, "Configuration is not ready")
    db_p = cfg.state_dir / "download_requests.db"
    return RequestStore(db_p)


@app.get("/api/v1/requests")
def get_download_requests(status: Optional[str] = None):
    store = _get_request_store()
    reqs = store.list_requests(status=status)
    return [
        {
            "id": r.id,
            "url": r.url,
            "format": r.format,
            "requester": r.requester,
            "status": r.status,
            "notes": r.notes,
            "created_at": r.created_at,
        }
        for r in reqs
    ]


@app.post("/api/v1/requests", status_code=201)
def post_download_request(body: DownloadRequestIn):
    store = _get_request_store()
    req = store.add_request(
        url=body.url,
        format=body.format,
        requester=body.requester,
        notes=body.notes,
    )
    return {
        "id": req.id,
        "url": req.url,
        "format": req.format,
        "requester": req.requester,
        "status": req.status,
        "notes": req.notes,
        "created_at": req.created_at,
    }


class UpdateRequestStatusIn(BaseModel):
    status: str


@app.patch("/api/v1/requests/{req_id}")
def patch_download_request(req_id: str, body: UpdateRequestStatusIn):
    store = _get_request_store()
    ok = store.update_request_status(req_id, body.status)
    if not ok:
        raise HTTPException(404, "Request not found")
    return {"status": "ok"}


@app.delete("/api/v1/requests/{req_id}", status_code=204)
def delete_download_request(req_id: str):
    store = _get_request_store()
    ok = store.delete_request(req_id)
    if not ok:
        raise HTTPException(404, "Request not found")
    return None


class ImportPlaylistParseRequest(BaseModel):
    source_type: str  # "url" | "csv" | "m3u"
    content: str  # URL string or raw file text


@app.post("/playlist/parse-import")
def post_parse_playlist_import(req: ImportPlaylistParseRequest):
    """Parse external playlist URLs (Spotify/Tidal/Qobuz) or CSV/M3U and match against Apple Music."""
    raw_tracks = []
    bearer = ""
    try:
        bearer = am_api.fetch_bearer_token()
    except Exception:
        pass

    if req.source_type == "url":
        url = req.content.strip()
        sp_id = playlist_import.parse_spotify_playlist_url(url)
        if sp_id:
            raw_tracks = playlist_import.fetch_spotify_public_playlist(sp_id)
        else:
            # Check if it's already an Apple Music playlist
            if "music.apple.com" in url:
                try:
                    am_tracks = am_api.fetch_public_playlist_tracks(url, bearer)
                    return {
                        "source_type": "apple_music",
                        "track_count": len(am_tracks),
                        "matches": [
                            {
                                "original_title": t.get("title", ""),
                                "original_artist": t.get("artist", ""),
                                "original_album": "",
                                "matched": True,
                                "match_score": 1.0,
                                "am_track": t,
                            }
                            for t in am_tracks
                        ],
                    }
                except Exception as e:
                    raise HTTPException(400, f"Failed to parse Apple Music playlist: {e}")
            else:
                # Unsupported URL source
                raise HTTPException(400, "Unsupported playlist URL. Supported: Spotify, Apple Music, CSV, M3U.")
    elif req.source_type == "csv":
        raw_tracks = playlist_import.parse_csv_tracks(req.content)
    elif req.source_type in ("m3u", "m3u8"):
        raw_tracks = playlist_import.parse_m3u_tracks(req.content)
    else:
        raise HTTPException(400, f"Unsupported source type: {req.source_type}")

    if not raw_tracks:
        return {"source_type": req.source_type, "track_count": 0, "matches": []}

    matches = playlist_import.match_tracks_to_apple_music(raw_tracks, bearer) if bearer else [
        {
            "original_title": t.get("title", ""),
            "original_artist": t.get("artist", ""),
            "original_album": t.get("album", ""),
            "original_isrc": t.get("isrc", ""),
            "matched": False,
            "match_score": 0.0,
            "am_track": None,
        }
        for t in raw_tracks
    ]

    return {
        "source_type": req.source_type,
        "track_count": len(raw_tracks),
        "matches": matches,
    }


class GeminiCurateRequest(BaseModel):
    prompt: str
    track_count: int = 20
    model: Optional[str] = None
    library_only: bool = False


@app.post("/gemini/curate")
def post_gemini_curate(req: GeminiCurateRequest):
    """Curate a custom playlist via Gemini AI, matching tracks against Apple Music."""
    if cfg is None:
        raise HTTPException(503, "Configuration is not ready")

    api_key = cfg.gemini_api_key
    if not api_key:
        # Check config file directly
        try:
            if DEFAULT_CONFIG_PATH.exists():
                with open(DEFAULT_CONFIG_PATH) as f:
                    raw = yaml.safe_load(f) or {}
                api_key = raw.get("gemini_api_key", "")
        except Exception:
            pass

    if not api_key:
        raise HTTPException(400, "Gemini API key is not configured. Please add it in Settings.")

    bearer = ""
    try:
        bearer = am_api.fetch_bearer_token()
    except Exception:
        pass

    result = gemini_ai.generate_smart_playlist(
        prompt=req.prompt,
        api_key=api_key,
        state=state,
        track_count=req.track_count,
        bearer_token=bearer,
        model=req.model,
        library_only=req.library_only,
    )

    if result.get("error"):
        raise HTTPException(500, f"Gemini curation error: {result['error']}")

    return result

@app.get("/gemini/models")
def get_gemini_models():
    """Returns available Gemini models for the configured API key, sorted cheapest first."""
    api_key = cfg.gemini_api_key if cfg else ""
    if not api_key:
        try:
            if DEFAULT_CONFIG_PATH.exists():
                with open(DEFAULT_CONFIG_PATH) as f:
                    raw = yaml.safe_load(f) or {}
                api_key = raw.get("gemini_api_key", "")
        except Exception:
            pass

    models = gemini_ai.list_available_gemini_models(api_key)
    return {"models": models}


class GeminiSavePlaylistRequest(BaseModel):
    name: str
    tracks: list[dict[str, Any]] = []
    prompt: Optional[str] = ""


class GeminiDownloadTracksRequest(BaseModel):
    tracks: list[dict[str, Any]]
    format: str = "ALAC"


@app.post("/gemini/download-tracks")
def post_gemini_download_tracks(req: GeminiDownloadTracksRequest):
    """Queue one-off lossless downloads for missing AI-curated tracks."""
    if not wrapper_running:
        raise HTTPException(409, "Downloader wrapper is not running — please log in to Apple Music first.")

    format_ = "ALAC"
    try:
        format_ = _validate_download_format(req.format)
    except Exception:
        pass

    queued_count = 0
    job_ids = []

    for t in req.tracks:
        # Extract Apple Music song URL
        am = t.get("am_track") or {}
        url = am.get("url") or t.get("url") or ""
        if not url and am.get("id"):
            url = f"https://music.apple.com/us/song/{am['id']}"

        if not url:
            continue

        try:
            valid_url = _validate_apple_music_url(url)
        except Exception:
            continue

        job_id = str(uuid.uuid4())
        job: dict = {
            "id": job_id,
            "type": "one-off",
            "url": valid_url,
            "format": format_,
            "playlist_name": None,
            "log_q": queue.Queue(),
            "started": threading.Event(),
        }
        with pending_jobs_lock:
            pending_jobs.append(job)
        job_queue.put(job)

        queued_count += 1
        job_ids.append(job_id)

    return {"queued": queued_count, "job_ids": job_ids}


@app.post("/gemini/save-playlist", status_code=201)
def post_gemini_save_playlist(req: GeminiSavePlaylistRequest):
    """Save an AI curated mix directly as a local tracked playlist."""
    if state is None:
        raise HTTPException(503, "Library is not ready")

    name = _validate_playlist_name(req.name)
    prompt_tag = req.prompt[:40].replace("\n", " ").strip() if req.prompt else "ai-mix"
    state.add_playlist(name, f"https://music.apple.com/us/playlist/gemini-{prompt_tag}")

    # Add any existing or matched tracks to this playlist
    for t in req.tracks:
        am = t.get("am_track") or {}
        tid = str(am.get("id") or am.get("track_id") or t.get("track_id") or "")
        title = t.get("title") or am.get("title") or "Unknown Title"
        artist = t.get("artist") or am.get("artist") or "Unknown Artist"
        album = t.get("album") or am.get("album") or "AI Curated"
        artwork = t.get("artwork_url") or am.get("artwork_url")

        if tid:
            # If track record does not exist yet in DB, record metadata placeholder
            existing_track = state.get_track(tid)
            if not existing_track:
                from alac_rip.state import Track
                state.add_track(
                    Track(
                        track_id=tid,
                        title=title,
                        artist=artist,
                        album=album,
                        local_path="",
                        downloaded_at=datetime.now().isoformat(),
                        artwork_url=artwork,
                    )
                )
            state.add_track_to_playlist(name, tid)

    from alac_rip.state import Playlist
    playlist = Playlist(name=name, url=f"https://music.apple.com/us/playlist/gemini-{prompt_tag}", last_synced=None, paused=False)
    return _playlist_dict(playlist)


# ── Smart Dynamic Playlists Endpoints ─────────────────────────────────────────

class SmartPlaylistCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    rules: dict[str, Any] = {}


class SmartPlaylistUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rules: Optional[dict[str, Any]] = None


class SmartPlaylistEvaluateRequest(BaseModel):
    rules: dict[str, Any]


@app.get("/smart-playlists")
def get_smart_playlists():
    if state is None:
        raise HTTPException(503, "Library is not ready")
    playlists = state.get_smart_playlists()
    result = []
    for sp in playlists:
        try:
            rules_cfg = json.loads(sp["rules_json"])
        except Exception:
            rules_cfg = {}
        # Calculate dynamic count
        all_tracks = state.get_all_tracks_with_provenance()
        matched = smart_playlists.evaluate_rules(all_tracks, rules_cfg)
        result.append({
            **sp,
            "rules": rules_cfg,
            "track_count": len(matched),
        })
    return result


@app.post("/smart-playlists", status_code=201)
def create_smart_playlist(req: SmartPlaylistCreateRequest):
    if state is None:
        raise HTTPException(503, "Library is not ready")
    name = _validate_playlist_name(req.name)
    existing = state.get_smart_playlist_by_name(name)
    if existing:
        raise HTTPException(409, f"Smart playlist '{name}' already exists")

    rules_json = json.dumps(req.rules)
    created = state.create_smart_playlist(name, req.description, rules_json)
    all_tracks = state.get_all_tracks_with_provenance()
    matched = smart_playlists.evaluate_rules(all_tracks, req.rules)
    return {
        **created,
        "rules": req.rules,
        "track_count": len(matched),
    }


@app.get("/smart-playlists/{sp_id}")
def get_smart_playlist_details(sp_id: int):
    if state is None:
        raise HTTPException(503, "Library is not ready")
    try:
        eval_result = smart_playlists.evaluate_smart_playlist(state, sp_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

    sp = eval_result["smart_playlist"]
    try:
        rules_cfg = json.loads(sp["rules_json"])
    except Exception:
        rules_cfg = {}

    return {
        **sp,
        "rules": rules_cfg,
        "tracks": eval_result["tracks"],
        "track_count": eval_result["count"],
    }


@app.patch("/smart-playlists/{sp_id}")
def update_smart_playlist(sp_id: int, req: SmartPlaylistUpdateRequest):
    if state is None:
        raise HTTPException(503, "Library is not ready")
    existing = state.get_smart_playlist(sp_id)
    if not existing:
        raise HTTPException(404, f"Smart playlist {sp_id} not found")

    new_name = None
    if req.name is not None:
        new_name = _validate_playlist_name(req.name)
        if new_name != existing["name"]:
            other = state.get_smart_playlist_by_name(new_name)
            if other and other["id"] != sp_id:
                raise HTTPException(409, f"Smart playlist '{new_name}' already exists")

    rules_json = json.dumps(req.rules) if req.rules is not None else None
    updated = state.update_smart_playlist(sp_id, name=new_name, description=req.description, rules_json=rules_json)
    if not updated:
        raise HTTPException(404, f"Smart playlist {sp_id} not found")

    try:
        rules_cfg = json.loads(updated["rules_json"])
    except Exception:
        rules_cfg = {}

    all_tracks = state.get_all_tracks_with_provenance()
    matched = smart_playlists.evaluate_rules(all_tracks, rules_cfg)

    return {
        **updated,
        "rules": rules_cfg,
        "track_count": len(matched),
    }


@app.delete("/smart-playlists/{sp_id}", status_code=204)
def delete_smart_playlist(sp_id: int):
    if state is None:
        raise HTTPException(503, "Library is not ready")
    deleted = state.delete_smart_playlist(sp_id)
    if not deleted:
        raise HTTPException(404, f"Smart playlist {sp_id} not found")
    return None


@app.post("/smart-playlists/preview")
def preview_smart_playlist(req: SmartPlaylistEvaluateRequest):
    if state is None:
        raise HTTPException(503, "Library is not ready")
    all_tracks = state.get_all_tracks_with_provenance()
    matched = smart_playlists.evaluate_rules(all_tracks, req.rules)
    return {
        "tracks": matched,
        "track_count": len(matched),
    }


def _read_sidecar_handshake(value: str) -> tuple[int, str]:
    try:
        data = json.loads(value)
        port = data["port"]
        capability = data["capability"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise ValueError("Invalid sidecar handshake") from None
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Invalid sidecar handshake")
    if not isinstance(capability, str) or not re.fullmatch(r"[0-9a-f]{64}", capability):
        raise ValueError("Invalid sidecar handshake")
    return port, capability


if __name__ == "__main__":
    port = 0
    if "--sidecar-handshake" in sys.argv:
        try:
            port, _api_capability = _read_sidecar_handshake(sys.stdin.readline())
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    uvicorn.run(app, fd=sock.fileno(), log_level="warning")
