import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from alac_rip.downloader import Downloader
from alac_rip.metadata import read_tags, write_tags
from alac_rip.organizer import ensure_album_dir, track_path
from alac_rip.state import StateManager, Track


@dataclass
class SyncResult:
    new_count: int
    skipped_count: int
    error_count: int


class SyncEngine:
    def __init__(
        self,
        downloader: Downloader,
        state: StateManager,
        music_dir: Path,
        playlist_name: str,
    ):
        self.downloader = downloader
        self.state = state
        self.music_dir = music_dir
        self.playlist_name = playlist_name

    def _track_id(self, relative_path: str) -> str:
        """Derive a stable track ID from its relative path in the downloads dir."""
        return relative_path

    def sync(self, playlist_url: str) -> SyncResult:
        """
        Run a full sync for one playlist URL.

        1. Invoke downloader → get downloads_dir
        2. Walk downloads_dir for .m4a files
        3. For each file: if not in DB, move to music_dir + tag + record
        4. Return SyncResult
        """
        self.downloader.start_wrapper()
        try:
            downloads_dir = self.downloader.download_playlist(playlist_url)
        finally:
            self.downloader.stop_wrapper()

        new_count = 0
        skipped_count = 0
        error_count = 0

        for src in downloads_dir.rglob("*.m4a"):
            relative = str(src.relative_to(downloads_dir))
            track_id = self._track_id(relative)

            if self.state.is_downloaded(track_id):
                skipped_count += 1
                src.unlink()  # discard staging copy
                continue

            try:
                tags = read_tags(src)
                artist = tags["artist"] or "Unknown Artist"
                album = tags["album"] or "Unknown Album"
                title = tags["title"] or src.stem
                track_num = tags["track_num"] or 1

                dest = track_path(self.music_dir, artist, album, track_num, title)
                ensure_album_dir(self.music_dir, artist, album)
                shutil.move(str(src), dest)

                write_tags(dest, title=title, artist=artist, album=album,
                           track_num=track_num, playlist_name=self.playlist_name)

                self.state.add_track(Track(
                    track_id=track_id,
                    title=title,
                    artist=artist,
                    album=album,
                    local_path=str(dest),
                    downloaded_at=datetime.now().isoformat(),
                ))
                new_count += 1

            except Exception:
                error_count += 1

        return SyncResult(new_count=new_count, skipped_count=skipped_count, error_count=error_count)
