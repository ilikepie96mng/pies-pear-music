import requests

LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"
_USER_AGENT = "PiesPearMusic/0.1.0 (https://github.com/ilikepie96mng/pies-alac-rip-tool)"


class LastFmError(Exception):
    pass


def _get(params: dict) -> dict:
    try:
        headers = {"User-Agent": _USER_AGENT}
        resp = requests.get(LASTFM_BASE, params={**params, "format": "json"}, headers=headers, timeout=10)

    except requests.RequestException as e:
        raise LastFmError(f"Network error: {e}") from e
    if not resp.ok:
        raise LastFmError(f"Last.fm returned {resp.status_code}")
    data = resp.json()
    if "error" in data:
        if data["error"] == 6:
            return {}
        raise LastFmError(f"Last.fm error {data['error']}: {data.get('message', '')}")
    return data


def get_similar_artists(artist: str, api_key: str, limit: int = 10) -> list[dict]:
    """Returns list of {name, match, url}. Returns [] if artist not found."""
    data = _get({"method": "artist.getSimilar", "artist": artist, "api_key": api_key, "limit": limit})
    artists = data.get("similarartists", {}).get("artist", [])
    return [{"name": a["name"], "match": float(a["match"]), "url": a["url"]} for a in artists]


def get_tag_top_artists(tag: str, api_key: str, limit: int = 10) -> list[dict]:
    """Returns popular artists for a Last.fm tag: [{name, url}]."""
    data = _get({"method": "tag.getTopArtists", "tag": tag, "api_key": api_key, "limit": limit})
    artists = data.get("topartists", {}).get("artist", [])
    return [{"name": a["name"], "url": a["url"]} for a in artists]


def get_artist_top_tracks(artist: str, api_key: str, limit: int = 5) -> list[dict]:
    """Returns top tracks for artist: [{name, url, artist}]. Returns [] if not found."""
    data = _get({"method": "artist.getTopTracks", "artist": artist, "api_key": api_key, "limit": limit})
    tracks = data.get("toptracks", {}).get("track", [])
    return [
        {"name": t["name"], "url": t["url"], "artist": t.get("artist", {}).get("name", artist)}
        for t in tracks
    ]


def get_artist_top_albums(artist: str, api_key: str, limit: int = 3) -> list[dict]:
    """Returns top albums for artist: [{name, url, artist, image_url}]. Returns [] if not found."""
    data = _get({"method": "artist.getTopAlbums", "artist": artist, "api_key": api_key, "limit": limit})
    albums = data.get("topalbums", {}).get("album", [])
    result = []
    for a in albums:
        images = a.get("image", [])
        image_url = next((img["#text"] for img in reversed(images) if img.get("#text")), None)
        result.append({
            "name": a["name"],
            "url": a["url"],
            "artist": a.get("artist", {}).get("name", artist),
            "image_url": image_url,
        })
    return result
