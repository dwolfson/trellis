"""Tests for GET /api/egeria/resync/scheduler-status -- Item 1 of
RECONCILE-ADMIN-IMPLEMENTED.md's design-review follow-ups.

Models the route directly on bootstrap.py's own `/status` (bootstrap_status()
-> bootstrap_mod.get_status()): cheap, reads in-process state only, no Egeria
call. Closes the gap resync.js's own header comment used to flag -- without
this, the Resync pane's "already scheduled" rows can't tell "the scheduler
ran and correctly found nothing" from "the scheduler hasn't run in days";
both looked like an identical clean row.

Also covers the other half of Item 2: `Finding.as_dict()`'s new `scheduled`
field, computed from SAFE_SCHEDULED_STEPS, mirroring the existing `expensive`
field -- the single source of truth resync.js now reads instead of keeping
its own hardcoded copy of the step names.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.egeria_resync import EXPENSIVE_STEPS, SAFE_SCHEDULED_STEPS, Finding
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
    ))
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    from resource_explorer.web.app import app
    return TestClient(app)


class TestFindingScheduledField:
    """Item 2: one source of truth in Python, not a hardcoded JS copy."""

    def test_a_safe_scheduled_step_is_flagged_scheduled(self):
        step = next(iter(SAFE_SCHEDULED_STEPS))
        f = Finding(key="k", title="t", detail="d", repair_step=step)
        assert f.as_dict()["scheduled"] is True

    def test_a_non_scheduled_repair_step_is_not_flagged(self):
        # Any repair step that is neither in SAFE_SCHEDULED_STEPS nor empty.
        non_scheduled = "republish_survey_results"
        assert non_scheduled not in SAFE_SCHEDULED_STEPS
        f = Finding(key="k", title="t", detail="d", repair_step=non_scheduled)
        assert f.as_dict()["scheduled"] is False

    def test_empty_repair_step_is_not_scheduled(self):
        f = Finding(key="k", title="t", detail="d", repair_step="")
        assert f.as_dict()["scheduled"] is False

    def test_expensive_and_scheduled_are_mutually_exclusive_sets(self):
        # SAFE_SCHEDULED_STEPS' own construction guarantees this -- a
        # regression guard, not a new invariant, since scan_and_clear()
        # already asserts it defensively at apply time.
        assert not (set(SAFE_SCHEDULED_STEPS) & set(EXPENSIVE_STEPS))


class TestResyncStatusRoute:
    """Route -> resource_explorer.egeria_resync.get_status(), end to end --
    not just a unit test of get_status() in isolation."""

    def test_returns_the_real_status_shape(self, client):
        fake_status = {
            "last_run_at": "2026-09-20T12:00:00+00:00",
            "last_reachable": True,
            "last_unreachable_reason": "",
            "last_applied": {"clear_stale_assets": {"cleared": 2}},
            "last_error": "",
            "consecutive_failures": 0,
        }
        with patch("resource_explorer.egeria_resync.get_status", return_value=fake_status) as mock_status:
            resp = client.get("/api/egeria/resync/scheduler-status")

        assert resp.status_code == 200
        assert resp.json() == fake_status
        mock_status.assert_called_once_with()

    def test_never_calls_egeria_reads_in_process_state_only(self, client):
        """Regression guard for the design constraint itself: the route must
        not reach for EgeriaResync/pyegeria at all -- only the plain module-
        level status dict."""
        with patch("resource_explorer.egeria_resync.EgeriaResync") as MockResync:
            resp = client.get("/api/egeria/resync/scheduler-status")

        assert resp.status_code == 200
        MockResync.assert_not_called()

    def test_nonzero_consecutive_failures_is_reported_as_is(self, client):
        """The route itself is a plain passthrough -- the "flag when
        non-zero, silent otherwise" rendering rule belongs to resync.js, but
        the route must not suppress or reshape the count it forwards."""
        fake_status = {
            "last_run_at": "2026-09-20T12:00:00+00:00",
            "last_reachable": False,
            "last_unreachable_reason": "platform down",
            "last_applied": {},
            "last_error": "ConnectionError: platform down",
            "consecutive_failures": 3,
        }
        with patch("resource_explorer.egeria_resync.get_status", return_value=fake_status):
            resp = client.get("/api/egeria/resync/scheduler-status")

        data = resp.json()
        assert data["consecutive_failures"] == 3
        assert data["last_error"] == "ConnectionError: platform down"
