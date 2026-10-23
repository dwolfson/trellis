"""The Egeria side of the 2026-10-22 questions edit (#842): update the "User Questions" terms in place.

Why not re-run `docs/dr-egeria/questions/scouting-questions.md`: it is a CREATE document keyed on display name.
Re-running it duplicates the multi-link perspective and ScopedBy links, creates a NEW term for every reworded
question, and leaves the retired and merged terms untouched. This script writes a separate document that only
changes what differs between the CSV and what Egeria holds.

Two subcommands, one plan function:

* ``inventory`` (READ-ONLY): pages the glossary's terms and writes JSON: GUID, qualifiedName, displayName,
  description, summary, usage, contentStatus, the ``question_id`` additional property (MISSING on terms authored
  before 2026-10-13 unless a later batch set it), and each term's ScopedBy links (perspectives and funnel stages)
  and ReplacementTerm links. It calls only ``get_glossaries_by_name``, ``find_glossary_terms`` and
  ``get_all_related_elements``; a test runs it against fakes whose every write method raises.

* ``plan --inventory <json> --out <md>``: joins each CSV row to a term by ``question_id``; a term without one is
  joined by the row's display name in the pre-edit CSV (d7a395a4), and the same Update sets its ``question_id``.
  ``build_plan`` returns one Plan object; the printed counts and the rendered document both come from it.

  - an active row whose term differs (display name, description, summary, usage, or no ``question_id``):
    ``Update Glossary Term`` located by the term's qualifiedName. Links the term already has are never re-added;
    a perspective or funnel-stage link the CSV names and the inventory lacks is added.
  - a new row with no term: Create + Classify as Question + each perspective link + each ScopedBy link.
  - a retired or merged row: Update with Status DEPRECATED and the CSV Status text as a description prefix;
    a merged term also gets a ReplacementTerm link (absorbed term = Term 1, survivor = Term 2), omitted when the
    inventory shows it. Every existing link on a deprecated term is kept: nothing here deletes a relationship.
  - a row the plan cannot place (no term by either path, two terms for one id or name, one term claimed by two
    rows, a survivor that is missing) is listed, no document is written and ``plan`` exits 1.

  An inventory taken after a successful apply gives a plan with no commands (tested).

The coordinator runs both subcommands; a builder never runs either against a live platform:

    .venv/bin/python packages/resource-explorer/scripts/question_term_update_batch.py inventory \\
        --out <inventory.json>
    .venv/bin/python packages/resource-explorer/scripts/question_term_update_batch.py plan \\
        --inventory <inventory.json> --out <update-batch.md>

Exit codes: 0 done; 1 the plan has rows it cannot place, or the inventory has read errors; 2 bad input or
Egeria could not be read at all (unreachable is never reported as "no terms").
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

_THIS_DIR = Path(__file__).resolve().parent
_PKG_DIR = _THIS_DIR.parent
_REPO_ROOT = _PKG_DIR.parent.parent
if __package__ in (None, ""):  # running as a script, not imported as a module
    sys.path.insert(0, str(_PKG_DIR))
from resource_explorer.question_status import is_skipped_status  # noqa: E402

CSV_PATH = _PKG_DIR / "docs" / "dr-egeria" / "resource_questions.csv"
#: The last main commit before #842 edited the CSV: its Question column is the display name every pre-edit term has.
PRE_EDIT_SHA = "d7a395a4"
PRE_EDIT_CSV_IN_REPO = "packages/resource-explorer/docs/dr-egeria/resource_questions.csv"
QUESTIONS_GLOSSARY = "User Questions"
INVENTORY_SCHEMA = "question-term-inventory/1"
DEPRECATED = "DEPRECATED"
PERSPECTIVE_QN_PREFIX = "Perspective::"
SCOPED_BY = "ScopedBy"
REPLACEMENT_TERM = "ReplacementTerm"
#: The only pyegeria methods `inventory` may call. Anything else on these clients is a write or a read this
#: script does not need.
INVENTORY_READ_METHODS = ("get_glossaries_by_name", "find_glossary_terms", "get_all_related_elements")
_MERGED_RX = re.compile(r"^\s*merged into\s+(Q-\d{4})\b", re.IGNORECASE)


def _load_generator():
    """csv_to_dr_egeria_questions.py by path (scripts/ is not a package): the description, summary, usage and
    Additional Properties text of a term come from the same functions the create document uses, so an Update here
    cannot disagree with what that document would author."""
    spec = importlib.util.spec_from_file_location("_csv_to_dr_egeria_questions", _THIS_DIR / "csv_to_dr_egeria_questions.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_gen = _load_generator()


# ---------------------------------------------------------------------------
# inventory (read-only)
# ---------------------------------------------------------------------------

class InventoryReadError(RuntimeError):
    """Egeria's answer could not be read as an answer. Never turned into "no terms"."""


