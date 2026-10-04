"""Catalogue scope for a database: what Curate decides gets catalogued.

Slice A of the catalogue-scope work (the designer's reply on catalogue scope,
page 18 of wireframes/CatalogueScope.dc.html). Everything up to
the commit button; NOTHING here writes to Egeria and nothing here compiles a
list for Egeria's cataloguer. That is slice B.

The one rule: the scope is a declared, signed, dated choice stored in RE. A
node (a schema or a table) is `catalogue`, `leave_out`, or absent, which is
undecided. Storage is two append-only registry tables
(`catalogue_scope_events`, `catalogue_scope_baselines`); the current choice of
a node is its newest event, and a cleared choice is itself an event so who
cleared it is never lost.

What may be PROPOSED (designer section 2, exactly): only a measured fact that
decides ALONE. Three rules, one function each, and nothing else may propose:

- `empty_schema`   a schema with 0 tables, measured (never "no access")  -> leave out
- `no_writes`      `db_change_rates` measured it idle across two surveys  -> leave out
- `data_lens_match` a measured match against the investigation's lens     -> catalogue

PII data classes are a MARK, never a proposal. A staging-looking schema name
is a NOTE, never a proposal. No access is "not established", never a
proposal. A verdict never proposes (it gates; the commit's population rule is
slice B). `propose_for_node` is the only door a proposal goes through, and
`tests/test_catalogue_scope.py` fails on purpose if any of those four sneaks in.

Four observation states, no fifth: proposed, confirmed, overridden, and
"survey now disagrees". A person's own choice that no rule proposed is
`chosen`; no choice at all is `undecided`; a table following its schema is
`inherited`. Those three are not observation states, they are the choice
itself.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

CATALOGUE = "catalogue"
LEAVE_OUT = "leave_out"
CHOICES = (CATALOGUE, LEAVE_OUT)

#: The four depths, in the order the depth line draws them. `how` is the
#: honest account of HOW each is done (the lever research,
#: the catalogue lever findings section 1: the cataloguer's lists match plain
#: names, an empty include list means "everything", so "off" is only
#: expressible as an include list holding a name that matches nothing).
#: Slice A stores the choice; nothing is compiled or sent.
DEPTHS: tuple[dict, ...] = (
    {"id": "database_only", "label": "the database only",
     "how": "no catalog target at all: the database asset alone, nothing below it"},
    {"id": "schemas", "label": "schemas",
     "how": "an include-schema list, with an impossible table name in the include-table list"},
    {"id": "schemas_and_tables", "label": "schemas and tables",
     "how": "include lists for schemas and tables, with an impossible column name in the include-column list"},
    {"id": "tables_and_columns", "label": "tables and columns",
     "how": "everything: the lists name schemas and tables and no column list is sent"},
)
DEPTH_IDS = tuple(d["id"] for d in DEPTHS)
DEFAULT_DEPTH = "schemas_and_tables"
DEPTH_HELP = ("Views follow the table lists: a view is catalogued when its name is in the "
              "table list, because Egeria's cataloguer never reads a separate view list.")

SYSTEM_SENTENCE = "not catalogued: system schemas are never offered"

#: Proposal rule ids. They are stored on the event as the confirmed `source`.
RULE_EMPTY_SCHEMA = "empty_schema"
RULE_NO_WRITES = "no_writes"
RULE_DATA_LENS = "data_lens_match"
PROPOSAL_RULES = (RULE_EMPTY_SCHEMA, RULE_NO_WRITES, RULE_DATA_LENS)


class ScopeError(Exception):
    """A scope request that cannot be honoured. `status` is the HTTP code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def md(iso: str | None) -> str:
    """`2026-10-02T09:00:00` -> `10-02`, the short date every row uses."""
    s = str(iso or "")
    return s[5:10] if len(s) >= 10 else ""


# ── provenance of a node, by depth ───────────────────────────────────────────

def depth_provenance(depth: str, kind: str) -> str:
    """The second line of a row: which level the depth leaves out, and how.

    The first three depths each leave a level out through an include list
    (the lever has no off switch). The database-only depth sends no catalog
    target at all, so it says that instead.
    """
    if depth == "database_only":
        return ("schemas excluded: no catalog target, nothing below the database is catalogued"
                if kind == "schema" else
                "tables excluded: no catalog target, nothing below the database is catalogued")
    if depth == "schemas":
        return "tables excluded via include list" if kind == "table" else ""
    if depth == "schemas_and_tables":
        return "columns excluded via include list" if kind == "table" else ""
    return ""


