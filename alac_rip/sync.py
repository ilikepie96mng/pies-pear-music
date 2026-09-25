import os
import re
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Sequence


from mutagen.flac import FLAC
from mutagen.mp4 import MP4

from alac_rip.metadata import embed_cover_art, read_tags, save_cover_file, write_tags
from alac_rip.organizer import ensure_album_dir, sanitize, track_path
from alac_rip.state import StateManager, Track, clean_artist, clean_title

LogCallback = Callable[[str, str], None]  # (message, phase)
ProgressCallback = Callable[[int, int], None]  # (current, total)


class StagingValidationError(ValueError):
    """Raised when a staging directory fails security or boundary validation."""
    pass


class IntegrityError(Exception):
    """Raised when audio stream integrity verification fails."""
    pass


def validate_staging_dir(
    staging_dir: Path,
    music_dir: Path,
    state_dir: Optional[Path] = None,
    tool_dir: Optional[Path] = None,
) -> Path:
    """Validate that the staging directory is safe and non-overlapping.

    Enforces:
    - Must be an absolute path and exist.
    - Cannot be filesystem root (/) or user's home directory.
    - Cannot be equal to, contain, or be contained by music_dir, state_dir, or tool_dir.
    """
    resolved_staging = staging_dir.resolve()
    resolved_music = music_dir.resolve()
    resolved_home = Path.home().resolve()
    resolved_root = Path("/").resolve()

    if not staging_dir.is_absolute():
        raise StagingValidationError(f"Staging directory must be an absolute path: {staging_dir}")

    if resolved_staging == resolved_root:
        raise StagingValidationError("Staging directory cannot be filesystem root (/)" )

    if resolved_staging == resolved_home:
        raise StagingValidationError(f"Staging directory cannot be home directory: {resolved_home}")

    protected_roots = [("music_dir", resolved_music)]
    if state_dir:
        protected_roots.append(("state_dir", state_dir.resolve()))
    if tool_dir:
        protected_roots.append(("tool_dir", tool_dir.resolve()))

    for name, protected_path in protected_roots:
        if resolved_staging == protected_path:
            raise StagingValidationError(f"Staging directory cannot be identical to {name}: {protected_path}")
        if resolved_staging.is_relative_to(protected_path):
            raise StagingValidationError(f"Staging directory cannot be inside {name}: {protected_path}")
        if protected_path.is_relative_to(resolved_staging):
            raise StagingValidationError(f"{name} cannot be inside staging directory: {resolved_staging}")

    return resolved_staging


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
        state_dir: Optional[Path] = None,
        on_progress: Optional[ProgressCallback] = None,
    ):
        self.state = state
        self.music_dir = music_dir.resolve()
        self.playlist_name = playlist_name
        self.state_dir = state_dir.resolve() if state_dir else None
        self._on_log: LogCallback = on_log or (lambda msg, phase: None)
        self.on_progress: Optional[ProgressCallback] = on_progress

    def _log(self, msg: str, phase: str = "processing") -> None:
        self._on_log(msg, phase)

    def _track_id(self, relative_path: str) -> str:
        return str(Path(relative_path).with_suffix(".flac"))

    def _safe_commit(self, src: Path, dest: Path) -> None:
        """Safely move or replace file across filesystems or network SMB/CIFS shares."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(str(src), str(dest))
        except OSError:
            # Cross-filesystem or FUSE / CIFS fallback: use byte-copy to avoid ioctl/utime failures on FUSE
            tmp_target = dest.with_name(f".tmp_commit_{os.getpid()}_{dest.name}")
            try:
                shutil.copyfile(str(src), str(tmp_target))
                try:
                    os.replace(str(tmp_target), str(dest))
                except OSError:
                    # Some network shares disallow atomic overwrite; remove existing target first
                    dest.unlink(missing_ok=True)
                    try:
                        os.replace(str(tmp_target), str(dest))
                    except OSError:
                        shutil.copyfile(str(src), str(dest))
                        tmp_target.unlink(missing_ok=True)
            finally:
                tmp_target.unlink(missing_ok=True)
            try:
                src.unlink(missing_ok=True)
            except OSError:
                pass

    def _write_m3u8(self) -> None:
        tracks = self.state.get_playlist_tracks(self.playlist_name)
        if not tracks:
            return

        playlists_dir = self.music_dir / "playlists"
        playlists_dir.mkdir(exist_ok=True)

        m3u8_path = playlists_dir / f"{sanitize(self.playlist_name)}.m3u8"

        lines = ["#EXTM3U", ""]
        for track in tracks:
            # Flatten any control characters or newlines to prevent M3U injection
            clean_artist = re.sub(r"[\r\n\t\x00-\x1f\x7f-\x9f\s]+", " ", track.artist).strip()
            clean_title = re.sub(r"[\r\n\t\x00-\x1f\x7f-\x9f\s]+", " ", track.title).strip()
            raw_path = track.local_path.replace("\r", "").replace("\n", "").strip()

            # Format relative path for universal Navidrome / Subsonic / SMB portability
            rel_path = raw_path
            try:
                track_abs = Path(raw_path).resolve()
                if track_abs.is_relative_to(self.music_dir):
                    rel_path = os.path.relpath(track_abs, playlists_dir).replace("\\", "/")
                elif "/artists/" in raw_path:
                    sub_rel = "artists/" + raw_path.split("/artists/", 1)[1]
                    rel_path = f"../{sub_rel}".replace("\\", "/")
                elif "\\artists\\" in raw_path:
                    sub_rel = "artists/" + raw_path.split("\\artists\\", 1)[1].replace("\\", "/")
                    rel_path = f"../{sub_rel}"
            except Exception:
                if "/artists/" in raw_path:
                    sub_rel = "artists/" + raw_path.split("/artists/", 1)[1]
                    rel_path = f"../{sub_rel}".replace("\\", "/")

            lines.append(f"#EXTINF:-1,{clean_artist} - {clean_title}")
            lines.append(rel_path)

        m3u8_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _convert_m4a_to_flac(self, src: Path, dest: Path) -> None:
        result = subprocess.run(
            ["ffmpeg", "-i", str(src), "-vn", "-c:a", "flac", "-map_metadata", "-1", "-y", str(dest)],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[:300]}")

    def _handle_cover(self, src_m4a: Path, local_flac: Path, album_dir: Path) -> None:
        """Extract embedded cover from M4A, embed in FLAC, and save cover.jpg in album dir."""
        try:
            mp4 = MP4(src_m4a)
            if mp4.tags and "covr" in mp4.tags and mp4.tags["covr"]:
                cover_data = bytes(mp4.tags["covr"][0])
                embed_cover_art(local_flac, cover_data)
                cover_jpg = album_dir / "cover.jpg"
                if not cover_jpg.exists():
                    save_cover_file(cover_jpg, cover_data)
        except Exception:
            pass  # cover art is best-effort

    def _save_cover_from_flac(self, local_flac: Path, album_dir: Path) -> None:
        """Extract embedded cover from FLAC and save cover.jpg in album dir."""
        cover_jpg = album_dir / "cover.jpg"
        if cover_jpg.exists():
            return
        try:
            audio = FLAC(local_flac)
            if audio.pictures:
                save_cover_file(cover_jpg, audio.pictures[0].data)
        except Exception:
            pass

    def _verify_flac_integrity(self, file_path: Path) -> tuple[bool, str]:
        """Verify MD5 checksums and audio frame decode validity on a FLAC file.

        Runs `flac -t -s <file_path>`.
        If flac binary is missing from PATH, logs a warning and returns (True, "flac binary not found (skipped)").
        If flac returns 0, returns (True, "OK").
        If flac returns non-zero, returns (False, error_message).
        """
        flac_bin = shutil.which("flac")
        if not flac_bin:
            self._log(
                f"Warning: 'flac' binary not found in PATH; skipping integrity check for {file_path.name}",
                "processing",
            )
            return True, "flac binary not found (skipped)"

        result = subprocess.run(
            [flac_bin, "-t", "-s", str(file_path)],
            capture_output=True,
        )
        if result.returncode == 0:
            return True, "OK"

        err_msg = result.stderr.decode(errors="replace").strip() or "FLAC stream corrupted or invalid"
        return False, err_msg

    def _handle_lrc(
        self,
        src_audio: Path,
        dest_flac: Path,
        lyrics_text: Optional[str] = None,
    ) -> Optional[str]:
        """Move matching .lrc file from staging to album dir or write lyrics_text.

        Returns the lyrics text if present, or None.
        """
        def _safe_write_lrc(target: Path, text: str) -> bool:
            try:
                resolved_root = self.music_dir.resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                resolved_parent = target.parent.resolve()
                resolved_parent.relative_to(resolved_root)

                if target.is_symlink():
                    target.unlink()

                tmp_name = f".tmp_{secrets.token_hex(8)}_{target.name}"
                tmp_path = target.parent / tmp_name

                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(str(tmp_path), flags, 0o644)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(text)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(str(tmp_path), str(target))
                    try:
                        dir_fd = os.open(str(target.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                        try:
                            os.fsync(dir_fd)
                        finally:
                            os.close(dir_fd)
                    except OSError:
                        pass
                    return True
                except Exception:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return False
            except Exception:
                return False

        lrc_src = src_audio.with_suffix(".lrc")
        lrc_dest = dest_flac.with_suffix(".lrc")
        if lrc_src.exists() and lrc_src.is_file() and not lrc_src.is_symlink():
            try:
                content = lrc_src.read_text(encoding="utf-8", errors="replace")
                if _safe_write_lrc(lrc_dest, content):
                    lrc_src.unlink(missing_ok=True)
                    return content
            except Exception:
                pass
        elif lyrics_text:
            if _safe_write_lrc(lrc_dest, lyrics_text):
                return lyrics_text
        elif lrc_dest.exists() and lrc_dest.is_file() and not lrc_dest.is_symlink():
            try:
                return lrc_dest.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        return None

    def _find_files(self, staging_dir: Path, manifest_files: Optional[Sequence[Path]] = None) -> list[Path]:
        audio_files: list[Path] = []
        valid_staging = staging_dir.resolve()
        if manifest_files is not None:
            for item in manifest_files:
                resolved_item = item.resolve()
                if (
                    resolved_item.is_file()
                    and not resolved_item.is_symlink()
                    and resolved_item.is_relative_to(valid_staging)
                    and resolved_item.suffix.lower() in (".flac", ".m4a")
                ):
                    audio_files.append(resolved_item)
        else:
            for f in valid_staging.rglob("*"):
                if (
                    f.is_file()
                    and not f.is_symlink()
                    and f.resolve().is_relative_to(valid_staging)
                    and f.suffix.lower() in (".flac", ".m4a")
                ):
                    audio_files.append(f)
        return audio_files

    def sync(
        self,
        staging_dir: Path,
        manifest_files: Optional[Sequence[Path]] = None,
    ) -> SyncResult:
        """
        Process .m4a/.flac files from staging_dir into music_dir.

        If manifest_files is provided, ONLY those files (which must exist in
        staging_dir) will be processed, ignoring other files in staging_dir.
        """
        valid_staging = validate_staging_dir(staging_dir, self.music_dir, self.state_dir)
        files = self._find_files(valid_staging, manifest_files=manifest_files)
        total_files = len(files)
        new_count = 0
        skipped_count = 0
        error_count = 0

        self._log(f"Found {total_files} file(s) in staging.", "processing")

        for i, src in enumerate(files, 1):
            try:
                tags = read_tags(src)
                track_id = self._track_id(str(src.relative_to(valid_staging)))

                artist = tags["artist"] or "Unknown Artist"
                album_artist = tags["album_artist"] or artist
                album = tags["album"] or "Unknown Album"
                title = tags["title"] or src.stem
                track_num = tags["track_num"] or 1

                dest = track_path(self.music_dir, album_artist, album, track_num, title, ext=".flac")
                album_dir = ensure_album_dir(self.music_dir, album_artist, album)

                # Check if this track already exists in library
                matched_track = None
                if self.state.is_downloaded(track_id):
                    matched_track = self.state.get_track(track_id)
                elif self.state.has_track_by_title_artist(title, artist):
                    matched_track = self.state.get_track_by_title_artist(title, artist)
                else:
                    path_track = self.state.get_track_by_path(str(dest))
                    if (
                        path_track is not None
                        and clean_title(path_track.title) == clean_title(title)
                        and (
                            not artist
                            or not path_track.artist
                            or clean_artist(path_track.artist) == clean_artist(artist)
                        )
                    ):
                        matched_track = path_track

                if matched_track is not None:
                    skipped_count += 1
                    try:
                        src.unlink(missing_ok=True)
                        src.with_suffix(".lrc").unlink(missing_ok=True)
                    except OSError:
                        pass
                    if self.playlist_name:
                        self.state.add_track_to_playlist(self.playlist_name, matched_track.track_id)
                    self._log(f"[{i}/{total_files}] skipped (already in library): {artist} — {title}", "processing")
                    continue

                # Progress callback
                if self.on_progress:
                    self.on_progress(i, total_files, f"[{i}/{total_files}] {src.name}", "processing")

                if dest.exists():
                    dest = album_dir / f"{track_num:02d} - {sanitize(title)}_coll_{i}.flac"

                # Perform all transcoding, tagging, and validation locally on fast local storage
                local_work_file = valid_staging / f".work_{os.getpid()}_{i}_{dest.name}"

                try:
                    if src.suffix.lower() == ".m4a":
                        self._convert_m4a_to_flac(src, local_work_file)
                        self._handle_cover(src, local_work_file, album_dir)
                    else:
                        shutil.copyfile(str(src), str(local_work_file))
                        self._save_cover_from_flac(local_work_file, album_dir)

                    # Collect lyrics from staging .lrc sidecar or embedded source tags
                    lrc_src = src.with_suffix(".lrc")
                    lyrics = ""
                    if lrc_src.exists() and lrc_src.is_file() and not lrc_src.is_symlink():
                        lyrics = lrc_src.read_text(encoding="utf-8", errors="replace")
                    elif tags.get("lyrics"):
                        lyrics = tags["lyrics"]

                    write_tags(
                        local_work_file,
                        title=title,
                        artist=artist,
                        album_artist=album_artist,
                        album=album,
                        track_num=track_num,
                        genre=tags.get("genre", ""),
                        lyrics=lyrics,
                    )

                    # FLAC stream integrity verification before commit
                    valid, err_msg = self._verify_flac_integrity(local_work_file)
                    if not valid:
                        raise IntegrityError(f"FLAC stream integrity check failed: {err_msg}")

                    # Safe replacement into final destination (handles cross-filesystem and SMB mounts)
                    self._safe_commit(local_work_file, dest)
                finally:
                    local_work_file.unlink(missing_ok=True)

                # Safe cleanup of source
                try:
                    src.unlink(missing_ok=True)
                except OSError:
                    pass

                self._handle_lrc(src, dest, lyrics_text=lyrics or None)

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
                self._log(f"[{i}/{total_files}] added: {artist} — {title}", "processing")

            except Exception as exc:
                error_count += 1
                self._log(f"[{i}/{total_files}] error processing {src.name}: {exc}", "processing")

        if self.playlist_name:
            self._write_m3u8()
        self._log(
            f"Sync complete: {new_count} new, {skipped_count} skipped, {error_count} errors",
            "done",
        )

        return SyncResult(new_count=new_count, skipped_count=skipped_count, error_count=error_count)

