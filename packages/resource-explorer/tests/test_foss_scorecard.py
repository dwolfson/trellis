"""A scorecard that says what it could not check.

OpenSSF Scorecard awards a low score to a check it could not evaluate, so
"this project has no branch protection" and "we could not see whether it has
branch protection" both land as a bad number and the aggregate silently mixes
them. This one excludes unevaluable checks from the score and reports the
coverage, which is the whole reason it exists rather than shelling out to the
real tool.
"""
from __future__ import annotations

from resource_explorer.surveyors.sub_surveyors.foss_scorecard import (
    CHECKS,
    FAIL,
    PARTIAL,
    PASS,
    UNKNOWN,
    _c_contributors,
    _c_license,
    _c_maintained,
    _c_sast,
    score,
)


def _row(check_id, label):
    return {"check_name": check_id, "label": label, "summary": "", "confidence": 100}


class TestScoring:
    def test_unknown_checks_are_excluded_not_zeroed(self):
        """The single most important behaviour. Zeroing an unevaluable check
        makes a project we could not inspect look like one we inspected and
        found wanting."""
        results = [_row("a", PASS), _row("b", UNKNOWN), _row("c", UNKNOWN)]
        agg = score(results)
        assert agg["score"] == 10.0, "unknowns dragged the score down"
        assert agg["checks_evaluated"] == 1
        assert agg["checks_unknown"] == 2

    def test_coverage_travels_with_the_score(self):
        """8.0 over five checks and 8.0 over twelve are different claims, and a
        number without its coverage cannot be told apart from either."""
        agg = score([_row("a", PASS), _row("b", FAIL)])
        assert {"score", "checks_evaluated", "checks_total", "checks_unknown"} <= set(agg)
        assert agg["checks_total"] == 2

    def test_a_wholly_unevaluable_resource_scores_nothing_not_zero(self):
        """Zero would say "we checked and it failed everything"."""
        agg = score([_row("a", UNKNOWN), _row("b", UNKNOWN)])
        assert agg["score"] is None
        assert agg["checks_evaluated"] == 0

    def test_it_does_not_claim_to_be_an_openssf_score(self):
        """Excluding unknowns makes the number incomparable with a published
        one. Saying so in the payload stops it being quoted as if it were."""
        assert score([_row("a", PASS)])["comparable_to_openssf"] is False


class TestChecks:
    def test_an_unidentified_licence_is_partial_not_a_pass(self):
        """GitHub returns "Other"/"NOASSERTION" when it found a licence file it
        could not identify. That is not a usable licence declaration, and for a
        FOSS scorecard treating it as one is the dangerous direction."""
        assert _c_license({"license_spdx_id": "Apache-2.0"}, {}, [])[0] == PASS
        assert _c_license({"license": "Other", "license_spdx_id": "NOASSERTION"}, {}, [])[0] == PARTIAL
        assert _c_license({}, {}, [])[0] == FAIL

    def test_an_archived_repo_fails_maintenance_whatever_its_history(self):
        assert _c_maintained({"archived": 1, "commits_90d": 5000}, {}, [])[0] == FAIL

    def test_a_single_maintainer_is_a_finding_not_an_unknown(self):
        """We measured it. The number IS the concern -- reporting it as unknown
        would hide a real bus-factor risk behind a shrug."""
        assert _c_contributors({"contributors_count": 1}, {}, [])[0] == FAIL
        assert _c_contributors({"contributors_count": 6}, {}, [])[0] == PARTIAL
        assert _c_contributors({"contributors_count": 63}, {}, [])[0] == PASS

    def test_uncollected_data_is_unknown_not_a_failure(self):
        """No contributor count means nobody counted, not that there are none."""
        assert _c_contributors({}, {}, [])[0] == UNKNOWN

    def test_empty_security_settings_are_unknown_not_disabled(self):
        """An empty security_and_analysis payload means GitHub told us nothing
        -- often a token-scope limit. Reading it as "nothing is enabled" would
        invent a finding out of a permissions gap."""
        assert _c_sast({"security_and_analysis_json": "{}"}, {}, [])[0] == UNKNOWN
        assert _c_sast({}, {}, [])[0] == UNKNOWN
        enabled = '{"secret_scanning": {"status": "enabled"}}'
        assert _c_sast({"security_and_analysis_json": enabled}, {}, [])[0] == PASS
        disabled = '{"secret_scanning": {"status": "disabled"}}'
        assert _c_sast({"security_and_analysis_json": disabled}, {}, [])[0] == FAIL

    def test_a_check_depending_on_another_analysis_says_so(self):
        """"CI runs no tests" and "the CI analysis never ran" are opposite
        answers, and the second must name what would settle it."""
        from resource_explorer.surveyors.sub_surveyors.foss_scorecard import _c_ci_tests

        state, detail = _c_ci_tests({}, {}, [])
        assert state == UNKNOWN and "has not run" in detail

    def test_every_unknown_check_says_what_it_needs(self):
        """An unknown that cannot be acted on is merely honest; one that names
        its blocker is useful."""
        stateless = {c.id for c in CHECKS
                     if c.evaluate({}, {}, [])[0] == UNKNOWN and not c.needs}
        # Checks whose unknown is explained in their detail string rather than
        # `needs` are allowed, but every one that is structurally unevaluable
        # must declare it.
        assert "branch_protection" not in stateless
        assert "code_review" not in stateless
        assert "signed_releases" not in stateless