def _no_elements(answer: Any) -> bool:
    return isinstance(answer, str) and " ".join(answer.split()).lower().rstrip(".") == "no elements found"


def _elements(answer: Any, what: str) -> list[dict]:
    """pyegeria's list answer, or [] for its exact "No elements found". None, another string or another type is a
    read failure (pyegeria's dynamic_catch can hand back None), never an empty result."""
    if _no_elements(answer):
        return []
    if isinstance(answer, list):
        return [e for e in answer if isinstance(e, dict)]
    if isinstance(answer, dict):
        if "elementList" in answer:
            return [e for e in (answer.get("elementList") or []) if isinstance(e, dict)]
        return [answer]
    shown = answer[:200] if isinstance(answer, str) else type(answer).__name__
    raise InventoryReadError(f"{what}: Egeria answered {shown!r}")


def _header(element: dict) -> dict:
    return element.get("elementHeader") or {}


def _props(element: dict) -> dict:
    return element.get("properties") or element.get("glossaryTermProperties") or {}


def _classifications(element: dict) -> list[dict]:
    """Every classification in the header, wherever this pyegeria/Egeria version files it (a named key such as
    `anchor`, or the `classifications`/`otherClassifications` lists)."""
    out = []
    for value in _header(element).values():
        items = value if isinstance(value, list) else [value]
        out.extend(c for c in items if isinstance(c, dict) and c.get("classificationName"))
    return out


def _anchor_scope_guid(element: dict) -> Optional[str]:
    for c in _classifications(element):
        if c.get("classificationName") == "Anchors":
            guid = (c.get("classificationProperties") or {}).get("anchorScopeGUID")
            if guid:
                return str(guid)
    return None


def _generic_prop(element: dict, name: str) -> str:
    """A property of an OpenMetadataStore element (`get_all_related_elements`' shape)."""
    props = (element or {}).get("elementProperties") or {}
    value = (props.get("propertiesAsStrings") or {}).get(name)
    if value is None:
        entry = (props.get("propertyValueMap") or {}).get(name) or {}
        value = entry.get("primitiveValue") if isinstance(entry, dict) else None
    return str(value or "")


def links_from_related(answer: Any, what: str) -> list[dict]:
    """Pure: the ScopedBy and ReplacementTerm links in one `get_all_related_elements(guid, graph_query_depth=1)`
    answer. `other_at_end1` is Egeria's `elementAtEnd1` for the OTHER element."""
    out = []
    for entry in _elements(answer, what):
        rtype = (entry.get("type") or {}).get("typeName")
        if rtype not in (SCOPED_BY, REPLACEMENT_TERM):
            continue
        other = entry.get("element") or {}
        out.append({
            "relationship": rtype,
            "relationship_guid": str(entry.get("relationshipGUID") or ""),
            "other_at_end1": bool(entry.get("elementAtEnd1")),
            "guid": str(other.get("elementGUID") or ""),
            "type": str((other.get("type") or {}).get("typeName") or ""),
            "qualified_name": _generic_prop(other, "qualifiedName"),
            "display_name": _generic_prop(other, "displayName"),
        })
    return out


def _term_record(element: dict) -> dict:
    props = _props(element)
    additional = props.get("additionalProperties") or {}
    qid = additional.get("question_id") if isinstance(additional, dict) else None
    return {
        "guid": str(_header(element).get("guid") or ""),
        "qualified_name": str(props.get("qualifiedName") or ""),
        "display_name": str(props.get("displayName") or ""),
        "description": str(props.get("description") or ""),
        "summary": str(props.get("summary") or ""),
        "usage": str(props.get("usage") or ""),
        "content_status": str(props.get("contentStatus") or ""),
        "element_status": str(_header(element).get("status") or ""),
        "question_id": (str(qid).strip() or None) if qid is not None else None,
        "classifications": sorted({c["classificationName"] for c in _classifications(element)}),
        "links": [],
    }


