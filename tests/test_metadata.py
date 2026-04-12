from alac_rip.metadata import read_tags, write_tags, embed_cover_art, save_cover_file

# Minimal 1x1 white JPEG for testing cover art embedding
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


def test_write_and_read_title(sample_m4a):
    write_tags(sample_m4a, title="Bohemian Rhapsody", artist="Queen",
               album="A Night at the Opera", track_num=1, playlist_name="Mega Playlist")
    tags = read_tags(sample_m4a)
    assert tags["title"] == "Bohemian Rhapsody"


def test_write_and_read_artist(sample_m4a):
    write_tags(sample_m4a, title="Bohemian Rhapsody", artist="Queen",
               album="A Night at the Opera", track_num=1, playlist_name="Mega Playlist")
    tags = read_tags(sample_m4a)
    assert tags["artist"] == "Queen"


def test_write_and_read_album(sample_m4a):
    write_tags(sample_m4a, title="Bohemian Rhapsody", artist="Queen",
               album="A Night at the Opera", track_num=1, playlist_name="Mega Playlist")
    tags = read_tags(sample_m4a)
    assert tags["album"] == "A Night at the Opera"


def test_write_and_read_track_num(sample_m4a):
    write_tags(sample_m4a, title="Bohemian Rhapsody", artist="Queen",
               album="A Night at the Opera", track_num=1, playlist_name="Mega Playlist")
    tags = read_tags(sample_m4a)
    assert tags["track_num"] == 1


def test_embed_cover_art_does_not_raise(sample_m4a):
    embed_cover_art(sample_m4a, _TINY_JPEG)  # should not raise


def test_save_cover_file_writes_bytes(tmp_path):
    cover_bytes = b"fake-jpeg-data"
    out = tmp_path / "cover.jpg"
    save_cover_file(out, cover_bytes)
    assert out.exists()
    assert out.read_bytes() == cover_bytes
