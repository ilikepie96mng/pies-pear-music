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
import time
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
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from mutagen.mp4 import MP4, MP4Cover
from pydantic import BaseModel, field_validator

from alac_rip import am_api, audit, gemini_ai, integrations, lastfm_api, lyrics, metadata_editor, playlist_import, smart_playlists, strawberry_sync, waveform
from alac_rip.requests import RequestStore
from alac_rip.am_api import AMApiError
from alac_rip.config import DEFAULT_CONFIG_PATH, Config, load_config, resolve_kio_fuse_path, save_config_file
from alac_rip.dap_export import DapExportError, export_dap_playlist
from alac_rip.metadata import read_tags
from alac_rip.organizer import sanitize
from alac_rip.scheduler import BackgroundSyncScheduler
from alac_rip.state import StateManager
from alac_rip.sync import StagingValidationError, SyncEngine, validate_staging_dir

# Ensure standard user tool directories (Linuxbrew, local bin, go bin) are present in PATH
extra_tool_paths = [
    "/home/linuxbrew/.linuxbrew/bin",
    "/home/linuxbrew/.linuxbrew/sbin",
    str(Path.home() / ".local" / "bin"),
    str(Path.home() / "go" / "bin"),
]
for _ep in reversed(extra_tool_paths):
    if os.path.isdir(_ep) and _ep not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = f"{_ep}{os.pathsep}{os.environ.get('PATH', '')}"



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
    """Resolve a user-supplied path when it is within the library or recorded track."""
    if cfg is None or state is None:
        raise HTTPException(503, "Library is not ready")

    p = Path(path).expanduser()
    p = resolve_kio_fuse_path(p)
    music_dir = cfg.music_dir.expanduser().resolve()

    if not p.is_absolute():
        p = (music_dir / p)

    if not p.is_file():
        path_str = str(p)
        for anchor in ("/artists/", "/playlists/", "artists/", "playlists/"):
            if anchor in path_str:
                rel = path_str.split(anchor, 1)[1]
                anchor_dir = anchor.strip("/")
                cand = (music_dir / anchor_dir / rel).resolve()
                if cand.is_file():
                    p = cand
                    break

    try:
        track_path = p.resolve()
        track_path.relative_to(music_dir)
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(403, "Path is outside the music library")

    if not state.has_track_path(track_path) and not state.has_track_path(p):
        raise HTTPException(403, "Path is not a known library track")

    return track_path

# ── Wrapper / downloader state ────────────────────────────────────────────────

CONTAINER_NAME = "alac-rip-wrapper"
IMAGE_NAME = "alac-rip-wrapper"

wrapper_process: Optional[subprocess.Popen] = None
wrapper_running: bool = False
wrapper_logging_in: bool = False
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
_queue_wake_event: threading.Event = threading.Event()
_queue_listeners_lock: threading.Lock = threading.Lock()
_queue_listeners: list[asyncio.Queue] = []


def _broadcast_queue_event(event: dict) -> None:
    with _queue_listeners_lock:
        for q in list(_queue_listeners):
            try:
                q.put_nowait(event)
            except Exception:
                pass


