from pathlib import Path
from alac_rip.organizer import sanitize, track_path, cover_path, ensure_album_dir, MAX_COMPONENT_LENGTH


def test_sanitize_removes_forbidden_chars():
    assert sanitize('AC/DC') == 'AC_DC'
    assert sanitize('Artist: Name') == 'Artist_ Name'
    assert sanitize('What? * "Hello" <world> | test') == 'What_ _ _Hello_ _world_ _ test'


def test_sanitize_removes_control_characters_and_newlines():
    assert sanitize("Line1\nLine2\rLine3\tTab") == "Line1_Line2_Line3_Tab"
    assert sanitize("Null\x00Byte\x1fControl\x7fDel\x80High") == "Null_Byte_Control_Del_High"


def test_sanitize_strips_trailing_dots_and_spaces():
    assert sanitize("Album.") == "Album"
    assert sanitize("Album...") == "Album"
    assert sanitize("Artist   ") == "Artist"
    assert sanitize("Track. . .") == "Track"


def test_sanitize_preserves_apostrophe():
    assert sanitize("Guns N' Roses") == "Guns N' Roses"


def test_sanitize_strips_whitespace():
    assert sanitize('  Artist  ') == 'Artist'


def test_sanitize_blocks_path_traversal_segments():
    assert sanitize('..') == '_'
    assert sanitize('.') == '_'
    assert sanitize('...') == '_'
    assert sanitize('') == '_'
    assert sanitize('   ') == '_'
    assert sanitize(' . . . ') == '_'


def test_sanitize_windows_reserved_names():
    assert sanitize('CON') == '_CON_'
    assert sanitize('aux') == '_aux_'
    assert sanitize('NUL') == '_NUL_'
    assert sanitize('prn') == '_prn_'
    assert sanitize('COM1') == '_COM1_'
    assert sanitize('lpt9') == '_lpt9_'
    assert sanitize('con.txt') == '_con.txt_'


def test_sanitize_truncates_overlong_components():
    overlong = "A" * 300
    cleaned = sanitize(overlong)
    assert len(cleaned) == MAX_COMPONENT_LENGTH
    assert cleaned == "A" * MAX_COMPONENT_LENGTH


def test_track_path_rejects_traversal_artist_album(tmp_path):
    path = track_path(tmp_path, "..", "..", 1, "Title")
    assert path.is_relative_to(tmp_path / "artists")


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

