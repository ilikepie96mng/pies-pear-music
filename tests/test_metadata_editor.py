import base64
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mutagen.flac import FLAC
from mutagen.mp4 import MP4, MP4Cover

from alac_rip import metadata_editor, server
from alac_rip.config import Config
from alac_rip.metadata_editor import (
    MetadataEditorError,
    batch_update_tracks,
    extract_embedded_cover,
    update_audio_tags,
)
from alac_rip.state import StateManager, Track


_TINY_JPEG = (
    b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
    b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
    b'\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a'
    b'\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\x1e!'
    b'11=36=\x1bF\x1b2;\x1b F7\x1c!!!\x1c\x1f\x1f\x1e\x1f""\x1d\xff\xc0'
    b'\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00'
    b'\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00'
    b'\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01'
    b'\x01\x00\x00?\x00\xfb\xd4P\x00\x00\x00\x1f\xff\xd9'
)


@pytest.fixture
def sample_flac(tmp_path):
    flac_path = tmp_path / "test_track.flac"
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "flac", "-y", str(flac_path),
        ],
        check=True,
        capture_output=True,
    )
    return flac_path


def test_update_audio_tags_mp4(sample_m4a):
    fields = {
        "title": "Midnight City",
        "artist": "M83",
        "album": "Hurry Up, We're Dreaming",
        "genre": "Synthwave",
        "year": "2011",
        "track_num": 5,
        "disc_num": 1,
        "lyrics": "Waiting in a car...",
    }
    res = update_audio_tags(sample_m4a, fields=fields, cover_bytes=_TINY_JPEG)
    assert res["status"] == "ok"

    mp4 = MP4(sample_m4a)
    assert mp4.tags["©nam"] == ["Midnight City"]
    assert mp4.tags["©ART"] == ["M83"]
    assert mp4.tags["©alb"] == ["Hurry Up, We're Dreaming"]
    assert mp4.tags["©gen"] == ["Synthwave"]
    assert mp4.tags["©day"] == ["2011"]
    assert mp4.tags["trkn"] == [(5, 0)]
    assert mp4.tags["disk"] == [(1, 0)]
    assert mp4.tags["©lyr"] == ["Waiting in a car..."]
    assert "covr" in mp4.tags

    # Extract embedded cover
    cover_data, mime = extract_embedded_cover(sample_m4a)
    assert cover_data == _TINY_JPEG
    assert "jpeg" in mime


def test_update_audio_tags_flac(sample_flac):
    fields = {
        "title": "Strobe",
        "artist": "deadmau5",
        "album": "For Lack of a Better Name",
        "genre": "Progressive House",
        "year": "2009",
        "track_num": 10,
        "disc_num": 1,
        "lyrics": "",
    }
    res = update_audio_tags(sample_flac, fields=fields, cover_bytes=_TINY_JPEG)
    assert res["status"] == "ok"

    flac = FLAC(sample_flac)
    assert flac["title"] == ["Strobe"]
    assert flac["artist"] == ["deadmau5"]
    assert flac["album"] == ["For Lack of a Better Name"]
    assert flac["genre"] == ["Progressive House"]
    assert flac["date"] == ["2009"]
    assert flac["tracknumber"] == ["10"]
    assert flac["discnumber"] == ["1"]
    assert len(flac.pictures) == 1

    cover_data, mime = extract_embedded_cover(sample_flac)
    assert cover_data == _TINY_JPEG


def test_batch_update_tracks_and_reorganize(tmp_path, sample_m4a):
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    db_path = tmp_path / "downloaded.db"
    state = StateManager(db_path)

    # Place track in music dir
    track_file = music_dir / "old_file.m4a"
    sample_m4a.rename(track_file)

    track_id = "trk_1"
    state.add_track(
        Track(
            track_id=track_id,
            title="Old Title",
            artist="Old Artist",
            album="Old Album",
            local_path=str(track_file),
            downloaded_at="2026-08-17T20:00:00",
        )
    )

    b64_art = base64.b64encode(_TINY_JPEG).decode("ascii")

    res = batch_update_tracks(
        state=state,
        music_dir=music_dir,
        track_ids=[track_id],
        fields={
            "artist": "New Artist",
            "album": "New Album",
            "title": "New Title",
            "genre": "Electronic",
            "track_num": 1,
        },
        cover_art_base64=b64_art,
        reorganize_files=True,
    )

    assert res["updated"] == 1
    assert len(res["errors"]) == 0

    # Verify track record updated in DB
    updated_track = state.get_track(track_id)
    assert updated_track.artist == "New Artist"
    assert updated_track.album == "New Album"
    assert updated_track.title == "New Title"
    assert Path(updated_track.local_path).is_file()
    assert "New Artist" in updated_track.local_path
    assert "New Album" in updated_track.local_path


def test_batch_tag_endpoint(tmp_path, sample_m4a, monkeypatch):
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    db_path = tmp_path / "downloaded.db"
    state = StateManager(db_path)

    track_file = music_dir / "track.m4a"
    sample_m4a.rename(track_file)

    state.add_track(
        Track(
            track_id="trk_endpoint",
            title="Test Title",
            artist="Test Artist",
            album="Test Album",
            local_path=str(track_file),
            downloaded_at="2026-08-17T20:00:00",
        )
    )

    config = Config(
        music_dir=music_dir,
        state_dir=tmp_path / "state",
        alac_rip_dir=tmp_path / "alac_rip",
    )

    monkeypatch.setattr(server, "state", state)
    monkeypatch.setattr(server, "cfg", config)

    client = TestClient(server.app)

    payload = {
        "track_ids": ["trk_endpoint"],
        "fields": {
            "genre": "Ambient",
            "year": "2024",
        },
        "reorganize_files": False,
    }

    res = client.post("/api/v1/tracks/batch-tag", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["updated"] == 1

    # Check cover extraction endpoint
    res_cover_404 = client.get("/api/v1/tracks/cover?track_id=trk_endpoint")
    # Initially no cover embedded
    assert res_cover_404.status_code in (404, 200)


@pytest.fixture
def sample_mp3(tmp_path):
    mp3_path = tmp_path / "test_track.mp3"
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "libmp3lame", "-y", str(mp3_path),
        ],
        check=True,
        capture_output=True,
    )
    return mp3_path


def test_update_audio_tags_mp3(sample_mp3):
    fields = {
        "title": "Around the World",
        "artist": "Daft Punk",
        "album": "Homework",
        "genre": "French House",
        "year": "1997",
        "track_num": 7,
        "disc_num": 1,
    }
    res = update_audio_tags(sample_mp3, fields=fields, cover_bytes=_TINY_JPEG)
    assert res["status"] == "ok"

    cover_data, mime = extract_embedded_cover(sample_mp3)
    assert cover_data == _TINY_JPEG
    assert "jpeg" in mime


def test_remove_cover_art(sample_m4a):
    update_audio_tags(sample_m4a, fields={}, cover_bytes=_TINY_JPEG)
    assert extract_embedded_cover(sample_m4a) is not None

    update_audio_tags(sample_m4a, fields={}, remove_cover=True)
    assert extract_embedded_cover(sample_m4a) is None


def test_batch_tag_invalid_base64_rejection(tmp_path, sample_m4a):
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    state = StateManager(tmp_path / "db.db")
    with pytest.raises(MetadataEditorError):
        batch_update_tracks(
            state=state,
            music_dir=music_dir,
            track_ids=["trk1"],
            fields={},
            cover_art_base64="!!!NOT_BASE_64!!!",
        )

