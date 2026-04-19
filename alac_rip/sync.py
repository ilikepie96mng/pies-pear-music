import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from mutagen.mp4 import MP4

from alac_rip.metadata import embed_cover_art, read_tags, save_cover_file, write_tags
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
        playlist_name: Optional[str] = None,
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

    def _convert_m4a_to_flac(self, src: Path, dest: Path) -> None:
        result = subprocess.run(
            ["ffmpeg", "-i", str(src), "-c:a", "flac", "-map_metadata", "-1", "-y", str(dest)],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[:300]}")

    def _handle_cover(self, src_m4a: Path, dest_flac: Path) -> None:
        """Extract embedded cover from M4A, embed in FLAC, and save cover.jpg."""
        try:
            mp4 = MP4(src_m4a)
            if mp4.tags and "covr" in mp4.tags and mp4.tags["covr"]:
                cover_data = bytes(mp4.tags["covr"][0])
                embed_cover_art(dest_flac, cover_data)
                cover_jpg = dest_flac.parent / "cover.jpg"
                if not cover_jpg.exists():
                    save_cover_file(cover_jpg, cover_data)
        except Exception:
            pass  # cover art is best-effort

    def _handle_lrc(self, src_audio: Path, dest_flac: Path) -> None:
        """Move matching .lrc file from staging to album dir."""
        lrc_src = src_audio.with_suffix(".lrc")
        if lrc_src.exists():
            lrc_dest = dest_flac.with_suffix(".lrc")
            shutil.move(str(lrc_src), lrc_dest)

    def sync(self, staging_dir: Path) -> SyncResult:
        """
        Process .m4a/.flac files from staging_dir into music_dir.

        For M4A: reads Apple Music tags with mutagen, transcodes to FLAC via
        ffmpeg (stripping all container metadata), then writes clean Vorbis
        Comments. Also handles embedded cover art and matching .lrc files.

        For FLAC: moves directly, handles .lrc.

        When playlist_name is None, skips playlist association and M3U8 writing.
        """
        audio_files = [f for f in staging_dir.rglob("*") if f.suffix.lower() in (".flac", ".m4a")]
        total = len(audio_files)
        self._log(f"Processing {total} file(s) from staging...", "processing")

        new_count = 0
        skipped_count = 0
        error_count = 0

        for i, src in enumerate(audio_files, 1):
            relative = str(src.relative_to(staging_dir))
            # Track ID uses .flac extension regardless of source format
            track_id = str(Path(relative).with_suffix(".flac"))

            if self.state.is_downloaded(track_id):
                skipped_count += 1
                src.unlink()
                if self.playlist_name:
                    self.state.add_track_to_playlist(self.playlist_name, track_id)
                self._log(f"[{i}/{total}] skipped (already downloaded): {src.name}", "processing")
                continue

            try:
                tags = read_tags(src)
                artist = tags["artist"] or "Unknown Artist"
                album_artist = tags["album_artist"] or artist
                album = tags["album"] or "Unknown Album"
                title = tags["title"] or src.stem
                track_num = tags["track_num"] or 1

                dest = track_path(self.music_dir, album_artist, album, track_num, title, ext=".flac")
                ensure_album_dir(self.music_dir, album_artist, album)

                if src.suffix.lower() == ".m4a":
                    self._convert_m4a_to_flac(src, dest)
                    self._handle_cover(src, dest)
                    src.unlink()
                else:
                    shutil.move(str(src), dest)

                write_tags(dest, title=title, artist=artist, album_artist=album_artist,
                           album=album, track_num=track_num,
                           playlist_name=self.playlist_name or "")

                self._handle_lrc(src, dest)

                self.state.add_track(Track(
                    track_id=track_id,
                    title=title,
                    artist=artist,
                    album=album,
                    local_path=str(dest),
                    downloaded_at=datetime.now().isoformat(),
                ))
                if self.playlist_name:
                    self.state.add_track_to_playlist(self.playlist_name, track_id)
                new_count += 1
                self._log(f"[{i}/{total}] added: {artist} — {title}", "processing")

            except Exception as exc:
                error_count += 1
                self._log(f"[{i}/{total}] error processing {src.name}: {exc}", "processing")

        if self.playlist_name:
            self._write_m3u8()
        self._log(
            f"Sync complete: {new_count} new, {skipped_count} skipped, {error_count} errors",
            "done",
        )

        return SyncResult(new_count=new_count, skipped_count=skipped_count, error_count=error_count)
