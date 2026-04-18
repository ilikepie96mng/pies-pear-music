import re
from pathlib import Path

# Characters forbidden in filenames on Linux and Windows (for portability)
_FORBIDDEN = re.compile(r'[<>:"/\\|?*]')


def sanitize(name: str) -> str:
    """Replace filesystem-unsafe characters with underscores and strip whitespace."""
    return _FORBIDDEN.sub("_", name).strip()


def track_path(music_dir: Path, artist: str, album: str, track_num: int, title: str) -> Path:
    """Return the canonical absolute path for a downloaded track file."""
    return (
        music_dir
        / "artists"
        / sanitize(artist)
        / sanitize(album)
        / f"{track_num:02d} - {sanitize(title)}.m4a"
    )


def cover_path(music_dir: Path, artist: str, album: str) -> Path:
    """Return the canonical path for cover.jpg in an album directory."""
    return music_dir / "artists" / sanitize(artist) / sanitize(album) / "cover.jpg"


def ensure_album_dir(music_dir: Path, artist: str, album: str) -> Path:
    """Create artists/Artist/Album directory tree if it doesn't exist. Returns the album dir path."""
    album_dir = music_dir / "artists" / sanitize(artist) / sanitize(album)
    album_dir.mkdir(parents=True, exist_ok=True)
    return album_dir