def _paged(call, what: str, page_size: int, max_pages: int = 500) -> list[dict]:
    out: list[dict] = []
    for page in range(max_pages):
        batch = _elements(call(start_from=page * page_size, page_size=page_size), what)
        out.extend(batch)
        if len(batch) < page_size:
            return out
    raise InventoryReadError(f"{what}: more than {max_pages} pages of {page_size}; stopped rather than guess")


def read_inventory(glossary_manager, metadata_expert, glossary_name: str = QUESTIONS_GLOSSARY, *,
                   page_size: int = 100, now: Optional[str] = None) -> dict:
    """READ-ONLY. The glossary's terms with their links. A glossary that cannot be found exactly once, or a term
    page that cannot be read, raises; a per-term link read that fails is recorded in `read_errors` (the plan
    refuses an inventory with any), never as "no links"."""
    glossaries = _elements(glossary_manager.get_glossaries_by_name(glossary_name, output_format="JSON"),
                           f"glossary {glossary_name!r}")
    exact = [g for g in glossaries if str(_props(g).get("displayName") or "") == glossary_name]
    if len(exact) != 1:
        raise InventoryReadError(f"glossary {glossary_name!r}: {len(exact)} exact matches (need 1)")
    glossary_guid = str(_header(exact[0]).get("guid") or "")
    if not glossary_guid:
        raise InventoryReadError(f"glossary {glossary_name!r}: answer carries no GUID")

    seen = _paged(lambda **kw: glossary_manager.find_glossary_terms("*", output_format="JSON", **kw),
                  "glossary terms", page_size)
    in_glossary = [e for e in seen if _anchor_scope_guid(e) == glossary_guid]
    if seen and not in_glossary:
        raise InventoryReadError(
            f"{len(seen)} terms read, none anchored to {glossary_name!r} ({glossary_guid}): the answer's shape is "
            "not the one this script reads, so it reports nothing rather than an empty glossary")

    terms, read_errors = [], []
    for element in in_glossary:
        record = _term_record(element)
        try:
            entries = _paged(lambda **kw: metadata_expert.get_all_related_elements(
                record["guid"], graph_query_depth=1, **kw), f"links of {record['guid']}", page_size)
            record["links"] = links_from_related(entries, f"links of {record['guid']}")
        except Exception as exc:  # recorded per term; the plan refuses the inventory
            read_errors.append({"guid": record["guid"], "display_name": record["display_name"],
                                "error": f"{type(exc).__name__}: {exc}"[:500]})
        terms.append(record)
    terms.sort(key=lambda t: (t["question_id"] or "~", t["display_name"]))
    return {
        "schema": INVENTORY_SCHEMA,
        "taken_at": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "glossary": {"name": glossary_name, "guid": glossary_guid},
        "terms_seen": len(seen),
        "terms": terms,
        "read_errors": read_errors,
    }


# ---------------------------------------------------------------------------
# plan (pure)
# ---------------------------------------------------------------------------

class PlanInputError(ValueError):
    """The inputs cannot be planned from at all (an inventory with read errors, a wrong schema)."""


@dataclass
class Command:
    command: str                 # "Update Glossary Term", "Link Element To Scope", ...
    fields: dict
    kind: str                    # update | create | classify | link_perspective | link_stage | deprecate | link_replacement
    question_id: str


@dataclass
class RowPlan:
    question_id: str
    question: str
    join_path: str               # question_id | old_name | not_found
    action: str = "unchanged"    # create | update | links_only | deprecate_retired | deprecate_merged | unchanged | unplaceable
    term: Optional[dict] = None
    commands: list = field(default_factory=list)
    changed_fields: list = field(default_factory=list)
    reason: str = ""


