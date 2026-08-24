"""Cost-tier scheduling: same-repo due analyses share one resource acquisition.

Shared resources are deduplicated *within* a SurveyOrchestrator.run() call, but
the scheduler ran each due analysis in its own call — so a repo with two
download-tier analyses scheduled daily fetched the same zipball twice a day.
Four of sixteen repo analyses are download-tier, and schedules are picked from a
small set of intervals, so they land on the same tick: the common case, not a
rare one.

The download-count test is the load-bearing one here. Everything else could pass
while the saving itself failed to materialise.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resource_explorer import scheduler
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="myproj", display_name="My Proj",
                    github_url="https://github.com/o/myproj", description=""))
    return reg


def _due(*analysis_ids):
    return [{"entity_type": "repo", "entity_slug": "myproj", "analysis_id": a,
             "next_run": "2020-01-01T00:00:00"} for a in analysis_ids]


class TestCoalescing:

    def test_two_due_analyses_for_one_repo_run_as_a_single_call(self, registry):
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch:
            Orch.return_value.run.return_value = MagicMock(step_errors={})
            out = scheduler._coalesce_repo_surveys(
                _due("code_symbol_extraction", "data_file_profiling"), registry)

        assert Orch.return_value.run.call_count == 1
        assert set(out) == {("myproj", "code_symbol_extraction"),
                            ("myproj", "data_file_profiling")}

    def test_steps_run_in_registry_order_not_schedule_order(self, registry):
        """run(steps=[...]) executes in the caller's given order, and the
        registry order encodes real prerequisites — repo_file_inventory must
        precede everything that reads the inventory, or the batch reports
        against the previous extraction while looking freshly profiled."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch:
            Orch.return_value.run.return_value = MagicMock(step_errors={})
            # Deliberately listed with the later-registry analysis first.
            scheduler._coalesce_repo_surveys(
                _due("sub_resource_survey", "data_file_profiling"), registry)

        steps = Orch.return_value.run.call_args.kwargs["steps"]
        order = list(STEP_REGISTRY)
        assert steps == sorted(steps, key=order.index)

    def test_a_single_due_analysis_is_left_on_the_existing_path(self, registry):
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch:
            out = scheduler._coalesce_repo_surveys(_due("data_file_profiling"), registry)

        assert out == {}
        Orch.return_value.run.assert_not_called()

    def test_one_failing_step_fails_only_the_analyses_containing_it(self, registry):
        """Without per-step attribution the batch would mark every analysis in
        it failed because one step raised — turning one real failure into
        several false ones, each with its own error activity entry."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_STEP_MAP)

        broken = REPO_ANALYSIS_STEP_MAP["data_file_profiling"][0]
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch:
            Orch.return_value.run.return_value = MagicMock(
                step_errors={broken: "DataProfiling raised unexpectedly: boom"})
            out = scheduler._coalesce_repo_surveys(
                _due("code_symbol_extraction", "data_file_profiling"), registry)

        assert out[("myproj", "data_file_profiling")] == [
            "DataProfiling raised unexpectedly: boom"]
        assert out[("myproj", "code_symbol_extraction")] == []


class TestExclusions:
    """Analyses whose dispatch does something other than run orchestrator steps
    must never be swept into a batch — they would silently not run at all."""

    def test_rag_ingestion_is_never_batched(self, registry):
        out = scheduler._coalesce_repo_surveys(
            _due("rag_ingestion", "data_file_profiling", "code_symbol_extraction"), registry)
        assert ("myproj", "rag_ingestion") not in out

    def test_publish_is_never_batched(self, registry):
        out = scheduler._coalesce_repo_surveys(
            _due("egeria_publish", "data_file_profiling", "code_symbol_extraction"), registry)
        assert ("myproj", "egeria_publish") not in out

    def test_website_ingestion_is_batched_despite_its_ingest_action(self, registry):
        """It carries action:"ingest" for the UI but is an ordinary
        SurveyOrchestrator step, unlike rag_ingestion. This is the distinction
        that made action a wrong dispatch key."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_STEP_MAP)

        assert REPO_ANALYSIS_STEP_MAP["website_ingestion"] == ["repo_website_ingestion"]
        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch:
            Orch.return_value.run.return_value = MagicMock(step_errors={})
            out = scheduler._coalesce_repo_surveys(
                _due("website_ingestion", "data_file_profiling"), registry)
        assert ("myproj", "website_ingestion") in out


class TestTheActualSaving:

    def test_both_analyses_steps_go_into_one_run(self, registry):
        """The saving itself: two download-tier analyses produce one run() call
        carrying both their steps. The deduplication that turns that into one
        zipball download is SurveyOrchestrator's own — it resolves each needed
        resource once per run() call regardless of how many selected steps ask
        for it — so what has to be true here is that there is one call, and that
        it carries every step both analyses needed."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_STEP_MAP, STEP_REGISTRY)

        wanted = set(REPO_ANALYSIS_STEP_MAP["code_symbol_extraction"]) | set(
            REPO_ANALYSIS_STEP_MAP["data_file_profiling"])
        # Precondition for the test to mean anything: both really do download.
        assert all(STEP_REGISTRY[k].fetch_cost == "download" for k in wanted)

        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as Orch:
            Orch.return_value.run.return_value = MagicMock(step_errors={})
            scheduler._coalesce_repo_surveys(
                _due("code_symbol_extraction", "data_file_profiling"), registry)

        assert Orch.return_value.run.call_count == 1
        assert set(Orch.return_value.run.call_args.kwargs["steps"]) == wanted


class TestCadenceGuidance:
    """"Cheap often, expensive rarely" — expressed in the cadence vocabulary
    the scheduler actually has, not in hours it cannot represent."""

    def test_zero_fetch_analyses_are_fine_daily(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            recommended_schedule)

        assert recommended_schedule("security_scan") == "daily"
        assert recommended_schedule("dependency_analysis") == "daily"

    def test_download_tier_backs_off_to_weekly(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            recommended_schedule)

        assert recommended_schedule("data_file_profiling") == "weekly"
        assert recommended_schedule("website_ingestion") == "weekly"

    def test_download_plus_high_compute_backs_off_furthest(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            recommended_schedule)

        assert recommended_schedule("rag_ingestion") == "monthly"

    def test_manual_is_never_too_frequent(self):
        """It does not recur at all, so no cost argument applies to it."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            schedule_is_more_frequent_than_recommended)

        assert not schedule_is_more_frequent_than_recommended("rag_ingestion", "manual")

    def test_daily_on_a_weekly_analysis_is_flagged(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            schedule_is_more_frequent_than_recommended)

        assert schedule_is_more_frequent_than_recommended("data_file_profiling", "daily")
        assert not schedule_is_more_frequent_than_recommended("data_file_profiling", "weekly")
        assert not schedule_is_more_frequent_than_recommended("security_scan", "daily")

    def test_analysis_cost_is_the_max_over_steps_not_the_first(self):
        """language_file_classification maps to three steps; its cost is the
        most expensive of them, since that is what governs whether the whole
        thing is safe to run often."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_STEP_MAP, STEP_REGISTRY, FETCH_COST_ORDER, analysis_cost)

        for aid, steps in REPO_ANALYSIS_STEP_MAP.items():
            if not steps:
                continue
            worst = max((STEP_REGISTRY[k].fetch_cost for k in steps if k in STEP_REGISTRY),
                        key=FETCH_COST_ORDER.index)
            assert analysis_cost(aid)[0] == worst
