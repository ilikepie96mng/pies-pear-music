from pathlib import Path

import pytest
from fastapi import HTTPException

import alac_rip.server as server_mod
from alac_rip.config import Config
from alac_rip.state import StateManager, Track


@pytest.fixture
def library(tmp_path, monkeypatch):
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    track_path = music_dir / "artist" / "album" / "track.m4a"
    track_path.parent.mkdir(parents=True)
    track_path.touch()

    state = StateManager(tmp_path / "state.db")
    state.add_track(Track(
        track_id="track-1",
        title="Track",
        artist="Artist",
        album="Album",
        local_path=str(track_path),
        downloaded_at="2026-01-01T00:00:00",
    ))
    monkeypatch.setattr(server_mod, "cfg", Config(
        music_dir=music_dir,
        state_dir=tmp_path / "state",
        alac_rip_dir=tmp_path / "tools",
    ))
    monkeypatch.setattr(server_mod, "state", state)
    return music_dir, track_path


def test_resolve_library_file_accepts_known_track(library):
    _, track_path = library
    assert server_mod._resolve_library_file(str(track_path)) == track_path.resolve()


def test_resolve_library_file_rejects_outside_library(library, tmp_path):
    outside = tmp_path / "private.txt"
    outside.touch()

    with pytest.raises(HTTPException, match="outside") as exc_info:
        server_mod._resolve_library_file(str(outside))

    assert exc_info.value.status_code == 403


def test_resolve_library_file_rejects_unrecorded_library_file(library):
    music_dir, _ = library
    unrecorded = music_dir / "unrecorded.m4a"
    unrecorded.touch()

    with pytest.raises(HTTPException, match="known") as exc_info:
        server_mod._resolve_library_file(str(unrecorded))

    assert exc_info.value.status_code == 403
