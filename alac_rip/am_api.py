import re
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
