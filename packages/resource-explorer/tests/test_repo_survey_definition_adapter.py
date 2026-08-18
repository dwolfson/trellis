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


def test_all_seventeen_step_keys_are_registered():
    steps = _build_re_analysis_steps()
    assert set(steps.keys()) == {
        "repo_file_structure", "repo_file_size", "repo_language", "repo_health",
        "repo_dependency", "repo_documentation", "repo_security", "repo_api_structure",
        "repo_data_profiling", "repo_file_classification", "repo_sub_resource_survey",
        "repo_license_classification", "repo_security_features", "repo_ci_quality",
        "repo_maturity", "repo_conventions", "repo_symbol_extraction",
    }
