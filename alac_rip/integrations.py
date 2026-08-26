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

    headers = {
        "X-Emby-Token": api_key,
        "Authorization": f'MediaBrowser Client="PiesPearMusic", Device="Desktop", DeviceId="pies-pear-music", Version="1.0.0", Token="{api_key}"',
        "Accept": "application/json",
    }
    for endpoint in ("/System/Info", "/System/Info/Public"):
        url = clean_url + endpoint
        try:
            resp = requests.get(url, headers=headers, params={"api_key": api_key}, timeout=timeout, allow_redirects=False)
            if resp.status_code == 200:
                data = resp.json()
                server_name = data.get("ServerName", "Jellyfin")
                version = data.get("Version", "")
                return True, f"Connected to {server_name} ({version})"
            elif resp.status_code in (401, 403):
                return False, "Authentication failed - invalid API key"
            elif 300 <= resp.status_code < 400:
                return False, f"Server returned redirect ({resp.status_code}); redirects are disabled for security"
        except requests.Timeout:
            return False, "Connection timed out"
        except Exception as e:
            logger.debug(f"Jellyfin check on {endpoint} failed: {e}")
            continue

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
        "Authorization": f'MediaBrowser Client="PiesPearMusic", Device="Desktop", DeviceId="pies-pear-music", Version="1.0.0", Token="{api_key}"',
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, params={"api_key": api_key}, json={}, timeout=timeout, allow_redirects=False)
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

    if not user:
        return False, "Navidrome username is missing"
    if not token:
        return False, "Navidrome token or password is missing"

    params = {
        "u": user,
        "v": "1.16.1",
        "c": "PiesPearMusic",
        "f": "json",
    }
    if salt:
        params["t"] = token
        params["s"] = salt
    else:
        params["p"] = token

    for ep in ("/rest/ping.view", "/ping.view"):
        url = clean_url + ep
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
        except requests.Timeout:
            return False, "Connection timed out"
        except Exception as e:
            logger.debug(f"Navidrome check on {ep} failed: {e}")
            continue

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
        "fullScan": "true",
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


def send_discord_webhook(
    webhook_url: str,
    title: str,
    description: str,
    fields: Optional[list[dict[str, Any]]] = None,
    thumbnail_url: Optional[str] = None,
    color: int = 0x3B82F6,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """Send a notification embed to a Discord webhook."""
    try:
        clean_url = validate_integration_url(webhook_url)
    except ValueError as ve:
        return False, str(ve)

    embed: dict[str, Any] = {
        "title": title,
        "description": description,
        "color": color,
        "footer": {"text": "Pies Pear Music"},
    }
    if fields:
        embed["fields"] = fields
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}

    payload = {
        "username": "Pies Pear Music",
        "embeds": [embed],
    }

    try:
        resp = requests.post(clean_url, json=payload, timeout=timeout, allow_redirects=False)
        if resp.status_code in (200, 204):
            return True, "Discord notification sent successfully"
        return False, f"Discord returned HTTP {resp.status_code}"
    except Exception as e:
        logger.error(f"Failed to send Discord webhook: {e}")
        return False, "Error contacting Discord webhook"


def send_telegram_notification(
    bot_token: str,
    chat_id: str,
    message: str,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """Send a message via Telegram Bot API."""
    if not bot_token or not chat_id:
        return False, "Telegram bot token or chat ID is missing"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout, allow_redirects=False)
        if resp.status_code == 200:
            return True, "Telegram notification sent successfully"
        return False, f"Telegram returned HTTP {resp.status_code}"
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return False, "Error contacting Telegram API"


def send_gotify_notification(
    server_url: str,
    token: str,
    title: str,
    message: str,
    priority: int = 5,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """Send a push notification via Gotify."""
    try:
        clean_url = validate_integration_url(server_url)
    except ValueError as ve:
        return False, str(ve)

    if not token:
        return False, "Gotify application token is missing"

    url = f"{clean_url}/message"
    headers = {"X-Gotify-Key": token}
    payload = {
        "title": title,
        "message": message,
        "priority": priority,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout, allow_redirects=False)
        if resp.status_code == 200:
            return True, "Gotify notification sent successfully"
        return False, f"Gotify returned HTTP {resp.status_code}"
    except Exception as e:
        logger.error(f"Failed to send Gotify notification: {e}")
        return False, "Error contacting Gotify server"


def dispatch_completion_notifications(
    config_dict: dict[str, Any],
    event_title: str,
    event_description: str,
    fields: Optional[list[dict[str, Any]]] = None,
    thumbnail_url: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Dispatch completion notifications across all enabled channels (Discord, Telegram, Gotify).
    """
    results = []
    integrations = config_dict.get("integrations", {})

    # Discord
    discord = integrations.get("discord", {})
    if discord.get("enabled") and discord.get("webhook_url"):
        ok, msg = send_discord_webhook(
            webhook_url=discord["webhook_url"],
            title=event_title,
            description=event_description,
            fields=fields,
            thumbnail_url=thumbnail_url,
        )
        results.append({"service": "discord", "success": ok, "message": msg})

    # Telegram
    telegram = integrations.get("telegram", {})
    if telegram.get("enabled") and telegram.get("bot_token") and telegram.get("chat_id"):
        text_content = f"<b>{event_title}</b>\n\n{event_description}"
        if fields:
            for f in fields:
                text_content += f"\n• <b>{f.get('name', '')}</b>: {f.get('value', '')}"
        ok, msg = send_telegram_notification(
            bot_token=telegram["bot_token"],
            chat_id=telegram["chat_id"],
            message=text_content,
        )
        results.append({"service": "telegram", "success": ok, "message": msg})

    # Gotify
    gotify = integrations.get("gotify", {})
    if gotify.get("enabled") and gotify.get("server_url") and gotify.get("token"):
        text_content = event_description
        if fields:
            for f in fields:
                text_content += f"\n• {f.get('name', '')}: {f.get('value', '')}"
        ok, msg = send_gotify_notification(
            server_url=gotify["server_url"],
            token=gotify["token"],
            title=event_title,
            message=text_content,
        )
        results.append({"service": "gotify", "success": ok, "message": msg})

    return results