# ── the three proposal rules ─────────────────────────────────────────────────

def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(name or "").lower()) if t}


def measure_fact(rule: str, facts: dict) -> dict | None:
    """The measurement a rule stands on, now. None when it cannot be taken.

    The same function backs the proposal AND the "survey now disagrees" check,
    so the two can never be reading different things.
    """
    if rule == RULE_EMPTY_SCHEMA:
        if facts["kind"] != "schema" or facts.get("classification") in ("no_access", "system"):
            return None
        if facts.get("table_count") is None:
            return None
        return {"table_count": int(facts["table_count"])}
    if rule == RULE_NO_WRITES:
        if facts.get("classification") in ("no_access", "system"):
            return None
        if facts["kind"] == "schema" and not facts.get("table_count"):
            return None
        idle = facts.get("idle")
        if idle is None:
            return None
        return {"idle": bool(idle)}
    if rule == RULE_DATA_LENS:
        if facts["kind"] != "table" or not facts.get("lens_terms"):
            return None
        hit = sorted(_tokens(facts["name"]) & {str(t).lower() for t in facts["lens_terms"]})
        return {"match": bool(hit), "term": hit[0] if hit else ""}
    return None


def propose_for_node(facts: dict) -> dict | None:
    """The single door a proposal goes through.

    `facts` is what was MEASURED about one node; nothing else is consulted, so
    a data class, a staging-looking name, a missing credential and a verdict
    cannot propose because none of them is in `facts` as a rule input. When two
    rules decide in opposite directions neither decides alone, so nothing is
    proposed and the row says the measurements disagree.
    """
    found: list[dict] = []
    m = measure_fact(RULE_EMPTY_SCHEMA, facts)
    if m is not None and m["table_count"] == 0:
        found.append({
            "rule": RULE_EMPTY_SCHEMA, "choice": LEAVE_OUT, "measured": m,
            "reason": ("0 tables, measured " + md(facts.get("measured_at"))).strip(),
        })
    m = measure_fact(RULE_NO_WRITES, facts)
    if m is not None and m["idle"] is True:
        found.append({
            "rule": RULE_NO_WRITES, "choice": LEAVE_OUT, "measured": m,
            "reason": (f"no writes since {md(facts.get('idle_from'))}"
                       f" (survey of {md(facts.get('idle_to'))})"),
        })
    m = measure_fact(RULE_DATA_LENS, facts)
    if m is not None and m["match"]:
        found.append({
            "rule": RULE_DATA_LENS, "choice": CATALOGUE, "measured": m,
            "reason": f"matches the lens on subject “{m['term']}”",
        })
    if not found:
        return None
    if len({p["choice"] for p in found}) > 1:
        return {"conflicting": [p["rule"] for p in found]}
    p = found[0]
    p["measured_at"] = facts.get("measured_at") or ""
    return p


def _disagreement(rule: str, stored: dict, current: dict | None, survey_at: str) -> dict | None:
    """Both values and the survey date when the measurement under a confirmed
    or overridden choice changed. None when unchanged or not measurable now
    (an unmeasurable now is not a disagreement, it is an absence)."""
    if current is None or not rule or current == stored:
        return None
    if rule == RULE_EMPTY_SCHEMA:
        was, now = stored.get("table_count"), current.get("table_count")
        words = f"it had {was} tables; it now has {now}"
    elif rule == RULE_NO_WRITES:
        words = ("no writes were measured; writes now show" if stored.get("idle")
                 else "writes were measured; none now show")
    else:
        words = ("it matched the lens; it no longer does" if stored.get("match")
                 else "it did not match the lens; it now does")
    return {"was": stored, "now": current, "survey_at": survey_at, "words": words}


# ── reading the world ────────────────────────────────────────────────────────

def _load_tree(registry, slug: str) -> dict:
    from resource_explorer.surveyors.database.survey_definition_adapter import (
        schema_inventory_tree,
    )
    return schema_inventory_tree(registry, slug) or {"schemas": []}


def _tree_survey_at(registry, slug: str) -> str:
    """When the rows the tree is built from were measured (newest run)."""
    try:
        with registry._conn() as conn:
            row = conn.execute(
                "SELECT MAX(surveyed_at) AS latest FROM database_tables WHERE database_slug = ?",
                (registry._normalize_slug(slug),),
            ).fetchone()
        return (dict(row).get("latest") if row else "") or ""
    except Exception:  # an unreadable table is an absence, not a date
        return ""


