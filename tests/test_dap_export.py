import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alac_rip.dap_export import (
    DapExportError,
    export_dap_playlist,
    validate_dap_target_dir,
)
from alac_rip.metadata import write_tags
from alac_rip.server import app
from alac_rip.state import StateManager, Track


@pytest.fixture
def music_dir(tmp_path):
    d = tmp_path / "Music"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def export_target_dir(tmp_path):
    d = tmp_path / "DAP_SDCard"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def state(tmp_path):
    return StateManager(tmp_path / "downloaded.db")


def create_flac_track(path: Path, title: str, artist: str, album: str, track_num: int, lrc: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
            "-c:a", "flac", "-y", str(path),
        ],
        check=True,
        capture_output=True,
    )
    write_tags(path, title=title, artist=artist, album=album, track_num=track_num, lyrics=lrc)
    if lrc:
        path.with_suffix(".lrc").write_text(lrc, encoding="utf-8")
    return path


def test_validate_dap_target_dir(tmp_path):
    valid_dir = tmp_path / "exports"
    resolved = validate_dap_target_dir(valid_dir)
    assert resolved == valid_dir.resolve()

    with pytest.raises(DapExportError):
        validate_dap_target_dir(Path("/"))


def test_export_dap_playlist_opus(music_dir, export_target_dir, state):
    track1_path = music_dir / "artists" / "Queen" / "Opera" / "01 - Bohemian Rhapsody.flac"
    create_flac_track(track1_path, "Bohemian Rhapsody", "Queen", "Opera", 1, lrc="[00:01.00] Mama")
    track2_path = music_dir / "artists" / "Queen" / "Opera" / "02 - Love of My Life.flac"
    create_flac_track(track2_path, "Love of My Life", "Queen", "Opera", 2)

    state.add_track(Track("t1", "Bohemian Rhapsody", "Queen", "Opera", str(track1_path), datetime.now().isoformat()))
    state.add_track(Track("t2", "Love of My Life", "Queen", "Opera", str(track2_path), datetime.now().isoformat()))
    state.add_playlist("Road Trip", "https://music.apple.com/us/playlist/road-trip/pl.123")
    state.add_track_to_playlist("Road Trip", "t1")
    state.add_track_to_playlist("Road Trip", "t2")

    result = export_dap_playlist(
        music_dir=music_dir,
        playlist_name="Road Trip",
        target_dir=export_target_dir,
        format="opus",
        bitrate="160k",
        state=state,
    )

    assert result["status"] == "ok"
    assert result["exported_count"] == 2
    assert result["error_count"] == 0

    export_dir = export_target_dir / "Road Trip"
    assert export_dir.is_dir()

    exported_opus_1 = export_dir / "01 - Bohemian Rhapsody.opus"
    exported_opus_2 = export_dir / "02 - Love of My Life.opus"
    assert exported_opus_1.exists()
    assert exported_opus_2.exists()

    # Check that .lrc sidecar was copied for track 1
    exported_lrc_1 = export_dir / "01 - Bohemian Rhapsody.lrc"
    assert exported_lrc_1.exists()
    assert exported_lrc_1.read_text(encoding="utf-8") == "[00:01.00] Mama"

    # Check relative M3U playlists
    inner_m3u = export_dir / "Road Trip.m3u"
    assert inner_m3u.exists()
    inner_content = inner_m3u.read_text(encoding="utf-8")
    assert "01 - Bohemian Rhapsody.opus" in inner_content
    assert "02 - Love of My Life.opus" in inner_content

    outer_m3u = export_target_dir / "Road Trip.m3u"
    assert outer_m3u.exists()
    outer_content = outer_m3u.read_text(encoding="utf-8")
    assert "Road Trip/01 - Bohemian Rhapsody.opus" in outer_content


def test_export_dap_playlist_aac(music_dir, export_target_dir, state):
    track1_path = music_dir / "artists" / "Queen" / "Opera" / "01 - Bohemian Rhapsody.flac"
    create_flac_track(track1_path, "Bohemian Rhapsody", "Queen", "Opera", 1)

    state.add_track(Track("t1", "Bohemian Rhapsody", "Queen", "Opera", str(track1_path), datetime.now().isoformat()))
    state.add_playlist("AAC Playlist", "https://music.apple.com/us/playlist/aac/pl.456")
    state.add_track_to_playlist("AAC Playlist", "t1")

    result = export_dap_playlist(
        music_dir=music_dir,
        playlist_name="AAC Playlist",
        target_dir=export_target_dir,
        format="aac",
        bitrate="256k",
        state=state,
    )

    assert result["status"] == "ok"
    assert result["exported_count"] == 1
    exported_m4a = export_target_dir / "AAC Playlist" / "01 - Bohemian Rhapsody.m4a"
    assert exported_m4a.exists()


