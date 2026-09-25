"""Tests for scheduler.py's Automate integration (Discovery-tier Part 4) —
after a scheduled run completes cleanly, active subscriptions watching that
exact (entity, analysis_id) get checked, and an RFA is written iff
notification_detector reports a real change.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.registry import DatabaseEntity, Project, ProjectRegistry
from resource_explorer import scheduler


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def registered_project(registry):
    registry.add(Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
        description="",
    ))
    return "myproj"


@pytest.fixture
def registered_database(registry):
    registry.register_database(DatabaseEntity(
        slug="coco_ods",
        display_name="Coco ODS",
        db_type="postgresql",
        host="localhost",
        port=5442,
        database_name="coco_ods",
    ))
    return "coco_ods"


def _make_due(registry, entity_type, slug, analysis_id):
    registry.save_schedule(entity_type, slug, analysis_id, "daily", True)
    with registry._conn() as conn:
        conn.execute(
            "UPDATE resource_schedules SET next_run = '2020-01-01T00:00:00+00:00' "
            "WHERE entity_type=? AND entity_slug=? AND analysis_id=?",
            (entity_type, slug, analysis_id),
        )


class TestSubscriptionDelivery:
    def test_no_subscription_no_rfa(self, registry, registered_project):
        _make_due(registry, "repo", registered_project, "license_classification")
        fake_result = MagicMock(errors=[])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        rfas = [e for e in registry.list_activity(entity_slug=registered_project) if e["operation"] == "rfa"]
        assert rfas == []

    def test_subscription_with_no_change_no_rfa(self, registry, registered_project):
        registry.create_subscription("repo", registered_project, "license_classification", "License risk changed")
        for ts in ("2026-08-01T00:00:00", "2026-08-02T00:00:00"):
            registry.upsert_finding(
                registered_project, "license_classification",
                [{"check_name": "license_risk_tier", "label": "permissive"}],
                surveyed_at=ts,
            )
        _make_due(registry, "repo", registered_project, "license_classification")
        fake_result = MagicMock(errors=[])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        rfas = [e for e in registry.list_activity(entity_slug=registered_project) if e["operation"] == "rfa"]
        assert rfas == []

        sub = registry.list_subscriptions(entity_slug=registered_project)[0]
        assert sub["last_checked_at"]
        assert sub["notification_count"] == 0

    def test_subscription_with_real_change_writes_rfa(self, registry, registered_project):
        registry.create_subscription("repo", registered_project, "license_classification", "License risk changed")
        registry.upsert_finding(
            registered_project, "license_classification",
            [{"check_name": "license_risk_tier", "label": "permissive"}],
            surveyed_at="2026-08-01T00:00:00",
        )
        registry.upsert_finding(
            registered_project, "license_classification",
            [{"check_name": "license_risk_tier", "label": "strong_copyleft"}],
            surveyed_at="2026-08-02T00:00:00",
        )
        _make_due(registry, "repo", registered_project, "license_classification")
        fake_result = MagicMock(errors=[])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        rfas = [e for e in registry.list_activity(entity_slug=registered_project) if e["operation"] == "rfa"]
        assert len(rfas) == 1
        assert "License risk changed" in rfas[0]["summary"]
        assert "strong_copyleft" in rfas[0]["detail"]

        sub = registry.list_subscriptions(entity_slug=registered_project)[0]
        assert sub["notification_count"] == 1
        assert sub["last_notified_at"]

    def test_inactive_subscription_never_checked(self, registry, registered_project):
        sub = registry.create_subscription("repo", registered_project, "license_classification")
        registry.set_subscription_active(sub["id"], False)
        registry.upsert_finding(
            registered_project, "license_classification",
            [{"check_name": "license_risk_tier", "label": "permissive"}], surveyed_at="2026-08-01T00:00:00",
        )
        registry.upsert_finding(
            registered_project, "license_classification",
            [{"check_name": "license_risk_tier", "label": "strong_copyleft"}], surveyed_at="2026-08-02T00:00:00",
        )
        _make_due(registry, "repo", registered_project, "license_classification")
        fake_result = MagicMock(errors=[])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        assert registry.get_subscription(sub["id"])["last_checked_at"] == ""
        rfas = [e for e in registry.list_activity(entity_slug=registered_project) if e["operation"] == "rfa"]
        assert rfas == []

    def test_failed_scheduled_run_never_checks_subscriptions(self, registry, registered_project):
        registry.create_subscription("repo", registered_project, "license_classification")
        _make_due(registry, "repo", registered_project, "license_classification")
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.side_effect = RuntimeError("boom")
            scheduler._run_due()

        sub = registry.list_subscriptions(entity_slug=registered_project)[0]
        assert sub["last_checked_at"] == ""


def _db_table(name, *, rows=1000, size=8192, schema="public"):
    return {
        "schema_name": schema, "table_name": name, "table_type": "BASE TABLE",
        "row_count": rows, "column_count": 3, "size_bytes": size,
        "description": "", "state": "measured",
    }


def _db_activity(table, *, ins=0, upd=0, dele=0, reset=None, schema="public"):
    return {
        "schema_name": schema, "table_name": table,
        "rows_inserted": ins, "rows_updated": upd, "rows_deleted": dele,
        "seq_scan": 0, "idx_scan": 0, "stats_reset": reset,
        "state": "measured",
    }


def _store_db_snapshot(registry, slug, surveyed_at, *, tables, activity):
    registry.record_database_survey(
        slug=slug, schema_count=1, table_count=len(tables),
        column_count=0, survey_data={}, source="local", surveyed_at=surveyed_at,
    )
    registry.write_detail_rows("database_tables", slug, surveyed_at, source="local", rows=tables)
    registry.write_detail_rows("database_table_activity", slug, surveyed_at, source="local", rows=activity)


class TestDatabaseSubscriptionDelivery:
    """Phase 1 slice 14: database subscriptions dispatch to
    db_change_comparator.detect_database_change, not the generic
    findings/metrics-backed detector (which has nothing to read for
    databases — see db_change_comparator.py's module docstring). Uses the
    real run_db_derived() (zero-fetch, deterministic) rather than mocking
    it, since the scheduled "survey" here is exactly that step."""

    def test_no_change_between_snapshots_writes_no_rfa(self, registry, registered_database):
        for at, ins in (("2026-09-14T00:00:00", 100), ("2026-09-21T00:00:00", 100)):
            _store_db_snapshot(
                registry, registered_database, at,
                tables=[_db_table("orders")],
                activity=[_db_activity("orders", ins=ins, reset="2026-09-01T00:00:00")],
            )
        registry.create_subscription("database", registered_database, "db_change_rates", "Orders changed")
        _make_due(registry, "database", registered_database, "db_change_rates")
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry):
            scheduler._run_due()

        rfas = [e for e in registry.list_activity(entity_slug=registered_database) if e["operation"] == "rfa"]
        assert rfas == []
        sub = registry.list_subscriptions(entity_slug=registered_database)[0]
        assert sub["last_checked_at"]
        assert sub["notification_count"] == 0

    def test_row_activity_between_snapshots_writes_an_rfa(self, registry, registered_database):
        _store_db_snapshot(
            registry, registered_database, "2026-09-14T00:00:00",
            tables=[_db_table("orders", rows=100)],
            activity=[_db_activity("orders", ins=1_000, reset="2026-09-01T00:00:00")],
        )
        _store_db_snapshot(
            registry, registered_database, "2026-09-21T00:00:00",
            tables=[_db_table("orders", rows=800)],
            activity=[_db_activity("orders", ins=8_000, reset="2026-09-01T00:00:00")],
        )
        registry.create_subscription("database", registered_database, "db_change_rates", "Orders changed")
        _make_due(registry, "database", registered_database, "db_change_rates")
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry):
            scheduler._run_due()

        rfas = [e for e in registry.list_activity(entity_slug=registered_database) if e["operation"] == "rfa"]
        assert len(rfas) == 1
        assert "Orders changed" in rfas[0]["summary"]
        assert "orders" in rfas[0]["detail"]

        sub = registry.list_subscriptions(entity_slug=registered_database)[0]
        assert sub["notification_count"] == 1

    def test_a_single_snapshot_is_insufficient_history_and_writes_no_rfa(self, registry, registered_database):
        """Absence discipline carried through the whole local delivery path:
        one survey is not "no change" and must not fire a false negative
        that later hides the database's real first change."""
        _store_db_snapshot(
            registry, registered_database, "2026-09-21T00:00:00",
            tables=[_db_table("orders")], activity=[_db_activity("orders", ins=100)],
        )
        registry.create_subscription("database", registered_database, "db_change_rates")
        _make_due(registry, "database", registered_database, "db_change_rates")
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry):
            scheduler._run_due()

        rfas = [e for e in registry.list_activity(entity_slug=registered_database) if e["operation"] == "rfa"]
        assert rfas == []
