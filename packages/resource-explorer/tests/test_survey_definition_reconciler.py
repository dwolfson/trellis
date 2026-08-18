"""Tests for survey_definition_reconciler.py — pure diff logic, no live
Egeria needed. Regression-guards the exact live incident (2026-08-13):
duplicate NextProcessStep links from re-running non-idempotent Dr.Egeria
Link commands, plus one genuinely stale edge on Repo Full Survey."""
from __future__ import annotations

from resource_explorer.surveyors.survey_definition_reconciler import (
    compute_expected_edges,
    diff_links,
)


def _link(prev_qn, next_qn, link_guid="link-guid"):
    return {
        "previousProcessStep": {"uniqueName": prev_qn},
        "nextProcessStep": {"uniqueName": next_qn},
        "nextProcessStepLinkGUID": link_guid,
    }


class TestComputeExpectedEdges:
    def test_linear_chain(self):
        edges = compute_expected_edges("RepoCoarseScout", ["repo_health", "repo_language"])
        assert edges == {
            ("GovActionProcessStep::RepoCoarseScout::repo_health", "GovActionProcessStep::RepoCoarseScout::repo_language"),
        }

    def test_three_step_chain_has_two_edges(self):
        edges = compute_expected_edges("X", ["a", "b", "c"])
        assert edges == {
            ("GovActionProcessStep::X::a", "GovActionProcessStep::X::b"),
            ("GovActionProcessStep::X::b", "GovActionProcessStep::X::c"),
        }

    def test_single_step_has_no_edges(self):
        assert compute_expected_edges("X", ["only_step"]) == set()

    def test_empty_steps_has_no_edges(self):
        assert compute_expected_edges("X", []) == set()


class TestDiffLinks:
    def test_clean_chain_removes_nothing(self):
        expected = compute_expected_edges("X", ["a", "b", "c"])
        links = [
            _link("GovActionProcessStep::X::a", "GovActionProcessStep::X::b", "l1"),
            _link("GovActionProcessStep::X::b", "GovActionProcessStep::X::c", "l2"),
        ]
        result = diff_links(links, expected, "GovActionProcess::X")
        assert result.kept == 2
        assert result.to_remove == []
        assert result.error == ""

    def test_duplicate_edge_second_occurrence_removed(self):
        # Reproduces the live incident's simplest case: repo_health ->
        # repo_language linked twice by re-running Link Next Process Step.
        expected = compute_expected_edges("RepoCoarseScout", ["repo_health", "repo_language"])
        links = [
            _link("GovActionProcessStep::RepoCoarseScout::repo_health", "GovActionProcessStep::RepoCoarseScout::repo_language", "l1"),
            _link("GovActionProcessStep::RepoCoarseScout::repo_health", "GovActionProcessStep::RepoCoarseScout::repo_language", "l2"),
        ]
        result = diff_links(links, expected, "GovActionProcess::RepoCoarseScout")
        assert result.kept == 1
        assert result.removed_duplicate == 1
        assert result.removed_stale == 0
        assert [e.link_guid for e in result.to_remove] == ["l2"]
        assert result.to_remove[0].reason == "duplicate"

    def test_stale_edge_from_prior_chain_ordering_removed(self):
        # Reproduces Repo Full Survey's actual live bug: repo_ci_quality
        # used to link directly to repo_api_structure before
        # repo_maturity/repo_conventions were inserted between them.
        expected = compute_expected_edges("X", ["repo_ci_quality", "repo_maturity", "repo_conventions", "repo_api_structure"])
        links = [
            _link("GovActionProcessStep::X::repo_ci_quality", "GovActionProcessStep::X::repo_maturity", "l1"),
            _link("GovActionProcessStep::X::repo_maturity", "GovActionProcessStep::X::repo_conventions", "l2"),
            _link("GovActionProcessStep::X::repo_conventions", "GovActionProcessStep::X::repo_api_structure", "l3"),
            _link("GovActionProcessStep::X::repo_ci_quality", "GovActionProcessStep::X::repo_api_structure", "stale-l4"),
        ]
        result = diff_links(links, expected, "GovActionProcess::X")
        assert result.kept == 3
        assert result.removed_stale == 1
        assert result.removed_duplicate == 0
        assert result.to_remove[0].link_guid == "stale-l4"
        assert result.to_remove[0].reason == "stale"

    def test_duplicates_and_stale_together_full_survey_shape(self):
        # A step with 3 live copies of its real edge plus a stale edge to
        # a different step — exactly RepoFullSurvey's repo_ci_quality shape
        # before the manual fix.
        expected = compute_expected_edges("X", ["repo_ci_quality", "repo_maturity"])
        links = [
            _link("GovActionProcessStep::X::repo_ci_quality", "GovActionProcessStep::X::repo_maturity", "l1"),
            _link("GovActionProcessStep::X::repo_ci_quality", "GovActionProcessStep::X::repo_maturity", "l2-dup"),
            _link("GovActionProcessStep::X::repo_ci_quality", "GovActionProcessStep::X::repo_api_structure", "l3-stale"),
        ]
        result = diff_links(links, expected, "GovActionProcess::X")
        assert result.kept == 1
        assert result.removed_duplicate == 1
        assert result.removed_stale == 1
        assert result.removed_total == 2
        reasons = {(e.link_guid, e.reason) for e in result.to_remove}
        assert reasons == {("l2-dup", "duplicate"), ("l3-stale", "stale")}

    def test_no_links_and_no_expected_edges_is_clean(self):
        result = diff_links([], set(), "GovActionProcess::SingleStep")
        assert result.kept == 0
        assert result.to_remove == []

    def test_idempotent_on_already_reconciled_graph(self):
        # Running the reconciler twice on an already-clean graph must be a
        # true no-op both times.
        expected = compute_expected_edges("X", ["a", "b"])
        links = [_link("GovActionProcessStep::X::a", "GovActionProcessStep::X::b", "l1")]
        first = diff_links(links, expected, "GovActionProcess::X")
        second = diff_links(links, expected, "GovActionProcess::X")
        assert first.to_remove == second.to_remove == []
        assert first.kept == second.kept == 1
