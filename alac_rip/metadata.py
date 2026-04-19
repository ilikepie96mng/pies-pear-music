from pathlib import Path

from mutagen.flac import FLAC
from mutagen.mp4 import MP4, MP4Cover


def _is_flac(file_path: Path) -> bool:
    return file_path.suffix.lower() == ".flac"


def read_tags(file_path: Path) -> dict:
    if _is_flac(file_path):
        audio = FLAC(file_path)
        tags = audio.tags or {}
        track_info = tags.get("tracknumber", ["0"])[0]
        try:
            track_num = int(str(track_info).split("/")[0])
        except ValueError:
            track_num = 0
        artist = str(tags.get("artist", [""])[0])
        return {
            "title": str(tags.get("title", [""])[0]),
            "artist": artist,
            "album_artist": str(tags.get("albumartist", [artist])[0]),
            "album": str(tags.get("album", [""])[0]),
            "track_num": track_num,
        }
    else:
        audio = MP4(file_path)
        tags = audio.tags or {}
        track_info = tags.get("trkn", [(0, 0)])[0]
        artist = str(tags.get("©ART", [""])[0])
        return {
            "title": str(tags.get("©nam", [""])[0]),
            "artist": artist,
            "album_artist": str(tags.get("aART", [artist])[0]),
            "album": str(tags.get("©alb", [""])[0]),
            "track_num": int(track_info[0]) if track_info else 0,
        }


def write_tags(
    file_path: Path,
    title: str,
    artist: str,
    album_artist: str,
    album: str,
    track_num: int,
    playlist_name: str = "",
) -> None:
    if _is_flac(file_path):
        audio = FLAC(file_path)
        audio["title"] = title
        audio["artist"] = artist
        audio["albumartist"] = album_artist
        audio["album"] = album
        audio["tracknumber"] = str(track_num)
        audio["genre"] = playlist_name
        audio.save()
    else:
        audio = MP4(file_path)
        if audio.tags is None:
            audio.add_tags()
        audio.tags["©nam"] = [title]
        audio.tags["©ART"] = [artist]
        audio.tags["aART"] = [album_artist]
        audio.tags["©alb"] = [album]
        audio.tags["trkn"] = [(track_num, 0)]
        audio.tags["©gen"] = [playlist_name]
        audio.save()


def embed_cover_art(file_path: Path, cover_data: bytes) -> None:
    if _is_flac(file_path):
        from mutagen.flac import Picture
        import struct
        audio = FLAC(file_path)
        pic = Picture()
        pic.type = 3  # front cover
        pic.mime = "image/jpeg"
        pic.data = cover_data
        audio.add_picture(pic)
        audio.save()
    else:
        audio = MP4(file_path)
        if audio.tags is None:
            audio.add_tags()
        audio.tags["covr"] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()


def save_cover_file(cover_path: Path, cover_data: bytes) -> None:
    cover_path.write_bytes(cover_data)
