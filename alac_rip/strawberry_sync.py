"""Export pies playlists into Strawberry music player's library.

Replaces (by name) any existing Strawberry playlists that share a pies playlist's
name, then inserts a fresh copy populated from pies' track records. Operates
directly on Strawberry's SQLite DB; refuses to run while Strawberry is open.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import quote


# Track-shaped duck-type: needs `title`, `artist`, `album`, `local_path`.
class _TrackLike:
    title: str
    artist: str
    album: str
    local_path: str


_FLATPAK_DB = Path.home() / ".var/app/org.strawberrymusicplayer.strawberry/data/strawberry/strawberry/strawberry.db"
_NATIVE_DB = Path.home() / ".local/share/strawberry/strawberry/strawberry.db"


def find_strawberry_db() -> Optional[Path]:
    """Return the path to Strawberry's SQLite DB, preferring flatpak install."""
    for p in (_FLATPAK_DB, _NATIVE_DB):
        if p.exists():
            return p
    return None


def is_strawberry_running() -> bool:
    """True if Strawberry has the DB open. We use pgrep — cheap and Linux-portable."""
    for needle in ("strawberry", "org.strawberrymusicplayer"):
        try:
            r = subprocess.run(["pgrep", "-f", needle], capture_output=True, timeout=2)
            if r.returncode == 0 and r.stdout.strip():
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return False


def _path_to_url(local_path: str) -> str:
    """Convert a filesystem path to Strawberry's `file:///` URL form."""
    abs_path = str(Path(local_path).absolute())
    return "file://" + quote(abs_path, safe="/")


def export_playlist(
    db_path: Path, playlist_name: str, tracks: Sequence[_TrackLike]
) -> dict:
    """Replace any playlists named `playlist_name` in Strawberry's DB with the
    given tracks.

    Returns: {"removed": N_old_playlists, "inserted": N_tracks, "playlist_id": new_rowid}
    """
    if not tracks:
        raise ValueError("refusing to export an empty playlist")

    backup = db_path.with_suffix(f".db.bak.{int(time.time())}")
    shutil.copy2(db_path, backup)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("BEGIN")

        old_ids = [
            r[0]
            for r in conn.execute(
                "SELECT ROWID FROM playlists WHERE name = ?", (playlist_name,)
            ).fetchall()
        ]
        for old_id in old_ids:
            conn.execute("DELETE FROM playlist_items WHERE playlist = ?", (old_id,))
            conn.execute("DELETE FROM playlists WHERE ROWID = ?", (old_id,))

        max_order = conn.execute("SELECT COALESCE(MAX(ui_order), -1) FROM playlists").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO playlists(name, ui_order, last_played, is_favorite) VALUES (?, ?, -1, 0)",
            (playlist_name, max_order + 1),
        )
        new_id = cur.lastrowid

        for t in tracks:
            url = _path_to_url(t.local_path)
            conn.execute(
                """INSERT INTO playlist_items
                   (playlist, type, url, title, artist, album, effective_albumartist)
                   VALUES (?, 1, ?, ?, ?, ?, ?)""",
                (new_id, url, t.title, t.artist, t.album, t.artist),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        # Restore the backup on failure so we never leave Strawberry in a bad state
        conn.close()
        shutil.copy2(backup, db_path)
        raise
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    return {"removed": len(old_ids), "inserted": len(tracks), "playlist_id": new_id, "backup": str(backup)}
