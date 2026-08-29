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


class TestAnalysisAvailability:
    """availability is DERIVED from run_time, not hand-tagged -- see
    AnalysisCatalogEntry.availability and context-compilation-design.md §20."""

    def test_only_fast_is_inline(self):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

        for resource_type in ("repo", "database", "filesystem"):
            for a in get_analyses(resource_type):
                expected = "inline" if a["run_time"] == "fast" else "queued"
                assert a["availability"] == expected, (
                    f"{a['id']}: run_time={a['run_time']} -> {a['availability']}"
                )

    def test_unknown_run_time_is_queued_not_inline(self):
        """Guessing cheap is the dangerous direction: an unrecognised run_time
        must not let a packer block on a minutes-long analysis."""
        from resource_explorer.surveyors.analysis_catalog_reader import AnalysisCatalogEntry

        entry = AnalysisCatalogEntry(
            id="x", name="x", description="", resource_types=["repo"],
            intent="analysis", perspectives=[], annotation_types=[],
            source="local", run_time="something-new", action="survey",
            recommended=False,
        )
        assert entry.availability == "queued"


class TestKnownGaps:
    def test_gap_report_is_available(self, report):
        """Not an assertion about the gaps themselves -- they are expected to
        move as the catalog grows. This only guards that the report still
        computes, so `Privacy reaches zero analyses` stays discoverable
        instead of being rediscovered by hand every few months."""
        assert "questions_with_no_analysis" in report
        assert isinstance(report["axes"]["perspectives"]["tags_reaching_nothing"], list)


class TestFeedbackCarriesDerivation:
    """A rating must be traceable to *why* those sources were chosen, not only
    to which chunks came back. Without it a thumbs-down cannot distinguish
    "wrong questions selected" from "right questions, bad answer" -- different
    fixes. See docs/context-compilation-design.md §13.
    """

    def test_record_query_persists_derivation(self, tmp_path):
        import json as _json

        from resource_explorer.observability.metrics_collector import MetricsCollector

        mc = MetricsCollector(database_url=f"sqlite:///{tmp_path / 'm.db'}")
        deriv = {
            "matched_purposes": ["Certify"],
            "matched_perspectives": ["Security"],
            "analysis_ids": ["security_scan"],
        }
        mc.record_query(
            query="is this ready to adopt?", intent="assessment",
            resource_slug="amundsen", response="...", derivation=deriv,
        )
        with mc._conn() as conn:
            row = conn.execute(
                "SELECT derivation FROM query_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert _json.loads(row["derivation"]) == deriv

    def test_derivation_is_optional(self, tmp_path):
        """Free-text RAG queries have no catalog behind them; absence must be
        an empty object, never a crash or a NULL that reads as data."""
        from resource_explorer.observability.metrics_collector import MetricsCollector

        mc = MetricsCollector(database_url=f"sqlite:///{tmp_path / 'm.db'}")
        mc.record_query(query="anything", intent="analysis", resource_slug=None, response="x")
        with mc._conn() as conn:
            row = conn.execute(
                "SELECT derivation FROM query_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row["derivation"] == "{}"


class TestEveryAnsweringAnalysisCanProduceAFinding:
    """A question may only name an analysis capable of answering it.

    Two instances made this worth checking rather than fixing case by case.
    `egeria_publish` — an action that writes to Egeria and produces no findings
    — was named by "Does it fit into our governance frameworks?" and reached
    the context compiler, where it could only ever appear as a permanent gap
    asserting a result that will never exist. It got there from PROSE: the note
    says "plus Curate zone/catalog membership (egeria_publish)", and the
    generator matched any known id anywhere in the note, so an explanatory
    aside became a dispatch target.

    The generator now excludes `action: publish` ids, which fixes that class at
    source. This test is the ratchet: it fails on a hand-edited YAML, on a new
    write-only action nobody thought to exclude, and on an id that outlives the
    analysis it names — the same stale-reference shape as the GAP note that
    cited OSV.dev as a candidate tool beside a cve_scan already using it.

    The criterion is a results reader rather than mere catalog presence,
    because that is what the compiler actually needs to turn a section into
    evidence. An id in the catalog with no reader yields a gap indistinguishable
    from an analysis that has never run.
    """

    def _referenced(self) -> dict[str, list[str]]:
        from resource_explorer.surveyors.question_catalog_reader import get_questions

        refs: dict[str, list[str]] = {}
        for entry in get_questions("repo"):
            for analysis_id in (entry.get("derivation") or {}).get("analysis_ids") or []:
                refs.setdefault(analysis_id, []).append(entry["question"])
        return refs

    def test_every_referenced_analysis_exists_in_the_catalog(self):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

        known = {a["id"] for a in get_analyses("repo", include_egeria_live=False)}
        unknown = {a: qs for a, qs in self._referenced().items() if a not in known}
        assert not unknown, (
            f"question(s) name analyses that are not in the catalog: {unknown}. "
            f"Either the analysis was removed and the question still cites it, "
            f"or the id is a typo — both leave a question that can never be "
            f"answered while appearing to have an answer."
        )

    def test_no_question_names_a_write_only_action(self):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

        write_only = {a["id"] for a in get_analyses("repo", include_egeria_live=False)
                      if a.get("action") == "publish"}
        named = {a: qs for a, qs in self._referenced().items() if a in write_only}
        assert not named, (
            f"question(s) name a write-only action as their answer: {named}. "
            f"A publish writes to Egeria and produces no finding, so it can "
            f"only ever surface as a permanent gap. Reword the CSV note so the "
            f"id appears as prose rather than as a dispatch target, or drop it."
        )

    def test_every_referenced_analysis_has_a_results_reader(self):
        """Without one the compiler cannot turn the section into evidence, so
        the question is answerable on paper and not in fact."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_RESULTS_MAP,
        )

        missing = {a: qs for a, qs in self._referenced().items()
                   if a not in REPO_ANALYSIS_RESULTS_MAP}
        assert not missing, (
            f"question(s) name analyses with no results reader: {missing}. "
            f"REPO_ANALYSIS_RESULTS_MAP is what the context compiler reads; an "
            f"id absent from it yields a gap indistinguishable from an analysis "
            f"that never ran."
        )

    def test_the_check_has_something_to_check(self):
        """Guards the three assertions above against passing vacuously — an
        empty reference set would satisfy all of them."""
        refs = self._referenced()
        assert len(refs) >= 20, (
            f"only {len(refs)} analyses referenced by questions; the invariants "
            f"above pass trivially on an empty set, so this asserts the join "
            f"still produces something"
        )
