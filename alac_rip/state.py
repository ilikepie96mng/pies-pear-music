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
                "INSERT OR IGNORE INTO playlists VALUES (?, ?, NULL)",
                (name, url),
            )

    def get_playlists(self) -> list[Playlist]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, url, last_synced FROM playlists"
            ).fetchall()
            return [Playlist(name=r[0], url=r[1], last_synced=r[2]) for r in rows]

    def update_playlist_synced(self, name: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE playlists SET last_synced = ? WHERE name = ?",
                (datetime.now().isoformat(), name),
            )

    def get_downloaded_count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