def _is_wrapper_port_alive(port: int = 10020) -> bool:
    """Check if the local decryption wrapper daemon is reachable on port 10020."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.8):
            return True
    except (OSError, socket.error):
        return False


def _credentials_path() -> Path:
    """Encrypted/private credentials fallback path."""
    if DEFAULT_CONFIG_PATH.parent.exists():
        p = DEFAULT_CONFIG_PATH.parent
    else:
        p = Path.home() / ".config" / "pies-alac-rip"
    p.mkdir(parents=True, exist_ok=True)
    return p / ".credentials"


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
    """Store credentials in Secret Service for desktop, or /config/.credentials for headless containers."""
    global _session_credentials
    _session_credentials = (email, password)
    persisted = _secret_service_store(email, password)
    if persisted:
        try:
            _credentials_path().unlink(missing_ok=True)
        except OSError:
            pass
        return True

    # In headless / Docker container mode, persist securely to mounted /config/.credentials (0600)
    if os.environ.get("PIES_HEADLESS") or os.environ.get("PIES_CONFIG_PATH"):
        try:
            p = _credentials_path()
            p.write_text(json.dumps({"email": email, "password": password}), encoding="utf-8")
            try:
                p.chmod(0o600)
            except OSError:
                pass
            return True
        except Exception:
            return False

    return False


def load_credentials() -> tuple[Optional[str], Optional[str]]:
    if _session_credentials is not None:
        return _session_credentials
    email, password = _secret_service_load()
    if email and password:
        return email, password

    # Fallback to local credentials file if secret-tool is locked or unavailable
    try:
        p = _credentials_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("email") and data.get("password"):
                return data["email"], data["password"]
    except Exception:
        pass

    return None, None


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
    global wrapper_running, wrapper_logging_in, wrapper_process, wrapper_needs_2fa, wrapper_2fa_type
    login_successful = False
    try:
        for line in iter(pipe.readline, ""):
            line = line.strip()
            if not line:
                continue
            target_list.append(_redact_wrapper_log(line, email, password))
            if "credentialHandler:" in line and "2FA: true" in line:
                wrapper_logging_in = False
                wrapper_needs_2fa = True
                wrapper_2fa_type = "sms"
                target_list.append("2FA required — please enter your code")
            if "[.] response type 4" in line or "[!] 2FA device code requested" in line:
                wrapper_logging_in = False
                wrapper_needs_2fa = True
                wrapper_2fa_type = "device"
                target_list.append("2FA required — Apple sent a code to your trusted device")
            if "[.] response type 6" in line:
                wrapper_running = True
                wrapper_logging_in = False
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
        wrapper_logging_in = False
        if wrapper_process and wrapper_process.poll() is not None:
            exit_code = wrapper_process.poll()
            if not login_successful:
                target_list.append(f"Login failed — wrapper exited with code {exit_code}")
                wrapper_running = False
                was_2fa = wrapper_needs_2fa
                wrapper_needs_2fa = False
                wrapper_2fa_type = ""
                if auto_login and not was_2fa:
                    target_list.append("Authentication failed, removing saved credentials")
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

    # Check if native binary wrapper is installed (e.g. inside Docker or standalone)
    native_bin = Path("/app/wrapper")
    if not native_bin.exists() and cfg and cfg.alac_rip_dir:
        candidate = cfg.alac_rip_dir / "wrapper" / "wrapper"
        if candidate.exists() and os.access(candidate, os.X_OK):
            native_bin = candidate

    if native_bin.exists() and (not shutil.which("podman") or os.environ.get("PIES_NATIVE_WRAPPER") or os.environ.get("PIES_HEADLESS")):
        dev_dir = native_bin.parent / "rootfs" / "dev"
        if dev_dir.exists():
            try:
                urandom_path = dev_dir / "urandom"
                subprocess.run(["rm", "-f", str(urandom_path)], capture_output=True)
                subprocess.run(["touch", str(urandom_path)], capture_output=True)
                subprocess.run(["mount", "--bind", "/dev/urandom", str(urandom_path)], capture_output=True)
            except Exception:
                pass

        if email and password:
            cmd = [str(native_bin), "-L", f"{email}:{password}"]
        else:
            cmd = [str(native_bin)]
        wrapper_logs.append(f"{prefix}Launching native decryption daemon: {native_bin}")
        child_env = os.environ.copy()
        cwd_dir = str(native_bin.parent)
    else:
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
        cwd_dir = None

    try:
        wrapper_logging_in = True
        wrapper_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
            env=child_env,
            cwd=cwd_dir,
        )

        threading.Thread(
            target=stream_wrapper_logs,
            args=(wrapper_process.stdout, wrapper_logs, email, password, auto_login),
            daemon=True,
        ).start()
        wrapper_logs.append(f"{prefix}Container started, waiting for login confirmation...")
        return True
    except Exception as e:
        wrapper_logging_in = False
        wrapper_logs.append(f"{prefix}Error starting container: {e}")
        return False


def attempt_auto_login() -> bool:
    email, password = load_credentials()
    if email and password:
        wrapper_logs.append("Found saved credentials, attempting auto-login...")
        return start_wrapper_login(email, password, auto_login=True)
    return False


sync_scheduler: Optional[BackgroundSyncScheduler] = None


def _run_scheduled_sync() -> str:
    """Execute background sync during scheduler trigger."""
    if cfg is None or state is None:
        return "Library not initialized"

    staging_dir = cfg.state_dir / "staging"
    if not staging_dir.exists() or not any(staging_dir.iterdir()):
        return "Staging directory is clean"

    try:
        engine = SyncEngine(cfg, state)
        res = engine.sync_staging(staging_dir)
        integrations.dispatch_media_webhooks(cfg.__dict__)
        integrations.dispatch_completion_notifications(
            cfg.__dict__,
            event_title="Automated Sync Completed",
            event_description=f"Scheduled sync organized {res.tracks_moved} tracks into the library.",
            fields=[
                {"name": "Tracks Moved", "value": str(res.tracks_moved)},
                {"name": "Playlists Updated", "value": str(len(res.playlists_updated))},
            ],
        )
    except Exception as e:
        return f"Sync failed: {e}"


def resolve_db_path(state_dir: Path) -> Path:
    if (state_dir / "downloaded.db").exists():
        return state_dir / "downloaded.db"
    if (state_dir / ".state" / "downloaded.db").exists():
        return state_dir / ".state" / "downloaded.db"
    if state_dir.parent.exists() and (state_dir.parent / "downloaded.db").exists():
        return state_dir.parent / "downloaded.db"
    return state_dir / "downloaded.db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global cfg, state, sync_scheduler
    cfg = load_config(DEFAULT_CONFIG_PATH)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    state = StateManager(resolve_db_path(cfg.state_dir))
    try:
        state.auto_rebase_paths(cfg.music_dir)
    except Exception:
        pass
    threading.Thread(target=attempt_auto_login, daemon=True).start()
    threading.Thread(target=_queue_worker, daemon=True).start()

    sched_cfg = cfg.scheduler or {}
    interval = int(sched_cfg.get("interval_minutes", 60))
    enabled = bool(sched_cfg.get("enabled", False))
    sync_scheduler = BackgroundSyncScheduler(
        interval_minutes=interval,
        sync_callback=_run_scheduled_sync,
        enabled=enabled,
    )
    if enabled:
        sync_scheduler.start()

    yield

    if sync_scheduler:
        sync_scheduler.stop()


app = FastAPI(title="pies-alac-rip", lifespan=lifespan)


@app.middleware("http")
async def require_api_capability(request: Request, call_next):
    """Require the Tauri-generated capability or configured API token."""
    if request.method != "OPTIONS":
        if _api_capability:
            supplied = request.headers.get(_API_CAPABILITY_HEADER) or request.query_params.get("token")
            if not supplied or not secrets.compare_digest(supplied, _api_capability):
                return Response(status_code=401)
        elif cfg and cfg.api_token and request.url.path.startswith("/api/"):
            auth_header = request.headers.get("authorization", "")
            bearer_token = auth_header.split(" ", 1)[1] if auth_header.startswith("Bearer ") else ""
            supplied = (
                request.headers.get(_API_CAPABILITY_HEADER)
                or bearer_token
                or request.query_params.get("token")
            )
            if not supplied or not secrets.compare_digest(supplied, cfg.api_token):
                return Response(status_code=401, content="Unauthorized: Invalid API Token")
    return await call_next(request)


_is_headless = "--headless" in sys.argv or bool(os.environ.get("PIES_HEADLESS")) or bool(os.environ.get("PORT"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _is_headless else ["http://tauri.localhost", "http://localhost:1420"],
    allow_origin_regex=r"https?://.*" if _is_headless else None,
    allow_credentials=True,
    allow_methods=["*"] if _is_headless else ["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["*"] if _is_headless else ["content-type", _API_CAPABILITY_HEADER],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/diagnostics")
def get_diagnostics():
    def check(label: str, ok: bool, detail: str = "") -> dict:
        return {"label": label, "ok": ok, "detail": detail}

    results: list[dict] = []
    is_container = bool(os.environ.get("PIES_HEADLESS") or os.environ.get("PIES_NATIVE_WRAPPER") or Path("/app/wrapper").exists())

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
        elif is_container and command in ("podman", "go"):
            available = True
            detail = "embedded in container"
        elif is_container and command == "MP4Box":
            available = True
            detail = "optional (ffmpeg demuxing active)"
        elif optional:
            detail = "optional — not found in PATH"
        else:
            detail = "not found in PATH"
        results.append(check(label, available, detail))

    config_path = Path(os.environ.get("PIES_CONFIG_PATH", str(DEFAULT_CONFIG_PATH)))
    config_exists = config_path.exists()
    results.append(check("Config file", config_exists, "available" if config_exists else "not found"))

    global cfg
    if cfg is None or not config_exists:
        try:
            cfg = load_config(config_path)
            config_exists = config_path.exists()
        except Exception:
            pass

    if cfg is not None:
        music_ok = cfg.music_dir.exists()
        results.append(check("Music directory", music_ok, "available" if music_ok else "not found"))

        state_ok = cfg.state_dir.exists()
        results.append(check("State directory", state_ok, "available" if state_ok else "not found"))

        if is_container and Path("/app/wrapper").exists():
            results.append(check("alac-rip directory", True, "available (container)"))
            results.append(check("Downloader source", True, "available (embedded amd-main binary)"))
            results.append(check("Wrapper source", True, "available (embedded native daemon)"))
        else:
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
    db_id: Optional[int] = job.get("db_id")

    def emit(event: dict) -> None:
        log_q.put(event)
        _broadcast_queue_event({
            "event": "job_progress",
            "job_id": db_id or job.get("id"),
            "data": event,
        })

    if cfg is None or not cfg.alac_rip_dir or not cfg.alac_rip_dir.exists():
        emit({"status": "error", "message": "alac_rip_dir not configured"})
        if db_id and state:
            try:
                state.update_job_status(db_id, "error", completed_at=datetime.now().isoformat(), error_message="alac_rip_dir not configured")
            except Exception:
                pass
        return
    if not cfg.music_dir or not cfg.music_dir.is_absolute():
        emit({"status": "error", "message": "music_dir not configured"})
        if db_id and state:
            try:
                state.update_job_status(db_id, "error", completed_at=datetime.now().isoformat(), error_message="music_dir not configured")
            except Exception:
                pass
        return

    cand_dirs = [
        cfg.alac_rip_dir / "apple-music-downloader" if cfg.alac_rip_dir else None,
        cfg.alac_rip_dir / "vendor" / "apple-music-downloader" if cfg.alac_rip_dir else None,
        Path("/app/apple-music-downloader"),
        Path("/app/vendor/apple-music-downloader"),
        Path.home() / ".local" / "share" / "pies-alac-rip" / "apple-music-downloader",
        Path.home() / "Documents/VS-Projects/pies-alac-rip-tool/vendor/apple-music-downloader",
        cfg.state_dir / "apple-music-downloader",
    ]
    amd_dir = None
    for cand in cand_dirs:
        if cand and cand.exists():
            amd_dir = cand
            break
    if amd_dir is None:
        amd_dir = cfg.state_dir / "apple-music-downloader"
        amd_dir.mkdir(parents=True, exist_ok=True)

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

    if db_id and state:
        try:
            state.update_job_status(db_id, "running", started_at=started_at.isoformat(), log_path=str(log_path))
        except Exception:
            pass

    def write_log(line: str) -> None:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {line}\n")

    def emit_log(phase: str, message: str) -> None:
        write_log(f"[{phase}] {message}")
        emit({"status": "running", "phase": phase, "message": message, "log_path": str(log_path)})

    def handle_early_error(msg: str) -> None:
        emit({"status": "error", "message": msg, "log_path": str(log_path)})
        if playlist_name:
            state.record_sync_run(playlist_name, started_at.isoformat(), datetime.now().isoformat(),
                                  "error", 0, 0, 0, str(log_path), msg)
        if db_id and state:
            try:
                state.update_job_status(db_id, "error", completed_at=datetime.now().isoformat(), error_message=msg)
            except Exception:
                pass

    write_log(f"[session] type={job['type']} url={url}")

    save_folder_key = {"ATMOS": "atmos-save-folder", "AAC": "aac-save-folder"}.get(format_, "alac-save-folder")
    try:
        cfg_file = amd_dir / "config.yaml"
        if not cfg_file.exists():
            # Attempt to copy from known vendor templates
            copied = False
            for tmpl in [
                Path("/app/vendor/apple-music-downloader/config.yaml"),
                Path("/app/apple-music-downloader/config.yaml"),
                Path.home() / "Documents/VS-Projects/pies-alac-rip-tool/vendor/apple-music-downloader/config.yaml",
            ]:
                if tmpl.exists():
                    shutil.copy2(tmpl, cfg_file)
                    copied = True
                    break
            if not copied:
                staging_p = "/staging" if Path("/staging").exists() else str(cfg.state_dir / "staging")
                Path(staging_p).mkdir(parents=True, exist_ok=True)
                default_cfg = {
                    "aac-save-folder": staging_p,
                    "alac-save-folder": staging_p,
                    "atmos-save-folder": staging_p,
                    "storefront": "us",
                    "convert-after-download": True,
                    "convert-format": "flac",
                    "decrypt-m3u8-port": "127.0.0.1:10020",
                    "get-m3u8-port": "127.0.0.1:20020",
                    "get-m3u8-mode": "hires",
                }
                with open(cfg_file, "w") as f:
                    yaml.dump(default_cfg, f)

        with open(cfg_file) as f:
            amd_cfg = yaml.safe_load(f) or {}

        # Ensure default storefront
        updated_cfg = False
        if amd_cfg.get("storefront") in ("", "enter your account storefront"):
            amd_cfg["storefront"] = "us"
            updated_cfg = True

        # Sync media_user_token from app config if present
        if cfg and cfg.media_user_token and cfg.media_user_token != amd_cfg.get("media-user-token"):
            amd_cfg["media-user-token"] = cfg.media_user_token
            updated_cfg = True

        # Fallback save folder to /staging or state_dir/staging if not configured or points to non-existent home
        cur_save = amd_cfg.get(save_folder_key, "")
        valid_save = False
        if cur_save:
            try:
                p_cand = Path(cur_save).expanduser()
                if not p_cand.exists():
                    p_cand.mkdir(parents=True, exist_ok=True)
                valid_save = p_cand.exists() and p_cand.is_dir()
            except (OSError, PermissionError):
                valid_save = False

        if not valid_save:
            staging_fallback = "/staging" if Path("/staging").exists() else str(cfg.state_dir / "staging")
            Path(staging_fallback).mkdir(parents=True, exist_ok=True)
            amd_cfg["aac-save-folder"] = staging_fallback
            amd_cfg["alac-save-folder"] = staging_fallback
            amd_cfg["atmos-save-folder"] = staging_fallback
            updated_cfg = True

        if updated_cfg:
            with open(cfg_file, "w") as f:
                yaml.dump(amd_cfg, f)

        save_folder = Path(amd_cfg.get(save_folder_key, "")).expanduser()
    except Exception as exc:
        msg = _redact_runtime_paths(f"Cannot read downloader config: {exc}")
        handle_early_error(msg)
        return

    if not save_folder or not save_folder.is_absolute():
        msg = f"Downloader save folder not configured ({save_folder_key})"
        handle_early_error(msg)
        return

    try:
        save_folder.mkdir(parents=True, exist_ok=True)
        save_folder = validate_staging_dir(
            save_folder,
            cfg.music_dir,
            cfg.state_dir,
            cfg.alac_rip_dir,
        )
    except StagingValidationError as sve:
        msg = _redact_runtime_paths(f"Invalid downloader staging folder: {sve}")
        handle_early_error(msg)
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

    mut = (cfg.media_user_token if cfg else "") or amd_cfg.get("media-user-token", "")
    if not mut or len(mut) < 20:
        emit_log("preflight", "⚠️ Notice: Apple Media User Token is not set. Go to Settings → Apple Music Authentication to paste your subscriber cookie if downloads fail.")

    if playlist_name and "music.apple.com" in url and "/playlist/gemini-" not in url:
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
                updates = []
                for db_track in unmatched:
                    key = (_normalize(db_track.title), _normalize(db_track.artist))
                    if key in am_by_key:
                        updates.append((am_by_key[key], db_track.track_id))
                if updates:
                    state.bulk_update_track_am_ids(updates)
                    emit_log("preflight", f"Matched {len(updates)} existing tracks to AM IDs")

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

            if delisted_ids or skip_ids:
                mapping = state.get_playlist_am_track_mapping(playlist_name)
                # Map am_track_id -> list of track_ids
                am_to_tracks: dict[str, list[str]] = {}
                for tid, am_id in mapping:
                    am_to_tracks.setdefault(am_id, []).append(tid)

                if delisted_ids:
                    now_str = datetime.now().isoformat()
                    delisted_records = []
                    for did in delisted_ids:
                        for tid in am_to_tracks.get(did, []):
                            delisted_records.append((playlist_name, tid, now_str))
                    if delisted_records:
                        state.bulk_record_delisted_tracks(delisted_records)
                        emit_log("preflight", f"Preserved {len(delisted_records)} delisted track(s) in streaming graveyard")

                # If tracks were restored/re-added upstream, clear their delisted mark
                if skip_ids:
                    restored_tids = []
                    for sid in skip_ids:
                        restored_tids.extend(am_to_tracks.get(sid, []))
                    if restored_tids:
                        state.bulk_clear_delisted_tracks(playlist_name, restored_tids)

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

    system_amd = shutil.which("amd-main")
    patched_bin = Path.home() / ".local" / "share" / "pies-alac-rip" / "amd-main"
    usr_bin_amd = Path("/usr/local/bin/amd-main")
    if system_amd:
        _amd_bin = [system_amd]
    elif usr_bin_amd.exists() and os.access(usr_bin_amd, os.X_OK):
        _amd_bin = [str(usr_bin_amd)]
    elif patched_bin.exists() and os.access(patched_bin, os.X_OK):
        _amd_bin = [str(patched_bin)]
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

    # Ensure decryption wrapper is alive before launching downloader
    if not _is_wrapper_port_alive():
        emit_log("downloading", "Decryption wrapper is not responding; attempting auto-recovery...")
        attempt_auto_login()
        for _ in range(15):
            if _is_wrapper_port_alive():
                emit_log("downloading", "Decryption wrapper auto-recovery successful.")
                break
            time.sleep(0.5)

    # ── Phase 1: download ──────────────────────────────────────────────────────
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            bufsize=1, universal_newlines=True,
            cwd=str(amd_dir), env=env,
        )
    except Exception as exc:
        msg = _redact_runtime_paths(str(exc))
        write_log(f"[error] {msg}")
        handle_early_error(msg)
        return

    last_progress_emit = 0.0
    for line in iter(proc.stdout.readline, ""):
        line = line.strip()
        if line:
            m = _TRACK_PROGRESS_RE.match(line)
            if m:
                current, total, rest = m.groups()
                emit_log("downloading", f"[{current}/{total}] {rest}".rstrip())
            elif line.startswith("Downloading...") or line.startswith("Decrypting..."):
                now = time.time()
                if now - last_progress_emit >= 0.25:
                    last_progress_emit = now
                    emit_log("downloading", line)
                else:
                    write_log(f"[downloading] {line}")
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

    # Trigger media server webhooks (Jellyfin / Navidrome) & notifications (Discord / Telegram / Gotify) asynchronously
    try:
        if DEFAULT_CONFIG_PATH.exists():
            with open(DEFAULT_CONFIG_PATH) as f_cfg:
                raw_cfg = yaml.safe_load(f_cfg) or {}

            # 1. Media server auto-scan webhooks
            threading.Thread(
                target=integrations.dispatch_media_webhooks,
                args=(raw_cfg,),
                daemon=True
            ).start()

            # 2. Notification webhooks (Discord, Telegram, Gotify)
            title = f"♫ Sync Complete: {playlist_name}" if playlist_name else f"♫ Download Complete: {job.get('title', 'Audio')}"
            desc = f"Finished processing **{result.new_count}** new tracks ({result.skipped_count} skipped, {result.error_count} errors)."
            fields = [
                {"name": "New Tracks", "value": f"+{result.new_count}", "inline": True},
                {"name": "Skipped", "value": f"{result.skipped_count}", "inline": True},
                {"name": "Format", "value": format_, "inline": True},
            ]
            thumb = job.get("artwork_url") or (_artwork_map.get(list(_artwork_map.keys())[0]) if _artwork_map else None)

            threading.Thread(
                target=integrations.dispatch_completion_notifications,
                args=(raw_cfg, title, desc, fields, thumb),
                daemon=True
            ).start()
    except Exception as e:
        write_log(f"[integrations] Webhook dispatch warning: {e}")

    write_log(f"[done] {result.new_count} new, {result.skipped_count} skipped, {result.error_count} errors"
              f"{' (downloader reported errors on some tracks; see log)' if downloader_had_errors else ''}")
    emit({"status": "done",
          "new": result.new_count, "skipped": result.skipped_count,
          "errors": result.error_count, "log_path": str(log_path)})

    if db_id and state:
        try:
            state.update_job_status(
                db_id,
                "done",
                completed_at=datetime.now().isoformat(),
                new_tracks=result.new_count,
                skipped_tracks=result.skipped_count,
                error_count=result.error_count,
                log_path=str(log_path),
            )
        except Exception:
            pass


def _queue_worker() -> None:
    global active_job
    # On startup or after crash recovery, reset any interrupted 'running' jobs to 'pending'
    if state:
        try:
            state.reset_interrupted_jobs()
        except Exception:
            pass

    while True:
        # 1. Process SQLite persistent queue first
        pending_db_job = None
        if state:
            try:
                pending_db_job = state.get_next_pending_job()
            except Exception:
                pass

        if pending_db_job is not None:
            job_id = str(uuid.uuid4())
            job = {
                "id": job_id,
                "db_id": pending_db_job["id"],
                "type": "one-off" if pending_db_job.get("item_type") != "playlist" else "playlist",
                "url": pending_db_job["url"],
                "format": pending_db_job.get("format", "ALAC"),
                "playlist_name": pending_db_job.get("title") if pending_db_job.get("item_type") == "playlist" else None,
                "title": pending_db_job.get("title", "Lossless Download"),
                "artist": pending_db_job.get("artist", ""),
                "album": pending_db_job.get("album", ""),
                "artwork_url": pending_db_job.get("artwork_url"),
                "log_q": queue.Queue(),
                "started": threading.Event(),
            }
            active_job = job
            job["started"].set()
            _broadcast_queue_event({"event": "job_started", "job": pending_db_job})
            try:
                sys.modules[__name__]._run_job(job)
            except Exception as exc:
                msg = _redact_runtime_paths(f"Internal error: {exc}")
                job["log_q"].put({"status": "error", "message": msg})
                if state:
                    try:
                        state.update_job_status(
                            pending_db_job["id"],
                            "error",
                            completed_at=datetime.now().isoformat(),
                            error_message=msg,
                        )
                    except Exception:
                        pass
            finally:
                job["log_q"].put(None)
                active_job = None
                _broadcast_queue_event({"event": "job_finished", "job_id": pending_db_job["id"]})
                time.sleep(0.3)
            continue

        # 2. Process in-memory queue fallback
        try:
            job = job_queue.get_nowait()
        except queue.Empty:
            job = None

        if job is not None:
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
                job["log_q"].put(None)
                active_job = None
                job_queue.task_done()
            continue

        # 3. Wait for new jobs
        _queue_wake_event.wait(timeout=1.5)
        _queue_wake_event.clear()


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


class QueueAddRequest(BaseModel):
    urls: list[str] = []
    items: list[dict[str, Any]] = []
    format: str = "ALAC"
    batch_id: Optional[str] = None
    batch_title: Optional[str] = None


class QueueCancelRequest(BaseModel):
    job_id: Optional[int] = None
    batch_id: Optional[str] = None
    cancel_all: bool = False


class QueueRetryRequest(BaseModel):
    job_ids: list[int] = []


class QueueReorderRequest(BaseModel):
    job_id: int
    new_position: int


@app.post("/api/v1/queue/add")
@app.post("/download/queue/add")
def post_queue_add(req: QueueAddRequest):
    format_ = _validate_download_format(req.format)
    jobs_to_insert = []
    batch_id = req.batch_id or (str(uuid.uuid4()) if (len(req.urls) + len(req.items)) > 1 else None)

    for item in req.items:
        url = item.get("url") or ""
        alb_id = str(item.get("id") or item.get("album_id") or "")
        if not url and alb_id:
            url = f"https://music.apple.com/us/album/{alb_id}"
        if not url:
            continue
        try:
            valid_url = _validate_apple_music_url(url)
        except ValueError:
            continue
        jobs_to_insert.append({
            "batch_id": batch_id,
            "batch_title": req.batch_title or item.get("batch_title"),
            "url": valid_url,
            "title": item.get("title") or item.get("name") or "Album Download",
            "artist": item.get("artist") or "",
            "album": item.get("album") or item.get("title") or "",
            "artwork_url": item.get("artwork_url"),
            "format": format_,
            "item_type": item.get("item_type") or "album",
            "total_tracks": item.get("total_tracks") or item.get("track_count") or 0,
        })

    for url_raw in req.urls:
        try:
            valid_url = _validate_apple_music_url(url_raw)
        except ValueError:
            continue
        jobs_to_insert.append({
            "batch_id": batch_id,
            "batch_title": req.batch_title,
            "url": valid_url,
            "title": "Lossless Download",
            "artist": "",
            "album": "",
            "artwork_url": None,
            "format": format_,
            "item_type": "album",
            "total_tracks": 0,
        })

    if not jobs_to_insert:
        raise HTTPException(400, "No valid URLs or items provided")

    job_ids = state.bulk_enqueue_download_jobs(jobs_to_insert) if state else []
    _queue_wake_event.set()
    _broadcast_queue_event({"event": "queue_updated", "count": len(job_ids)})
    return {"queued": len(job_ids), "job_ids": job_ids, "batch_id": batch_id}


@app.get("/api/v1/queue")
@app.get("/download/queue")
def get_download_queue():
    if not state:
        return {
            "active": None,
            "pending": [],
            "completed": [],
            "counts": {"pending": 0, "running": 0, "done": 0, "error": 0, "cancelled": 0, "total": 0},
        }
    summary = state.get_queue_summary()
    if not summary["active"] and active_job:
        summary["active"] = {
            "id": active_job.get("db_id") or active_job.get("id"),
            "title": active_job.get("title") or active_job.get("playlist_name") or "Lossless Download",
            "url": active_job.get("url"),
            "status": "running",
            "format": active_job.get("format", "ALAC"),
            "artist": active_job.get("artist", ""),
            "album": active_job.get("album", ""),
        }
    return summary


@app.post("/api/v1/queue/cancel")
def post_queue_cancel(req: QueueCancelRequest):
    if not state:
        raise HTTPException(500, "Database state not initialized")
    if req.cancel_all:
        count = state.cancel_all_pending_jobs()
        _broadcast_queue_event({"event": "queue_updated"})
        return {"cancelled": count}
    if req.batch_id:
        count = state.cancel_all_pending_jobs(batch_id=req.batch_id)
        _broadcast_queue_event({"event": "queue_updated"})
        return {"cancelled": count}
    if req.job_id:
        ok = state.cancel_queue_job(req.job_id)
        _broadcast_queue_event({"event": "queue_updated"})
        return {"cancelled": 1 if ok else 0}
    raise HTTPException(400, "Must provide 'job_id', 'batch_id', or 'cancel_all=true'")


@app.post("/api/v1/queue/retry")
def post_queue_retry(req: QueueRetryRequest):
    if not state:
        raise HTTPException(500, "Database state not initialized")
    count = state.retry_failed_jobs(req.job_ids or None)
    _queue_wake_event.set()
    _broadcast_queue_event({"event": "queue_updated"})
    return {"retried": count}


@app.post("/api/v1/queue/clear")
def post_queue_clear(older_than_days: int = 0):
    if not state:
        raise HTTPException(500, "Database state not initialized")
    count = state.clear_completed_queue(older_than_days=older_than_days)
    _broadcast_queue_event({"event": "queue_updated"})
    return {"cleared": count}


@app.post("/api/v1/queue/reorder")
def post_queue_reorder(req: QueueReorderRequest):
    if not state:
        raise HTTPException(500, "Database state not initialized")
    ok = state.reorder_queue_job(req.job_id, req.new_position)
    _queue_wake_event.set()
    _broadcast_queue_event({"event": "queue_updated"})
    return {"reordered": ok}


@app.get("/api/v1/queue/stream")
async def queue_event_stream():
    """SSE stream for real-time queue updates, live logs, and progress."""
    q: asyncio.Queue = asyncio.Queue()
    with _queue_listeners_lock:
        _queue_listeners.append(q)

    async def event_generator():
        try:
            if state:
                summary = state.get_queue_summary()
                yield f"data: {json.dumps({'event': 'queue_state', 'summary': summary})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            with _queue_listeners_lock:
                try:
                    _queue_listeners.remove(q)
                except ValueError:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/sync/queue")
def get_queue():
    if state:
        summary = state.get_queue_summary()
        active = summary["active"]
        pending = [
            {
                "id": j["id"],
                "type": j.get("item_type", "one-off"),
                "playlist_name": j.get("title") if j.get("item_type") == "playlist" else None,
                "url": j.get("url"),
                "title": j.get("title"),
                "artist": j.get("artist"),
            }
            for j in summary["pending"]
        ]
        if active:
            active_dict = {
                "id": active["id"],
                "type": active.get("item_type", "one-off"),
                "playlist_name": active.get("title") if active.get("item_type") == "playlist" else None,
                "url": active.get("url"),
                "title": active.get("title"),
                "artist": active.get("artist"),
            }
        else:
            active_dict = None
        return {"active": active_dict, "pending": pending}

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

    # Regenerate m3u8 playlist with updated track list
    try:
        cfg = load_config()
        if cfg:
            music_dir = cfg.music_dir.expanduser().resolve()
            engine = SyncEngine(state, music_dir, name)
            engine._write_m3u8()
    except Exception as e:
        logger.warning(f"Failed to update m3u8 after deduplication: {e}")

    # Trigger media server webhooks (Navidrome / Jellyfin) to reflect deduplication
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
        logger.warning(f"Webhook dispatch error after deduplication: {e}")

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


@app.get("/playlists/{name:path}/tracks")
def get_single_playlist_tracks(name: str):
    if state is None:
        raise HTTPException(503, "Database is not ready")
    tracks = state.get_playlist_tracks(name)
    return [
        {
            "track_id": t.track_id,
            "title": t.title,
            "artist": t.artist,
            "album": t.album,
            "local_path": t.local_path,
            "downloaded_at": t.downloaded_at,
            "artwork_url": t.artwork_url,
            "has_lyrics": False,
        }
        for t in tracks
    ]


@app.get("/library")
def get_library():
    if state is None:
        raise HTTPException(503, "Database is not ready")
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
                "has_lyrics": False,
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
        fmt = lp.rsplit(".", 1)[-1].upper() if (lp and "." in lp) else "FLAC"
        size = 0
        exists = bool(lp)
        if lp:
            try:
                p = Path(lp)
                if p.is_file():
                    size = p.stat().st_size
            except Exception:
                pass
        result.append({
            **t,
            "exists_on_disk": exists,
            "has_lyrics": False,
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
        if track_path.suffix.lower() == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(track_path)
            if audio.pictures:
                pic = audio.pictures[0]
                fmt = pic.mime or "image/jpeg"
                return Response(content=pic.data, media_type=fmt)
        elif track_path.suffix.lower() in (".m4a", ".alac", ".mp4"):
            from mutagen.mp4 import MP4, MP4Cover
            tags = MP4(track_path)
            covers = tags.get("covr", [])
            if covers:
                cover = covers[0]
                fmt = "image/jpeg" if cover.imageformat == MP4Cover.FORMAT_JPEG else "image/png"
                return Response(content=bytes(cover), media_type=fmt)
        elif track_path.suffix.lower() == ".mp3":
            from mutagen.mp3 import MP3
            audio = MP3(track_path)
            if audio.tags:
                for k, v in audio.tags.items():
                    if k.startswith("APIC"):
                        return Response(content=v.data, media_type=getattr(v, "mime", "image/jpeg"))
    except Exception:
        pass

    # 2. Try directory cover files in track parent directory
    parent_dir = track_path.parent
    for cover_name in ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "front.png", "artwork.jpg", "cover.webp"):
        cand = parent_dir / cover_name
        if cand.is_file():
            mime = "image/png" if cand.suffix.lower() == ".png" else "image/webp" if cand.suffix.lower() == ".webp" else "image/jpeg"
            return Response(content=cand.read_bytes(), media_type=mime)

    # 3. Check if DB has an Apple Music artwork_url for this track
    if state:
        track_row = state.get_track_by_path(str(track_path))
        if track_row and track_row.artwork_url and track_row.artwork_url.startswith("http"):
            art_url = track_row.artwork_url.replace("{w}x{h}", "300x300")
            return RedirectResponse(art_url, status_code=307)

    raise HTTPException(404, "No cover art found")


class ConfigUpdate(BaseModel):
    music_dir: Optional[str] = None
    state_dir: Optional[str] = None
    alac_rip_dir: Optional[str] = None
    log_retention_days: Optional[int] = None
    lastfm_api_key: Optional[str] = None
    lastfm_shared_secret: Optional[str] = None
    lastfm_username: Optional[str] = None
    gemini_api_key: Optional[str] = None
    media_user_token: Optional[str] = None
    api_token: Optional[str] = None
    scheduler: Optional[dict] = None
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


def _sync_media_user_token_to_downloader(token: str) -> None:
    if not token or token == "********":
        return
    cand_cfgs = [
        cfg.alac_rip_dir / "apple-music-downloader" / "config.yaml" if cfg and cfg.alac_rip_dir else None,
        cfg.alac_rip_dir / "vendor" / "apple-music-downloader" / "config.yaml" if cfg and cfg.alac_rip_dir else None,
        Path("/app/apple-music-downloader/config.yaml"),
        Path("/app/vendor/apple-music-downloader/config.yaml"),
        Path.home() / ".local/share/pies-alac-rip/apple-music-downloader/config.yaml",
        Path.home() / "Documents/VS-Projects/pies-alac-rip-tool/vendor/apple-music-downloader/config.yaml",
        cfg.state_dir / "apple-music-downloader" / "config.yaml" if cfg else None,
    ]
    for c in cand_cfgs:
        if c and c.parent.exists():
            try:
                amd_cfg = {}
                if c.exists():
                    with open(c) as f:
                        amd_cfg = yaml.safe_load(f) or {}
                amd_cfg["media-user-token"] = token
                with open(c, "w") as f:
                    yaml.dump(amd_cfg, f)
            except Exception:
                pass


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
                    for secret_field in ("api_key", "token", "password", "salt", "webhook_url", "bot_token"):
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
    sanitized["media_user_token_configured"] = bool(data.get("media_user_token"))
    if data.get("media_user_token"):
        sanitized["media_user_token"] = "********"
    return sanitized


@app.put("/config")
def update_config(body: ConfigUpdate):
    current: dict = {}
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH) as f:
            current = yaml.safe_load(f) or {}
    current.pop("github_remote", None)

    updates = body.model_dump(exclude_none=True)
    if updates.get("media_user_token") == "********":
        updates.pop("media_user_token")
    elif "media_user_token" in updates:
        current["media_user_token"] = updates["media_user_token"]
        _sync_media_user_token_to_downloader(updates["media_user_token"])

    # Preserve existing secrets if masked values were sent back
    if "integrations" in updates and isinstance(updates["integrations"], dict):
        cur_integ = current.get("integrations", {})
        for s_name, s_cfg in updates["integrations"].items():
            if isinstance(s_cfg, dict) and s_name in cur_integ:
                cur_s = cur_integ[s_name]
                for secret_field in ("api_key", "token", "password", "salt", "webhook_url", "bot_token"):
                    if s_cfg.get(secret_field) == "********":
                        s_cfg[secret_field] = cur_s.get(secret_field, "")
                    s_cfg.pop(f"{secret_field}_configured", None)

    current.update(updates)
    save_config_file(DEFAULT_CONFIG_PATH, current)
    global cfg, state
    cfg = load_config(DEFAULT_CONFIG_PATH)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    state = StateManager(resolve_db_path(cfg.state_dir))
    try:
        state.auto_rebase_paths(cfg.music_dir)
    except Exception:
        pass

    # Sync running scheduler dynamically
    if "scheduler" in updates and sync_scheduler:
        s_cfg = updates["scheduler"]
        enabled = bool(s_cfg.get("enabled", False))
        interval_min = int(s_cfg.get("interval_minutes", 60))
        sync_scheduler.update_config(enabled=enabled, interval_minutes=interval_min)
        if enabled and not sync_scheduler.is_running():
            sync_scheduler.start()
        elif not enabled and sync_scheduler.is_running():
            sync_scheduler.stop()

    return {"status": "ok"}


@app.get("/database/export")
def export_database():
    if cfg is None:
        raise HTTPException(503, "Config not ready")
    db_file = resolve_db_path(cfg.state_dir)
    if not db_file.exists():
        raise HTTPException(404, "Database file not found")
    return FileResponse(
        path=str(db_file),
        filename="downloaded.db",
        media_type="application/x-sqlite3",
    )


@app.post("/database/import")
async def import_database(request: Request):
    global state, cfg
    if cfg is None:
        raise HTTPException(503, "Config not ready")

    db_target = resolve_db_path(cfg.state_dir)
    db_target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = db_target.with_suffix(".tmp_import")

    content = await request.body()
    if len(content) < 100:
        raise HTTPException(400, "Uploaded file is too small to be a valid SQLite database")

    temp_target.write_bytes(content)
    try:
        test_conn = sqlite3.connect(temp_target)
        test_conn.execute("SELECT count(*) FROM tracks").fetchone()
        test_conn.close()
    except Exception as e:
        if temp_target.exists():
            temp_target.unlink()
        raise HTTPException(400, f"Invalid database file: {e}")

    temp_target.replace(db_target)
    state = StateManager(db_target)
    try:
        state.auto_rebase_paths(cfg.music_dir)
    except Exception:
        pass

    stats = state.get_library_stats()
    return {
        "status": "ok",
        "total_tracks": stats.get("total_tracks", 0),
        "total_playlists": stats.get("total_playlists", 0),
    }



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
    global wrapper_running, wrapper_logging_in, wrapper_process, wrapper_needs_2fa, wrapper_2fa_type
    if wrapper_process and wrapper_process.poll() is not None and wrapper_running:
        wrapper_running = False
        wrapper_logging_in = False
    return {
        "running": wrapper_running,
        "logging_in": wrapper_logging_in,
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
    """Extract and return cover artwork for a track (from embedded tags, directory cover.jpg, or CDN fallback)."""
    if state is None or cfg is None:
        raise HTTPException(503, "Library is not ready")

    if not track_id:
        raise HTTPException(400, "Missing track_id parameter")

    track = state.get_track(track_id)
    if not track:
        raise HTTPException(404, f"Track {track_id} not found")

    file_path: Optional[Path] = None
    if track.local_path:
        candidates = [
            Path(track.local_path).expanduser(),
            resolve_kio_fuse_path(Path(track.local_path).expanduser()),
            cfg.music_dir / track_id,
            cfg.music_dir / Path(track.local_path).name,
        ]
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                if resolved.is_file():
                    file_path = resolved
                    break
            except Exception:
                pass

    if file_path and file_path.is_file():
        # 1. Check embedded tags
        cover_info = metadata_editor.extract_embedded_cover(file_path)
        if cover_info:
            cover_bytes, mime = cover_info
            return Response(
                content=cover_bytes,
                media_type=mime,
                headers={"Cache-Control": "public, max-age=86400"}
            )

        # 2. Check folder cover file (cover.jpg, folder.jpg, etc.)
        for art_name in ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "artwork.jpg"):
            sidecar = file_path.parent / art_name
            if sidecar.is_file():
                mime = "image/png" if sidecar.suffix.lower() == ".png" else "image/jpeg"
                return Response(
                    content=sidecar.read_bytes(),
                    media_type=mime,
                    headers={"Cache-Control": "public, max-age=86400"}
                )

    # 3. Fallback to catalog artwork_url from DB if file is remote / not accessible
    if track.artwork_url:
        cdn_url = track.artwork_url.replace("{w}x{h}", "600x600")
        return Response(
            status_code=307,
            headers={"Location": cdn_url, "Cache-Control": "public, max-age=604800"}
        )

    raise HTTPException(404, "No cover artwork found")


class JellyfinTestRequest(BaseModel):
    server_url: str
    api_key: str


@app.post("/integrations/jellyfin/test")
def post_test_jellyfin(req: JellyfinTestRequest):
    server_url = req.server_url
    api_key = req.api_key
    if cfg and isinstance(cfg.integrations, dict):
        jf_cfg = cfg.integrations.get("jellyfin", {})
        if not server_url:
            server_url = jf_cfg.get("server_url", "")
        if api_key == "********" or not api_key:
            api_key = jf_cfg.get("api_key", "")
    elif cfg and getattr(cfg.integrations, "jellyfin", None):
        if not server_url:
            server_url = getattr(cfg.integrations.jellyfin, "server_url", "")
        if api_key == "********" or not api_key:
            api_key = getattr(cfg.integrations.jellyfin, "api_key", "")
    ok, msg = integrations.test_jellyfin_connection(server_url, api_key)
    return {"success": ok, "message": msg}


class NavidromeTestRequest(BaseModel):
    server_url: str
    user: str
    token: str
    salt: str


@app.post("/integrations/navidrome/test")
def post_test_navidrome(req: NavidromeTestRequest):
    server_url = req.server_url
    user = req.user
    token = req.token
    salt = req.salt
    if cfg and isinstance(cfg.integrations, dict):
        nav_cfg = cfg.integrations.get("navidrome", {})
        if not server_url:
            server_url = nav_cfg.get("server_url", "")
        if not user:
            user = nav_cfg.get("user", "")
        if token == "********" or not token:
            token = nav_cfg.get("token", "")
        if salt == "********" or not salt:
            salt = nav_cfg.get("salt", "")
    elif cfg and getattr(cfg.integrations, "navidrome", None):
        if not server_url:
            server_url = getattr(cfg.integrations.navidrome, "server_url", "")
        if not user:
            user = getattr(cfg.integrations.navidrome, "user", "")
        if token == "********" or not token:
            token = getattr(cfg.integrations.navidrome, "token", "")
        if salt == "********" or not salt:
            salt = getattr(cfg.integrations.navidrome, "salt", "")
    ok, msg = integrations.test_navidrome_connection(server_url, user, token, salt)
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

    bearer = ""
    try:
        bearer = am_api.fetch_bearer_token()
    except Exception:
        pass

    for t in req.tracks:
        # Extract Apple Music song URL
        am = t.get("am_track") or {}
        url = am.get("url") or t.get("url") or ""
        tid = str(t.get("track_id") or "")
        if not url and tid and not tid.startswith("ai-"):
            url = f"https://music.apple.com/us/song/{tid}"

        # If still no URL, search catalog on-the-fly using smart query cascade
        if not url and bearer:
            title = (t.get("title") or "").strip()
            artist = (t.get("artist") or "").strip()
            album = (t.get("album") or "").strip()

            search_queries = []
            if artist and title:
                # Clean featured artists / collabs (e.g. "A & B", "A ft. B", "A feat. B")
                clean_artist = re.split(r"\s+(?:ft\.?|feat\.?|&|x|,)\s+", artist, flags=re.IGNORECASE)[0].strip()
                search_queries.append(f"{artist} {title}")
                if clean_artist != artist:
                    search_queries.append(f"{clean_artist} {title}")
            if title:
                search_queries.append(title)

            for query in search_queries:
                try:
                    matches = am_api.search_apple_music_tracks(query, bearer, limit=3)
                    if matches and matches[0].get("url"):
                        url = matches[0]["url"]
                        break
                except Exception:
                    pass

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
        local = t.get("local_track") or {}
        tid = str(am.get("id") or am.get("track_id") or local.get("track_id") or t.get("track_id") or "")
        title = t.get("title") or am.get("title") or local.get("title") or "Unknown Title"
        artist = t.get("artist") or am.get("artist") or local.get("artist") or "Unknown Artist"
        album = t.get("album") or am.get("album") or local.get("album") or "AI Curated"
        artwork = am.get("artwork_url") or local.get("artwork_url") or t.get("artwork_url")

        if not tid:
            # Generate deterministic fallback ID for unindexed AI tracks
            import hashlib
            clean_slug = re.sub(r"[^\w]+", "-", f"{artist}-{title}").strip("-").lower()
            tid = f"ai-{hashlib.md5(clean_slug.encode('utf-8')).hexdigest()[:12]}"

        existing_track = state.get_track(tid)
        if not existing_track:
            from alac_rip.state import Track
            state.add_track(
                Track(
                    track_id=tid,
                    title=title,
                    artist=artist,
                    album=album,
                    local_path=local.get("local_path", ""),
                    downloaded_at=datetime.now().isoformat(),
                    artwork_url=artwork,
                )
            )
        elif artwork and not existing_track.artwork_url:
            # Update artwork URL if existing track didn't have one
            state.store_artwork(tid, artwork)

        state.add_track_to_playlist(name, tid)

    from alac_rip.state import Playlist
    playlist = Playlist(name=name, url=f"https://music.apple.com/us/playlist/gemini-{prompt_tag}", last_synced=None, paused=False)
    return _playlist_dict(playlist)


# ── Catalog & Discography Download Endpoints ─────────────────────────────────

def _get_storefront() -> str:
    cand_cfgs = [
        cfg.alac_rip_dir / "apple-music-downloader" / "config.yaml" if cfg and cfg.alac_rip_dir else None,
        cfg.alac_rip_dir / "vendor" / "apple-music-downloader" / "config.yaml" if cfg and cfg.alac_rip_dir else None,
        Path("/app/apple-music-downloader/config.yaml"),
        Path("/app/vendor/apple-music-downloader/config.yaml"),
        Path.home() / ".local/share/pies-alac-rip/apple-music-downloader/config.yaml",
        Path.home() / "Documents/VS-Projects/pies-alac-rip-tool/vendor/apple-music-downloader/config.yaml",
        cfg.state_dir / "apple-music-downloader" / "config.yaml" if cfg else None,
    ]
    for c in cand_cfgs:
        if c and c.exists():
            try:
                with open(c) as f:
                    amd_cfg = yaml.safe_load(f) or {}
                sf = amd_cfg.get("storefront")
                if sf and sf not in ("", "enter your account storefront"):
                    return sf
            except Exception:
                pass
    return "us"


@app.get("/catalog/search")
def get_catalog_search(
    q: str = Query(..., min_length=1),
    types: str = Query("songs,albums,artists"),
    limit: int = Query(8, ge=1, le=25),
):
    """Search Apple Music catalog across songs, albums, and artists."""
    try:
        bearer = am_api.fetch_bearer_token()
    except Exception as exc:
        raise HTTPException(502, f"Failed to obtain Apple Music bearer token: {exc}")

    storefront = _get_storefront()
    type_list = tuple(t.strip() for t in types.split(",") if t.strip() in ("songs", "albums", "artists"))
    if not type_list:
        type_list = ("songs", "albums", "artists")

    try:
        results = am_api.search_apple_music_catalog(q, bearer, storefront=storefront, types=type_list, limit=limit)
        return results
    except Exception as exc:
        raise HTTPException(500, f"Catalog search failed: {exc}")


@app.get("/catalog/album")
def get_catalog_album(
    id: Optional[str] = Query(None),
    url: Optional[str] = Query(None),
):
    """Fetch album metadata and full tracklist from Apple Music catalog."""
    target = id or url
    if not target:
        raise HTTPException(400, "Must provide 'id' or 'url' query parameter")

    try:
        bearer = am_api.fetch_bearer_token()
    except Exception as exc:
        raise HTTPException(502, f"Failed to obtain Apple Music bearer token: {exc}")

    storefront = _get_storefront()
    try:
        album_data = am_api.fetch_album_details(target, bearer, storefront=storefront)
        return album_data
    except am_api.AMApiError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Failed to fetch album details: {exc}")


@app.get("/catalog/artist")
def get_catalog_artist(
    id: Optional[str] = Query(None),
    url: Optional[str] = Query(None),
):
    """Fetch artist details and full paginated discography albums."""
    target = id or url
    if not target:
        raise HTTPException(400, "Must provide 'id' or 'url' query parameter")

    try:
        bearer = am_api.fetch_bearer_token()
    except Exception as exc:
        raise HTTPException(502, f"Failed to obtain Apple Music bearer token: {exc}")

    storefront = _get_storefront()
    try:
        artist_data = am_api.fetch_artist_discography(target, bearer, storefront=storefront)
        return artist_data
    except am_api.AMApiError as exc:
        raise HTTPException(404, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Failed to fetch artist discography: {exc}")


class DownloadAlbumRequest(BaseModel):
    url: Optional[str] = None
    album_id: Optional[str] = None
    format: str = "ALAC"


@app.post("/download/album")
def post_download_album(req: DownloadAlbumRequest):
    """Queue download for a single album."""
    format_ = _validate_download_format(req.format)
    target_url = req.url
    if not target_url and req.album_id:
        target_url = f"https://music.apple.com/us/album/{req.album_id}"
    if not target_url:
        raise HTTPException(400, "Must provide 'url' or 'album_id'")

    try:
        valid_url = _validate_apple_music_url(target_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    if state:
        db_id = state.enqueue_download_job(
            url=valid_url,
            title="Album Download",
            format=format_,
            item_type="album",
        )
        _queue_wake_event.set()
        _broadcast_queue_event({"event": "queue_updated", "count": 1})
        return {"queued": 1, "job_ids": [db_id]}

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
    _queue_wake_event.set()

    return {"queued": 1, "job_ids": [job_id]}


class DownloadArtistAlbumsRequest(BaseModel):
    artist_id: Optional[str] = None
    albums: list[dict[str, Any]] = []
    format: str = "ALAC"


@app.post("/download/artist-albums")
def post_download_artist_albums(req: DownloadArtistAlbumsRequest):
    """Queue batch download for selected albums of an artist."""
    format_ = _validate_download_format(req.format)
    if not req.albums:
        raise HTTPException(400, "Must provide at least one album in 'albums' list")

    batch_id = str(uuid.uuid4())
    batch_title = f"Artist Discography Batch"
    jobs_to_insert = []

    for alb in req.albums:
        url = alb.get("url") or ""
        alb_id = str(alb.get("id") or alb.get("album_id") or "")
        if not url and alb_id:
            url = f"https://music.apple.com/us/album/{alb_id}"

        if not url:
            continue

        try:
            valid_url = _validate_apple_music_url(url)
        except ValueError:
            continue

        jobs_to_insert.append({
            "batch_id": batch_id,
            "batch_title": alb.get("artist") or batch_title,
            "url": valid_url,
            "title": alb.get("title") or alb.get("name") or "Album Download",
            "artist": alb.get("artist") or "",
            "album": alb.get("album") or alb.get("title") or "",
            "artwork_url": alb.get("artwork_url"),
            "format": format_,
            "item_type": "album",
            "total_tracks": alb.get("total_tracks") or alb.get("track_count") or 0,
        })

    if not jobs_to_insert:
        raise HTTPException(400, "No valid albums provided")

    if state:
        job_ids = state.bulk_enqueue_download_jobs(jobs_to_insert)
        _queue_wake_event.set()
        _broadcast_queue_event({"event": "queue_updated", "count": len(job_ids)})
        return {"queued": len(job_ids), "job_ids": job_ids, "batch_id": batch_id}

    job_ids = []
    for j in jobs_to_insert:
        job_id = str(uuid.uuid4())
        job: dict = {
            "id": job_id,
            "type": "one-off",
            "url": j["url"],
            "format": format_,
            "playlist_name": None,
            "log_q": queue.Queue(),
            "started": threading.Event(),
        }
        with pending_jobs_lock:
            pending_jobs.append(job)
        job_queue.put(job)
        job_ids.append(job_id)

    _queue_wake_event.set()
    return {"queued": len(job_ids), "job_ids": job_ids}


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


_artwork_resync_lock = threading.Lock()
_artwork_resync_status: dict[str, Any] = {
    "running": False,
    "total": 0,
    "processed": 0,
    "updated": 0,
    "message": "",
    "error": None,
}


def _run_artwork_resync() -> None:
    global _artwork_resync_status
    try:
        tracks = state.get_all_tracks_with_provenance() if state else []
        missing = [t for t in tracks if not t.get("artwork_url")]
        _artwork_resync_status["total"] = len(missing)
        _artwork_resync_status["processed"] = 0
        _artwork_resync_status["updated"] = 0

        if not missing:
            _artwork_resync_status["running"] = False
            _artwork_resync_status["message"] = "All tracks already have artwork!"
            return

        bearer = ""
        try:
            bearer = am_api.fetch_bearer_token()
        except Exception:
            pass

        updated_count = 0
        for idx, t in enumerate(missing):
            tid = t["track_id"]
            title = (t.get("title") or "").strip()
            artist = (t.get("artist") or "").strip()
            album = (t.get("album") or "").strip()
            local_path = t.get("local_path") or ""
            found_art = None

            # 1. Search Apple Music catalog
            if bearer and (title or album):
                clean_artist = re.split(r"\s+(?:ft\.?|feat\.?|&|x|,)\s+", artist, flags=re.IGNORECASE)[0].strip()
                queries = []
                if artist and title:
                    queries.append(f"{artist} {title}".strip())
                if artist and album:
                    queries.append(f"{artist} {album}".strip())
                if clean_artist != artist:
                    if title:
                        queries.append(f"{clean_artist} {title}".strip())
                    if album:
                        queries.append(f"{clean_artist} {album}".strip())
                if title:
                    queries.append(title)
                if album:
                    queries.append(album)

                for q in queries:
                    try:
                        matches = am_api.search_apple_music_tracks(q, bearer, limit=1)
                        if matches and matches[0].get("artwork_url"):
                            found_art = matches[0]["artwork_url"]
                            break
                    except Exception:
                        pass

            # 2. Check local embedded or directory cover artwork
            if not found_art and local_path:
                try:
                    resolved = _resolve_library_file(local_path)
                    if resolved.exists():
                        found_art = f"/track-art?path={local_path}"
                except Exception:
                    pass

            if found_art and state:
                state.store_artwork(tid, found_art)
                updated_count += 1

            _artwork_resync_status["processed"] = idx + 1
            _artwork_resync_status["updated"] = updated_count
            _artwork_resync_status["message"] = f"Processed {idx + 1}/{len(missing)} ({updated_count} matched)"

        _artwork_resync_status["running"] = False
        _artwork_resync_status["message"] = f"Finished! Matched cover art for {updated_count} of {len(missing)} tracks."
    except Exception as exc:
        _artwork_resync_status["running"] = False
        _artwork_resync_status["error"] = str(exc)
        _artwork_resync_status["message"] = f"Resync failed: {exc}"


@app.post("/library/resync-artwork")
def post_library_resync_artwork():
    """Start asynchronous global artwork resync across library and playlists."""
    if state is None:
        raise HTTPException(503, "Library is not ready")

    with _artwork_resync_lock:
        if _artwork_resync_status.get("running"):
            return _artwork_resync_status

        _artwork_resync_status["running"] = True
        _artwork_resync_status["error"] = None
        _artwork_resync_status["message"] = "Starting artwork resync…"
        _artwork_resync_status["processed"] = 0
        _artwork_resync_status["updated"] = 0

        t = threading.Thread(target=_run_artwork_resync, daemon=True)
        t.start()

    return _artwork_resync_status


@app.get("/library/resync-artwork/status")
def get_library_resync_artwork_status():
    """Get live progress of artwork resync."""
    return _artwork_resync_status


# ─────────────────────────────────────────────────────────────────────────────
# Storage, SMB Network Mount & Navidrome Integration Endpoints
# ─────────────────────────────────────────────────────────────────────────────

class TestStorageRequest(BaseModel):
    path: str

class ResolveSmbRequest(BaseModel):
    uri: str

class GenerateNavidromeTokenRequest(BaseModel):
    password: str


@app.post("/api/v1/storage/test")
def test_storage_endpoint(req: TestStorageRequest):
    """Test read/write/delete permissions, latency, and free space on any storage path."""
    import alac_rip.smb_helper as smb_helper
    if not req.path.strip():
        raise HTTPException(status_code=400, detail="Path cannot be empty")
    return smb_helper.test_storage_path(Path(req.path.strip()))


@app.post("/api/v1/storage/resolve-smb")
def resolve_smb_endpoint(req: ResolveSmbRequest):
    """Attempt to resolve an smb:// URI to an active local GVFS or CIFS mount point."""
    import alac_rip.smb_helper as smb_helper
    if not req.uri.strip():
        raise HTTPException(status_code=400, detail="SMB URI cannot be empty")
    resolved = smb_helper.resolve_smb_mount(req.uri.strip())
    return {
        "uri": req.uri.strip(),
        "resolved_path": str(resolved) if resolved else None,
        "found": resolved is not None,
    }


