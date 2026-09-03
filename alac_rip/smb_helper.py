import hashlib
import os
import random
import re
import string
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional


def generate_subsonic_token(password: str) -> dict[str, str]:
    """Generate Subsonic authentication salt and MD5 token from a plain password.
    
    Subsonic/Navidrome token scheme:
    token = md5(password + salt)
    """
    if not password:
        raise ValueError("Password cannot be empty")
    chars = string.ascii_letters + string.digits
    salt = "".join(random.choice(chars) for _ in range(12))
    token = hashlib.md5((password + salt).encode("utf-8")).hexdigest()
    return {"token": token, "salt": salt}


def parse_smb_uri(smb_uri: str) -> dict[str, str]:
    """Parse an smb:// URI into its host, share, user, and subpath components."""
    clean = smb_uri.strip()
    if not clean.lower().startswith("smb://"):
        raise ValueError("URI must start with smb://")

    # Replace smb:// with http:// for urllib.parse convenience
    http_equivalent = "http://" + clean[6:]
    parsed = urllib.parse.urlparse(http_equivalent)

    host = parsed.hostname or ""
    user = parsed.username or ""
    port = parsed.port

    path_parts = [p for p in parsed.path.split("/") if p]
    share = path_parts[0] if path_parts else ""
    subpath = "/".join(path_parts[1:]) if len(path_parts) > 1 else ""

    return {
        "host": host,
        "user": user,
        "port": str(port) if port else "",
        "share": share,
        "subpath": subpath,
    }


import subprocess

def resolve_smb_mount(smb_uri: str) -> Optional[Path]:
    """
    Attempt to find or mount an active local mount point for the given smb:// URI.
    Checks:
    1. KDE KIO-FUSE DBus interface (mountUrl) and /run/user/<uid>/kio-fuse-* (KDE Plasma / Dolphin)
    2. GNOME GVFS mount points: /run/user/<uid>/gvfs/smb-share:* (GNOME Files)
    3. Standard Linux /proc/mounts CIFS entries
    """
    clean_uri = smb_uri.strip()
    try:
        parsed = parse_smb_uri(clean_uri)
    except Exception:
        return None

    host = parsed["host"].lower()
    share = parsed["share"].lower()
    subpath = parsed["subpath"]
    uid = os.getuid()

    # 1. Check KDE KIOFuse DBus mountUrl (Dolphin / KDE Plasma)
    try:
        cmd = [
            "gdbus", "call", "--session",
            "--dest", "org.kde.KIOFuse",
            "--object-path", "/org/kde/KIOFuse",
            "--method", "org.kde.KIOFuse.VFS.mountUrl",
            clean_uri,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3.0)
        if res.returncode == 0 and res.stdout:
            match = re.search(r"'(.*?)'", res.stdout)
            if match:
                kio_path = Path(match.group(1))
                if kio_path.exists():
                    return kio_path.resolve()
    except Exception:
        pass

    # 2. Check KDE kio-fuse filesystem directories directly
    run_user = Path(f"/run/user/{uid}")
    if run_user.exists():
        try:
            for d in run_user.glob("kio-fuse-*"):
                if d.is_dir():
                    smb_dir = d / "smb"
                    if smb_dir.exists():
                        for host_dir in smb_dir.iterdir():
                            if host in host_dir.name.lower():
                                target = host_dir / share / subpath if subpath else host_dir / share
                                if target.exists():
                                    return target.resolve()
        except Exception:
            pass

    # 3. Check GVFS mounts (GNOME / Files / Nautilus)
    gvfs_dir = Path(f"/run/user/{uid}/gvfs")
    if gvfs_dir.exists() and gvfs_dir.is_dir():
        try:
            for entry in gvfs_dir.iterdir():
                name_lower = entry.name.lower()
                if "smb-share" in name_lower and (host in name_lower) and (share in name_lower):
                    target = entry / subpath if subpath else entry
                    try:
                        target.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        pass
                    if target.exists() or entry.exists():
                        return target.resolve()
        except (PermissionError, OSError):
            pass

    # 4. Check /proc/mounts for CIFS / SMB mounts
    proc_mounts = Path("/proc/mounts")
    if proc_mounts.exists():
        try:
            content = proc_mounts.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                parts = line.strip().split()
                if len(parts) >= 3:
                    src, mount_point, fstype = parts[0].lower(), parts[1], parts[2].lower()
                    if fstype in ("cifs", "smbfs"):
                        if host in src and share in src:
                            mount_path = Path(mount_point)
                            target = mount_path / subpath if subpath else mount_path
                            try:
                                target.mkdir(parents=True, exist_ok=True)
                            except Exception:
                                pass
                            if target.exists() or mount_path.exists():
                                return target.resolve()
        except Exception:
            pass

    return None


def test_storage_path(target_path: Path) -> dict[str, Any]:
    """Test accessibility, read/write/delete permissions, disk space, and latency on a path."""
    resolved = target_path.expanduser().resolve()
    result: dict[str, Any] = {
        "path": str(resolved),
        "exists": False,
        "is_dir": False,
        "writable": False,
        "free_space_bytes": 0,
        "free_space_formatted": "0 GB",
        "latency_ms": 0.0,
        "message": "",
    }

    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        result["message"] = f"Cannot create directory: {e}"
        return result

    result["exists"] = resolved.exists()
    result["is_dir"] = resolved.is_dir()

    if not result["is_dir"]:
        result["message"] = "Path is not a directory"
        return result

    # Measure write & delete latency
    test_file = resolved / f".pies_test_{os.getpid()}_{int(time.time()*1000)}.tmp"
    start_time = time.perf_counter()
    try:
        test_file.write_bytes(b"pies-pear-music-storage-probe-test\n")
        read_back = test_file.read_bytes()
        if read_back != b"pies-pear-music-storage-probe-test\n":
            raise ValueError("Read-back verification mismatch")
        test_file.unlink(missing_ok=True)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        result["writable"] = True
        result["latency_ms"] = round(elapsed_ms, 2)
    except Exception as e:
        test_file.unlink(missing_ok=True)
        result["message"] = f"Write test failed: {e}"
        return result

    # Disk Space
    try:
        st = os.statvfs(resolved)
        free_bytes = st.f_bavail * st.f_frsize
        result["free_space_bytes"] = free_bytes
        gb = free_bytes / (1024 ** 3)
        result["free_space_formatted"] = f"{gb:.2f} GB"
        result["message"] = f"Ready (Write verified, ~{result['latency_ms']}ms latency, {result['free_space_formatted']} free)"
    except Exception:
        result["message"] = f"Ready (Write verified, ~{result['latency_ms']}ms latency)"

    return result