@dataclass
class Plan:
    rows: list
    inventory_taken_at: str
    unknown_terms: list = field(default_factory=list)   # glossary terms no CSV row joined to (left alone)
    stale_links: list = field(default_factory=list)     # links the CSV no longer names (kept: no deletes)

    @property
    def unplaceable(self) -> list:
        return [r for r in self.rows if r.action == "unplaceable"]

    def commands(self) -> list:
        """The document's commands, in its order: creates (a survivor exists before a ReplacementTerm names it),
        then active-term updates and link adds, then deprecations."""
        order = {"create": 0, "update": 1, "links_only": 1, "deprecate_retired": 2, "deprecate_merged": 2}
        rows = sorted((r for r in self.rows if r.action in order), key=lambda r: order[r.action])
        return [c for r in rows for c in r.commands]

    def counts(self) -> dict:
        def tally(values: Iterable[str]) -> dict:
            out: dict = {}
            for v in values:
                out[v] = out.get(v, 0) + 1
            return dict(sorted(out.items()))
        cmds = self.commands()
        return {
            "rows": len(self.rows),
            "join_path": tally(r.join_path for r in self.rows),
            "action": tally(r.action for r in self.rows),
            "command_kind": tally(c.kind for c in cmds),
            "command": tally(c.command for c in cmds),
            "commands_total": len(cmds),
            "unplaceable": len(self.unplaceable),
            "unknown_terms": len(self.unknown_terms),
            "stale_links_kept": len(self.stale_links),
        }


def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").split())


def _stage_tokens(row: dict) -> list[str]:
    return [t.strip() for t in (row.get("Funnel Stage") or "").split("/") if t.strip()]


def perspective_columns(fieldnames: Iterable[str]) -> list[str]:
    """Same by-elimination rule as the create generator: every column that is not a known lead column."""
    return [c for c in fieldnames if c not in _gen.REQUIRED_COLUMNS and c not in _gen.OPTIONAL_LEAD_COLUMNS]


def _term_perspectives(term: dict) -> set[str]:
    return {l["qualified_name"] for l in term.get("links", [])
            if l["relationship"] == SCOPED_BY and l["qualified_name"].startswith(PERSPECTIVE_QN_PREFIX)}


def _term_stages(term: dict) -> set[str]:
    """Funnel-stage scopes: ScopedBy to a GlossaryTerm. Matched on the other element's identity, not on the link's
    direction, because a question is never the scope of a perspective or a stage term."""
    return {l["display_name"] for l in term.get("links", [])
            if l["relationship"] == SCOPED_BY and l["type"] in ("GlossaryTerm", "")
            and not l["qualified_name"].startswith(PERSPECTIVE_QN_PREFIX) and l["display_name"]}


def _desired_text(row: dict) -> dict:
    question = (row.get("Question") or "").strip()
    rationale = row.get("Rationale/Source", "")
    return {
        "Display Name": question,
        "Description": _gen._question_description(question, rationale),
        "Summary": _gen._question_summary(row.get("Why is this important?", ""), rationale),
        "Usage": _gen._question_usage(_stage_tokens(row)),
    }


_CURRENT_KEY = {"Display Name": "display_name", "Description": "description", "Summary": "summary", "Usage": "usage"}


def _link_commands(row_plan: RowPlan, row: dict, persp_cols: list[str], ref: str, term: Optional[dict]) -> list:
    have_p = _term_perspectives(term) if term else set()
    have_s = _term_stages(term) if term else set()
    out = []
    for col in persp_cols:
        if (row.get(col) or "").strip() and f"{PERSPECTIVE_QN_PREFIX}{col}" not in have_p:
            out.append(Command("Link Perspective to Question",
                               {"Perspective Name": f"{PERSPECTIVE_QN_PREFIX}{col}", "Question Name": ref},
                               "link_perspective", row_plan.question_id))
    for token in _stage_tokens(row):
        if token not in have_s:
            out.append(Command("Link Element To Scope", {"Target Element": ref, "Scope Reference": token},
                               "link_stage", row_plan.question_id))
    return out


