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
                "SELECT track_id, title, artist, album, local_path, downloaded_at, artwork_url FROM tracks WHERE track_id = ?",
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

    def has_track_path(self, path: Path) -> bool:
        """Return whether *path* belongs to a track recorded by this library."""
        target = path.resolve()
        with self._conn() as conn:
            paths = conn.execute("SELECT local_path FROM tracks").fetchall()
        for (stored_path,) in paths:
            try:
                if Path(stored_path).expanduser().resolve() == target:
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
