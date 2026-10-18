import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from alac_rip.artist_sync import ArtistReleaseChecker
from alac_rip.state import StateManager, Track


class TestArtistSubscriptions(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_downloaded.db"
        self.state = StateManager(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_subscribe_and_get_artists(self):
        # 1. Subscribe to an artist
        artist = self.state.subscribe_artist(
            artist_id="12345",
            name="Daft Punk",
            service="apple_music",
            url="https://music.apple.com/us/artist/daft-punk/12345",
            artwork_url="https://example.com/daftpunk.jpg",
            auto_download=True,
            known_album_ids=["alb-1", "alb-2"],
        )
        self.assertEqual(artist.artist_id, "12345")
        self.assertEqual(artist.name, "Daft Punk")
        self.assertTrue(artist.auto_download)
        self.assertEqual(set(artist.known_album_ids), {"alb-1", "alb-2"})

        # 2. Get subscribed artist
        fetched = self.state.get_subscribed_artist("12345", service="apple_music")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Daft Punk")
        self.assertEqual(set(fetched.known_album_ids), {"alb-1", "alb-2"})

        # 3. List subscribed artists
        all_artists = self.state.get_subscribed_artists()
        self.assertEqual(len(all_artists), 1)
        self.assertEqual(all_artists[0].artist_id, "12345")

        # 4. Filter by service
        am_artists = self.state.get_subscribed_artists(service="apple_music")
        self.assertEqual(len(am_artists), 1)
        tidal_artists = self.state.get_subscribed_artists(service="tidal")
        self.assertEqual(len(tidal_artists), 0)

    def test_update_and_unsubscribe_artist(self):
        self.state.subscribe_artist(
            artist_id="99999",
            name="Justice",
            auto_download=False,
        )

        # Update auto_download
        updated = self.state.update_subscribed_artist(
            artist_id="99999",
            auto_download=True,
            known_album_ids=["alb-justice-1"],
        )
        self.assertIsNotNone(updated)
        self.assertTrue(updated.auto_download)
        self.assertEqual(set(updated.known_album_ids), {"alb-justice-1"})

        # Verify in DB
        fetched = self.state.get_subscribed_artist("99999")
        self.assertTrue(fetched.auto_download)
        self.assertEqual(set(fetched.known_album_ids), {"alb-justice-1"})

        # Unsubscribe
        ok = self.state.unsubscribe_artist("99999")
        self.assertTrue(ok)
        self.assertIsNone(self.state.get_subscribed_artist("99999"))

    def test_pending_releases_lifecycle(self):
        rel = self.state.record_pending_release(
            artist_id="12345",
            artist_name="Daft Punk",
            album_id="alb-new-1",
            title="Random Access Memories (10th Anniversary)",
            release_date="2023-05-12",
            track_count=13,
            is_single=False,
            url="https://music.apple.com/us/album/random-access-memories-10th-anniversary/alb-new-1",
            artwork_url="https://example.com/ram.jpg",
        )
        self.assertGreater(rel.id, 0)
        rel_id = rel.id

        # Duplicate record_pending_release should not create a second entry
        rel_2 = self.state.record_pending_release(
            artist_id="12345",
            artist_name="Daft Punk",
            album_id="alb-new-1",
            title="Random Access Memories (10th Anniversary)",
            release_date="2023-05-12",
            track_count=13,
            is_single=False,
            url="https://music.apple.com/us/album/random-access-memories-10th-anniversary/alb-new-1",
        )
        self.assertEqual(rel_id, rel_2.id)

        # Retrieve available pending releases
        available = self.state.get_pending_releases(status="available")
        self.assertEqual(len(available), 1)
        self.assertEqual(available[0].album_id, "alb-new-1")
        self.assertEqual(available[0].title, "Random Access Memories (10th Anniversary)")

        # Update status to downloaded
        ok = self.state.update_pending_release_status(rel_id, status="downloaded")
        self.assertTrue(ok)

        available_after = self.state.get_pending_releases(status="available")
        self.assertEqual(len(available_after), 0)

        downloaded = self.state.get_pending_releases(status="downloaded")
        self.assertEqual(len(downloaded), 1)

    def test_has_album_in_library(self):
        # Insert tracks into the library
        self.state.add_track(
            Track(
                track_id="trk-1",
                title="Get Lucky",
                artist="Daft Punk feat. Pharrell Williams",
                album="Random Access Memories",
                local_path="/music/Daft Punk/Random Access Memories/01 Get Lucky.m4a",
                downloaded_at="2024-01-01T00:00:00",
                am_track_id="123456",
            )
        )
        self.state.add_track(
            Track(
                track_id="trk-2",
                title="Alive",
                artist="ReoNa",
                album="Alive",
                local_path="/music/artists/ReoNa/Alive/01 - Alive.m4a",
                downloaded_at="2024-01-01T00:00:00",
            )
        )

        # 1. Exact match
        self.assertTrue(self.state.has_album_in_library("Daft Punk", "Random Access Memories"))
        # 2. Case-insensitive
        self.assertTrue(self.state.has_album_in_library("daft punk", "random access memories"))
        # 3. Single suffix normalization: catalog "Alive - Single" matches library "Alive"
        self.assertTrue(self.state.has_album_in_library("ReoNa", "Alive - Single"))
        # 4. EP / Deluxe edition normalization
        self.assertTrue(self.state.has_album_in_library("Daft Punk", "Random Access Memories (10th Anniversary Edition)"))
        # 5. Single matched by track title
        self.assertTrue(self.state.has_album_in_library("Daft Punk", "Get Lucky - Single", is_single=True))
        # 6. Non-existent album
        self.assertFalse(self.state.has_album_in_library("Daft Punk", "Homework"))
        self.assertFalse(self.state.has_album_in_library("The Weeknd", "Random Access Memories"))

        # 7. Filesystem check
        music_dir = Path(self.temp_dir.name) / "music"
        alb_dir = music_dir / "artists" / "ReoNa" / "unknown"
        alb_dir.mkdir(parents=True)
        (alb_dir / "01 - unknown.flac").touch()
        self.assertTrue(self.state.has_album_in_library("ReoNa", "unknown", music_dir=music_dir))


class TestArtistReleaseChecker(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_downloaded.db"
        self.state = StateManager(self.db_path)
        self.queue_wake = MagicMock()
        self.broadcast_event = MagicMock()
        self.checker = ArtistReleaseChecker(
            state=self.state,
            storefront="us",
            on_queue_wake=self.queue_wake,
            on_broadcast_event=self.broadcast_event,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("alac_rip.artist_sync._fetch_apple_music_artist_albums")
    def test_check_artist_no_new_releases(self, mock_fetch):
        # Artist already knows alb-1 and alb-2
        artist = self.state.subscribe_artist(
            artist_id="art-100",
            name="Kavinsky",
            auto_download=False,
            known_album_ids=["alb-1", "alb-2"],
        )

        mock_fetch.return_value = (
            "Kavinsky",
            "https://music.apple.com/us/artist/kavinsky/art-100",
            "https://example.com/kavinsky.jpg",
            [
                {"id": "alb-1", "title": "OutRun", "artist": "Kavinsky", "url": "https://example.com/1"},
                {"id": "alb-2", "title": "Reborn", "artist": "Kavinsky", "url": "https://example.com/2"},
            ]
        )

        result = self.checker.check_artist(artist)
        self.assertEqual(result["new_releases_count"], 0)
        self.assertEqual(result["enqueued_count"], 0)
        self.assertEqual(len(result["new_releases"]), 0)

        # Subscribed artist last_checked was updated
        updated_artist = self.state.get_subscribed_artist("art-100")
        self.assertIsNotNone(updated_artist.last_checked)

    @patch("alac_rip.artist_sync._fetch_apple_music_artist_albums")
    def test_check_artist_with_pending_release(self, mock_fetch):
        # Auto-download = False -> should store in pending releases
        artist = self.state.subscribe_artist(
            artist_id="art-100",
            name="Kavinsky",
            auto_download=False,
            known_album_ids=["alb-1"],
        )

        mock_fetch.return_value = (
            "Kavinsky",
            "https://music.apple.com/us/artist/kavinsky/art-100",
            "https://example.com/kavinsky.jpg",
            [
                {"id": "alb-1", "title": "OutRun", "artist": "Kavinsky", "url": "https://example.com/1"},
                {"id": "alb-new-2", "title": "Nightcall EP", "artist": "Kavinsky", "url": "https://example.com/2", "is_single": True, "release_date": "2024-01-01"},
            ]
        )

        result = self.checker.check_artist(artist)
        self.assertEqual(result["new_releases_count"], 1)
        self.assertEqual(result["enqueued_count"], 0)
        self.assertEqual(result["new_releases"][0]["album_id"], "alb-new-2")

        # Verified in pending_artist_releases table
        pending = self.state.get_pending_releases(status="available")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].album_id, "alb-new-2")
        self.assertEqual(pending[0].title, "Nightcall EP")

        # Known albums now includes alb-new-2
        updated_artist = self.state.get_subscribed_artist("art-100")
        self.assertIn("alb-new-2", updated_artist.known_album_ids)

    @patch("alac_rip.artist_sync._fetch_apple_music_artist_albums")
    def test_check_artist_with_auto_download(self, mock_fetch):
        # Auto-download = True -> should enqueue to download queue
        artist = self.state.subscribe_artist(
            artist_id="art-100",
            name="Kavinsky",
            auto_download=True,
            known_album_ids=["alb-1"],
        )

        mock_fetch.return_value = (
            "Kavinsky",
            "https://music.apple.com/us/artist/kavinsky/art-100",
            "https://example.com/kavinsky.jpg",
            [
                {"id": "alb-1", "title": "OutRun", "artist": "Kavinsky", "url": "https://example.com/1"},
                {"id": "alb-new-3", "title": "Zenith", "artist": "Kavinsky", "url": "https://example.com/3", "is_single": False},
            ]
        )

        result = self.checker.check_artist(artist)
        self.assertEqual(result["new_releases_count"], 1)
        self.assertEqual(result["enqueued_count"], 1)
        self.assertEqual(len(result["enqueued_job_ids"]), 1)

        # Queue wake should have been called
        self.queue_wake.assert_called()

        # Job in queue
        jobs = self.state.get_queue_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Zenith (New)")
        self.assertEqual(jobs[0]["artist"], "Kavinsky")

    @patch("alac_rip.artist_sync._fetch_apple_music_artist_albums")
    def test_check_artist_skips_library_existing_album(self, mock_fetch):
        # If album is already downloaded in library, do not flag as new release
        self.state.add_track(
            Track(
                track_id="trk-outrun-1",
                title="Nightcall",
                artist="Kavinsky",
                album="OutRun",
                local_path="/music/Kavinsky/OutRun/01 Nightcall.m4a",
                downloaded_at="2024-01-01T00:00:00",
            )
        )

        artist = self.state.subscribe_artist(
            artist_id="art-100",
            name="Kavinsky",
            auto_download=True,
            known_album_ids=[],  # Knows nothing in state table initially
        )

        mock_fetch.return_value = (
            "Kavinsky",
            "https://music.apple.com/us/artist/kavinsky/art-100",
            "https://example.com/kavinsky.jpg",
            [
                {"id": "alb-outrun-id", "title": "OutRun", "artist": "Kavinsky", "url": "https://example.com/outrun"},
            ]
        )

        result = self.checker.check_artist(artist)
        # Should detect that OutRun is already in the library, add to known IDs, but not enqueue
        self.assertEqual(result["new_releases_count"], 0)
        self.assertEqual(result["enqueued_count"], 0)

    @patch("alac_rip.artist_sync._fetch_tidal_artist_albums")
    def test_check_tidal_artist_with_auto_download(self, mock_fetch):
        # Create checker with mock tidal client
        mock_tidal_client = MagicMock()
        tidal_checker = ArtistReleaseChecker(
            state=self.state,
            storefront="us",
            on_queue_wake=self.queue_wake,
            on_broadcast_event=self.broadcast_event,
            tidal_client=mock_tidal_client,
        )

        artist = self.state.subscribe_artist(
            artist_id="tidal:artist:12345",
            name="Daft Punk",
            service="tidal",
            auto_download=True,
            known_album_ids=["tidal:album:111"],
        )

        mock_fetch.return_value = (
            "Daft Punk",
            "https://tidal.com/browse/artist/12345",
            "https://resources.tidal.com/images/daftpunk/1280x1280.jpg",
            [
                {"id": "tidal:album:111", "title": "Homework", "artist": "Daft Punk", "url": "https://tidal.com/browse/album/111", "provider": "tidal"},
                {"id": "tidal:album:222", "title": "Discovery", "artist": "Daft Punk", "url": "https://tidal.com/browse/album/222", "provider": "tidal"},
            ],
        )

        result = tidal_checker.check_artist(artist)
        self.assertEqual(result["new_releases_count"], 1)
        self.assertEqual(result["enqueued_count"], 1)
        self.assertEqual(len(result["enqueued_job_ids"]), 1)

        # Queue wake should have been called
        self.queue_wake.assert_called()

        # Job in queue should be FLAC format
        jobs = self.state.get_queue_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Discovery (New)")
        self.assertEqual(jobs[0]["artist"], "Daft Punk")
        self.assertEqual(jobs[0]["format"], "FLAC")


from fastapi.testclient import TestClient
from alac_rip import server


class TestArtistServerEndpoints(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_downloaded.db"
        self.state = StateManager(self.db_path)
        self.orig_state = server.state
        server.state = self.state
        self.client = TestClient(server.app)

    def tearDown(self):
        server.state = self.orig_state
        self.temp_dir.cleanup()

    @patch("alac_rip.artist_sync._fetch_apple_music_artist_albums")
    def test_subscribe_and_list_endpoints(self, mock_fetch):
        mock_fetch.return_value = ("Daft Punk", "https://example.com/daftpunk", None, [])

        # 1. Subscribe
        sub_res = self.client.post(
            "/api/v1/artists/subscribe",
            json={
                "artist_id": "art-1",
                "name": "Daft Punk",
                "service": "apple_music",
                "auto_download": True,
            },
        )
        self.assertEqual(sub_res.status_code, 201)
        data = sub_res.json()
        self.assertEqual(data["artist"]["artist_id"], "art-1")
        self.assertEqual(data["artist"]["name"], "Daft Punk")

        # 2. Get subscriptions
        list_res = self.client.get("/api/v1/artists/subscriptions")
        self.assertEqual(list_res.status_code, 200)
        subs = list_res.json()
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["artist_id"], "art-1")

        # 3. Patch subscription
        patch_res = self.client.patch(
            "/api/v1/artists/subscriptions/art-1",
            json={"auto_download": False},
        )
        self.assertEqual(patch_res.status_code, 200)
        self.assertFalse(patch_res.json()["auto_download"])

        # 4. Delete subscription
        del_res = self.client.delete("/api/v1/artists/subscriptions/art-1")
        self.assertEqual(del_res.status_code, 204)

        # 5. Verify deleted
        list_res_after = self.client.get("/api/v1/artists/subscriptions")
        self.assertEqual(list_res_after.status_code, 200)
        self.assertEqual(len(list_res_after.json()), 0)

    def test_pending_releases_endpoints(self):
        rel = self.state.record_pending_release(
            artist_id="art-2",
            artist_name="Justice",
            album_id="alb-hyperdrama",
            title="Hyperdrama",
            release_date="2024-04-26",
            track_count=13,
            is_single=False,
            url="https://music.apple.com/us/album/hyperdrama/alb-hyperdrama",
        )

        # 1. Get pending releases
        get_res = self.client.get("/api/v1/artists/pending-releases")
        self.assertEqual(get_res.status_code, 200)
        pending = get_res.json()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["title"], "Hyperdrama")

        # 2. Dismiss release
        dismiss_res = self.client.post(f"/api/v1/artists/pending-releases/{rel.id}/dismiss")
        self.assertEqual(dismiss_res.status_code, 200)

        # 3. Verify dismissed
        get_res_after = self.client.get("/api/v1/artists/pending-releases")
        self.assertEqual(get_res_after.status_code, 200)
        self.assertEqual(len(get_res_after.json()), 0)

    def test_download_pending_release_endpoint_tidal(self):
        rel = self.state.record_pending_release(
            artist_id="tidal:artist:12345",
            artist_name="Daft Punk",
            album_id="tidal:album:222",
            title="Discovery",
            release_date="2001-03-12",
            track_count=14,
            is_single=False,
            url="https://tidal.com/browse/album/222",
        )

        # 1. Download pending release
        dl_res = self.client.post(f"/api/v1/artists/pending-releases/{rel.id}/download")
        self.assertEqual(dl_res.status_code, 200)
        data = dl_res.json()
        self.assertEqual(data["queued"], 1)
        job = [j for j in self.state.get_queue_jobs() if j["id"] == data["job_id"]][0]
        self.assertEqual(job["format"], "FLAC")

        # 2. Check pending releases now marked downloaded
        get_res = self.client.get("/api/v1/artists/pending-releases?status=available")
        self.assertEqual(len(get_res.json()), 0)

    def test_dismiss_all_pending_releases(self):
        self.state.record_pending_release("a1", "Artist 1", "alb1", "Title 1")
        self.state.record_pending_release("a2", "Artist 2", "alb2", "Title 2")
        self.assertEqual(len(self.state.get_pending_releases(status="available")), 2)

        res = self.client.post("/api/v1/artists/pending-releases/dismiss-all")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(self.state.get_pending_releases(status="available")), 0)

    def test_pending_releases_auto_cleanup(self):
        # Record pending release for an album
        rel = self.state.record_pending_release("art1", "ReoNa", "alb_alive", "Alive - Single", is_single=True)
        # Add the track to library
        self.state.add_track(
            Track(
                track_id="trk-reona-1",
                title="Alive",
                artist="ReoNa",
                album="Alive",
                local_path="/music/Alive.m4a",
                downloaded_at="2024-01-01T00:00:00",
            )
        )

        # Calling GET /api/v1/artists/pending-releases should auto-clean it since it's already in library
        res = self.client.get("/api/v1/artists/pending-releases")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()), 0)


if __name__ == "__main__":
    unittest.main()

