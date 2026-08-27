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
    # Two errors, not one — an executes_at="egeria" step with no registered
    # other_engine_handlers now counts as a real error too (2026-08-24,
    # "closing the stub"): it genuinely never executes anywhere, since RE's
    # own client-side walk is the only thing driving execution today. Used
    # to be silently swallowed (status "skipped_egeria", nothing in `errors`
    # at all) — a run with a step that never ran reported "complete."
    assert len(result["errors"]) == 2
    assert "totally_unknown_step" in result["errors"][0]
    assert "Step::Egeria" in result["errors"][1]
    statuses = {s["step"]: s["status"] for s in result["steps"]}
    assert statuses["Step::Known"] == "ok"
    assert statuses["Step::Unknown"] == "unknown_step"
    assert statuses["Step::Egeria"] == "not_executed_no_egeria_handler"
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


class TestRunBatch:
    """D1 (docs/survey-tab-unification-plan.md) — consecutive plain
    'resource-explorer' steps batch into one adapter.run_batch() call when
    the adapter provides one, instead of one call per step. Real fix, not a
    micro-optimization: per-step dispatch meant any step declaring a shared
    D6 resource (e.g. repo's zipball_root) re-acquired it independently
    every time."""

    def _survey_def(self, *step_keys, guid="proc-batch"):
        return SurveyDefinition(
            process_guid=guid,
            display_name="Batchable Survey",
            qualified_name="GovActionProcess::Batchable",
            supported_technology_type="Fake Tech",
            steps=[
                SurveyStep(
                    guid=f"s{i}", display_name=key, qualified_name=f"Step::{key}",
                    executes_at="resource-explorer", re_analysis_step=key,
                )
                for i, key in enumerate(step_keys)
            ],
        )

    def test_consecutive_steps_call_run_batch_once_not_per_step(self):
        run_batch = MagicMock(return_value={"annotations": ["a1", "a2"], "errors": []})
        per_step_runner = MagicMock()  # must NOT be called — proves batching, not per-step dispatch
        adapter = ResourceTypeAdapter(
            entity_type="batchable",
            technology_type="Fake Tech",
            re_analysis_steps={"step_a": per_step_runner, "step_b": per_step_runner},
            get_entity=lambda registry, slug: object(),
            publish=MagicMock(return_value="report-guid-batch"),
            run_batch=run_batch,
        )
        register_adapter(adapter)

        survey_def = self._survey_def("step_a", "step_b")
        registry = _fake_registry()
        reader = _fake_reader(survey_def, candidates=[{"guid": "proc-batch", "qualified_name": "GovActionProcess::Batchable", "display_name": "Batchable"}])
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        result = executor.run(entity_type="batchable", slug="my-repo")

        run_batch.assert_called_once()
        args, _ = run_batch.call_args
        assert args[2] == ["step_a", "step_b"]
        per_step_runner.assert_not_called()
        statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert statuses == {"Step::step_a": "ok", "Step::step_b": "ok"}
        assert result["errors"] == []
        adapter.publish.assert_called_once()

    def test_a_single_batchable_step_still_uses_the_per_step_path(self):
        """A group of exactly one falls through to the original per-step
        runner unchanged — batching only kicks in for 2+ consecutive steps,
        so single-step Survey Definitions (or single-step remainders) don't
        pay any behavior-change cost at all."""
        run_batch = MagicMock()
        per_step_runner = MagicMock(return_value={"annotations": ["a1"]})
        adapter = ResourceTypeAdapter(
            entity_type="batchable2",
            technology_type="Fake Tech",
            re_analysis_steps={"step_a": per_step_runner},
            get_entity=lambda registry, slug: object(),
            publish=MagicMock(return_value="report-guid"),
            run_batch=run_batch,
        )
        register_adapter(adapter)

        survey_def = self._survey_def("step_a", guid="proc-batch2")
        registry = _fake_registry()
        reader = _fake_reader(survey_def, candidates=[{"guid": "proc-batch2", "qualified_name": "GovActionProcess::Batchable", "display_name": "Batchable"}])
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        executor.run(entity_type="batchable2", slug="my-repo")

        run_batch.assert_not_called()
        per_step_runner.assert_called_once()

    def test_run_batch_errors_are_surfaced_and_shared_across_the_group(self):
        run_batch = MagicMock(return_value={"annotations": [], "errors": ["repo_health failed: rate limited"]})
        adapter = ResourceTypeAdapter(
            entity_type="batchable3",
            technology_type="Fake Tech",
            re_analysis_steps={"step_a": MagicMock(), "step_b": MagicMock()},
            get_entity=lambda registry, slug: object(),
            publish=MagicMock(),
            run_batch=run_batch,
        )
        register_adapter(adapter)

        survey_def = self._survey_def("step_a", "step_b", guid="proc-batch3")
        registry = _fake_registry()
        reader = _fake_reader(survey_def, candidates=[{"guid": "proc-batch3", "qualified_name": "GovActionProcess::Batchable", "display_name": "Batchable"}])
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        result = executor.run(entity_type="batchable3", slug="my-repo")

        assert "rate limited" in result["errors"][0]
        statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert statuses == {"Step::step_a": "error", "Step::step_b": "error"}

    def test_run_batch_exception_is_caught_not_raised(self):
        adapter = ResourceTypeAdapter(
            entity_type="batchable4",
            technology_type="Fake Tech",
            re_analysis_steps={"step_a": MagicMock(), "step_b": MagicMock()},
            get_entity=lambda registry, slug: object(),
            publish=MagicMock(),
            run_batch=MagicMock(side_effect=RuntimeError("zipball download failed")),
        )
        register_adapter(adapter)

        survey_def = self._survey_def("step_a", "step_b", guid="proc-batch4")
        registry = _fake_registry()
        reader = _fake_reader(survey_def, candidates=[{"guid": "proc-batch4", "qualified_name": "GovActionProcess::Batchable", "display_name": "Batchable"}])
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        result = executor.run(entity_type="batchable4", slug="my-repo")

        assert "zipball download failed" in result["errors"][0]
        statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert statuses == {"Step::step_a": "error", "Step::step_b": "error"}

    def test_an_unknown_step_key_breaks_the_group_but_doesnt_block_the_rest(self):
        """A step this adapter doesn't recognize must never be silently
        absorbed into a batch — it still gets reported as 'unknown_step',
        same as the non-batched path always did."""
        run_batch = MagicMock(return_value={"annotations": [], "errors": []})
        adapter = ResourceTypeAdapter(
            entity_type="batchable5",
            technology_type="Fake Tech",
            re_analysis_steps={"step_a": MagicMock(), "step_c": MagicMock()},
            get_entity=lambda registry, slug: object(),
            publish=MagicMock(return_value="report-guid"),
            run_batch=run_batch,
        )
        register_adapter(adapter)

        survey_def = self._survey_def("step_a", "step_unknown", "step_c", guid="proc-batch5")
        registry = _fake_registry()
        reader = _fake_reader(survey_def, candidates=[{"guid": "proc-batch5", "qualified_name": "GovActionProcess::Batchable", "display_name": "Batchable"}])
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        result = executor.run(entity_type="batchable5", slug="my-repo")

        statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert statuses["Step::step_unknown"] == "unknown_step"
        # step_a and step_c are each isolated singletons (the unknown step
        # breaks any run of 2+) — run_batch should never be called at all.
        run_batch.assert_not_called()

    def test_database_adapter_has_no_run_batch_default_none(self):
        """Every adapter registered before D1 existed must keep run_batch=None
        (the exact prior one-call-per-step behavior) unless explicitly opted in."""
        from resource_explorer.surveyors.survey_definition_executor import get_adapter
        import resource_explorer.surveyors.database.survey_definition_adapter  # noqa: F401
        assert get_adapter("database").run_batch is None


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


