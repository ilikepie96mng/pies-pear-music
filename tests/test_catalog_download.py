import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import alac_rip.server as server_mod
from alac_rip.server import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        f"music_dir: {tmp_path}/Music\n"
        f"state_dir: {tmp_path}/state\n"
    )
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", cfg_file)
    with TestClient(app) as c:
        yield c


def test_catalog_search_endpoint(client):
    mock_search_results = {
        "songs": [
            {"id": "123", "title": "Get Lucky", "artist": "Daft Punk", "album": "RAM", "url": "https://music.apple.com/us/song/123", "artwork_url": None}
        ],
        "albums": [
            {"id": "456", "title": "RAM", "artist": "Daft Punk", "release_date": "2013", "track_count": 13, "url": "https://music.apple.com/us/album/456", "artwork_url": None}
        ],
        "artists": [
            {"id": "789", "name": "Daft Punk", "genre_names": ["Electronic"], "url": "https://music.apple.com/us/artist/789", "artwork_url": None}
        ],
    }
    with patch("alac_rip.am_api.fetch_bearer_token", return_value="fake-bearer-token"), \
         patch("alac_rip.am_api.search_apple_music_catalog", return_value=mock_search_results):
        resp = client.get("/catalog/search?q=Daft+Punk&types=songs,albums,artists&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["songs"]) == 1
        assert data["songs"][0]["title"] == "Get Lucky"
        assert len(data["albums"]) == 1
        assert data["albums"][0]["title"] == "RAM"
        assert len(data["artists"]) == 1
        assert data["artists"][0]["name"] == "Daft Punk"


def test_catalog_album_endpoint(client):
    mock_album_details = {
        "id": "456",
        "title": "Random Access Memories",
        "artist": "Daft Punk",
        "release_date": "2013-05-17",
        "record_label": "Columbia",
        "genre_names": ["Electronic", "Dance"],
        "track_count": 2,
        "artwork_url": "https://example.com/art.jpg",
        "url": "https://music.apple.com/us/album/456",
        "tracks": [
            {
                "id": "101",
                "title": "Give Life Back to Music",
                "artist": "Daft Punk",
                "album": "Random Access Memories",
                "track_number": 1,
                "disc_number": 1,
                "duration_ms": 275000,
                "url": "https://music.apple.com/us/song/101",
                "artwork_url": "https://example.com/art.jpg",
                "isrc": "USSM11300001",
            },
            {
                "id": "102",
                "title": "Get Lucky",
                "artist": "Daft Punk",
                "album": "Random Access Memories",
                "track_number": 2,
                "disc_number": 1,
                "duration_ms": 369000,
                "url": "https://music.apple.com/us/song/102",
                "artwork_url": "https://example.com/art.jpg",
                "isrc": "USSM11300002",
            }
        ]
    }
    with patch("alac_rip.am_api.fetch_bearer_token", return_value="fake-bearer-token"), \
         patch("alac_rip.am_api.fetch_album_details", return_value=mock_album_details):
        resp = client.get("/catalog/album?id=456")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "456"
        assert data["title"] == "Random Access Memories"
        assert len(data["tracks"]) == 2
        assert data["tracks"][1]["title"] == "Get Lucky"


def test_catalog_artist_endpoint(client):
    mock_artist_discog = {
        "id": "789",
        "name": "Daft Punk",
        "url": "https://music.apple.com/us/artist/789",
        "genres": ["Electronic"],
        "artwork_url": "https://example.com/artist.jpg",
        "album_count": 2,
        "albums": [
            {
                "id": "456",
                "title": "Random Access Memories",
                "artist": "Daft Punk",
                "release_date": "2013-05-17",
                "track_count": 13,
                "is_single": False,
                "url": "https://music.apple.com/us/album/456",
                "artwork_url": "https://example.com/art1.jpg",
            },
            {
                "id": "457",
                "title": "Discovery",
                "artist": "Daft Punk",
                "release_date": "2001-03-12",
                "track_count": 14,
                "is_single": False,
                "url": "https://music.apple.com/us/album/457",
                "artwork_url": "https://example.com/art2.jpg",
            }
        ]
    }
    with patch("alac_rip.am_api.fetch_bearer_token", return_value="fake-bearer-token"), \
         patch("alac_rip.am_api.fetch_artist_discography", return_value=mock_artist_discog):
        resp = client.get("/catalog/artist?id=789")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "789"
        assert data["name"] == "Daft Punk"
        assert len(data["albums"]) == 2
        assert data["albums"][0]["title"] == "Random Access Memories"
        assert data["albums"][1]["title"] == "Discovery"


def test_download_album_endpoint(client):
    req_body = {
        "url": "https://music.apple.com/us/album/random-access-memories/456",
        "format": "ALAC",
    }
    resp = client.post("/download/album", json=req_body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["queued"] == 1
    assert len(data["job_ids"]) == 1


def test_download_artist_albums_batch_endpoint(client):
    req_body = {
        "artist_id": "789",
        "albums": [
            {"id": "456", "url": "https://music.apple.com/us/album/random-access-memories/456", "title": "RAM"},
            {"id": "457", "url": "https://music.apple.com/us/album/discovery/457", "title": "Discovery"},
        ],
        "format": "ALAC",
    }
    resp = client.post("/download/artist-albums", json=req_body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["queued"] == 2
    assert len(data["job_ids"]) == 2


def test_version_endpoint_clean_public(client):
    resp = client.get("/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "2.3.0"
    assert data["display"] == "v2.3.0"
    assert "(dev)" not in data["display"]


def test_catalog_genres_and_charts_endpoints(client):
    resp = client.get("/catalog/genres")
    assert resp.status_code == 200
    genres = resp.json()["genres"]
    assert len(genres) >= 10
    assert any(g["id"] == "20" for g in genres)

    mock_charts = {
        "genre_id": "20",
        "playlists": [
            {
                "id": "pl.alt1",
                "title": "ALT CTRL",
                "curator": "Apple Music Alternative",
                "track_count": 50,
                "provider": "apple",
            }
        ],
        "albums": [],
        "songs": [],
    }
    with patch("alac_rip.am_api.fetch_bearer_token", return_value="fake-bearer-token"), \
         patch("alac_rip.am_api.fetch_genre_charts", return_value=mock_charts):
        chart_resp = client.get("/catalog/genre/20/charts")
        assert chart_resp.status_code == 200
        cdata = chart_resp.json()
        assert cdata["genre_id"] == "20"
        assert len(cdata["playlists"]) == 1
        assert cdata["playlists"][0]["title"] == "ALT CTRL"


def test_catalog_playlist_details_endpoint(client):
    mock_pl = {
        "id": "pl.synthwave",
        "title": "Synthwave Essentials",
        "curator": "Apple Music Electronic",
        "description": "Retro futuristic sounds.",
        "track_count": 2,
        "artwork_url": "https://example.com/pl.jpg",
        "url": "https://music.apple.com/us/playlist/synthwave-essentials/pl.synthwave",
        "provider": "apple",
        "tracks": [
            {
                "id": "901",
                "title": "Nightcall",
                "artist": "Kavinsky",
                "album": "OutRun",
                "track_number": 1,
                "disc_number": 1,
                "duration_ms": 258000,
                "url": "https://music.apple.com/us/song/901",
            },
            {
                "id": "902",
                "title": "Tech Noir",
                "artist": "GUNSHIP",
                "album": "GUNSHIP",
                "track_number": 2,
                "disc_number": 1,
                "duration_ms": 297000,
                "url": "https://music.apple.com/us/song/902",
            },
        ],
    }
    with patch("alac_rip.am_api.fetch_bearer_token", return_value="fake-bearer-token"), \
         patch("alac_rip.am_api.fetch_playlist_details", return_value=mock_pl):
        resp = client.get("/catalog/playlist?id=pl.synthwave")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "pl.synthwave"
        assert data["title"] == "Synthwave Essentials"
        assert len(data["tracks"]) == 2
        assert data["tracks"][0]["in_library"] is False


def test_custom_playlist_and_add_tracks(client):
    # 1. Create a decoupled custom playlist without an Apple Music URL
    create_resp = client.post(
        "/api/v1/playlists/custom",
        json={
            "name": "Late Night Drive",
            "description": "Custom synthwave mix",
            "cover_art_url": "https://example.com/cover.jpg",
        },
    )
    assert create_resp.status_code == 201
    pl_data = create_resp.json()
    assert pl_data["name"] == "Late Night Drive"
    assert pl_data["is_custom"] is True
    assert pl_data["url"] == ""
    assert pl_data["paused"] is True

    # 2. Add tracks to the custom playlist (queues missing tracks with destination_playlist)
    add_resp = client.post(
        "/api/v1/playlists/Late%20Night%20Drive/add-tracks",
        json={
            "tracks": [
                {
                    "id": "901",
                    "title": "Nightcall",
                    "artist": "Kavinsky",
                    "album": "OutRun",
                    "url": "https://music.apple.com/us/song/901",
                }
            ],
            "download_missing": True,
            "format": "ALAC",
        },
    )
    assert add_resp.status_code == 200
    res_data = add_resp.json()
    assert res_data["playlist_name"] == "Late Night Drive"
    assert res_data["queued_downloads"] == 1
    assert len(res_data["job_ids"]) == 1

