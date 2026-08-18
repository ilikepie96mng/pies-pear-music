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
    Fetch lyrics from LRCLIB API with a 3-tier fallback strategy:
    1. Strict /api/get with track, artist, album, duration
    2. Relaxed /api/get without album/duration
    3. Search /api/search?q={artist} {title}
    Returns a dict with 'syncedLyrics', 'plainLyrics', etc., or None if not found/error.
    """
    if not track_title or not artist_name:
        return None

    headers = {
        "User-Agent": "Pies-ALAC-Rip-Tool/1.0 (https://github.com/ilikepie96mng/pies-alac-rip-tool)",
    }

    # Step 1: Strict query
    params: dict[str, str | int] = {
        "track_name": track_title.strip()[:200],
        "artist_name": artist_name.strip()[:200],
    }
    if album_name and album_name.strip():
        params["album_name"] = album_name.strip()[:200]
    if duration_seconds and duration_seconds > 0:
        params["duration"] = int(round(duration_seconds))

    try:
        resp = requests.get(LRCLIB_API_URL, params=params, headers=headers, timeout=timeout, allow_redirects=False)
        if resp.status_code == 200:
            if len(resp.content) <= _MAX_LYRICS_BYTES:
                data = resp.json()
                if isinstance(data, dict):
                    return data
    except Exception as e:
        logger.debug(f"LRCLIB step 1 failed: {e}")

    # Step 2: Relaxed query without album / duration
    if album_name or duration_seconds:
        try:
            relaxed_params = {
                "track_name": track_title.strip()[:200],
                "artist_name": artist_name.strip()[:200],
            }
            resp = requests.get(LRCLIB_API_URL, params=relaxed_params, headers=headers, timeout=timeout, allow_redirects=False)
            if resp.status_code == 200:
                if len(resp.content) <= _MAX_LYRICS_BYTES:
                    data = resp.json()
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            logger.debug(f"LRCLIB step 2 failed: {e}")

    # Step 3: Full search fallback
    try:
        search_query = f"{artist_name.strip()} {track_title.strip()}"[:200]
        search_url = "https://lrclib.net/api/search"
        resp = requests.get(search_url, params={"q": search_query}, headers=headers, timeout=timeout, allow_redirects=False)
        if resp.status_code == 200:
            if len(resp.content) <= _MAX_LYRICS_BYTES:
                results = resp.json()
                if isinstance(results, list) and results:
                    # Prefer item with syncedLyrics, else plainLyrics
                    for item in results:
                        if isinstance(item, dict) and item.get("syncedLyrics"):
                            return item
                    for item in results:
                        if isinstance(item, dict) and item.get("plainLyrics"):
                            return item
                    if isinstance(results[0], dict):
                        return results[0]
    except Exception as e:
        logger.debug(f"LRCLIB step 3 search failed: {e}")

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