class TestPublishGatedOnAssignedEgeriaProject:
    """Confirmed live 2026-08-27: this used to publish unconditionally for any
    repo a Survey Definition ran against, decided-in-Egeria or not — the only
    other publish path (egeria.py's manual button) has always gated this."""

    def _run(self, registry, publish=None):
        adapter = ResourceTypeAdapter(
            entity_type="fake3",
            technology_type="Fake Tech",
            re_analysis_steps={"known_step": MagicMock(return_value={"annotations": ["a1"]})},
            get_entity=lambda registry, slug: object(),
            publish=publish or MagicMock(return_value="report-guid"),
        )
        register_adapter(adapter)
        survey_def = SurveyDefinition(
            process_guid="proc-3",
            display_name="Fake Survey 3",
            qualified_name="GovActionProcess::Fake3",
            supported_technology_type="Fake Tech",
            steps=[
                SurveyStep(
                    guid="s1", display_name="Known", qualified_name="Step::Known",
                    executes_at="resource-explorer", re_analysis_step="known_step",
                ),
            ],
        )
        reader = _fake_reader(survey_def, candidates=[
            {"guid": "proc-3", "qualified_name": "GovActionProcess::Fake3", "display_name": "Fake3"},
        ])
        executor = SurveyDefinitionExecutor(registry, reader=reader)
        result = executor.run(entity_type="fake3", slug="my-fake3")
        return result, adapter

    def test_unassigned_resource_skips_publish(self):
        registry = _fake_registry()
        registry.has_assigned_egeria_project.return_value = False
        result, adapter = self._run(registry)

        adapter.publish.assert_not_called()
        assert result["published"] is False
        assert result["egeria_report_guid"] == ""

    def test_assigned_resource_still_publishes(self):
        registry = _fake_registry()
        registry.has_assigned_egeria_project.return_value = True
        result, adapter = self._run(registry)

        adapter.publish.assert_called_once()
        assert result["published"] is True
        assert result["egeria_report_guid"] == "report-guid"

    def test_a_publish_failure_is_reported_as_an_error_not_raised(self):
        registry = _fake_registry()
        registry.has_assigned_egeria_project.return_value = True
        result, adapter = self._run(registry, publish=MagicMock(side_effect=RuntimeError("egeria down")))

        assert result["published"] is False
        assert any("egeria down" in e for e in result["errors"])
