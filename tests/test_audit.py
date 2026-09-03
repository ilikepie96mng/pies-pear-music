import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from alac_rip.audit import (
    adopt_orphaned_files,
    audit_library,
    repair_playlists,
    verify_library_flac_integrity,
)
from alac_rip.metadata import write_tags
from alac_rip.state import Playlist, StateManager, Track


@pytest.fixture
def music_dir(tmp_path):
    d = tmp_path / "Music"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def state(tmp_path):
    return StateManager(tmp_path / "downloaded.db")


def make_flac(path: Path, title: str = "Title", artist: str = "Artist", album: str = "Album", lyrics: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1",
            "-c:a", "flac", "-y", str(path),
        ],
        check=True,
        capture_output=True,
    )
    write_tags(path, title=title, artist=artist, album=album, track_num=1, lyrics=lyrics)
    return path


def test_audit_missing_and_orphaned_files(music_dir, state):
    # 1. Add tracked file that exists
    tracked_existing = music_dir / "artists" / "Artist A" / "Album A" / "01 - Track 1.flac"
    make_flac(tracked_existing, title="Track 1", artist="Artist A", album="Album A")
    # Add .lrc sidecar and cover.jpg
    tracked_existing.with_suffix(".lrc").write_text("[00:00.00]Hello\n", encoding="utf-8")
    (tracked_existing.parent / "cover.jpg").write_bytes(b"fakecover")

    t1 = Track(
        track_id="t1",
        title="Track 1",
        artist="Artist A",
        album="Album A",
        local_path=str(tracked_existing),
        downloaded_at=datetime.now().isoformat(),
        artwork_url="http://example.com/art.jpg",
    )
    state.add_track(t1)
    state.add_playlist("Favorites", "https://music.apple.com/pl1")
    state.add_track_to_playlist("Favorites", "t1")

    # 2. Add tracked file that DOES NOT exist
    missing_path = music_dir / "artists" / "Artist B" / "Album B" / "02 - Missing.flac"
    t2 = Track(
        track_id="t2",
        title="Missing Track",
        artist="Artist B",
        album="Album B",
        local_path=str(missing_path),
        downloaded_at=datetime.now().isoformat(),
    )
    state.add_track(t2)
    state.add_track_to_playlist("Favorites", "t2")

    # 3. Create an orphaned audio file (not in state)
    orphaned_file = music_dir / "artists" / "Unknown Artist" / "Orphan Album" / "01 - Orphan.flac"
    make_flac(orphaned_file, title="Orphan", artist="Unknown Artist", album="Orphan Album")

    # Run audit
    report = audit_library(music_dir, state)

    assert report["summary"]["total_db_tracks"] == 2
    assert report["summary"]["missing_files_count"] == 1
    assert report["summary"]["orphaned_files_count"] == 1

    assert len(report["missing_files"]) == 1
    assert report["missing_files"][0]["track_id"] == "t2"
    assert "Favorites" in report["missing_files"][0]["playlists"]

    assert len(report["orphaned_files"]) == 1
    assert Path(report["orphaned_files"][0]["path"]).resolve() == orphaned_file.resolve()


def test_audit_missing_lyrics_and_art(music_dir, state):
    # Track without .lrc and without artwork_url/cover.jpg
    tracked = music_dir / "artists" / "Artist X" / "Album X" / "01 - No Art No Lyrics.flac"
    make_flac(tracked, title="No Art", artist="Artist X", album="Album X")

    t = Track(
        track_id="tx",
        title="No Art",
        artist="Artist X",
        album="Album X",
        local_path=str(tracked),
        downloaded_at=datetime.now().isoformat(),
        artwork_url=None,
    )
    state.add_track(t)

    report = audit_library(music_dir, state)
    assert report["summary"]["missing_lyrics_count"] == 1
    assert report["summary"]["missing_art_count"] == 1
    assert report["missing_lyrics"][0]["track_id"] == "tx"
    assert report["missing_art"][0]["track_id"] == "tx"


def test_repair_playlists(music_dir, state):
    state.add_playlist("Pop Hits", "https://music.apple.com/pl2")
    track_file = music_dir / "artists" / "Pop Star" / "Pop Hits" / "01 - Hit.flac"
    make_flac(track_file, title="Hit", artist="Pop Star", album="Pop Hits")

    t = Track(
        track_id="pop1",
        title="Hit",
        artist="Pop Star",
        album="Pop Hits",
        local_path=str(track_file),
        downloaded_at=datetime.now().isoformat(),
    )
    state.add_track(t)
    state.add_track_to_playlist("Pop Hits", "pop1")

    res = repair_playlists(music_dir, state)
    assert res["repaired_count"] == 1
    assert "Pop Hits" in res["playlists"]

    m3u_file = music_dir / "playlists" / "Pop Hits.m3u8"
    assert m3u_file.is_file()
    content = m3u_file.read_text(encoding="utf-8")
    assert "#EXTM3U" in content
    assert "#EXTINF:-1,Pop Star - Hit" in content
    assert str(track_file) in content


def test_adopt_orphaned_files(music_dir, state):
    orphan_file = music_dir / "artists" / "Indie" / "EP" / "01 - Song.flac"
    make_flac(orphan_file, title="Song", artist="Indie", album="EP")

    res = adopt_orphaned_files(music_dir, state)
    assert res["adopted_count"] == 1
    assert res["adopted"][0]["title"] == "Song"
    assert res["adopted"][0]["artist"] == "Indie"

    # Verify track is now tracked in state
    all_tracks = state.get_all_tracks_with_provenance()
    assert len(all_tracks) == 1
    assert all_tracks[0]["title"] == "Song"
    assert state.is_downloaded(res["adopted"][0]["track_id"])