def _change_rates(registry, slug: str) -> dict:
    from resource_explorer.surveyors.database.db_derived import (
        DerivedInputs, derive_change_rates,
    )
    try:
        return derive_change_rates(registry, DerivedInputs(slug=slug, surveyed_at=None, source=None))
    except Exception:
        return {}


def data_lens_for(registry, slug: str) -> dict | None:
    """The data lens of an investigation this database is in, if one exists.

    None on this build, and it says so rather than guessing: no stored,
    investigation-level DataLens exists (`step_preconditions._needs_human_input`
    and `batch_io.NO_LENS` say the same). The lens-match proposal rule is
    fully implemented and tested through the `lens` argument; it fires in
    the product the day a lens is stored and this function returns it.
    """
    return None


def data_class_facts(registry, slug: str) -> dict:
    """Data classes found per table: `{(schema, table): {"classes": [...], "pii_columns": n}}`.

    Empty on this build, honestly: `data_class_match` results have no local
    store (Backlog, "Database per-column match results have no local store"),
    so the tree says "not established" rather than "none found". The PII mark
    is wired and tested through the `data_classes` argument.
    """
    return {}


def _survey_header(registry, slug: str) -> dict:
    """Egeria's latest recorded native survey, from the proof row, or not measured."""
    from resource_explorer.registry import SOURCE_EGERIA
    try:
        rows = registry.get_database_surveys(slug) or []
    except Exception:
        rows = []
    for r in rows:
        if (r.get("source") or "") != SOURCE_EGERIA:
            continue
        if r.get("schema_count") is None or r.get("table_count") is None:
            continue
        return {"state": "measured", "schema_count": int(r["schema_count"]),
                "table_count": int(r["table_count"]), "surveyed_at": r.get("surveyed_at") or "",
                "report_guid": r.get("egeria_report_guid") or ""}
    return {"state": "not_measured", "schema_count": None, "table_count": None,
            "surveyed_at": "", "report_guid": ""}


def _tree_keys(tree: dict) -> dict:
    schemas, tables = [], []
    for s in tree.get("schemas") or []:
        if s.get("classification") == "system" or not s.get("schema"):
            continue
        schemas.append(s["schema"])
        for t in s.get("tables") or []:
            tables.append(f"{s['schema']}.{t['name']}")
    return {"schemas": sorted(schemas), "tables": sorted(tables)}


def _latest_by_node(events: list[dict]) -> tuple[dict, dict | None]:
    """(node key -> newest event, newest depth event).

    A node whose newest event is a clear is absent from the first dict."""
    latest: dict[tuple, dict] = {}
    depth = None
    for e in events:  # oldest first, so the last write wins
        if e["node_kind"] == "depth":
            depth = e
            continue
        latest[(e["node_kind"], e["schema_name"], e["table_name"])] = e
    return {k: v for k, v in latest.items() if v["choice"]}, depth


# ── the merged view ──────────────────────────────────────────────────────────

