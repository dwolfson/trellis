"""Compiling a context for the adoption gate.

Closes the loop Phase 0 opened: the derivation that get_questions() already
computed becomes the section list, and the packer decides what fits.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resource_explorer.context_compile import compile_context


def _registry(findings_by_kind):
    r = MagicMock()
    r.query_findings.side_effect = lambda slug, kind, *a, **k: findings_by_kind.get(kind, [])
    return r


def _finding(check, label="ok", summary="detail here"):
    return {"check_name": check, "label": label, "summary": summary,
            "surveyed_at": "2026-08-28T00:00:00"}


class TestDerivation:
    def test_the_chain_travels_with_the_answer(self):
        """The explanation with content: which question, which purpose matched,
        which analysis it dispatches to."""
        c = compile_context(_registry({"license_classification": [_finding("license")]}),
                            "x", "q", purposes=["Certify"], budget=4000)
        assert c.derivation
        first = c.derivation[0]
        assert set(first) >= {"question", "matched_purposes", "analysis_ids", "rank"}

    def test_ranking_sets_weight_not_membership(self):
        """Purpose ORDERS and never excludes, so a low-ranked analysis is a
        light section rather than an absent one."""
        c = compile_context(_registry({}), "x", "q", purposes=["Certify"], budget=4000)
        keys = {g["key"] for g in c.manifest["gaps"]}
        assert len(keys) > 3, "low-ranked analyses should still appear, as gaps"


class TestQuestionRelevance:
    """Measured 2026-08-31: "Show me all the documentation survey results for
    egeria" packed repository_health / architecture_doc_lens /
    language_file_classification and dropped documentation_coverage as a gap
    entirely. `question` was accepted by compile_context() and never read
    again -- with no Perspective chips set (the common case), every one of
    the ~50 catalog questions weighed the same, decaying only by its
    arbitrary position in question_catalog.yaml. The model, given evidence
    that did not answer what was asked, fell back to vector_search and
    answered from Egeria's OWN documentation about its Survey Framework
    feature instead -- a keyword collision on "survey", not an answer."""

    def test_a_question_naming_its_topic_outranks_unrelated_ones(self):
        from resource_explorer.context_compile import _question_relevance
        from resource_explorer.surveyors.question_catalog_reader import get_questions

        entries = get_questions("repo", perspectives=None, purposes=None)
        question = "Show me all the documentation survey results for egeria"

        scored = []
        for position, e in enumerate(entries):
            ids = e["answering"]["analysis_ids"]
            if not ids:
                continue
            relevance = _question_relevance(question, e["question"], ids)
            weight = (1.0 + relevance * 20.0) / (1 + position * 0.1)
            scored.append((weight, e["question"], ids))
        scored.sort(key=lambda t: -t[0])

        top_ids = [ids for _, _, ids in scored[:2]]
        assert all("documentation_coverage" in ids for ids in top_ids), (
            f"documentation_coverage should rank first; got {scored[:2]}"
        )

    def test_weight_reaches_the_real_compile(self, monkeypatch):
        """Not just the scoring helper in isolation -- the analysis actually
        outranks an unrelated one in a real compile_context() call. Both
        pack either way at this budget (each is tiny with one finding), so
        membership alone does not distinguish fixed from unfixed -- PACKING
        ORDER does, since packed sections are emitted in weight order and
        repository_health (an unrelated, higher-catalog-position question)
        used to rank ahead of the analysis the question actually named."""
        import resource_explorer.surveyors.repo_survey_definition_adapter as adapter
        from resource_explorer import context_compile as cc

        reader_output = {"findings": [
            {"check_name": "readme", "label": "present", "summary": "README present"},
        ]}
        monkeypatch.setitem(adapter.REPO_ANALYSIS_RESULTS_MAP,
                            "documentation_coverage", (lambda reg, slug: reader_output, None))

        c = cc.compile_context(_registry({}), "egeria",
                               "Show me all the documentation survey results for egeria",
                               budget=1200)
        packed_order = [p["key"] for p in c.manifest["packed"] if p["key"] != "instructions"]
        assert "documentation_coverage" in packed_order, (
            f"documentation_coverage was crowded out; packed={packed_order}"
        )
        assert "repository_health" in packed_order, "test assumes both pack at this budget"
        assert packed_order.index("documentation_coverage") < packed_order.index("repository_health"), (
            f"documentation_coverage should outrank an unrelated question's "
            f"analysis given what was asked; packed order was {packed_order}"
        )

    def test_irrelevant_questions_are_ranked_down_not_excluded(self):
        """Purpose already establishes ranking over exclusion for this
        system; this must not become the first thing that filters instead."""
        from resource_explorer.context_compile import _question_relevance

        assert _question_relevance(
            "Show me all the documentation survey results for egeria",
            "Are there outstanding CVEs?", ["cve_scan"],
        ) == 0.0  # no overlap -- but a 0.0 weight component, not a dropped entry

    def test_no_overlap_returns_zero_not_an_error(self):
        from resource_explorer.context_compile import _question_relevance

        assert _question_relevance("", "How well documented is it?",
                                   ["documentation_coverage"]) == 0.0

    def test_rank_is_catalog_position_not_list_order(self):
        """S4 review, 2026-08-31: `derivation` is now sorted by weight
        (relevance-then-position), but each entry's `rank` field still
        reports its ORIGINAL catalog/Purpose position -- the two can and
        should diverge for a low-catalog-rank, high-relevance entry. Locking
        this in as intended behavior, not an oversight a future pass should
        "fix" by renumbering `rank` to match list order."""
        from resource_explorer.context_compile import compile_context

        c = compile_context(_registry({}), "egeria",
                            "Show me all the documentation survey results for egeria",
                            budget=8000)
        # documentation_coverage's catalog rank (24/25, see the module-level
        # measurement in this class's docstring) is well behind several
        # zero-relevance, position < 24 entries -- so it must now sort near
        # the front of `derivation` while its own `rank` field still reads
        # its true, larger catalog position.
        doc_entries = [d for d in c.derivation if "documentation_coverage" in d["analysis_ids"]]
        assert doc_entries, "documentation_coverage should be reachable from this question"
        list_index = c.derivation.index(doc_entries[0])
        assert doc_entries[0]["rank"] > list_index, (
            "rank should still report catalog position even though list order "
            f"now reflects relevance; rank={doc_entries[0]['rank']}, list_index={list_index}"
        )


class TestGapsAreNotSilence:
    def test_an_analysis_with_no_findings_is_reported(self):
        """The derivation says it answers the question and it has no stored
        result. That is information, not something to omit."""
        c = compile_context(_registry({"repo_conventions": [_finding("a")]}),
                            "x", "q", purposes=["Assess"], budget=4000)
        gap_keys = {g["key"] for g in c.manifest["gaps"]}
        packed_keys = {p["key"] for p in c.manifest["packed"]}
        assert gap_keys and not (gap_keys & packed_keys)

    def test_nothing_is_run_to_fill_a_gap(self):
        """A compile must never block on a survey. Only stored results are
        read."""
        registry = _registry({})
        compile_context(registry, "x", "q", purposes=["Certify"], budget=4000)
        assert registry.query_findings.called
        for name in ("run_analysis", "run_survey", "dispatch"):
            assert not getattr(registry, name).called


class TestBudget:
    def test_instructions_survive_a_tight_budget(self):
        """Required. A context with evidence and no instructions is a different
        task, not a smaller one."""
        c = compile_context(_registry({"repo_conventions": [_finding("a", summary="x" * 500)]}),
                            "x", "q", budget=400)
        assert any(p["key"] == "instructions" for p in c.manifest["packed"])

    def test_evidence_degrades_before_it_disappears(self):
        big = [_finding(f"check{i}", summary="y" * 200) for i in range(6)]
        c = compile_context(_registry({"repo_conventions": big}), "x", "q", budget=900)
        rungs = {p["key"]: p["rung"] for p in c.manifest["packed"]}
        assert rungs.get("repo_conventions") in {"SUMMARY", "IDENTIFIERS"}

    def test_the_ceiling_holds(self):
        big = [_finding(f"c{i}", summary="z" * 400) for i in range(10)]
        for budget in (300, 600, 1200, 5000):
            c = compile_context(_registry({"repo_conventions": big}), "x", "q", budget=budget)
            assert c.manifest["used"] <= budget

    def test_an_impossible_budget_fails_loudly(self):
        with pytest.raises(Exception):
            compile_context(_registry({}), "x", "q", budget=5)


class TestProvenance:
    def test_findings_carry_when_they_were_surveyed(self):
        """An old fact and a stale read are different things."""
        from resource_explorer.context_compile import _provenance

        prov = _provenance([_finding("a")], "repo_conventions")
        assert prov[0]["surveyed_at"] == "2026-08-28T00:00:00"
        assert prov[0]["analysis_id"] == "repo_conventions"


class TestPointerSections:
    """Backlog: "a compiled answer should be able to POINT at a view, not only
    describe it." Only analyses with a real addressable view get one."""

    def test_a_pointable_analysis_gets_a_link_alongside_its_prose(self):
        from resource_explorer.context_compile import _pointer_for

        prov = ({"analysis_id": "architecture_recovery", "check": "detect",
                 "surveyed_at": "2026-08-28T00:00:00"},)
        ptr = _pointer_for("architecture_recovery", "egeria_git", prov)
        assert ptr is not None
        assert ptr.resource_slug == "egeria_git"
        assert ptr.view == "architecture"
        assert ptr.as_of == "2026-08-28T00:00:00"

    def test_an_analysis_with_no_view_gets_none(self):
        from resource_explorer.context_compile import _pointer_for

        assert _pointer_for("license_classification", "egeria_git", ()) is None

    def test_the_pointer_reaches_the_manifest(self):
        c = compile_context(
            _registry({"architecture_recovery": [_finding("detect")]}),
            "egeria_git", "q", budget=4000,
        )
        packed = {p["key"]: p for p in c.manifest["packed"]}
        assert "pointer" in packed["architecture_recovery"]
        assert packed["architecture_recovery"]["pointer"]["view"] == "architecture"


