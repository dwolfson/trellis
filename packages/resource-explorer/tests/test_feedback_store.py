"""Tests for FeedbackStore — insert, list, filter, stats, triage update."""
from __future__ import annotations

import pytest

from resource_explorer.feedback_store import FeedbackEntry, FeedbackStore


@pytest.fixture
def store(tmp_path):
    return FeedbackStore(db_path=str(tmp_path / "test_feedback.db"))


class TestAddAndList:
    def test_add_and_list(self, store):
        entry = store.add(FeedbackEntry(page="nav-chat", rating=5, message="great tool"))
        rows = store.list()
        assert len(rows) == 1
        assert rows[0]["id"] == entry.id
        assert rows[0]["page"] == "nav-chat"
        assert rows[0]["rating"] == 5
        assert rows[0]["message"] == "great tool"
        assert rows[0]["triage_status"] == "new"

    def test_list_empty(self, store):
        assert store.list() == []

    def test_list_filters_by_triage_status(self, store):
        a = store.add(FeedbackEntry(message="a"))
        store.add(FeedbackEntry(message="b"))
        store.update_triage_status(a.id, "triaged")

        triaged = store.list(triage_status="triaged")
        new_only = store.list(triage_status="new")
        assert len(triaged) == 1
        assert triaged[0]["id"] == a.id
        assert len(new_only) == 1

    def test_list_respects_limit(self, store):
        for i in range(5):
            store.add(FeedbackEntry(message=f"msg-{i}"))
        assert len(store.list(limit=2)) == 2

    def test_list_newest_first(self, store):
        first = store.add(FeedbackEntry(message="first"))
        second = store.add(FeedbackEntry(message="second"))
        rows = store.list()
        assert rows[0]["id"] == second.id
        assert rows[1]["id"] == first.id


class TestStats:
    def test_stats_empty(self, store):
        stats = store.stats()
        assert stats == {"total": 0, "new": 0, "wants_response": 0, "avg_rating": None}

    def test_stats_counts_and_average(self, store):
        store.add(FeedbackEntry(rating=4))
        store.add(FeedbackEntry(rating=2))
        store.add(FeedbackEntry(rating=None, wants_response=True))
        stats = store.stats()
        assert stats["total"] == 3
        assert stats["new"] == 3
        assert stats["wants_response"] == 1
        assert stats["avg_rating"] == 3.0


class TestTriageUpdate:
    def test_update_triage_status(self, store):
        entry = store.add(FeedbackEntry(message="x"))
        updated = store.update_triage_status(entry.id, "actioned")
        assert updated is not None
        assert updated["triage_status"] == "actioned"

    def test_update_missing_returns_none(self, store):
        assert store.update_triage_status("does-not-exist", "triaged") is None

    def test_update_invalid_status_raises(self, store):
        entry = store.add(FeedbackEntry(message="x"))
        with pytest.raises(ValueError):
            store.update_triage_status(entry.id, "bogus")
