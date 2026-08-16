import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from alac_rip.organizer import sanitize
from alac_rip.state import StateManager

DAP_FORMATS = {
    "opus": {
        "ext": ".opus",
        "codec": "libopus",
        "default_bitrate": "160k",
    },
    "aac": {
        "ext": ".m4a",
        "codec": "aac",
        "default_bitrate": "256k",
    },
    "m4a": {
        "ext": ".m4a",
        "codec": "aac",
        "default_bitrate": "256k",
    },
}

ProgressCallback = Callable[[int, int, str], None]


class DapExportError(Exception):
    """Raised when DAP export or transcoding fails."""
    pass


def validate_dap_target_dir(target_dir: Path) -> Path:
    """Validate that the target DAP export directory is safe."""
    resolved = target_dir.expanduser().resolve()
    if resolved == Path("/").resolve():
        raise DapExportError("Target directory cannot be filesystem root (/)")
    return resolved


def export_dap_playlist(
    music_dir: Path,
    playlist_name: str,
    target_dir: Path,
    format: str = "opus",
    bitrate: Optional[str] = None,
    state: Optional[StateManager] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> dict:
    """Export and transcode a playlist for DAP / portable players.

    - Reads tracks for playlist_name from state.
    - Transcodes tracks to Opus or AAC using ffmpeg into target_dir / playlist_name /
    - Copies matching .lrc sidecars alongside transcoded audio.
    - Generates relative M3U playlists in target_dir and export_dir.
    """
    if not playlist_name or not playlist_name.strip():
        raise DapExportError("Playlist name cannot be empty")

    fmt_key = format.lower().strip()
    if fmt_key not in DAP_FORMATS:
        raise DapExportError(
            f"Unsupported format '{format}'. Supported formats: {', '.join(sorted(DAP_FORMATS.keys()))}"
        )

    fmt_info = DAP_FORMATS[fmt_key]
    out_ext = fmt_info["ext"]
    codec = fmt_info["codec"]
    chosen_bitrate = (bitrate or fmt_info["default_bitrate"]).strip()
    if not re.match(r"^[1-9]\d{1,3}k$", chosen_bitrate, re.IGNORECASE):
        raise DapExportError(f"Invalid bitrate '{chosen_bitrate}'. Format must be e.g. '160k', '256k', '320k'")

    resolved_target = validate_dap_target_dir(target_dir)
    resolved_target.mkdir(parents=True, exist_ok=True)

    if state is None:
        raise DapExportError("StateManager is required for DAP playlist export")

    tracks = state.get_playlist_tracks(playlist_name)
    if not tracks:
        raise DapExportError(f"Playlist '{playlist_name}' has no tracks in the library")

    sanitized_pl = sanitize(playlist_name)
    export_dir = resolved_target / sanitized_pl
    export_dir.mkdir(parents=True, exist_ok=True)

    exported_files: list[str] = []
    exported_count = 0
    skipped_count = 0
    error_count = 0
    total = len(tracks)

    playlist_relative_entries: list[tuple[str, str, str]] = []  # (artist, title, filename)

    for idx, track in enumerate(tracks, 1):
        src_path = Path(track.local_path).resolve()
        clean_artist = re.sub(r"[\r\n\t\x00-\x1f\x7f-\x9f\s]+", " ", track.artist).strip()
        clean_title = re.sub(r"[\r\n\t\x00-\x1f\x7f-\x9f\s]+", " ", track.title).strip()
        out_name = f"{idx:02d} - {sanitize(track.title)}{out_ext}"
        dest_path = export_dir / out_name

        if on_progress:
            on_progress(idx, total, f"Transcoding {track.artist} - {track.title}")

        if not src_path.exists():
            error_count += 1
            continue

        try:
            # Transcode audio using ffmpeg with metadata preservation
            cmd = [
                "ffmpeg",
                "-i", str(src_path),
                "-vn",
                "-c:a", codec,
                "-b:a", chosen_bitrate,
                "-map_metadata", "0",
                "-y",
                str(dest_path),
            ]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                err_msg = result.stderr.decode(errors="replace")[:300]
                raise RuntimeError(f"ffmpeg transcode failed: {err_msg}")

            # Copy .lrc sidecar if present next to source
            src_lrc = src_path.with_suffix(".lrc")
            if src_lrc.exists() and src_lrc.is_file() and not src_lrc.is_symlink():
                dest_lrc = dest_path.with_suffix(".lrc")
                shutil.copy2(str(src_lrc), str(dest_lrc))

            exported_files.append(str(dest_path))
            playlist_relative_entries.append((clean_artist, clean_title, out_name))
            exported_count += 1

        except Exception as exc:
            error_count += 1

    # Write relative M3U inside export_dir (e.g. export_dir / Playlist.m3u)
    inner_m3u = export_dir / f"{sanitized_pl}.m3u"
    inner_lines = ["#EXTM3U", ""]
    for artist, title, filename in playlist_relative_entries:
        inner_lines.append(f"#EXTINF:-1,{artist} - {title}")
        inner_lines.append(filename)
    inner_m3u.write_text("\n".join(inner_lines) + "\n", encoding="utf-8")

    # Write root-relative M3U in target_dir (e.g. target_dir / Playlist.m3u)
    outer_m3u = resolved_target / f"{sanitized_pl}.m3u"
    outer_lines = ["#EXTM3U", ""]
    for artist, title, filename in playlist_relative_entries:
        outer_lines.append(f"#EXTINF:-1,{artist} - {title}")
        outer_lines.append(f"{sanitized_pl}/{filename}")
    outer_m3u.write_text("\n".join(outer_lines) + "\n", encoding="utf-8")

    return {
        "status": "ok",
        "playlist_name": playlist_name,
        "format": fmt_key,
        "bitrate": chosen_bitrate,
        "target_dir": str(resolved_target),
        "export_dir": str(export_dir),
        "exported_count": exported_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "playlist_file": str(inner_m3u),
        "files": exported_files,
    }