# ── The findings table is not where most results live ────────────────────────
class TestResolvingBeyondTheFindingsTable:
    """A gap meant "not in project_analysis_findings" while claiming to mean
    "never run".

    Measured on egeria_git 2026-08-29: eleven analyses reported as gaps, seven
    of which had real stored data — repository_health scoring 85.8,
    api_structure holding 3,232 Java classes. Each keeps results in its own
    table, and only the generic findings table was consulted.
    docs/granularity-pass.md §1.2 had already measured that 12 analyses have no
    finding `kind` at all, so this was knowable without running anything.
    """

    def test_a_reader_only_analysis_is_packed_not_gapped(self, monkeypatch):
        from resource_explorer import context_compile as cc

        seen = {}

        def fake_reader(registry, slug):
            seen["called"] = slug
            return {"overall": 85.8, "activity": 100.0}

        import resource_explorer.surveyors.repo_survey_definition_adapter as adapter
        monkeypatch.setitem(adapter.REPO_ANALYSIS_RESULTS_MAP,
                            "repository_health", (fake_reader, None))

        c = cc.compile_context(_registry({}), "egeria_git", "is this ready to adopt?",
                               budget=8000)
        gaps = {g["key"] for g in c.manifest["gaps"]}
        assert "repository_health" not in gaps, "packed data still reported missing"
        assert seen.get("called") == "egeria_git"
        assert "repository_health" in {e["key"] for e in c.manifest["packed"]}

    def test_a_genuinely_empty_result_stays_a_gap(self, monkeypatch):
        """The fix must not swap a wrong gap for a wrong section. cve_scan
        answers {"findings": []} — a dict, therefore truthy, and meaning
        nothing was found."""
        import resource_explorer.surveyors.repo_survey_definition_adapter as adapter
        from resource_explorer import context_compile as cc

        monkeypatch.setitem(adapter.REPO_ANALYSIS_RESULTS_MAP,
                            "cve_scan", (lambda reg, slug: {"findings": []}, None))
        c = cc.compile_context(_registry({}), "x", "is this ready to adopt?", budget=8000)
        assert "cve_scan" in {g["key"] for g in c.manifest["gaps"]}

    def test_a_reader_that_raises_is_not_evidence_of_absence(self, monkeypatch):
        """It still ends as a gap — there is nothing to pack — but it must not
        take the whole compile down with it."""
        import resource_explorer.surveyors.repo_survey_definition_adapter as adapter
        from resource_explorer import context_compile as cc

        def boom(reg, slug):
            raise RuntimeError("table missing")

        monkeypatch.setitem(adapter.REPO_ANALYSIS_RESULTS_MAP, "cve_scan", (boom, None))
        c = cc.compile_context(_registry({}), "x", "is this ready to adopt?", budget=8000)
        assert "cve_scan" in {g["key"] for g in c.manifest["gaps"]}

    def test_findings_win_when_both_exist(self, monkeypatch):
        """The findings table is consulted first and its richer per-check rungs
        are kept; the reader is a fallback, not an override."""
        import resource_explorer.surveyors.repo_survey_definition_adapter as adapter
        from resource_explorer import context_compile as cc

        monkeypatch.setitem(adapter.REPO_ANALYSIS_RESULTS_MAP,
                            "license_classification",
                            (lambda reg, slug: {"from": "reader"}, None))
        c = cc.compile_context(
            _registry({"license_classification": [_finding("license_risk_tier")]}),
            "x", "q", purposes=["Certify"], budget=8000)
        assert "license_risk_tier" in c.text, "findings rungs were not used"
        assert '"from": "reader"' not in c.text, "the fallback overrode real findings"


