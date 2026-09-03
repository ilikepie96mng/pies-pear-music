import base64
import binascii
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any, Optional

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, USLT
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from alac_rip import organizer
from alac_rip.state import StateManager


class MetadataEditorError(Exception):
    """Raised when an error occurs during audio metadata modification."""
    pass


def extract_embedded_cover(file_path: Path) -> Optional[tuple[bytes, str]]:
    """Extract embedded front cover artwork from FLAC, MP4/M4A, or MP3 file.
    
    Returns (image_bytes, mime_type) if found, else None.
    """
    if not file_path.is_file():
        return None

    ext = file_path.suffix.lower()
    try:
        if ext == ".flac":
            audio = FLAC(file_path)
            # Find front cover (type 3) or first available picture
            front_pic = next((p for p in audio.pictures if p.type == 3), None)
            if not front_pic and audio.pictures:
                front_pic = audio.pictures[0]
            if front_pic and front_pic.data:
                mime = front_pic.mime or "image/jpeg"
                return front_pic.data, mime

        elif ext in {".m4a", ".mp4", ".alac", ".aac"}:
            audio = MP4(file_path)
            tags = audio.tags or {}
            covers = tags.get("covr", [])
            if covers:
                cover = covers[0]
                mime = "image/png" if getattr(cover, "imageformat", None) == MP4Cover.FORMAT_PNG else "image/jpeg"
                return bytes(cover), mime

        elif ext == ".mp3":
            audio = MP3(file_path)
            tags = audio.tags
            if tags:
                for key in tags.keys():
                    if key.startswith("APIC"):
                        apic = tags[key]
                        mime = apic.mime or "image/jpeg"
                        return apic.data, mime
    except Exception:
        return None

    return None


