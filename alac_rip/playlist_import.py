import csv
import io
import json
import logging
import re
from typing import Optional
import requests
from alac_rip.am_api import AMApiError, search_apple_music_tracks

logger = logging.getLogger(__name__)

_MAX_IMPORT_BYTES = 1_000_000
_MAX_IMPORT_TRACKS = 500


def _sanitize_cell_text(val: Optional[str]) -> str:
    """Strip leading control/formula prefix characters to prevent CSV formula injection risks."""
    if not val or not isinstance(val, str):
        return ""
    text = val.strip()[:250]
    # Neutralize spreadsheet formula prefixes if present
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        text = text.lstrip("=+-@\t\r").strip()
    return text


def parse_spotify_playlist_url(url: str) -> Optional[str]:
    """Extract Spotify playlist ID from URL or URI."""
    if not url or len(url) > 500:
        return None
    m = re.search(r"(?:spotify:playlist:|playlist/)([a-zA-Z0-9]{15,40})", url)
    return m.group(1) if m else None


def parse_tidal_playlist_url(url: str) -> Optional[str]:
    """Extract Tidal playlist UUID from URL."""
    if not url or len(url) > 500:
        return None
    m = re.search(r"(?:tidal\.com/(?:browse/)?playlist/|playlist/)([0-9a-fA-F-]{32,40})", url)
    return m.group(1) if m else None


def parse_qobuz_playlist_url(url: str) -> Optional[str]:
    """Extract Qobuz playlist ID from URL."""
    if not url or len(url) > 500:
        return None
    m = re.search(r"(?:open\.qobuz\.com/playlist/|playlist/)([0-9a-zA-Z]{5,40})", url)
    return m.group(1) if m else None


def parse_csv_tracks(csv_text: str) -> list[dict]:
    """Parse CSV with track metadata, bounded to safe sizes."""
    if not csv_text or len(csv_text) > _MAX_IMPORT_BYTES:
        return []

    tracks = []
    try:
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        for i, row in enumerate(reader):
            if i >= _MAX_IMPORT_TRACKS:
                break
            # Standardize header names
            keys = {k.lower().strip(): v for k, v in row.items() if k}
            title = _sanitize_cell_text(keys.get("title") or keys.get("track name") or keys.get("name") or keys.get("track_name"))
            artist = _sanitize_cell_text(keys.get("artist") or keys.get("artist name") or keys.get("artist_name"))
            album = _sanitize_cell_text(keys.get("album") or keys.get("album name") or keys.get("album_name"))
            isrc = _sanitize_cell_text(keys.get("isrc"))
            if title and artist:
                tracks.append({
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "isrc": isrc,
                })
    except Exception as e:
        logger.debug(f"CSV parsing error: {e}")

    return tracks


def parse_m3u_tracks(m3u_text: str) -> list[dict]:
    """Parse #EXTINF lines from M3U / M3U8 content, bounded to safe limits."""
    if not m3u_text or len(m3u_text) > _MAX_IMPORT_BYTES:
        return []

    tracks = []
    lines = m3u_text.strip().splitlines()
    for line in lines:
        if len(tracks) >= _MAX_IMPORT_TRACKS:
            break
        line = line.strip()
        if line.startswith("#EXTINF:"):
            parts = line.split(",", 1)
            if len(parts) > 1:
                info = _sanitize_cell_text(parts[1])
                if " - " in info:
                    artist, title = info.split(" - ", 1)
                    tracks.append({"artist": artist.strip(), "title": title.strip(), "album": "", "isrc": ""})
                else:
                    tracks.append({"artist": "", "title": info, "album": "", "isrc": ""})
    return tracks


def fetch_spotify_public_playlist(playlist_id: str) -> list[dict]:
    """Scrape tracks from public Spotify playlist embed / open page safely."""
    if not playlist_id or not re.fullmatch(r"[a-zA-Z0-9]{15,40}", playlist_id):
        return []

    url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=False)
        if resp.status_code != 200 or len(resp.content) > 5_000_000:
            return []
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', resp.text)
        if not m:
            return []
        data = json.loads(m.group(1))
        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        track_list = entity.get("trackList", [])
        tracks = []
        for t in track_list[:_MAX_IMPORT_TRACKS]:
            title = _sanitize_cell_text(t.get("title", ""))
            subtitle = _sanitize_cell_text(t.get("subtitle", ""))
            if title:
                tracks.append({"title": title, "artist": subtitle, "album": "", "isrc": ""})
        return tracks
    except Exception as e:
        logger.debug(f"Failed to fetch Spotify public playlist: {e}")
        return []


def match_tracks_to_apple_music(
    raw_tracks: list[dict],
    bearer_token: str,
    storefront: str = "us",
    max_matches: int = 50,
) -> list[dict]:
    """
    Search Apple Music for each imported track and match to catalog IDs.
    Bounded to max_matches to prevent API abuse.
    """
    if not bearer_token or not raw_tracks:
        return []

    clamped_tracks = raw_tracks[:max_matches]
    results = []

    for t in clamped_tracks:
        title = t.get("title", "").strip()
        artist = t.get("artist", "").strip()
        album = t.get("album", "").strip()
        isrc = t.get("isrc", "").strip()

        matched_track = None
        match_confidence = "none"

        # Search by ISRC if present
        if isrc:
            try:
                matches = search_apple_music_tracks(f"isrc:{isrc}", bearer_token, storefront=storefront, limit=1)
                if matches:
                    matched_track = matches[0]
                    match_confidence = "isrc"
            except Exception:
                pass

        # Fallback to Artist + Title text search
        if not matched_track and artist and title:
            query = f"{artist} {title}".strip()
            try:
                matches = search_apple_music_tracks(query, bearer_token, storefront=storefront, limit=3)
                if matches:
                    matched_track = matches[0]
                    match_confidence = "fuzzy"
            except Exception:
                pass

        results.append({
            "source_track": t,
            "matched": matched_track is not None,
            "confidence": match_confidence,
            "am_track": matched_track,
        })

    return results
