"""A run that stopped must stop claiming to be running.

Survey Definition runs happen in a daemon thread inside the web process. Every
way that thread can END writes a terminal status; exactly one way it can STOP
does not — the process dying. The row then says "running" for ever.

Measured 2026-08-26: six such rows, the oldest three days old, while the user
could not tell whether a survey they had just started was working. "Started,
outcome unknown" rendered as "in progress" is this codebase's recurring failure
sitting in the one field someone checks when they are already unsure.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from resource_explorer.run_reconciler import (
    INTERRUPTED,
    _age_of,
    _is_alive,
    owner_of,
    process_identity,
    reconcile,
)


class TestLiveness:
    def test_this_process_is_alive(self):
        assert _is_alive(process_identity()) is True

    def test_a_dead_pid_is_dead(self):
        assert _is_alive({"pid": 2 ** 22, "started_at": "whenever"}) is False

    def test_a_pid_without_a_start_time_is_undetermined(self):
        """Pids are recycled. "A process with this number exists" is too weak a
        claim to resolve either way, so it must not resolve at all."""
        assert _is_alive({"pid": os.getpid()}) is None

    def test_a_reused_pid_is_not_mistaken_for_the_original(self):
        """Same pid, different start time — a different process."""
        assert _is_alive({"pid": os.getpid(), "started_at": "not-when-this-started"}) is False

    def test_a_malformed_owner_is_undetermined(self):
        assert _is_alive({}) is None
        assert _is_alive({"pid": "not-an-int"}) is None


class TestAge:
    """Activity timestamps are stored timezone-AWARE. Subtracting a naive now
    from one raises TypeError, which an earlier version caught as "unreadable"
    and sent EVERY row to left_alone — the reconciler ran cleanly and did
    nothing at all against rows three days stale. Failing safe silently on
    every row is a no-op wearing a safety belt.
    """

    def test_an_aware_timestamp_measures_against_a_naive_now(self):
        now = datetime(2026, 8, 26, 12, 0, 0)
        age = _age_of("2026-08-24T12:00:00.000000+00:00", now)
        assert age == timedelta(days=2)

    def test_a_naive_timestamp_still_works(self):
        now = datetime(2026, 8, 26, 12, 0, 0)
        assert _age_of("2026-08-26T09:00:00", now) == timedelta(hours=3)

    def test_an_aware_now_also_works(self):
        now = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
        assert _age_of("2026-08-26T09:00:00+00:00", now) == timedelta(hours=3)

    def test_an_unreadable_timestamp_is_none_not_zero(self):
        """None routes to left-alone; a zero would read as 'just started'."""
        assert _age_of("not a date", datetime(2026, 8, 26)) is None
        assert _age_of(None, datetime(2026, 8, 26)) is None


class TestOwner:
    def test_owner_survives_json_or_dict(self):
        ident = {"pid": 1, "started_at": "x"}
        assert owner_of(json.dumps({"_runner": ident})) == ident
        assert owner_of({"_runner": ident}) == ident

    def test_no_owner_is_empty_not_an_error(self):
        assert owner_of("") == {}
        assert owner_of("not json") == {}
        assert owner_of({"something": "else"}) == {}


@pytest.fixture
def reg(pg_registry):
    """A registry with no running rows.

    The throwaway schema is session-scoped, so rows one test leaves behind are
    visible to the next — and reconcile() reads EVERY running row, so a test
    asserting exact counts would otherwise measure its predecessors. Caught by
    two tests passing alone and failing in the suite.
    """
    with pg_registry._conn() as c:
        c.execute("DELETE FROM activity_log WHERE status IN ('running', 'interrupted')")
    return pg_registry


def _running_row(reg, slug, ts, detail=None):
    from resource_explorer.activity_logger import log_survey

    entry_id = log_survey(
        reg, "repo", slug, slug, "", "assessment", "running", "Running…",
        json.dumps(detail) if detail is not None else "",
    )
    with reg._conn() as c:
        c.execute("UPDATE activity_log SET ts = ? WHERE id = ?", (ts, entry_id))
    return entry_id


class TestReconcile:
    def test_a_run_owned_by_a_live_process_is_left_running(self, reg):
        """The case that makes ownership worth recording: a peer Resource
        Explorer process sharing this database must not have its live run
        resolved out from under it."""
        _running_row(reg, "live-one", datetime.now(timezone.utc).isoformat(),
                     {"_runner": process_identity()})
        result = reconcile(reg)
        assert result["still_running"] == 1
        assert result["resolved"] == 0

    def test_a_run_owned_by_a_dead_process_is_resolved(self, reg):
        entry = _running_row(reg, "dead-one", datetime.now(timezone.utc).isoformat(),
                             {"_runner": {"pid": 2 ** 22, "started_at": "gone"}})
        assert reconcile(reg)["resolved"] == 1
        with reg._conn() as c:
            row = dict(c.execute("SELECT status, summary FROM activity_log WHERE id = ?",
                                 (entry,)).fetchone())
        assert row["status"] == INTERRUPTED
        assert "not known" in row["summary"], \
            "must not claim the run completed or failed"

    def test_interrupted_is_not_error(self, reg):
        """We know it stopped; we do not know it failed. Several of these had
        already written most of their findings, and calling that an error swaps
        one false claim for another."""
        entry = _running_row(reg, "stopped", datetime.now(timezone.utc).isoformat(),
                             {"_runner": {"pid": 2 ** 22, "started_at": "gone"}})
        reconcile(reg)
        with reg._conn() as c:
            status = dict(c.execute("SELECT status FROM activity_log WHERE id = ?",
                                    (entry,)).fetchone())["status"]
        assert status == INTERRUPTED != "error"

    def test_an_ownerless_row_is_judged_only_by_age(self, reg):
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        _running_row(reg, "ancient", old)
        _running_row(reg, "recent", recent)
        result = reconcile(reg)
        assert result["resolved"] == 1, "the 48h row should resolve"
        assert result["left_alone"] == 1, "a 20-minute run may still be working"

    def test_a_long_survey_is_not_killed_by_the_age_rule(self, reg):
        """A real RepoFullSurvey against the Egeria repo took 16 minutes. The
        age threshold has to clear that by a wide margin, or this becomes a
        cancel button nobody pressed."""
        _running_row(reg, "long-run",
                     (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat())
        assert reconcile(reg)["resolved"] == 0

    def test_counts_report_what_was_left_alone(self, reg):
        """A growing left_alone means this is quietly doing nothing — which is
        exactly how the timezone bug hid."""
        _running_row(reg, "undetermined", "not-a-timestamp")
        assert reconcile(reg)["left_alone"] == 1

    def test_nothing_running_is_not_an_error(self, reg):
        assert reconcile(reg) == {"resolved": 0, "still_running": 0,
                                  "left_alone": 0, "resolved_ids": []}


class TestWiring:
    def test_a_run_records_its_owner(self):
        """Without this every row falls back to the age rule, which cannot tell
        a dead 5-minute run from a live one."""
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "resource_explorer" / "web"
               / "routes" / "survey_definitions.py").read_text()
        route = src.split('@router.post("/{entity_type}/{slug}/run")')[1]
        assert "process_identity()" in route
        assert '"_runner"' in route

    def test_startup_reconciles(self):
        """Moved out of web/app.py's lifespan into the worker role
        (2026-09-04, docs/runtime-architecture-plan.md §2). The web
        process reaches it through the embedded worker; a standalone
        `resource-explorer worker` reaches it directly."""
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "resource_explorer"
               / "worker.py").read_text()
        body = src.split("def run_worker(")[1].split("\n\n\n")[0]
        assert "_reconcile_orphaned_runs()" in body

    def test_startup_reconciliation_cannot_break_startup(self):
        """Bookkeeping must never stop the process coming up."""
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "resource_explorer"
               / "worker.py").read_text()
        fn = src.split("def _reconcile_orphaned_runs()")[1].split("\n\n\n")[0]
        assert "try:" in fn and "except Exception" in fn
