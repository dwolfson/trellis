from unittest.mock import MagicMock

from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    SurveyDefinitionExecutor,
    SurveyDefinitionExecutorError,
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
    return registry


def test_dispatch_loop_runs_known_step_and_reports_unknown_step():
    known_runner = MagicMock(return_value={"ok": True})
    adapter = ResourceTypeAdapter(
        entity_type="fake",
        technology_type="Fake Tech",
        re_analysis_steps={"known_step": known_runner},
        get_entity=lambda registry, slug: object(),
        publish=MagicMock(return_value="report-guid-1"),
    )
    register_adapter(adapter)

    survey_def = SurveyDefinition(
        process_guid="proc-1",
        display_name="Fake Survey",
        qualified_name="GovActionProcess::Fake",
        supported_technology_type="Fake Tech",
        steps=[
            SurveyStep(
                guid="s1", display_name="Known", qualified_name="Step::Known",
                executes_at="resource-explorer", re_analysis_step="known_step",
            ),
            SurveyStep(
                guid="s2", display_name="Unknown", qualified_name="Step::Unknown",
                executes_at="resource-explorer", re_analysis_step="totally_unknown_step",
            ),
            SurveyStep(
                guid="s3", display_name="EgeriaSide", qualified_name="Step::Egeria",
                executes_at="egeria", re_analysis_step=None,
            ),
        ],
    )

    registry = _fake_registry()
    reader = _fake_reader(survey_def, candidates=[{"guid": "proc-1", "qualified_name": "GovActionProcess::Fake", "display_name": "Fake"}])
    executor = SurveyDefinitionExecutor(registry, reader=reader)

    result = executor.run(entity_type="fake", slug="my-fake")

    known_runner.assert_called_once()
    adapter.publish.assert_called_once()
    assert len(result["errors"]) == 1
    assert "totally_unknown_step" in result["errors"][0]
    statuses = {s["step"]: s["status"] for s in result["steps"]}
    assert statuses["Step::Known"] == "ok"
    assert statuses["Step::Unknown"] == "unknown_step"
    assert statuses["Step::Egeria"] == "skipped_egeria"
    assert result["egeria_report_guid"] == "report-guid-1"


def test_other_engine_handler_is_triggered_and_reported():
    known_runner = MagicMock(return_value={"ok": True})
    egeria_trigger = MagicMock(return_value={"engine_action_guid": "action-guid-1"})
    adapter = ResourceTypeAdapter(
        entity_type="fake3",
        technology_type="Fake Tech 3",
        re_analysis_steps={"known_step": known_runner},
        get_entity=lambda registry, slug: object(),
        publish=MagicMock(return_value="report-guid-2"),
        other_engine_handlers={"egeria": egeria_trigger},
    )
    register_adapter(adapter)

    survey_def = SurveyDefinition(
        process_guid="proc-2",
        display_name="Fake Survey 2",
        qualified_name="GovActionProcess::Fake2",
        supported_technology_type="Fake Tech 3",
        steps=[
            SurveyStep(
                guid="s1", display_name="Known", qualified_name="Step::Known",
                executes_at="resource-explorer", re_analysis_step="known_step",
            ),
            SurveyStep(
                guid="s2", display_name="EgeriaSide", qualified_name="Step::Egeria",
                executes_at="egeria", re_analysis_step=None,
            ),
        ],
    )

    registry = _fake_registry()
    reader = _fake_reader(survey_def, candidates=[{"guid": "proc-2", "qualified_name": "GovActionProcess::Fake2", "display_name": "Fake2"}])
    executor = SurveyDefinitionExecutor(registry, reader=reader)

    result = executor.run(entity_type="fake3", slug="my-fake3")

    egeria_trigger.assert_called_once()
    statuses = {s["step"]: s["status"] for s in result["steps"]}
    assert statuses["Step::Egeria"] == "triggered"
    egeria_entry = next(s for s in result["steps"] if s["step"] == "Step::Egeria")
    assert egeria_entry["detail"]["engine_action_guid"] == "action-guid-1"
    assert result["errors"] == []


def test_other_engine_handler_failure_reported_as_error():
    def _failing_handler(entity, registry, step, **_):
        raise RuntimeError("database not cataloged")

    adapter = ResourceTypeAdapter(
        entity_type="fake4",
        technology_type="Fake Tech 4",
        re_analysis_steps={},
        get_entity=lambda registry, slug: object(),
        publish=MagicMock(),
        other_engine_handlers={"egeria": _failing_handler},
    )
    register_adapter(adapter)

    survey_def = SurveyDefinition(
        process_guid="proc-3",
        display_name="Fake Survey 3",
        qualified_name="GovActionProcess::Fake3",
        supported_technology_type="Fake Tech 4",
        steps=[
            SurveyStep(
                guid="s1", display_name="EgeriaSide", qualified_name="Step::Egeria",
                executes_at="egeria", re_analysis_step=None,
            ),
        ],
    )
    registry = _fake_registry()
    reader = _fake_reader(survey_def, candidates=[{"guid": "proc-3", "qualified_name": "GovActionProcess::Fake3", "display_name": "Fake3"}])
    executor = SurveyDefinitionExecutor(registry, reader=reader)

    result = executor.run(entity_type="fake4", slug="my-fake4")

    statuses = {s["step"]: s["status"] for s in result["steps"]}
    assert statuses["Step::Egeria"] == "error"
    assert len(result["errors"]) == 1
    assert "database not cataloged" in result["errors"][0]


def test_unknown_entity_type_raises():
    registry = _fake_registry()
    executor = SurveyDefinitionExecutor(registry, reader=_fake_reader(None))
    try:
        executor.run(entity_type="not-a-real-type", slug="whatever")
        assert False, "expected SurveyDefinitionExecutorError"
    except SurveyDefinitionExecutorError:
        pass


def test_multiple_candidates_raises_ambiguity_error():
    adapter = ResourceTypeAdapter(
        entity_type="fake2",
        technology_type="Fake Tech 2",
        re_analysis_steps={},
        get_entity=lambda registry, slug: object(),
        publish=MagicMock(),
    )
    register_adapter(adapter)

    registry = _fake_registry()
    reader = _fake_reader(
        None,
        candidates=[
            {"guid": "g1", "qualified_name": "Survey::One", "display_name": "One"},
            {"guid": "g2", "qualified_name": "Survey::Two", "display_name": "Two"},
        ],
    )
    executor = SurveyDefinitionExecutor(registry, reader=reader)
    try:
        executor.run(entity_type="fake2", slug="whatever")
        assert False, "expected SurveyDefinitionExecutorError for ambiguous candidates"
    except SurveyDefinitionExecutorError as exc:
        assert "Survey::One" in str(exc) and "Survey::Two" in str(exc)
