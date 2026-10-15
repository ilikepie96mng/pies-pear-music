import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from alac_rip.state import StateManager, Track
from alac_rip.subsonic_sync import (
    SubsonicClient,
    SubsonicError,
    SubsonicSyncEngine,
    _normalize_text,
    _parse_iso_datetime,
)


class TestSubsonicSync(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_downloaded.db"
        self.state = StateManager(self.db_path)
        self.client = SubsonicClient(
            server_url="http://127.0.0.1:4533",
            user="testuser",
            token="abcdef123456",
            salt="somesalt",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_subsonic_client_config(self):
        c = SubsonicClient("http://127.0.0.1:4533", "user", "token", "salt")
        self.assertTrue(c.is_configured)
        self.assertEqual(c._build_params()["u"], "user")
        self.assertEqual(c._build_params()["t"], "token")
        self.assertEqual(c._build_params()["s"], "salt")
        self.assertEqual(c._build_params()["v"], "1.16.1")
        self.assertEqual(c._build_params()["f"], "json")

        unconfigured = SubsonicClient("", "", "")
        self.assertFalse(unconfigured.is_configured)

    @patch("requests.get")
    def test_subsonic_client_ping(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "subsonic-response": {
                "status": "ok",
                "version": "1.16.1",
            }
        }
        mock_get.return_value = mock_resp

        ok, msg = self.client.ping()
        self.assertTrue(ok)
        self.assertIn("1.16.1", msg)

    @patch("requests.get")
    def test_subsonic_client_error_response(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "subsonic-response": {
                "status": "failed",
                "error": {"code": 40, "message": "Wrong username or password"},
            }
        }
        mock_get.return_value = mock_resp

        with self.assertRaises(SubsonicError) as exc_info:
            self.client.get_playlists()
        self.assertIn("Wrong username or password", str(exc_info.exception))
        self.assertEqual(exc_info.exception.code, 40)

    @patch("requests.get")
    def test_subsonic_client_get_playlists_normalizes_dict_to_list(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "subsonic-response": {
                "status": "ok",
                "playlists": {
                    "playlist": {"id": "pl-1", "name": "Single Playlist", "songCount": 5}
                },
            }
        }
        mock_get.return_value = mock_resp

        playlists = self.client.get_playlists()
        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0]["name"], "Single Playlist")

    @patch("requests.get")
    def test_subsonic_client_get_playlist(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "subsonic-response": {
                "status": "ok",
                "playlist": {
                    "id": "pl-1",
                    "name": "My Favorites",
                    "entry": [
                        {
                            "id": "song-1",
                            "title": "Song One",
                            "artist": "Artist One",
                            "path": "artists/Artist One/Album One/01 - Song One.flac",
                        }
                    ],
                },
            }
        }
        mock_get.return_value = mock_resp

        pl = self.client.get_playlist("pl-1")
        self.assertEqual(pl["name"], "My Favorites")
        self.assertEqual(len(pl["entry"]), 1)
        self.assertEqual(pl["entry"][0]["title"], "Song One")

    @patch("requests.get")
    def test_subsonic_client_create_and_delete_playlist(self, mock_get):
        mock_resp_create = MagicMock()
        mock_resp_create.status_code = 200
        mock_resp_create.json.return_value = {
            "subsonic-response": {
                "status": "ok",
                "playlist": {"id": "new-pl-123", "name": "Created Mix"},
            }
        }
        mock_get.return_value = mock_resp_create

        pl_id = self.client.create_playlist("Created Mix", ["song-1", "song-2"])
        self.assertEqual(pl_id, "new-pl-123")

        mock_resp_del = MagicMock()
        mock_resp_del.status_code = 200
        mock_resp_del.json.return_value = {
            "subsonic-response": {"status": "ok"}
        }
        mock_get.return_value = mock_resp_del
        self.assertTrue(self.client.delete_playlist("new-pl-123"))

    @patch("requests.get")
    def test_subsonic_client_resolve_song_id(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "subsonic-response": {
                "status": "ok",
                "searchResult3": {
                    "song": [
                        {
                            "id": "navi-song-99",
                            "title": "Midnight City",
                            "artist": "M83",
                            "path": "artists/M83/Hurry Up, We're Dreaming/01 - Midnight City.flac",
                        }
                    ]
                },
            }
        }
        mock_get.return_value = mock_resp

        local_track = Track(
            track_id="t-1",
            title="Midnight City",
            artist="M83",
            album="Hurry Up, We're Dreaming",
            local_path="/music/artists/M83/Hurry Up, We're Dreaming/01 - Midnight City.flac",
            downloaded_at="2026-01-01T00:00:00",
        )

        resolved_id = self.client.resolve_song_id(local_track)
        self.assertEqual(resolved_id, "navi-song-99")

        # Verify cached without making second request
        mock_get.reset_mock()
        self.assertEqual(self.client.resolve_song_id(local_track), "navi-song-99")
        mock_get.assert_not_called()

    def test_sync_engine_inbound_import(self):
        # Setup local tracks
        t1 = Track(
            track_id="t1",
            title="Midnight City",
            artist="M83",
            album="Hurry Up",
            local_path="/music/artists/M83/Hurry Up/01 - Midnight City.flac",
            downloaded_at="2026-01-01T00:00:00",
        )
        self.state.add_track(t1)

        # Mock Subsonic responses
        self.client.get_playlists = MagicMock(return_value=[
            {
                "id": "remote-pl-1",
                "name": "Night Drive",
                "changed": "2026-10-14T12:00:00Z",
                "songCount": 1,
            }
        ])
        self.client.get_playlist = MagicMock(return_value={
            "id": "remote-pl-1",
            "name": "Night Drive",
            "entry": [
                {
                    "id": "s-1",
                    "title": "Midnight City",
                    "artist": "M83",
                    "path": "artists/M83/Hurry Up/01 - Midnight City.flac",
                }
            ],
        })

        engine = SubsonicSyncEngine(self.state, self.client)
        summary = engine.sync_all()

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["imported_from_remote"], 1)

        # Verify state in downloaded.db
        pl = self.state.get_playlist("Night Drive")
        self.assertIsNotNone(pl)
        self.assertEqual(pl.navidrome_id, "remote-pl-1")
        self.assertEqual(pl.remote_changed_at, "2026-10-14T12:00:00Z")

        tracks = self.state.get_playlist_tracks("Night Drive")
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].track_id, "t1")

    def test_sync_engine_inbound_update_when_remote_newer(self):
        t1 = Track(
            track_id="t1", title="Track 1", artist="Artist", album="Album",
            local_path="/music/artists/Artist/Album/01 - Track 1.flac", downloaded_at="2026-01-01T00:00:00"
        )
        t2 = Track(
            track_id="t2", title="Track 2", artist="Artist", album="Album",
            local_path="/music/artists/Artist/Album/02 - Track 2.flac", downloaded_at="2026-01-01T00:00:00"
        )
        self.state.add_track(t1)
        self.state.add_track(t2)

        # Initially had only t1
        self.state.add_playlist("Existing Playlist", "http://example.com")
        self.state.link_playlist_navidrome("Existing Playlist", "rem-100", "2026-10-14T10:00:00Z")
        self.state.add_track_to_playlist("Existing Playlist", "t1")

        # Remote updated at 12:00 with both t1 and t2
        self.client.get_playlists = MagicMock(return_value=[
            {"id": "rem-100", "name": "Existing Playlist", "changed": "2026-10-14T12:00:00Z"}
        ])
        self.client.get_playlist = MagicMock(return_value={
            "id": "rem-100",
            "name": "Existing Playlist",
            "entry": [
                {"id": "s-1", "title": "Track 1", "artist": "Artist", "path": "artists/Artist/Album/01 - Track 1.flac"},
                {"id": "s-2", "title": "Track 2", "artist": "Artist", "path": "artists/Artist/Album/02 - Track 2.flac"},
            ],
        })

        engine = SubsonicSyncEngine(self.state, self.client)
        summary = engine.sync_all()

        self.assertEqual(summary["updated_local"], 1)
        tracks = self.state.get_playlist_tracks("Existing Playlist")
        self.assertEqual(len(tracks), 2)

    def test_sync_engine_outbound_push_when_local_newer(self):
        t1 = Track(
            track_id="t1", title="Track 1", artist="Artist", album="Album",
            local_path="/music/artists/Artist/Album/01 - Track 1.flac", downloaded_at="2026-01-01T00:00:00"
        )
        self.state.add_track(t1)
        self.state.add_playlist("Local Edited", "http://example.com")
        self.state.link_playlist_navidrome("Local Edited", "rem-200", "2026-10-14T10:00:00Z")
        self.state.add_track_to_playlist("Local Edited", "t1")
        # Mark local modified at 14:00 (after 10:00 remote)
        self.state.touch_playlist_local_modified("Local Edited", "2026-10-14T14:00:00Z")

        self.client.get_playlists = MagicMock(return_value=[
            {"id": "rem-200", "name": "Local Edited", "changed": "2026-10-14T10:00:00Z"}
        ])
        self.client.resolve_song_id = MagicMock(return_value="navi-t1")
        self.client.create_playlist = MagicMock(return_value="rem-200")

        engine = SubsonicSyncEngine(self.state, self.client)
        summary = engine.sync_all()

        self.assertEqual(summary["pushed_to_remote"], 1)
        self.client.create_playlist.assert_called_with(name="Local Edited", song_ids=["navi-t1"], playlist_id="rem-200")

    def test_sync_engine_outbound_create_new_local_playlist(self):
        t1 = Track(
            track_id="t1", title="Track 1", artist="Artist", album="Album",
            local_path="/music/artists/Artist/Album/01 - Track 1.flac", downloaded_at="2026-01-01T00:00:00"
        )
        self.state.add_track(t1)
        self.state.add_playlist("Brand New Local", "http://example.com")
        self.state.add_track_to_playlist("Brand New Local", "t1")

        self.client.get_playlists = MagicMock(return_value=[])
        self.client.resolve_song_id = MagicMock(return_value="navi-t1")
        self.client.create_playlist = MagicMock(return_value="brand-new-remote-id")

        engine = SubsonicSyncEngine(self.state, self.client)
        summary = engine.sync_all()

        self.assertEqual(summary["pushed_to_remote"], 1)
        self.client.create_playlist.assert_called_with(name="Brand New Local", song_ids=["navi-t1"])

        pl = self.state.get_playlist("Brand New Local")
        self.assertEqual(pl.navidrome_id, "brand-new-remote-id")

    def test_helpers(self):
        self.assertEqual(_normalize_text("The 1975 - Somebody Else (Official Audio)!"), "the 1975 somebody else official audio")
        dt = _parse_iso_datetime("2026-10-14T19:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 10)
        self.assertEqual(dt.day, 14)


try:
    from starlette.testclient import TestClient
    HAS_TESTCLIENT = True
except ImportError:
    HAS_TESTCLIENT = False


@unittest.skipUnless(HAS_TESTCLIENT, "starlette/fastapi testclient not installed in current python")
class TestSubsonicServerEndpoints(unittest.TestCase):
    def setUp(self):
        import alac_rip.server as server_mod
        from alac_rip.config import Config

        self.server_mod = server_mod
        self.temp_dir = tempfile.TemporaryDirectory()
        self.music_dir = Path(self.temp_dir.name) / "music"
        self.music_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = Path(self.temp_dir.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "downloaded.db"

        self.state = StateManager(self.db_path)
        self.cfg = Config(
            music_dir=self.music_dir,
            state_dir=self.state_dir,
            alac_rip_dir=Path(self.temp_dir.name),
            integrations={
                "navidrome": {
                    "enabled": True,
                    "server_url": "http://127.0.0.1:4533",
                    "user": "testuser",
                    "token": "tok123",
                    "salt": "salt123",
                    "bidirectional_sync": True,
                }
            },
        )
        self.orig_state = server_mod.state
        self.orig_cfg = server_mod.cfg
        server_mod.state = self.state
        server_mod.cfg = self.cfg
        self.client = TestClient(server_mod.app)

    def tearDown(self):
        self.server_mod.state = self.orig_state
        self.server_mod.cfg = self.orig_cfg
        self.temp_dir.cleanup()

    def test_sync_status_endpoint(self):
        resp = self.client.get("/api/v1/integrations/navidrome/sync-status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("imported_from_remote", data)

    @patch("alac_rip.server.SubsonicSyncEngine")
    def test_trigger_sync_endpoint(self, mock_engine_cls):
        mock_instance = MagicMock()
        mock_instance.sync_all.return_value = {
            "status": "ok",
            "imported_from_remote": 2,
            "updated_local": 1,
            "pushed_to_remote": 0,
            "errors": [],
        }
        mock_engine_cls.return_value = mock_instance

        resp = self.client.post("/api/v1/integrations/navidrome/sync")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["imported_from_remote"], 2)

    def test_playlist_endpoints_expose_subsonic_fields(self):
        self.state.add_playlist("Subsonic Playlist", "https://music.apple.com/us/playlist/test/pl.123")
        self.state.link_playlist_navidrome("Subsonic Playlist", "navi-pl-99", "2026-10-14T20:00:00Z")
        self.state.touch_playlist_local_modified("Subsonic Playlist", "2026-10-14T21:00:00Z")

        resp = self.client.get("/playlists")
        self.assertEqual(resp.status_code, 200)
        pls = resp.json()
        target = next((p for p in pls if p["name"] == "Subsonic Playlist"), None)
        self.assertIsNotNone(target)
        self.assertEqual(target["navidrome_id"], "navi-pl-99")
        self.assertEqual(target["remote_changed_at"], "2026-10-14T20:00:00Z")
        self.assertEqual(target["last_local_modified"], "2026-10-14T21:00:00Z")
        self.assertNotIn("staging_folder", target)


if __name__ == "__main__":
    unittest.main()
