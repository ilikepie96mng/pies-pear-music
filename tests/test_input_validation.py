import pytest

from alac_rip.server import (
    _MAX_PLAYLIST_NAME_LENGTH,
    _validate_apple_music_url,
    _validate_download_format,
    _validate_playlist_name,
)


@pytest.mark.parametrize("url", [
    "https://music.apple.com/us/album/example/123",
    "https://music.apple.com/us/playlist/example/pl.123?l=en",
])
def test_apple_music_url_accepts_valid_https_urls(url):
    assert _validate_apple_music_url(url) == url


@pytest.mark.parametrize("url", [
    "",
    "http://music.apple.com/us/album/example/123",
    "https://example.com/us/album/example/123",
    "https://user:password@music.apple.com/us/album/example/123",
    "https://music.apple.com/",
])
def test_apple_music_url_rejects_unsafe_or_invalid_urls(url):
    with pytest.raises(ValueError, match="music.apple.com"):
        _validate_apple_music_url(url)


@pytest.mark.parametrize(("value", "expected"), [("alac", "ALAC"), ("AAC", "AAC"), ("atmos", "ATMOS")])
def test_download_format_normalizes_supported_values(value, expected):
    assert _validate_download_format(value) == expected


def test_download_format_rejects_unknown_value():
    with pytest.raises(ValueError, match="Format must be"):
        _validate_download_format("MP3")


def test_playlist_name_trims_safe_name():
    assert _validate_playlist_name("  Favorites  ") == "Favorites"


@pytest.mark.parametrize("name", ["", "   ", "A\nB", "A" * (_MAX_PLAYLIST_NAME_LENGTH + 1)])
def test_playlist_name_rejects_blank_control_or_overlong_values(name):
    with pytest.raises(ValueError):
        _validate_playlist_name(name)
