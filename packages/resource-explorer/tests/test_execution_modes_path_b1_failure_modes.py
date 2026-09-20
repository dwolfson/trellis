"""Phase 2 of PLAN-EXECUTION-MODES-VERIFICATION.md — Path B1 failure-mode
tests (plan §2 "Path B", the B1 bullet).

Pure unit tests, no live Egeria needed. `survey_definition_executor.py:473-514`
has three distinct outcomes for a step whose `executes_at` is not
"resource-explorer", and this codebase's own stated principle is that a
Survey Definition run must never silently succeed when a step genuinely never
executed (see that module's `_stamp_definition_provenance`-adjacent comments
and the 2026-08-24 "closing the stub" fix already pinned by
test_survey_definition_executor.py's `test_dispatch_loop_runs_known_step_and_
reports_unknown_step`). These tests pin the three failure shapes precisely,
including one exercised through the REAL `database` adapter
(`database/survey_definition_adapter.py`'s `_trigger_egeria_native_survey`)
rather than only a test double, since that is the actual code the "no stored
Egeria asset guid" message lives in.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import resource_explorer.surveyors.database.survey_definition_adapter as db_adapter
from resource_explorer.registry import DatabaseEntity
from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    SurveyDefinitionExecutor,
    get_adapter,
    register_adapter,
)
from resource_explorer.surveyors.survey_definition_reader import SurveyDefinition, SurveyStep


def _fake_reader(survey_def, candidates=None):
    reader = MagicMock()
    reader.fetch.return_value = survey_def
    reader.find_candidate_process_guids.return_value = candidates or []
    return reader


def _fake_registry():
    registry = MagicMock()
    registry.get_survey_definition_guid.return_value = None
    registry.has_assigned_egeria_project.return_value = False
    return registry


class TestUncataloguedAssetRaises:
    """`_trigger_egeria_native_survey` (database/survey_definition_adapter.py)
    is the real handler behind `other_engine_handlers["egeria"]` — this is
    the code the "no stored Egeria asset guid" message actually lives in,
    tested directly first, then through the full executor dispatch."""

    def test_direct_call_raises_with_the_exact_message(self):
        db_entity = DatabaseEntity(
            slug="uncatalogued-db", display_name="Uncatalogued", db_type="postgresql",
            host="localhost", port=5432, database_name="mydb", egeria_asset_guid="",
        )
        with pytest.raises(RuntimeError, match="no stored Egeria asset guid"):
            db_adapter._trigger_egeria_native_survey(db_entity, MagicMock(), step=MagicMock())

    def test_a_guid_present_does_not_raise_and_triggers_the_native_survey(self):
        """Sanity check on the other side of the same branch — a cataloged
        database does not hit this failure mode at all. Since the async
        result-retrieval build, this now also polls to a terminal status and
        reads back the produced report's annotations — both pyegeria clients
        (trigger/poll) and the report/annotation reads are mocked here; the
        happy-path detail (report attribution, annotation conversion) is
        covered by test_egeria_async_survey_result.py instead of duplicated."""
        from datetime import datetime, timedelta, timezone

        db_entity = DatabaseEntity(
            slug="catalogued-db", display_name="Catalogued", db_type="postgresql",
            host="localhost", port=5432, database_name="mydb",
            egeria_asset_guid="asset-guid-123",
        )
        fake_surveyor = MagicMock()
        fake_surveyor.trigger_survey_by_guid.return_value = "engine-action-guid-1"
        fake_surveyor.get_survey_reports_by_guid.return_value = [
            # Comfortably after whatever wall-clock instant the handler
            # records as its trigger time during the test.
            {"guid": "report-guid-1", "qualified_name": "SurveyReport::x",
             "surveyed_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()},
        ]
        fake_surveyor.get_annotations_by_report_guid.return_value = []

        metadata_expert = MagicMock()
        metadata_expert.get_metadata_element_by_guid.return_value = {
            "elementProperties": {"propertyValueMap": {
                "activityStatus": {"symbolicName": "COMPLETED"},
            }}
        }

        with patch(
            "resource_explorer.surveyors.database.egeria_database_surveyor.EgeriaDatabaseSurveyor",
            return_value=fake_surveyor,
        ), patch(
            "resource_explorer.surveyors.egeria_async_survey_result._get_clients",
            return_value=(MagicMock(), metadata_expert),
        ):
            result = db_adapter._trigger_egeria_native_survey(db_entity, MagicMock(), step=MagicMock())

        assert result["status"] == "ok"
        assert result["engine_action_guid"] == "engine-action-guid-1"
        assert result["final_status"] == "COMPLETED"
        assert result["report_guid"] == "report-guid-1"
        assert result["annotations"] == []
        fake_surveyor.trigger_survey_by_guid.assert_called_once_with("asset-guid-123")

    def test_through_the_full_executor_the_raise_becomes_a_reported_error_not_a_crash(self):
        """survey_definition_executor.py:473-486 — other_engine_handlers is
        called inside a try/except; the handler's RuntimeError must surface
        as an `errors` entry and an `"error"` step status, not propagate out
        of `run()`."""
        register_adapter(get_adapter("database"))  # ensure the real adapter is registered

        db_entity = DatabaseEntity(
            slug="uncatalogued-db", display_name="Uncatalogued", db_type="postgresql",
            host="localhost", port=5432, database_name="mydb", egeria_asset_guid="",
        )
        registry = _fake_registry()
        registry.get_database.return_value = db_entity

        survey_def = SurveyDefinition(
            process_guid="proc-uncatalogued",
            display_name="Uncatalogued DB Survey",
            qualified_name="GovActionProcess::UncataloguedDb",
            supported_technology_type="PostgreSQL Database",
            steps=[
                SurveyStep(
                    guid="s1", display_name="EgeriaNative", qualified_name="Step::EgeriaNative",
                    executes_at="egeria", re_analysis_step=None,
                ),
            ],
        )
        reader = _fake_reader(survey_def, candidates=[
            {"guid": "proc-uncatalogued", "qualified_name": "GovActionProcess::UncataloguedDb",
             "display_name": "UncataloguedDb"},
        ])
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        result = executor.run(entity_type="database", slug="uncatalogued-db")

        statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert statuses["Step::EgeriaNative"] == "error"
        assert len(result["errors"]) == 1
        assert "no stored Egeria asset guid" in result["errors"][0]


class TestUnregisteredEngineHandlerYieldsNotExecuted:
    """survey_definition_executor.py:487-510 — an entity type with no
    `other_engine_handlers["egeria"]` registered at all. Repos are the real,
    live example (plan §1 Path B / §0(a)): `repo_survey_definition_adapter.py`
    registers no `other_engine_handlers`, so a repo Survey Definition step
    tagged executes_at="egeria" genuinely never runs anywhere."""

    def test_repo_adapter_has_no_egeria_handler_registered(self):
        """Confirms the premise directly against the real adapter, so the
        next test's result isn't just an artifact of a stale import."""
        import resource_explorer.surveyors.repo_survey_definition_adapter  # noqa: F401

        adapter = get_adapter("repo")
        assert "egeria" not in adapter.other_engine_handlers

    def test_repo_egeria_step_is_not_executed_no_egeria_handler_and_counted_as_an_error(self):
        import resource_explorer.surveyors.repo_survey_definition_adapter  # noqa: F401

        adapter = get_adapter("repo")
        registry = _fake_registry()
        registry.get.return_value = MagicMock(display_name="Fixture Repo", github_url="")

        survey_def = SurveyDefinition(
            process_guid="proc-repo-egeria",
            display_name="Repo Egeria-side Survey",
            qualified_name="GovActionProcess::RepoEgeriaSide",
            supported_technology_type=adapter.technology_type,
            steps=[
                SurveyStep(
                    guid="s1", display_name="EgeriaNative", qualified_name="Step::EgeriaNative",
                    executes_at="egeria", re_analysis_step=None,
                ),
            ],
        )
        reader = _fake_reader(survey_def, candidates=[
            {"guid": "proc-repo-egeria", "qualified_name": "GovActionProcess::RepoEgeriaSide",
             "display_name": "RepoEgeriaSide"},
        ])
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        result = executor.run(entity_type="repo", slug="fixture-repo")

        statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert statuses["Step::EgeriaNative"] == "not_executed_no_egeria_handler"
        assert len(result["errors"]) == 1
        assert "Step::EgeriaNative" in result["errors"][0]
        assert "no other_engine_handlers['egeria']" in result["errors"][0] or \
               "other_engine_handlers['egeria']" in result["errors"][0]


class TestUnrecognizedExecutesAtYieldsUnrecognizedEngine:
    """survey_definition_executor.py:511-519 — a value that is neither
    'resource-explorer' nor 'egeria' nor a Prefect route nor a registered
    other_engine_handlers key."""

    def test_an_unknown_executes_at_value_is_reported_not_silently_skipped(self):
        adapter = ResourceTypeAdapter(
            entity_type="fake_unrecognized",
            technology_type="Fake Tech Unrecognized",
            re_analysis_steps={},
            get_entity=lambda registry, slug: object(),
            publish=MagicMock(),
        )
        register_adapter(adapter)

        survey_def = SurveyDefinition(
            process_guid="proc-unrecognized",
            display_name="Unrecognized Engine Survey",
            qualified_name="GovActionProcess::Unrecognized",
            supported_technology_type="Fake Tech Unrecognized",
            steps=[
                SurveyStep(
                    guid="s1", display_name="AirflowStep", qualified_name="Step::Airflow",
                    executes_at="airflow", re_analysis_step=None,
                ),
            ],
        )
        registry = _fake_registry()
        reader = _fake_reader(survey_def, candidates=[
            {"guid": "proc-unrecognized", "qualified_name": "GovActionProcess::Unrecognized",
             "display_name": "Unrecognized"},
        ])
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        result = executor.run(entity_type="fake_unrecognized", slug="whatever")

        statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert statuses["Step::Airflow"] == "unrecognized_engine"
        assert len(result["errors"]) == 1
        assert "unrecognized executes_at='airflow'" in result["errors"][0]