def build_scope_view(registry, slug: str, *, tree: dict | None = None,
                     change_rates: dict | None = None, data_classes: dict | None = None,
                     lens: dict | None = None) -> dict:
    """The scope merged with the Schema Inventory tree: one read for the screen."""
    tree = tree if tree is not None else _load_tree(registry, slug)
    events = registry.list_catalogue_scope_events(slug)
    baselines = registry.list_catalogue_scope_baselines(slug)
    explicit, depth_event = _latest_by_node(events)
    survey_at = _tree_survey_at(registry, slug)
    rates = change_rates if change_rates is not None else _change_rates(registry, slug)
    classes = data_classes if data_classes is not None else data_class_facts(registry, slug)
    lens = lens if lens is not None else data_lens_for(registry, slug)
    lens_terms = list((lens or {}).get("subjectTerms") or [])

    idle_by_table: dict[tuple, str] = {}
    for e in (rates.get("per_table") or []):
        if e.get("change") in ("idle", "active"):
            idle_by_table[(e["schema_name"], e["table_name"])] = e["change"]
    rates_from = rates.get("from_surveyed_at") or ""
    rates_to = rates.get("to_surveyed_at") or ""

    baseline = baselines[-1] if baselines else None
    base_keys = (baseline or {}).get("baseline") or {}
    base_schemas = set(base_keys.get("schemas") or [])
    base_tables = set(base_keys.get("tables") or [])

    depth = (depth_event or {}).get("choice") or DEFAULT_DEPTH

    def event_view(e: dict | None) -> dict | None:
        if not e:
            return None
        return {"choice": e["choice"], "action": e["action"], "source": e["source"],
                "by": e["author"], "at": e["changed_at"], "reason": e["reason"],
                "proposal_rule": e["proposal_rule"], "proposal_choice": e["proposal_choice"],
                "measured_at": e["measured_at"], "measured": e["measured"]}

    def decide(kind: str, facts: dict, ev: dict | None) -> dict:
        """The observation state of one node from its facts and its newest event."""
        proposal = propose_for_node(facts)
        out: dict[str, Any] = {"proposal": None, "live_proposal": None, "overridden": None,
                               "disagrees": None, "notes": [], "marks": []}
        if proposal and "conflicting" in proposal:
            out["notes"].append("measurements disagree: nothing is proposed")
            proposal = None
        out["live_proposal"] = proposal
        if ev is None:
            out["state"] = "proposed" if proposal else "undecided"
            out["proposal"] = proposal
            return out
        rule = ev["proposal_rule"]
        if ev["action"] in ("confirm", "override") and rule:
            now = measure_fact(rule, facts)
            out["disagrees"] = _disagreement(rule, ev["measured"], now, survey_at)
        if ev["action"] == "override":
            out["overridden"] = {"rule": rule, "choice": ev["proposal_choice"],
                                 "reason": ev["reason"], "measured_at": ev["measured_at"]}
            out["state"] = "overridden"
        elif ev["action"] == "confirm":
            out["state"] = "confirmed"
        else:
            out["state"] = "chosen"
        if out["disagrees"]:
            out["state"] = "disagrees"
        return out

    schemas_out: list[dict] = []
    system_row = None
    name_to_tables: dict[str, list[dict]] = {}

    for s in tree.get("schemas") or []:
        if s.get("classification") == "system":
            system_row = s
            continue
        sname = s["schema"]
        cls = s.get("classification") or ""
        tabs = s.get("tables") or []
        changes = [idle_by_table.get((sname, t["name"])) for t in tabs]
        if tabs and all(c == "idle" for c in changes):
            s_idle = True
        elif any(c == "active" for c in changes):
            s_idle = False
        else:
            s_idle = None
        s_facts = {"kind": "schema", "name": sname, "classification": cls,
                   "table_count": s.get("table_count"), "idle": s_idle,
                   "idle_from": rates_from, "idle_to": rates_to, "measured_at": survey_at}
        s_ev = explicit.get(("schema", sname, ""))
        sv = decide("schema", s_facts, s_ev)
        s_choice = s_ev["choice"] if s_ev else None
        in_baseline = sname in base_schemas
        node: dict[str, Any] = {
            "kind": "schema", "name": sname, "key": sname, "classification": cls,
            "reason": s.get("reason") or "", "table_count": s.get("table_count"),
            "row_total": s.get("row_total"), "bytes_total": s.get("bytes_total"),
            "is_estimate": bool(s.get("is_estimate")),
            "explicit": event_view(s_ev), "effective": s_choice,
            "effective_from": "self" if s_choice else None,
            "new_since": bool(baseline) and not in_baseline,
            "access": "not_established" if cls == "no_access" else "established",
            "last_write": {"state": ("idle" if s_idle else "active") if s_idle is not None else "not_established",
                           "from": rates_from, "to": rates_to},
            "data_classes": {"state": "not_established", "classes": [], "pii_columns": 0},
            "provenance": depth_provenance(depth, "schema"),
            "conflict": None, "tables": [], **sv,
        }
        if cls == "staging":
            node["notes"].append("name suggests staging")
        if s_choice is None:
            node["undecided_words"] = "keeps what’s in Egeria now"
        pii_s = 0
        for t in tabs:
            tname = t["name"]
            dc = classes.get((sname, tname))
            pii = int((dc or {}).get("pii_columns") or 0)
            pii_s += pii
            t_change = idle_by_table.get((sname, tname))
            t_facts = {"kind": "table", "schema": sname, "name": tname, "classification": cls,
                       "idle": (t_change == "idle") if t_change else None,
                       "idle_from": rates_from, "idle_to": rates_to, "measured_at": survey_at,
                       "lens_terms": lens_terms}
            t_ev = explicit.get(("table", sname, tname))
            tv = decide("table", t_facts, t_ev)
            own = t_ev["choice"] if t_ev else None
            if own:
                eff, eff_from = own, "self"
            elif s_choice:
                eff, eff_from = s_choice, "schema"
            else:
                eff, eff_from = None, None
            tnode = {
                "kind": "table", "name": tname, "schema": sname, "key": f"{sname}.{tname}",
                "table_type": t.get("table_type") or "", "row_count": t.get("row_count"),
                "row_count_state": t.get("row_count_state") or "", "size_bytes": t.get("size_bytes"),
                "column_count": t.get("column_count"),
                "explicit": event_view(t_ev), "effective": eff, "effective_from": eff_from,
                "inherited": s_choice if not own else None,
                "differs_from_schema": bool(own and s_choice and own != s_choice),
                "new_since": bool(baseline) and f"{sname}.{tname}" not in base_tables,
                "access": "not_established" if cls == "no_access" else "established",
                "last_write": {"state": t_change or "not_established",
                               "from": rates_from, "to": rates_to},
                "data_classes": ({"state": "measured", "classes": list(dc.get("classes") or []),
                                  "pii_columns": pii} if dc
                                 else {"state": "not_established", "classes": [], "pii_columns": 0}),
                "provenance": depth_provenance(depth, "table"),
                "conflict": None, **tv,
            }
            if pii:
                tnode["marks"].append(f"PII · {pii} column{'s' if pii != 1 else ''}")
            if depth == "tables_and_columns":
                tnode["columns"] = t.get("columns") or []
            node["tables"].append(tnode)
            name_to_tables.setdefault(tname, []).append(tnode)
        if pii_s:
            node["marks"].append(f"PII · {pii_s} column{'s' if pii_s != 1 else ''}")
            node["data_classes"] = {"state": "measured", "classes": [], "pii_columns": pii_s}
        schemas_out.append(node)

    # name-conflict check (designer section 4): the filter matches plain names
    pairs, names = [], []
    for tname, nodes in sorted(name_to_tables.items()):
        yes = [n["schema"] for n in nodes if n["effective"] == CATALOGUE]
        no = [n["schema"] for n in nodes if n["effective"] == LEAVE_OUT]
        if yes and no:
            names.append(tname)
            involved = yes + no
            text = (f"{tname} is chosen differently in "
                    + (" and ".join(involved) if len(involved) <= 2
                       else ", ".join(involved[:-1]) + " and " + involved[-1]))
            for n in nodes:
                if n["effective"] in CHOICES:
                    n["conflict"] = {"name": tname, "text": text,
                                     "catalogue_in": yes, "leave_out_in": no}
            for a in yes:
                for b in no:
                    pairs.append({"name": tname, "catalogue_in": a, "leave_out_in": b})
    conflicts = {"count": len(names), "names": names, "pairs": pairs}

    view = {
        "database": slug, "schemas": schemas_out,
        "system": ({"folded": system_row.get("system_count"), "text": SYSTEM_SENTENCE}
                   if system_row else None),
        "survey": _survey_header(registry, slug),
        "tree_surveyed_at": survey_at,
        "declared": ({"declared": True, "by": baseline["declared_by"], "at": baseline["declared_at"],
                      "kind": baseline["kind"], "baseline_survey_at": baseline["survey_at"]}
                     if baseline else {"declared": False, "by": "", "at": "", "kind": "",
                                       "baseline_survey_at": ""}),
        "depth": {"value": depth, "declared": depth_event is not None,
                  "by": (depth_event or {}).get("author", ""), "at": (depth_event or {}).get("changed_at", ""),
                  "options": [dict(d) for d in DEPTHS], "help": DEPTH_HELP},
        "conflicts": conflicts,
    }
    view["counts"] = {
        "schemas_offered": len(schemas_out),
        "schemas_catalogue": sum(1 for n in schemas_out if n["effective"] == CATALOGUE),
        "schemas_leave_out": sum(1 for n in schemas_out if n["effective"] == LEAVE_OUT),
        "schemas_undecided": sum(1 for n in schemas_out if n["effective"] is None),
    }
    view["new_since"] = _new_since_from_view(view)
    return view


