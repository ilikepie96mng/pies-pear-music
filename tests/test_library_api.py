import json
import subprocess
from datetime import datetime
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import alac_rip.server as server_mod
from alac_rip.metadata import write_tags
from alac_rip.server import app
from alac_rip.state import Track


@pytest.fixture
def test_setup(tmp_path, monkeypatch):
    music_dir = tmp_path / "Music"
    music_dir.mkdir(parents=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        f"music_dir: {music_dir}\n"
        f"state_dir: {state_dir}\n"
    )
    monkeypatch.setattr(server_mod, "DEFAULT_CONFIG_PATH", cfg_file)
    with TestClient(app) as c:
        yield c, music_dir, state_dir


def make_flac(path: Path, title: str = "Song", artist: str = "Band", album: str = "Record") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
            "-c:a", "flac", "-y", str(path),
        ],
        check=True,
        capture_output=True,
    )
    write_tags(path, title=title, artist=artist, album=album, track_num=1)
    return path


def test_get_library_tracks_and_stats(test_setup):
    client, music_dir, _ = test_setup

    f1 = music_dir / "artists" / "Rock" / "Album" / "01 - RockSong.flac"
    make_flac(f1, title="RockSong", artist="Rock", album="Album")

    server_mod.state.add_track(Track(
        track_id="t1",
        title="RockSong",
        artist="Rock",
        album="Album",
        local_path=str(f1),
        downloaded_at=datetime.now().isoformat(),
        artwork_url="http://art.com/1.jpg",
    ))
    server_mod.state.add_playlist("Rock Playlist", "https://music.apple.com/rock")
    server_mod.state.add_track_to_playlist("Rock Playlist", "t1")

    # GET /library/tracks
    resp = client.get("/library/tracks")
    assert resp.status_code == 200
    tracks = resp.json()
    assert len(tracks) == 1
    assert tracks[0]["title"] == "RockSong"
    assert tracks[0]["playlists"] == ["Rock Playlist"]
    assert tracks[0]["exists_on_disk"] is True
    assert tracks[0]["format"] == "FLAC"
    assert tracks[0]["file_size"] > 0

    # GET /library/stats
    resp_stats = client.get("/library/stats")
    assert resp_stats.status_code == 200
    stats = resp_stats.json()
    assert stats["total_tracks"] == 1
    assert stats["total_albums"] == 1
    assert stats["total_artists"] == 1
    assert stats["total_bytes"] > 0


def test_get_library_audit_and_repair(test_setup):
    client, music_dir, _ = test_setup

    # Create an orphan file
    orphan = music_dir / "artists" / "OrphanArtist" / "OrphanAlbum" / "01 - OrphanTrack.flac"
    make_flac(orphan, title="OrphanTrack", artist="OrphanArtist", album="OrphanAlbum")

    # Add missing track to state
    missing_path = music_dir / "artists" / "Ghost" / "Void" / "01 - Phantom.flac"
    server_mod.state.add_track(Track(
        track_id="ghost1",
        title="Phantom",
        artist="Ghost",
        album="Void",
        local_path=str(missing_path),
        downloaded_at=datetime.now().isoformat(),
    ))
    server_mod.state.add_playlist("Spooky", "https://music.apple.com/spooky")
    server_mod.state.add_track_to_playlist("Spooky", "ghost1")

    # Audit endpoint
    resp_audit = client.get("/library/audit")
    assert resp_audit.status_code == 200
    data = resp_audit.json()
    assert data["summary"]["missing_files_count"] == 1
    assert data["summary"]["orphaned_files_count"] == 1

    # Repair: prune missing
    resp_prune = client.post("/library/repair", json={"action": "prune_missing"})
    assert resp_prune.status_code == 200
    assert resp_prune.json()["pruned_count"] == 1
    assert not server_mod.state.is_downloaded("ghost1")

    # Repair: adopt orphans
    resp_adopt = client.post("/library/repair", json={"action": "adopt_orphans"})
    assert resp_adopt.status_code == 200
    assert resp_adopt.json()["adopted_count"] == 1
    all_tracks = server_mod.state.get_all_tracks_with_provenance()
    assert len(all_tracks) == 1
    assert all_tracks[0]["title"] == "OrphanTrack"

    # Repair: regenerate m3u8
    resp_m3u = client.post("/library/repair", json={"action": "regenerate_m3u8"})
    assert resp_m3u.status_code == 200
    assert "Spooky" in resp_m3u.json()["playlists"]


def test_verify_integrity_endpoint(test_setup):
    client, music_dir, _ = test_setup

    good_file = music_dir / "artists" / "Band" / "Album" / "01 - Good.flac"
    make_flac(good_file, title="Good", artist="Band", album="Album")

    server_mod.state.add_track(Track(
        track_id="good1",
        title="Good",
        artist="Band",
        album="Album",
        local_path=str(good_file),
        downloaded_at=datetime.now().isoformat(),
    ))

    resp = client.post("/library/verify-integrity", json={"limit": 10})
    assert resp.status_code == 200
    res = resp.json()
    assert res["checked_count"] == 1
    assert res["status"] == "ok"
    assert len(res["corrupted"]) == 0
