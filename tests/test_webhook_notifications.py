from unittest.mock import patch, MagicMock
from alac_rip.integrations import (
    send_discord_webhook,
    send_telegram_notification,
    send_gotify_notification,
    dispatch_completion_notifications,
)


@patch("requests.post")
def test_send_discord_webhook(mock_post):
    mock_post.return_value = MagicMock(status_code=204)
    ok, msg = send_discord_webhook(
        webhook_url="https://discord.com/api/webhooks/123/abc",
        title="Test Download",
        description="Album completed",
        fields=[{"name": "Artist", "value": "Ado", "inline": True}],
    )
    assert ok is True
    assert "successfully" in msg
    assert mock_post.called
    payload = mock_post.call_args[1]["json"]
    assert payload["embeds"][0]["title"] == "Test Download"


@patch("requests.post")
def test_send_telegram_notification(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    ok, msg = send_telegram_notification(
        bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        chat_id="987654321",
        message="<b>Completed</b>",
    )
    assert ok is True
    assert "successfully" in msg
    assert mock_post.called
    payload = mock_post.call_args[1]["json"]
    assert payload["chat_id"] == "987654321"


@patch("requests.post")
def test_send_gotify_notification(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    ok, msg = send_gotify_notification(
        server_url="https://gotify.example.com",
        token="A1B2C3D4E5",
        title="Gotify Test",
        message="Downloaded 10 tracks",
    )
    assert ok is True
    assert "successfully" in msg
    assert mock_post.called
    headers = mock_post.call_args[1]["headers"]
    assert headers["X-Gotify-Key"] == "A1B2C3D4E5"


@patch("alac_rip.integrations.send_discord_webhook")
@patch("alac_rip.integrations.send_telegram_notification")
@patch("alac_rip.integrations.send_gotify_notification")
def test_dispatch_completion_notifications(mock_gotify, mock_telegram, mock_discord):
    mock_discord.return_value = (True, "Discord OK")
    mock_telegram.return_value = (True, "Telegram OK")
    mock_gotify.return_value = (True, "Gotify OK")

    config = {
        "integrations": {
            "discord": {"enabled": True, "webhook_url": "https://discord.com/api/webhooks/123/abc"},
            "telegram": {"enabled": True, "bot_token": "token", "chat_id": "123"},
            "gotify": {"enabled": True, "server_url": "https://gotify.local", "token": "gtoken"},
        }
    }

    results = dispatch_completion_notifications(
        config,
        event_title="Sync Complete",
        event_description="Organized 20 tracks",
        fields=[{"name": "Count", "value": "20"}],
    )

    assert len(results) == 3
    assert all(r["success"] for r in results)
    assert mock_discord.called
    assert mock_telegram.called
    assert mock_gotify.called
