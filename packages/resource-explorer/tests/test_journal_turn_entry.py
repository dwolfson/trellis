"""The journal entry IS the chat turn: derived from the turn alone, one write function behind both paths.

Covers the derivation, the chat's confirm-gated `write_journal` tool, the pane's route, and that the tool and the
route write the SAME row for the same turn. No live calls: a sqlite registry and fakes that bind real signatures.
"""
from __future__ import annotations

import inspect
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from resource_explorer.agents import journal_tool
from resource_explorer.journal import (
    NO_EARLIER_ANSWER, NO_INVESTIGATION, PROPOSAL_WORDS, Journal, derive_turn_entry, write_turn_entry,
)
from resource_explorer.registry import Project, ProjectRegistry

QUESTION = "Who are the main contributors to docling_core?"
ANSWER = "| author | commits |\n|---|---|\n| alice | 120 |\n| bob | 80 |"
MANIFEST = {
    "compile_id": "abcdef1234567890",
    "packed": [
        {"key": "contributor_stats", "role": "evidence", "rung": "FULL", "size": 10,
         "pointer": {"resource_slug": "docling_core", "view": "v", "as_of": "2026-10-20T08:00:00+00:00"}},
        {"key": "commit_activity", "role": "evidence", "rung": "SUMMARY", "size": 5,
         "pointer": {"resource_slug": "docling_core", "view": "v", "as_of": "2026-10-18T08:00:00+00:00"}},
    ],
    "gaps": [{"key": "bus_factor", "reason": "never run"}],
    "coverage": {"kind": "analysis"},
}


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="docling_core", display_name="docling_core", github_url="https://github.com/x/d", description=""))
    r.record_compile("abcdef1234567890", "docling_core", QUESTION, MANIFEST, [], session_id="s1", user_id="alice")
    return r


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    monkeypatch.setattr("resource_explorer.registry.current_user_id", lambda: "peterprofile")


@pytest.fixture
def investigation(registry):
    return registry.create_investigation("Contributors study")["slug"]


def _exchange(registry, session="s1", q=QUESTION, a=ANSWER, compile_id="abcdef1234567890"):
    registry.append_turn(session, "user", q, "docling_core", user_id="peterprofile", compile_id=compile_id)
    registry.append_turn(session, "assistant", a, "docling_core", user_id="peterprofile", compile_id=compile_id)


class TestDerivation:
    def test_the_body_is_the_turn_and_carries_the_evidence_ids(self, registry):
        d = derive_turn_entry(registry, question=QUESTION, answer=ANSWER, compile_id="abcdef1234567890",
                              investigation="study", resource_slug="docling_core")
        assert d["body"] == "\n".join([
            "Per chat", "", f"Question: {QUESTION}", "", "Answer:", "", ANSWER, "",
            "- Scope: investigation study · resource docling_core",
            "- As of: 2026-10-20T08:00:00+00:00",
            "- Confidence: answered from 2 stored results; 1 not measured (bus_factor)",
            "- Evidence: contributor_stats, commit_activity",
            "- Compile: abcdef12",
        ])
        assert d["turn"]["evidence"] == ["contributor_stats", "commit_activity"]

    def test_the_same_turn_always_derives_the_same_body(self, registry):
        kw = dict(question=QUESTION, answer=ANSWER, compile_id="abcdef1234567890", investigation="s", resource_slug="d")
        assert derive_turn_entry(registry, **kw) == derive_turn_entry(registry, **kw)

    def test_no_compile_is_said_not_read_as_confident(self, registry):
        d = derive_turn_entry(registry, question="q", answer="a", compile_id=None, investigation="s", resource_slug=None)
        assert "- Confidence: no compile recorded, so confidence is not established" in d["body"]
        assert "- As of: not recorded" in d["body"] and "- Evidence: none recorded" in d["body"]
        assert "resource" not in d["body"].split("- Scope:")[1].split("\n")[0]

    def test_a_compile_that_is_not_on_file_is_said(self, registry):
        d = derive_turn_entry(registry, question="q", answer="a", compile_id="deadbeef00", investigation="s", resource_slug="x")
        assert "compile deadbeef is not on file" in d["body"]

    def test_the_note_is_stored_apart_from_the_derived_text(self, registry, investigation):
        out = write_turn_entry(registry, investigation=investigation, author="alice", question=QUESTION, answer=ANSWER,
                               compile_id="abcdef1234567890", resource_slug="docling_core", note="check bob's bot account")
        row = Journal(registry).entries("investigation", investigation)[0]
        assert row["note"] == "check bob's bot account" and "bot account" not in row["body"]
        assert row["turn"]["evidence"] == ["contributor_stats", "commit_activity"]
        assert row["suggested_to"] == [] and row["compile_id"] == "abcdef1234567890"
        assert out["note"] == row["note"]

    def test_a_hand_written_entry_keeps_its_plain_list(self, registry):
        Journal(registry).write("repo", "docling_core", author="a", body="hand", suggest_to=["Steward"])
        row = Journal(registry).entries("repo", "docling_core")[0]
        assert row["suggested_to"] == ["Steward"] and "note" not in row and "turn" not in row