def test_prune_missing_tracks(music_dir, state):
    t1 = Track(
        track_id="t1",
        title="Track 1",
        artist="Artist A",
        album="Album A",
        local_path="/nonexistent/path/1.flac",
        downloaded_at=datetime.now().isoformat(),
    )
    t2 = Track(
        track_id="t2",
        title="Track 2",
        artist="Artist B",
        album="Album B",
        local_path="/nonexistent/path/2.flac",
        downloaded_at=datetime.now().isoformat(),
    )
    state.add_track(t1)
    state.add_track(t2)
    state.add_playlist("Mix", "https://music.apple.com/mix")
    state.add_track_to_playlist("Mix", "t1")
    state.add_track_to_playlist("Mix", "t2")
    state.record_delisted_track("Mix", "t1", datetime.now().isoformat())

    pruned = state.prune_missing_tracks(["t1"])
    assert pruned == 1
    assert not state.is_downloaded("t1")
    assert state.is_downloaded("t2")
    assert "t1" not in state.get_delisted_track_ids("Mix")


def test_verify_library_flac_integrity(music_dir, state):
    valid_file = music_dir / "artists" / "A" / "B" / "01 - Valid.flac"
    make_flac(valid_file, title="Valid", artist="A", album="B")

    corrupt_file = music_dir / "artists" / "A" / "B" / "02 - Corrupt.flac"
    corrupt_file.write_bytes(b"fLaC\x00\x00\x00\x22" + b"\xff\x00\xaa\x55" * 64)

    t1 = Track("t1", "Valid", "A", "B", str(valid_file), datetime.now().isoformat())
    t2 = Track("t2", "Corrupt", "A", "B", str(corrupt_file), datetime.now().isoformat())
    state.add_track(t1)
    state.add_track(t2)

    res = verify_library_flac_integrity(music_dir, state)
    assert res["checked_count"] == 2
    assert res["status"] == "errors_found"
    assert len(res["corrupted"]) == 1
    assert res["corrupted"][0]["track_id"] == "t2"


def test_find_and_sweep_library_duplicates(music_dir, state):
    from alac_rip.audit import find_library_duplicates, sweep_library_duplicates

    # 1. Primary album track
    f1 = music_dir / "artists" / "Daft Punk" / "Discovery" / "01 - One More Time.flac"
    make_flac(f1, title="One More Time", artist="Daft Punk", album="Discovery")
    f1.with_suffix(".lrc").write_text("[00:01.00]One more time", encoding="utf-8")

    # 2. Duplicate single track
    f2 = music_dir / "artists" / "Daft Punk" / "One More Time - Single" / "01 - One More Time.flac"
    make_flac(f2, title="One More Time (feat. Romanthony)", artist="Daft Punk", album="One More Time - Single")
    f2.with_suffix(".lrc").write_text("[00:01.00]One more time", encoding="utf-8")

    # 3. Duplicate collision file
    f3 = music_dir / "artists" / "Daft Punk" / "Discovery" / "01 - One More Time_coll_1.flac"
    make_flac(f3, title="One More Time", artist="Daft Punk", album="Discovery")

    t1 = Track("t1", "One More Time", "Daft Punk", "Discovery", str(f1), datetime.now().isoformat())
    t2 = Track("t2", "One More Time (feat. Romanthony)", "Daft Punk", "One More Time - Single", str(f2), datetime.now().isoformat())
    t3 = Track("t3", "One More Time", "Daft Punk", "Discovery", str(f3), datetime.now().isoformat())

    state.add_track(t1)
    state.add_track(t2)
    state.add_track(t3)

    state.add_playlist("Favorites", "https://music.apple.com/pl1")
    state.add_track_to_playlist("Favorites", "t2")  # Playlist had the single version

    # Find duplicates
    dup_res = find_library_duplicates(music_dir, state)
    assert dup_res["total_groups"] == 1
    assert dup_res["total_duplicate_tracks"] == 2
    assert dup_res["total_reclaimable_bytes"] > 0
    group = dup_res["groups"][0]
    assert group["title"] == "One More Time"
    assert group["tracks"][0]["track_id"] == "t1"
    assert group["tracks"][0]["is_recommended"] is True

    # Sweep duplicates
    sweep_res = sweep_library_duplicates(music_dir, state, keep_criteria="recommended", delete_files=True, remap_playlists=True)
    assert sweep_res["status"] == "ok"
    assert sweep_res["processed_groups"] == 1
    assert sweep_res["removed_tracks_count"] == 2
    assert sweep_res["deleted_files_count"] == 2

    # Verify primary file remains, duplicates deleted
    assert f1.is_file()
    assert not f2.is_file()
    assert not f2.with_suffix(".lrc").is_file()
    assert not f3.is_file()

    # Verify database state
    assert state.is_downloaded("t1")
    assert not state.is_downloaded("t2")
    assert not state.is_downloaded("t3")

    # Verify playlist was remapped to primary t1
    pl_tracks = state.get_playlist_tracks("Favorites")
    assert len(pl_tracks) == 1
    assert pl_tracks[0].track_id == "t1"

