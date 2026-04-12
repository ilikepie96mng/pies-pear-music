import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from alac_rip.downloader import Downloader
from alac_rip.metadata import read_tags, write_tags
from alac_rip.organizer import ensure_album_dir, sanitize, track_path
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

    def _write_m3u8(self) -> None:
        """Write/update the M3U8 playlist file for all tracks in this playlist."""
        tracks = self.state.get_playlist_tracks(self.playlist_name)
        if not tracks:
            return

        playlists_dir = self.music_dir / "Playlists"
        playlists_dir.mkdir(exist_ok=True)

        m3u8_path = playlists_dir / f"{sanitize(self.playlist_name)}.m3u8"

        lines = ["#EXTM3U", ""]
        for track in tracks:
            lines.append(f"#EXTINF:-1,{track.artist} - {track.title}")
            lines.append(track.local_path)

        m3u8_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def sync(self, playlist_url: str) -> SyncResult:
        """
        Run a full sync for one playlist URL.

        1. Invoke downloader → get downloads_dir
        2. Walk downloads_dir for .m4a files
        3. For each file: move to music_dir + tag + record (new), or skip (seen)
        4. Record playlist membership for every track encountered
        5. Write/update the M3U8 playlist file
        6. Return SyncResult
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
                # Still record that this track belongs to this playlist
                self.state.add_track_to_playlist(self.playlist_name, track_id)
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
                self.state.add_track_to_playlist(self.playlist_name, track_id)
                new_count += 1

            except Exception:
                error_count += 1

        self._write_m3u8()

        return SyncResult(new_count=new_count, skipped_count=skipped_count, error_count=error_count)