@app.post("/api/v1/integrations/navidrome/generate-token")
def generate_navidrome_token_endpoint(req: GenerateNavidromeTokenRequest):
    """Generate Subsonic MD5 token and salt from a password for Navidrome authentication."""
    import alac_rip.smb_helper as smb_helper
    if not req.password:
        raise HTTPException(status_code=400, detail="Password cannot be empty")
    return smb_helper.generate_subsonic_token(req.password)


class TestWebhookRequest(BaseModel):
    service: str  # "discord", "telegram", "gotify", "jellyfin", "navidrome"
    url: Optional[str] = None
    token: Optional[str] = None
    chat_id: Optional[str] = None
    api_key: Optional[str] = None
    user: Optional[str] = None
    salt: Optional[str] = None


@app.post("/api/v1/integrations/test-webhook")
def test_webhook_endpoint(req: TestWebhookRequest):
    svc = req.service.lower().strip()
    integ = cfg.integrations if (cfg and isinstance(cfg.integrations, dict)) else {}

    if svc == "discord":
        url = req.url
        if not url or url == "********":
            url = integ.get("discord", {}).get("webhook_url", "")
        if not url:
            raise HTTPException(400, "Discord Webhook URL is required")
        ok, msg = integrations.send_discord_webhook(
            webhook_url=url,
            title="♫ Pies Pear Music Test",
            description="Test notification from Pies Pear Music server: Online & Reachable.",
            fields=[{"name": "Status", "value": "✓ Reachable", "inline": True}],
        )
        return {"success": ok, "message": msg}
    elif svc == "telegram":
        token = req.token
        chat_id = req.chat_id
        if not token or token == "********":
            token = integ.get("telegram", {}).get("bot_token", "")
        if not chat_id:
            chat_id = integ.get("telegram", {}).get("chat_id", "")
        if not token or not chat_id:
            raise HTTPException(400, "Bot token and Chat ID are required")
        ok, msg = integrations.send_telegram_notification(
            bot_token=token,
            chat_id=chat_id,
            message="<b>♫ Pies Pear Music</b>\n\nTest notification from server: Online & Reachable.",
        )
        return {"success": ok, "message": msg}
    elif svc == "gotify":
        url = req.url
        token = req.token
        if not url:
            url = integ.get("gotify", {}).get("server_url", "")
        if not token or token == "********":
            token = integ.get("gotify", {}).get("token", "")
        if not url or not token:
            raise HTTPException(400, "Server URL and App token are required")
        ok, msg = integrations.send_gotify_notification(
            server_url=url,
            token=token,
            title="♫ Pies Pear Music Test",
            message="Test notification from Pies Pear Music server: Online & Reachable.",
        )
        return {"success": ok, "message": msg}
    elif svc == "jellyfin":
        url = req.url or integ.get("jellyfin", {}).get("server_url", "")
        api_key = req.api_key
        if not api_key or api_key == "********":
            api_key = integ.get("jellyfin", {}).get("api_key", "")
        if not url or not api_key:
            raise HTTPException(400, "Server URL and API Key are required")
        ok, msg = integrations.test_jellyfin_connection(url, api_key)
        return {"success": ok, "message": msg}
    elif svc == "navidrome":
        url = req.url or integ.get("navidrome", {}).get("server_url", "")
        user = req.user or integ.get("navidrome", {}).get("user", "")
        token = req.token
        if not token or token == "********":
            token = integ.get("navidrome", {}).get("token", "")
        salt = req.salt
        if not salt or salt == "********":
            salt = integ.get("navidrome", {}).get("salt", "")
        if not url or not user or not token:
            raise HTTPException(400, "Server URL, user, and token are required")
        ok, msg = integrations.test_navidrome_connection(url, user, token, salt)
        return {"success": ok, "message": msg}
    else:
        raise HTTPException(400, f"Unsupported service '{req.service}'")


