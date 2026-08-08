"""SQLite-backed query metrics — always available, zero external dependencies."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from resource_explorer.config import get_config


class MetricsCollector:
    def __init__(self) -> None:
        db_path = get_config().observability.metrics_db
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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
            # Migration: add chunk_refs to existing query_log tables
            existing = {r[1] for r in conn.execute("PRAGMA table_info(query_log)")}
            if "chunk_refs" not in existing:
                conn.execute("ALTER TABLE query_log ADD COLUMN chunk_refs TEXT DEFAULT '[]'")

    def record_query(
        self,
        query: str,
        intent: str,
        project_slug: str | None,
        response: str,
        latency_ms: int = 0,
        cache_hit: bool = False,
        chunk_refs: list[str] | None = None,
    ) -> None:
        import hashlib
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO query_log
                   (timestamp, query_hash, intent, project_slug, latency_ms,
                    cache_hit, response_length, chunk_refs)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (datetime.utcnow().isoformat(), query_hash, intent, project_slug,
                 latency_ms, int(cache_hit), len(response),
                 json.dumps(chunk_refs or [])),
            )
        # Non-blocking MLflow logging (already called from a daemon thread)
        try:
            from resource_explorer.observability.mlflow_tracking import log_query
            log_query(
                query=query,
                intent=intent,
                project_slug=project_slug,
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
                           positive_count = positive_count + ?,
                           total_count = total_count + 1,
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
        return dict(row) if row else {}

    def feedback_stats(self) -> dict:
        """Summary of feedback quality across all chunks."""
        with self._conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) as chunks_with_feedback,
                       SUM(positive_count) as total_positive,
                       SUM(total_count) as total_votes
                FROM chunk_feedback WHERE total_count > 0
            """).fetchone()
        return dict(row) if row else {}
