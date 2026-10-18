import re
import xml.etree.ElementTree as ET
from typing import Optional

import requests

_bearer_token_cache: str | None = None  # not thread-safe; safe for single-threaded use


class AMApiError(Exception):
    pass


def _decode_jwt_payload(jwt_str: str) -> dict:
    import base64
    import json
    try:
        parts = jwt_str.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def fetch_bearer_token(force_refresh: bool = False) -> str:
    """Scrape music.apple.com, extract the valid Bearer JWT from the JS bundle, and return it.

    Result is cached in a module-level variable for the lifetime of the process.
    Raises AMApiError on network failure or if the token cannot be found.
    """
    global _bearer_token_cache
    if _bearer_token_cache and not force_refresh:
        return _bearer_token_cache

    try:
        r = requests.get("https://music.apple.com/us/browse", timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        raise AMApiError(f"Could not fetch music.apple.com: {e}") from e

    js_paths = re.findall(
        r'<script[^>]+src="((?:https://music\.apple\.com)?/assets/[^"]+\.js)"', r.text
    )
    if not js_paths:
        js_paths = re.findall(r'/assets/[^"\'\s]+\.js', r.text)

    if not js_paths:
        raise AMApiError("Could not find Apple Music JS bundle in page HTML")

    candidate_tokens: list[str] = []
    for path in js_paths:
        js_url = path if path.startswith("http") else f"https://music.apple.com{path}"
        try:
            js_r = requests.get(js_url, timeout=15)
            js_r.raise_for_status()
            found = re.findall(
                r'"(eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+)"', js_r.text
            )
            for t in found:
                if t not in candidate_tokens:
                    candidate_tokens.append(t)
        except Exception:
            continue

    if not candidate_tokens:
        raise AMApiError("Could not extract bearer token from JS bundles")

    valid_token = None
    for token in candidate_tokens:
        payload = _decode_jwt_payload(token)
        iss = payload.get("iss", "")
        if iss and iss not in ("AMPWebPlay", "M62YD85FTQ"):
            valid_token = token
            break

    if not valid_token:
        for token in candidate_tokens:
            payload = _decode_jwt_payload(token)
            if payload.get("iss") != "AMPWebPlay":
                valid_token = token
                break

    if not valid_token:
        valid_token = candidate_tokens[0]

    _bearer_token_cache = valid_token
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
        if r.status_code == 200:
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
            if results:
                return results
    except Exception:
        pass

    # Fallback to iTunes search API
    itunes_res = _search_itunes_fallback(query, limit=limit)
    return itunes_res.get("songs", [])


def fetch_album_details(
    album_id_or_url: str,
    bearer_token: str,
    storefront: str = "us",
) -> dict:
    """Fetch album metadata and full tracklist from Apple Music AMP API."""
    if not storefront or storefront == "enter your account storefront":
        storefront = "us"

    # Extract album ID if full URL passed
    album_id = album_id_or_url
    if "music.apple.com" in album_id_or_url or "/album/" in album_id_or_url:
        m = re.search(r"/album/(?:[^/]+/)?(\d+)", album_id_or_url)
        if m:
            album_id = m.group(1)
        else:
            m_end = re.search(r"(\d+)(?:[/?]|$)", album_id_or_url)
            if m_end:
                album_id = m_end.group(1)

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Origin": "https://music.apple.com",
    }

    url = f"https://amp-api.music.apple.com/v1/catalog/{storefront}/albums/{album_id}"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            raise AMApiError(f"Apple Music returned {r.status_code} for album {album_id}")
        data = r.json()
        item = data.get("data", [])[0]
        attrs = item.get("attributes", {})
        art = attrs.get("artwork", {})

        # Fetch tracks relationship
        rel_tracks = item.get("relationships", {}).get("tracks", {}).get("data", [])
        tracks = []
        for t in rel_tracks:
            t_attrs = t.get("attributes", {})
            t_art = t_attrs.get("artwork", {})
            tracks.append({
                "id": t.get("id", ""),
                "title": t_attrs.get("name", ""),
                "artist": t_attrs.get("artistName", ""),
                "album": attrs.get("name", ""),
                "track_number": t_attrs.get("trackNumber", 0),
                "disc_number": t_attrs.get("discNumber", 1),
                "duration_ms": t_attrs.get("durationInMillis", 0),
                "url": t_attrs.get("url", ""),
                "artwork_url": t_art.get("url") or art.get("url"),
                "isrc": t_attrs.get("isrc", ""),
            })

        return {
            "id": item.get("id", ""),
            "title": attrs.get("name", ""),
            "artist": attrs.get("artistName", ""),
            "release_date": attrs.get("releaseDate", ""),
            "record_label": attrs.get("recordLabel", ""),
            "genre_names": attrs.get("genreNames", []),
            "track_count": attrs.get("trackCount", len(tracks)),
            "artwork_url": art.get("url"),
            "url": attrs.get("url", ""),
            "tracks": tracks,
        }
    except AMApiError:
        raise
    except Exception as e:
        raise AMApiError(f"Failed to fetch album {album_id}: {e}") from e


