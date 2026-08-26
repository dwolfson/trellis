"""Facts leave the layer already judged.

Every agent that answers a question needs the value AND whether the value means
anything. When each one goes to the tables itself, an empty table becomes "none
found" -- and "none found" and "we never looked" read identically to whoever
asked. An LLM narrating raw rows is the most efficient way yet devised to
produce that error at scale, which is why the state travels with the value.
"""
from __future__ import annotations

import pytest

from resource_explorer.facts import (
    PARTIAL,
    PROVENANCE_RECOVERED,
    UNANSWERABLE_KINDS,
    UNDECLARED_KINDS,
    Envelope,
    Fact,
    FactLayer,
    _has_content,
)
from resource_explorer.surveyors.result_status import (
    MEASURED,
    NEVER_RUN,
    NOT_ESTABLISHED,
    NOTHING_FOUND,
)


class TestIsKnown:
    def test_a_measured_zero_is_knowledge(self):
        """nothing_found means we looked and there was nothing. That is an
        answer, and treating it as ignorance would make every clean result
        indistinguishable from an unrun one."""
        assert Fact("x", NOTHING_FOUND).is_known is True

    def test_never_run_and_not_established_are_not(self):
        assert Fact("x", NEVER_RUN).is_known is False
        assert Fact("x", NOT_ESTABLISHED).is_known is False

    def test_a_partial_run_still_counts(self):
        """A partial result is usable. Discarding it would throw away real work
        because it was incomplete."""
        assert Fact("x", PARTIAL).is_known is True


class TestEnvelope:
    def test_an_envelope_with_nothing_known_is_not_answerable(self):
        """The whole reason this type exists rather than returning values: a
        caller must not be able to turn silence into a negative answer."""
        env = Envelope(subject="s", facts=[Fact("a", NEVER_RUN), Fact("b", NOT_ESTABLISHED)])
        assert env.answerable is False

    def test_one_known_fact_is_enough(self):
        env = Envelope(subject="s", facts=[Fact("a", NEVER_RUN), Fact("b", NOTHING_FOUND)])
        assert env.answerable is True

    def test_can_run_is_deduped_across_facts_in_order(self):
        """Two analyses sharing a step must not offer to run it twice."""
        env = Envelope(subject="s", facts=[
            Fact("a", NEVER_RUN, can_run=["repo_language", "repo_health"]),
            Fact("b", NEVER_RUN, can_run=["repo_health", "repo_security"]),
        ])
        assert env.can_run == ["repo_language", "repo_health", "repo_security"]

    def test_counts_are_computed_once_in_the_envelope(self):
        """So two agents cannot disagree about whether the same envelope had
        an answer."""
        d = Envelope(subject="s", facts=[Fact("a", MEASURED), Fact("b", NEVER_RUN)]).as_dict()
        assert d["known_count"] == 1 and d["unknown_count"] == 1


class TestHasContent:
    """`_status`, `surveyed_at` and `detail` describe the RUN, not the finding."""

    def test_a_results_dict_of_only_envelope_keys_has_measured_nothing(self):
        assert _has_content({"_status": {"state": "measured"},
                             "surveyed_at": "2026-08-26T00:00:00",
                             "detail": {"source": "egeria"}}) is False

    def test_real_content_is_content(self):
        assert _has_content({"surveyed_at": "x", "components": [{"name": "a"}]}) is True

    def test_zero_and_empty_are_not_content(self):
        assert _has_content({"count": 0}) is False
        assert _has_content({"items": []}) is False
        assert _has_content({"name": "   "}) is False

    def test_a_false_flag_is_not_content(self):
        """`partial: False` says a run was complete; it is not a finding."""
        assert _has_content({"partial": False}) is False


class TestQuestionRouting:
    """The catalog already states how each question is answerable, so routing
    is a lookup rather than an inference -- and for most of them the correct
    behaviour is to produce no answer about the resource at all."""

    def _q(self, kind, ids=None, note=""):
        return {"question": f"a {kind} question",
                "answering": {"kind": kind, "analysis_ids": ids or [], "note": note}}

    def test_a_gap_question_answers_about_the_gap_not_the_resource(self):
        env = FactLayer().answer("any-slug", self._q("gap", note="GAP: CVE scan"))
        assert env.answerable is False
        assert env.facts == []
        assert "No mechanism exists" in env.blocked_reason
        assert "CVE scan" in env.blocked_reason

    def test_a_human_question_is_not_answered_from_surveys(self):
        env = FactLayer().answer("any-slug", self._q("human"))
        assert env.answerable is False
        assert "human-supplied" in env.blocked_reason

    def test_an_undeclared_kind_is_not_reported_as_a_missing_mechanism(self):
        """`direct` questions ARE answerable -- from a field on the resource.
        Calling that "nothing can answer this" would be false, and would hide
        the largest cheap fix in the catalog."""
        env = FactLayer().answer("any-slug", self._q("direct"))
        assert env.answerable is False
        assert "No mechanism exists" not in env.blocked_reason
        assert "catalog records" in env.blocked_reason

    def test_the_two_tables_do_not_overlap(self):
        """A kind in both would resolve by dict order, silently."""
        assert not (set(UNANSWERABLE_KINDS) & set(UNDECLARED_KINDS))

    def test_a_question_declaring_no_analysis_says_so(self):
        env = FactLayer().answer("any-slug", self._q("analysis"))
        assert env.answerable is False
        assert "declares no analysis" in env.blocked_reason


class TestAgainstRealCatalog:
    """Live-ish: the real 41 questions against a real registry."""

    def test_every_catalogued_question_produces_an_envelope(self):
        from resource_explorer.surveyors.question_catalog_reader import get_questions

        fl = FactLayer()
        for q in get_questions():
            env = fl.answer("no-such-repo-at-all", q)
            # Never raises, and never claims an answer about a repo that does
            # not exist.
            assert env.answerable is False
            assert env.blocked_reason, f"no reason given for: {q['question'][:50]}"

    def test_an_unknown_analysis_id_is_not_established_rather_than_empty(self):
        """An id with no results reader cannot be read from, whatever it did --
        egeria_publish is the live example: an action, not an analysis."""
        f = FactLayer().fact("no-such-repo-at-all", "egeria_publish")
        assert f.state == NOT_ESTABLISHED
        assert f.is_known is False
        assert "action rather than findings" in f.note


class TestProvenance:
    def test_recovered_components_are_marked_as_proposals(self):
        """A component recovered from a repo is a proposal, not a validated
        part of an architecture. Reporting a recovered partition as an
        established one is what a blueprint must not be built on."""
        assert FactLayer._provenance_for({"components": []}) == PROVENANCE_RECOVERED

    def test_egeria_sourced_facts_say_so(self):
        from resource_explorer.facts import PROVENANCE_EGERIA

        assert FactLayer._provenance_for({"detail": {"source": "egeria"}}) == PROVENANCE_EGERIA
