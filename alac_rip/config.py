import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "pies-alac-rip" / "config.yaml"


@dataclass
class Config:
    music_dir: Path
    state_dir: Path
    alac_rip_dir: Path
    log_retention_days: int = 2
    lastfm_api_key: str = ""
    lastfm_shared_secret: str = ""
    lastfm_username: str = ""
    gemini_api_key: str = ""
    api_token: str = ""
    web_dir: Path = field(default_factory=lambda: Path(""))
    scheduler: dict[str, Any] = field(default_factory=dict)
    integrations: dict[str, Any] = field(default_factory=dict)


def resolve_kio_fuse_path(p: Path) -> Path:
    """If a path was pointing to an older session's kio-fuse mount, dynamically resolve to the active mount."""
    path_str = str(p)
    if "kio-fuse-" in path_str:
        if p.exists():
            return p
        # Check if another kio-fuse mount is currently active under /run/user/<uid>/
        try:
            parts = path_str.split("kio-fuse-", 1)
            parent = Path(parts[0])
            subpath = parts[1].split("/", 1)[1] if "/" in parts[1] else ""
            if parent.exists() and subpath:
                for candidate in parent.glob("kio-fuse-*"):
                    target = candidate / subpath
                    if target.exists():
                        return target.resolve()
        except Exception:
            pass
        # Attempt DBus mountUrl if kio-fuse DBus service is available
        try:
            import subprocess
            if "/smb/" in path_str:
                smb_part = path_str.split("/smb/", 1)[1]
                smb_url = f"smb://{smb_part}"
                r = subprocess.run(
                    ["qdbus", "org.kde.KIOFuse", "/org/kde/KIOFuse", "org.kde.KIOFuse.VFS.mountUrl", smb_url],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0 and r.stdout.strip():
                    mount_path = Path(r.stdout.strip())
                    if mount_path.exists():
                        return mount_path.resolve()
        except Exception:
            pass
    return p


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    env_config_path = os.environ.get("PIES_CONFIG_PATH")
    if env_config_path:
        path = Path(env_config_path)

    data: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

    def p(key: str, env_var: str, default: str = "") -> Path:
        val = os.environ.get(env_var) or data.get(key, default)
        resolved = Path(val).expanduser().resolve() if val else Path("")
        return resolve_kio_fuse_path(resolved)

    api_token = os.environ.get("PIES_API_TOKEN") or str(data.get("api_token", "")).strip()
    web_dir_val = os.environ.get("PIES_WEB_DIR") or data.get("web_dir", "")
    web_dir_resolved = Path(web_dir_val).expanduser().resolve() if web_dir_val else Path("")

    return Config(
        music_dir=p("music_dir", "PIES_MUSIC_DIR", "~/Music/pies-alac-rip"),
        state_dir=p("state_dir", "PIES_STATE_DIR", str(Path.home() / ".local/share/pies-alac-rip")),
        alac_rip_dir=p("alac_rip_dir", "PIES_ALAC_RIP_DIR", ""),
        log_retention_days=int(data.get("log_retention_days", 2)),
        lastfm_api_key=data.get("lastfm_api_key", ""),
        lastfm_shared_secret=data.get("lastfm_shared_secret", ""),
        lastfm_username=data.get("lastfm_username", ""),
        gemini_api_key=data.get("gemini_api_key", ""),
        api_token=api_token,
        web_dir=web_dir_resolved,
        scheduler=data.get("scheduler", {}),
        integrations=data.get("integrations", {}),
    )


def save_config_file(path: Path, data: dict) -> None:
    """Atomically write configuration YAML with private 0600 permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(tmp_path), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
        try:
            os.chmod(str(path), 0o600)
        except OSError:
            pass
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
