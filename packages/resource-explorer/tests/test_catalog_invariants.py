"""Invariants over the real question/analysis catalogs.

These guard the *curated vocabulary* rather than any code path. The tagging
in docs/dr-egeria/resource_questions.csv is hand-authored intellectual work;
the dispatch decisions in docs/investigation-framing-design.md §3 rest on
measured properties of that tagging, and nothing currently notices if a
retag invalidates them. A future edit that breaks one of these should fail
here rather than silently change what RE runs by default.

See docs/context-compilation-design.md §14 (nesting invariant) and §18
(protect the vocabulary, not the schema).
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors.question_catalog_reader import get_questions

pytest.importorskip("yaml")

# Recomputed from the shipped catalogs; the coverage script
# (scripts/question_catalog_coverage.py) prints the same numbers.
from scripts.question_catalog_coverage import build_report  # noqa: E402


@pytest.fixture(scope="module")
def report() -> dict:
    return build_report("repo")


class TestPerspectiveNesting:
    def test_no_perspective_has_unique_reach(self, report):
        """The nesting invariant.

        Measured 2026-08-24: not one of the twelve Perspectives reaches an
        analysis another Perspective does not also reach. The sets are
        strictly nested, so Perspective varies the SIZE of a result and never
        its CONTENT.

        Two decisions rest on this. Perspective ranks rather than filters
        dispatch (investigation-framing-design.md §3), and in the context
        compiler it weights the budget rather than gating sections, which is
        only safe *because* nothing is reachable through it alone
        (context-compilation-design.md §3).

        If this fails, Perspective has become discriminating. That is not
        necessarily bad — but both decisions above need revisiting before the
        tagging change lands, and Perspective would become identity-bearing
        for cache purposes.
        """
        unique = report["axes"]["perspectives"]["tags_with_unique_reach"]
        assert unique == [], (
            f"Perspective(s) {unique} now reach analyses no other Perspective "
            "reaches. The nesting invariant is broken -- see this test's "
            "docstring before updating it."
        )

    def test_purpose_discriminates_more_than_perspective(self, report):
        """Purpose is the primary dispatch axis *because* it discriminates
        better, not by preference. Measured 0.22 vs 0.37 mean pairwise
        overlap. The ordering is the claim; the exact values are allowed to
        drift with legitimate retagging."""
        purpose = report["axes"]["purposes"]["mean_pairwise_overlap"]
        perspective = report["axes"]["perspectives"]["mean_pairwise_overlap"]
        assert purpose < perspective, (
            f"Purpose overlap ({purpose}) is no longer below Perspective's "
            f"({perspective}). Purpose was made the primary dispatch axis on "
            "the strength of that gap."
        )


class TestPurposeRanksWithoutExcluding:
    def test_ranking_never_drops_a_question(self):
        """Purpose ORDERS, it does not exclude. Filtering on Purpose would be
        a bug -- nothing is hidden by it (investigation-framing-design.md §3).
        """
        everything = get_questions("repo")
        ranked = get_questions("repo", purposes=["Certify"])
        assert len(ranked) == len(everything)
        assert {q["question"] for q in ranked} == {q["question"] for q in everything}

    def test_matching_purposes_sort_first(self):
        ranked = get_questions("repo", purposes=["Certify"])
        flags = [q["derivation"]["purpose_ranked"] for q in ranked]
        assert any(flags), "no question serves Certify -- catalog changed?"
        # every promoted entry precedes every unpromoted one
        assert flags == sorted(flags, key=lambda matched: not matched)

    def test_unknown_purpose_is_inert(self):
        """An unrecognised Purpose ranks nothing rather than emptying the
        list -- the failure mode of a filter, which this is not."""
        ranked = get_questions("repo", purposes=["NoSuchPurpose"])
        assert len(ranked) == len(get_questions("repo"))
        assert not any(q["derivation"]["purpose_ranked"] for q in ranked)


class TestDerivationTrace:
    def test_every_entry_carries_a_derivation(self):
        for q in get_questions("repo"):
            assert "derivation" in q
            assert set(q["derivation"]) >= {
                "matched_perspectives", "matched_purposes",
                "purpose_ranked", "analysis_ids",
            }

    def test_derivation_records_what_matched(self):
        ranked = get_questions("repo", perspectives=["Security"], purposes=["Certify"])
        assert ranked, "Security/Certify reaches no questions -- catalog changed?"
        for q in ranked:
            # perspectives filter, so every entry must record its match
            assert q["derivation"]["matched_perspectives"], q["question"]
            assert all(
                p.lower() == "security" for p in q["derivation"]["matched_perspectives"]
            )

    def test_derivation_analysis_ids_match_answering(self):
        for q in get_questions("repo"):
            assert q["derivation"]["analysis_ids"] == q["answering"]["analysis_ids"]


class TestKnownGaps:
    def test_gap_report_is_available(self, report):
        """Not an assertion about the gaps themselves -- they are expected to
        move as the catalog grows. This only guards that the report still
        computes, so `Privacy reaches zero analyses` stays discoverable
        instead of being rediscovered by hand every few months."""
        assert "questions_with_no_analysis" in report
        assert isinstance(report["axes"]["perspectives"]["tags_reaching_nothing"], list)