class TestTool:
    def _ctx(self, session="s1", inv=None):
        journal_tool.set_journal_context(session, inv)

    def test_confirm_false_asks_in_the_exact_words_and_writes_nothing(self, registry, investigation):
        _exchange(registry)
        self._ctx(inv=investigation)
        assert journal_tool.write_journal_raw(confirm=False, registry=registry) == \
            "Add this turn to the investigation journal? [Add] [Not now]"
        assert Journal(registry).entries("investigation", investigation) == []
        prop = journal_tool.turn_proposal()
        assert prop["question"] == QUESTION and prop["answer"] == ANSWER and prop["investigation"] == investigation

    def test_confirm_true_writes_one_row_authored_by_the_signed_in_user(self, registry, investigation, monkeypatch):
        _exchange(registry)
        self._ctx(inv=investigation)
        monkeypatch.setattr("resource_explorer.registry.current_user_id", lambda: "peterprofile")
        assert journal_tool.write_journal_raw(confirm=True, note="n", registry=registry) == "Added to the investigation journal."
        rows = Journal(registry).entries("investigation", investigation)
        assert len(rows) == 1
        assert rows[0]["author"] == "peterprofile" and rows[0]["compile_id"] == "abcdef1234567890"
        assert rows[0]["note"] == "n"

    def test_anonymous_is_refused_and_nothing_is_written(self, registry, investigation):
        _exchange(registry)
        self._ctx(inv=investigation)
        assert journal_tool.write_journal_raw(confirm=True, registry=registry, author="").startswith("Sign in")
        assert Journal(registry).entries("investigation", investigation) == []

    def test_this_is_the_last_turn_never_the_proposal_or_the_request(self, registry, investigation):
        _exchange(registry, q="older question", a="older answer", compile_id=None)
        _exchange(registry)
        # the journal exchange itself, as persisted after the proposal
        _exchange(registry, q="save this to the journal", a=PROPOSAL_WORDS, compile_id=None)
        self._ctx(inv=investigation)
        journal_tool.write_journal_raw(confirm=True, registry=registry, author="u")
        body = Journal(registry).entries("investigation", investigation)[0]["body"]
        assert f"Question: {QUESTION}" in body and "older question" not in body and "save this" not in body

    def test_no_investigation_says_so_and_writes_nothing(self, registry):
        _exchange(registry)
        self._ctx(inv=None)
        for confirm in (False, True):
            assert journal_tool.write_journal_raw(confirm=confirm, registry=registry) == \
                "no investigation is open · choose one on the rail"
        assert NO_INVESTIGATION == "no investigation is open · choose one on the rail"

    def test_no_earlier_answer_says_so(self, registry, investigation):
        self._ctx(inv=investigation)
        assert journal_tool.write_journal_raw(confirm=False, registry=registry) == NO_EARLIER_ANSWER

    @pytest.mark.parametrize("q", ["save this to the journal", "Add that to the investigation journal", "put it in the journal",
                                   "please note this", "note that", "Can you save this answer to my journal?"])
    def test_journal_verbs_route_to_the_tool(self, q):
        assert journal_tool.is_journal_request(q)

    @pytest.mark.parametrize("q", ["Who wrote the journal module?", "note the dependency counts", "what changed last week"])
    def test_other_questions_do_not(self, q):
        assert not journal_tool.is_journal_request(q)

    def test_the_tool_binds_the_real_signature(self):
        assert list(inspect.signature(journal_tool.write_journal_raw).parameters)[:2] == ["confirm", "note"]
        mock.create_autospec(journal_tool.write_journal_raw, spec_set=True)(confirm=False, note="")


