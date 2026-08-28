"""A schedule can now target a Survey Definition, not only an analysis."""
from unittest.mock import patch

import pytest

from resource_explorer.registry import TARGET_ANALYSIS, TARGET_SURVEY, Project


def test_a_survey_can_be_scheduled(pg_registry):
    """The whole point: until 2026-08-28 a schedule could only name an
    analysis, so a Survey Definition could be authored, listed and run by hand
    but never put on a cadence."""
    reg = pg_registry
    reg.add(Project(slug="s", display_name="s", github_url="https://github.com/x/s"))
    reg.save_schedule("repo", "s", "GovActionProcess::RepoScoutingSurvey",
                      "daily", target_kind=TARGET_SURVEY)

    rows = reg.get_schedules("repo", "s")
    assert len(rows) == 1
    assert rows[0]["target_kind"] == TARGET_SURVEY
    assert rows[0]["analysis_id"] == "GovActionProcess::RepoScoutingSurvey"


def test_an_analysis_schedule_still_defaults_to_the_analysis_target(pg_registry):
    """Rows written before target_kind existed, and every caller that has not
    been updated, must keep meaning what they meant."""
    reg = pg_registry
    reg.add(Project(slug="a", display_name="a", github_url="https://github.com/x/a"))
    reg.save_schedule("repo", "a", "foss_scorecard", "weekly")
    assert reg.get_schedules("repo", "a")[0]["target_kind"] == TARGET_ANALYSIS


def test_the_two_namespaces_cannot_collide_on_the_primary_key(pg_registry):
    """Why the key did not need rebuilding: a survey reference always contains
    '::' and no analysis id does, so both can share the ref column."""
    reg = pg_registry
    reg.add(Project(slug="c", display_name="c", github_url="https://github.com/x/c"))
    reg.save_schedule("repo", "c", "foss_scorecard", "daily")
    reg.save_schedule("repo", "c", "GovActionProcess::RepoFullSurvey", "weekly",
                      target_kind=TARGET_SURVEY)
    kinds = {r["analysis_id"]: r["target_kind"] for r in reg.get_schedules("repo", "c")}
    assert kinds == {"foss_scorecard": TARGET_ANALYSIS,
                     "GovActionProcess::RepoFullSurvey": TARGET_SURVEY}


def test_an_unknown_target_kind_is_refused(pg_registry):
    reg = pg_registry
    reg.add(Project(slug="u", display_name="u", github_url="https://github.com/x/u"))
    with pytest.raises(ValueError) as exc:
        reg.save_schedule("repo", "u", "x", "daily", target_kind="whatever")
    assert "target_kind" in str(exc.value)


def test_a_survey_schedule_dispatches_to_the_survey_executor():
    """Analysis schedules keep their old path; survey schedules take the new
    one. Routing on target_kind rather than on the shape of the reference,
    because guessing from the string is how the two would drift."""
    from resource_explorer import scheduler

    with patch.object(scheduler, "run_survey_definition", create=True), \
         patch("resource_explorer.surveyors.survey_definition_executor.run_survey_definition",
               return_value={"errors": [], "run_recorded": True}) as run, \
         patch.object(scheduler, "_run_repo_survey") as legacy:
        reg = type("R", (), {"get": lambda self, s: type("P", (), {
            "display_name": s, "github_url": ""})()})()
        scheduler._execute("repo", "demo", "GovActionProcess::X", reg,
                           target_kind="survey")
    run.assert_called_once()
    legacy.assert_not_called()


def test_a_survey_that_ran_but_was_not_recorded_reports_an_error():
    """It ran; the schedules view is where someone looks to find out whether it
    did, so a bookkeeping miss must not read as a clean run."""
    from resource_explorer import scheduler

    with patch("resource_explorer.surveyors.survey_definition_executor.run_survey_definition",
               return_value={"errors": [], "run_recorded": False}):
        reg = type("R", (), {"get": lambda self, s: type("P", (), {
            "display_name": s, "github_url": ""})()})()
        _, _, errors = scheduler._execute("repo", "demo", "GovActionProcess::X",
                                          reg, target_kind="survey")
    assert errors and "could not be recorded" in errors[0]