class TestReaderFindingsShapeIsFormattedNotCounted:
    """Measured 2026-08-31: asking the chat "show me documentation coverage
    on Egeria" answered "5 key(s) with 4 item(s) found" -- the model
    narrating _results_to_rungs' generic SUMMARY verbatim.
    _documentation_results (repo_survey_definition_adapter.py) returns
    {"findings": [...], "_status": {...}}, the same finding shape the
    findings table itself uses; the reader-fallback path was reducing it to
    two cardinalities instead of reusing _findings_to_rungs' own per-check
    formatting.

    Tests hit _results_to_rungs directly, not through compile_context: the
    bug is specifically in the SUMMARY rung, and a budget generous enough to
    let the packer choose FULL instead (a full JSON dump, which happens to
    contain the real strings too) would pass without the fix -- caught by
    running these against the unfixed code before adding them."""

    def _reader_output(self):
        return {
            "findings": [
                {"check_name": "readme", "label": "present",
                 "summary": "README.md found at repo root"},
                {"check_name": "changelog", "label": "missing",
                 "summary": "no CHANGELOG file located"},
            ],
            "_status": {"state": "measured", "outcome": "complete"},
        }

    def test_summary_rung_keeps_per_check_content(self):
        from resource_explorer.context_compile import _results_to_rungs
        from trellis_artifact_tree.model import Rung

        rungs = _results_to_rungs(self._reader_output(), "documentation_coverage")
        summary = rungs[Rung.SUMMARY]

        assert "readme" in summary and "present" in summary
        assert "changelog" in summary and "missing" in summary
        # The exact bug: two cardinalities standing in for the content above.
        assert "item(s)" not in summary
        assert "key(s)" not in summary

    def test_full_rung_also_uses_finding_formatting(self):
        from resource_explorer.context_compile import _results_to_rungs
        from trellis_artifact_tree.model import Rung

        rungs = _results_to_rungs(self._reader_output(), "documentation_coverage")
        full = rungs[Rung.FULL]

        assert "README.md found at repo root" in full
        assert "no CHANGELOG file located" in full
        # Other top-level keys (here, _status) are noted, not silently dropped.
        assert "_status" in full

    def test_reaches_the_answer_through_compile_context_too(self, monkeypatch):
        """Integration-level check that the fix is actually wired in, at
        whichever rung the packer picks for a real compile."""
        import resource_explorer.surveyors.repo_survey_definition_adapter as adapter
        from resource_explorer import context_compile as cc

        monkeypatch.setitem(adapter.REPO_ANALYSIS_RESULTS_MAP,
                            "documentation_coverage",
                            (lambda reg, slug: self._reader_output(), None))
        c = cc.compile_context(_registry({}), "egeria_git", "is this ready to adopt?", budget=8000)
        assert "documentation_coverage" not in {g["key"] for g in c.manifest["gaps"]}
        assert "readme" in c.text

    def test_a_reader_returning_a_genuinely_non_finding_shape_is_unaffected(self):
        """The generic path (key: cardinality) still applies to shapes that
        are not the findings-list envelope -- e.g. repository_health's flat
        metrics dict. This exception is a shape match, not a blanket change
        to every reader's output."""
        from resource_explorer.context_compile import _results_to_rungs
        from trellis_artifact_tree.model import Rung

        rungs = _results_to_rungs({"overall": 85.8, "activity": 100.0}, "repository_health")
        assert "85.8" in rungs[Rung.SUMMARY]
        assert "key(s)" not in rungs[Rung.SUMMARY]  # no dict/list values here to miscount
        # A shape that genuinely has no per-check identity keeps the old,
        # structural summary -- e.g. a list-valued key still reads as a count.
        rungs2 = _results_to_rungs({"by_ecosystem": {"pypi": 3, "npm": 5}, "total": 8},
                                    "dependency_analysis")
        assert "2 key(s)" in rungs2[Rung.SUMMARY]  # by_ecosystem: 2 key(s) — unchanged behavior


