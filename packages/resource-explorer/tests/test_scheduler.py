"""Tests for the background scheduler's due-analysis execution.

Focus: every run — success or failure — must write a real ActivityEntry
(previously scheduler.py only logged to Python's own logger, invisible from
the UI) and must record the outcome on the schedule row itself, which is
what the Admin Schedules overview reads.
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
def registered_database_with_credentials(registry):
    registry.register_database(DatabaseEntity(
        slug="mydb",
        display_name="My DB",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database_name="mydb",
        db_user="admin",
        db_password="secret",
    ))
    return "mydb"


@pytest.fixture
def registered_database_without_credentials(registry):
    registry.register_database(DatabaseEntity(
        slug="mydb-no-creds",
        display_name="My DB (no creds)",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database_name="mydb",
    ))
    return "mydb-no-creds"


def _make_due(registry, entity_type, slug, analysis_id="security_scan"):
    registry.save_schedule(entity_type, slug, analysis_id, "daily", True)
    # save_schedule computes next_run in the future — force it due now.
    with registry._conn() as conn:
        conn.execute(
            "UPDATE resource_schedules SET next_run = '2020-01-01T00:00:00+00:00' "
            "WHERE entity_type=? AND entity_slug=? AND analysis_id=?",
            (entity_type, slug, analysis_id),
        )


class TestRunDueSuccess:
    def test_successful_repo_survey_writes_ok_activity_entry(self, registry, registered_project):
        _make_due(registry, "repo", registered_project)
        fake_result = MagicMock(errors=[])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        entries = registry.list_activity(entity_slug=registered_project)
        assert len(entries) == 1
        assert entries[0]["status"] == "ok"
        assert entries[0]["operation"] == "survey"
        assert "completed successfully" in entries[0]["summary"]

    def test_successful_run_updates_schedule_status(self, registry, registered_project):
        _make_due(registry, "repo", registered_project)
        fake_result = MagicMock(errors=[])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        rows = registry.get_schedules("repo", registered_project)
        assert rows[0]["last_run_status"] == "ok"
        assert rows[0]["last_run_activity_id"]  # linked to the activity entry
        assert rows[0]["last_run"]

    def test_activity_id_on_schedule_matches_written_entry(self, registry, registered_project):
        _make_due(registry, "repo", registered_project)
        fake_result = MagicMock(errors=[])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        activity_id = registry.get_schedules("repo", registered_project)[0]["last_run_activity_id"]
        assert registry.get_activity(activity_id) is not None


class TestRunDueFailure:
    def test_survey_raising_writes_error_activity_entry(self, registry, registered_project):
        _make_due(registry, "repo", registered_project)
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.side_effect = RuntimeError("survey blew up")
            scheduler._run_due()

        entries = registry.list_activity(entity_slug=registered_project)
        assert len(entries) == 1
        assert entries[0]["status"] == "error"
        assert "survey blew up" in entries[0]["detail"]

    def test_survey_raising_updates_schedule_error_status(self, registry, registered_project):
        _make_due(registry, "repo", registered_project)
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.side_effect = RuntimeError("boom")
            scheduler._run_due()

        rows = registry.get_schedules("repo", registered_project)
        assert rows[0]["last_run_status"] == "error"

    def test_survey_completing_with_partial_errors_is_recorded_as_error(self, registry, registered_project):
        _make_due(registry, "repo", registered_project)
        fake_result = MagicMock(errors=["some sub-surveyor failed"])
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            scheduler._run_due()

        entries = registry.list_activity(entity_slug=registered_project)
        assert entries[0]["status"] == "error"
        assert "some sub-surveyor failed" in entries[0]["detail"]

    def test_missing_repo_writes_error_entry_not_a_crash(self, registry):
        _make_due(registry, "repo", "deleted-repo-slug")
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry):
            scheduler._run_due()  # must not raise

        entries = registry.list_activity(entity_slug="deleted-repo-slug")
        assert len(entries) == 1
        assert entries[0]["status"] == "error"
        assert "not found" in entries[0]["detail"]
        assert registry.get_schedules("repo", "deleted-repo-slug")[0]["last_run_status"] == "error"


class TestRunDueDatabaseSurvey:
    """Regression coverage for the real bug reported live: scheduled database
    surveys crashed with a bare KeyError('user') because scheduler.py passed
    an empty credentials dict with no resolution step. Fixed to resolve
    db.db_user/db.db_password the same way the manual survey route does."""

    def test_missing_credentials_produces_clear_error_not_a_crash(self, registry, registered_database_without_credentials):
        _make_due(registry, "database", registered_database_without_credentials, analysis_id="schema_inventory")
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry):
            scheduler._run_due()  # must not raise

        entries = registry.list_activity(entity_slug=registered_database_without_credentials)
        assert len(entries) == 1
        assert entries[0]["status"] == "error"
        assert "No stored database credentials" in entries[0]["detail"]
        assert registry.get_schedules("database", registered_database_without_credentials)[0]["last_run_status"] == "error"

    def test_stored_credentials_are_used_for_the_survey(self, registry, registered_database_with_credentials):
        _make_due(registry, "database", registered_database_with_credentials, analysis_id="schema_inventory")
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.database.database_surveyor.run_database_survey") as mock_run:
            mock_run.return_value = {}
            scheduler._run_due()

        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["credentials"] == {"user": "admin", "password": "secret"}

    def test_successful_database_survey_writes_ok_entry(self, registry, registered_database_with_credentials):
        _make_due(registry, "database", registered_database_with_credentials, analysis_id="schema_inventory")
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.database.database_surveyor.run_database_survey", return_value={}):
            scheduler._run_due()

        entries = registry.list_activity(entity_slug=registered_database_with_credentials)
        assert entries[0]["status"] == "ok"
        rows = registry.get_schedules("database", registered_database_with_credentials)
        assert rows[0]["last_run_status"] == "ok"

    def test_survey_exception_with_valid_credentials_is_recorded_as_error(self, registry, registered_database_with_credentials):
        _make_due(registry, "database", registered_database_with_credentials, analysis_id="schema_inventory")
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.database.database_surveyor.run_database_survey") as mock_run:
            mock_run.side_effect = RuntimeError("connection refused")
            scheduler._run_due()

        entries = registry.list_activity(entity_slug=registered_database_with_credentials)
        assert entries[0]["status"] == "error"
        assert "connection refused" in entries[0]["detail"]


class TestRunDueMisc:
    def test_no_due_schedules_is_a_noop(self, registry):
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry):
            scheduler._run_due()  # should not raise, nothing to do
        assert registry.list_activity() == []

    def test_disabled_schedule_never_runs(self, registry, registered_project):
        registry.save_schedule("repo", registered_project, "security_scan", "daily", False)
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry), \
             patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            scheduler._run_due()
        MockOrch.assert_not_called()
        assert registry.list_activity() == []

    def test_unknown_entity_type_writes_error_entry(self, registry):
        registry.save_schedule("filesystem", "some-fs", "filesystem_inventory", "daily", True)
        with registry._conn() as conn:
            conn.execute(
                "UPDATE resource_schedules SET next_run = '2020-01-01T00:00:00+00:00' "
                "WHERE entity_type='filesystem' AND entity_slug='some-fs'"
            )
        with patch("resource_explorer.registry.ProjectRegistry", return_value=registry):
            scheduler._run_due()
        entries = registry.list_activity(entity_slug="some-fs")
        assert entries[0]["status"] == "error"
        assert "Unknown entity_type" in entries[0]["detail"]
