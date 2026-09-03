"""Tests for the Strawberry export module."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

import alac_rip.strawberry_sync as strawberry_sync
from alac_rip.strawberry_sync import _path_to_url, export_playlist


@dataclass
class _Track:
    title: str
    artist: str
    album: str
    local_path: str


def _make_strawberry_schema(db: Path) -> None:
    """Mimic the subset of Strawberry's schema we touch."""
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE playlists (
          name TEXT NOT NULL,
          last_played INTEGER NOT NULL DEFAULT -1,
          ui_order INTEGER NOT NULL DEFAULT 0,
          is_favorite INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE playlist_items (
          playlist INTEGER NOT NULL,
          type INTEGER NOT NULL DEFAULT 0,
          url TEXT NOT NULL,
          title TEXT,
          artist TEXT,
          album TEXT,
          effective_albumartist TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def test_path_to_url_quotes_special_chars():
    assert _path_to_url("/tmp/Music/Q & A/01 — Title.flac").startswith("file:///")
    assert "%20" in _path_to_url("/path with space/song.flac")
    assert "%26" in _path_to_url("/path/Q&A/song.flac")  # & must escape


def test_export_creates_new_playlist(tmp_path):
    db = tmp_path / "strawberry.db"
    _make_strawberry_schema(db)

    tracks = [
        _Track("Song A", "Artist A", "Album X", "/music/a.flac"),
        _Track("Song B", "Artist B", "Album Y", "/music/b.flac"),
    ]
    result = export_playlist(db, "Liked Songs", tracks)

    assert result["inserted"] == 2
    assert result["removed"] == 0

    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT title, artist FROM playlist_items WHERE playlist = ?",
        (result["playlist_id"],),
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0] == ("Song A", "Artist A")


def test_export_replaces_existing_playlist_by_name(tmp_path):
    db = tmp_path / "strawberry.db"
    _make_strawberry_schema(db)

    # Pre-populate with stale "Liked Songs" entries (Strawberry allows duplicate names)
    conn = sqlite3.connect(str(db))
    conn.execute("INSERT INTO playlists(name, ui_order) VALUES ('Liked Songs', 0)")
    pid1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO playlists(name, ui_order) VALUES ('Liked Songs', 1)")
    pid2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO playlists(name, ui_order) VALUES ('Other', 2)")
    conn.execute(
        "INSERT INTO playlist_items(playlist, type, url, title) VALUES (?, 1, 'file:///old1', 'Old1')",
        (pid1,),
    )
    conn.execute(
        "INSERT INTO playlist_items(playlist, type, url, title) VALUES (?, 1, 'file:///old2', 'Old2')",
        (pid2,),
    )
    conn.commit()
    conn.close()

    tracks = [_Track("New", "A", "X", "/music/new.flac")]
    result = export_playlist(db, "Liked Songs", tracks)

    assert result["removed"] == 2
    assert result["inserted"] == 1

    conn = sqlite3.connect(str(db))
    # Old playlists gone
    assert conn.execute(
        "SELECT COUNT(*) FROM playlists WHERE name = 'Liked Songs'"
    ).fetchone()[0] == 1
    # Other playlist preserved
    assert conn.execute(
        "SELECT COUNT(*) FROM playlists WHERE name = 'Other'"
    ).fetchone()[0] == 1
    # No orphan items
    orphans = conn.execute(
        "SELECT COUNT(*) FROM playlist_items WHERE title IN ('Old1', 'Old2')"
    ).fetchone()[0]
    assert orphans == 0
    conn.close()


def test_export_rejects_empty_playlist(tmp_path):
    db = tmp_path / "strawberry.db"
    _make_strawberry_schema(db)
    with pytest.raises(ValueError):
        export_playlist(db, "Empty", [])


def test_export_url_encoding(tmp_path):
    db = tmp_path / "strawberry.db"
    _make_strawberry_schema(db)
    tracks = [_Track("T", "A", "Al", "/music/Q & A/song with space.flac")]
    result = export_playlist(db, "PL", tracks)
    conn = sqlite3.connect(str(db))
    url = conn.execute(
        "SELECT url FROM playlist_items WHERE playlist = ?", (result["playlist_id"],)
    ).fetchone()[0]
    conn.close()
    assert url.startswith("file:///")
    assert "%20" in url
    assert "%26" in url


def test_export_reports_busy_database_without_overwriting_it(tmp_path, monkeypatch):
    db = tmp_path / "strawberry.db"
    _make_strawberry_schema(db)
    monkeypatch.setattr(strawberry_sync, "_DB_TIMEOUT_SECONDS", 0.01)

    lock = sqlite3.connect(str(db))
    lock.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(strawberry_sync.StrawberryBusyError):
            export_playlist(db, "Locked", [_Track("T", "A", "Al", "/music/t.flac")])
    finally:
        lock.rollback()
        lock.close()

    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0] == 0
    conn.close()
