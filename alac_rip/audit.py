import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from alac_rip.config import resolve_kio_fuse_path
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


def _normalize_track_file_path(lp: str, music_dir_resolved: Path) -> Optional[Path]:
    """Resolve a track file path across local and network mounts (KIO-Fuse, GVFS, SMB)."""
    if not lp:
        return None
    p = Path(lp).expanduser()
    p = resolve_kio_fuse_path(p)
    try:
        if p.is_file():
            return p.resolve()
    except (OSError, RuntimeError):
        pass

    # Try resolving relative to current music_dir
    try:
        if not p.is_absolute():
            cand = (music_dir_resolved / p).resolve()
            if cand.is_file():
                return cand
        path_str = str(p)
        for anchor in ("/artists/", "/playlists/", "artists/", "playlists/"):
            if anchor in path_str:
                rel = path_str.split(anchor, 1)[1]
                anchor_dir = anchor.strip("/")
                cand = (music_dir_resolved / anchor_dir / rel).resolve()
                if cand.is_file():
                    return cand
    except Exception:
        pass
    return None


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
        p = _normalize_track_file_path(lp, music_dir_resolved)

        if p is None:
            missing_files.append({
                "track_id": t["track_id"],
                "title": t["title"],
                "artist": t["artist"],
                "album": t["album"],
                "local_path": lp,
                "playlists": t.get("playlists", []),
            })
        else:
            # Self-healing: update database record if stored with old session mount path
            if str(p) != lp:
                try:
                    state.update_track_local_path(t["track_id"], str(p))
                except Exception:
                    pass

            tracked_resolved_paths.add(p)
            # Check lyrics (.lrc sidecar)
            lrc_path = p.with_suffix(".lrc")
            if not lrc_path.is_file():
                missing_lyrics.append({
                    "track_id": t["track_id"],
                    "title": t["title"],
                    "artist": t["artist"],
                    "album": t["album"],
                    "local_path": str(p),
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
                    "local_path": str(p),
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
    music_dir_resolved = music_dir.expanduser().resolve()
    tracks = state.get_all_tracks_with_provenance()
    flac_tracks = []
    for t in tracks:
        lp = t.get("local_path", "")
        if lp and lp.lower().endswith(".flac"):
            p = _normalize_track_file_path(lp, music_dir_resolved)
            if p and p.is_file() and not p.is_symlink() and _is_safe_subpath(p, music_dir_resolved):
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
            raw_path = track.local_path.replace("\r", "").replace("\n", "").strip()

            # Format relative path for universal Navidrome / Subsonic / SMB portability
            rel_path = raw_path
            try:
                track_abs = Path(raw_path).resolve()
                if track_abs.is_relative_to(music_dir_resolved):
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


def normalize_match_key(title: str, artist: str) -> tuple[str, str]:
    """Normalize title and artist to catch duplicate tracks across singles, albums, and naming differences."""
    # Clean feat / featuring / with / remaster / deluxe tags
    t = re.sub(
        r"\s*[\(\[](?:feat\.|featuring|ft\.|with|remaster(?:ed)?|deluxe|explicit|clean|mono|stereo|bonus track)[\s\w\.\,\-]*[\)\]]",
        "",
        title or "",
        flags=re.IGNORECASE,
    )
    # Strip numeric prefixes like "01 - ", "1550. "
    t = re.sub(r"^\d+[\.\-\s]+", "", t)
    t = re.sub(r"[^\w\s]", "", t).strip().lower()

    a = re.sub(
        r"\s*[\(\[](?:feat\.|featuring|ft\.|with)[\s\w\.\,\-]*[\)\]]",
        "",
        artist or "",
        flags=re.IGNORECASE,
    )
    a = re.sub(r"[^\w\s]", "", a).strip().lower()
    return (t, a)


def _extract_track_identity(t: dict, p: Optional[Path]) -> tuple[str, str, str]:
    """Extract true artist, title, album from file tags or file path if DB has placeholders."""
    artist = (t.get("artist") or "").strip()
    title = (t.get("title") or "").strip()
    album = (t.get("album") or "").strip()

    if p and p.is_file():
        try:
            tags = read_tags(p)
            tag_artist = (tags.get("artist") or "").strip()
            tag_title = (tags.get("title") or "").strip()
            tag_album = (tags.get("album") or "").strip()

            if tag_artist and tag_artist.lower() not in ("unknown artist", "unknown", ""):
                artist = tag_artist
            if tag_title and tag_title.lower() not in ("unknown title", "unknown", ""):
                title = tag_title
            if tag_album and tag_album.lower() not in ("unknown album", "unknown", ""):
                album = tag_album
        except Exception:
            pass

        # If still unknown or looks like placeholder, derive from folder path
        # Format: /music/artists/<Artist>/<Album>/<TrackNum> - <Title>.flac
        parts = p.parts
        if "artists" in parts:
            idx = parts.index("artists")
            if len(parts) > idx + 1 and (not artist or artist.lower() in ("unknown artist", "unknown")):
                artist = parts[idx + 1]
            if len(parts) > idx + 2 and (not album or album.lower() in ("unknown album", "unknown")):
                album = parts[idx + 2]
            if len(parts) > idx + 3 and (not title or title.isdigit() or title.lower() in ("unknown", "unknown title")):
                filename = p.stem
                clean_name = re.sub(r"^\d+[\.\-\s]+", "", filename)
                clean_name = re.sub(r"_coll_\d+", "", clean_name)
                if clean_name.strip():
                    title = clean_name.strip()

    return artist, title, album


def find_library_duplicates(music_dir: Path, state: StateManager) -> dict:
    """
    Scan entire library for duplicate tracks, collision files (_coll_*), and duplicate playlist mappings.
    Returns categorized duplicate groups with recommended primary track and reclaimable disk space.
    """
    music_dir_resolved = music_dir.expanduser().resolve()
    all_tracks = state.get_all_tracks_with_provenance()

    groups_map: dict[tuple[str, str], list[dict]] = {}

    for t in all_tracks:
        lp = t.get("local_path", "")
        p = _normalize_track_file_path(lp, music_dir_resolved)
        exists = p is not None and p.is_file()
        file_size = p.stat().st_size if exists else 0

        # Extract true grounded artist, title, album from audio file tags / folder structure
        artist, title, album = _extract_track_identity(t, p)

        # Detect collision suffix
        has_collision_suffix = "_coll_" in p.name if p else "_coll_" in lp
        album_is_single = any(s in album.lower() for s in ("- single", " - ep", "(single)", "[single]"))

        fmt = p.suffix.lstrip(".").upper() if p else "FLAC"

        norm_title, norm_artist = normalize_match_key(title, artist)
        # Require non-empty title and artist
        if not norm_title or not norm_artist:
            continue

        track_obj = {
            "track_id": t["track_id"],
            "title": title,
            "artist": artist,
            "album": album,
            "local_path": str(p) if p else lp,
            "file_exists": exists,
            "file_size": file_size,
            "format": fmt,
            "downloaded_at": t.get("downloaded_at", ""),
            "am_track_id": t.get("am_track_id"),
            "artwork_url": t.get("artwork_url"),
            "playlists": t.get("playlists", []),
            "has_collision_suffix": has_collision_suffix,
            "album_is_single": album_is_single,
        }

        key = (norm_title, norm_artist)
        groups_map.setdefault(key, []).append(track_obj)

    duplicate_groups = []
    total_duplicate_tracks = 0
    total_reclaimable_bytes = 0

    for idx, (key, tracks) in enumerate(groups_map.items(), 1):
        if len(tracks) < 2:
            continue

        # Score tracks to determine recommended primary
        def _score(track: dict) -> int:
            score = 0
            if track["file_exists"]:
                score += 1000
            if not track["has_collision_suffix"]:
                score += 200
            if not track["album_is_single"]:
                score += 100
            score += len(track["playlists"]) * 50
            if track["am_track_id"]:
                score += 25
            score += min(track["file_size"] // (1024 * 1024), 50)  # Up to 50 pts for file size
            return score

        tracks_sorted = sorted(tracks, key=_score, reverse=True)
        # Mark primary track
        for i, t in enumerate(tracks_sorted):
            t["is_recommended"] = (i == 0)

        group_reclaimable = sum(t["file_size"] for t in tracks_sorted[1:] if t["file_exists"])
        total_reclaimable_bytes += group_reclaimable
        total_duplicate_tracks += len(tracks_sorted) - 1

        group_id = f"dup_{abs(hash(key))}_{idx}"
        duplicate_groups.append({
            "group_id": group_id,
            "title": tracks_sorted[0]["title"],
            "artist": tracks_sorted[0]["artist"],
            "track_count": len(tracks_sorted),
            "reclaimable_bytes": group_reclaimable,
            "tracks": tracks_sorted,
        })

    duplicate_groups.sort(key=lambda g: (g["reclaimable_bytes"], g["track_count"]), reverse=True)

    return {
        "total_groups": len(duplicate_groups),
        "total_duplicate_tracks": total_duplicate_tracks,
        "total_reclaimable_bytes": total_reclaimable_bytes,
        "groups": duplicate_groups,
    }


def sweep_library_duplicates(
    music_dir: Path,
    state: StateManager,
    keep_criteria: str = "recommended",
    delete_files: bool = True,
    remap_playlists: bool = True,
    group_ids: Optional[list[str]] = None,
) -> dict:
    """
    Execute a deduplication sweep across the entire library.
    Removes duplicate tracks, unlinks duplicate files from disk, remaps playlists, and regenerates .m3u8 files.
    """
    music_dir_resolved = music_dir.expanduser().resolve()
    report = find_library_duplicates(music_dir, state)

    target_groups = report["groups"]
    if group_ids:
        group_id_set = set(group_ids)
        target_groups = [g for g in target_groups if g["group_id"] in group_id_set]

    freed_bytes = 0
    deleted_files_count = 0
    remap_pairs: list[tuple[str, str]] = []
    tracks_to_delete: list[str] = []
    processed_groups = 0

    for group in target_groups:
        tracks = group["tracks"]
        if len(tracks) < 2:
            continue

        # Determine primary track based on criteria
        if keep_criteria == "oldest":
            primary = min(tracks, key=lambda t: t.get("downloaded_at") or "9999")
        elif keep_criteria == "newest":
            primary = max(tracks, key=lambda t: t.get("downloaded_at") or "")
        elif keep_criteria == "highest_quality":
            primary = max(tracks, key=lambda t: (t.get("file_size") or 0, t.get("file_exists") or False))
        else:
            # Default "recommended" or "album_over_single"
            primary = next((t for t in tracks if t.get("is_recommended")), tracks[0])

        duplicates = [t for t in tracks if t["track_id"] != primary["track_id"]]

        for dup in duplicates:
            remap_pairs.append((dup["track_id"], primary["track_id"]))
            tracks_to_delete.append(dup["track_id"])

            if delete_files and dup["file_exists"]:
                dup_path_str = dup.get("local_path", "")
                p = _normalize_track_file_path(dup_path_str, music_dir_resolved)
                primary_p = _normalize_track_file_path(primary.get("local_path", ""), music_dir_resolved)

                # Ensure we do not delete the primary track file
                if p and p.is_file() and (primary_p is None or p.resolve() != primary_p.resolve()):
                    if _is_safe_subpath(p, music_dir_resolved):
                        try:
                            file_sz = p.stat().st_size
                            p.unlink(missing_ok=True)
                            freed_bytes += file_sz
                            deleted_files_count += 1
                            # Clean up matching lyrics sidecar if present
                            lrc_p = p.with_suffix(".lrc")
                            if lrc_p.is_file():
                                lrc_p.unlink(missing_ok=True)

                            # Clean up empty parent directory if empty
                            parent = p.parent
                            if parent != music_dir_resolved and _is_safe_subpath(parent, music_dir_resolved):
                                try:
                                    remaining = list(parent.iterdir())
                                    # If only cover.jpg / folder.jpg remains, delete them
                                    if all(f.name.lower() in ("cover.jpg", "folder.jpg", "cover.png", ".ds_store") for f in remaining):
                                        for f in remaining:
                                            f.unlink(missing_ok=True)
                                        parent.rmdir()
                                except Exception:
                                    pass
                        except Exception:
                            pass

        processed_groups += 1

    # Execute database remapping and deletion
    remapped_count, deleted_db_count = state.remap_and_remove_tracks(remap_pairs, tracks_to_delete)

    # Regenerate .m3u8 playlist files if playlists were affected
    repaired_playlists_count = 0
    if remap_playlists and remapped_count > 0:
        repair_res = repair_playlists(music_dir, state)
        repaired_playlists_count = repair_res.get("repaired_count", 0)

    return {
        "status": "ok",
        "processed_groups": processed_groups,
        "removed_tracks_count": deleted_db_count,
        "deleted_files_count": deleted_files_count,
        "freed_bytes": freed_bytes,
        "remapped_playlist_references": remapped_count,
        "repaired_playlists_count": repaired_playlists_count,
    }