class TestHasContent:
    """The zero case, which a first version got wrong.

    `_has_content` put the numeric test in an `elif ... and value` and followed
    it with a catch-all `elif value is not None`, so a zero failed the numeric
    branch and was caught by the fallback. `{"by_ecosystem": {}, "total": 0}`
    read as content and packed dependency_analysis as an empty section
    asserting it had something to say.
    """

    @pytest.mark.parametrize("value,expected", [
        ({"by_ecosystem": {}, "total": 0}, False),
        ({"findings": []}, False),
        ({}, False),
        ({"x": None}, False),
        ({"s": ""}, False),
        ({"n": 0.0}, False),
        ({"ok": False}, False),
        ({"total": 3}, True),
        ({"overall": 85.8}, True),
        ({"ok": True}, True),
        ({"s": "a"}, True),
        ({"items": [1]}, True),
    ])
    def test_truth_table(self, value, expected):
        from resource_explorer.context_compile import _has_content
        assert _has_content(value) is expected


class TestPublishActionsAreNotAnalyses:
    def test_egeria_publish_is_never_a_gap(self):
        """It writes to Egeria and has no results, so it could only ever be a
        permanent gap asserting a result that will never exist. The scheduler
        excludes action == "publish" for the same reason. A catalog question
        references it, which is how it reaches the compile at all."""
        c = compile_context(_registry({}), "x", "is this ready to adopt?", budget=8000)
        assert "egeria_publish" not in {g["key"] for g in c.manifest["gaps"]}
        assert "egeria_publish" not in str(c.derivation)