def fetch_artist_discography(
    artist_id_or_url: str,
    bearer_token: str,
    storefront: str = "us",
) -> dict:
    """Fetch artist details and paginated albums/singles from Apple Music AMP API."""
    if not storefront or storefront == "enter your account storefront":
        storefront = "us"

    artist_id = artist_id_or_url
    if "music.apple.com" in artist_id_or_url or "/artist/" in artist_id_or_url:
        m = re.search(r"/artist/(?:[^/]+/)?(\d+)", artist_id_or_url)
        if m:
            artist_id = m.group(1)
        else:
            m_end = re.search(r"(\d+)(?:[/?]|$)", artist_id_or_url)
            if m_end:
                artist_id = m_end.group(1)

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Origin": "https://music.apple.com",
    }

    # 1. Fetch artist details
    artist_name = "Unknown Artist"
    artist_url = ""
    artist_genres: list[str] = []
    artist_art = None

    try:
        r_art = requests.get(
            f"https://amp-api.music.apple.com/v1/catalog/{storefront}/artists/{artist_id}",
            headers=headers,
            timeout=15,
        )
        if r_art.status_code == 200:
            art_data = r_art.json().get("data", [])[0]
            art_attrs = art_data.get("attributes", {})
            artist_name = art_attrs.get("name", artist_name)
            artist_url = art_attrs.get("url", "")
            artist_genres = art_attrs.get("genreNames", [])
            artist_art = art_attrs.get("artwork", {}).get("url")
    except Exception:
        pass

    # 2. Paginate artist albums
    albums: list[dict] = []
    next_url: Optional[str] = f"https://amp-api.music.apple.com/v1/catalog/{storefront}/artists/{artist_id}/albums?limit=100"

    while next_url:
        try:
            r = requests.get(next_url, headers=headers, timeout=15)
            if r.status_code != 200:
                break
            data = r.json()
            for alb in data.get("data", []):
                attrs = alb.get("attributes", {})
                art = attrs.get("artwork", {})
                albums.append({
                    "id": alb.get("id", ""),
                    "title": attrs.get("name", ""),
                    "artist": attrs.get("artistName", artist_name),
                    "release_date": attrs.get("releaseDate", ""),
                    "track_count": attrs.get("trackCount", 0),
                    "record_label": attrs.get("recordLabel", ""),
                    "is_single": attrs.get("isSingle", False),
                    "is_compilation": attrs.get("isCompilation", False),
                    "is_complete": attrs.get("isComplete", True),
                    "url": attrs.get("url", ""),
                    "artwork_url": art.get("url"),
                })
            next_path = data.get("next")
            if next_path:
                next_url = next_path if next_path.startswith("http") else f"https://amp-api.music.apple.com{next_path}"
            else:
                next_url = None
        except Exception:
            break

    return {
        "id": artist_id,
        "name": artist_name,
        "url": artist_url,
        "genres": artist_genres,
        "artwork_url": artist_art,
        "album_count": len(albums),
        "albums": albums,
    }