def update_audio_tags(
    file_path: Path,
    fields: dict[str, Any],
    cover_bytes: Optional[bytes] = None,
    cover_mime: str = "image/jpeg",
    remove_cover: bool = False,
) -> dict[str, Any]:
    """Atomically updates metadata tags and/or cover art for a local audio file.
    
    Supported fields in `fields`:
    - title: Optional[str]
    - artist: Optional[str]
    - album: Optional[str]
    - album_artist: Optional[str]
    - genre: Optional[str]
    - year: Optional[str]
    - track_num: Optional[int]
    - disc_num: Optional[int]
    - lyrics: Optional[str]
    - comment: Optional[str]
    """
    if not file_path.is_file():
        raise MetadataEditorError(f"File not found: {file_path}")

    ext = file_path.suffix.lower()

    try:
        if ext == ".flac":
            audio = FLAC(file_path)
            if audio.tags is None:
                audio.add_tags()

            if "title" in fields and fields["title"] is not None:
                audio["title"] = str(fields["title"])
            if "artist" in fields and fields["artist"] is not None:
                audio["artist"] = str(fields["artist"])
            if "album" in fields and fields["album"] is not None:
                audio["album"] = str(fields["album"])
            if "album_artist" in fields and fields["album_artist"] is not None:
                audio["albumartist"] = str(fields["album_artist"])
            if "genre" in fields and fields["genre"] is not None:
                audio["genre"] = str(fields["genre"])
            if "year" in fields and fields["year"] is not None:
                audio["date"] = str(fields["year"])
            if "track_num" in fields and fields["track_num"] is not None:
                audio["tracknumber"] = str(fields["track_num"])
            if "disc_num" in fields and fields["disc_num"] is not None:
                audio["discnumber"] = str(fields["disc_num"])
            if "lyrics" in fields and fields["lyrics"] is not None:
                audio["lyrics"] = str(fields["lyrics"])
                audio["unsyncedlyrics"] = str(fields["lyrics"])
            if "comment" in fields and fields["comment"] is not None:
                audio["comment"] = str(fields["comment"])

            if remove_cover:
                audio.clear_pictures()
            elif cover_bytes:
                audio.clear_pictures()
                pic = Picture()
                pic.type = 3  # front cover
                pic.mime = cover_mime
                pic.data = cover_bytes
                audio.add_picture(pic)

            audio.save()

        elif ext in {".m4a", ".mp4", ".alac", ".aac"}:
            audio = MP4(file_path)
            if audio.tags is None:
                audio.add_tags()

            if "title" in fields and fields["title"] is not None:
                audio.tags["©nam"] = [str(fields["title"])]
            if "artist" in fields and fields["artist"] is not None:
                audio.tags["©ART"] = [str(fields["artist"])]
            if "album" in fields and fields["album"] is not None:
                audio.tags["©alb"] = [str(fields["album"])]
            if "album_artist" in fields and fields["album_artist"] is not None:
                audio.tags["aART"] = [str(fields["album_artist"])]
            if "genre" in fields and fields["genre"] is not None:
                audio.tags["©gen"] = [str(fields["genre"])]
            if "year" in fields and fields["year"] is not None:
                audio.tags["©day"] = [str(fields["year"])]
            if "track_num" in fields and fields["track_num"] is not None:
                existing_total = 0
                if "trkn" in audio.tags and audio.tags["trkn"]:
                    existing_total = audio.tags["trkn"][0][1]
                audio.tags["trkn"] = [(int(fields["track_num"]), existing_total)]
            if "disc_num" in fields and fields["disc_num"] is not None:
                existing_total = 0
                if "disk" in audio.tags and audio.tags["disk"]:
                    existing_total = audio.tags["disk"][0][1]
                audio.tags["disk"] = [(int(fields["disc_num"]), existing_total)]
            if "lyrics" in fields and fields["lyrics"] is not None:
                audio.tags["©lyr"] = [str(fields["lyrics"])]
            if "comment" in fields and fields["comment"] is not None:
                audio.tags["©cmt"] = [str(fields["comment"])]

            if remove_cover:
                if "covr" in audio.tags:
                    del audio.tags["covr"]
            elif cover_bytes:
                img_fmt = MP4Cover.FORMAT_PNG if "png" in cover_mime.lower() else MP4Cover.FORMAT_JPEG
                audio.tags["covr"] = [MP4Cover(cover_bytes, imageformat=img_fmt)]

            audio.save()

        elif ext == ".mp3":
            try:
                audio = MP3(file_path, ID3=ID3)
                if audio.tags is None:
                    audio.add_tags()
            except Exception:
                audio = MP3(file_path)
                audio.add_tags()

            if "title" in fields and fields["title"] is not None:
                audio.tags.setall("TIT2", [TIT2(encoding=3, text=str(fields["title"]))])
            if "artist" in fields and fields["artist"] is not None:
                audio.tags.setall("TPE1", [TPE1(encoding=3, text=str(fields["artist"]))])
            if "album" in fields and fields["album"] is not None:
                audio.tags.setall("TALB", [TALB(encoding=3, text=str(fields["album"]))])
            if "album_artist" in fields and fields["album_artist"] is not None:
                audio.tags.setall("TPE2", [TPE2(encoding=3, text=str(fields["album_artist"]))])
            if "genre" in fields and fields["genre"] is not None:
                audio.tags.setall("TCON", [TCON(encoding=3, text=str(fields["genre"]))])
            if "year" in fields and fields["year"] is not None:
                audio.tags.setall("TDRC", [TDRC(encoding=3, text=str(fields["year"]))])
            if "track_num" in fields and fields["track_num"] is not None:
                audio.tags.setall("TRCK", [TRCK(encoding=3, text=str(fields["track_num"]))])
            if "disc_num" in fields and fields["disc_num"] is not None:
                audio.tags.setall("TPOS", [TPOS(encoding=3, text=str(fields["disc_num"]))])
            if "lyrics" in fields and fields["lyrics"] is not None:
                audio.tags.setall("USLT", [USLT(encoding=3, lang="eng", desc="", text=str(fields["lyrics"]))])

            if remove_cover:
                audio.tags.delall("APIC")
            elif cover_bytes:
                audio.tags.delall("APIC")
                audio.tags.add(
                    APIC(
                        encoding=3,
                        mime=cover_mime,
                        type=3,
                        desc="Front Cover",
                        data=cover_bytes,
                    )
                )

            audio.save()
        else:
            raise MetadataEditorError(f"Unsupported audio format: {ext}")

    except Exception as e:
        if isinstance(e, MetadataEditorError):
            raise
        raise MetadataEditorError(f"Failed to update metadata for {file_path.name}: {e}") from e

    return {"status": "ok", "file": str(file_path)}


