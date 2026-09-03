from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
import uuid
from typing import Optional


@dataclass
class DownloadRequest:
    id: str
    url: str
    format: str
    requester: str
    status: str  # pending, approved, rejected, completed
    notes: str
    created_at: str


class RequestStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_requests (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    format TEXT NOT NULL DEFAULT 'ALAC',
                    requester TEXT NOT NULL DEFAULT 'local',
                    status TEXT NOT NULL DEFAULT 'pending',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def add_request(self, url: str, format: str = "ALAC", requester: str = "local", notes: str = "") -> DownloadRequest:
        req_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()
        req = DownloadRequest(
            id=req_id,
            url=url,
            format=format,
            requester=requester,
            status="pending",
            notes=notes,
            created_at=created_at,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO download_requests (id, url, format, requester, status, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (req.id, req.url, req.format, req.requester, req.status, req.notes, req.created_at),
            )
            conn.commit()
        return req

    def list_requests(self, status: Optional[str] = None) -> list[DownloadRequest]:
        with sqlite3.connect(self.db_path) as conn:
            if status:
                rows = conn.execute(
                    "SELECT id, url, format, requester, status, notes, created_at FROM download_requests WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, url, format, requester, status, notes, created_at FROM download_requests ORDER BY created_at DESC"
                ).fetchall()
            return [DownloadRequest(*r) for r in rows]

    def update_request_status(self, req_id: str, status: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE download_requests SET status = ? WHERE id = ?",
                (status, req_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def delete_request(self, req_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM download_requests WHERE id = ?",
                (req_id,),
            )
            conn.commit()
            return cur.rowcount > 0
