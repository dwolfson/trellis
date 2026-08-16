"""Tests for notification_subscriptions — the Automate local-first
subscription registry (Discovery-tier Part 4).
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


class TestCreateAndGet:
    def test_create_returns_full_row(self, registry):
        sub = registry.create_subscription("repo", "myproj", "license_classification", "License risk changed")
        assert sub["entity_type"] == "repo"
        assert sub["entity_slug"] == "myproj"
        assert sub["analysis_id"] == "license_classification"
        assert sub["label"] == "License risk changed"
        assert sub["active"] == 1
        assert sub["notification_count"] == 0
        assert sub["created_at"]

    def test_slug_normalized(self, registry):
        sub = registry.create_subscription("repo", "MyProj", "maturity")
        assert sub["entity_slug"] == "myproj"

    def test_get_by_id(self, registry):
        created = registry.create_subscription("repo", "myproj", "maturity")
        fetched = registry.get_subscription(created["id"])
        assert fetched == created

    def test_get_missing_returns_none(self, registry):
        assert registry.get_subscription(9999) is None


class TestListSubscriptions:
    def test_filters_by_entity_and_analysis(self, registry):
        registry.create_subscription("repo", "a", "maturity")
        registry.create_subscription("repo", "b", "maturity")
        registry.create_subscription("repo", "a", "license_classification")

        all_a = registry.list_subscriptions(entity_slug="a")
        assert len(all_a) == 2

        maturity_only = registry.list_subscriptions(analysis_id="maturity")
        assert len(maturity_only) == 2
        assert {s["entity_slug"] for s in maturity_only} == {"a", "b"}

    def test_active_only_excludes_deactivated(self, registry):
        sub = registry.create_subscription("repo", "a", "maturity")
        registry.set_subscription_active(sub["id"], False)
        assert registry.list_subscriptions(entity_slug="a", active_only=True) == []
        assert len(registry.list_subscriptions(entity_slug="a", active_only=False)) == 1


class TestLifecycle:
    def test_deactivate_and_reactivate(self, registry):
        sub = registry.create_subscription("repo", "a", "maturity")
        registry.set_subscription_active(sub["id"], False)
        assert registry.get_subscription(sub["id"])["active"] == 0
        registry.set_subscription_active(sub["id"], True)
        assert registry.get_subscription(sub["id"])["active"] == 1

    def test_record_checked_updates_timestamp(self, registry):
        sub = registry.create_subscription("repo", "a", "maturity")
        registry.record_subscription_checked(sub["id"], "2026-08-13T00:00:00")
        assert registry.get_subscription(sub["id"])["last_checked_at"] == "2026-08-13T00:00:00"

    def test_record_notified_increments_count_and_timestamp(self, registry):
        sub = registry.create_subscription("repo", "a", "maturity")
        registry.record_subscription_notified(sub["id"], "2026-08-13T00:00:00")
        registry.record_subscription_notified(sub["id"], "2026-08-14T00:00:00")
        row = registry.get_subscription(sub["id"])
        assert row["notification_count"] == 2
        assert row["last_notified_at"] == "2026-08-14T00:00:00"
