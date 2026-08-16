import logging
import re
from pathlib import Path
from typing import Optional
import requests

logger = logging.getLogger(__name__)

LRCLIB_API_URL = "https://lrclib.net/api/get"


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
        "track_name": track_title.strip(),
        "artist_name": artist_name.strip(),
    }
    if album_name and album_name.strip():
        params["album_name"] = album_name.strip()
    if duration_seconds and duration_seconds > 0:
        params["duration"] = int(round(duration_seconds))

    headers = {
        "User-Agent": "Pies-ALAC-Rip-Tool/1.0 (https://github.com/ilikepie96mng/pies-alac-rip-tool)",
    }

    try:
        resp = requests.get(LRCLIB_API_URL, params=params, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                return data
        elif resp.status_code == 404:
            # Try without album name or duration if specific match failed
            if album_name:
                params.pop("album_name", None)
                fallback_resp = requests.get(LRCLIB_API_URL, params=params, headers=headers, timeout=timeout)
                if fallback_resp.status_code == 200:
                    data = fallback_resp.json()
                    if isinstance(data, dict):
                        return data
        else:
            logger.debug(f"LRCLIB returned status {resp.status_code} for {track_title} - {artist_name}")
    except Exception as e:
        logger.debug(f"LRCLIB request failed: {e}")

    return None


def save_lrc_file(lrc_path: Path, lyrics_text: str) -> bool:
    """Safely write lyrics to .lrc sidecar file."""
    try:
        lrc_path.parent.mkdir(parents=True, exist_ok=True)
        lrc_path.write_text(lyrics_text, encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"Failed to save .lrc file to {lrc_path}: {e}")
        return False