def _new_since_from_view(view: dict) -> dict:
    """What appeared in the latest survey that the declared scope never saw.

    Nodes that have since been given an explicit choice are in the scope now
    and are not counted. With no declaration there is nothing to be new since,
    and the answer says so rather than reporting zero."""
    if not view["declared"]["declared"]:
        return {"declared": False, "schemas": 0, "tables": 0, "tables_in_known_schemas": 0,
                "schema_names": [], "text": "", "since": ""}
    new_schemas = [s for s in view["schemas"] if s["new_since"] and s["explicit"] is None]
    tables_in_new = sum(1 for s in new_schemas for t in s["tables"] if t["explicit"] is None)
    known = [t for s in view["schemas"] if not s["new_since"] for t in s["tables"]
             if t["new_since"] and t["explicit"] is None]
    n, m = len(new_schemas), tables_in_new
    text = ""
    if n:
        text = f"{n} new schema{'s' if n != 1 else ''} ({m} table{'s' if m != 1 else ''}) not in your scope"
    if known:
        extra = f"{len(known)} new table{'s' if len(known) != 1 else ''} in schemas you already know"
        text = f"{text} · {extra}" if text else extra
    return {"declared": True, "schemas": n, "tables": m, "tables_in_known_schemas": len(known),
            "schema_names": [s["name"] for s in new_schemas], "text": text,
            "since": view["declared"]["at"]}