class UpdateSchedulerRequest(BaseModel):
    enabled: bool
    interval_minutes: int


@app.get("/api/v1/scheduler/status")
def get_scheduler_status_endpoint():
    if sync_scheduler is None:
        return {
            "enabled": False,
            "running": False,
            "interval_minutes": 60,
            "last_run_time": None,
            "last_run_status": "inactive",
            "last_run_message": "",
            "run_count": 0,
        }
    return sync_scheduler.get_status()


@app.post("/api/v1/scheduler/trigger")
def trigger_scheduler_sync_endpoint():
    if sync_scheduler is None:
        raise HTTPException(503, "Scheduler is not initialized")
    sync_scheduler.trigger_now()
    return {"status": "triggered"}


@app.post("/api/v1/scheduler/config")
def update_scheduler_config_endpoint(req: UpdateSchedulerRequest):
    if sync_scheduler is None:
        raise HTTPException(503, "Scheduler is not initialized")
    sync_scheduler.update_config(enabled=req.enabled, interval_minutes=req.interval_minutes)
    if req.enabled and not sync_scheduler.is_running():
        sync_scheduler.start()
    elif not req.enabled and sync_scheduler.is_running():
        sync_scheduler.stop()
    return sync_scheduler.get_status()


def _find_web_dir() -> Optional[Path]:
    """Find the frontend build directory if available."""
    candidates = []
    if cfg and cfg.web_dir and cfg.web_dir.exists():
        candidates.append(cfg.web_dir)
    candidates.extend([
        Path(__file__).parent.parent / "app" / "build",
        Path.cwd() / "app" / "build",
        Path.cwd() / "build",
        Path("/app/web"),
    ])
    for c in candidates:
        if c.exists() and (c / "index.html").exists():
            return c
    return None


_web_dir = _find_web_dir()
if _web_dir:
    if (_web_dir / "_app").exists():
        app.mount("/_app", StaticFiles(directory=str(_web_dir / "_app")), name="app_assets")
    if (_web_dir / "favicon.png").exists():
        @app.get("/favicon.png", include_in_schema=False)
        def favicon():
            return FileResponse(_web_dir / "favicon.png")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_spa_frontend(full_path: str):
        if full_path.startswith("api/") or full_path in ("health", "diagnostics", "metrics", "docs", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not Found")
        file_path = _web_dir / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(_web_dir / "index.html")


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
    port = int(os.environ.get("PIES_PORT") or os.environ.get("PORT") or "10025")
    host = os.environ.get("PIES_HOST") or os.environ.get("HOST") or ("0.0.0.0" if "--headless" in sys.argv or os.environ.get("PIES_HEADLESS") else "127.0.0.1")
    if "--sidecar-handshake" in sys.argv:
        try:
            port, _api_capability = _read_sidecar_handshake(sys.stdin.readline())
            host = "127.0.0.1"
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        uvicorn.run(app, fd=sock.fileno(), log_level="warning")
    else:
        uvicorn.run(app, host=host, port=port, log_level="info")