def build_plan(rows: list[dict], old_rows: list[dict], inventory: dict, *,
               questions_glossary: str = QUESTIONS_GLOSSARY) -> Plan:
    """THE plan. Pure: CSV rows (current), the pre-edit CSV rows, and an inventory in; one Plan out."""
    if inventory.get("schema") != INVENTORY_SCHEMA:
        raise PlanInputError(f"inventory schema {inventory.get('schema')!r}, expected {INVENTORY_SCHEMA!r}")
    if inventory.get("read_errors"):
        raise PlanInputError(f"inventory has {len(inventory['read_errors'])} read error(s); a term whose links "
                             "could not be read cannot be planned (missing is not the same as not read)")
    terms = list(inventory.get("terms") or [])
    persp_cols = perspective_columns(rows[0].keys()) if rows else []

    by_id: dict[str, list] = {}
    by_name: dict[str, list] = {}
    for t in terms:
        if t.get("question_id"):
            by_id.setdefault(t["question_id"], []).append(t)
        else:
            by_name.setdefault(_norm(t.get("display_name")), []).append(t)
    old_by_id = {(r.get("Question ID") or "").strip(): r for r in old_rows}

    # Pass 1: join every row to at most one term.
    plans: list[RowPlan] = []
    row_of: dict[str, dict] = {}
    for row in rows:
        question = (row.get("Question") or "").strip()
        qid = (row.get("Question ID") or "").strip()
        if not question or not qid:
            continue
        row_of[qid] = row
        rp = RowPlan(question_id=qid, question=question, join_path="not_found")
        id_hits = by_id.get(qid, [])
        if len(id_hits) > 1:
            rp.join_path, rp.action = "question_id", "unplaceable"
            rp.reason = f"{len(id_hits)} terms carry question_id {qid}: " + ", ".join(t["guid"] for t in id_hits)
        elif id_hits:
            rp.join_path, rp.term = "question_id", id_hits[0]
        else:
            old = old_by_id.get(qid)
            names = [n for n in dict.fromkeys([_norm(old.get("Question")) if old else "", _norm(question)]) if n]
            hits = list({t["guid"]: t for n in names for t in by_name.get(n, [])}.values())
            if len(hits) > 1:
                rp.join_path, rp.action = "old_name", "unplaceable"
                rp.reason = f"{len(hits)} terms without a question_id are named like {qid}: " + ", ".join(
                    t["guid"] for t in hits)
            elif hits:
                rp.join_path, rp.term = "old_name", hits[0]
            elif old is not None or is_skipped_status(row.get("Status")):
                rp.action = "unplaceable"
                rp.reason = f"no term for {qid} by question_id or by its pre-edit display name"
            else:
                rp.action = "create"
        plans.append(rp)

    claims: dict[str, list] = {}
    for rp in plans:
        if rp.term is not None and rp.action != "unplaceable":
            claims.setdefault(rp.term["guid"], []).append(rp)
    for guid, claimants in claims.items():
        if len(claimants) > 1:
            for rp in claimants:
                rp.action = "unplaceable"
                rp.reason = f"term {guid} is claimed by " + ", ".join(c.question_id for c in claimants)
    plan_of = {rp.question_id: rp for rp in plans}
    joined_guids = {rp.term["guid"] for rp in plans if rp.term is not None}

    # Pass 2: the commands.
    stale: list = []
    for rp in plans:
        if rp.action == "unplaceable":
            continue
        row = row_of[rp.question_id]
        status = (row.get("Status") or "").strip()
        if rp.action == "create":
            text = _desired_text(row)
            rp.commands.append(Command("Create Glossary Term", {
                "Glossary Name": questions_glossary, **text,
                "Additional Properties": _gen._question_properties(rp.question_id)}, "create", rp.question_id))
            rp.commands.append(Command("Classify Term as Question", {"Term Name": rp.question}, "classify",
                                       rp.question_id))
            rp.commands.extend(_link_commands(rp, row, persp_cols, rp.question, None))
            continue

        term = rp.term
        need_id = not term.get("question_id")
        if is_skipped_status(status):
            merged = _MERGED_RX.match(status)
            fields = {"Qualified Name": term["qualified_name"], "Display Name": term["display_name"]}
            current_desc = term.get("description") or ""
            if not _norm(current_desc).startswith(_norm(status)):
                fields["Description"] = f"{status} — {current_desc}" if current_desc.strip() else status
                rp.changed_fields.append("Description")
            if (term.get("content_status") or "").upper() != DEPRECATED:
                rp.changed_fields.append("Status")
            if need_id:
                rp.changed_fields.append("question_id")
            if rp.changed_fields:
                fields["Status"] = DEPRECATED
                if need_id:
                    fields["Additional Properties"] = _gen._question_properties(rp.question_id)
                rp.commands.append(Command("Update Glossary Term", fields, "deprecate", rp.question_id))
            rp.action = "deprecate_merged" if merged else "deprecate_retired"
            if merged:
                survivor_id = merged.group(1).upper()
                survivor = plan_of.get(survivor_id)
                survivor_row = row_of.get(survivor_id)
                if (survivor is None or survivor_row is None or is_skipped_status(survivor_row.get("Status"))
                        or survivor.action == "unplaceable"):
                    rp.action, rp.commands = "unplaceable", []
                    rp.reason = f"merged into {survivor_id}, and that survivor is missing, not active or not placed"
                    continue
                if survivor.term is not None:
                    links = [l for l in term.get("links", []) if l["relationship"] == REPLACEMENT_TERM
                             and l["guid"] == survivor.term["guid"]]
                    if any(l["other_at_end1"] for l in links):
                        rp.action, rp.commands = "unplaceable", []
                        rp.reason = (f"a ReplacementTerm between {rp.question_id} and {survivor_id} runs the other "
                                     "way (survivor at end 1); resolve by hand")
                        continue
                    present, survivor_ref = bool(links), survivor.term["qualified_name"]
                else:  # created earlier in this same document
                    present, survivor_ref = False, survivor.question
                if not present:
                    rp.commands.append(Command("Link Term-Term Relationship", {
                        "Term 1": term["qualified_name"], "Term 2": survivor_ref,
                        "Relationship Type": REPLACEMENT_TERM}, "link_replacement", rp.question_id))
            if not rp.commands:
                rp.action = "unchanged"
            continue

        desired = _desired_text(row)
        rp.changed_fields = [label for label, value in desired.items()
                             if value and _norm(value) != _norm(term.get(_CURRENT_KEY[label]))]
        if need_id:
            rp.changed_fields.append("question_id")
        if rp.changed_fields:
            fields = {"Qualified Name": term["qualified_name"], **desired}
            if need_id:
                fields["Additional Properties"] = _gen._question_properties(rp.question_id)
            rp.commands.append(Command("Update Glossary Term", fields, "update", rp.question_id))
        rp.commands.extend(_link_commands(rp, row, persp_cols, term["qualified_name"], term))
        rp.action = "update" if rp.changed_fields else ("links_only" if rp.commands else "unchanged")

        wanted_p = {f"{PERSPECTIVE_QN_PREFIX}{c}" for c in persp_cols if (row.get(c) or "").strip()}
        wanted_s = set(_stage_tokens(row))
        stale += [{"question_id": rp.question_id, "kind": "perspective", "scope": p}
                  for p in sorted(_term_perspectives(term) - wanted_p)]
        stale += [{"question_id": rp.question_id, "kind": "stage", "scope": s}
                  for s in sorted(_term_stages(term) - wanted_s)]

    unknown = [{"guid": t["guid"], "display_name": t["display_name"], "question_id": t.get("question_id")}
               for t in terms if t["guid"] not in joined_guids]
    return Plan(rows=plans, inventory_taken_at=str(inventory.get("taken_at") or ""), unknown_terms=unknown,
                stale_links=stale)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

