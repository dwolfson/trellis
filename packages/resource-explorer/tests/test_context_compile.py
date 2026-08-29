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
