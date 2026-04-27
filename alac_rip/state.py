import sqlite3
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
        return sqlite3.connect(self.db_path)

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

    def is_downloaded(self, track_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM tracks WHERE track_id = ?", (track_id,)
            ).fetchone()
            return row is not None

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

    def add_playlist(self, name: str, url: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO playlists (name, url, last_synced) VALUES (?, ?, NULL)",
                (name, url),
            )

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