def scope_conflicts(registry, slug: str, *, view: dict | None = None, **kw) -> dict:
    """Choices Egeria's plain-name filter cannot express: `{count, names, pairs}`.

    Slice B disables the Catalogue button while `count` > 0 ("N choices Egeria
    can't express, resolve them above")."""
    return (view or build_scope_view(registry, slug, **kw))["conflicts"]


def new_since_declared(registry, slug: str, *, view: dict | None = None, **kw) -> dict:
    """The count slice B's manifest quotes: "N new schemas (M tables) not in your scope"."""
    return (view or build_scope_view(registry, slug, **kw))["new_since"]


# ── writes (all append; none touch Egeria) ───────────────────────────────────

def _now() -> str:
    return datetime.utcnow().isoformat()


def _declare_if_needed(registry, slug: str, author: str, keys: dict, now: str) -> None:
    """First declaration: store the baseline (the node keys the latest survey
    knows right now). A no-op once a baseline exists."""
    if registry.list_catalogue_scope_baselines(slug):
        return
    registry.append_catalogue_scope_baseline(
        slug, baseline=keys, survey_at=_tree_survey_at(registry, slug),
        author=author, kind="first", declared_at=now)


def _find_node(view: dict, schema: str, table: str) -> dict:
    for s in view["schemas"]:
        if s["name"] == schema:
            if not table:
                return s
            for t in s["tables"]:
                if t["name"] == table:
                    return t
            raise ScopeError(404, f"table {schema}.{table} is not in the latest survey")
    raise ScopeError(404, f"schema {schema} is not offered: it is not in the latest survey, "
                          "or it is a system schema (system schemas are never offered)")


def set_node_choice(registry, slug: str, author: str, *, schema: str, table: str = "",
                    choice: str, reason: str = "", now: str | None = None, **view_kw) -> dict:
    """Set a node's choice. If a rule is proposing for this node right now, the
    event records it: the same choice is a confirmation (source = the rule id),
    the opposite is an override (source = person, the proposal kept beside it)."""
    if choice not in CHOICES:
        raise ScopeError(400, f"choice must be one of {', '.join(CHOICES)}")
    if not author:
        raise ScopeError(401, "a scope choice needs an author")
    now = now or _now()
    view = build_scope_view(registry, slug, **view_kw)
    node = _find_node(view, schema, table)
    prop = node.get("live_proposal")
    kw: dict[str, Any] = {"action": "set", "source": "person", "reason": reason}
    if prop:
        kw.update(proposal_rule=prop["rule"], proposal_choice=prop["choice"],
                  reason=prop["reason"], measured_at=prop.get("measured_at") or "",
                  measured=prop["measured"])
        if prop["choice"] == choice:
            kw.update(action="confirm", source=prop["rule"])
        else:
            kw.update(action="override", source="person")
    _declare_if_needed(registry, slug, author, _view_tree_keys(view), now)
    registry.append_catalogue_scope_event(
        slug, node_kind="table" if table else "schema", schema_name=schema, table_name=table,
        choice=choice, author=author, changed_at=now, **kw)
    return {"state": kw["action"], "node": f"{schema}.{table}" if table else schema}


