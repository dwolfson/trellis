"""Tests for the /api/survey-definitions routes."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import DatabaseEntity, Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
    ))
    r.register_database(DatabaseEntity(
        slug="mydb",
        display_name="My DB",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database_name="mydb",
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


def _fake_step(qn, executes_at, re_analysis_step=None, description=""):
    from resource_explorer.surveyors.survey_definition_reader import SurveyStep
    return SurveyStep(
        guid=f"guid-{qn}", display_name=qn, qualified_name=qn,
        executes_at=executes_at, re_analysis_step=re_analysis_step, description=description,
    )


def _fake_survey_def(qn="GovActionProcess::Test", description="A test survey", steps=None):
    from resource_explorer.surveyors.survey_definition_reader import SurveyDefinition
    return SurveyDefinition(
        process_guid="proc-guid", display_name=qn, qualified_name=qn,
        supported_technology_type="PostgreSQL Database",
        steps=steps or [], description=description,
    )


class TestListCandidates:
    def test_unknown_entity_type_returns_400(self, client):
        resp = client.get("/api/survey-definitions/not-a-real-type/mydb/candidates")
        assert resp.status_code == 400

    def test_returns_step_detail_for_valid_candidate(self, client):
        step = _fake_step(
            "GovActionProcessStep::Test::SchemaAndStats", "resource-explorer",
            re_analysis_step="postgres_schema_and_stats", description="",
        )
        survey_def = _fake_survey_def(steps=[step])

        with patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
            return_value=[{"qualified_name": "GovActionProcess::Test", "display_name": "Test", "guid": "proc-guid"}],
        ), patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.fetch",
            return_value=survey_def,
        ):
            resp = client.get("/api/survey-definitions/database/mydb/candidates")

        assert resp.status_code == 200
        data = resp.json()
        assert data["technology_type"] == "PostgreSQL Database"
        assert len(data["candidates"]) == 1
        candidate = data["candidates"][0]
        assert candidate["error"] is None
        assert candidate["description"] == "A test survey"
        assert len(candidate["steps"]) == 1
        step_out = candidate["steps"][0]
        assert step_out["executes_at"] == "resource-explorer"
        assert "SchemaAnalysisAnnotation" in step_out["annotation_types"]

    def test_survey_kind_query_param_threaded_to_reader(self, client):
        with patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
            return_value=[],
        ) as mock_find:
            resp = client.get("/api/survey-definitions/database/mydb/candidates?survey_kind=discovery")

        assert resp.status_code == 200
        mock_find.assert_called_once()
        assert mock_find.call_args.kwargs.get("survey_kind") == "discovery"

    def test_no_survey_kind_query_param_defaults_to_none(self, client):
        # Backward compatibility — omitting the param must behave exactly as
        # before this feature (every candidate for the technology type).
        with patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
            return_value=[],
        ) as mock_find:
            resp = client.get("/api/survey-definitions/database/mydb/candidates")

        assert resp.status_code == 200
        assert mock_find.call_args.kwargs.get("survey_kind") is None

    def test_egeria_step_enriched_with_produced_annotation_types(self, client):
        step = _fake_step(
            "GovActionProcessStep::Test::RowCountSnapshot", "egeria", description="",
        )
        survey_def = _fake_survey_def(steps=[step])
        fake_produced = [{
            "name": "Capture Database Measurements",
            "description": "Capture summary statistics about a database.",
            "explanation": "",
            "annotation_type": "ResourceMeasureAnnotation",
            "analysis_step_name": "Profiling Associated Resources",
        }]

        with patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
            return_value=[{"qualified_name": "GovActionProcess::Test", "display_name": "Test", "guid": "proc-guid"}],
        ), patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.fetch",
            return_value=survey_def,
        ), patch(
            "resource_explorer.surveyors.egeria_tech_type_catalog.EgeriaTechTypeCatalog.get_produced_annotation_types",
            return_value=fake_produced,
        ):
            resp = client.get("/api/survey-definitions/database/mydb/candidates")

        assert resp.status_code == 200
        step_out = resp.json()["candidates"][0]["steps"][0]
        assert step_out["egeria_produced_annotation_types"] == fake_produced

    def test_egeria_tech_type_catalog_failure_does_not_break_listing(self, client):
        step = _fake_step("GovActionProcessStep::Test::RowCountSnapshot", "egeria", description="")
        survey_def = _fake_survey_def(steps=[step])

        with patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
            return_value=[{"qualified_name": "GovActionProcess::Test", "display_name": "Test", "guid": "proc-guid"}],
        ), patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.fetch",
            return_value=survey_def,
        ), patch(
            "resource_explorer.surveyors.egeria_tech_type_catalog.EgeriaTechTypeCatalog.get_produced_annotation_types",
            side_effect=Exception("Egeria unreachable"),
        ):
            resp = client.get("/api/survey-definitions/database/mydb/candidates")

        assert resp.status_code == 200
        step_out = resp.json()["candidates"][0]["steps"][0]
        assert "egeria_produced_annotation_types" not in step_out

    def test_unfetchable_candidate_surfaces_as_errored_not_crashing(self, client):
        with patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
            return_value=[{"qualified_name": "GovActionProcess::Branching", "display_name": "Branching", "guid": "bad-guid"}],
        ), patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.fetch",
            side_effect=Exception("branching Survey Definitions are not supported yet"),
        ):
            resp = client.get("/api/survey-definitions/database/mydb/candidates")

        assert resp.status_code == 200
        candidates = resp.json()["candidates"]
        assert len(candidates) == 1
        assert candidates[0]["error"] is not None
        assert candidates[0]["steps"] == []

    def test_empty_candidates_list(self, client):
        with patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
            return_value=[],
        ):
            resp = client.get("/api/survey-definitions/database/mydb/candidates")
        assert resp.status_code == 200
        assert resp.json()["candidates"] == []

    def test_phase_param_uses_scoped_lookup_when_questions_resolve(self, client):
        # D2 (docs/survey-question-context-plan.md): phase given, question
        # catalog returns entries -> scoped lookup used, full scan skipped.
        with patch(
            "resource_explorer.surveyors.question_catalog_reader.get_questions",
            return_value=[{"question": "Is this repository actively maintained?", "answering": {}}],
        ), patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids_by_questions",
            return_value=[{"qualified_name": "GovActionProcess::Scoped", "display_name": "Scoped", "guid": "g1"}],
        ) as mock_scoped, patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
        ) as mock_full_scan:
            resp = client.get("/api/survey-definitions/database/mydb/candidates?phase=scouting")

        assert resp.status_code == 200
        mock_scoped.assert_called_once()
        mock_full_scan.assert_not_called()
        assert resp.json()["candidates"][0]["qualified_name"] == "GovActionProcess::Scoped"

    def test_phase_param_falls_back_to_full_scan_when_scoped_lookup_empty(self, client):
        # No Question resolved to a real GUID yet (or none scoped to a
        # matching Survey Definition) -> falls back to the full scan rather
        # than showing an empty list, per D2's own decision.
        with patch(
            "resource_explorer.surveyors.question_catalog_reader.get_questions",
            return_value=[{"question": "Some question", "answering": {}}],
        ), patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids_by_questions",
            return_value=[],
        ), patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
            return_value=[{"qualified_name": "GovActionProcess::FullScan", "display_name": "FullScan", "guid": "g2"}],
        ) as mock_full_scan:
            resp = client.get("/api/survey-definitions/database/mydb/candidates?phase=scouting")

        assert resp.status_code == 200
        mock_full_scan.assert_called_once()
        assert resp.json()["candidates"][0]["qualified_name"] == "GovActionProcess::FullScan"

    def test_no_phase_param_falls_back_to_full_scan_when_no_cataloged_questions(self, client):
        # entity_type=database has zero cataloged questions today
        # (question_catalog.yaml only has "repo" entries) — falls back to
        # the full scan, but because get_questions() genuinely returns
        # nothing for this entity type, not because phase was omitted.
        with patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids_by_questions",
        ) as mock_scoped, patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
            return_value=[],
        ) as mock_full_scan:
            resp = client.get("/api/survey-definitions/database/mydb/candidates")

        assert resp.status_code == 200
        mock_scoped.assert_not_called()
        mock_full_scan.assert_called_once()

    def test_no_phase_param_still_uses_scoped_lookup_by_default(self, client):
        # Real live bug, fixed 2026-08-13: the UI never sends phase= at all
        # (see loadSurveyDefinitionsPanel() in index.html), and even when it
        # did, Discovery's own Survey Definitions are ScopedBy Questions
        # tagged asked_at=Scouting — never phase='discovery' — so gating the
        # scoped lookup behind an explicit phase param meant it silently
        # never engaged for the real Discovery UI. Confirmed here: omitting
        # phase entirely (matching exactly what the UI sends) still tries
        # the scoped lookup first, using every cataloged question for the
        # resource type.
        with patch(
            "resource_explorer.surveyors.question_catalog_reader.get_questions",
            return_value=[{"question": "Is this repository actively maintained?", "answering": {}}],
        ) as mock_get_questions, patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids_by_questions",
            return_value=[{"qualified_name": "GovActionProcess::Scoped", "display_name": "Scoped", "guid": "g1"}],
        ) as mock_scoped, patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
        ) as mock_full_scan:
            resp = client.get("/api/survey-definitions/repo/myproj/candidates?survey_kind=discovery")

        assert resp.status_code == 200
        mock_get_questions.assert_called_once_with(resource_type="repo", phase=None, perspectives=None)
        mock_scoped.assert_called_once()
        mock_full_scan.assert_not_called()
        assert resp.json()["candidates"][0]["qualified_name"] == "GovActionProcess::Scoped"

    def test_egeria_native_processes_excludes_delete_kind(self, client):
        # Uses the real config/technology_type_processes.yaml (seeded for
        # "PostgreSQL Relational Database") rather than mocking — this is the
        # externalized table, not something to fake in a unit test.
        with patch(
            "resource_explorer.surveyors.survey_definition_reader.SurveyDefinitionReader.find_candidate_process_guids",
            return_value=[],
        ):
            resp = client.get("/api/survey-definitions/database/mydb/candidates")
        assert resp.status_code == 200
        native = resp.json()["egeria_native_processes"]
        kinds = {p["kind"] for p in native}
        assert "delete" not in kinds
        assert "survey_existing" in kinds
        assert "catalog_and_survey" in kinds


class TestRunSurveyDefinition:
    def test_run_returns_executor_result(self, client):
        fake_result = {
            "source": "survey-definition", "entity_type": "database", "slug": "mydb",
            "process_qualified_name": "GovActionProcess::Test",
            "steps": [{"step": "SchemaAndStats", "status": "ok"}],
            "errors": [], "egeria_report_guid": "report-guid-123",
        }
        with patch(
            "resource_explorer.surveyors.survey_definition_executor.run_survey_definition",
            return_value=fake_result,
        ) as mock_run:
            resp = client.post(
                "/api/survey-definitions/database/mydb/run",
                json={"survey_definition_ref": "GovActionProcess::Test", "db_user": "u", "db_pwd": "p"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["egeria_report_guid"] == "report-guid-123"
        assert body["egeria_portal_report_url"].endswith("/tech-catalog?guid=report-guid-123")
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["survey_definition_ref"] == "GovActionProcess::Test"
        assert kwargs["db_user"] == "u"

    def test_run_without_report_guid_has_no_portal_link(self, client):
        fake_result = {
            "source": "survey-definition", "entity_type": "database", "slug": "mydb",
            "process_qualified_name": "GovActionProcess::Test",
            "steps": [], "errors": ["something went wrong"], "egeria_report_guid": "",
        }
        with patch(
            "resource_explorer.surveyors.survey_definition_executor.run_survey_definition",
            return_value=fake_result,
        ):
            resp = client.post(
                "/api/survey-definitions/database/mydb/run",
                json={"survey_definition_ref": "GovActionProcess::Test"},
            )
        assert resp.status_code == 200
        assert "egeria_portal_report_url" not in resp.json()

    def test_run_maps_executor_error_to_400(self, client):
        from resource_explorer.surveyors.survey_definition_executor import SurveyDefinitionExecutorError
        with patch(
            "resource_explorer.surveyors.survey_definition_executor.run_survey_definition",
            side_effect=SurveyDefinitionExecutorError("no candidates found"),
        ):
            resp = client.post(
                "/api/survey-definitions/database/mydb/run",
                json={"survey_definition_ref": "GovActionProcess::Test"},
            )
        assert resp.status_code == 400
