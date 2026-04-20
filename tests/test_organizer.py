from pathlib import Path
from alac_rip.organizer import sanitize, track_path, cover_path, ensure_album_dir


def test_sanitize_removes_forbidden_chars():
    assert sanitize('AC/DC') == 'AC_DC'
    assert sanitize('Artist: Name') == 'Artist_ Name'


def test_sanitize_preserves_apostrophe():
    assert sanitize("Guns N' Roses") == "Guns N' Roses"


def test_sanitize_strips_whitespace():
    assert sanitize('  Artist  ') == 'Artist'


def test_track_path_structure(tmp_path):
    path = track_path(tmp_path, "Queen", "A Night at the Opera", 1, "Bohemian Rhapsody")
    assert path == tmp_path / "artists" / "Queen" / "A Night at the Opera" / "01 - Bohemian Rhapsody.m4a"


def test_track_path_pads_track_number(tmp_path):
    path = track_path(tmp_path, "Artist", "Album", 9, "Track")
    assert path.name == "09 - Track.m4a"
    path2 = track_path(tmp_path, "Artist", "Album", 10, "Track")
    assert path2.name == "10 - Track.m4a"


def test_track_path_sanitizes_artist(tmp_path):
    path = track_path(tmp_path, "AC/DC", "Highway to Hell", 1, "Highway to Hell")
    assert "AC_DC" in str(path)


def test_cover_path_structure(tmp_path):
    path = cover_path(tmp_path, "Queen", "A Night at the Opera")
    assert path == tmp_path / "artists" / "Queen" / "A Night at the Opera" / "cover.jpg"


def test_ensure_album_dir_creates_directories(tmp_path):
    album_dir = ensure_album_dir(tmp_path, "Queen", "A Night at the Opera")
    assert album_dir.exists()
    assert album_dir.is_dir()
    assert album_dir == tmp_path / "artists" / "Queen" / "A Night at the Opera"


def test_ensure_album_dir_idempotent(tmp_path):
    ensure_album_dir(tmp_path, "Queen", "A Night at the Opera")
    ensure_album_dir(tmp_path, "Queen", "A Night at the Opera")  # should not raise
