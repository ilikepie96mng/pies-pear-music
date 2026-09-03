import os
import re
import unicodedata
from pathlib import Path

# Characters forbidden in filenames across Linux, Windows, and FAT32/exFAT
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]')

# Windows reserved device names (case-insensitive)
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

MAX_COMPONENT_LENGTH = 240


def sanitize(name: str) -> str:
    """Sanitize metadata strings into safe filesystem components.

    Enforces universal safety for Linux, Windows (NTFS), and FAT32/exFAT:
    - Normalizes Unicode (NFC).
    - Replaces forbidden characters and C0/C1 control codes (\r, \n, \t, etc.) with underscores.
    - Strips leading and trailing whitespace and trailing dots (forbidden in Windows/FAT32).
    - Prevents path-traversal (names that are entirely dots or empty collapse to '_').
    - Disambiguates Windows reserved device names (CON, AUX, NUL, PRN, COM1-9, LPT1-9).
    - Truncates to MAX_COMPONENT_LENGTH characters to prevent ENAMETOOLONG.
    """
    if not name:
        return "_"

    # Unicode normalization
    normalized = unicodedata.normalize("NFC", str(name))

    # Replace forbidden chars and control characters
    cleaned = _FORBIDDEN.sub("_", normalized).strip()

    # Strip trailing dots and spaces (invalid on Windows and FAT32)
    cleaned = cleaned.rstrip(". ")

    # Collapse empty or dot-only segments
    if not cleaned or cleaned.strip(".") == "":
        return "_"

    # Check for Windows reserved names
    base_name = cleaned.split(".")[0].upper()
    if base_name in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}_"

    # Truncate to maximum component length
    if len(cleaned) > MAX_COMPONENT_LENGTH:
        cleaned = cleaned[:MAX_COMPONENT_LENGTH].rstrip(". ")

    return cleaned or "_"


ALLOWED_EXTENSIONS = frozenset({".m4a", ".flac", ".mp3", ".lrc", ".m3u8", ".jpg", ".png", ".webp"})


def track_path(music_dir: Path, artist: str, album: str, track_num: int, title: str, ext: str = ".m4a") -> Path:
    """Return the canonical absolute path for a downloaded track file and assert containment."""
    s_artist = sanitize(artist)
    s_album = sanitize(album)
    s_title = sanitize(title)
    s_ext = ext if ext.startswith(".") else f".{ext}"
    if s_ext.lower() not in ALLOWED_EXTENSIONS:
        s_ext = ".flac" if "flac" in s_ext.lower() else ".m4a"

    target = (
        music_dir
        / "artists"
        / s_artist
        / s_album
        / f"{track_num:02d} - {s_title}{s_ext}"
    )
    return target


def cover_path(music_dir: Path, artist: str, album: str) -> Path:
    """Return the canonical path for cover.jpg in an album directory."""
    return music_dir / "artists" / sanitize(artist) / sanitize(album) / "cover.jpg"


def ensure_album_dir(music_dir: Path, artist: str, album: str) -> Path:
    """Create artists/Artist/Album directory tree if it doesn't exist. Returns the album dir path."""
    album_dir = music_dir / "artists" / sanitize(artist) / sanitize(album)
    album_dir.mkdir(parents=True, exist_ok=True)
    return album_dir

