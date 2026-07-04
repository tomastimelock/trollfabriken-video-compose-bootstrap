from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DB_PATH = Path.home() / ".video_compose" / "jobs.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    spec_path   TEXT,
    output_path TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    error       TEXT,
    webhook_url TEXT
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    """SQLite-backed render job tracker stored at ~/.video_compose/jobs.db."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = Path(db_path) if db_path else _DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(_CREATE_SQL)

    # ── CRUD ────────────────────────────────────────────────────────────────

    def create_job(
        self,
        spec_path: str | None = None,
        output_path: str | None = None,
        webhook_url: str | None = None,
    ) -> str:
        job_id = str(uuid.uuid4())[:8]
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO jobs (id, spec_path, output_path, created_at, webhook_url) "
                "VALUES (?,?,?,?,?)",
                (job_id, spec_path, output_path, _now(), webhook_url),
            )
        return job_id

    def update_status(
        self,
        job_id: str,
        status: str,
        output_path: str | None = None,
        error: str | None = None,
    ) -> None:
        now = _now()
        with self._conn() as conn:
            if status == "running":
                conn.execute(
                    "UPDATE jobs SET status=?, started_at=? WHERE id=?",
                    (status, now, job_id),
                )
            elif status in ("done", "failed"):
                conn.execute(
                    "UPDATE jobs SET status=?, finished_at=?, output_path=COALESCE(?,output_path), error=? WHERE id=?",
                    (status, now, output_path, error, job_id),
                )
            else:
                conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def cancel_job(self, job_id: str) -> bool:
        """Mark a pending/running job as failed. Returns True if found."""
        job = self.get_job(job_id)
        if not job:
            return False
        if job["status"] not in ("pending", "running"):
            return False
        self.update_status(job_id, "failed", error="Cancelled by user")
        return True
