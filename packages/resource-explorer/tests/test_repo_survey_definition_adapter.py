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
        "repo_conventions", "repo_symbol_extraction", "repo_rag_ingestion",
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


def test_rag_ingestion_runs_last():
    """The mirror of the two ordering tests above. STEP_REGISTRY order is "Full
    Survey (all steps)" order, and repo_rag_ingestion is both the most expensive
    step in the set and the only one nothing downstream reads (pgvector is read
    by Chat and the query router, not by other steps) — so it must never delay
    the cheap signals a survey exists to produce."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

    assert list(STEP_REGISTRY)[-1] == "repo_rag_ingestion"


def test_rag_ingestion_declares_no_shared_resource():
    """Deliberate divergence from repo_file_inventory/repo_symbol_extraction:
    IncrementalIndexer downloads a zipball only when there are changed files, so
    declaring zipball_root would make the common no-op case pay for a download."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

    assert STEP_REGISTRY["repo_rag_ingestion"].requires_resources == {}


def test_file_inventory_declares_the_shared_zipball_resource():
    """Without requires_resources it gets no extraction root at all; with it,
    resolve_resources shares one download across every step that asks."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

    assert STEP_REGISTRY["repo_file_inventory"].requires_resources == {
        "zipball_root": "local_path"
    }


class TestStepCostTiers:
    """Step cost tiers plan (docs/step-cost-tiers-plan.md). Exhaustive on
    purpose, same rationale as test_all_step_keys_are_registered above — a
    new step must make a cost decision, not silently inherit the
    StepInfo default."""

    def test_every_step_declares_both_cost_fields(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

        for key, info in STEP_REGISTRY.items():
            assert info.fetch_cost in {"none", "api", "api_heavy", "download"}, key
            assert info.compute_cost in {"low", "medium", "high"}, key

    def test_fetch_cost_is_never_numeric(self):
        """D2/Hazards: the moment these are seconds, they're wrong for every
        repo but the one they were measured on — same rot as run_time."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

        for info in STEP_REGISTRY.values():
            assert not info.fetch_cost.isdigit()
            assert not info.compute_cost.isdigit()

    def test_d3_zipball_steps_never_declare_fetch_cost_none(self):
        """D3: fetch_cost must stay consistent with the structural
        requires_resources signal — a step that downloads a zipball cannot
        claim to fetch nothing."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

        for key, info in STEP_REGISTRY.items():
            if "zipball_root" in info.requires_resources:
                assert info.fetch_cost != "none", key

    def test_the_four_zipball_steps_are_exactly_these(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

        zipball_steps = {
            k for k, info in STEP_REGISTRY.items() if "zipball_root" in info.requires_resources
        }
        assert zipball_steps == {
            "repo_file_inventory", "repo_homepage", "repo_data_profiling", "repo_symbol_extraction",
        }

    def test_rag_ingestion_is_the_only_high_compute_cost_step(self):
        """D4: compute_cost="high" (embeds the repo) is explicitly called
        out for exactly this one step — a second "high" step should be a
        deliberate decision, not something this test lets slip by."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

        high_compute = {k for k, info in STEP_REGISTRY.items() if info.compute_cost == "high"}
        assert high_compute == {"repo_rag_ingestion"}

    def test_git_statistics_is_the_measured_api_heavy_baseline(self):
        """D4: the 430s-against-odpi/egeria measurement this whole plan is
        grounded in."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

        assert STEP_REGISTRY["repo_git_statistics"].fetch_cost == "api_heavy"
        assert STEP_REGISTRY["repo_git_statistics"].compute_cost == "low"


class TestStageCostConsistency:
    """The stage-assignment connection (docs/step-cost-tiers-plan.md) —
    a question tagged Scouting/Discovery (the two zero/near-zero-fetch
    funnel stages, CLAUDE.md rule 17) must not be answered by a
    survey-action analysis whose run_time is anything but "fast". Uses
    analysis_catalog.yaml's existing run_time, not the new per-step
    fetch_cost/compute_cost fields — deriving an analysis's cost from its
    steps' costs is explicitly out of scope for this plan (D1).

    action != "survey" entries are excluded: egeria_publish (action=
    "publish") is the one hit this check finds without the exclusion, and
    it's a catalog-of-record write, not an analysis — see the plan's note.
    With the exclusion applied, this passes cleanly today and exists to
    catch future drift (a Scouting/Discovery question acquiring an
    expensive answer), not to clean up a present violation.
    """

    _FAST_ONLY_STAGES = {"Scouting", "Discovery"}

    def _analyses_by_id(self):
        import yaml
        from pathlib import Path

        config_path = (
            Path(__file__).parent.parent / "resource_explorer" / "configdata" / "analysis_catalog.yaml"
        )
        raw = yaml.safe_load(config_path.read_text())
        analyses = {}
        for section in ("repo_analyses", "database_analyses", "filesystem_analyses"):
            for entry in raw.get(section) or []:
                analyses[entry["id"]] = entry
        return analyses

    def _questions(self):
        import yaml
        from pathlib import Path

        config_path = (
            Path(__file__).parent.parent / "resource_explorer" / "configdata" / "question_catalog.yaml"
        )
        raw = yaml.safe_load(config_path.read_text())
        return raw.get("repo_questions") or []

    def test_no_fast_stage_question_is_answered_by_a_non_fast_survey_analysis(self):
        analyses = self._analyses_by_id()
        violations = []
        for question in self._questions():
            stage = question["stage"]
            if stage not in self._FAST_ONLY_STAGES:
                continue
            for analysis_id in question["answering"].get("analysis_ids") or []:
                analysis = analyses.get(analysis_id)
                if analysis is None or analysis.get("action") != "survey":
                    continue
                if analysis.get("run_time") != "fast":
                    violations.append((question["question"], stage, analysis_id, analysis.get("run_time")))
        assert violations == []

    def test_egeria_publish_is_the_one_hit_the_action_exclusion_clears(self):
        """Confirms the action != "survey" exclusion is actually doing
        something, not vacuously passing because the data changed: without
        it, egeria_publish (linked from the "Analysis/Enrichment" governance
        question, run_time=minutes, action=publish) would be a real
        candidate hit if Analysis/Enrichment were ever added to
        _FAST_ONLY_STAGES — the plan's one known case from 2026-08-20."""
        analyses = self._analyses_by_id()
        assert analyses["egeria_publish"]["run_time"] == "minutes"
        assert analyses["egeria_publish"]["action"] == "publish"
        governance_question = next(
            q for q in self._questions() if "egeria_publish" in (q["answering"].get("analysis_ids") or [])
        )
        assert governance_question["stage"] == "Analysis/Enrichment"


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

