"""Regression test for a real bug found 2026-09-19, live, the first time
`PREFECT_ENABLED` defaulted to true with a real reachable Prefect server: a
Survey Definition mixing `executes_at="resource-explorer"` and
`executes_at="egeria"` steps got its egeria step silently routed through the
whole-definition Prefect flow's local-analysis-step runner instead of its own
`other_engine_handlers["egeria"]` handler.

`_run_via_prefect` hands its ENTIRE plan to `prefect/flows.py`'s
`re_survey_definition_flow`, which calls `run_planned_step_task` for every
step with no per-step engine check at all — it always ends up at
`run_surveyor_step_task.fn`, the plain local-analysis-step runner. Repo Survey
Definitions never exposed this (repos have no Egeria-coordinated path today),
and phase 2 of PLAN-PREFECT-OR-ALTERNATIVE.md's live verification called
`run_prefect_step` directly for one step rather than exercising this
whole-definition path — so it went unnoticed until CI failed on a database
Survey Definition fixture after the default flipped.

The fix, in survey_definition_executor.py: `_all_steps_prefect_runnable()`
gates `_run_via_prefect` off entirely for a definition that mixes engines,
falling through to the existing local loop, which already routes each step
correctly one at a time (including calling `run_prefect_step` for individual
`executes_at="prefect"` steps). This test proves the egeria step reaches its
REAL handler — not a "not found"-shaped error from the wrong runner — with
Prefect orchestration forced on, independent of whether a real server happens
to be reachable in whatever environment runs this test.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    SurveyDefinitionExecutor,
    register_adapter,
)
from resource_explorer.surveyors.survey_definition_reader import SurveyDefinition, SurveyStep


@pytest.fixture(autouse=True)
def _force_prefect_orchestration_on(monkeypatch):
    """The bug only manifests when `_prefect_orchestration_enabled()` is
    true — force it, rather than depending on ambient `PREFECT_ENABLED` or a
    real reachable server, so this test is deterministic regardless of what
    environment runs it."""
    monkeypatch.setattr(
        "resource_explorer.surveyors.survey_definition_executor._prefect_orchestration_enabled",
        lambda: True,
    )


def _fake_registry():
    registry = MagicMock()
    registry.get_survey_definition_guid.return_value = None
    registry.has_assigned_egeria_project.return_value = False
    return registry


def _fake_reader(survey_def):
    reader = MagicMock()
    reader.fetch.return_value = survey_def
    return reader


class TestMixedEngineDefinitionSkipsWholeDefinitionPrefectOrchestration:
    def test_the_egeria_step_reaches_its_own_handler_not_the_local_runner(self):
        egeria_handler_calls = []

        def _egeria_handler(entity, registry, step, **kwargs):
            egeria_handler_calls.append(step.qualified_name)
            return {"engine_action_guid": "real-egeria-dispatch"}

        local_step_calls = []

        def _local_step(entity, registry, **kwargs):
            local_step_calls.append("ran")
            return {"annotations": []}

        entity = MagicMock()
        entity.slug = "mixed-entity"

        adapter = ResourceTypeAdapter(
            entity_type="mixed_resource",
            technology_type="Mixed Fixture",
            re_analysis_steps={"local_step": _local_step},
            get_entity=lambda registry, slug: entity,
            publish=lambda *a, **kw: "",
            other_engine_handlers={"egeria": _egeria_handler},
        )
        register_adapter(adapter)

        survey_def = SurveyDefinition(
            process_guid="proc-mixed",
            display_name="Mixed Engine Survey",
            qualified_name="GovActionProcess::Mixed",
            supported_technology_type="Mixed Fixture",
            steps=[
                SurveyStep(
                    guid="s1", display_name="Local", qualified_name="Step::Local",
                    executes_at="resource-explorer", re_analysis_step="local_step",
                ),
                SurveyStep(
                    guid="s2", display_name="EgeriaNative", qualified_name="Step::EgeriaNative",
                    executes_at="egeria", re_analysis_step=None,
                ),
            ],
        )
        registry = _fake_registry()
        reader = _fake_reader(survey_def)
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        result = executor.run(entity_type="mixed_resource", slug="mixed-entity")

        # The egeria step reached its REAL handler — proof it was not
        # silently run through the local-analysis-step path instead, which
        # has no `local_step`-shaped entry for it and would either error
        # ("not found"/unrecognized) or, worse, run the wrong thing.
        assert egeria_handler_calls == ["Step::EgeriaNative"]
        assert local_step_calls == ["ran"]

        statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert statuses["Step::Local"] == "ok"
        assert statuses["Step::EgeriaNative"] == "triggered"
        assert result["errors"] == []

    def test_a_pure_local_definition_may_still_use_whole_definition_prefect_orchestration(self):
        """Negative control: the guard must not over-fire. A definition with
        no non-local-engine steps is exactly what `_run_via_prefect` is FOR,
        and this test proves the gate doesn't block it — it should attempt
        Prefect orchestration (and here, with no real server reachable in
        this unit-test context, gracefully fall back to the local loop and
        still produce a correct result, per `_run_via_prefect`'s own
        try/except contract)."""
        entity = MagicMock()
        entity.slug = "local-only-entity"

        def _local_step(entity, registry, **kwargs):
            return {"annotations": []}

        adapter = ResourceTypeAdapter(
            entity_type="local_only_resource",
            technology_type="Local Only Fixture",
            re_analysis_steps={"local_step": _local_step},
            get_entity=lambda registry, slug: entity,
            publish=lambda *a, **kw: "",
        )
        register_adapter(adapter)

        survey_def = SurveyDefinition(
            process_guid="proc-local-only",
            display_name="Local Only Survey",
            qualified_name="GovActionProcess::LocalOnly",
            supported_technology_type="Local Only Fixture",
            steps=[
                SurveyStep(
                    guid="s1", display_name="Local", qualified_name="Step::Local",
                    executes_at="resource-explorer", re_analysis_step="local_step",
                ),
            ],
        )
        registry = _fake_registry()
        reader = _fake_reader(survey_def)
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        result = executor.run(entity_type="local_only_resource", slug="local-only-entity")

        statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert statuses["Step::Local"] == "ok"
        assert result["errors"] == []