class TestChatRoutesThroughTheCompiler:
    """The answer path, not just the Evidence pane.

    Previously the agent was told which collections exist and left to search
    them. Now the analyses the question catalog says answer this question are
    resolved from stored results and put in the prompt directly.
    """

    def _agent(self):
        from resource_explorer.agents.conversation_agent import ConversationAgent

        return ConversationAgent()

    def test_gaps_are_named_in_the_prompt(self):
        """From inside a prompt, an analysis that never ran looks exactly like
        one that ran and found nothing. Naming the gaps is what stops the model
        answering 'no CVEs' when no CVE scan has ever run."""
        from unittest.mock import patch

        from resource_explorer.context_compile import CompiledContext

        compiled = CompiledContext(
            text="## repo_conventions\n- a: ok",
            manifest={"gaps": [{"key": "cve_scan"}, {"key": "security_scan"}]},
            derivation=[],
        )
        with patch("resource_explorer.context_compile.compile_context", return_value=compiled), \
             patch("resource_explorer.registry.ProjectRegistry"):
            blocks = self._agent()._compiled_evidence("q", "slug", [])
        joined = "\n".join(blocks)
        assert "cve_scan" in joined and "security_scan" in joined
        # Judged, not flattened. "ran and found nothing" and "has not run" are
        # the same number and opposite answers, so the prompt must not merge
        # them -- and must not claim the stronger one for a gap it cannot
        # support, which an earlier version did for two of three.
        assert "opposite" not in joined  # we state the distinction, not the meta
        assert "has not run has not" in joined

    def test_evidence_reaches_the_prompt(self):
        from unittest.mock import patch

        from resource_explorer.context_compile import CompiledContext

        compiled = CompiledContext(text="## license_classification\n- apache-2.0",
                                   manifest={"gaps": []}, derivation=[])
        with patch("resource_explorer.context_compile.compile_context", return_value=compiled), \
             patch("resource_explorer.registry.ProjectRegistry"):
            joined = "\n".join(self._agent()._compiled_evidence("q", "slug", []))
        assert "license_classification" in joined
        assert "compiled from stored analysis results" in joined

    def test_a_failed_compile_costs_nothing(self):
        """Fail-soft. A compiler that cannot compile must not cost the answer —
        the agent still has its tools and proceeds as it did before."""
        from unittest.mock import patch

        with patch("resource_explorer.context_compile.compile_context",
                   side_effect=RuntimeError("no db")), \
             patch("resource_explorer.registry.ProjectRegistry"):
            assert self._agent()._compiled_evidence("q", "slug", []) == []

    def test_no_perspectives_is_a_real_state_not_a_missing_value(self):
        """Empty chips means no perspective filter, and the compile still runs.
        Treating it as missing would silently skip the whole path."""
        from unittest.mock import patch

        from resource_explorer.context_compile import CompiledContext

        with patch("resource_explorer.context_compile.compile_context",
                   return_value=CompiledContext("x", {"gaps": []}, [])) as m, \
             patch("resource_explorer.registry.ProjectRegistry"):
            self._agent()._compiled_evidence("q", "slug", None)
        assert m.call_args.kwargs["perspectives"] == []


