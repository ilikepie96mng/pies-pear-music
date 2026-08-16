import re
import xml.etree.ElementTree as ET
from typing import Optional

import requests

_bearer_token_cache: str | None = None  # not thread-safe; safe for single-threaded use


class AMApiError(Exception):
    pass


def fetch_bearer_token() -> str:
    """Scrape music.apple.com, extract the Bearer JWT from the JS bundle, and return it.

    Result is cached in a module-level variable for the lifetime of the process.
    Raises AMApiError on network failure or if the token cannot be found.
    """
    global _bearer_token_cache
    if _bearer_token_cache:
        return _bearer_token_cache

    try:
        r = requests.get("https://music.apple.com", timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        raise AMApiError(f"Could not fetch music.apple.com: {e}") from e

    match = re.search(
        r'<script[^>]+src="((?:https://music\.apple\.com)?/assets/index[^"]+\.js)"', r.text
    )
    if not match:
        raise AMApiError("Could not find Apple Music JS bundle in page HTML")

    path = match.group(1)
    js_url = path if path.startswith("http") else f"https://music.apple.com{path}"
    try:
        js_r = requests.get(js_url, timeout=15)
        js_r.raise_for_status()
    except requests.RequestException as e:
        raise AMApiError(f"Could not fetch JS bundle: {e}") from e

    token_match = re.search(
        r'"(eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)"', js_r.text
    )
    if not token_match:
        raise AMApiError("Could not extract bearer token from JS bundle")

    _bearer_token_cache = token_match.group(1)
    return _bearer_token_cache


def fetch_public_playlist_tracks(
    playlist_url: str,
    bearer_token: str,
    storefront: str = "us",
) -> list[dict]:
    """Return all tracks from a public playlist using only the bearer token.

    Uses amp-api.music.apple.com which accepts bearer-only auth for public playlists.
    Raises AMApiError on invalid URL, network failure, or non-200 response.
    """
    match = re.search(r"/(pl\.[A-Za-z0-9\-]+)", playlist_url)
    if not match:
        raise AMApiError(f"Could not extract playlist ID from URL: {playlist_url}")
    playlist_id = match.group(1)

    if not storefront or storefront == "enter your account storefront":
        storefront = "us"

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Origin": "https://music.apple.com",
    }

    tracks: list[dict] = []
    url: str | None = (
        f"https://amp-api.music.apple.com/v1/catalog/{storefront}"
        f"/playlists/{playlist_id}/tracks?limit=100"
    )

    while url:
        try:
            r = requests.get(url, headers=headers, timeout=15)
        except requests.RequestException as e:
            raise AMApiError(f"Request failed: {e}") from e

        if r.status_code != 200:
            raise AMApiError(
                f"Apple Music API returned {r.status_code} for {url}"
            )

        data = r.json()
        for item in data.get("data", []):
            attrs = item.get("attributes", {})
            art = attrs.get("artwork", {})
            tracks.append({
                "id": item["id"],
                "title": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
                "artwork_url": art.get("url") or None,
            })

        next_path = data.get("next")
        if next_path:
            url = (
                next_path
                if next_path.startswith("http")
                else f"https://amp-api.music.apple.com{next_path}"
            )
        else:
            url = None

    return tracks


def fetch_playlist_tracks(
    playlist_url: str,
    media_user_token: str,
    bearer_token: str,
    storefront: str = "us",
) -> list[dict]:
    """Return all tracks from a playlist as dicts with 'id', 'title', 'artist'.

    Paginates automatically. Raises AMApiError on invalid URL, network failure,
    or non-200 response.
    """
    match = re.search(r"/(pl\.[A-Za-z0-9\-]+)", playlist_url)
    if not match:
        raise AMApiError(f"Could not extract playlist ID from URL: {playlist_url}")
    playlist_id = match.group(1)

    if not storefront or storefront == "enter your account storefront":
        storefront = "us"

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Music-User-Token": media_user_token,
    }

    tracks: list[dict] = []
    url: str | None = (
        f"https://api.music.apple.com/v1/catalog/{storefront}"
        f"/playlists/{playlist_id}/tracks"
    )

    while url:
        try:
            r = requests.get(url, headers=headers, timeout=15)
        except requests.RequestException as e:
            raise AMApiError(f"Request failed: {e}") from e

        if r.status_code != 200:
            if r.status_code == 401:
                global _bearer_token_cache
                _bearer_token_cache = None
            raise AMApiError(
                f"Apple Music API returned {r.status_code} for {url}"
            )

        data = r.json()
        for item in data.get("data", []):
            attrs = item.get("attributes", {})
            tracks.append({
                "id": item["id"],
                "title": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
            })

        next_path = data.get("next")
        if next_path:
            url = (
                next_path
                if next_path.startswith("http")
                else f"https://api.music.apple.com{next_path}"
            )
        else:
            url = None

    return tracks


