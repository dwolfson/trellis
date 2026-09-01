"""Feedback Store — SQLite/Postgres-backed store for product/UI feedback.

Deliberately separate from ProjectRegistry: feedback is a support/triage
workflow, not project/resource state, with its own lifecycle and its own
database file so its schema can evolve independently. Reuses
ProjectRegistry's ConnectionWrapper for sqlite/postgres portability, so
this table migrates cleanly whenever RE's own storage moves onto Postgres
— nothing here is SQLite-specific.

Ported from Egeria Workspaces Portal's demo_feedback_handler.py, trimmed
of Portal-specific concepts RE has no equivalent of (JWT-derived user_id,
env, persona) — see resource_explorer/web/admin_auth.py for the admin
gating this store's triage endpoints require.
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from resource_explorer.registry import ConnectionWrapper

VALID_TRIAGE_STATUSES = {"new", "triaged", "actioned"}
VALID_CATEGORIES = {"bug", "confusing", "suggestion", "praise"}


@dataclass
class FeedbackEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    page: str = ""
    element_guid: str = ""
    rating: int | None = None
    category: str = ""  # bug | confusing | suggestion | praise
    message: str = ""
    email: str = ""
    wants_response: bool = False
    consent_to_contact: bool = False
    build_version: str = ""
    user_agent: str = ""
    viewport: str = ""
    locale: str = ""
    triage_status: str = "new"  # new | triaged | actioned
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class FeedbackStore:
    def __init__(self, db_path: str = "data/feedback.db") -> None:
        self.db_path = db_path
        if db_path == "data/feedback.db":
            try:
                from resource_explorer.config import get_config
                config = get_config()
                self.database_url = config.feedback.database_url
            except Exception:
                import os
                self.database_url = os.environ.get("FEEDBACK_DATABASE_URL", f"sqlite:///{db_path}")
        else:
            self.database_url = f"sqlite:///{db_path}"

        if self.database_url.startswith("sqlite:///"):
            path_str = self.database_url[len("sqlite:///"):]
            if path_str and path_str != ":memory:":
                Path(path_str).parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(self.database_url)
        self._init_schema()

    @contextmanager
    def _conn(self):
        is_postgres = self.database_url.startswith("postgresql")
        raw_conn = self.engine.raw_connection()
        if not is_postgres:
            raw_conn.row_factory = sqlite3.Row
        conn = ConnectionWrapper(raw_conn, is_postgres)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY,
                    session_id TEXT DEFAULT '',
                    page TEXT DEFAULT '',
                    element_guid TEXT DEFAULT '',
                    rating INTEGER,
                    category TEXT DEFAULT '',
                    message TEXT DEFAULT '',
                    email TEXT DEFAULT '',
                    wants_response INTEGER DEFAULT 0,
                    consent_to_contact INTEGER DEFAULT 0,
                    build_version TEXT DEFAULT '',
                    user_agent TEXT DEFAULT '',
                    viewport TEXT DEFAULT '',
                    locale TEXT DEFAULT '',
                    triage_status TEXT DEFAULT 'new',
                    created_at TEXT NOT NULL
                )
            """)

    def add(self, entry: FeedbackEntry) -> FeedbackEntry:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO feedback (
                    id, session_id, page, element_guid, rating, category, message,
                    email, wants_response, consent_to_contact, build_version,
                    user_agent, viewport, locale, triage_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.id, entry.session_id, entry.page, entry.element_guid,
                    entry.rating, entry.category, entry.message, entry.email,
                    int(entry.wants_response), int(entry.consent_to_contact),
                    entry.build_version, entry.user_agent, entry.viewport,
                    entry.locale, entry.triage_status, entry.created_at,
                ),
            )
        return entry

    def list(
        self,
        triage_status: str | None = None,
        category: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM feedback"
        clauses: list[str] = []
        params: list[Any] = []
        if triage_status:
            clauses.append("triage_status = ?")
            params.append(triage_status)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(r.items()) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM feedback").fetchone()["n"]
            new = conn.execute(
                "SELECT COUNT(*) AS n FROM feedback WHERE triage_status = 'new'"
            ).fetchone()["n"]
            wants_response = conn.execute(
                "SELECT COUNT(*) AS n FROM feedback WHERE wants_response = 1"
            ).fetchone()["n"]
            avg_row = conn.execute(
                "SELECT AVG(rating) AS avg_rating FROM feedback WHERE rating IS NOT NULL"
            ).fetchone()
            avg_rating = avg_row["avg_rating"] if avg_row else None
        return {
            "total": total,
            "new": new,
            "wants_response": wants_response,
            # float(), not just round(): Postgres AVG() returns Decimal where
            # SQLite returns a float, so without this the *type* of this field
            # depends on the backend. FastAPI's own encoder copes, but plain
            # json.dumps() on the result raises "Object of type Decimal is not
            # JSON serializable" — found on the 2026-08-23 move to Postgres.
            # The store's contract is a number, so it returns one either way.
            "avg_rating": round(float(avg_rating), 2) if avg_rating is not None else None,
        }

    def update_triage_status(self, feedback_id: str, triage_status: str) -> dict[str, Any] | None:
        if triage_status not in VALID_TRIAGE_STATUSES:
            raise ValueError(f"Invalid triage_status: {triage_status!r}")
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE feedback SET triage_status = ? WHERE id = ?",
                (triage_status, feedback_id),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
            return dict(row.items()) if row else None
