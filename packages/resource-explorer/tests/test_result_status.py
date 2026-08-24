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
