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

    def is_downloaded(self, track_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM tracks WHERE track_id = ?", (track_id,)
            ).fetchone()
            return row is not None

    def add_track(self, track: Track) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tracks VALUES (?, ?, ?, ?, ?, ?)",
                (track.track_id, track.title, track.artist,
                 track.album, track.local_path, track.downloaded_at),
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
                       t.local_path, t.downloaded_at
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
