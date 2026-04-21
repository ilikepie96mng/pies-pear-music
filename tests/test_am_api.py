import pytest
from unittest.mock import patch, MagicMock
from alac_rip.am_api import AMApiError, fetch_bearer_token, fetch_playlist_tracks
import alac_rip.am_api as am_api_module


@pytest.fixture(autouse=True)
def clear_token_cache():
    am_api_module._bearer_token_cache = None
    yield
    am_api_module._bearer_token_cache = None


FAKE_HTML = '''<html><head>
<script type="module" crossorigin src="/assets/index~abc123.js"></script>
</head></html>'''

FAKE_JS = 'some js content "authorization":"Bearer eyJhbGciOiJFUzI1NiJ9.fake.token" more content'


def _mock_get(url, **kwargs):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if "music.apple.com/assets" in url:
        resp.text = FAKE_JS
    else:
        resp.text = FAKE_HTML
    return resp


def test_fetch_bearer_token_extracts_jwt():
    with patch("alac_rip.am_api.requests.get", side_effect=_mock_get):
        token = fetch_bearer_token()
    assert token == "eyJhbGciOiJFUzI1NiJ9.fake.token"


def test_fetch_bearer_token_caches_result():
    with patch("alac_rip.am_api.requests.get", side_effect=_mock_get) as mock_get:
        fetch_bearer_token()
        fetch_bearer_token()
    # Only two calls total (html + js) despite calling twice
    assert mock_get.call_count == 2


def test_fetch_bearer_token_raises_if_no_script():
    bad_html = MagicMock()
    bad_html.raise_for_status = MagicMock()
    bad_html.text = "<html>no scripts here</html>"
    with patch("alac_rip.am_api.requests.get", return_value=bad_html):
        with pytest.raises(AMApiError, match="JS bundle"):
            fetch_bearer_token()


def test_fetch_bearer_token_raises_if_no_token_in_js():
    def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "assets" in url:
            resp.text = "no token here"
        else:
            resp.text = FAKE_HTML
        return resp

    with patch("alac_rip.am_api.requests.get", side_effect=mock_get):
        with pytest.raises(AMApiError, match="bearer token"):
            fetch_bearer_token()


def _make_tracks_response(ids_titles_artists, next_url=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.status_code = 200
    body = {
        "data": [
            {"id": id_, "attributes": {"name": title, "artistName": artist}}
            for id_, title, artist in ids_titles_artists
        ]
    }
    if next_url:
        body["next"] = next_url
    resp.json.return_value = body
    return resp


def test_fetch_playlist_tracks_returns_dicts():
    resp = _make_tracks_response([("111", "Song A", "Artist A"), ("222", "Song B", "Artist B")])
    with patch("alac_rip.am_api.requests.get", return_value=resp):
        tracks = fetch_playlist_tracks(
            "https://music.apple.com/us/playlist/test/pl.abc123",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
        )
    assert tracks == [
        {"id": "111", "title": "Song A", "artist": "Artist A"},
        {"id": "222", "title": "Song B", "artist": "Artist B"},
    ]


def test_fetch_playlist_tracks_paginates():
    call_count = 0

    def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_tracks_response(
                [("111", "A", "X"), ("222", "B", "X")],
                next_url="/v1/catalog/us/playlists/pl.abc/tracks?offset=2"
            )
        else:
            return _make_tracks_response([("333", "C", "X")])

    with patch("alac_rip.am_api.requests.get", side_effect=mock_get):
        tracks = fetch_playlist_tracks(
            "https://music.apple.com/us/playlist/test/pl.abc123",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
        )
    assert [t["id"] for t in tracks] == ["111", "222", "333"]
    assert call_count == 2


def test_fetch_playlist_tracks_raises_on_bad_url():
    with pytest.raises(AMApiError, match="playlist ID"):
        fetch_playlist_tracks(
            "https://music.apple.com/us/album/not-a-playlist/12345",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
        )


def test_fetch_playlist_tracks_raises_on_api_error():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.status_code = 401
    with patch("alac_rip.am_api.requests.get", return_value=resp):
        with pytest.raises(AMApiError, match="401"):
            fetch_playlist_tracks(
                "https://music.apple.com/us/playlist/test/pl.abc123",
                media_user_token="fake-mut",
                bearer_token="fake-bearer",
            )


def test_fetch_playlist_tracks_defaults_storefront_placeholder():
    resp = _make_tracks_response([("111", "A", "X")])
    with patch("alac_rip.am_api.requests.get", return_value=resp) as mock_get:
        fetch_playlist_tracks(
            "https://music.apple.com/us/playlist/test/pl.abc123",
            media_user_token="fake-mut",
            bearer_token="fake-bearer",
            storefront="enter your account storefront",
        )
    called_url = mock_get.call_args[0][0]
    assert "/v1/catalog/us/" in called_url