class TestRegistration:
    def test_the_analysis_is_wired_end_to_end(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            ANALYSIS_KINDS,
            REPO_ANALYSIS_RESULTS_MAP,
            REPO_ANALYSIS_STEP_MAP,
            STEP_REGISTRY,
        )

        assert "repo_foss_scorecard" in STEP_REGISTRY
        assert ANALYSIS_KINDS["foss_scorecard"].step_keys == ["repo_foss_scorecard"]
        assert REPO_ANALYSIS_STEP_MAP["foss_scorecard"] == ["repo_foss_scorecard"]
        assert "foss_scorecard" in REPO_ANALYSIS_RESULTS_MAP

    def test_it_is_in_the_catalog_with_real_perspectives(self):
        from resource_explorer.surveyors.analysis_catalog_reader import (
            EGERIA_PERSPECTIVES,
            get_analyses,
        )

        entry = next(a for a in get_analyses("repo", include_egeria_live=False)
                     if a["id"] == "foss_scorecard")
        assert entry["intent"] == "assessment"
        assert entry["perspectives"], "an untagged analysis cannot be filtered"
        for p in entry["perspectives"]:
            assert p == "all" or p in EGERIA_PERSPECTIVES


# ── supply-chain and path-derived checks (2026-08-26 extension) ─────────────
from resource_explorer.surveyors.sub_surveyors import foss_scorecard as FS


def test_supply_chain_checks_are_unknown_until_the_parser_has_run():
    """Never a failure. "We have not parsed the workflows" and "the workflows
    are unsafe" are opposite claims, and the second is an accusation."""
    for fn in (FS._c_token_permissions, FS._c_pinned_dependencies,
               FS._c_dangerous_workflow):
        state, detail = fn({}, {}, [])
        assert state == FS.UNKNOWN
        assert "refresh" in detail.lower()


def test_supply_chain_labels_map_onto_the_scorecard_vocabulary():
    findings = {"supply_chain": [
        {"check_name": "supply_chain_token_permissions", "label": "partial",
         "summary": "2 of 3 workflows."},
        {"check_name": "supply_chain_dangerous_workflow", "label": "fail",
         "summary": "1 job checks out untrusted code."},
        {"check_name": "supply_chain_pinned_dependencies", "label": "not_established",
         "summary": "no workflows parsed"},
    ]}
    assert FS._c_token_permissions({}, findings, [])[0] == FS.PARTIAL
    assert FS._c_dangerous_workflow({}, findings, [])[0] == FS.FAIL
    # The parser's own absence state must not become a zero-scoring failure.
    assert FS._c_pinned_dependencies({}, findings, [])[0] == FS.UNKNOWN


def test_a_supply_chain_run_that_omits_a_check_is_unknown_not_absent():
    findings = {"supply_chain": [{"check_name": "supply_chain_token_permissions",
                                  "label": "pass", "summary": ""}]}
    state, detail = FS._c_dangerous_workflow({}, findings, [])
    assert state == FS.UNKNOWN
    assert "did not report" in detail


def test_no_file_inventory_is_unknown_while_an_empty_one_is_a_real_answer():
    """The distinction the whole fact layer exists for: never-looked versus
    looked-and-found-nothing. Passing [] would make the first read as the second."""
    assert FS._c_sbom({}, {}, None)[0] == FS.UNKNOWN
    assert FS._c_dependency_update_tool({}, {}, None)[0] == FS.UNKNOWN
    assert FS._c_sbom({}, {}, ["README.md"])[0] == FS.FAIL


def test_sbom_detection_matches_real_spdx_and_cyclonedx_layouts():
    """Paths taken from deep_causality, which really does commit per-crate
    SPDX documents — the only repo of 49k catalogued paths that does."""
    paths = ["ultragraph/sbom.spdx", "deep_causality_num/deep_causality_num_sbom.spdx.json",
             "src/main.rs"]
    state, detail = FS._c_sbom({}, {}, paths)
    assert state == FS.PASS and "2 SBOM" in detail
    assert FS._c_sbom({}, {}, ["docs/bombardier.md", "src/bomb.py"])[0] == FS.FAIL


def test_dependency_update_tool_reads_the_bot_config_by_name():
    assert FS._c_dependency_update_tool({}, {}, [".github/dependabot.yml"])[0] == FS.PASS
    assert FS._c_dependency_update_tool({}, {}, ["renovate.json"])[0] == FS.PASS
    assert FS._c_dependency_update_tool({}, {}, ["package.json"])[0] == FS.FAIL


def test_unknown_checks_still_never_reach_the_score():
    """The extension quadrupled the number of checks that can be unknown, so
    the exclusion this whole module is built on is re-asserted here."""
    results = [{"label": FS.PASS}, {"label": FS.UNKNOWN}, {"label": FS.UNKNOWN}]
    agg = FS.score(results)
    assert agg["score"] == 10.0
    assert agg["checks_evaluated"] == 1 and agg["checks_unknown"] == 2
