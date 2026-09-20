import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Track:
    track_id: str
    title: str
    artist: str
    album: str
    local_path: str
    downloaded_at: str
    artwork_url: Optional[str] = None
    am_track_id: Optional[str] = None


@dataclass
class Playlist:
    name: str
    url: str
    last_synced: Optional[str]
    paused: bool = False


@dataclass
class SyncRun:
    id: int
    playlist_name: str
    started_at: str
    ended_at: str
    status: str  # "success" | "error"
    new_count: int
    skipped_count: int
    error_count: int
    log_path: str
    error_message: Optional[str]


class StateManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        # A local desktop app can have overlapping UI and sync requests. Bound
        # SQLite's lock wait so a busy database cannot leave an API request
        # stuck indefinitely.
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    track_id    TEXT PRIMARY KEY,
                    title       TEXT NOT NULL,
                    artist      TEXT NOT NULL,
                    album       TEXT NOT NULL,
                    local_path  TEXT NOT NULL,
                    downloaded_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS playlists (
                    name        TEXT PRIMARY KEY,
                    url         TEXT NOT NULL,
                    last_synced TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS playlist_tracks (
                    playlist_name TEXT NOT NULL,
                    track_id      TEXT NOT NULL,
                    PRIMARY KEY (playlist_name, track_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_runs (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_name TEXT NOT NULL,
                    started_at    TEXT NOT NULL,
                    ended_at      TEXT NOT NULL,
                    status        TEXT NOT NULL,
                    new_count     INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    error_count   INTEGER NOT NULL DEFAULT 0,
                    log_path      TEXT NOT NULL,
                    error_message TEXT
                )
            """)
            # Migrations
            cols = {r[1] for r in conn.execute("PRAGMA table_info(playlists)")}
            if "paused" not in cols:
                conn.execute("ALTER TABLE playlists ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")
            if "staging_folder" not in cols:
                conn.execute("ALTER TABLE playlists ADD COLUMN staging_folder TEXT")
            # am_track_id migration
            track_cols = {r[1] for r in conn.execute("PRAGMA table_info(tracks)")}
            if "am_track_id" not in track_cols:
                conn.execute("ALTER TABLE tracks ADD COLUMN am_track_id TEXT")
            if "artwork_url" not in track_cols:
                conn.execute("ALTER TABLE tracks ADD COLUMN artwork_url TEXT")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recommendation_exclusions (
                    artist TEXT PRIMARY KEY
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recommendation_genres (
                    genre TEXT PRIMARY KEY
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS waveform_cache (
                    track_id    TEXT PRIMARY KEY,
                    peaks_json  TEXT NOT NULL,
                    extracted_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recommendation_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS delisted_tracks (
                    playlist_name TEXT NOT NULL,
                    track_id      TEXT NOT NULL,
                    delisted_at   TEXT NOT NULL,
                    PRIMARY KEY (playlist_name, track_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS smart_playlists (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT UNIQUE NOT NULL,
                    description   TEXT,
                    rules_json    TEXT NOT NULL,
                    created_at    TEXT NOT NULL,
                    updated_at    TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_queue (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id       TEXT,
                    batch_title    TEXT,
                    url            TEXT NOT NULL,
                    title          TEXT NOT NULL,
                    artist         TEXT NOT NULL DEFAULT '',
                    album          TEXT NOT NULL DEFAULT '',
                    artwork_url    TEXT,
                    format         TEXT NOT NULL DEFAULT 'ALAC',
                    status         TEXT NOT NULL DEFAULT 'pending',
                    item_type      TEXT NOT NULL DEFAULT 'album',
                    total_tracks   INTEGER NOT NULL DEFAULT 0,
                    new_tracks     INTEGER NOT NULL DEFAULT 0,
                    skipped_tracks INTEGER NOT NULL DEFAULT 0,
                    error_count    INTEGER NOT NULL DEFAULT 0,
                    error_message  TEXT,
                    log_path       TEXT,
                    position       INTEGER NOT NULL DEFAULT 0,
                    created_at     TEXT NOT NULL,
                    started_at     TEXT,
                    completed_at   TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_download_queue_status_pos ON download_queue (status, position, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_download_queue_batch ON download_queue (batch_id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audio_waveforms (
                    track_id    TEXT PRIMARY KEY,
                    points      INTEGER NOT NULL,
                    duration    REAL NOT NULL,
                    peaks_json  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                )
            """)

    def auto_rebase_paths(self, current_music_dir: Path) -> int:
        """
        If track records point to a previous host path (e.g. kio-fuse SMB or local directory)
        rebase their local_path to match current_music_dir.
        """
        music_str = str(current_music_dir.resolve())
        updated = 0
        with self._conn() as conn:
            rows = conn.execute("SELECT track_id, local_path FROM tracks WHERE local_path NOT LIKE ? || '%'", (music_str,)).fetchall()
            for tid, path_str in rows:
                if "/artists/" in path_str:
                    rel_part = "artists/" + path_str.split("/artists/", 1)[1]
                    new_path = current_music_dir / rel_part
                    conn.execute("UPDATE tracks SET local_path = ? WHERE track_id = ?", (str(new_path), tid))
                    updated += 1
        return updated

    def create_smart_playlist(self, name: str, description: Optional[str], rules_json: str) -> dict:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO smart_playlists (name, description, rules_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (name, description, rules_json, now, now),
            )
            sp_id = cur.lastrowid
        return {
            "id": sp_id,
            "name": name,
            "description": description,
            "rules_json": rules_json,
            "created_at": now,
            "updated_at": now,
        }

    def get_smart_playlists(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, name, description, rules_json, created_at, updated_at FROM smart_playlists ORDER BY name ASC"
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "description": r[2],
                    "rules_json": r[3],
                    "created_at": r[4],
                    "updated_at": r[5],
                }
                for r in rows
            ]

    def get_smart_playlist(self, sp_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, name, description, rules_json, created_at, updated_at FROM smart_playlists WHERE id = ?",
                (sp_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "rules_json": row[3],
                "created_at": row[4],
                "updated_at": row[5],
            }

    def get_smart_playlist_by_name(self, name: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, name, description, rules_json, created_at, updated_at FROM smart_playlists WHERE name = ?",
                (name,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "rules_json": row[3],
                "created_at": row[4],
                "updated_at": row[5],
            }

    def update_smart_playlist(self, sp_id: int, name: Optional[str] = None, description: Optional[str] = None, rules_json: Optional[str] = None) -> Optional[dict]:
        existing = self.get_smart_playlist(sp_id)
        if not existing:
            return None
        new_name = name if name is not None else existing["name"]
        new_desc = description if description is not None else existing["description"]
        new_rules = rules_json if rules_json is not None else existing["rules_json"]
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE smart_playlists SET name = ?, description = ?, rules_json = ?, updated_at = ? WHERE id = ?",
                (new_name, new_desc, new_rules, now, sp_id),
            )
        return {
            "id": sp_id,
            "name": new_name,
            "description": new_desc,
            "rules_json": new_rules,
            "created_at": existing["created_at"],
            "updated_at": now,
        }

    def delete_smart_playlist(self, sp_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM smart_playlists WHERE id = ?", (sp_id,))
            return cur.rowcount > 0

    def record_delisted_track(self, playlist_name: str, track_id: str, delisted_at: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO delisted_tracks (playlist_name, track_id, delisted_at) VALUES (?, ?, ?)",
                (playlist_name, track_id, delisted_at),
            )

    def clear_delisted_track(self, playlist_name: str, track_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM delisted_tracks WHERE playlist_name = ? AND track_id = ?",
                (playlist_name, track_id),
            )

    def get_delisted_track_ids(self, playlist_name: str) -> set[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT track_id FROM delisted_tracks WHERE playlist_name = ?",
                (playlist_name,),
            ).fetchall()
            return {r[0] for r in rows}

    def get_delisted_tracks(self, playlist_name: Optional[str] = None) -> list[dict]:
        with self._conn() as conn:
            if playlist_name:
                rows = conn.execute("""
                    SELECT d.playlist_name, d.track_id, d.delisted_at, t.title, t.artist, t.album, t.local_path, t.artwork_url
                    FROM delisted_tracks d
                    JOIN tracks t ON d.track_id = t.track_id
                    WHERE d.playlist_name = ?
                    ORDER BY d.delisted_at DESC
                """, (playlist_name,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT d.playlist_name, d.track_id, d.delisted_at, t.title, t.artist, t.album, t.local_path, t.artwork_url
                    FROM delisted_tracks d
                    JOIN tracks t ON d.track_id = t.track_id
                    ORDER BY d.delisted_at DESC
                """).fetchall()

            return [
                {
                    "playlist_name": r[0],
                    "track_id": r[1],
                    "delisted_at": r[2],
                    "title": r[3],
                    "artist": r[4],
                    "album": r[5],
                    "local_path": r[6],
                    "artwork_url": r[7],
                }
                for r in rows
            ]

    def is_downloaded(self, track_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM tracks WHERE track_id = ?", (track_id,)
            ).fetchone()
            return row is not None


    def get_track(self, track_id: str) -> Optional[Track]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT track_id, title, artist, album, local_path, downloaded_at, artwork_url, am_track_id FROM tracks WHERE track_id = ?",
                (track_id,),
            ).fetchone()
            if not row:
                return None
            return Track(
                track_id=row[0],
                title=row[1],
                artist=row[2],
                album=row[3],
                local_path=row[4],
                downloaded_at=row[5],
                artwork_url=row[6],
                am_track_id=row[7] if len(row) > 7 else None,
            )

    def get_track_by_path(self, path: str) -> Optional[Track]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT track_id, title, artist, album, local_path, downloaded_at, artwork_url, am_track_id FROM tracks WHERE local_path = ?",
                (path,)
            ).fetchone()
            if not row:
                p_obj = Path(path)
                row = conn.execute(
                    "SELECT track_id, title, artist, album, local_path, downloaded_at, artwork_url, am_track_id FROM tracks WHERE local_path LIKE ? OR local_path LIKE ?",
                    (f"%{p_obj.name}", f"%{p_obj.parent.name}/{p_obj.name}")
                ).fetchone()
            if row:
                return Track(
                    track_id=row[0],
                    title=row[1],
                    artist=row[2],
                    album=row[3],
                    local_path=row[4],
                    downloaded_at=row[5],
                    artwork_url=row[6],
                    am_track_id=row[7] if len(row) > 7 else None,
                )
            return None

    def update_track_local_path(self, track_id: str, new_path: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE tracks SET local_path = ? WHERE track_id = ?",
                (new_path, track_id)
            )


    def add_track(self, track: Track) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tracks (track_id, title, artist, album, local_path, downloaded_at, artwork_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (track.track_id, track.title, track.artist,
                 track.album, track.local_path, track.downloaded_at, track.artwork_url),
            )

    def add_track_to_playlist(self, playlist_name: str, track_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO playlist_tracks VALUES (?, ?)",
                (playlist_name, track_id),
            )

    def find_and_associate_existing_tracks_to_playlist(self, playlist_name: str, am_tracks: list[dict]) -> int:
        """Ensure all tracks present in am_tracks that already exist in library are linked to playlist."""
        if not am_tracks:
            return 0
        count = 0
        with self._conn() as conn:
            # 1. Direct match on am_track_id
            am_ids = [str(t["id"]) for t in am_tracks if t.get("id")]
            if am_ids:
                placeholders = ",".join("?" * len(am_ids))
                rows = conn.execute(
                    f"SELECT track_id, am_track_id FROM tracks WHERE am_track_id IN ({placeholders})",
                    am_ids
                ).fetchall()
                for (tid, am_id) in rows:
                    res = conn.execute(
                        "INSERT OR IGNORE INTO playlist_tracks VALUES (?, ?)",
                        (playlist_name, tid)
                    )
                    if res.rowcount > 0:
                        count += 1
            # 2. Match by normalized title + artist
            all_rows = conn.execute("SELECT track_id, title, artist FROM tracks").fetchall()
            lib_by_key: dict[tuple[str, str], str] = {}
            for tid, t_title, t_artist in all_rows:
                k = (t_title.strip().lower(), t_artist.strip().lower())
                lib_by_key[k] = tid
            for t in am_tracks:
                k = (str(t.get("title", "")).strip().lower(), str(t.get("artist", "")).strip().lower())
                if k in lib_by_key:
                    res = conn.execute(
                        "INSERT OR IGNORE INTO playlist_tracks VALUES (?, ?)",
                        (playlist_name, lib_by_key[k])
                    )
                    if res.rowcount > 0:
                        count += 1

            # 3. Match and repair unparsed tracks only by EXACT normalized title match
            import re
            unknown_rows = conn.execute(
                "SELECT track_id, title, local_path FROM tracks WHERE artist = 'Unknown Artist' OR album = 'Unknown Album' OR title LIKE '%. %'"
            ).fetchall()
            for tid, t_title, lpath in unknown_rows:
                clean_t = re.sub(r"^\d+\.\s*", "", t_title).strip().lower()
                if not clean_t:
                    continue
                for t in am_tracks:
                    am_t = str(t.get("title", "")).strip().lower()
                    if clean_t == am_t:
                        conn.execute(
                            "UPDATE tracks SET title = ?, artist = ?, album = ?, am_track_id = ? WHERE track_id = ?",
                            (t.get("title", clean_t), t.get("artist", "Unknown Artist"), t.get("album", "Unknown Album"), str(t.get("id", "")), tid)
                        )
                        res = conn.execute(
                            "INSERT OR IGNORE INTO playlist_tracks VALUES (?, ?)",
                            (playlist_name, tid)
                        )
                        if res.rowcount > 0:
                            count += 1
                        break
        return count

    def find_existing_am_track_ids(self, am_tracks: list[dict]) -> set[str]:
        """Return set of Apple Music track IDs from am_tracks that already exist in the local library."""
        if not am_tracks:
            return set()
        existing_ids: set[str] = set()
        with self._conn() as conn:
            # 1. Direct match by am_track_id
            am_ids = [str(t["id"]) for t in am_tracks if t.get("id")]
            if am_ids:
                placeholders = ",".join("?" * len(am_ids))
                rows = conn.execute(
                    f"SELECT am_track_id FROM tracks WHERE am_track_id IN ({placeholders})",
                    am_ids,
                ).fetchall()
                for (am_id,) in rows:
                    if am_id:
                        existing_ids.add(str(am_id))

            # 2. Match by normalized title + artist
            all_rows = conn.execute("SELECT track_id, title, artist, album, am_track_id FROM tracks").fetchall()
            lib_by_key: dict[tuple[str, str], tuple[str, Optional[str]]] = {}
            for tid, t_title, t_artist, t_album, db_am_id in all_rows:
                k = (t_title.strip().lower(), t_artist.strip().lower())
                lib_by_key[k] = (tid, db_am_id)

            updates: list[tuple[str, str]] = []
            for t in am_tracks:
                t_id = str(t.get("id", ""))
                if not t_id or t_id in existing_ids:
                    continue
                k = (str(t.get("title", "")).strip().lower(), str(t.get("artist", "")).strip().lower())
                if k in lib_by_key:
                    tid, db_am_id = lib_by_key[k]
                    existing_ids.add(t_id)
                    if not db_am_id:
                        updates.append((t_id, tid))

            if updates:
                conn.executemany(
                    "UPDATE tracks SET am_track_id = ? WHERE track_id = ? AND (am_track_id IS NULL OR am_track_id = '')",
                    updates,
                )

        return existing_ids

    def get_playlist_tracks(self, playlist_name: str) -> list[Track]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT t.track_id, t.title, t.artist, t.album,
                       t.local_path, t.downloaded_at, t.artwork_url
                FROM tracks t
                JOIN playlist_tracks pt ON t.track_id = pt.track_id
                WHERE pt.playlist_name = ?
                ORDER BY t.artist, t.album, t.title
                """,
                (playlist_name,),
            ).fetchall()
            return [Track(*r) for r in rows]

    def get_duplicate_tracks_in_playlist(self, playlist_name: str) -> list[dict]:
        """Find tracks with identical title and artist in the given playlist."""
        tracks = self.get_playlist_tracks(playlist_name)
        seen: dict[tuple[str, str], list[Track]] = {}
        for t in tracks:
            key = (t.title.strip().lower(), t.artist.strip().lower())
            seen.setdefault(key, []).append(t)
        duplicates: list[dict] = []
        for key, track_list in seen.items():
            if len(track_list) > 1:
                duplicates.append({
                    "title": track_list[0].title,
                    "artist": track_list[0].artist,
                    "album": track_list[0].album,
                    "count": len(track_list),
                    "track_ids": [t.track_id for t in track_list],
                    "tracks": [
                        {
                            "track_id": t.track_id,
                            "title": t.title,
                            "artist": t.artist,
                            "album": t.album,
                            "local_path": t.local_path,
                            "artwork_url": t.artwork_url,
                        }
                        for t in track_list
                    ],
                })
        return duplicates

    def deduplicate_playlist(self, playlist_name: str) -> dict:
        """Remove duplicate tracks (matching title and artist) preserving the first occurrence."""
        duplicates = self.get_duplicate_tracks_in_playlist(playlist_name)
        removed_track_ids: list[str] = []
        with self._conn() as conn:
            for item in duplicates:
                # Keep first track_id, delete remaining
                for duplicate_id in item["track_ids"][1:]:
                    conn.execute(
                        "DELETE FROM playlist_tracks WHERE playlist_name = ? AND track_id = ?",
                        (playlist_name, duplicate_id),
                    )
                    removed_track_ids.append(duplicate_id)
        return {
            "status": "ok",
            "playlist_name": playlist_name,
            "duplicates_found": len(duplicates),
            "removed_count": len(removed_track_ids),
            "removed_track_ids": removed_track_ids,
        }

    def has_track_path(self, path: Path) -> bool:
        """Return whether *path* belongs to a track recorded by this library."""
        target = path.resolve()
        target_str = str(target)
        with self._conn() as conn:
            paths = conn.execute("SELECT local_path FROM tracks").fetchall()
        for (stored_path,) in paths:
            try:
                if not stored_path:
                    continue
                p_stored = Path(stored_path).expanduser().resolve()
                if p_stored == target:
                    return True
                for anchor in ("/artists/", "/playlists/", "artists/", "playlists/"):
                    if anchor in stored_path and anchor in target_str:
                        if stored_path.split(anchor, 1)[1] == target_str.split(anchor, 1)[1]:
                            return True
            except (OSError, RuntimeError):
                continue
        return False

    def add_playlist(self, name: str, url: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO playlists (name, url, last_synced) VALUES (?, ?, NULL)",
                (name, url),
            )

    def delete_playlist(self, name: str) -> None:
        """Remove a playlist and only the records that belong to it."""
        with self._conn() as conn:
            conn.execute("DELETE FROM playlist_tracks WHERE playlist_name = ?", (name,))
            conn.execute("DELETE FROM sync_runs WHERE playlist_name = ?", (name,))
            conn.execute("DELETE FROM playlists WHERE name = ?", (name,))

    def get_playlists(self) -> list[Playlist]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, url, last_synced, paused FROM playlists"
            ).fetchall()
            return [Playlist(name=r[0], url=r[1], last_synced=r[2], paused=bool(r[3])) for r in rows]

    def rename_playlist(self, old_name: str, new_name: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE playlist_tracks SET playlist_name = ? WHERE playlist_name = ?", (new_name, old_name))
            conn.execute("UPDATE sync_runs SET playlist_name = ? WHERE playlist_name = ?", (new_name, old_name))
            conn.execute("UPDATE playlists SET name = ? WHERE name = ?", (new_name, old_name))

    def set_playlist_paused(self, name: str, paused: bool) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE playlists SET paused = ? WHERE name = ?", (int(paused), name))

    def update_playlist_synced(self, name: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE playlists SET last_synced = ? WHERE name = ?",
                (datetime.now().isoformat(), name),
            )

    def get_playlist_am_ids(self, playlist_name: str) -> set[str]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT t.am_track_id
                FROM tracks t
                JOIN playlist_tracks pt ON t.track_id = pt.track_id
                WHERE pt.playlist_name = ? AND t.am_track_id IS NOT NULL
                """,
                (playlist_name,),
            ).fetchall()
            return {r[0] for r in rows}

    def get_playlist_am_track_mapping(self, playlist_name: str) -> list[tuple[str, str]]:
        """Return (track_id, am_track_id) pairs for a playlist."""
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT pt.track_id, t.am_track_id
                FROM playlist_tracks pt
                JOIN tracks t ON pt.track_id = t.track_id
                WHERE pt.playlist_name = ? AND t.am_track_id IS NOT NULL
                """,
                (playlist_name,),
            ).fetchall()

    def bulk_record_delisted_tracks(self, records: list[tuple[str, str, str]]) -> None:
        """Insert or replace multiple delisted tracks (playlist_name, track_id, delisted_at)."""
        if not records:
            return
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO delisted_tracks (playlist_name, track_id, delisted_at) VALUES (?, ?, ?)",
                records,
            )

    def bulk_clear_delisted_tracks(self, playlist_name: str, track_ids: list[str]) -> None:
        """Clear multiple delisted tracks in a single batch."""
        if not track_ids:
            return
        with self._conn() as conn:
            conn.executemany(
                "DELETE FROM delisted_tracks WHERE playlist_name = ? AND track_id = ?",
                [(playlist_name, tid) for tid in track_ids],
            )

    def bulk_update_track_am_ids(self, updates: list[tuple[str, str]]) -> None:
        """Batch update (am_track_id, track_id) pairs."""
        if not updates:
            return
        with self._conn() as conn:
            conn.executemany(
                "UPDATE tracks SET am_track_id = ? WHERE track_id = ?",
                updates,
            )

    def update_track_am_id(self, track_id: str, am_track_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE tracks SET am_track_id = ? WHERE track_id = ?",
                (am_track_id, track_id),
            )

    def update_track_artwork(self, track_id: str, artwork_url: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE tracks SET artwork_url = ? WHERE track_id = ?",
                (artwork_url, track_id),
            )

    def update_track_metadata(
        self,
        track_id: str,
        title: str,
        artist: str,
        album: str,
        local_path: Optional[str] = None,
    ) -> None:
        with self._conn() as conn:
            if local_path:
                conn.execute(
                    """
                    UPDATE tracks
                    SET title = ?, artist = ?, album = ?, local_path = ?
                    WHERE track_id = ?
                    """,
                    (title, artist, album, local_path, track_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE tracks
                    SET title = ?, artist = ?, album = ?
                    WHERE track_id = ?
                    """,
                    (title, artist, album, track_id),
                )


    def get_playlist_tracks_without_am_id(self, playlist_name: str) -> list[Track]:
        """Return tracks in a playlist that have no AM track ID yet."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT t.track_id, t.title, t.artist, t.album,
                       t.local_path, t.downloaded_at, t.artwork_url
                FROM tracks t
                JOIN playlist_tracks pt ON t.track_id = pt.track_id
                WHERE pt.playlist_name = ? AND t.am_track_id IS NULL
                ORDER BY t.artist, t.album, t.title
                """,
                (playlist_name,),
            ).fetchall()
            return [Track(*r) for r in rows]

    def get_downloaded_count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]

    def record_sync_run(
        self,
        playlist_name: str,
        started_at: str,
        ended_at: str,
        status: str,
        new_count: int,
        skipped_count: int,
        error_count: int,
        log_path: str,
        error_message: Optional[str] = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sync_runs
                   (playlist_name, started_at, ended_at, status,
                    new_count, skipped_count, error_count, log_path, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (playlist_name, started_at, ended_at, status,
                 new_count, skipped_count, error_count, log_path, error_message),
            )

    def get_recent_runs(self, playlist_name: Optional[str] = None, limit: int = 20) -> list[SyncRun]:
        with self._conn() as conn:
            if playlist_name is not None:
                rows = conn.execute(
                    """SELECT id, playlist_name, started_at, ended_at, status,
                              new_count, skipped_count, error_count, log_path, error_message
                       FROM sync_runs WHERE playlist_name = ?
                       ORDER BY started_at DESC LIMIT ?""",
                    (playlist_name, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, playlist_name, started_at, ended_at, status,
                              new_count, skipped_count, error_count, log_path, error_message
                       FROM sync_runs ORDER BY started_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [SyncRun(*r) for r in rows]

    def store_artwork(self, track_id: str, artwork_url: str) -> None:
        """Store or update artwork URL for a specific track by track_id."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE tracks SET artwork_url = ? WHERE track_id = ?",
                (artwork_url, track_id),
            )

    def bulk_store_artwork(self, artwork_map: dict[str, str]) -> None:
        """Store artwork URLs for tracks matched by am_track_id. Only fills nulls."""
        with self._conn() as conn:
            conn.executemany(
                "UPDATE tracks SET artwork_url = ? WHERE am_track_id = ? AND artwork_url IS NULL",
                [(url, am_id) for am_id, url in artwork_map.items()],
            )

    def get_recent_tracks(self, limit: int = 5) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT title, artist, album, local_path, artwork_url, downloaded_at
                   FROM tracks ORDER BY downloaded_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "title": r[0], "artist": r[1], "album": r[2],
                "local_path": r[3], "artwork_url": r[4], "downloaded_at": r[5],
            }
            for r in rows
        ]

    def get_tracks_in_run(self, playlist_name: str, started_at: str, ended_at: str) -> list[dict]:
        """Tracks downloaded during a specific sync run window."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.title, t.artist, t.album, t.local_path, t.artwork_url, t.downloaded_at
                   FROM tracks t
                   JOIN playlist_tracks pt ON t.track_id = pt.track_id
                   WHERE pt.playlist_name = ?
                     AND t.downloaded_at >= ?
                     AND t.downloaded_at <= ?
                   ORDER BY t.downloaded_at DESC""",
                (playlist_name, started_at, ended_at),
            ).fetchall()
        return [
            {
                "title": r[0], "artist": r[1], "album": r[2],
                "local_path": r[3], "artwork_url": r[4], "downloaded_at": r[5],
            }
            for r in rows
        ]

    def get_top_artists(self, limit: int = 10) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT artist, COUNT(*) AS cnt FROM tracks GROUP BY artist ORDER BY cnt DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [r[0] for r in rows]

    def get_all_artists(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT DISTINCT artist FROM tracks").fetchall()
        return [r[0] for r in rows]

    def get_recommendation_exclusions(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT artist FROM recommendation_exclusions").fetchall()
        return [row[0] for row in rows]

    def exclude_recommendation_artist(self, artist: str) -> None:
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO recommendation_exclusions (artist) VALUES (?)", (artist,))

    def include_recommendation_artist(self, artist: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM recommendation_exclusions WHERE artist = ?", (artist,))

    def clear_recommendation_exclusions(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM recommendation_exclusions")

    def get_recommendation_genres(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT genre FROM recommendation_genres ORDER BY genre").fetchall()
        return [row[0] for row in rows]

    def set_recommendation_genres(self, genres: list[str]) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM recommendation_genres")
            conn.executemany(
                "INSERT INTO recommendation_genres (genre) VALUES (?)",
                [(genre,) for genre in genres],
            )

    def get_recommendation_cache(self) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload, updated_at FROM recommendation_cache WHERE cache_key = 'home'"
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return None
        return {**payload, "updated_at": row[1]}

    def set_recommendation_cache(self, payload: dict) -> None:
        updated_at = datetime.now().astimezone().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO recommendation_cache (cache_key, payload, updated_at) VALUES ('home', ?, ?)",
                (json.dumps(payload), updated_at),
            )

    def get_library_profile(self) -> dict:
        with self._conn() as conn:
            artist_rows = conn.execute(
                "SELECT artist, COUNT(*) FROM tracks GROUP BY artist ORDER BY COUNT(*) DESC, artist LIMIT 200"
            ).fetchall()
            album_rows = conn.execute(
                "SELECT artist, album, COUNT(*) FROM tracks GROUP BY artist, album ORDER BY COUNT(*) DESC, artist, album LIMIT 200"
            ).fetchall()
            track_count = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        return {
            "track_count": track_count,
            "artists": [{"name": artist, "track_count": count} for artist, count in artist_rows],
            "albums": [
                {"artist": artist, "name": album, "track_count": count}
                for artist, album, count in album_rows
            ],
        }

    def get_playlist_thumbnail(self, playlist_name: str) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT t.artwork_url FROM tracks t
                JOIN playlist_tracks pt ON t.track_id = pt.track_id
                WHERE pt.playlist_name = ? AND t.artwork_url IS NOT NULL
                LIMIT 1
                """,
                (playlist_name,),
            ).fetchone()
            return row[0] if row else None

    def get_all_tracks_with_provenance(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT t.track_id, t.title, t.artist, t.album, t.local_path, t.downloaded_at,
                       t.artwork_url, t.am_track_id,
                       GROUP_CONCAT(pt.playlist_name, '|||') AS playlists
                FROM tracks t
                LEFT JOIN playlist_tracks pt ON t.track_id = pt.track_id
                GROUP BY t.track_id
                ORDER BY t.downloaded_at DESC, t.artist, t.album, t.title
            """).fetchall()
            result = []
            for r in rows:
                pl_raw = r[8]
                playlists = [p for p in pl_raw.split("|||") if p] if pl_raw else []
                result.append({
                    "track_id": r[0],
                    "title": r[1],
                    "artist": r[2],
                    "album": r[3],
                    "local_path": r[4],
                    "downloaded_at": r[5],
                    "artwork_url": r[6],
                    "am_track_id": r[7],
                    "playlists": sorted(playlists),
                })
            return result

    def get_library_stats(self) -> dict:
        with self._conn() as conn:
            total_tracks = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
            total_albums = conn.execute("SELECT COUNT(DISTINCT album) FROM tracks").fetchone()[0]
            total_artists = conn.execute("SELECT COUNT(DISTINCT artist) FROM tracks").fetchone()[0]
            total_playlists = conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0]
            delisted_count = conn.execute("SELECT COUNT(*) FROM delisted_tracks").fetchone()[0]
            local_paths = [r[0] for r in conn.execute("SELECT local_path FROM tracks").fetchall()]

        total_bytes = 0
        for lp in local_paths:
            try:
                p = Path(lp).expanduser().resolve()
                if p.is_file():
                    total_bytes += p.stat().st_size
            except (OSError, RuntimeError):
                pass

        return {
            "total_tracks": total_tracks,
            "total_albums": total_albums,
            "total_artists": total_artists,
            "total_playlists": total_playlists,
            "delisted_count": delisted_count,
            "total_bytes": total_bytes,
        }

    def prune_missing_tracks(self, missing_track_ids: list[str]) -> int:
        if not missing_track_ids:
            return 0
        unique_ids = list(set(missing_track_ids))
        deleted_count = 0
        with self._conn() as conn:
            for chunk_start in range(0, len(unique_ids), 500):
                chunk = unique_ids[chunk_start:chunk_start + 500]
                placeholders = ",".join("?" for _ in chunk)
                conn.execute(f"DELETE FROM playlist_tracks WHERE track_id IN ({placeholders})", chunk)
                conn.execute(f"DELETE FROM delisted_tracks WHERE track_id IN ({placeholders})", chunk)
                cur = conn.execute(f"DELETE FROM tracks WHERE track_id IN ({placeholders})", chunk)
                deleted_count += cur.rowcount
        return deleted_count

    def remap_and_remove_tracks(self, remap_pairs: list[tuple[str, str]], remove_track_ids: list[str]) -> tuple[int, int]:
        """
        Remap duplicate track references in playlist_tracks to primary track IDs,
        then delete the duplicate tracks from database.
        Returns: (remapped_count, deleted_count)
        """
        remapped_count = 0
        deleted_count = 0
        with self._conn() as conn:
            # 1. Remap playlists
            for old_id, new_id in remap_pairs:
                if old_id == new_id:
                    continue
                playlists = conn.execute(
                    "SELECT playlist_name FROM playlist_tracks WHERE track_id = ?",
                    (old_id,)
                ).fetchall()
                for (pl_name,) in playlists:
                    conn.execute(
                        "INSERT OR IGNORE INTO playlist_tracks (playlist_name, track_id) VALUES (?, ?)",
                        (pl_name, new_id)
                    )
                    conn.execute(
                        "DELETE FROM playlist_tracks WHERE playlist_name = ? AND track_id = ?",
                        (pl_name, old_id)
                    )
                    remapped_count += 1

            # 2. Delete duplicate tracks
            if remove_track_ids:
                unique_ids = list(set(remove_track_ids))
                for chunk_start in range(0, len(unique_ids), 500):
                    chunk = unique_ids[chunk_start:chunk_start + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    conn.execute(f"DELETE FROM playlist_tracks WHERE track_id IN ({placeholders})", chunk)
                    conn.execute(f"DELETE FROM delisted_tracks WHERE track_id IN ({placeholders})", chunk)
                    conn.execute(f"DELETE FROM audio_waveforms WHERE track_id IN ({placeholders})", chunk)
                    cur = conn.execute(f"DELETE FROM tracks WHERE track_id IN ({placeholders})", chunk)
                    deleted_count += cur.rowcount
        return remapped_count, deleted_count

    def get_waveform(self, track_id: str, points: int = 100) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT points, duration, peaks_json FROM audio_waveforms WHERE track_id = ?",
                (track_id,),
            ).fetchone()
            if not row:
                return None
            cached_points, duration, peaks_json = row
            if cached_points == points:
                try:
                    peaks = json.loads(peaks_json)
                    return {
                        "track_id": track_id,
                        "points": cached_points,
                        "duration": duration,
                        "peaks": peaks,
                    }
                except Exception:
                    return None
            return None

    def save_waveform(self, track_id: str, points: int, duration: float, peaks: list[float]) -> dict:
        now = datetime.now().isoformat()
        peaks_json = json.dumps(peaks)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO audio_waveforms (track_id, points, duration, peaks_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(track_id) DO UPDATE SET
                    points = excluded.points,
                    duration = excluded.duration,
                    peaks_json = excluded.peaks_json,
                    updated_at = excluded.updated_at
                """,
                (track_id, points, duration, peaks_json, now),
            )
        return {
            "track_id": track_id,
            "points": points,
            "duration": duration,
            "peaks": peaks,
        }

    def delete_waveform(self, track_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM audio_waveforms WHERE track_id = ?", (track_id,))
            return cur.rowcount > 0

    # ── Download Queue (Persistent SQLite Queue) ──────────────────────────────

    def enqueue_download_job(
        self,
        url: str,
        title: str,
        artist: str = "",
        album: str = "",
        artwork_url: Optional[str] = None,
        format: str = "ALAC",
        item_type: str = "album",
        batch_id: Optional[str] = None,
        batch_title: Optional[str] = None,
        total_tracks: int = 0,
    ) -> int:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            max_pos = conn.execute("SELECT COALESCE(MAX(position), 0) FROM download_queue WHERE status = 'pending'").fetchone()[0]
            cur = conn.execute(
                """
                INSERT INTO download_queue (
                    batch_id, batch_title, url, title, artist, album, artwork_url,
                    format, status, item_type, total_tracks, position, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (batch_id, batch_title, url, title, artist, album, artwork_url,
                 format, item_type, total_tracks, max_pos + 1, now),
            )
            return cur.lastrowid

    def bulk_enqueue_download_jobs(self, jobs: list[dict]) -> list[int]:
        if not jobs:
            return []
        now = datetime.now().isoformat()
        job_ids = []
        with self._conn() as conn:
            max_pos = conn.execute("SELECT COALESCE(MAX(position), 0) FROM download_queue WHERE status = 'pending'").fetchone()[0]
            for i, j in enumerate(jobs):
                cur = conn.execute(
                    """
                    INSERT INTO download_queue (
                        batch_id, batch_title, url, title, artist, album, artwork_url,
                        format, status, item_type, total_tracks, position, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (
                        j.get("batch_id"),
                        j.get("batch_title"),
                        j["url"],
                        j["title"],
                        j.get("artist", ""),
                        j.get("album", ""),
                        j.get("artwork_url"),
                        j.get("format", "ALAC"),
                        j.get("item_type", "album"),
                        j.get("total_tracks", 0),
                        max_pos + 1 + i,
                        now,
                    ),
                )
                job_ids.append(cur.lastrowid)
        return job_ids

    def get_next_pending_job(self) -> Optional[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM download_queue
                WHERE status = 'pending'
                ORDER BY position ASC, id ASC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None

    def get_queue_job(self, job_id: int) -> Optional[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM download_queue WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def get_queue_jobs(
        self,
        status: Optional[str] = None,
        batch_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        query = "SELECT * FROM download_queue WHERE 1=1"
        params: list[object] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if batch_id:
            query += " AND batch_id = ?"
            params.append(batch_id)

        # Sort running first, then pending by position, then completed by completed_at desc
        query += """
            ORDER BY
                CASE status
                    WHEN 'running' THEN 1
                    WHEN 'pending' THEN 2
                    WHEN 'error' THEN 3
                    ELSE 4
                END,
                position ASC,
                id ASC
            LIMIT ?
        """
        params.append(limit)

        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_queue_summary(self) -> dict:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            active_row = conn.execute(
                "SELECT * FROM download_queue WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()

            counts = dict(conn.execute(
                "SELECT status, COUNT(*) FROM download_queue GROUP BY status"
            ).fetchall())

            pending_jobs = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM download_queue WHERE status = 'pending' ORDER BY position ASC, id ASC LIMIT 50"
                ).fetchall()
            ]

            recent_completed = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM download_queue WHERE status IN ('done', 'error', 'cancelled') ORDER BY id DESC LIMIT 20"
                ).fetchall()
            ]

            return {
                "active": dict(active_row) if active_row else None,
                "pending": pending_jobs,
                "completed": recent_completed,
                "counts": {
                    "pending": counts.get("pending", 0),
                    "running": counts.get("running", 0),
                    "done": counts.get("done", 0),
                    "error": counts.get("error", 0),
                    "cancelled": counts.get("cancelled", 0),
                    "total": sum(counts.values()),
                }
            }

    def update_job_status(
        self,
        job_id: int,
        status: str,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        new_tracks: Optional[int] = None,
        skipped_tracks: Optional[int] = None,
        error_count: Optional[int] = None,
        error_message: Optional[str] = None,
        log_path: Optional[str] = None,
    ) -> bool:
        sets = ["status = ?"]
        params: list[object] = [status]

        if started_at is not None:
            sets.append("started_at = ?")
            params.append(started_at)
        if completed_at is not None:
            sets.append("completed_at = ?")
            params.append(completed_at)
        if new_tracks is not None:
            sets.append("new_tracks = ?")
            params.append(new_tracks)
        if skipped_tracks is not None:
            sets.append("skipped_tracks = ?")
            params.append(skipped_tracks)
        if error_count is not None:
            sets.append("error_count = ?")
            params.append(error_count)
        if error_message is not None:
            sets.append("error_message = ?")
            params.append(error_message)
        if log_path is not None:
            sets.append("log_path = ?")
            params.append(log_path)

        params.append(job_id)
        with self._conn() as conn:
            cur = conn.execute(f"UPDATE download_queue SET {', '.join(sets)} WHERE id = ?", params)
            return cur.rowcount > 0

    def cancel_queue_job(self, job_id: int) -> bool:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE download_queue SET status = 'cancelled', completed_at = ? WHERE id = ? AND status IN ('pending', 'running')",
                (now, job_id),
            )
            return cur.rowcount > 0

    def cancel_all_pending_jobs(self, batch_id: Optional[str] = None) -> int:
        now = datetime.now().isoformat()
        query = "UPDATE download_queue SET status = 'cancelled', completed_at = ? WHERE status = 'pending'"
        params = [now]
        if batch_id:
            query += " AND batch_id = ?"
            params.append(batch_id)
        with self._conn() as conn:
            cur = conn.execute(query, params)
            return cur.rowcount

    def retry_failed_jobs(self, job_ids: Optional[list[int]] = None, retry_empty_done: bool = True) -> int:
        with self._conn() as conn:
            if job_ids:
                placeholders = ",".join("?" for _ in job_ids)
                cur = conn.execute(
                    f"""
                    UPDATE download_queue
                    SET status = 'pending', error_count = 0, error_message = NULL,
                        started_at = NULL, completed_at = NULL
                    WHERE id IN ({placeholders}) AND (
                        status IN ('error', 'cancelled')
                        OR (status = 'done' AND new_tracks = 0 AND skipped_tracks = 0)
                    )
                    """,
                    job_ids,
                )
            else:
                extra_cond = "OR (status = 'done' AND new_tracks = 0 AND skipped_tracks = 0)" if retry_empty_done else ""
                cur = conn.execute(
                    f"""
                    UPDATE download_queue
                    SET status = 'pending', error_count = 0, error_message = NULL,
                        started_at = NULL, completed_at = NULL
                    WHERE status IN ('error', 'cancelled') {extra_cond}
                    """
                )
            return cur.rowcount

    def clear_completed_queue(self, older_than_days: int = 0) -> int:
        with self._conn() as conn:
            if older_than_days <= 0:
                cur = conn.execute("DELETE FROM download_queue WHERE status IN ('done', 'cancelled', 'error')")
            else:
                cutoff = datetime.fromtimestamp(datetime.now().timestamp() - older_than_days * 86400).isoformat()
                cur = conn.execute(
                    "DELETE FROM download_queue WHERE status IN ('done', 'cancelled', 'error') AND completed_at < ?",
                    (cutoff,),
                )
            return cur.rowcount

    def reorder_queue_job(self, job_id: int, new_position: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("UPDATE download_queue SET position = ? WHERE id = ?", (new_position, job_id))
            return cur.rowcount > 0

    def reset_interrupted_jobs(self) -> int:
        """On server start/crash-recovery, reset any 'running' jobs back to 'pending'."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE download_queue
                SET status = 'pending', started_at = NULL
                WHERE status = 'running'
                """
            )
            return cur.rowcount

    def reset_job_to_pending(self, job_id: int, error_message: Optional[str] = None) -> bool:
        """Reset a job back to pending so it will be retried when conditions recover."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE download_queue
                SET status = 'pending', started_at = NULL, error_message = ?
                WHERE id = ?
                """,
                (error_message, job_id),
            )
            return cur.rowcount > 0



