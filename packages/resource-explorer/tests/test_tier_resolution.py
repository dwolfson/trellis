"""Resolving a recorded run to its CURRENT funnel tier.

`activity_log.intent` is stamped at write time and never revisited, so it holds
what the catalog said that day. The catalog has been retagged twice (CLAUDE.md
rule 17). Measured 2026-09-10 over 1,217 rows: **174 of the 348 attributable
rows — 50% — carry an intent that disagrees with the catalog's current one**,
and reading the column finds **no `analysis` tier at all** while 11 analyses
declare it and it is in fact the largest tier by rows.

Same bug class as everything else here, in the data rather than the code: a true
statement about the mechanism read as a claim about the world.
"""
from __future__ import annotations

import pytest

from resource_explorer.tier_resolution import (
    TierAttribution, TierCoverage, clear_cache, current_tier_of_analysis,
    tier_of_activity_row)


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_cache()
    yield
    clear_cache()


def _survey(*step_keys, process="RepoCoarseProfile"):
    return {"steps": [{"step": f"GovActionProcessStep::{process}::{k}", "status": "ok"}
                      for k in step_keys]}


class TestTheTierComesFromTheCatalogNotTheRow:
    def test_a_recorded_intent_that_disagrees_loses_to_the_catalog(self):
        """`architecture_recovery` was retagged discovery -> analysis on
        2026-08-30; rows written before that still say `discovery`."""
        a = tier_of_activity_row("analysis_run",
                                 {"analysis_id": "architecture_recovery"},
                                 recorded_intent="discovery")
        assert a.resolved
        assert a.tiers == frozenset({"analysis"}), (
            "the resolver is echoing the row's stale intent instead of asking "
            "the catalog")
        assert a.recorded_tier == "discovery"
        assert a.drifted, "the disagreement is not being reported as drift"

    def test_agreement_is_not_drift(self):
        a = tier_of_activity_row("analysis_run",
                                 {"analysis_id": "architecture_recovery"},
                                 recorded_intent="analysis")
        assert a.resolved and not a.drifted

    def test_a_row_with_no_recorded_intent_still_resolves(self):
        a = tier_of_activity_row("analysis_run",
                                 {"analysis_id": "security_scan"})
        assert a.resolved and a.tiers
        assert not a.drifted, "an absent label cannot disagree with anything"


class TestWhatCannotBeResolvedSaysSo:
    def test_a_survey_with_no_steps_is_unattributable_not_untiered(self):
        """Predates step recording. Which analyses ran is unknowable — NOT
        none, and NOT whatever the row's intent happens to say."""
        a = tier_of_activity_row("survey", {}, recorded_intent="assessment")
        assert a.state == "unattributable"
        assert not a.tiers, (
            "an unattributable survey was given a tier anyway — almost "
            "certainly its stale recorded intent")
        assert not a.resolved

    def test_an_analysis_id_the_catalog_no_longer_has_is_unknown_not_absent(self):
        a = tier_of_activity_row("analysis_run",
                                 {"analysis_id": "an_analysis_that_was_removed"},
                                 recorded_intent="assessment")
        assert a.state == "unknown-analysis"
        assert not a.tiers and a.analyses == frozenset({"an_analysis_that_was_removed"})

    def test_an_analysis_run_with_no_id_is_unattributable(self):
        assert tier_of_activity_row("analysis_run", {}).state == "unattributable"

    def test_a_non_run_row_is_not_a_run(self):
        """A `catalog` or `scout` row is real activity but is not a tier's work
        being done to a resource, and counting it would inflate every tier."""
        for op in ("catalog", "scout", "rfa", "publish"):
            assert tier_of_activity_row(op, {"analysis_id": "security_scan"}).state \
                == "not-a-run", op

    def test_a_detail_that_is_not_a_dict_does_not_crash(self):
        for junk in (None, [], "steps", 7):
            assert tier_of_activity_row("survey", junk).state == "unattributable"


