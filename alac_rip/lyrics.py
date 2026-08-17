import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional
import requests

logger = logging.getLogger(__name__)

LRCLIB_API_URL = "https://lrclib.net/api/get"
_MAX_LYRICS_BYTES = 500_000


def fetch_lrclib_lyrics(
    track_title: str,
    artist_name: str,
    album_name: Optional[str] = None,
    duration_seconds: Optional[int | float] = None,
    timeout: float = 10.0,
) -> Optional[dict]:
    """
    Fetch lyrics from LRCLIB API.
    Returns a dict with 'syncedLyrics', 'plainLyrics', etc., or None if not found/error.
    """
    if not track_title or not artist_name:
        return None

    params: dict[str, str | int] = {
        "track_name": track_title.strip()[:200],
        "artist_name": artist_name.strip()[:200],
    }
    if album_name and album_name.strip():
        params["album_name"] = album_name.strip()[:200]
    if duration_seconds and duration_seconds > 0:
        params["duration"] = int(round(duration_seconds))

    headers = {
        "User-Agent": "Pies-ALAC-Rip-Tool/1.0 (https://github.com/ilikepie96mng/pies-alac-rip-tool)",
    }

    try:
        resp = requests.get(LRCLIB_API_URL, params=params, headers=headers, timeout=timeout, allow_redirects=False)
        if resp.status_code == 200:
            if len(resp.content) > _MAX_LYRICS_BYTES:
                return None
            data = resp.json()
            if isinstance(data, dict):
                return data
        elif resp.status_code == 404:
            # Try without album name or duration if specific match failed
            if album_name:
                params.pop("album_name", None)
                fallback_resp = requests.get(LRCLIB_API_URL, params=params, headers=headers, timeout=timeout, allow_redirects=False)
                if fallback_resp.status_code == 200:
                    if len(fallback_resp.content) > _MAX_LYRICS_BYTES:
                        return None
                    data = fallback_resp.json()
                    if isinstance(data, dict):
                        return data
        else:
            logger.debug(f"LRCLIB returned status {resp.status_code} for {track_title} - {artist_name}")
    except Exception as e:
        logger.debug(f"LRCLIB request failed: {e}")

    return None


def save_lrc_file(lrc_path: Path, lyrics_text: str) -> bool:
    """
    Safely write lyrics to .lrc sidecar file.
    Guards against symlink traversal and non-regular target files.
    """
    if not lyrics_text or len(lyrics_text) > _MAX_LYRICS_BYTES:
        return False

    try:
        resolved_parent = lrc_path.parent.resolve()
        resolved_parent.mkdir(parents=True, exist_ok=True)

        # Refuse to follow symlinks if lrc_path or any parent is a symlink
        if lrc_path.is_symlink():
            logger.warning(f"Refusing to write .lrc file: {lrc_path} is a symlink")
            return False

        # Write to temporary file in the same directory and atomically replace
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=".lrc_tmp_",
            suffix=".lrc",
            dir=str(resolved_parent)
        )
        tmp_path = Path(tmp_name)

        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(lyrics_text)
                f.flush()
                os.fsync(f.fileno())

            # Double-check destination is not a symlink before replacing
            if lrc_path.is_symlink():
                tmp_path.unlink(missing_ok=True)
                return False

            os.replace(str(tmp_path), str(lrc_path))
            return True
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
    except Exception as e:
        logger.error(f"Failed to save .lrc file to {lrc_path}: {e}")
        return False