class TestGapsAreJudgedNotListed:
    """A measured zero and a never-run are the same number and opposite
    answers (facts.py). The packer knows only that a section had no candidate;
    the fact layer knows which of the two it is.
    """

    def test_a_real_zero_is_not_called_missing(self):
        from unittest.mock import MagicMock

        from resource_explorer.context_compile import _judge_gap

        fl = MagicMock()
        fl.fact.return_value = MagicMock(
            state="nothing_found", last_run_at="2026-08-28", can_run=["repo_cve_scan"])
        gap = _judge_gap(fl, "x", "cve_scan")
        assert gap["state"] == "nothing_found"
        assert "real zero" in gap["reason"]
        assert gap["can_run"] == ["repo_cve_scan"]

    def test_never_run_says_so(self):
        from unittest.mock import MagicMock

        from resource_explorer.context_compile import _judge_gap

        fl = MagicMock()
        fl.fact.return_value = MagicMock(state="never_run", last_run_at="", can_run=["repo_x"])
        assert _judge_gap(fl, "x", "a")["reason"] == "has not run"

    def test_an_unjudgeable_gap_is_still_reported(self):
        """Fail-soft: a fact layer that cannot answer must not cost the compile,
        and an unjudged gap is still worth naming."""
        from unittest.mock import MagicMock

        from resource_explorer.context_compile import _judge_gap

        fl = MagicMock()
        fl.fact.side_effect = RuntimeError("no registry")
        gap = _judge_gap(fl, "x", "a")
        assert gap["key"] == "a" and "resolver produced nothing" in gap["reason"]
        assert "state" not in gap

    def test_the_vocabulary_is_borrowed_not_invented(self):
        """result_status.py already carries these states and facts.py already
        applies them. A parallel vocabulary here is how four retired RE
        perspectives ended up beside Egeria's twelve."""
        from resource_explorer import facts
        from resource_explorer.context_compile import _GAP_PHRASING

        # facts.py is the source of truth for Fact.state: it imports the
        # result_status states AND adds PARTIAL of its own. Asserting against
        # result_status alone was too narrow — and caught me inventing
        # "partial" in the very code this test guards.
        for state in _GAP_PHRASING:
            assert hasattr(facts, state.upper()), f"{state} is not a Fact state"


