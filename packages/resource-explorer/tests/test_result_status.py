"""The three empty states a results card can be in, and why one string was wrong.

Every render mode fell back to "No results yet — click Run to scan." Measured
across the corpus 2026-08-24, the persisted outcomes said otherwise for 51 of
them: 36 data_profile rows are `no_signal` (scanned, provably no data files)
and 15 more are `unverified` (a different step is the missing prerequisite).
So the message asserted "never run" about runs that had happened, and sent
people to press a button that could not help.

step_outcome.py answers the question a RUN has ("is my zero provable?").
This answers the question a READER has ("what should I do about it?"), and the
two are not the same question — which is why this is a separate vocabulary
rather than the same five labels reused.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.surveyors import result_status as rs


class TestOutcomeMapsToAReaderState:

    @pytest.mark.parametrize("outcome,expected", [
        ("recovered", rs.MEASURED),
        ("partial", rs.MEASURED),
        ("regression", rs.MEASURED),
        ("no_signal", rs.NOTHING_FOUND),
        ("unverified", rs.NOT_ESTABLISHED),
    ])
    def test_every_outcome_has_a_state(self, outcome, expected):
        assert rs.status_from_detail({"outcome": outcome})["state"] == expected

    def test_no_signal_and_unverified_do_not_collapse(self):
        """The distinction the whole vocabulary exists for. If these two ever
        map to the same state, the card is back to one message for two
        meanings."""
        a = rs.status_from_detail({"outcome": "no_signal", "outcome_cause": "no_data_files"})
        b = rs.status_from_detail({"outcome": "unverified", "outcome_cause": "empty_file_inventory"})
        assert a["state"] != b["state"]

    def test_a_kind_with_no_outcome_gets_no_status(self):
        """Kinds that have not adopted the vocabulary must keep today's
        behaviour rather than being handed a guessed state."""
        assert rs.status_from_detail({"total": 3}) is None
        assert rs.status_from_detail(None) is None
        assert rs.status_from_detail("") is None

    def test_detail_may_arrive_as_json_text(self):
        """Postgres hands back JSONB as a dict, SQLite as a string — the same
        backend divergence that has bitten this codebase repeatedly."""
        raw = json.dumps({"outcome": "no_signal", "outcome_cause": "no_data_files"})
        assert rs.status_from_detail(raw)["state"] == rs.NOTHING_FOUND


class TestHints:

    def test_a_known_cause_says_what_to_do(self):
        st = rs.status_from_detail({"outcome": "unverified",
                                    "outcome_cause": "empty_file_inventory"})
        assert "Coarse Profile" in st["hint"]

    def test_an_unknown_cause_does_not_invent_a_remedy(self):
        """Silence is better than a confident wrong instruction — the failure
        this whole change is fixing."""
        st = rs.status_from_detail({"outcome": "unverified", "outcome_cause": "something_new"})
        assert st["hint"] == ""

    def test_a_nothing_found_hint_never_asks_for_a_re_run(self):
        """`no_signal` is a final answer. Any hint that tells the reader to run
        something is wrong by construction here."""
        for cause in ("no_data_files", "no_hygiene_files", "no_dependency_manifest"):
            hint = rs.status_from_detail({"outcome": "no_signal", "outcome_cause": cause})["hint"]
            assert hint and "Run " not in hint, cause


class TestAttach:

    def test_attach_is_additive(self):
        result = {"profiles": [], "total": 0}
        out = rs.attach(result, {"outcome": "no_signal", "outcome_cause": "no_data_files"})
        assert out["total"] == 0 and out["profiles"] == []
        assert out["_status"]["state"] == rs.NOTHING_FOUND

    def test_attach_adds_nothing_when_undecidable(self):
        out = rs.attach({"total": 0}, None)
        assert "_status" not in out


class TestSkippedByDesign:
    """A gate declining to run is the funnel working, not failing.

    Raised by the session that landed repo_classification: its run/skip gate had
    no label that fits, and none of step_outcome.py's five does — `unverified`
    means "we tried and could not tell", where a skip means "we chose not to
    try, and that choice was correct". It lives here, in the reader-facing
    layer, rather than becoming a sixth run outcome.
    """

    def test_a_skip_is_its_own_state(self):
        st = rs.skipped("Tutorial repos have no architecture to recover.")
        assert st["state"] == rs.SKIPPED_BY_DESIGN

    def test_a_skip_is_not_confused_with_a_failed_run(self):
        assert rs.SKIPPED_BY_DESIGN not in (rs.NOT_ESTABLISHED, rs.NOTHING_FOUND, rs.NEVER_RUN)

    def test_a_skip_always_carries_its_reason(self):
        """A skip with no stated reason renders identically to a failure, which
        is the whole thing this state exists to prevent."""
        st = rs.skipped("Gate: classified as documentation, not software.")
        assert st["hint"]

    def test_no_outcome_label_is_invented_for_it(self):
        """It must not borrow one of step_outcome's five — a skip had no run to
        describe."""
        assert rs.skipped("x")["outcome"] == ""


class TestMisgrouped:
    """Right files, wrong grouping — a different kind of answer, not a weaker one.

    From the architecture-recovery session's real case: Kubernetes scored 0 of 6
    components while covering 2,002 of 2,132 files, all six collapsed under one
    overclaiming node. Rendered as "found nothing" — which is what happened —
    that reads as a detection failure when the fault was in the merge, and it
    cost an afternoon.
    """

    def test_it_is_not_nothing_found(self):
        """The confusion that motivated it."""
        assert rs.misgrouped("x")["state"] != rs.NOTHING_FOUND

    def test_it_is_not_a_degraded_measurement(self):
        """Nothing went wrong with the looking, so it must not share a state
        with the cases where something did."""
        st = rs.misgrouped("x")["state"]
        assert st not in (rs.NOT_ESTABLISHED, rs.NEVER_RUN, rs.MEASURED)

    def test_it_carries_no_score_shaped_field(self):
        """docs/architecture-recovery-design.md §5.5a(c) rules out scores,
        grades and percentages because they punish deliberate choices. A
        coverage number on this state would be a partial-credit score in
        everything but name — the evidence goes in the prose instead."""
        banned = ("score", "grade", "rating", "maturity", "percentage", "count", "coverage")
        for field in rs.misgrouped("2,002 of 2,132 files matched"):
            assert not any(b in field.lower() for b in banned), field

    def test_the_reason_is_required_and_kept(self):
        st = rs.misgrouped("2,002 of 2,132 files matched, but all six landed under one node.")
        assert "2,132" in st["hint"]

    def test_every_reader_state_is_distinct(self):
        """The whole vocabulary in one assertion — five states that must never
        collapse into each other."""
        states = {rs.MEASURED, rs.NOTHING_FOUND, rs.NOT_ESTABLISHED,
                  rs.NEVER_RUN, rs.SKIPPED_BY_DESIGN, rs.MISGROUPED}
        assert len(states) == 6
