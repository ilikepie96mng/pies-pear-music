from pathlib import Path

import pytest

from alac_rip.server import _m3u_save_target, _playlist_m3u
from alac_rip.state import Track


def test_playlist_m3u_contains_metadata_and_local_file_locations():
    result = _playlist_m3u([
        Track(
            track_id="one",
            title="A title\nwith a line break",
            artist="An artist",
            album="Album",
            local_path="/music/An artist/Album/A title.m4a",
            downloaded_at="2026-01-01T00:00:00",
        ),
    ])

    assert result == (
        "#EXTM3U\n"
        "#EXTINF:-1,An artist - A title with a line break\n"
        "/music/An artist/Album/A title.m4a\n"
    )


def test_playlist_m3u_save_path_requires_an_absolute_m3u_path(tmp_path):
    target = _m3u_save_target(str(tmp_path / "playlist.m3u8"))

    assert target == tmp_path / "playlist.m3u8"
    with pytest.raises(ValueError):
        _m3u_save_target("playlist.txt")