class TestSurveyRowsResolveThroughStepOWNERSHIP:
    def test_a_survey_step_resolves_to_its_owning_analysis_tier(self):
        a = tier_of_activity_row("survey", _survey("repo_arch_detect"))
        assert a.resolved
        assert a.analyses == frozenset({"architecture_recovery"})
        assert a.tiers == frozenset({"analysis"})

    def test_the_diagram_is_never_credited_for_the_recoverys_steps(self):
        """Ownership, not `REPO_ANALYSIS_SOURCE_STEPS`. The source map answers
        'what do I run', and using it here would re-create the exact
        mis-attribution fixed on 2026-09-08 — the picture taking credit for the
        work."""
        a = tier_of_activity_row("survey",
                                 _survey("repo_arch_detect", "repo_arch_coupling"))
        assert "architecture_diagram" not in a.analyses, (
            "a derived analysis is being credited for steps it does not own")
        assert a.analyses == frozenset({"architecture_recovery"})

    def test_a_survey_spanning_tiers_reports_all_of_them(self):
        """Collapsing a multi-tier survey to one tier would be a choice
        disguised as a reading."""
        a = tier_of_activity_row("survey", _survey("repo_arch_detect", "repo_security"))
        assert len(a.tiers) >= 2, f"expected more than one tier, got {a.tiers}"
        assert a.resolved

    def test_steps_the_map_does_not_know_do_not_invent_a_tier(self):
        a = tier_of_activity_row("survey", _survey("repo_not_a_real_step"))
        assert not a.tiers and a.state == "unknown-analysis"


class TestCoverageKeepsAnHonestDenominator:
    def test_unattributable_rows_stay_in_the_denominator(self):
        """Dropping them would inflate every percentage computed from this —
        the difference between 'no repo reached Analysis' and 'we cannot say
        for most of them'."""
        cov = TierCoverage()
        cov.add(tier_of_activity_row("analysis_run", {"analysis_id": "security_scan"}))
        cov.add(tier_of_activity_row("survey", {}))
        cov.add(tier_of_activity_row("catalog", {}))
        assert cov.attributed == 1 and cov.unattributable == 1 and cov.not_a_run == 1
        assert cov.considered == 2, (
            "not-a-run must be excluded and unattributable must be included")

    def test_a_multi_tier_row_counts_once_per_tier_but_not_as_drift(self):
        cov = TierCoverage()
        cov.add(tier_of_activity_row("survey",
                                     _survey("repo_arch_detect", "repo_security"),
                                     recorded_intent="assessment"))
        assert sum(cov.rows_by_tier.values()) >= 2
        assert cov.drifted == 0, (
            "a survey spanning several tiers has no single label to disagree "
            "with; counting it as drift measures the row's shape, not drift")

    def test_drift_is_counted_and_attributed(self):
        cov = TierCoverage()
        for _ in range(3):
            cov.add(tier_of_activity_row(
                "analysis_run", {"analysis_id": "architecture_recovery"},
                recorded_intent="discovery"))
        assert cov.drifted == 3
        assert cov.recorded_vs_current[("discovery", "analysis")] == 3


class TestAgainstTheRealCatalog:
    def test_the_catalog_declares_an_analysis_tier(self):
        """The whole point. Reading `activity_log.intent` finds zero `analysis`
        rows; the catalog declares 11 analyses in that tier, and resolved it is
        the largest tier by row count."""
        tiers = set(current_tier_of_analysis().values())
        assert "analysis" in tiers

    def test_the_specs_assumed_understanding_rung_has_no_analyses(self):
        """The funnel-cost spec ranks scouting/discovery/analysis/understanding
        and excludes assessment. `understanding` is a canonical intent per rule
        17 but NO analysis declares it, so it cannot be costed — while
        `assessment`, which the spec excludes, has the most analyses of any
        tier. Anyone using that rank order is measuring an invented ladder."""
        by_tier: dict[str, int] = {}
        for tier in current_tier_of_analysis().values():
            by_tier[tier] = by_tier.get(tier, 0) + 1
        assert "understanding" not in by_tier, (
            "an `understanding` analysis now exists — the spec's ladder may be "
            "measurable after all, and this test should be revisited")
        assert by_tier.get("assessment", 0) > 0, (
            "assessment has no analyses, so excluding it from the ladder would "
            "be harmless after all")

    def test_every_catalogued_analysis_resolves(self):
        """No analysis should be un-tierable — a missing intent means a row
        that can never be attributed."""
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
        ids = {a["id"] for a in get_analyses("repo", include_egeria_live=False)}
        resolved = current_tier_of_analysis()
        missing = sorted(i for i in ids if i not in resolved)
        assert not missing, f"these analyses declare no intent: {missing}"
