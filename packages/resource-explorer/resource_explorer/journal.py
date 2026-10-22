"""The journal: why a resource matters, written to be read by someone else.

Everything else RE holds about a resource is written to be CORRECT — a
measurement, a verdict, a field with an author. A journal entry is written
to be READ: prose, dated, addressed to someone. Curation is not only getting
the record right; it is advocacy, and a curator who catalogues a resource
accurately and tells nobody has done half the job.

Three properties follow, and each is a relief:

* **Append-only.** An entry is a statement someone made on a date. Later
  events do not invalidate it — they get a later entry. So it sits outside
  the durable/perishable split entirely: no review flags, nothing to
  reconcile, never overwritten.
* **It has an audience, and the product already knows who.** Suggesting a
  resource is a routing question, and perspectives answer it — a note on a
  data-heavy repo is for Data Experts and Consumers, the same tags on every
  question row. So suggestion is "pick a perspective, or pick a person",
  not a share dialogue.
* **A suggestion arrives as a work-list entry, not a notification.** Work
  lists already exist, carry counts, and survive being ignored for a
  fortnight; a notification is a thing you dismiss. One list per audience —
  "Suggested to Data Expert" — the resource as a member, the entry as its
  rationale. The same promote mechanism the sub-resources and selections
  already use.

What this deliberately does not do: block cataloguing on an entry. Advocacy
written to satisfy a required field produces "useful library" on two
hundred assets. The empty state is visible instead — catalogued, never
written about — which a corpus view can count.

The author is stamped by the caller from the signed-in identity; this
module never takes one on trust from a payload.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from resource_explorer.registry import ProjectRegistry
from resource_explorer.work_lists import WorkLists

SUGGESTION_PREFIX = "suggested-to-"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# The resource_journal table is created by ProjectRegistry._init_schema (a migration), not here.


def audience_slug(target: str) -> str:
    """`Data Expert` -> `suggested-to-data-expert`; `peterprofile` ->
    `suggested-to-peterprofile`. One work list per audience, found by slug."""
    return SUGGESTION_PREFIX + re.sub(r"[^a-z0-9]+", "-", target.strip().lower()).strip("-")


def _pack_extras(targets: list[str], turn: dict | None, note: str) -> str:
    """The `suggested_to` column's JSON. A hand-written entry keeps the plain list it always had; an entry made from
    a chat turn stores an object, so the turn's evidence and the person's optional note ride in the same row under
    their own keys, apart from the derived `body`. (The column is TEXT JSON, so this needs no DDL.)"""
    if turn is None and not note:
        return json.dumps(targets)
    return json.dumps({"suggested_to": targets, "turn": turn, "note": note or ""})


def _unpack_extras(raw) -> tuple[list[str], dict | None, str]:
    try:
        v = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return [], None, ""
    if isinstance(v, dict):
        targets = v.get("suggested_to") or []
        return (targets if isinstance(targets, list) else []), v.get("turn"), v.get("note") or ""
    return (v if isinstance(v, list) else []), None, ""


class Journal:
    def __init__(self, registry: ProjectRegistry | None = None):
        self.registry = registry or ProjectRegistry()

    def _conn(self):
        return self.registry._conn()

    def entries(self, entity_type: str, entity_slug: str) -> list[dict]:
        """Newest first. Every entry ever written; there is no delete."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, author, written_at, body, suggested_to, compile_id FROM resource_journal "
                "WHERE entity_type = ? AND entity_slug = ? ORDER BY written_at DESC",
                (entity_type, entity_slug),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r) if not isinstance(r, dict) else r
            targets, turn, note = _unpack_extras(d.get("suggested_to"))
            d["suggested_to"] = targets
            # Only a turn entry carries these; a hand-written entry has neither key.
            if turn is not None:
                d["turn"] = turn
            if note:
                d["note"] = note
            out.append(d)
        return out

    def write(self, entity_type: str, entity_slug: str, *, author: str, body: str,
              suggest_to: list[str] | None = None, compile_id: str | None = None,
              turn: dict | None = None, note: str | None = None) -> dict:
        """Append one entry, and route it. Returns the entry plus the work
        lists the suggestion landed in, so the UI can say where it went
        rather than "sent"."""
        if not author:
            raise ValueError("a journal entry needs an author")
        body = (body or "").strip()
        if not body:
            raise ValueError("a journal entry needs a body")
        targets = [t.strip() for t in (suggest_to or []) if t and t.strip()]
        compile_id = (compile_id or "").strip() or None
        note = (note or "").strip()
        entry_id = uuid.uuid4().hex
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO resource_journal (id, entity_type, entity_slug, author, written_at, body, suggested_to, compile_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (entry_id, entity_type, entity_slug, author, now, body, _pack_extras(targets, turn, note), compile_id),
            )
        landed = [self._route(target, entity_type, entity_slug, author, body) for target in targets]
        out = {"id": entry_id, "author": author, "written_at": now, "body": body,
               "suggested_to": targets, "compile_id": compile_id, "work_lists": landed}
        if turn is not None:
            out["turn"] = turn
        if note:
            out["note"] = note
        return out

    def _route(self, target: str, entity_type: str, entity_slug: str, author: str, body: str) -> dict:
        """One work list per audience, created on first use; the resource
        joins it with the entry as its rationale. A second suggestion of the
        same resource to the same audience updates the rationale rather than
        adding a second row — set_member upserts."""
        wl = WorkLists(self.registry)
        slug = audience_slug(target)
        name = f"Suggested to {target}"
        existing = wl.get(slug)
        if existing is None:
            wl.create(name, [entity_slug], slug=slug, entity_type=entity_type,
                      created_by=author, derived_from="journal",
                      description="Resources someone wrote about and suggested to this audience. "
                                  "Each member's rationale is their journal entry.",
                      rationale=body)
        else:
            wl.set_member(slug, entity_slug, rationale=body)
            name = (existing.get("display_name") if isinstance(existing, dict)
                    else getattr(existing, "display_name", None)) or name
        # The NAME is where it landed; the slug is how the server finds it.
        return {"target": target, "work_list": slug, "name": name}

    def suggested_targets(self, entity_type: str, entity_slug: str) -> list[str]:
        """Everyone this resource has ever been suggested to."""
        seen: list[str] = []
        for e in self.entries(entity_type, entity_slug):
            for t in e.get("suggested_to") or []:
                if t not in seen:
                    seen.append(t)
        return seen


