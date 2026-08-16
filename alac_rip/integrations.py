import logging
import urllib.parse
from typing import Any, Optional
import requests

logger = logging.getLogger(__name__)


def test_jellyfin_connection(server_url: str, api_key: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Test Jellyfin server connectivity and authentication."""
    if not server_url:
        return False, "Jellyfin server URL is empty"
    if not api_key:
        return False, "Jellyfin API key is empty"

    url = server_url.rstrip("/") + "/System/Info"
    headers = {
        "X-Emby-Token": api_key,
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            server_name = data.get("ServerName", "Jellyfin")
            version = data.get("Version", "")
            return True, f"Connected to {server_name} ({version})"
        elif resp.status_code in (401, 403):
            return False, f"Authentication failed (HTTP {resp.status_code}) - invalid API key"
        else:
            return False, f"Server returned HTTP {resp.status_code}"
    except Exception as e:
        return False, f"Connection failed: {e}"


def trigger_jellyfin_refresh(server_url: str, api_key: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Trigger a full library scan on Jellyfin via POST /Library/Refresh."""
    if not server_url or not api_key:
        return False, "Jellyfin not configured"

    url = server_url.rstrip("/") + "/Library/Refresh"
    headers = {
        "X-Emby-Token": api_key,
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, json={}, timeout=timeout)
        if resp.status_code in (200, 204):
            return True, "Library refresh triggered successfully"
        return False, f"Library refresh failed (HTTP {resp.status_code})"
    except Exception as e:
        logger.error(f"Failed to trigger Jellyfin refresh: {e}")
        return False, f"Error contacting Jellyfin: {e}"


def test_navidrome_connection(server_url: str, user: str, token: str, salt: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Test Navidrome/Subsonic server connectivity and authentication via ping.view."""
    if not server_url:
        return False, "Navidrome server URL is empty"
    if not user or not token or not salt:
        return False, "Navidrome user, token, or salt is missing"

    url = server_url.rstrip("/") + "/rest/ping.view"
    params = {
        "u": user,
        "t": token,
        "s": salt,
        "v": "1.16.1",
        "c": "PiesALACRip",
        "f": "json",
    }
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            sub = data.get("subsonic-response", {})
            if sub.get("status") == "ok":
                version = sub.get("version", "")
                return True, f"Connected to Subsonic/Navidrome (API v{version})"
            error_info = sub.get("error", {})
            err_msg = error_info.get("message", f"Code {error_info.get('code')}")
            return False, f"Subsonic error: {err_msg}"
        return False, f"Server returned HTTP {resp.status_code}"
    except Exception as e:
        return False, f"Connection failed: {e}"


def trigger_navidrome_refresh(server_url: str, user: str, token: str, salt: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Trigger a scan on Navidrome/Subsonic via GET /rest/startScan.view."""
    if not server_url or not user or not token or not salt:
        return False, "Navidrome not configured"

    url = server_url.rstrip("/") + "/rest/startScan.view"
    params = {
        "u": user,
        "t": token,
        "s": salt,
        "v": "1.16.1",
        "c": "PiesALACRip",
        "f": "json",
    }
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            sub = data.get("subsonic-response", {})
            if sub.get("status") == "ok":
                return True, "Navidrome scan initiated successfully"
            error_info = sub.get("error", {})
            return False, f"Scan failed: {error_info.get('message', 'Unknown error')}"
        return False, f"Server returned HTTP {resp.status_code}"
    except Exception as e:
        logger.error(f"Failed to trigger Navidrome scan: {e}")
        return False, f"Error contacting Navidrome: {e}"


def dispatch_media_webhooks(config_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Trigger enabled integrations according to config.
    Returns list of result objects.
    """
    results = []
    integrations = config_dict.get("integrations", {})
    if not isinstance(integrations, dict):
        return results

    jf = integrations.get("jellyfin", {})
    if isinstance(jf, dict) and jf.get("enabled") and jf.get("auto_refresh"):
        ok, msg = trigger_jellyfin_refresh(jf.get("server_url", ""), jf.get("api_key", ""))
        results.append({"service": "jellyfin", "success": ok, "message": msg})

    navi = integrations.get("navidrome", {})
    if isinstance(navi, dict) and navi.get("enabled") and navi.get("auto_refresh"):
        ok, msg = trigger_navidrome_refresh(
            navi.get("server_url", ""),
            navi.get("user", ""),
            navi.get("token", ""),
            navi.get("salt", ""),
        )
        results.append({"service": "navidrome", "success": ok, "message": msg})

    return results
