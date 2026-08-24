"""MetricsCollector on both backends — the store that had no portability layer.

Until 2026-08-23 this was raw `sqlite3.connect`, the last store in the package
with no abstraction, and the reason `data/metrics.db` kept being written long
after the registry moved to Postgres. Porting it onto the registry's
SQLAlchemy engine + ConnectionWrapper surfaced two divergences that no
SQLite-only test could have shown, both fixed and both pinned here:

  * `ON CONFLICT ... DO UPDATE SET positive_count = positive_count + ?` is
    valid SQLite and an AmbiguousColumn error on Postgres, which resolves a
    bare name there against `excluded`. The column has to be table-qualified.
  * `AVG()`/`SUM()` return Decimal on Postgres and float/int on SQLite, so the
    summary dicts' value *types* depended on the backend and `json.dumps()`
    raised on the Postgres one.

The Postgres half auto-skips when no instance is reachable, so this file still
runs (SQLite half only) with no external services.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from resource_explorer.observability.metrics_collector import MetricsCollector

_QUERY = "what is egeria?"
_HASH = hashlib.sha256(_QUERY.encode()).hexdigest()[:16]


def _exercise(collector: MetricsCollector) -> tuple[dict, dict]:
    """One query, then two positive votes — the second is what drives the
    ON CONFLICT branch rather than the initial INSERT."""
    collector.record_query(_QUERY, "conceptual", "egeria_git", "an answer",
                           latency_ms=42, cache_hit=False, chunk_refs=["c1", "c2"])
    collector.record_feedback(_HASH, 1)
    collector.record_feedback(_HASH, 1)
    return collector.summary(), collector.feedback_stats()


@pytest.fixture
def sqlite_collector(tmp_path):
    return MetricsCollector(database_url=f"sqlite:///{tmp_path / 'm.db'}")


@pytest.fixture
def pg_collector(pg_test_schema):
    from resource_explorer.config import get_config

    cfg = get_config().pgvector
    collector = MetricsCollector(database_url=(
        f"postgresql://{cfg.db_user}:{cfg.password}@{cfg.host}:{cfg.port}"
        f"/{cfg.dbname}?options=-csearch_path%3D{pg_test_schema}"))
    # pg_test_schema is session-scoped, so without this the Postgres rows
    # accumulate across tests while the SQLite fixture gets a fresh tmp_path
    # each time — which is exactly what made test_both_backends_agree fail on
    # its first run, for a reason that had nothing to do with the backends.
    with collector._conn() as conn:
        conn.execute("DELETE FROM query_log")
        conn.execute("DELETE FROM chunk_feedback")
    return collector


class TestSqlite:
    def test_round_trip(self, sqlite_collector):
        summary, feedback = _exercise(sqlite_collector)
        assert summary["total"] == 1
        assert summary["avg_latency"] == 42.0
        assert feedback["total_votes"] == 4      # 2 chunks x 2 votes
        assert feedback["total_positive"] == 4

    def test_summaries_are_json_serialisable(self, sqlite_collector):
        _exercise(sqlite_collector)
        json.dumps(sqlite_collector.summary())
        json.dumps(sqlite_collector.feedback_stats())


@pytest.mark.requires_pgvector
class TestPostgres:
    def test_round_trip(self, pg_collector):
        summary, feedback = _exercise(pg_collector)
        assert summary["total"] == 1
        assert summary["avg_latency"] == 42.0
        assert feedback["total_votes"] == 4
        assert feedback["total_positive"] == 4

    def test_summaries_are_json_serialisable(self, pg_collector):
        """The Decimal trap: FastAPI's encoder would paper over it, a plain
        json.dumps would not."""
        _exercise(pg_collector)
        json.dumps(pg_collector.summary())
        json.dumps(pg_collector.feedback_stats())

    def test_upsert_accumulates_rather_than_erroring(self, pg_collector):
        """The AmbiguousColumn regression guard — this is the exact statement
        that failed on Postgres while passing on SQLite."""
        _exercise(pg_collector)
        pg_collector.record_feedback(_HASH, 1)
        assert pg_collector.feedback_stats()["total_votes"] == 6


@pytest.mark.requires_pgvector
def test_both_backends_agree(sqlite_collector, pg_collector):
    """The property that makes keeping two backends defensible at all."""
    assert _exercise(sqlite_collector) == _exercise(pg_collector)
