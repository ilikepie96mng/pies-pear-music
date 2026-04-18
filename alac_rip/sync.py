import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from alac_rip.metadata import read_tags, write_tags
from alac_rip.organizer import ensure_album_dir, sanitize, track_path
from alac_rip.state import StateManager, Track

LogCallback = Callable[[str, str], None]  # (message, phase)


@dataclass
class SyncResult:
    new_count: int
    skipped_count: int
    error_count: int


class SyncEngine:
    def __init__(
        self,
        state: StateManager,
        music_dir: Path,
        playlist_name: str,
        on_log: Optional[LogCallback] = None,
    ):
        self.state = state
        self.music_dir = music_dir
        self.playlist_name = playlist_name
        self._on_log: LogCallback = on_log or (lambda msg, phase: None)

    def _log(self, msg: str, phase: str = "processing") -> None:
        self._on_log(msg, phase)

    def _track_id(self, relative_path: str) -> str:
        return relative_path

    def _write_m3u8(self) -> None:
        tracks = self.state.get_playlist_tracks(self.playlist_name)
        if not tracks:
            return

        playlists_dir = self.music_dir / "playlists"
        playlists_dir.mkdir(exist_ok=True)

        m3u8_path = playlists_dir / f"{sanitize(self.playlist_name)}.m3u8"

        lines = ["#EXTM3U", ""]
        for track in tracks:
            lines.append(f"#EXTINF:-1,{track.artist} - {track.title}")
            lines.append(track.local_path)

        m3u8_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def sync(self, staging_dir: Path) -> SyncResult:
        """
        Process .m4a files from staging_dir into music_dir.

        Moves each file to its canonical artists/Artist/Album path, tags it,
        records it in state, and updates the M3U8 playlist file.
        """
        m4a_files = list(staging_dir.rglob("*.m4a"))
        total = len(m4a_files)
        self._log(f"Processing {total} file(s) from staging...", "processing")

        new_count = 0
        skipped_count = 0
        error_count = 0

        for i, src in enumerate(m4a_files, 1):
            relative = str(src.relative_to(staging_dir))
            track_id = self._track_id(relative)

            if self.state.is_downloaded(track_id):
                skipped_count += 1
                src.unlink()
                self.state.add_track_to_playlist(self.playlist_name, track_id)
                self._log(f"[{i}/{total}] skipped (already downloaded): {src.name}", "processing")
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
                self._log(f"[{i}/{total}] added: {artist} — {title}", "processing")

            except Exception as exc:
                error_count += 1
                self._log(f"[{i}/{total}] error processing {src.name}: {exc}", "processing")

        self._write_m3u8()
        self._log(
            f"Sync complete: {new_count} new, {skipped_count} skipped, {error_count} errors",
            "done",
        )

        return SyncResult(new_count=new_count, skipped_count=skipped_count, error_count=error_count)
