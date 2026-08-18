"""Tests for DatabaseSurveyor.survey(steps=...) — the database per-card
dispatch fix (D6 prerequisite, docs/repo-scope-narrowing-funnel.md). Before
this, every local database analysis card triggered the identical whole-DB
survey (schema + statistics + views) regardless of which was clicked."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors.database.database_surveyor import (
    DATABASE_ANALYSIS_STEP_MAP,
    DatabaseSurveyor,
)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def db_entity(registry):
    entity = DatabaseEntity(
        slug="mydb", display_name="My DB", db_type="postgresql",
        host="localhost", port=5432, database_name="mydb",
        db_user="admin", db_password="secret",
    )
    registry.register_database(entity)
    return entity


def _mock_conn():
    conn = MagicMock()
    conn.get_schema_info.return_value = {"schemas": [], "total_tables": 0, "total_columns": 0}
    conn.get_statistics.return_value = {"row_stats": [], "table_stats": []}
    return conn


@contextmanager
def _patched_connection(conn):
    with patch(
        "resource_explorer.surveyors.database.database_surveyor.database_connection",
    ) as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = conn
        mock_ctx.return_value.__exit__.return_value = False
        yield


class TestStepsNone:
    def test_runs_schema_statistics_and_views(self, registry, db_entity):
        conn = _mock_conn()
        surveyor = DatabaseSurveyor(db_entity, {"user": "admin", "password": "secret"}, registry)
        with _patched_connection(conn), \
             patch.object(surveyor, "_survey_views", return_value=[]) as mock_views:
            surveyor.survey()
        conn.get_schema_info.assert_called_once()
        conn.get_statistics.assert_called_once()
        mock_views.assert_called_once()


class TestStepsFiltered:
    def test_schema_inventory_steps_skip_statistics(self, registry, db_entity):
        conn = _mock_conn()
        surveyor = DatabaseSurveyor(db_entity, {"user": "admin", "password": "secret"}, registry)
        with _patched_connection(conn), \
             patch.object(surveyor, "_survey_views", return_value=[]) as mock_views:
            surveyor.survey(steps=DATABASE_ANALYSIS_STEP_MAP["schema_inventory"])
        conn.get_schema_info.assert_called_once()  # "schema" always runs
        conn.get_statistics.assert_not_called()
        mock_views.assert_called_once()

    def test_row_count_snapshot_steps_skip_views(self, registry, db_entity):
        conn = _mock_conn()
        surveyor = DatabaseSurveyor(db_entity, {"user": "admin", "password": "secret"}, registry)
        with _patched_connection(conn), \
             patch.object(surveyor, "_survey_views", return_value=[]) as mock_views:
            surveyor.survey(steps=DATABASE_ANALYSIS_STEP_MAP["row_count_snapshot"])
        conn.get_schema_info.assert_called_once()
        conn.get_statistics.assert_called_once()
        mock_views.assert_not_called()

    def test_schema_always_runs_even_if_omitted_from_steps(self, registry, db_entity):
        conn = _mock_conn()
        surveyor = DatabaseSurveyor(db_entity, {"user": "admin", "password": "secret"}, registry)
        with _patched_connection(conn), \
             patch.object(surveyor, "_survey_views", return_value=[]) as mock_views:
            surveyor.survey(steps=["statistics"])  # "schema" deliberately omitted
        conn.get_schema_info.assert_called_once()
        conn.get_statistics.assert_called_once()
        mock_views.assert_not_called()


class TestDatabaseAnalysisStepMap:
    def test_maps_all_three_local_survey_ids(self):
        assert set(DATABASE_ANALYSIS_STEP_MAP) == {"schema_inventory", "row_count_snapshot", "privilege_audit"}

    def test_privilege_audit_still_runs_full_survey(self):
        # No dedicated check exists yet — must run every step, matching the
        # pre-dispatch-fix behavior exactly (D5's documented aspirational status).
        assert set(DATABASE_ANALYSIS_STEP_MAP["privilege_audit"]) == {"schema", "statistics", "views"}