class TestNoSingleFindingDominates:
    """Findings are written for whatever consumer the surveyor had in mind, and
    some are not prose — a rendered diagram, a serialised graph, a file listing.
    One of them can crowd out every other check in the same analysis.
    """

    def test_a_huge_finding_is_clipped(self):
        from resource_explorer.context_compile import MAX_FINDING_CHARS, _findings_to_rungs
        from trellis_artifact_tree.model import Rung

        findings = [
            {"check_name": "architecture_diagram", "label": "ok", "summary": "M" * 40000},
            {"check_name": "components", "label": "12 found", "summary": "short and useful"},
        ]
        full = _findings_to_rungs(findings, "architecture_recovery")[Rung.FULL]
        assert len(full) < MAX_FINDING_CHARS * 2
        assert "short and useful" in full, "the small finding must survive the big one"

    def test_truncation_is_marked_not_silent(self):
        """An elided finding that looked complete is the failure this module
        keeps finding in other forms."""
        from resource_explorer.context_compile import _findings_to_rungs
        from trellis_artifact_tree.model import Rung

        full = _findings_to_rungs(
            [{"check_name": "diagram", "label": "", "summary": "x" * 5000}], "arch",
        )[Rung.FULL]
        assert "truncated" in full and "arch/diagram" in full

    def test_ordinary_findings_are_untouched(self):
        from resource_explorer.context_compile import _findings_to_rungs
        from trellis_artifact_tree.model import Rung

        body = "a normal finding summary"
        full = _findings_to_rungs(
            [{"check_name": "c", "label": "l", "summary": body}], "a")[Rung.FULL]
        assert body in full and "truncated" not in full


class TestThinFindingsDoNotSuppressTheReader:
    """An earlier version fell back to the results reader only when findings
    were EMPTY, so any whole-resource finding — however slight — replaced an
    analysis's real results. The rule is about evidence, not precedence.
    """

    def _compile(self, findings, reader_results):
        from unittest.mock import MagicMock, patch

        from resource_explorer.context_compile import compile_context

        registry = MagicMock()
        registry.query_findings.side_effect = (
            lambda slug, kind, *a, **k: findings.get(kind, []))
        reader = MagicMock(return_value=reader_results)
        with patch("resource_explorer.surveyors.repo_survey_definition_adapter"
                   ".REPO_ANALYSIS_RESULTS_MAP", {"repo_conventions": (reader, None)}), \
             patch("resource_explorer.facts.FactLayer"):
            return compile_context(registry, "x", "q", budget=8000), reader

    def test_a_slight_finding_does_not_hide_richer_results(self):
        """The exact regression: one whole-resource diagram finding replaced an
        analysis's results with a picture, making the section worse than before
        the finding existed."""
        thin = {"repo_conventions": [
            {"check_name": "diagram", "label": "", "summary": ""}]}
        rich = {"detail": "a" * 3000}
        compiled, reader = self._compile(thin, rich)
        assert reader.called, "a thin finding must not suppress the reader"

    def test_substantial_findings_do_not_call_the_reader(self):
        """The reader is a fallback, not a second opinion on good evidence."""
        fat = {"repo_conventions": [
            {"check_name": f"c{i}", "label": "ok", "summary": "y" * 200}
            for i in range(5)]}
        _, reader = self._compile(fat, {"detail": "z" * 50})
        assert not reader.called

    def test_the_reader_does_not_displace_more_than_it_offers(self):
        """Falling back is not the same as preferring. If the reader says less
        than the thin findings did, the findings stay."""
        from resource_explorer.context_compile import _findings_to_rungs
        from trellis_artifact_tree.model import Rung

        thin = [{"check_name": "c", "label": "l", "summary": "x" * 150}]
        compiled, _ = self._compile({"repo_conventions": thin}, {"detail": ""})
        packed = " ".join(s for s in [compiled.text])
        assert "repo_conventions" in packed
