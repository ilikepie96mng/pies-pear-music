import ipaddress
import logging
import socket
import urllib.parse
from typing import Any, Optional
import requests

logger = logging.getLogger(__name__)


def validate_integration_url(server_url: str) -> str:
    """
    Validate server URL scheme, host, and target IP to prevent SSRF against
    cloud metadata endpoints and link-local addresses.
    """
    if not server_url or not isinstance(server_url, str):
        raise ValueError("Server URL cannot be empty")

    parsed = urllib.parse.urlparse(server_url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Server URL must use http or https scheme")
    if parsed.username or parsed.password:
        raise ValueError("Server URL must not contain embedded credentials")
    if not parsed.hostname:
        raise ValueError("Server URL must include a valid hostname")

    # Validate port if specified
    if parsed.port is not None and not (1 <= parsed.port <= 65535):
        raise ValueError("Invalid port number")

    # Resolve hostname and verify against dangerous IP ranges
    hostname = parsed.hostname.lower()
    try:
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)

            # Block link-local (e.g. 169.254.169.254 cloud metadata), multicast, unspecified, and broadcast
            if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
                raise ValueError(f"Target address {ip_str} is in a forbidden network range")
            if ip.is_reserved and not ip.is_loopback:
                raise ValueError(f"Target address {ip_str} is in a forbidden network range")
            if isinstance(ip, ipaddress.IPv4Address) and ip_str == "255.255.255.255":
                raise ValueError("Broadcast address is forbidden")
    except socket.gaierror:
        # If DNS resolution fails here, let the request timeout safely
        pass

    return server_url.rstrip("/")


def test_jellyfin_connection(server_url: str, api_key: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Test Jellyfin server connectivity and authentication safely."""
    try:
        clean_url = validate_integration_url(server_url)
    except ValueError as ve:
        return False, str(ve)

    if not api_key:
        return False, "Jellyfin API key is empty"

    url = clean_url + "/System/Info"
    headers = {
        "X-Emby-Token": api_key,
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
        if resp.status_code == 200:
            data = resp.json()
            server_name = data.get("ServerName", "Jellyfin")
            version = data.get("Version", "")
            return True, f"Connected to {server_name} ({version})"
        elif resp.status_code in (401, 403):
            return False, "Authentication failed - invalid API key"
        elif 300 <= resp.status_code < 400:
            return False, f"Server returned redirect ({resp.status_code}); redirects are disabled for security"
        else:
            return False, f"Server returned HTTP {resp.status_code}"
    except requests.Timeout:
        return False, "Connection timed out"
    except Exception as e:
        logger.debug(f"Jellyfin connection check failed: {type(e).__name__}")
        return False, "Failed to connect to Jellyfin server"


def trigger_jellyfin_refresh(server_url: str, api_key: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Trigger a full library scan on Jellyfin via POST /Library/Refresh."""
    try:
        clean_url = validate_integration_url(server_url)
    except ValueError as ve:
        return False, str(ve)

    if not api_key:
        return False, "Jellyfin not configured"

    url = clean_url + "/Library/Refresh"
    headers = {
        "X-Emby-Token": api_key,
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, json={}, timeout=timeout, allow_redirects=False)
        if resp.status_code in (200, 204):
            return True, "Library refresh triggered successfully"
        return False, f"Library refresh failed (HTTP {resp.status_code})"
    except Exception as e:
        logger.error(f"Failed to trigger Jellyfin refresh: {type(e).__name__}")
        return False, "Error contacting Jellyfin server"


def test_navidrome_connection(server_url: str, user: str, token: str, salt: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Test Navidrome/Subsonic server connectivity without disclosing query credentials in errors."""
    try:
        clean_url = validate_integration_url(server_url)
    except ValueError as ve:
        return False, str(ve)

    if not user or not token or not salt:
        return False, "Navidrome user, token, or salt is missing"

    url = clean_url + "/rest/ping.view"
    params = {
        "u": user,
        "t": token,
        "s": salt,
        "v": "1.16.1",
        "c": "PiesALACRip",
        "f": "json",
    }
    try:
        resp = requests.get(url, params=params, timeout=timeout, allow_redirects=False)
        if resp.status_code == 200:
            data = resp.json()
            sub = data.get("subsonic-response", {})
            if sub.get("status") == "ok":
                version = sub.get("version", "")
                return True, f"Connected to Subsonic/Navidrome (API v{version})"
            error_info = sub.get("error", {})
            err_msg = error_info.get("message", "Authentication or parameter error")
            return False, f"Subsonic error: {err_msg}"
        elif 300 <= resp.status_code < 400:
            return False, f"Server returned redirect ({resp.status_code}); redirects are disabled for security"
        return False, f"Server returned HTTP {resp.status_code}"
    except requests.Timeout:
        return False, "Connection timed out"
    except Exception as e:
        logger.debug(f"Navidrome connection test failed: {type(e).__name__}")
        return False, "Failed to connect to Navidrome server"


def trigger_navidrome_refresh(server_url: str, user: str, token: str, salt: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Trigger a scan on Navidrome/Subsonic via GET /rest/startScan.view safely."""
    try:
        clean_url = validate_integration_url(server_url)
    except ValueError as ve:
        return False, str(ve)

    if not user or not token or not salt:
        return False, "Navidrome not configured"

    url = clean_url + "/rest/startScan.view"
    params = {
        "u": user,
        "t": token,
        "s": salt,
        "v": "1.16.1",
        "c": "PiesALACRip",
        "f": "json",
    }
    try:
        resp = requests.get(url, params=params, timeout=timeout, allow_redirects=False)
        if resp.status_code == 200:
            data = resp.json()
            sub = data.get("subsonic-response", {})
            if sub.get("status") == "ok":
                return True, "Navidrome scan initiated successfully"
            error_info = sub.get("error", {})
            return False, f"Scan failed: {error_info.get('message', 'Unknown error')}"
        return False, f"Server returned HTTP {resp.status_code}"
    except Exception as e:
        logger.error(f"Failed to trigger Navidrome scan: {type(e).__name__}")
        return False, "Error contacting Navidrome server"


def dispatch_media_webhooks(config_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Trigger enabled integrations according to config.
    Returns list of result objects with sanitized status messages.
    """
    results = []
    integrations = config_dict.get("integrations", {})

    # Jellyfin
    jf = integrations.get("jellyfin", {})
    if jf.get("enabled") and jf.get("auto_refresh"):
        server_url = jf.get("server_url", "")
        api_key = jf.get("api_key", "")
        success, msg = trigger_jellyfin_refresh(server_url, api_key)
        results.append({"service": "jellyfin", "success": success, "message": msg})

    # Navidrome
    navi = integrations.get("navidrome", {})
    if navi.get("enabled") and navi.get("auto_refresh"):
        server_url = navi.get("server_url", "")
        user = navi.get("user", "")
        token = navi.get("token", "")
        salt = navi.get("salt", "")
        success, msg = trigger_navidrome_refresh(server_url, user, token, salt)
        results.append({"service": "navidrome", "success": success, "message": msg})

    return results
