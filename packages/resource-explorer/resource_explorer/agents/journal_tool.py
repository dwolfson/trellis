"""The chat's journal tool: add the LAST chat turn to the open investigation's journal.

Same confirm pattern as ``create_rfa_from_finding`` (agents/rfa_tools.py): ``confirm=False`` writes nothing and
returns the question to put to the person; ``confirm=True`` writes. The write is ``journal.write_turn_entry``,
the same function the pane's per-turn control reaches through ``POST /api/journal/investigation/{slug}/turn``,
so the two paths cannot produce different rows for the same turn.

The entry is derived from the turn, never from what the model says about it: "this" is the last exchange of the
session, read from the stored conversation, so the tool takes no question or answer argument a small model could
paraphrase. Only the in-app chat gets this tool (``BaseExplorerAgent.allow_writes``); the A2A surface is read-only.
"""
from __future__ import annotations

import re
from contextvars import ContextVar

from beeai_framework.tools import tool

from resource_explorer.journal import (
    NO_EARLIER_ANSWER, NO_INVESTIGATION, PROPOSAL_WORDS, SIGN_IN_WORDS, write_turn_entry,
)

#: A request for the journal: "save this to the journal", "add that to the investigation journal", "put it in
#: the journal", and "note this". The pane has a control for the verb, so the chat must act on it and never
#: answer that it does not know (docs/design-notes: verbs for unmapped controls).
JOURNAL_VERB = re.compile(
    r"\b(?:save|add|put|write|record|log|file|store|keep|enter)\b[^.?!]{0,60}\bjournal\b"
    r"|^\s*(?:please\s+)?note\s+(?:this|that|it)\b",
    re.IGNORECASE,
)

#: What the chat says after the write, and the words a stored exchange carries when it was only a journal
#: exchange; `last_turn` skips these so "this" never resolves to the proposal itself.
SAVED_WORDS = "Added to the investigation journal."
_SERVICE_ANSWERS = (PROPOSAL_WORDS, SAVED_WORDS, NO_EARLIER_ANSWER, SIGN_IN_WORDS, NO_INVESTIGATION)

#: Where the tool finds the session and the open investigation. Set by the conversation agent at the start of a
#: turn; a ContextVar rather than a tool argument because the model must not choose either.
_context: ContextVar[dict] = ContextVar("_journal_context", default={})
#: The proposals made this turn. A list, not a value: BeeAI runs tools in child tasks whose own `set` would not
#: reach the caller, but an append to this one list does (same shape as tools._turn_facts).
_proposals: ContextVar[list | None] = ContextVar("_journal_proposals", default=None)


def set_journal_context(session_id: str | None, investigation: str | None) -> None:
    _context.set({"session_id": session_id or "", "investigation": (investigation or "").strip()})
    _proposals.set([])


def turn_proposal() -> dict | None:
    """The proposal made this turn (what the pane draws [Add] [Not now] for), or None."""
    made = _proposals.get()
    return made[-1] if made else None


def is_journal_request(query: str) -> bool:
    return bool(JOURNAL_VERB.search(query or ""))


def last_turn(registry, session_id: str) -> dict | None:
    """The last question/answer pair of the session that was not itself a journal exchange."""
    if not session_id:
        return None
    for ex in registry.load_exchanges(session_id):
        if (ex.get("answer") or "").strip() in _SERVICE_ANSWERS or is_journal_request(ex.get("question") or ""):
            continue
        return ex
    return None


def write_journal_raw(confirm: bool = False, note: str = "", *, registry=None, author: str | None = None) -> str:
    from resource_explorer.registry import ProjectRegistry, current_user_id

    ctx = _context.get()
    investigation = ctx.get("investigation") or ""
    if not investigation:
        return NO_INVESTIGATION
    registry = registry or ProjectRegistry()
    ex = last_turn(registry, ctx.get("session_id") or "")
    if ex is None:
        return NO_EARLIER_ANSWER
    if not confirm:
        made = _proposals.get()
        if made is not None:
            made.append({"investigation": investigation, "question": ex["question"], "answer": ex["answer"],
                         "compile_id": ex.get("compile_id"), "resource_slug": ex.get("resource_slug")})
        return PROPOSAL_WORDS
    who = current_user_id() if author is None else author
    if not who:
        return SIGN_IN_WORDS
    write_turn_entry(registry, investigation=investigation, author=who, question=ex["question"],
                     answer=ex["answer"], compile_id=ex.get("compile_id"), resource_slug=ex.get("resource_slug"),
                     note=note)
    return SAVED_WORDS


@tool(
    description=(
        "Add the LAST chat turn (the question just answered and its answer, with the evidence it cited) to the "
        "open investigation's journal. Use it when the person asks to save, add, put or note this/that in the "
        "journal; never answer that you cannot. The entry is derived from the stored turn, so you pass no text. "
        "Two-step: with confirm=false (the default) nothing is written and you get the question to put to the "
        "person; call again with confirm=true only after they agree. note is the person's own optional words, "
        "kept apart from the entry."
    )
)
def write_journal(confirm: bool = False, note: str = "") -> str:
    return write_journal_raw(confirm=confirm, note=note)
