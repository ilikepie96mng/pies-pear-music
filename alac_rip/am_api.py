import re
import requests

_bearer_token_cache: str | None = None


class AMApiError(Exception):
    pass


def fetch_bearer_token() -> str:
    global _bearer_token_cache
    if _bearer_token_cache:
        return _bearer_token_cache

    try:
        r = requests.get("https://music.apple.com", timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        raise AMApiError(f"Could not fetch music.apple.com: {e}") from e

    match = re.search(
        r'<script[^>]+src="(https://music\.apple\.com/assets/index[^"]+\.js)"', r.text
    )
    if not match:
        raise AMApiError("Could not find Apple Music JS bundle in page HTML")

    js_url = match.group(1)
    try:
        js_r = requests.get(js_url, timeout=15)
        js_r.raise_for_status()
    except requests.RequestException as e:
        raise AMApiError(f"Could not fetch JS bundle: {e}") from e

    token_match = re.search(
        r'"authorization"\s*:\s*"Bearer\s+([A-Za-z0-9\-_.]+)"', js_r.text
    )
    if not token_match:
        raise AMApiError("Could not extract bearer token from JS bundle")

    _bearer_token_cache = token_match.group(1)
    return _bearer_token_cache


def fetch_playlist_track_ids(
    playlist_url: str,
    media_user_token: str,
    bearer_token: str,
    storefront: str = "us",
) -> list[str]:
    match = re.search(r"/(pl\.[A-Za-z0-9]+)", playlist_url)
    if not match:
        raise AMApiError(f"Could not extract playlist ID from URL: {playlist_url}")
    playlist_id = match.group(1)

    if not storefront or storefront == "enter your account storefront":
        storefront = "us"

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Music-User-Token": media_user_token,
    }

    track_ids: list[str] = []
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
            raise AMApiError(
                f"Apple Music API returned {r.status_code} for {url}"
            )

        data = r.json()
        for item in data.get("data", []):
            track_ids.append(item["id"])

        next_path = data.get("next")
        if next_path:
            url = (
                next_path
                if next_path.startswith("http")
                else f"https://api.music.apple.com{next_path}"
            )
        else:
            url = None

    return track_ids