_SECTIONS = (
    ("create", "New question terms (Q-ids not yet in Egeria)"),
    ("active", "Existing question terms: text, question_id and missing links"),
    ("deprecate", "Retired and merged question terms: DEPRECATED, links kept"),
)


def _section_of(cmd: Command, action_of: dict) -> str:
    action = action_of[cmd.question_id]
    if action == "create":
        return "create"
    if action.startswith("deprecate"):
        return "deprecate"
    return "active"


def render_document(plan: Plan) -> str:
    """The Dr.Egeria document: exactly `plan.commands()`, in that order. Nothing is counted here."""
    counts = plan.counts()
    out = [
        "# Question term update batch — generated",
        "",
        "Generated by scripts/question_term_update_batch.py plan from the inventory taken "
        f"{plan.inventory_taken_at or '(no timestamp)'} and docs/dr-egeria/resource_questions.csv. Do not hand-edit:",
        "take a fresh inventory and plan again. Run with VALIDATE first, then PROCESS. It deletes no relationship.",
        "",
        f"Commands: {counts['commands_total']} "
        + ", ".join(f"{k} {v}" for k, v in counts["command"].items()),
        "",
    ]
    cmds = plan.commands()
    if not cmds:
        out += ["No changes: Egeria's question terms already match the CSV.", ""]
        return "\n".join(out)
    action_of = {r.question_id: r.action for r in plan.rows}
    current = None
    for cmd in cmds:
        section = _section_of(cmd, action_of)
        if section != current:
            out += ["---", "", f"# {dict(_SECTIONS)[section]}", ""]
            current = section
        out.append(_gen._block(cmd.command, **cmd.fields))
    return "\n".join(out) + "\n"