def confirm_proposal(registry, slug: str, author: str, *, schema: str, table: str = "",
                     now: str | None = None, **view_kw) -> dict:
    node = _find_node(build_scope_view(registry, slug, **view_kw), schema, table)
    if not node.get("live_proposal"):
        raise ScopeError(409, "nothing is proposed for this row now")
    return set_node_choice(registry, slug, author, schema=schema, table=table,
                           choice=node["live_proposal"]["choice"], now=now, **view_kw)


def override_proposal(registry, slug: str, author: str, *, schema: str, table: str = "",
                      now: str | None = None, **view_kw) -> dict:
    node = _find_node(build_scope_view(registry, slug, **view_kw), schema, table)
    prop = node.get("live_proposal")
    if not prop:
        raise ScopeError(409, "nothing is proposed for this row now")
    other = LEAVE_OUT if prop["choice"] == CATALOGUE else CATALOGUE
    return set_node_choice(registry, slug, author, schema=schema, table=table,
                           choice=other, now=now, **view_kw)


def clear_node_choice(registry, slug: str, author: str, *, schema: str, table: str = "",
                      now: str | None = None, **view_kw) -> dict:
    if not author:
        raise ScopeError(401, "a scope choice needs an author")
    node = _find_node(build_scope_view(registry, slug, **view_kw), schema, table)
    if node["explicit"] is None:
        raise ScopeError(409, "this row has no choice to clear")
    registry.append_catalogue_scope_event(
        slug, node_kind="table" if table else "schema", schema_name=schema, table_name=table,
        choice="", action="clear", author=author, changed_at=now or _now())
    return {"state": "cleared", "node": f"{schema}.{table}" if table else schema}


def set_depth(registry, slug: str, author: str, *, depth: str, now: str | None = None,
              **view_kw) -> dict:
    if depth not in DEPTH_IDS:
        raise ScopeError(400, f"depth must be one of {', '.join(DEPTH_IDS)}")
    if not author:
        raise ScopeError(401, "a depth choice needs an author")
    now = now or _now()
    tree = view_kw.get("tree") if view_kw.get("tree") is not None else _load_tree(registry, slug)
    _declare_if_needed(registry, slug, author, _tree_keys(tree), now)
    registry.append_catalogue_scope_event(
        slug, node_kind="depth", choice=depth, action="set", author=author, changed_at=now)
    return {"state": "set", "depth": depth}


def redeclare(registry, slug: str, author: str, *, now: str | None = None, **view_kw) -> dict:
    """Declare the scope again: the baseline becomes what the latest survey
    knows now, so "new since your scope was declared" starts counting from here."""
    if not author:
        raise ScopeError(401, "a declaration needs an author")
    tree = view_kw.get("tree") if view_kw.get("tree") is not None else _load_tree(registry, slug)
    first = not registry.list_catalogue_scope_baselines(slug)
    registry.append_catalogue_scope_baseline(
        slug, baseline=_tree_keys(tree), survey_at=_tree_survey_at(registry, slug), author=author,
        kind="first" if first else "redeclare", declared_at=now or _now())
    return {"state": "declared"}


def resolve_conflict(registry, slug: str, author: str, *, name: str, choice: str,
                     now: str | None = None, **view_kw) -> dict:
    """Resolve one name conflict the one way a person can: the same explicit
    choice on every table of that name that is currently decided."""
    if choice not in CHOICES:
        raise ScopeError(400, f"choice must be one of {', '.join(CHOICES)}")
    view = build_scope_view(registry, slug, **view_kw)
    if name not in view["conflicts"]["names"]:
        raise ScopeError(409, f"{name} is not in conflict now")
    now = now or _now()
    done = []
    for s in view["schemas"]:
        for t in s["tables"]:
            if t["name"] == name and t["effective"] in CHOICES:
                _declare_if_needed(registry, slug, author, _view_tree_keys(view), now)
                registry.append_catalogue_scope_event(
                    slug, node_kind="table", schema_name=s["name"], table_name=name,
                    choice=choice, action="set", author=author, changed_at=now,
                    reason="resolves a name conflict")
                done.append(f"{s['name']}.{name}")
    return {"state": "resolved", "nodes": done}


def _view_tree_keys(view: dict) -> dict:
    """Baseline keys from a built view (its schemas are the non-system tree)."""
    return {"schemas": sorted(s["name"] for s in view["schemas"]),
            "tables": sorted(t["key"] for s in view["schemas"] for t in s["tables"])}
