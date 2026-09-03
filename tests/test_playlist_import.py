from unittest.mock import patch
from alac_rip import playlist_import


def test_parse_spotify_playlist_url():
    url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=123"
    assert playlist_import.parse_spotify_playlist_url(url) == "37i9dQZF1DXcBWIGoYBM5M"

    uri = "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"
    assert playlist_import.parse_spotify_playlist_url(uri) == "37i9dQZF1DXcBWIGoYBM5M"

    invalid = "https://example.com/song"
    assert playlist_import.parse_spotify_playlist_url(invalid) is None


def test_parse_csv_tracks():
    csv_data = """Track Name,Artist Name,Album Name,ISRC
Midnight City,M83,Hurry Up We're Dreaming,FR6V81100078
Starboy,The Weeknd,Starboy,USUG11601729
"""
    tracks = playlist_import.parse_csv_tracks(csv_data)
    assert len(tracks) == 2
    assert tracks[0]["title"] == "Midnight City"
    assert tracks[0]["artist"] == "M83"
    assert tracks[0]["isrc"] == "FR6V81100078"


def test_parse_m3u_tracks():
    m3u_data = """#EXTM3U
#EXTINF:244,Daft Punk - Get Lucky
/music/daft_punk_get_lucky.flac
#EXTINF:180,Justice - D.A.N.C.E.
/music/justice_dance.flac
"""
    tracks = playlist_import.parse_m3u_tracks(m3u_data)
    assert len(tracks) == 2
    assert tracks[0]["artist"] == "Daft Punk"
    assert tracks[0]["title"] == "Get Lucky"
    assert tracks[1]["artist"] == "Justice"
    assert tracks[1]["title"] == "D.A.N.C.E."


def test_match_tracks_to_apple_music():
    raw_tracks = [{"title": "Instant Crush", "artist": "Daft Punk", "album": "RAM", "isrc": ""}]
    with patch("alac_rip.playlist_import.search_apple_music_tracks") as mock_search:
        mock_search.return_value = [{
            "id": "am-999",
            "title": "Instant Crush",
            "artist": "Daft Punk",
            "album": "Random Access Memories",
        }]
        matches = playlist_import.match_tracks_to_apple_music(raw_tracks, bearer_token="token123")
        assert len(matches) == 1
        assert matches[0]["matched"] is True
        assert matches[0]["am_track"]["id"] == "am-999"