def test_stage_survey_kinds_are_disjoint_where_they_should_be():
    """The automate_full bundle must not be offered as a scouting-tier survey.

    It surfaced on Scouting's Survey tab because the UI never passed the
    survey_kind filter the endpoint has always supported, so every stage listed
    every Survey Definition — and running the 20-step bundle from Scouting then
    deposited Assessment-tier results (security, documentation) that rendered as
    Scouting Results cards.
    """
    import csv
    from pathlib import Path

    csv_path = Path(__file__).resolve().parent.parent / "docs" / "dr-egeria" / "repo_survey_types.csv"
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    by_kind = {}
    for r in rows:
        by_kind.setdefault(r["survey_kind"], set()).add(r["survey_group"])

    assert "RepoFullSurvey" in by_kind["automate_full"]
    assert "RepoFullSurvey" not in by_kind.get("scouting", set())
    # the scouting-tier set, all three of them
    assert by_kind["scouting"] == {"RepoCoarseScout", "RepoCoarseProfile", "RepoScoutingSurvey"}
    # Every stage that has survey types of its own now filters to them, so the
    # automate_full bundle cannot reappear in any of them.
    for kind in ("assessment", "analysis", "discovery"):
        assert "RepoFullSurvey" not in by_kind.get(kind, set())


def test_assessment_and_analysis_surveys_are_self_sufficient():
    """Both prefix the prerequisite refresh steps. Every assessment- and
    analysis-tier step reads project_stats, and documentation/data_profiling/
    sub_resource_survey also read project_file_inventory — neither table is
    written by a step in those tiers, so without the prefix the run scores
    whatever an earlier, unrelated survey happened to leave behind. This is the
    same failure repo_git_statistics and repo_file_inventory were created to fix.
    """
    import csv
    from pathlib import Path

    csv_path = Path(__file__).resolve().parent.parent / "docs" / "dr-egeria" / "repo_survey_types.csv"
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    for group in ("RepoAssessmentSurvey", "RepoAnalysisSurvey"):
        steps = [r["step_key"] for r in rows if r["survey_group"] == group]
        assert steps, f"{group} has no steps"
        assert steps[0] == "repo_git_statistics", f"{group} must refresh stats first"
        assert steps[1] == "repo_file_inventory", f"{group} must refresh the inventory second"


def test_analysis_survey_carries_the_expensive_steps_and_assessment_does_not():
    """Assessment is cheap apart from its prerequisites; Analysis is deliberately
    the expensive tier. If that inverts, the cost tiers are telling us the
    membership is wrong."""
    import csv
    from pathlib import Path

    from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

    csv_path = Path(__file__).resolve().parent.parent / "docs" / "dr-egeria" / "repo_survey_types.csv"
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))

    def costs(group, skip_prereqs=True):
        steps = [r["step_key"] for r in rows if r["survey_group"] == group]
        if skip_prereqs:
            steps = steps[2:]
        return {s: STEP_REGISTRY[s].compute_cost for s in steps}

    assert set(costs("RepoAssessmentSurvey").values()) == {"low"}
    assert "high" in costs("RepoAnalysisSurvey").values()


def test_scouting_survey_covers_every_scouting_tier_step():
    """"Scouting Survey" is the run-everything-Scouting-does option: the union
    of Git Statistics Survey and Coarse Profile Survey, which stay available for
    the narrower cases."""
    import csv
    from pathlib import Path

    csv_path = Path(__file__).resolve().parent.parent / "docs" / "dr-egeria" / "repo_survey_types.csv"
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    steps = {g: [r["step_key"] for r in rows if r["survey_group"] == g]
             for g in ("RepoCoarseScout", "RepoCoarseProfile", "RepoScoutingSurvey")}
    union = set(steps["RepoCoarseScout"]) | set(steps["RepoCoarseProfile"])
    assert set(steps["RepoScoutingSurvey"]) == union, (
        f"missing {union - set(steps['RepoScoutingSurvey'])}, "
        f"extra {set(steps['RepoScoutingSurvey']) - union}"
    )
    # prerequisites first — same ordering rule as STEP_REGISTRY
    order = steps["RepoScoutingSurvey"]
    assert order.index("repo_git_statistics") < order.index("repo_health")
    assert order.index("repo_file_inventory") < order.index("repo_file_structure")