def batch_update_tracks(
    state: StateManager,
    music_dir: Path,
    track_ids: list[str],
    fields: dict[str, Any],
    cover_art_base64: Optional[str] = None,
    cover_art_mime: str = "image/jpeg",
    remove_cover: bool = False,
    reorganize_files: bool = True,
) -> dict[str, Any]:
    """Applies batch metadata updates and/or cover art replacement across multiple tracks.
    
    Synchronizes file system paths (if reorganized) and database state records atomically.
    """
    cover_bytes: Optional[bytes] = None
    if cover_art_base64 and not remove_cover:
        try:
            # Handle potential data URL prefix: "data:image/jpeg;base64,..."
            clean_b64 = cover_art_base64
            if "," in clean_b64:
                header, clean_b64 = clean_b64.split(",", 1)
                if "image/png" in header:
                    cover_mime = "image/png"
                elif "image/webp" in header:
                    cover_mime = "image/webp"
                elif "image/jpeg" in header or "image/jpg" in header:
                    cover_mime = "image/jpeg"
            cover_bytes = base64.b64decode(clean_b64)
        except (binascii.Error, ValueError) as err:
            raise MetadataEditorError(f"Invalid base64 cover artwork: {err}")

    updated_count = 0
    errors: list[str] = []
    updated_records: list[dict[str, Any]] = []

    for tid in track_ids:
        track = state.get_track(tid)
        if not track:
            errors.append(f"Track {tid} not found in database")
            continue

        if not track.local_path:
            errors.append(f"Track {tid} has no local file path")
            continue

        file_path = Path(track.local_path).expanduser().resolve()
        if not file_path.is_file():
            errors.append(f"File for track {tid} not found on disk: {track.local_path}")
            continue

        try:
            # 1. Update tags in audio file
            update_audio_tags(
                file_path=file_path,
                fields=fields,
                cover_bytes=cover_bytes,
                cover_mime=cover_art_mime,
                remove_cover=remove_cover,
            )

            # Determine updated metadata values
            new_title = str(fields["title"]) if "title" in fields and fields["title"] is not None else track.title
            new_artist = str(fields["artist"]) if "artist" in fields and fields["artist"] is not None else track.artist
            new_album = str(fields["album"]) if "album" in fields and fields["album"] is not None else track.album
            track_num = int(fields["track_num"]) if "track_num" in fields and fields["track_num"] is not None else 1

            new_local_path = file_path

            # 2. Reorganize files on disk if artist/album/title changed & reorganize is enabled
            if reorganize_files:
                target_dest = organizer.track_path(
                    music_dir=music_dir,
                    artist=new_artist,
                    album=new_album,
                    track_num=track_num,
                    title=new_title,
                    ext=file_path.suffix,
                )
                if target_dest != file_path:
                    target_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(file_path), str(target_dest))
                    new_local_path = target_dest

                    # Clean up old empty parent directory if safe
                    try:
                        old_parent = file_path.parent
                        if old_parent.is_dir() and not any(old_parent.iterdir()):
                            old_parent.rmdir()
                    except OSError:
                        pass

            # 3. Update database record
            state.update_track_metadata(
                track_id=tid,
                title=new_title,
                artist=new_artist,
                album=new_album,
                local_path=str(new_local_path),
            )

            updated_records.append({
                "track_id": tid,
                "title": new_title,
                "artist": new_artist,
                "album": new_album,
                "local_path": str(new_local_path),
            })
            updated_count += 1

        except Exception as e:
            errors.append(f"Failed updating track {tid} ({file_path.name}): {e}")

    return {
        "updated": updated_count,
        "total_requested": len(track_ids),
        "errors": errors,
        "tracks": updated_records,
    }