def test_export_dap_playlist_invalid_format(music_dir, export_target_dir, state):
    with pytest.raises(DapExportError) as exc_info:
        export_dap_playlist(
            music_dir=music_dir,
            playlist_name="Invalid Format Test",
            target_dir=export_target_dir,
            format="mp3_unsupported",
            state=state,
        )
    assert "Unsupported format" in str(exc_info.value)


def test_export_dap_empty_playlist(music_dir, export_target_dir, state):
    state.add_playlist("Empty", "https://music.apple.com/us/playlist/empty/pl.789")
    with pytest.raises(DapExportError) as exc_info:
        export_dap_playlist(
            music_dir=music_dir,
            playlist_name="Empty",
            target_dir=export_target_dir,
            state=state,
        )
    assert "has no tracks" in str(exc_info.value)


def test_export_dap_playlist_invalid_bitrate(music_dir, export_target_dir, state):
    track1_path = music_dir / "artists" / "Queen" / "Opera" / "01 - Song.flac"
    create_flac_track(track1_path, "Song", "Queen", "Opera", 1)
    state.add_track(Track("t1", "Song", "Queen", "Opera", str(track1_path), datetime.now().isoformat()))
    state.add_playlist("Bitrate Test", "https://music.apple.com/us/playlist/b/pl.123")
    state.add_track_to_playlist("Bitrate Test", "t1")

    with pytest.raises(DapExportError) as exc_info:
        export_dap_playlist(
            music_dir=music_dir,
            playlist_name="Bitrate Test",
            target_dir=export_target_dir,
            format="opus",
            bitrate="-an invalid",
            state=state,
        )
    assert "Invalid bitrate" in str(exc_info.value)


# ── Server Endpoint Tests ───────────────────────────────────────────────────

def test_server_dap_export_endpoint(tmp_path, monkeypatch):
    music_dir = tmp_path / "Music"
    music_dir.mkdir(parents=True)
    target_dir = tmp_path / "ExportDAP"
    target_dir.mkdir(parents=True)

    test_state = StateManager(tmp_path / "downloaded.db")
    track_file = create_flac_track(
        music_dir / "artists" / "Queen" / "Opera" / "01 - Bohemian Rhapsody.flac",
        "Bohemian Rhapsody", "Queen", "Opera", 1,
    )
    test_state.add_track(Track("t1", "Bohemian Rhapsody", "Queen", "Opera", str(track_file), datetime.now().isoformat()))
    test_state.add_playlist("Endpoint Test", "https://music.apple.com/us/playlist/test/pl.999")
    test_state.add_track_to_playlist("Endpoint Test", "t1")

    from alac_rip.config import Config
    mock_cfg = Config(
        music_dir=music_dir,
        state_dir=tmp_path / ".state",
        alac_rip_dir=tmp_path / "alac",
    )

    import alac_rip.server as srv
    monkeypatch.setattr(srv, "cfg", mock_cfg)
    monkeypatch.setattr(srv, "state", test_state)

    client = TestClient(app)

    # 1. Success case
    response = client.post(
        "/export/dap",
        json={
            "playlist_name": "Endpoint Test",
            "target_dir": str(target_dir),
            "format": "opus",
            "bitrate": "160k",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["exported_count"] == 1

    # 2. Non-existent / empty playlist -> 404
    resp_404 = client.post(
        "/export/dap",
        json={
            "playlist_name": "NonExistent",
            "target_dir": str(target_dir),
            "format": "opus",
        },
    )
    assert resp_404.status_code == 404

    # 3. Invalid format -> 422
    resp_422 = client.post(
        "/export/dap",
        json={
            "playlist_name": "Endpoint Test",
            "target_dir": str(target_dir),
            "format": "flv",
        },
    )
    assert resp_422.status_code == 422

    # 4. Relative target_dir -> 422
    resp_rel = client.post(
        "/export/dap",
        json={
            "playlist_name": "Endpoint Test",
            "target_dir": "relative/path",
            "format": "opus",
        },
    )
    assert resp_rel.status_code == 422