def _parse_ttml_time(time_str: str) -> Optional[str]:
    """Convert a TTML timestamp (e.g. 00:01:23.456, 01:23.45, 83.45s) into standard LRC format [mm:ss.xx]."""
    if not time_str:
        return None
    time_str = time_str.strip()
    if time_str.endswith("ms"):
        try:
            total_sec = float(time_str[:-2]) / 1000.0
            mins = int(total_sec // 60)
            secs = total_sec % 60
            return f"[{mins:02d}:{secs:05.2f}]"
        except ValueError:
            return None
    if time_str.endswith("s"):
        time_str = time_str[:-1]

    if ":" not in time_str:
        try:
            total_sec = float(time_str)
            mins = int(total_sec // 60)
            secs = total_sec % 60
            return f"[{mins:02d}:{secs:05.2f}]"
        except ValueError:
            return None

    parts = time_str.split(":")
    if len(parts) == 2:
        try:
            mins = int(parts[0])
            secs = float(parts[1])
            return f"[{mins:02d}:{secs:05.2f}]"
        except ValueError:
            return None
    elif len(parts) == 3:
        try:
            hours = int(parts[0])
            mins = int(parts[1]) + hours * 60
            secs = float(parts[2])
            return f"[{mins:02d}:{secs:05.2f}]"
        except ValueError:
            return None
    return None


def ttml_to_lrc(ttml_text: str) -> str:
    """Convert Apple Music TTML lyric XML string into standard synchronized LRC format."""
    if not ttml_text or not ttml_text.strip():
        return ""

    try:
        root = ET.fromstring(ttml_text)
    except ET.ParseError:
        return ttml_text.strip()

    lrc_lines = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag.lower() == "p":
            begin_attr = elem.attrib.get("begin") or elem.attrib.get("{http://www.w3.org/ns/ttml}begin")
            # Extract and normalize text from p and child spans
            raw_text = "".join(elem.itertext())
            line_text = re.sub(r"\s+", " ", raw_text).strip()
            if not line_text and not begin_attr:
                continue

            lrc_ts = _parse_ttml_time(begin_attr) if begin_attr else ""
            if lrc_ts:
                lrc_lines.append(f"{lrc_ts} {line_text}".strip())
            elif line_text:
                lrc_lines.append(line_text)

    return "\n".join(lrc_lines)


def fetch_lyrics(
    track_id: str,
    bearer_token: str,
    storefront: str = "us",
) -> Optional[str]:
    """Fetch synchronized lyrics for a song by track ID from Apple Music AMP API.

    Returns the lyrics converted to synchronized .lrc format, or None if unavailable.
    """
    if not storefront or storefront == "enter your account storefront":
        storefront = "us"

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Origin": "https://music.apple.com",
    }

    url = f"https://amp-api.music.apple.com/v1/catalog/{storefront}/songs/{track_id}/lyrics"
    try:
        r = requests.get(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        raise AMApiError(f"Request failed: {e}") from e

    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise AMApiError(f"Apple Music API returned {r.status_code} for lyrics {track_id}")

    try:
        data = r.json()
    except Exception as e:
        raise AMApiError(f"Failed to parse lyrics response JSON: {e}") from e

    for item in data.get("data", []):
        attrs = item.get("attributes", {})
        ttml = attrs.get("ttml")
        if ttml:
            lrc = ttml_to_lrc(ttml)
            if lrc:
                return lrc
        for key in ("lrc", "plainText", "lyrics"):
            val = attrs.get(key)
            if val and isinstance(val, str) and val.strip():
                return val.strip()

    return None


def search_apple_music_tracks(
    query: str,
    bearer_token: str,
    storefront: str = "us",
    limit: int = 10,
) -> list[dict]:
    """Search Apple Music catalog for songs matching query."""
    if not query.strip():
        return []
    if not storefront or storefront == "enter your account storefront":
        storefront = "us"

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Origin": "https://music.apple.com",
    }
    url = f"https://amp-api.music.apple.com/v1/catalog/{storefront}/search?term={requests.utils.quote(query)}&types=songs&limit={limit}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        songs = data.get("results", {}).get("songs", {}).get("data", [])
        results = []
        for s in songs:
            attrs = s.get("attributes", {})
            art = attrs.get("artwork", {})
            results.append({
                "id": s.get("id", ""),
                "title": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
                "album": attrs.get("albumName", ""),
                "url": attrs.get("url", ""),
                "artwork_url": art.get("url"),
                "isrc": attrs.get("isrc", ""),
            })
        return results
    except Exception:
        return []