def _search_itunes_fallback(query: str, limit: int = 8) -> dict:
    """Fallback search using the public iTunes Search API when AMP API is rate-limited or unavailable."""
    url = f"https://itunes.apple.com/search?term={requests.utils.quote(query)}&media=music&limit={limit * 3}"
    try:
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return {"songs": [], "albums": [], "artists": [], "playlists": []}
        data = r.json().get("results", [])
        songs = []
        albums = []
        artists = []
        seen_artists = set()
        seen_albums = set()

        for item in data:
            wrapper = item.get("wrapperType")
            kind = item.get("kind")
            art_raw = item.get("artworkUrl100") or item.get("artworkUrl60") or ""
            art_template = (
                art_raw.replace("100x100bb.jpg", "{w}x{h}bb.jpg").replace("60x60bb.jpg", "{w}x{h}bb.jpg")
                if art_raw
                else None
            )

            if (kind == "song" or wrapper == "track") and len(songs) < limit:
                songs.append({
                    "id": str(item.get("trackId", "")),
                    "title": item.get("trackName", ""),
                    "artist": item.get("artistName", ""),
                    "album": item.get("collectionName", ""),
                    "url": item.get("trackViewUrl", ""),
                    "artwork_url": art_template,
                })
            if item.get("collectionId") and item.get("collectionName") not in seen_albums and len(albums) < limit:
                seen_albums.add(item.get("collectionName"))
                albums.append({
                    "id": str(item.get("collectionId", "")),
                    "title": item.get("collectionName", ""),
                    "artist": item.get("artistName", ""),
                    "release_date": item.get("releaseDate", ""),
                    "track_count": item.get("trackCount", 0),
                    "url": item.get("collectionViewUrl", ""),
                    "artwork_url": art_template,
                })
            if item.get("artistName") and item.get("artistName") not in seen_artists and len(artists) < limit:
                seen_artists.add(item.get("artistName"))
                artists.append({
                    "id": str(item.get("artistId", "")),
                    "name": item.get("artistName", ""),
                    "genre_names": [item.get("primaryGenreName")] if item.get("primaryGenreName") else [],
                    "url": item.get("artistViewUrl", ""),
                    "artwork_url": art_template,
                })

        return {"songs": songs, "albums": albums, "artists": artists, "playlists": []}
    except Exception:
        return {"songs": [], "albums": [], "artists": [], "playlists": []}


def search_apple_music_catalog(
    query: str,
    bearer_token: str,
    storefront: str = "us",
    types: tuple[str, ...] = ("songs", "albums", "artists", "playlists"),
    limit: int = 8,
) -> dict:
    """Multi-entity catalog search across songs, albums, artists, and playlists."""
    if not query.strip():
        return {"songs": [], "albums": [], "artists": [], "playlists": []}
    if not storefront or storefront == "enter your account storefront":
        storefront = "us"

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Origin": "https://music.apple.com",
    }
    types_param = ",".join(types)
    url = f"https://amp-api.music.apple.com/v1/catalog/{storefront}/search?term={requests.utils.quote(query)}&types={types_param}&limit={limit}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json().get("results", {})

            songs = []
            for s in data.get("songs", {}).get("data", []):
                attrs = s.get("attributes", {})
                art = attrs.get("artwork", {})
                songs.append({
                    "id": s.get("id", ""),
                    "title": attrs.get("name", ""),
                    "artist": attrs.get("artistName", ""),
                    "album": attrs.get("albumName", ""),
                    "url": attrs.get("url", ""),
                    "artwork_url": art.get("url"),
                })

            albums = []
            for a in data.get("albums", {}).get("data", []):
                attrs = a.get("attributes", {})
                art = attrs.get("artwork", {})
                albums.append({
                    "id": a.get("id", ""),
                    "title": attrs.get("name", ""),
                    "artist": attrs.get("artistName", ""),
                    "release_date": attrs.get("releaseDate", ""),
                    "track_count": attrs.get("trackCount", 0),
                    "url": attrs.get("url", ""),
                    "artwork_url": art.get("url"),
                })

            artists = []
            for art in data.get("artists", {}).get("data", []):
                attrs = art.get("attributes", {})
                artwork = attrs.get("artwork", {})
                artists.append({
                    "id": art.get("id", ""),
                    "name": attrs.get("name", ""),
                    "genre_names": attrs.get("genreNames", []),
                    "url": attrs.get("url", ""),
                    "artwork_url": artwork.get("url"),
                })

            playlists = []
            for p in data.get("playlists", {}).get("data", []):
                attrs = p.get("attributes", {})
                art = attrs.get("artwork", {})
                desc_obj = attrs.get("description", {})
                desc_str = ""
                if isinstance(desc_obj, dict):
                    desc_str = desc_obj.get("standard") or desc_obj.get("short") or ""
                elif isinstance(desc_obj, str):
                    desc_str = desc_obj
                playlists.append({
                    "id": p.get("id", ""),
                    "title": attrs.get("name", ""),
                    "curator_name": attrs.get("curatorName", "Apple Music"),
                    "description": desc_str,
                    "track_count": attrs.get("trackCount", 0),
                    "url": attrs.get("url", ""),
                    "artwork_url": art.get("url"),
                    "last_modified": attrs.get("lastModifiedDate", ""),
                    "provider": "apple",
                })

            if songs or albums or artists or playlists:
                return {
                    "songs": songs,
                    "albums": albums,
                    "artists": artists,
                    "playlists": playlists,
                }
    except Exception:
        pass

    # Seamless fallback to public iTunes API
    return _search_itunes_fallback(query, limit=limit)