# ── the entry IS the chat turn ──────────────────────────────────────────────────────────────────────────────
# The journal entry is derived from the turn alone: the question as typed, the answer as shown, the evidence the
# compile packed, its as-of and confidence words, and the scope. The person adds a confirmation and, optionally,
# one free-text note kept apart from the derived text. The pane's per-turn control and the chat's `write_journal`
# tool both end in `write_turn_entry`, so they cannot write different rows for the same turn.

NO_INVESTIGATION = "no investigation is open · choose one on the rail"
PROPOSAL_WORDS = "Add this turn to the investigation journal? [Add] [Not now]"
NO_EARLIER_ANSWER = "There is no earlier answer in this chat to add."
SIGN_IN_WORDS = "Sign in to write in the journal — an entry needs an author."


def _evidence_of(compile_row: dict | None) -> tuple[list[str], str | None, str]:
    """(evidence keys, as-of, confidence words) read from a stored compile, never guessed. A turn with no compile
    says so in the confidence words; an as-of nobody recorded is None, which the body renders as "not recorded"."""
    if not compile_row:
        return [], None, "no compile recorded, so confidence is not established"
    manifest = compile_row.get("manifest") or {}
    packed = [p for p in (manifest.get("packed") or []) if isinstance(p, dict)]
    keys: list[str] = []
    for p in packed:
        if p.get("key") and p["key"] not in keys:
            keys.append(p["key"])
    as_ofs = [(p.get("pointer") or {}).get("as_of") for p in packed]
    as_of = max((a for a in as_ofs if a), default=None)
    gaps = [g.get("key") for g in (manifest.get("gaps") or []) if isinstance(g, dict) and g.get("key")]
    if (manifest.get("coverage") or {}).get("kind") == "none":
        confidence = "no stored analysis answers this question"
    else:
        confidence = f"answered from {len(keys)} stored result{'' if len(keys) == 1 else 's'}"
        if gaps:
            confidence += f"; {len(gaps)} not measured ({', '.join(gaps)})"
    return keys, as_of, confidence


def derive_turn_entry(registry, *, question: str, answer: str, compile_id: str | None,
                      investigation: str, resource_slug: str | None) -> dict:
    """The derived entry for one chat turn: {"body", "turn"}. Pure of the person's say-so: the same turn always
    derives the same body, which is what lets two write paths agree."""
    compile_id = (compile_id or "").strip() or None
    row = None
    if compile_id:
        try:
            row = registry.get_compile(compile_id)
        except Exception:
            row = None
    keys, as_of, confidence = _evidence_of(row)
    if compile_id and row is None:
        confidence = f"compile {compile_id[:8]} is not on file, so confidence is not established"
    scope = f"investigation {investigation}" + (f" · resource {resource_slug}" if resource_slug else "")
    body = "\n".join([
        "Per chat",
        "",
        f"Question: {(question or '').strip()}",
        "",
        "Answer:",
        "",
        (answer or "").strip(),
        "",
        f"- Scope: {scope}",
        f"- As of: {as_of or 'not recorded'}",
        f"- Confidence: {confidence}",
        f"- Evidence: {', '.join(keys) if keys else 'none recorded'}",
        f"- Compile: {compile_id[:8] if compile_id else 'none recorded'}",
    ])
    turn = {"question": (question or "").strip(), "resource_slug": resource_slug or None, "evidence": keys,
            "as_of": as_of, "confidence": confidence}
    return {"body": body, "turn": turn}


def write_turn_entry(registry, *, investigation: str, author: str, question: str, answer: str,
                     compile_id: str | None, resource_slug: str | None, note: str | None = None) -> dict:
    """The one write for a chat-turn entry. Called by the route behind the pane's control and by the chat tool."""
    if not (investigation or "").strip():
        raise ValueError(NO_INVESTIGATION)
    if not (answer or "").strip():
        raise ValueError(NO_EARLIER_ANSWER)
    derived = derive_turn_entry(registry, question=question, answer=answer, compile_id=compile_id,
                                investigation=investigation, resource_slug=resource_slug)
    return Journal(registry).write("investigation", investigation, author=author, body=derived["body"],
                                   compile_id=compile_id, turn=derived["turn"], note=note)
