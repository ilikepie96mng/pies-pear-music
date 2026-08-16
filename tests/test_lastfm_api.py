import pytest
from unittest.mock import patch, MagicMock
from alac_rip.lastfm_api import LastFmError, get_similar_artists
import requests


def _mock_resp(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.ok = status < 400
    resp.status_code = status
    resp.json.return_value = data
    return resp


SIMILAR_RESPONSE = {
    "similarartists": {
        "artist": [
            {"name": "Artist B", "match": "0.87", "url": "https://www.last.fm/music/Artist+B"},
            {"name": "Artist C", "match": "0.65", "url": "https://www.last.fm/music/Artist+C"},
        ]
    }
}


def test_get_similar_artists_returns_list():
    with patch("alac_rip.lastfm_api.requests.get", return_value=_mock_resp(SIMILAR_RESPONSE)):
        result = get_similar_artists("Artist A", "fake-key")
    assert len(result) == 2
    assert result[0] == {"name": "Artist B", "match": 0.87, "url": "https://www.last.fm/music/Artist+B"}
    assert result[1]["name"] == "Artist C"


def test_get_similar_artists_match_is_float():
    with patch("alac_rip.lastfm_api.requests.get", return_value=_mock_resp(SIMILAR_RESPONSE)):
        result = get_similar_artists("Artist A", "fake-key")
    assert isinstance(result[0]["match"], float)


def test_get_similar_artists_artist_not_found_returns_empty():
    resp = _mock_resp({"error": 6, "message": "The artist you supplied could not be found"})
    with patch("alac_rip.lastfm_api.requests.get", return_value=resp):
        result = get_similar_artists("Unknown Artist", "fake-key")
    assert result == []


def test_get_similar_artists_other_api_error_raises():
    resp = _mock_resp({"error": 10, "message": "Invalid API key"})
    with patch("alac_rip.lastfm_api.requests.get", return_value=resp):
        with pytest.raises(LastFmError, match="10"):
            get_similar_artists("Artist A", "bad-key")


def test_get_similar_artists_non_200_raises():
    resp = _mock_resp({}, status=503)
    with patch("alac_rip.lastfm_api.requests.get", return_value=resp):
        with pytest.raises(LastFmError, match="503"):
            get_similar_artists("Artist A", "fake-key")


def test_get_similar_artists_network_error_raises():
    with patch("alac_rip.lastfm_api.requests.get", side_effect=requests.ConnectionError("timeout")):
        with pytest.raises(LastFmError, match="Network error"):
            get_similar_artists("Artist A", "fake-key")


def test_get_similar_artists_passes_correct_params():
    with patch("alac_rip.lastfm_api.requests.get", return_value=_mock_resp(SIMILAR_RESPONSE)) as mock_get:
        get_similar_artists("Test Artist", "my-key", limit=5)
    params = mock_get.call_args[1]["params"]
    assert params["method"] == "artist.getSimilar"
    assert params["artist"] == "Test Artist"
    assert params["api_key"] == "my-key"
    assert params["limit"] == 5
    assert params["format"] == "json"


def test_get_similar_artists_empty_artist_list():
    resp = _mock_resp({"similarartists": {"artist": []}})
    with patch("alac_rip.lastfm_api.requests.get", return_value=resp):
        result = get_similar_artists("Niche Artist", "fake-key")
    assert result == []


def test_lastfm_uses_https_and_user_agent():
    with patch("alac_rip.lastfm_api.requests.get", return_value=_mock_resp(SIMILAR_RESPONSE)) as mock_get:
        get_similar_artists("Artist", "key")
    url = mock_get.call_args[0][0]
    headers = mock_get.call_args[1].get("headers", {})
    assert url.startswith("https://")
    assert "User-Agent" in headers
    assert "PiesPearMusic" in headers["User-Agent"]