def fetch_playlist_details(
    playlist_id_or_url: str,
    bearer_token: str,
    storefront: str = "us",
) -> dict:
    """Fetch playlist metadata and paginated tracklist from Apple Music AMP API."""
    if not storefront or storefront == "enter your account storefront":
        storefront = "us"

    playlist_id = playlist_id_or_url
    if "music.apple.com" in playlist_id_or_url or "/playlist/" in playlist_id_or_url:
        m = re.search(r"/playlist/(?:[^/]+/)?(pl\.[^\s/?#]+)", playlist_id_or_url)
        if m:
            playlist_id = m.group(1)
        else:
            m_end = re.search(r"(pl\.[^\s/?#]+)(?:[/?]|$)", playlist_id_or_url)
            if m_end:
                playlist_id = m_end.group(1)

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Origin": "https://music.apple.com",
    }

    url = f"https://amp-api.music.apple.com/v1/catalog/{storefront}/playlists/{playlist_id}"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            raise AMApiError(f"Apple Music returned {r.status_code} for playlist {playlist_id}")
        data = r.json()
        pl_data = data.get("data", [])[0]
        attrs = pl_data.get("attributes", {})
        art = attrs.get("artwork", {})
        desc_obj = attrs.get("description", {})
        desc_str = ""
        if isinstance(desc_obj, dict):
            desc_str = desc_obj.get("standard") or desc_obj.get("short") or ""
        elif isinstance(desc_obj, str):
            desc_str = desc_obj

        tracks: list[dict] = []
        relationships = pl_data.get("relationships", {})
        rel_tracks = relationships.get("tracks", {})
        for idx, t in enumerate(rel_tracks.get("data", []), start=1):
            t_attrs = t.get("attributes", {})
            t_art = t_attrs.get("artwork", {})
            tracks.append({
                "id": t.get("id", ""),
                "title": t_attrs.get("name", ""),
                "artist": t_attrs.get("artistName", ""),
                "album": t_attrs.get("albumName", ""),
                "track_number": idx,
                "duration_ms": t_attrs.get("durationInMillis", 0),
                "url": t_attrs.get("url", ""),
                "artwork_url": t_art.get("url"),
                "isrc": t_attrs.get("isrc"),
                "provider": "apple",
            })

        next_path = rel_tracks.get("next")
        while next_path and len(tracks) < 300:
            next_url = next_path if next_path.startswith("http") else f"https://amp-api.music.apple.com{next_path}"
            try:
                nr = requests.get(next_url, headers=headers, timeout=15)
                if nr.status_code != 200:
                    break
                ndata = nr.json()
                for t in ndata.get("data", []):
                    t_attrs = t.get("attributes", {})
                    t_art = t_attrs.get("artwork", {})
                    tracks.append({
                        "id": t.get("id", ""),
                        "title": t_attrs.get("name", ""),
                        "artist": t_attrs.get("artistName", ""),
                        "album": t_attrs.get("albumName", ""),
                        "track_number": len(tracks) + 1,
                        "duration_ms": t_attrs.get("durationInMillis", 0),
                        "url": t_attrs.get("url", ""),
                        "artwork_url": t_art.get("url"),
                        "isrc": t_attrs.get("isrc"),
                        "provider": "apple",
                    })
                next_path = ndata.get("next")
            except Exception:
                break

        return {
            "id": playlist_id,
            "title": attrs.get("name", ""),
            "curator_name": attrs.get("curatorName", "Apple Music"),
            "description": desc_str,
            "track_count": attrs.get("trackCount", len(tracks)),
            "artwork_url": art.get("url"),
            "url": attrs.get("url", ""),
            "last_modified": attrs.get("lastModifiedDate", ""),
            "tracks": tracks,
            "provider": "apple",
        }
    except AMApiError:
        raise
    except Exception as e:
        raise AMApiError(f"Failed to fetch playlist {playlist_id}: {e}") from e


