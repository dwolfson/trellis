"""Query metrics — Postgres by default, SQLite when pointed at a file.

Was raw `sqlite3` until 2026-08-23: the last store in this package with no
portability layer, and the reason a `data/metrics.db` file kept being written
long after the registry moved to Postgres. It now uses the same SQLAlchemy
engine + ProjectRegistry.ConnectionWrapper pair the registry and FeedbackStore
use, which is what makes the SQL below backend-agnostic — the wrapper
translates `?` placeholders to `%s` and rewrites
`INTEGER PRIMARY KEY AUTOINCREMENT` to `SERIAL PRIMARY KEY` on Postgres, so
none of the statements here needed changing.

"zero external dependencies" was the original justification for SQLite. That
stopped being true of the product as a whole once the registry required
Postgres; keeping metrics on a file only meant one more store nobody was
looking at.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine

from resource_explorer.config import get_config
from resource_explorer.registry import ConnectionWrapper


class MetricsCollector:
    def __init__(self, database_url: str | None = None) -> None:
        cfg = get_config().observability
        # An explicit sqlite:/// metrics_db still wins, so a from-scratch or
        # offline environment can keep a file; otherwise the shared instance.
        if database_url is not None:
            self.database_url = database_url
        elif cfg.metrics_db and cfg.metrics_db != "data/metrics.db":
            self.database_url = f"sqlite:///{cfg.metrics_db}"
        else:
            self.database_url = cfg.metrics_database_url

        self.db_path = cfg.metrics_db
        if self.database_url.startswith("sqlite:///"):
            path_str = self.database_url[len("sqlite:///"):]
            if path_str and path_str != ":memory:":
                Path(path_str).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(self.database_url, pool_pre_ping=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        import sqlite3

        is_postgres = self.database_url.startswith("postgresql")
        raw_conn = self.engine.raw_connection()
        if not is_postgres:
            raw_conn.row_factory = sqlite3.Row
            raw_conn.execute("PRAGMA foreign_keys=ON")
        conn = ConnectionWrapper(raw_conn, is_postgres)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    query_hash TEXT NOT NULL,
                    intent TEXT,
                    project_slug TEXT,
                    latency_ms INTEGER,
                    cache_hit INTEGER DEFAULT 0,
                    response_length INTEGER,
                    chunk_refs TEXT DEFAULT '[]',
                    derivation TEXT DEFAULT '{}',
                    feedback INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunk_feedback (
                    chunk_ref TEXT PRIMARY KEY,
                    positive_count INTEGER DEFAULT 0,
                    total_count INTEGER DEFAULT 0,
                    last_updated TEXT
                )
            """)
            # Migration: add chunk_refs to existing query_log tables. PRAGMA is
            # SQLite-only, so the column list comes from information_schema on
            # Postgres — same two-backend split registry._get_table_columns
            # makes, and read through this same open transaction so a table
            # created moments ago is visible.
            if conn.is_postgres:
                rows = conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'query_log'"
                ).fetchall()
                existing = {r["column_name"] for r in rows}
            else:
                # .fetchall(), not iteration: ConnectionWrapper returns a
                # cursor wrapper, and unlike the raw sqlite3 cursor this used
                # to get, it is not iterable.
                existing = {r[1] for r in conn.execute("PRAGMA table_info(query_log)").fetchall()}
            if "chunk_refs" not in existing:
                conn.execute("ALTER TABLE query_log ADD COLUMN chunk_refs TEXT DEFAULT '[]'")
            # Why these sources were selected, as distinct from chunk_refs'
            # "which chunks came back". A thumbs-down is otherwise ambiguous
            # between "the wrong questions/analyses were chosen" and "the right
            # ones were chosen and the answer was still bad" -- different fixes.
            # See docs/context-compilation-design.md §13.
            if "derivation" not in existing:
                conn.execute("ALTER TABLE query_log ADD COLUMN derivation TEXT DEFAULT '{}'")

    def record_query(
        self,
        query: str,
        intent: str,
        resource_slug: str | None,
        response: str,
        latency_ms: int = 0,
        cache_hit: bool = False,
        chunk_refs: list[str] | None = None,
        derivation: dict | None = None,
    ) -> None:
        """Record one query.

        derivation: the selection chain behind this answer -- Purpose and
        Perspective matched, questions raised, analysis ids dispatched to (the
        shape question_catalog_reader.get_questions() now returns per entry).
        Distinct from chunk_refs, which says what retrieval returned rather
        than why it was asked for. Optional: a query with no catalog behind it
        (free-text RAG) simply has none.
        """
        import hashlib
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO query_log
                   (timestamp, query_hash, intent, project_slug, latency_ms,
                    cache_hit, response_length, chunk_refs, derivation)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (datetime.utcnow().isoformat(), query_hash, intent, resource_slug,
                 latency_ms, int(cache_hit), len(response),
                 json.dumps(chunk_refs or []), json.dumps(derivation or {})),
            )
        # Non-blocking MLflow logging (already called from a daemon thread)
        try:
            from resource_explorer.observability.mlflow_tracking import log_query
            log_query(
                query=query,
                intent=intent,
                resource_slug=resource_slug,
                response=response,
                latency_ms=latency_ms,
                collections_used=chunk_refs or [],
            )
        except Exception:
            pass

    def record_feedback(self, query_hash: str, feedback: int) -> None:
        """Record thumbs-up (+1) or thumbs-down (-1) for a query and update per-chunk scores."""
        with self._conn() as conn:
            # Update query_log feedback column
            conn.execute(
                """UPDATE query_log SET feedback = ?
                   WHERE id = (SELECT id FROM query_log WHERE query_hash = ?
                               ORDER BY id DESC LIMIT 1)""",
                (feedback, query_hash),
            )
            # Look up which chunks were retrieved for this query
            row = conn.execute(
                """SELECT chunk_refs FROM query_log WHERE query_hash = ?
                   ORDER BY id DESC LIMIT 1""",
                (query_hash,),
            ).fetchone()
            if not row:
                return
            try:
                refs = json.loads(row["chunk_refs"] or "[]")
            except Exception:
                refs = []

            # Update per-chunk feedback counts
            now = datetime.utcnow().isoformat()
            is_positive = 1 if feedback > 0 else 0
            for ref in refs:
                conn.execute(
                    """INSERT INTO chunk_feedback (chunk_ref, positive_count, total_count, last_updated)
                       VALUES (?, ?, 1, ?)
                       ON CONFLICT(chunk_ref) DO UPDATE SET
                           positive_count = chunk_feedback.positive_count + ?,
                           total_count = chunk_feedback.total_count + 1,
                           last_updated = ?""",
                    (ref, is_positive, now, is_positive, now),
                )

    def summary(self) -> dict:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) as total,
                       AVG(latency_ms) as avg_latency,
                       SUM(cache_hit) as cache_hits,
                       AVG(CASE WHEN feedback IS NOT NULL THEN feedback END) as avg_feedback
                FROM query_log
            """).fetchone()
        return _numeric(dict(row)) if row else {}

    def feedback_stats(self) -> dict:
        """Summary of feedback quality across all chunks."""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) as chunks_with_feedback,
                       SUM(positive_count) as total_positive,
                       SUM(total_count) as total_votes
                FROM chunk_feedback WHERE total_count > 0
            """).fetchone()
        return _numeric(dict(row)) if row else {}


def _numeric(d: dict) -> dict:
    """Postgres AVG()/SUM() return Decimal where SQLite returns float/int, so
    without this the *types* in these summaries depend on the backend and
    json.dumps() raises "Object of type Decimal is not JSON serializable".
    Found on the 2026-08-23 move (the feedback store's stats() hit the same
    thing). These are numbers by contract; they come back as numbers."""
    from decimal import Decimal

    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in d.items()}
