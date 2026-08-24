"""Does Automate actually notify anyone?

Its whole value is the notification, and two independent faults meant it never
reached a person:

  1. Delivery. log_rfa() wrote activity entries with no annotations, and the RFA
     drawer selects on annotations — so every notification was invisible. Fixed
     separately (see tests/test_rfa_visibility.py); this file covers the path
     from a scheduled run through to something a human can see.
  2. Prerequisite. Detection only runs off a *scheduled* completion, so a
     subscription with no recurring schedule for the same analysis never fires.
     Live state on 2026-08-20: an active `maturity` subscription on sqlglot, no
     schedule for it, `last_checked_at` empty — inert, and the UI said so only in
     a toast at create time.

Neither produced an error. A subscription that never fires and a subscription
with nothing to report look identical from outside, which is why this needed a
test that follows the whole chain rather than a unit of it.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from resource_explorer import scheduler
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="p", display_name="P", github_url="u", description=""))
    return reg


def _drawer_rows(reg):
    """The selection GET /api/activity/rfas performs — what a human sees."""
    return [a for e in reg.list_activity(limit=500)
            for a in (e.get("annotations") or [])
            if "RequestForAction" in (a.get("annotation_type") or "")]


class TestDelivery:

    def test_a_detected_change_reaches_the_rfa_drawer(self, registry):
        """The end-to-end claim: change detected on a scheduled run becomes
        something visible on the surface built to act on it."""
        registry.create_subscription("repo", "p", "maturity", "Maturity changed")

        with patch("resource_explorer.notification_detector.detect_change") as detect:
            detect.return_value = type("R", (), {"changed": True, "summary": "B → A",
                                                 "detail": "grade improved"})()
            scheduler._check_subscriptions("repo", "p", "maturity", "P", registry)

        rows = _drawer_rows(registry)
        assert len(rows) == 1, "a detected change produced no visible RFA"

    def test_no_change_notifies_nobody(self, registry):
        registry.create_subscription("repo", "p", "maturity", "Maturity changed")

        with patch("resource_explorer.notification_detector.detect_change") as detect:
            detect.return_value = type("R", (), {"changed": False, "summary": "",
                                                 "detail": ""})()
            scheduler._check_subscriptions("repo", "p", "maturity", "P", registry)

        assert _drawer_rows(registry) == []

    def test_an_inactive_subscription_is_not_notified(self, registry):
        sub = registry.create_subscription("repo", "p", "maturity", "Maturity changed")
        registry.set_subscription_active(sub["id"], False)

        with patch("resource_explorer.notification_detector.detect_change") as detect:
            detect.return_value = type("R", (), {"changed": True, "summary": "x",
                                                 "detail": ""})()
            scheduler._check_subscriptions("repo", "p", "maturity", "P", registry)

        assert _drawer_rows(registry) == []

    def test_checking_is_recorded_even_when_nothing_changed(self, registry):
        """`last_checked_at` is how a user distinguishes "watching, nothing to
        report" from "never ran" — the exact ambiguity that hid the fault."""
        registry.create_subscription("repo", "p", "maturity", "Maturity changed")

        with patch("resource_explorer.notification_detector.detect_change") as detect:
            detect.return_value = type("R", (), {"changed": False, "summary": "",
                                                 "detail": ""})()
            scheduler._check_subscriptions("repo", "p", "maturity", "P", registry)

        assert registry.list_subscriptions()[0]["last_checked_at"]


class TestTheScheduledPrerequisiteIsVisible:
    """A subscription that can never fire must say so wherever it is shown, not
    only in a toast at the moment it was created."""

    @pytest.fixture
    def client(self, registry, monkeypatch):
        from fastapi.testclient import TestClient

        from resource_explorer.web.app import app

        monkeypatch.setattr("resource_explorer.web.routes.automate.ProjectRegistry",
                            lambda *a, **kw: registry)
        return TestClient(app)

    def test_a_subscription_without_a_schedule_is_flagged(self, client, registry):
        registry.create_subscription("repo", "p", "maturity", "Maturity changed")
        rows = client.get("/api/automate/subscriptions").json()
        assert rows[0]["has_schedule"] is False

    def test_a_subscription_with_a_matching_schedule_is_not_flagged(self, client, registry):
        registry.create_subscription("repo", "p", "maturity", "Maturity changed")
        registry.save_schedule(entity_type="repo", entity_slug="p",
                               analysis_id="maturity", schedule="daily", enabled=True)
        assert client.get("/api/automate/subscriptions").json()[0]["has_schedule"] is True

    def test_a_manual_schedule_does_not_count(self, client, registry):
        """"manual" never recurs, so nothing ever completes on a cadence for
        detection to compare against — it is no schedule at all for this."""
        registry.create_subscription("repo", "p", "maturity", "Maturity changed")
        registry.save_schedule(entity_type="repo", entity_slug="p",
                               analysis_id="maturity", schedule="manual", enabled=True)
        assert client.get("/api/automate/subscriptions").json()[0]["has_schedule"] is False

    def test_a_schedule_for_a_different_analysis_does_not_count(self, client, registry):
        """The live case: the only schedule was for another entity and another
        analysis, so the subscription was inert while both existed."""
        registry.create_subscription("repo", "p", "maturity", "Maturity changed")
        registry.save_schedule(entity_type="repo", entity_slug="p",
                               analysis_id="security_scan", schedule="daily", enabled=True)
        assert client.get("/api/automate/subscriptions").json()[0]["has_schedule"] is False

    def test_a_disabled_schedule_does_not_count(self, client, registry):
        registry.create_subscription("repo", "p", "maturity", "Maturity changed")
        registry.save_schedule(entity_type="repo", entity_slug="p",
                               analysis_id="maturity", schedule="daily", enabled=False)
        assert client.get("/api/automate/subscriptions").json()[0]["has_schedule"] is False