def fetch_genre_charts(
    genre_id: str,
    bearer_token: str,
    storefront: str = "us",
) -> dict:
    """Fetch top playlists, albums, and songs for a specific genre."""
    if not storefront or storefront == "enter your account storefront":
        storefront = "us"

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Origin": "https://music.apple.com",
    }
    url = f"https://amp-api.music.apple.com/v1/catalog/{storefront}/charts?types=playlists,albums,songs&genre={genre_id}&limit=20"
    try:
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            return {"genre_id": genre_id, "playlists": [], "albums": [], "songs": []}

        results = r.json().get("results", {})

        playlists = []
        for chart in results.get("playlists", []):
            for p in chart.get("data", []):
                attrs = p.get("attributes", {})
                art = attrs.get("artwork", {})
                desc_obj = attrs.get("description", {})
                desc_str = ""
                if isinstance(desc_obj, dict):
                    desc_str = desc_obj.get("standard") or desc_obj.get("short") or ""
                elif isinstance(desc_obj, str):
                    desc_str = desc_obj
                playlists.append({
                    "id": p.get("id", ""),
                    "title": attrs.get("name", ""),
                    "curator_name": attrs.get("curatorName", "Apple Music"),
                    "description": desc_str,
                    "artwork_url": art.get("url"),
                    "track_count": attrs.get("trackCount", 0),
                    "url": attrs.get("url", ""),
                    "provider": "apple",
                })

        albums = []
        for chart in results.get("albums", []):
            for a in chart.get("data", []):
                attrs = a.get("attributes", {})
                art = attrs.get("artwork", {})
                albums.append({
                    "id": a.get("id", ""),
                    "title": attrs.get("name", ""),
                    "artist": attrs.get("artistName", ""),
                    "release_date": attrs.get("releaseDate", ""),
                    "track_count": attrs.get("trackCount", 0),
                    "artwork_url": art.get("url"),
                    "url": attrs.get("url", ""),
                    "provider": "apple",
                })

        songs = []
        for chart in results.get("songs", []):
            for s in chart.get("data", []):
                attrs = s.get("attributes", {})
                art = attrs.get("artwork", {})
                songs.append({
                    "id": s.get("id", ""),
                    "title": attrs.get("name", ""),
                    "artist": attrs.get("artistName", ""),
                    "album": attrs.get("albumName", ""),
                    "artwork_url": art.get("url"),
                    "url": attrs.get("url", ""),
                    "provider": "apple",
                })

        return {
            "genre_id": genre_id,
            "playlists": playlists,
            "albums": albums,
            "songs": songs,
        }
    except Exception:
        return {"genre_id": genre_id, "playlists": [], "albums": [], "songs": []}


CATALOG_GENRES: list[dict[str, str]] = [
    {"id": "7", "name": "Electronic", "icon": "⚡", "slug": "electronic"},
    {"id": "18", "name": "Hip-Hop / Rap", "icon": "🎤", "slug": "hip-hop"},
    {"id": "21", "name": "Rock", "icon": "🎸", "slug": "rock"},
    {"id": "20", "name": "Alternative", "icon": "📻", "slug": "alternative"},
    {"id": "14", "name": "R&B / Soul", "icon": "💜", "slug": "rnb"},
    {"id": "11", "name": "Jazz", "icon": "🎷", "slug": "jazz"},
    {"id": "6", "name": "Country", "icon": "🤠", "slug": "country"},
    {"id": "5", "name": "Classical", "icon": "🎻", "slug": "classical"},
    {"id": "17", "name": "Dance", "icon": "🪩", "slug": "dance"},
    {"id": "10", "name": "Singer/Songwriter", "icon": "☕", "slug": "acoustic"},
    {"id": "12", "name": "Latin", "icon": "🌴", "slug": "latin"},
    {"id": "16", "name": "Soundtrack", "icon": "🎬", "slug": "soundtrack"},
    {"id": "24", "name": "Reggae", "icon": "☀️", "slug": "reggae"},
    {"id": "2", "name": "Blues", "icon": "🎺", "slug": "blues"},
    {"id": "15", "name": "Soul / Funk", "icon": "🕺", "slug": "soul"},
    {"id": "22", "name": "Metal", "icon": "🤘", "slug": "metal"},
    {"id": "28", "name": "J-Pop", "icon": "🌸", "slug": "j-pop"},
    {"id": "51", "name": "K-Pop", "icon": "✨", "slug": "k-pop"},
    {"id": "19", "name": "World", "icon": "🌍", "slug": "world"},
    {"id": "100001", "name": "Ambient & Synthwave", "icon": "🌌", "slug": "ambient"},
]


def get_catalog_genres() -> list[dict[str, str]]:
    return list(CATALOG_GENRES)
