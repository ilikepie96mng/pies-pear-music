import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from alac_rip import gemini_ai, integrations, lyrics, playlist_import
from alac_rip.integrations import validate_integration_url
from alac_rip.server import _sanitize_config_dict


def test_integration_ssrf_and_url_validation():
    """Verify that dangerous IP ranges and malformed URLs are rejected."""
    # Must reject invalid schemes
    with pytest.raises(ValueError, match="http or https"):
        validate_integration_url("ftp://example.com/api")
    with pytest.raises(ValueError, match="http or https"):
        validate_integration_url("file:///etc/passwd")

    # Must reject embedded credentials
    with pytest.raises(ValueError, match="credentials"):
        validate_integration_url("http://user:pass@192.168.1.5:8096")

    # Must reject link-local and metadata addresses
    with pytest.raises(ValueError, match="forbidden network range"):
        validate_integration_url("http://169.254.169.254/latest/meta-data")

    # Must reject broadcast
    with pytest.raises(ValueError, match="forbidden"):
        validate_integration_url("http://255.255.255.255:8096")

    # Must accept valid LAN or domain targets
    assert validate_integration_url("http://192.168.1.100:8096/") == "http://192.168.1.100:8096"
    assert validate_integration_url("https://jellyfin.local:8096") == "https://jellyfin.local:8096"


def test_jellyfin_and_navidrome_credential_redaction(monkeypatch):
    """Verify that integration checks never leak secrets in error messages."""
    # Navidrome connection test with sensitive salt/token
    with patch("requests.get", side_effect=Exception("Connection reset by peer")):
        success, msg = integrations.test_navidrome_connection(
            "http://192.168.1.50:4533",
            user="secret_user",
            token="SUPER_SECRET_TOKEN",
            salt="SUPER_SECRET_SALT",
        )
        assert not success
        assert "SUPER_SECRET_TOKEN" not in msg
        assert "SUPER_SECRET_SALT" not in msg
        assert "secret_user" not in msg
        assert msg == "Failed to connect to Navidrome server"

    # Jellyfin connection test with secret token
    with patch("requests.get", side_effect=Exception("Connection refused")):
        success, msg = integrations.test_jellyfin_connection(
            "http://192.168.1.50:8096",
            api_key="SUPER_SECRET_JELLYFIN_API_KEY",
        )
        assert not success
        assert "SUPER_SECRET_JELLYFIN_API_KEY" not in msg
        assert msg == "Failed to connect to Jellyfin server"


def test_save_lrc_file_refuses_symlinks_and_persists_safely():
    """Verify that .lrc persistence refuses to follow symlinks to outside files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        outside_file = root / "sensitive_target.txt"
        outside_file.write_text("INITIAL_SENSITIVE_DATA", encoding="utf-8")

        music_dir = root / "Music" / "Artist" / "Album"
        music_dir.mkdir(parents=True)

        symlink_lrc = music_dir / "track.lrc"
        symlink_lrc.symlink_to(outside_file)

        # Attempting to save lyrics over the symlink must fail and leave the outside file intact
        res = lyrics.save_lrc_file(symlink_lrc, "[00:01.00] Malicious lyrics")
        assert not res
        assert outside_file.read_text(encoding="utf-8") == "INITIAL_SENSITIVE_DATA"

        # Legitimate regular write
        real_lrc = music_dir / "legit_track.lrc"
        ok = lyrics.save_lrc_file(real_lrc, "[00:01.00] Legitimate lyrics")
        assert ok
        assert real_lrc.is_file()
        assert not real_lrc.is_symlink()
        assert "[00:01.00] Legitimate lyrics" in real_lrc.read_text(encoding="utf-8")


def test_gemini_header_auth_and_schema_validation():
    """Verify that Gemini API key is sent via header and never in query URL."""
    captured_requests = []

    def mock_post(url, *args, **kwargs):
        captured_requests.append({"url": url, "headers": kwargs.get("headers", {})})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"playlist_title": "Synth Rock", "description": "80s synths", "vibe_tags": ["synth"], "tracks": [{"title": "Blue Monday", "artist": "New Order", "album": "Power", "rationale": "Classic"}]}'
                            }
                        ]
                    }
                }
            ]
        }
        return mock_resp

    with patch("requests.post", side_effect=mock_post), patch("alac_rip.gemini_ai.list_available_gemini_models", return_value=["gemini-2.5-flash"]):
        res = gemini_ai.generate_smart_playlist("80s synth rock", api_key="GEMINI_SECRET_KEY_12345")
        assert res.get("playlist_title") == "Synth Rock"
        assert len(res.get("tracks", [])) == 1

        assert len(captured_requests) > 0
        for req in captured_requests:
            # Key MUST NOT be in the URL
            assert "key=" not in req["url"]
            assert "GEMINI_SECRET_KEY_12345" not in req["url"]
            # Key MUST be in x-goog-api-key header
            assert req["headers"].get("x-goog-api-key") == "GEMINI_SECRET_KEY_12345"


def test_config_secrets_redaction():
    """Verify that integration and API keys are recursively redacted in get_config."""
    raw_cfg = {
        "music_dir": "/home/user/Music",
        "gemini_api_key": "top_secret_gemini",
        "lastfm_api_key": "top_secret_lastfm",
        "integrations": {
            "jellyfin": {
                "enabled": True,
                "server_url": "http://192.168.1.10:8096",
                "api_key": "jellyfin_secret_key_abc",
            },
            "navidrome": {
                "enabled": True,
                "server_url": "http://192.168.1.10:4533",
                "user": "alice",
                "token": "navidrome_token_123",
                "salt": "navidrome_salt_456",
            },
        },
    }

    sanitized = _sanitize_config_dict(raw_cfg)
    assert "gemini_api_key" not in sanitized
    assert "lastfm_api_key" not in sanitized
    assert sanitized["integrations"]["jellyfin"]["api_key"] == "********"
    assert sanitized["integrations"]["jellyfin"]["api_key_configured"] is True
    assert sanitized["integrations"]["navidrome"]["token"] == "********"
    assert sanitized["integrations"]["navidrome"]["salt"] == "********"
    assert sanitized["integrations"]["navidrome"]["token_configured"] is True


def test_csv_formula_prefix_neutralization():
    """Verify that spreadsheet formula prefixes are stripped during CSV parsing."""
    csv_payload = """Track Name,Artist Name,Album Name
=1+1,Safe Artist,Safe Album
+SUM(A1:A10),Safe Artist,Safe Album
@HYPERLINK("http://evil.com"),Safe Artist,Safe Album
-100,Safe Artist,Safe Album
Normal Song,Normal Artist,Normal Album
"""
    tracks = playlist_import.parse_csv_tracks(csv_payload)
    assert len(tracks) == 5
    assert tracks[0]["title"] == "1+1"
    assert tracks[1]["title"] == "SUM(A1:A10)"
    assert tracks[2]["title"] == 'HYPERLINK("http://evil.com")'
    assert tracks[3]["title"] == "100"
    assert tracks[4]["title"] == "Normal Song"
