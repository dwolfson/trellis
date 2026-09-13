"""REPLY-BLANK-RAIL-AND-LIST-ANSWERS (designer, 2026-09-12, read against
19f3733): the evidence rail had three writers, a guard that read a
preference instead of the DOM, an early return that rendered failure as
blank, and a candidate button that counted answer lines. The rules that
make the class of bug impossible, pinned at the source; the behaviour was
verified in a browser (guard on a closed DOM, last click wins, the frame
names what and for what)."""
from __future__ import annotations

import re
from pathlib import Path

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"


def _app():
    return (NEXT / "app.js").read_text(encoding="utf-8")


class TestTheRailRules:
    def test_writers_guard_on_the_dom_not_the_preference(self):
        app = _app()
        assert "function railIsShowing()" in app and "classList.contains('rail-closed')" in app
        for fn in ("function showEvidence(", "async function openMembers(", "function renderEnrichmentEvidence("):
            body = app[app.index(fn):app.index(fn) + 1500]
            assert "ensureRailShowing()" in body, f"{fn} does not open the rail it writes into"
            assert "if (!railIsOpen()) setRailOpen(true)" not in body, f"{fn} still guards on localStorage"

    def test_every_terminal_state_of_evidence_is_a_sentence(self):
        app = _app()
        body = app[app.index("function showEvidence("):app.index("Boot\n", app.index("function showEvidence("))]
        assert "if (!out || !env || env === 'loading' || env.__error) return;" not in body
        for phrase in ("Nothing was requested", "Still reading", "failed to read", "No facts on this envelope"):
            assert phrase in body, f"missing sentence: {phrase}"

    def test_three_writers_one_slot_one_ticket(self):
        app = _app()
        assert "let railTicket = 0;" in app
        members = app[app.index("async function openMembers("):app.index("async function openMembers(") + 1400]
        assert "const ticket = railClaim();" in members
        assert members.count("railStale(ticket)") >= 2, "a stale ticket must stand down on both the error and success paths"
        for fn in ("function showEvidence(", "function renderEnrichmentEvidence("):
            assert "railClaim();" in app[app.index(fn):app.index(fn) + 900]

    def test_the_frame_names_what_and_for_what(self):
        app = _app()
        assert "function railFrame(kind, forWhat, bodyHtml" in app
        members = app[app.index("async function openMembers("):app.index("async function openMembers(") + 3000]
        assert "for <span class=\"font-mono\">${esc(slug)}</span>" in members


class TestTheCandidateHeuristicIsGone:
    def test_no_button_counts_answer_lines(self):
        app = _app()
        assert "function listCandidates(" not in app and "function showCandidates(" not in app
        assert "Open as candidates" not in re.sub(r"/\*.*?\*/|^\s*//.*$|^\s*\*.*$", "", app, flags=re.S | re.M)
        assert "l.length < 80" not in app

    def test_a_list_answer_opens_the_member_tree_it_was_answered_from(self):
        app = _app()
        assert "function listSources(body)" in app
        assert "p.role === 'evidence' && MEMBER_LISTED.has(p.key)" in app
        assert "data-list-source" in app and "openMembers({ slug, analysisId: b.dataset.listSource" in app
        assert "if (turn.listSources && turn.listSources.length) return 'list';" in app
