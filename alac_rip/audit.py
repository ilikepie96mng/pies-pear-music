import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from alac_rip.metadata import read_tags
from alac_rip.organizer import sanitize
from alac_rip.state import StateManager, Track

_AUDIO_EXTENSIONS = frozenset({".flac", ".m4a", ".alac", ".mp3", ".aac", ".opus", ".ogg"})


def _is_safe_subpath(path: Path, base_dir: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(base_dir.expanduser().resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def audit_library(music_dir: Path, state: StateManager) -> dict:
    """Compare database records against filesystem state and return audit discrepancies."""
    music_dir_resolved = music_dir.expanduser().resolve()
    tracks = state.get_all_tracks_with_provenance()

    missing_files = []
    missing_lyrics = []
    missing_art = []
    tracked_resolved_paths = set()

    for t in tracks:
        lp = t.get("local_path", "")
        if not lp:
            missing_files.append({
                "track_id": t["track_id"],
                "title": t["title"],
                "artist": t["artist"],
                "album": t["album"],
                "local_path": lp,
                "playlists": t.get("playlists", []),
            })
            continue

        try:
            p = Path(lp).expanduser().resolve()
        except (OSError, RuntimeError):
            p = None

        if p is None or not p.is_file():
            missing_files.append({
                "track_id": t["track_id"],
                "title": t["title"],
                "artist": t["artist"],
                "album": t["album"],
                "local_path": lp,
                "playlists": t.get("playlists", []),
            })
        else:
            tracked_resolved_paths.add(p)
            # Check lyrics (.lrc sidecar)
            lrc_path = p.with_suffix(".lrc")
            if not lrc_path.is_file():
                missing_lyrics.append({
                    "track_id": t["track_id"],
                    "title": t["title"],
                    "artist": t["artist"],
                    "album": t["album"],
                    "local_path": lp,
                })

            # Check artwork (DB artwork_url or cover.jpg in directory)
            has_db_art = bool(t.get("artwork_url"))
            cover_file = p.parent / "cover.jpg"
            if not has_db_art and not cover_file.is_file():
                missing_art.append({
                    "track_id": t["track_id"],
                    "title": t["title"],
                    "artist": t["artist"],
                    "album": t["album"],
                    "local_path": lp,
                })

    orphaned_files = []
    if music_dir_resolved.is_dir():
        for file_path in music_dir_resolved.rglob("*"):
            try:
                if not file_path.is_file():
                    continue
                # Skip hidden files/directories and temporary staging directories
                parts = file_path.relative_to(music_dir_resolved).parts
                if any(part.startswith(".") for part in parts):
                    continue
                if any(part.lower() in ("staging", "tmp", ".tmp") for part in parts):
                    continue

                if file_path.suffix.lower() in _AUDIO_EXTENSIONS:
                    resolved_file = file_path.resolve()
                    if resolved_file not in tracked_resolved_paths:
                        orphaned_files.append({
                            "path": str(resolved_file),
                            "name": file_path.name,
                            "size": resolved_file.stat().st_size,
                            "relative_path": str(resolved_file.relative_to(music_dir_resolved)),
                        })
            except (OSError, RuntimeError):
                continue

    return {
        "missing_files": missing_files,
        "orphaned_files": orphaned_files,
        "missing_lyrics": missing_lyrics,
        "missing_art": missing_art,
        "summary": {
            "total_db_tracks": len(tracks),
            "missing_files_count": len(missing_files),
            "orphaned_files_count": len(orphaned_files),
            "missing_lyrics_count": len(missing_lyrics),
            "missing_art_count": len(missing_art),
        },
    }


def verify_library_flac_integrity(
    music_dir: Path,
    state: StateManager,
    limit: Optional[int] = None,
) -> dict:
    """Verify audio frame integrity of library FLAC files via flac -t."""
    tracks = state.get_all_tracks_with_provenance()
    flac_tracks = []
    for t in tracks:
        lp = t.get("local_path", "")
        if lp and lp.lower().endswith(".flac"):
            p = Path(lp).expanduser().resolve()
            if p.is_file():
                flac_tracks.append((t, p))

    if limit is not None and limit > 0:
        flac_tracks = flac_tracks[:limit]

    flac_binary = shutil.which("flac")
    corrupted = []

    for t, p in flac_tracks:
        if flac_binary:
            try:
                proc = subprocess.run(
                    [flac_binary, "-t", "-s", str(p)],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    corrupted.append({
                        "track_id": t["track_id"],
                        "title": t["title"],
                        "artist": t["artist"],
                        "album": t["album"],
                        "local_path": str(p),
                        "error": proc.stderr.strip() or f"flac integrity check failed (code {proc.returncode})",
                    })
            except Exception as exc:
                corrupted.append({
                    "track_id": t["track_id"],
                    "title": t["title"],
                    "artist": t["artist"],
                    "album": t["album"],
                    "local_path": str(p),
                    "error": str(exc),
                })
        else:
            # Fallback when flac binary is unavailable: test reading tags
            try:
                read_tags(p)
            except Exception as exc:
                corrupted.append({
                    "track_id": t["track_id"],
                    "title": t["title"],
                    "artist": t["artist"],
                    "album": t["album"],
                    "local_path": str(p),
                    "error": f"Tag decode error: {exc}",
                })

    return {
        "checked_count": len(flac_tracks),
        "corrupted": corrupted,
        "status": "ok" if not corrupted else "errors_found",
    }


def repair_playlists(music_dir: Path, state: StateManager) -> dict:
    """Regenerate all .m3u8 playlist files from SQLite database mappings."""
    music_dir_resolved = music_dir.expanduser().resolve()
    playlists_dir = music_dir_resolved / "playlists"
    playlists_dir.mkdir(parents=True, exist_ok=True)

    playlists = state.get_playlists()
    repaired = []

    for pl in playlists:
        tracks = state.get_playlist_tracks(pl.name)
        m3u8_path = playlists_dir / f"{sanitize(pl.name)}.m3u8"
        lines = ["#EXTM3U", ""]
        for track in tracks:
            clean_artist = re.sub(r"[\r\n\t\x00-\x1f\x7f-\x9f\s]+", " ", track.artist).strip()
            clean_title = re.sub(r"[\r\n\t\x00-\x1f\x7f-\x9f\s]+", " ", track.title).strip()
            clean_path = track.local_path.replace("\r", "").replace("\n", "").strip()
            lines.append(f"#EXTINF:-1,{clean_artist} - {clean_title}")
            lines.append(clean_path)
        m3u8_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        repaired.append(pl.name)

    return {
        "repaired_count": len(repaired),
        "playlists": repaired,
    }


def adopt_orphaned_files(
    music_dir: Path,
    state: StateManager,
    file_paths: Optional[list[str]] = None,
) -> dict:
    """Import unindexed audio files inside music_dir into SQLite state."""
    music_dir_resolved = music_dir.expanduser().resolve()

    if file_paths is None:
        audit_res = audit_library(music_dir, state)
        candidate_paths = [Path(o["path"]) for o in audit_res["orphaned_files"]]
    else:
        candidate_paths = []
        for p_str in file_paths:
            p = Path(p_str).expanduser().resolve()
            if not _is_safe_subpath(p, music_dir_resolved):
                continue
            if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS:
                candidate_paths.append(p)

    adopted = []
    now_iso = datetime.now().isoformat()

    for p in candidate_paths:
        if not _is_safe_subpath(p, music_dir_resolved):
            continue
        try:
            rel_path = str(p.relative_to(music_dir_resolved))
        except (ValueError, OSError):
            continue

        try:
            tags = read_tags(p)
            title = tags.get("title") or p.stem
            artist = tags.get("artist") or "Unknown Artist"
            album = tags.get("album") or "Unknown Album"
        except Exception:
            title = p.stem
            artist = "Unknown Artist"
            album = "Unknown Album"

        track_id = rel_path
        track = Track(
            track_id=track_id,
            title=title,
            artist=artist,
            album=album,
            local_path=str(p),
            downloaded_at=now_iso,
        )
        state.add_track(track)
        adopted.append({
            "track_id": track_id,
            "title": title,
            "artist": artist,
            "album": album,
            "local_path": str(p),
        })

    return {
        "adopted_count": len(adopted),
        "adopted": adopted,
    }
