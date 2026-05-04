import requests

LASTFM_BASE = "http://ws.audioscrobbler.com/2.0/"


class LastFmError(Exception):
    pass


def get_similar_artists(artist: str, api_key: str, limit: int = 10) -> list[dict]:
    """Fetch artists similar to `artist` from Last.fm.

    Returns list of {name, match, url}. Returns [] if artist not found (error 6).
    Raises LastFmError on network failure or other API errors.
    """
    try:
        resp = requests.get(
            LASTFM_BASE,
            params={
                "method": "artist.getSimilar",
                "artist": artist,
                "api_key": api_key,
                "format": "json",
                "limit": limit,
            },
            timeout=10,
        )
    except requests.RequestException as e:
        raise LastFmError(f"Network error: {e}") from e

    if not resp.ok:
        raise LastFmError(f"Last.fm returned {resp.status_code}")

    data = resp.json()
    if "error" in data:
        if data["error"] == 6:
            return []
        raise LastFmError(f"Last.fm error {data['error']}: {data.get('message', '')}")

    artists = data.get("similarartists", {}).get("artist", [])
    return [
        {"name": a["name"], "match": float(a["match"]), "url": a["url"]}
        for a in artists
    ]
