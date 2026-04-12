from pathlib import Path

from mutagen.mp4 import MP4, MP4Cover


def read_tags(file_path: Path) -> dict:
    """Read metadata tags from an M4A file.

    Returns dict with keys: title, artist, album, track_num (int).
    Missing tags return empty string or 0.
    """
    audio = MP4(file_path)
    tags = audio.tags or {}
    track_info = tags.get("trkn", [(0, 0)])[0]
    return {
        "title": str(tags.get("©nam", [""])[0]),
        "artist": str(tags.get("©ART", [""])[0]),
        "album": str(tags.get("©alb", [""])[0]),
        "track_num": int(track_info[0]) if track_info else 0,
    }


def write_tags(
    file_path: Path,
    title: str,
    artist: str,
    album: str,
    track_num: int,
    playlist_name: str,
) -> None:
    """Write metadata tags to an M4A file. Overwrites existing tags."""
    audio = MP4(file_path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags["©nam"] = [title]
    audio.tags["©ART"] = [artist]
    audio.tags["©alb"] = [album]
    audio.tags["trkn"] = [(track_num, 0)]
    audio.tags["©gen"] = [playlist_name]
    audio.save()


def embed_cover_art(file_path: Path, cover_data: bytes) -> None:
    """Embed cover art JPEG into an M4A file, replacing any existing cover."""
    audio = MP4(file_path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags["covr"] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def save_cover_file(cover_path: Path, cover_data: bytes) -> None:
    """Write cover art bytes to a cover.jpg file on disk."""
    cover_path.write_bytes(cover_data)
