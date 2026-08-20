"""Regression coverage for repo_survey_definition_adapter.py's re_analysis_steps
runners after the refactor to delegate to SurveyOrchestrator.run(steps=[...])
instead of each maintaining its own surveyor closure. Public contract must be
unchanged: runner(project, registry, **_) -> {"annotations": [...]}.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from resource_explorer.registry import Project
from resource_explorer.surveyors.repo_survey_definition_adapter import _build_re_analysis_steps


def _project():
    return Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
        description="",
    )


def test_each_step_key_delegates_to_orchestrator_with_itself_as_the_only_step():
    steps = _build_re_analysis_steps()
    project = _project()
    registry = MagicMock()

    for key, runner in steps.items():
        fake_result = MagicMock(annotations=[f"ann-for-{key}"])
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            output = runner(project, registry)

        # fast=False is the runner's own default when its caller (e.g. the
        # Survey Definition executor) doesn't pass one — forwarded
        # unconditionally to SurveyOrchestrator.run(), which itself only
        # actually applies it to steps whose StepInfo.accepts_fast is True.
        MockOrch.return_value.run.assert_called_once_with(project.slug, steps=[key], fast=False)
        assert output == {"annotations": [f"ann-for-{key}"]}


def test_all_step_keys_are_registered():
    """Exhaustive on purpose: adding a step without a runner would otherwise
    surface only as a Survey Definition that silently does less than its
    definition says. Deliberately not named for a count — it was
    "seventeen" until repo_file_inventory made it eighteen."""
    steps = _build_re_analysis_steps()
    assert set(steps.keys()) == {
        "repo_git_statistics", "repo_file_inventory", "repo_file_structure", "repo_file_size", "repo_language",
        "repo_health", "repo_homepage", "repo_dependency", "repo_documentation", "repo_security",
        "repo_api_structure", "repo_data_profiling", "repo_file_classification",
        "repo_sub_resource_survey", "repo_license_classification",
        "repo_security_features", "repo_ci_quality", "repo_maturity",
        "repo_conventions", "repo_symbol_extraction",
    }


def test_file_inventory_runs_before_every_step_that_reads_the_inventory():
    """Ordering is correctness here, not neatness. STEP_REGISTRY order is also
    the order "Repo Full Survey" runs (the "*" sentinel in
    repo_survey_types.csv), so a refresh placed after its consumers would leave
    them reporting the previous extraction while the run looks like a fresh
    profile."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

    order = list(STEP_REGISTRY)
    readers = [
        "repo_file_structure", "repo_language", "repo_file_classification",
        "repo_file_size", "repo_documentation", "repo_sub_resource_survey",
    ]
    idx = order.index("repo_file_inventory")
    for r in readers:
        assert idx < order.index(r), f"repo_file_inventory must precede {r}"


def test_file_inventory_declares_the_shared_zipball_resource():
    """Without requires_resources it gets no extraction root at all; with it,
    resolve_resources shares one download across every step that asks."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

    assert STEP_REGISTRY["repo_file_inventory"].requires_resources == {
        "zipball_root": "local_path"
    }


class TestRunBatch:
    """D1 (docs/survey-tab-unification-plan.md) — repo's own
    ResourceTypeAdapter.run_batch: one SurveyOrchestrator.run(steps=[...])
    call for a whole step_key list, so the executor's grouping (see
    test_survey_definition_executor.py::TestRunBatch) actually gets the
    single-zipball-download win it exists for."""

    def test_calls_orchestrator_once_with_all_step_keys(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import _run_batch

        project = _project()
        registry = MagicMock()
        fake_result = MagicMock(annotations=["a1", "a2"], errors=[])
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            output = _run_batch(project, registry, ["repo_language", "repo_file_classification"])

        MockOrch.return_value.run.assert_called_once_with(
            project.slug, steps=["repo_language", "repo_file_classification"], fast=False,
        )
        assert output == {"annotations": ["a1", "a2"], "errors": []}

    def test_forwards_fast_flag(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import _run_batch

        project = _project()
        registry = MagicMock()
        fake_result = MagicMock(annotations=[], errors=[])
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            _run_batch(project, registry, ["repo_health", "repo_language"], fast=True)

        _, kwargs = MockOrch.return_value.run.call_args
        assert kwargs["fast"] is True

    def test_surfaces_orchestrator_errors(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import _run_batch

        project = _project()
        registry = MagicMock()
        fake_result = MagicMock(annotations=[], errors=["repo_data_profiling raised unexpectedly: boom"])
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch:
            MockOrch.return_value.run.return_value = fake_result
            output = _run_batch(project, registry, ["repo_language", "repo_data_profiling"])

        assert output["errors"] == ["repo_data_profiling raised unexpectedly: boom"]

    def test_registered_on_the_real_adapter(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import _ADAPTER, _run_batch
        assert _ADAPTER.run_batch is _run_batch
