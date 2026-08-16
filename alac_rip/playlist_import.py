import csv
import io
import json
import logging
import re
from typing import Optional
import requests
from alac_rip.am_api import AMApiError, search_apple_music_tracks

logger = logging.getLogger(__name__)


def parse_spotify_playlist_url(url: str) -> Optional[str]:
    """Extract Spotify playlist ID from URL or URI."""
    m = re.search(r"(?:spotify:playlist:|playlist/)([a-zA-Z0-9]+)", url)
    return m.group(1) if m else None


def parse_tidal_playlist_url(url: str) -> Optional[str]:
    """Extract Tidal playlist UUID from URL."""
    m = re.search(r"(?:tidal\.com/(?:browse/)?playlist/|playlist/)([0-9a-fA-F-]+)", url)
    return m.group(1) if m else None


def parse_qobuz_playlist_url(url: str) -> Optional[str]:
    """Extract Qobuz playlist ID from URL."""
    m = re.search(r"(?:open\.qobuz\.com/playlist/|playlist/)([0-9a-zA-Z]+)", url)
    return m.group(1) if m else None


def parse_csv_tracks(csv_text: str) -> list[dict]:
    """Parse CSV with track metadata (e.g. from Soundiiz, TuneMyMusic, or custom export)."""
    tracks = []
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    for row in reader:
        # Standardize header names
        keys = {k.lower().strip(): v for k, v in row.items() if k}
        title = keys.get("title") or keys.get("track name") or keys.get("name") or ""
        artist = keys.get("artist") or keys.get("artist name") or ""
        album = keys.get("album") or keys.get("album name") or ""
        isrc = keys.get("isrc") or ""
        if title and artist:
            tracks.append({
                "title": title.strip(),
                "artist": artist.strip(),
                "album": album.strip(),
                "isrc": isrc.strip(),
            })
    return tracks


def parse_m3u_tracks(m3u_text: str) -> list[dict]:
    """Parse #EXTINF lines from M3U / M3U8 content."""
    tracks = []
    lines = m3u_text.strip().splitlines()
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF:"):
            # Format: #EXTINF:duration,Artist - Title
            parts = line.split(",", 1)
            if len(parts) > 1:
                info = parts[1].strip()
                if " - " in info:
                    artist, title = info.split(" - ", 1)
                    tracks.append({"artist": artist.strip(), "title": title.strip(), "album": "", "isrc": ""})
                else:
                    tracks.append({"artist": "", "title": info, "album": "", "isrc": ""})
    return tracks


def fetch_spotify_public_playlist(playlist_id: str) -> list[dict]:
    """Scrape tracks from public Spotify playlist embed / open page."""
    url = f"https://open.spotify.com/embed/playlist/{playlist_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', resp.text)
        if not m:
            return []
        data = json.loads(m.group(1))
        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        track_list = entity.get("trackList", [])
        tracks = []
        for t in track_list:
            title = t.get("title", "")
            subtitle = t.get("subtitle", "")
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
) -> list[dict]:
    """
    Match imported tracks against Apple Music catalog.
    Returns list of track matching results.
    """
    results = []
    for item in raw_tracks:
        title = item.get("title", "")
        artist = item.get("artist", "")
        isrc = item.get("isrc", "")
        album = item.get("album", "")

        query = f"{artist} {title}".strip() if artist else title
        matched_am_track = None
        match_score = 0.0

        if query:
            try:
                candidates = search_apple_music_tracks(query, bearer_token, storefront=storefront, limit=5)
                if candidates:
                    # Pick top candidate
                    top = candidates[0]
                    matched_am_track = top
                    # Rough match scoring
                    match_score = 1.0 if (artist.lower() in top.get("artist", "").lower() or not artist) else 0.8
            except Exception as e:
                logger.debug(f"Search failed for {query}: {e}")

        results.append({
            "original_title": title,
            "original_artist": artist,
            "original_album": album,
            "original_isrc": isrc,
            "matched": matched_am_track is not None,
            "match_score": match_score,
            "am_track": matched_am_track,
        })

    return results