class TestConversationAgentRouting:
    def test_save_this_to_the_journal_goes_to_the_tool_not_the_model(self, registry, investigation):
        from resource_explorer.agents.conversation_agent import ConversationAgent

        _exchange(registry)
        agent = ConversationAgent.__new__(ConversationAgent)
        agent.session_id, agent.investigation = "s1", investigation
        agent._last_compiled = None
        agent._run_persistent = mock.Mock(side_effect=AssertionError("the model must not be asked"))
        with mock.patch("resource_explorer.registry.ProjectRegistry", return_value=registry):
            words = agent.handle("save this to the journal")
        assert words == "Add this turn to the investigation journal? [Add] [Not now]"
        assert agent._journal_proposal["investigation"] == investigation

    def test_the_a2a_agent_without_writes_is_not_routed(self):
        from resource_explorer.agents.conversation_agent import ConversationAgent

        a = ConversationAgent.__new__(ConversationAgent)
        a.allow_writes = False
        assert "write_journal" not in [getattr(t, "name", "") for t in a._write_tools()]


class TestRouteAndToolWriteTheSameRow:
    @pytest.fixture
    def client(self, registry, monkeypatch):
        monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                            lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
        monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
        monkeypatch.setattr("resource_explorer.web.routes.journal.get_current_user",
                            lambda request: {"user_id": "peterprofile"})
        monkeypatch.setattr("resource_explorer.registry.current_user_id", lambda: "peterprofile")
        from resource_explorer.web.app import app
        return TestClient(app)

    def test_preview_derives_and_writes_nothing(self, client, registry, investigation):
        r = client.post(f"/api/journal/investigation/{investigation}/turn",
                        json={"question": QUESTION, "answer": ANSWER, "compile_id": "abcdef1234567890", "resource_slug": "docling_core"})
        assert r.status_code == 200 and r.json()["written"] is False
        assert f"Question: {QUESTION}" in r.json()["body"]
        assert Journal(registry).entries("investigation", investigation) == []

    def test_the_route_and_the_tool_write_identical_rows(self, client, registry, investigation):
        _exchange(registry)
        r = client.post(f"/api/journal/investigation/{investigation}/turn", json={
            "question": QUESTION, "answer": ANSWER, "compile_id": "abcdef1234567890", "resource_slug": "docling_core",
            "note": "same note", "confirm": True})
        assert r.status_code == 200 and r.json()["written"] is True
        journal_tool.set_journal_context("s1", investigation)
        journal_tool.write_journal_raw(confirm=True, note="same note", registry=registry)
        a, b = Journal(registry).entries("investigation", investigation)
        for key in ("author", "body", "compile_id", "suggested_to", "turn", "note"):
            assert a[key] == b[key], key
        assert a["id"] != b["id"] and a["author"] == "peterprofile"

    def test_anonymous_is_refused_unknown_investigation_is_404(self, client, monkeypatch, investigation):
        body = {"question": "q", "answer": "a", "confirm": True}
        assert client.post("/api/journal/investigation/nope/turn", json=body).status_code == 404
        monkeypatch.setattr("resource_explorer.web.routes.journal.get_current_user", lambda request: None)
        assert client.post(f"/api/journal/investigation/{investigation}/turn", json=body).status_code == 401
        assert client.post(f"/api/journal/investigation/{investigation}/turn", json={**body, "answer": " "}).status_code == 422
