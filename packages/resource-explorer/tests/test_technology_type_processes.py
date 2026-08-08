"""Tests for the externalized Technology Type -> native process table
(config/technology_type_processes.yaml + its loader)."""
from __future__ import annotations

from resource_explorer.surveyors import technology_type_processes as ttp


def setup_function(_fn):
    ttp.clear_cache()


class TestGetNativeProcesses:
    def test_returns_seeded_postgres_database_processes(self):
        procs = ttp.get_native_processes("database", "PostgreSQL Relational Database")
        names = {p.qualified_name for p in procs}
        assert "PostgreSQLSurvey::survey-postgres-database" in names
        assert "PostgreSQLDatabase:CreateAndSurveyGovernanceActionProcess" in names

    def test_unknown_technology_type_returns_empty_list(self):
        assert ttp.get_native_processes("database", "Nonexistent Technology") == []

    def test_unknown_entity_type_returns_empty_list(self):
        assert ttp.get_native_processes("filesystem", "PostgreSQL Relational Database") == []


class TestGetProcessByKind:
    def test_finds_survey_existing_process(self):
        proc = ttp.get_process_by_kind("database", "PostgreSQL Relational Database", ttp.KIND_SURVEY_EXISTING)
        assert proc is not None
        assert proc.qualified_name == "PostgreSQLSurvey::survey-postgres-database"

    def test_finds_catalog_and_survey_process(self):
        proc = ttp.get_process_by_kind("database", "PostgreSQL Relational Database", ttp.KIND_CATALOG_AND_SURVEY)
        assert proc is not None
        assert proc.qualified_name == "PostgreSQLDatabase:CreateAndSurveyGovernanceActionProcess"

    def test_finds_delete_process_but_caller_must_not_expose_it(self):
        # The loader itself doesn't gatekeep — callers (routes/adapters) are
        # responsible for never surfacing kind == "delete" as runnable.
        proc = ttp.get_process_by_kind("database", "PostgreSQL Relational Database", ttp.KIND_DELETE)
        assert proc is not None
        assert proc.kind == ttp.KIND_DELETE

    def test_missing_kind_returns_none(self):
        assert ttp.get_process_by_kind("database", "PostgreSQL Server", ttp.KIND_DELETE) is None

    def test_unknown_technology_type_returns_none(self):
        assert ttp.get_process_by_kind("database", "Nonexistent", ttp.KIND_SURVEY_EXISTING) is None
