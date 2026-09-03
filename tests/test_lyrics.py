import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from alac_rip.am_api import AMApiError, _parse_ttml_time, fetch_lyrics, ttml_to_lrc
from alac_rip.metadata import read_tags, write_tags
from alac_rip.state import StateManager
from alac_rip.sync import SyncEngine


@pytest.fixture
def music_dir(tmp_path):
    d = tmp_path / "Music"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def staging_dir(tmp_path):
    d = tmp_path / "staging"
    d.mkdir()
    return d


@pytest.fixture
def sync_state(tmp_path):
    return StateManager(tmp_path / "downloaded.db")


def make_sample_flac(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
            "-c:a", "flac", "-y", str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def make_sample_m4a(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
            "-c:a", "alac", "-y", str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


# ── TTML Parsing Tests ────────────────────────────────────────────────────────

def test_parse_ttml_time():
    assert _parse_ttml_time("00:01.234") == "[00:01.23]"
    assert _parse_ttml_time("01:23.456") == "[01:23.46]"
    assert _parse_ttml_time("00:02:15.500") == "[02:15.50]"
    assert _parse_ttml_time("75.5s") == "[01:15.50]"
    assert _parse_ttml_time("1500ms") == "[00:01.50]"
    assert _parse_ttml_time("invalid") is None
    assert _parse_ttml_time("") is None


def test_ttml_to_lrc_standard():
    ttml = """<?xml version="1.0" encoding="utf-8"?>
    <tt xmlns="http://www.w3.org/ns/ttml">
      <body>
        <div>
          <p begin="00:01.200" end="00:04.500">Is this the real life?</p>
          <p begin="00:04.800" end="00:08.100">Is this just fantasy?</p>
          <p begin="00:08.500" end="00:12.000">Caught in a landslide</p>
        </div>
      </body>
    </tt>
    """
    lrc = ttml_to_lrc(ttml)
    lines = lrc.splitlines()
    assert len(lines) == 3
    assert lines[0] == "[00:01.20] Is this the real life?"
    assert lines[1] == "[00:04.80] Is this just fantasy?"
    assert lines[2] == "[00:08.50] Caught in a landslide"


def test_ttml_to_lrc_with_spans():
    ttml = """<tt xmlns="http://www.w3.org/ns/ttml">
      <body>
        <div>
          <p begin="00:10.500">
            <span begin="00:10.500">No </span>
            <span begin="00:11.000">escape </span>
            <span begin="00:11.500">from reality</span>
          </p>
        </div>
      </body>
    </tt>
    """
    lrc = ttml_to_lrc(ttml)
    assert lrc == "[00:10.50] No escape from reality"


def test_ttml_to_lrc_fallback_plain_text():
    raw_lyrics = "Line one\nLine two\nLine three"
    assert ttml_to_lrc(raw_lyrics) == raw_lyrics


# ── AM API fetch_lyrics Tests ────────────────────────────────────────────────

def test_fetch_lyrics_success():
    fake_ttml = """<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="00:02.000">Hello World</p></div></body></tt>"""
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "data": [
            {
                "id": "123",
                "type": "lyrics",
                "attributes": {
                    "ttml": fake_ttml,
                },
            }
        ]
    }

    with patch("requests.get", return_value=fake_response):
        lrc = fetch_lyrics("123456", "fake_token")
        assert lrc == "[00:02.00] Hello World"


def test_fetch_lyrics_not_found_404():
    fake_response = MagicMock()
    fake_response.status_code = 404

    with patch("requests.get", return_value=fake_response):
        lrc = fetch_lyrics("123456", "fake_token")
        assert lrc is None


def test_fetch_lyrics_error_500():
    fake_response = MagicMock()
    fake_response.status_code = 500

    with patch("requests.get", return_value=fake_response):
        with pytest.raises(AMApiError):
            fetch_lyrics("123456", "fake_token")


def test_fetch_lyrics_network_failure():
    with patch("requests.get", side_effect=requests.RequestException("connection failed")):
        with pytest.raises(AMApiError):
            fetch_lyrics("123456", "fake_token")


# ── Metadata Tag Embedding Tests ─────────────────────────────────────────────

def test_flac_lyrics_write_and_read(tmp_path):
    flac_file = make_sample_flac(tmp_path / "test.flac")
    lyrics_content = "[00:01.00] Line one\n[00:05.00] Line two"

    write_tags(
        flac_file,
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        track_num=1,
        lyrics=lyrics_content,
    )

    tags = read_tags(flac_file)
    assert tags["title"] == "Test Song"
    assert tags["lyrics"] == lyrics_content


def test_m4a_lyrics_write_and_read(tmp_path):
    m4a_file = make_sample_m4a(tmp_path / "test.m4a")
    lyrics_content = "[00:01.00] Line one\n[00:05.00] Line two"

    write_tags(
        m4a_file,
        title="Test Song",
        artist="Test Artist",
        album="Test Album",
        track_num=1,
        lyrics=lyrics_content,
    )

    tags = read_tags(m4a_file)
    assert tags["title"] == "Test Song"
    assert tags["lyrics"] == lyrics_content


# ── Sync Engine Sidecar and Tag Integration ──────────────────────────────────

def test_sync_extracts_lrc_sidecar_and_embeds_tags(music_dir, staging_dir, sync_state):
    track_src = staging_dir / "Artist" / "Album" / "01 - Bohemian Rhapsody.flac"
    make_sample_flac(track_src)
    write_tags(track_src, title="Bohemian Rhapsody", artist="Queen", album="A Night at the Opera", track_num=1)

    lrc_content = "[00:01.00] Is this the real life?\n[00:04.00] Is this just fantasy?"
    lrc_src = staging_dir / "Artist" / "Album" / "01 - Bohemian Rhapsody.lrc"
    lrc_src.write_text(lrc_content, encoding="utf-8")

    engine = SyncEngine(state=sync_state, music_dir=music_dir, playlist_name="Rock Classics")
    result = engine.sync(staging_dir)

    assert result.new_count == 1
    assert result.error_count == 0

    dest_flac = music_dir / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.flac"
    dest_lrc = music_dir / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.lrc"

    assert dest_flac.exists()
    assert dest_lrc.exists()
    assert dest_lrc.read_text(encoding="utf-8") == lrc_content

    # Verify Vorbis tags embedded in destination FLAC
    dest_tags = read_tags(dest_flac)
    assert dest_tags["lyrics"] == lrc_content