def format_counts(plan: Plan) -> str:
    c = plan.counts()
    lines = [
        f"rows {c['rows']}",
        "join path: " + ", ".join(f"{k} {v}" for k, v in c["join_path"].items()),
        "action:    " + ", ".join(f"{k} {v}" for k, v in c["action"].items()),
        f"commands {c['commands_total']}: " + ", ".join(f"{k} {v}" for k, v in c["command_kind"].items()),
        f"unknown terms left alone {c['unknown_terms']}, stale links kept {c['stale_links_kept']}",
    ]
    text_updates = [r for r in plan.rows if r.action == "update"]
    id_only = sum(1 for r in text_updates if r.changed_fields == ["question_id"])
    lines.append(f"updates: {len(text_updates)} ({len(text_updates) - id_only} change text, {id_only} set question_id only)")
    for r in plan.unplaceable:
        lines.append(f"UNPLACEABLE {r.question_id} ({r.join_path}): {r.reason}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def read_csv_rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def _pre_edit_csv_text() -> str:
    r = subprocess.run(["git", "-C", str(_REPO_ROOT), "show", f"{PRE_EDIT_SHA}:{PRE_EDIT_CSV_IN_REPO}"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise PlanInputError(f"could not read the pre-edit CSV at {PRE_EDIT_SHA}: {r.stderr.strip()}")
    return r.stdout


def _cmd_inventory(args) -> int:
    from pyegeria.omvs.glossary_manager import GlossaryManager
    from pyegeria.omvs.metadata_expert import MetadataExpert

    from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as, egeria_client

    try:
        with acting_as(Daemon(DaemonReason.DR_EGERIA, requested_by=args.requested_by)) as identity:
            clients = egeria_client(identity, purpose="question term inventory (read-only)",
                                    view_server=args.view_server, platform_url=args.platform_url)
            inventory = read_inventory(clients.of(GlossaryManager), clients.of(MetadataExpert), args.glossary)
    except Exception as exc:
        print(f"Could not read the inventory ({type(exc).__name__}: {exc}). Nothing written; this says nothing "
              "about what Egeria holds.", file=sys.stderr)
        return 2
    Path(args.out).write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with_id = sum(1 for t in inventory["terms"] if t["question_id"])
    print(f"Wrote {args.out}: {len(inventory['terms'])} terms in {args.glossary!r} ({with_id} with question_id, "
          f"{len(inventory['terms']) - with_id} without), {inventory['terms_seen']} terms read in all, "
          f"{len(inventory['read_errors'])} read error(s)")
    return 1 if inventory["read_errors"] else 0


def _cmd_plan(args) -> int:
    try:
        inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
        rows = read_csv_rows(Path(args.csv).read_text(encoding="utf-8"))
        old_text = Path(args.old_csv).read_text(encoding="utf-8") if args.old_csv else _pre_edit_csv_text()
        plan = build_plan(rows, read_csv_rows(old_text), inventory, questions_glossary=args.glossary)
    except (OSError, ValueError) as exc:
        print(f"Cannot plan: {exc}", file=sys.stderr)
        return 2
    print(format_counts(plan))
    if plan.unplaceable:
        print(f"\n{len(plan.unplaceable)} row(s) cannot be placed: no document written.", file=sys.stderr)
        return 1
    Path(args.out).write_text(render_document(plan), encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("inventory", help="READ-ONLY: the glossary's terms and links, as JSON")
    inv.add_argument("--out", required=True)
    inv.add_argument("--glossary", default=QUESTIONS_GLOSSARY)
    inv.add_argument("--platform-url", default=None)
    inv.add_argument("--view-server", default=None)
    inv.add_argument("--requested-by", default=None, help="who asked for the read (recorded on the daemon identity)")
    pl = sub.add_parser("plan", help="the update document from an inventory (no Egeria calls)")
    pl.add_argument("--inventory", required=True)
    pl.add_argument("--out", required=True)
    pl.add_argument("--csv", default=str(CSV_PATH))
    pl.add_argument("--old-csv", default=None, help=f"pre-edit CSV (default: git show {PRE_EDIT_SHA})")
    pl.add_argument("--glossary", default=QUESTIONS_GLOSSARY)
    args = parser.parse_args(argv)
    return _cmd_inventory(args) if args.cmd == "inventory" else _cmd_plan(args)


if __name__ == "__main__":
    sys.exit(main())
