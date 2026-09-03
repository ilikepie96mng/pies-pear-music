from unittest.mock import patch, MagicMock
from alac_rip import lyrics


def test_fetch_lrclib_lyrics_found():
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 123,
            "trackName": "Get Lucky",
            "artistName": "Daft Punk",
            "syncedLyrics": "[00:10.00] Like the legend of the phoenix",
            "plainLyrics": "Like the legend of the phoenix",
        }
        mock_get.return_value = mock_resp

        res = lyrics.fetch_lrclib_lyrics("Get Lucky", "Daft Punk")
        assert res is not None
        assert res["syncedLyrics"] == "[00:10.00] Like the legend of the phoenix"


def test_fetch_lrclib_lyrics_not_found():
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        res = lyrics.fetch_lrclib_lyrics("NonExistentTrackXYZ", "UnknownArtistABC")
        assert res is None


def test_save_lrc_file(tmp_path):
    lrc_file = tmp_path / "album" / "song.lrc"
    lrc_content = "[00:05.00] First line\n[00:12.50] Second line"
    ok = lyrics.save_lrc_file(lrc_file, lrc_content)
    assert ok is True
    assert lrc_file.is_file()
    assert lrc_file.read_text(encoding="utf-8") == lrc_content
