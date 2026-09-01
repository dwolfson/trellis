"""A stage load waited in series on round trips that had no reason to be serial.

Measured 2026-08-31: `/candidates` took ~24s cold and 0.12s warm, and the UI
issued it **twice** — once scoped to the stage, once unscoped for cross-stage
`automate_full` definitions. Two independent causes, fixed separately:

  server  `find_candidate_process_guids_by_questions` resolved one Egeria GUID
          per question, strictly one after another. Ten questions for a stage;
          **49** for the unscoped call, because no `phase` means every cataloged
          question.
  client  the two fetches were awaited one after the other.

Neither was work. Both were waiting. These tests pin the properties that make
the fix safe rather than the timings, which vary with whatever Egeria is doing.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from unittest.mock import patch

from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader

INDEX = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "index.html"


def _reader() -> SurveyDefinitionReader:
    return SurveyDefinitionReader()


def test_guid_resolution_preserves_input_order():
    """The result feeds a cache key and pairs each guid with its question text.
    Concurrency must not be visible in the output."""
    qs = [f"Q{i}" for i in range(12)]

    def fake(q):
        # Reverse the natural completion order: later questions finish first.
        time.sleep(0.01 * (len(qs) - int(q[1:])))
        return "guid-" + q

    with patch.object(SurveyDefinitionReader, "resolve_question_guid", side_effect=fake), \
         patch.object(SurveyDefinitionReader, "_connect_classification_explorer", return_value=None):
        out = _reader()._resolve_question_guids(qs)

    assert out == [(q, "guid-" + q) for q in qs], (
        "questions came back in completion order rather than input order"
    )


def test_unresolvable_questions_are_dropped_not_paired_with_none():
    """A question with no Egeria element contributes no scoping — it must not
    arrive as (question, None) and be treated as a real guid downstream."""
    qs = ["known", "missing", "also-known"]

    def fake(q):
        return None if q == "missing" else "guid-" + q

    with patch.object(SurveyDefinitionReader, "resolve_question_guid", side_effect=fake), \
         patch.object(SurveyDefinitionReader, "_connect_classification_explorer", return_value=None):
        out = _reader()._resolve_question_guids(qs)

    assert out == [("known", "guid-known"), ("also-known", "guid-also-known")]


def test_resolution_is_concurrent_not_serial():
    """The point of the change. Asserted as a bound well clear of both outcomes
    so it cannot fail on a slow machine: 20 lookups of 50ms are 1.0s serially
    and ~0.15s at 8 workers."""
    qs = [f"Q{i}" for i in range(20)]

    def fake(q):
        time.sleep(0.05)
        return "guid-" + q

    with patch.object(SurveyDefinitionReader, "resolve_question_guid", side_effect=fake), \
         patch.object(SurveyDefinitionReader, "_connect_classification_explorer", return_value=None):
        start = time.monotonic()
        _reader()._resolve_question_guids(qs)
        elapsed = time.monotonic() - start

    assert elapsed < 0.6, (
        f"resolution took {elapsed:.2f}s for 20x50ms lookups — serial would be "
        "~1.0s, so this has regressed to one-at-a-time"
    )


def test_the_client_is_warmed_before_the_pool_starts():
    """`_connect_classification_explorer` memoises on the instance AND fetches a
    bearer token as a side effect. Letting N workers race to be first means N
    clients constructed and N token requests, all but one discarded.

    The warm-up is done by resolving the first question on the calling thread,
    deliberately, rather than by wrapping the connect call in its own
    try/except — that would have added a silent-failure site (the
    no-silent-success ratchet caught exactly that) when
    `resolve_question_guid` already handles its own errors.
    """
    import threading

    main = threading.get_ident()
    threads: list[int] = []
    connects: list[int] = []

    def fake_connect(self):
        connects.append(1)
        return None

    def fake_resolve(q):
        threads.append(threading.get_ident())
        SurveyDefinitionReader._connect_classification_explorer(None)
        return "guid-" + q

    with patch.object(SurveyDefinitionReader, "_connect_classification_explorer", fake_connect), \
         patch.object(SurveyDefinitionReader, "resolve_question_guid", side_effect=fake_resolve):
        _reader()._resolve_question_guids([f"Q{i}" for i in range(10)])

    assert threads[0] == main, (
        "the first question was resolved on a worker, so nothing guarantees the "
        "client is constructed once before the pool fans out"
    )
    assert len(threads) == 10


def test_a_single_question_does_not_start_a_thread_pool():
    """The common case for a narrow stage. Spinning up an executor to wait on
    one call is pure overhead."""
    with patch.object(SurveyDefinitionReader, "resolve_question_guid", side_effect=lambda q: "g"), \
         patch.object(SurveyDefinitionReader, "_connect_classification_explorer", return_value=None):
        assert _reader()._resolve_question_guids(["only"]) == [("only", "g")]
        assert _reader()._resolve_question_guids([]) == []


def test_the_two_candidate_fetches_are_issued_together():
    """Client half. They are independent — the second only appends cross-stage
    definitions the first cannot return — so awaiting one before starting the
    other paid both round trips end to end.
    """
    src = INDEX.read_text()
    block = src[src.index("const _candParams = { phase: intent"):]
    block = block[:block.index("/* non-fatal")]

    assert "Promise.allSettled" in block, (
        "the two candidate fetches are not issued concurrently"
    )
    # allSettled rather than all: the cross-stage fetch was already non-fatal,
    # and `all` rejects the pair as soon as either fails.
    assert "Promise.all(" not in block, (
        "Promise.all would make a failing cross-stage fetch take the stage's "
        "own surveys down with it"
    )
    # No await may sit between the two fetch() calls, or they are serial again
    # while looking concurrent.
    between = block[block.index("Promise.allSettled"):block.index("]);")]
    assert "await" not in between, (
        f"an await appears between the two fetches, re-serialising them: {between!r}"
    )


def test_both_candidate_filters_are_still_sent():
    """Guards the same incident `test_ui_terminology_consistency` documents:
    each filter alone returns a plausible wrong list. Re-asserted here because
    this file rewrote the call site."""
    src = INDEX.read_text()
    assert "const _candParams = { phase: intent, survey_kind: intent };" in src
    assert re.search(r"survey_kind:\s*'automate_full'", src)
