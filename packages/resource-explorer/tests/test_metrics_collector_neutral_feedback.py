"""Regression guard for the neutral-vote landmine in `record_feedback`.

`metrics_collector.py:189` used to be `is_positive = 1 if feedback > 0 else 0`
— a sign test on an integer. EA's own wire convention (`advisor/web/app.py:
131-135`) encodes a neutral/"partially correct" vote as `feedback == 0`. Under
the old sign test, `0 > 0` is `False`, the same branch a `-1` (thumbs-down)
takes — so a neutral vote would silently score identically to a negative one
in `chunk_feedback.positive_count`/`total_count`, corrupting the RAG
chunk-ranking signal with no error and no failing test.

This file pins the fix: neutral (0), positive (+1), and negative (-1) must
each land in a distinguishable stored state. `test_neutral_is_not_scored_as_negative`
is the one that would have failed against the old line — it is the whole
point of this file.
"""
from __future__ import annotations

import hashlib

import pytest

from resource_explorer.observability.metrics_collector import MetricsCollector

_QUERY_POS = "positive query"
_QUERY_NEG = "negative query"
_QUERY_NEU = "neutral query"


def _hash(q: str) -> str:
    return hashlib.sha256(q.encode()).hexdigest()[:16]


@pytest.fixture
def collector(tmp_path):
    return MetricsCollector(database_url=f"sqlite:///{tmp_path / 'm.db'}")


def _chunk_row(collector: MetricsCollector, chunk_ref: str) -> dict:
    with collector._conn() as conn:
        row = conn.execute(
            "SELECT positive_count, neutral_count, total_count "
            "FROM chunk_feedback WHERE chunk_ref = ?",
            (chunk_ref,),
        ).fetchone()
    return dict(row)


def test_neutral_is_not_scored_as_negative(collector):
    """The regression test. Fails if a neutral (0) vote is ever counted the
    same as a negative (-1) vote in chunk_feedback's stored counters."""
    collector.record_query(_QUERY_NEU, "conceptual", "egeria_git", "an answer",
                            chunk_refs=["neutral_chunk"])
    collector.record_feedback(_hash(_QUERY_NEU), 0)

    collector.record_query(_QUERY_NEG, "conceptual", "egeria_git", "an answer",
                            chunk_refs=["negative_chunk"])
    collector.record_feedback(_hash(_QUERY_NEG), -1)

    neutral_row = _chunk_row(collector, "neutral_chunk")
    negative_row = _chunk_row(collector, "negative_chunk")

    # Both still contribute to total_count (a vote was cast either way)...
    assert neutral_row["total_count"] == 1
    assert negative_row["total_count"] == 1

    # ...but a neutral vote must be visibly distinguishable from a negative
    # one in the stored data. Under the pre-fix sign test they were
    # identical: positive_count=0, total_count=1 for both.
    assert neutral_row["neutral_count"] == 1
    assert negative_row["neutral_count"] == 0
    assert neutral_row != negative_row, (
        "neutral and negative votes produced identical chunk_feedback rows — "
        "neutral is being scored as negative"
    )


def test_positive_neutral_negative_each_distinct(collector):
    """All three states, one chunk apiece, must each land in their own
    distinguishable stored shape."""
    collector.record_query(_QUERY_POS, "conceptual", "egeria_git", "an answer",
                            chunk_refs=["c_pos"])
    collector.record_feedback(_hash(_QUERY_POS), 1)

    collector.record_query(_QUERY_NEU, "conceptual", "egeria_git", "an answer",
                            chunk_refs=["c_neu"])
    collector.record_feedback(_hash(_QUERY_NEU), 0)

    collector.record_query(_QUERY_NEG, "conceptual", "egeria_git", "an answer",
                            chunk_refs=["c_neg"])
    collector.record_feedback(_hash(_QUERY_NEG), -1)

    pos = _chunk_row(collector, "c_pos")
    neu = _chunk_row(collector, "c_neu")
    neg = _chunk_row(collector, "c_neg")

    assert pos == {"positive_count": 1, "neutral_count": 0, "total_count": 1}
    assert neu == {"positive_count": 0, "neutral_count": 1, "total_count": 1}
    assert neg == {"positive_count": 0, "neutral_count": 0, "total_count": 1}


def test_feedback_stats_reports_neutral_separately(collector):
    collector.record_query(_QUERY_NEU, "conceptual", "egeria_git", "an answer",
                            chunk_refs=["c1"])
    collector.record_feedback(_hash(_QUERY_NEU), 0)

    stats = collector.feedback_stats()
    assert stats["total_neutral"] == 1
    assert stats["total_positive"] == 0
    assert stats["total_votes"] == 1
