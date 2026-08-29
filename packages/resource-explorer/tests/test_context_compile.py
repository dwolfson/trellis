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
        assert "not evidence of absence" in joined
        # "no stored result", never "has not run": two of egeria_git's three
        # gaps DO run and emit an annotation explaining the empty result, so the
        # stronger claim is false and would send a reader to re-run something
        # that cannot help.
        assert "no stored result" in joined
        assert "NOT run" not in joined

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
