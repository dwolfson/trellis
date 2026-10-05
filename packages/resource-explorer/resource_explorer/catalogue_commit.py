"""The catalogue commit for a database, by schema-kind targets (slice B).

`BRIEF-CURATE-CATALOGUE-COMMIT-DATABASES.md`. Slice A (`catalogue_scope.py`)
keeps the scope: a declared, signed, dated choice per schema and table. This
module compiles that record into Egeria's lever every time it is pressed, and
shows what Egeria actually holds afterwards.

**The door is the schema-kind catalog target** (owner's decision, 2026-10-05).
One DeployedDatabaseSchema per chosen schema, created from the template and
attached to the JDBC cataloguer with no configuration lists. Never the database
element and never the server: a database-kind target catalogues every schema's
tables directly under the database whatever its lists say.

Three mechanisms run, in this order, and the manifest names all three:

1. RE publishes the server and database elements (description and version
   supplied so no `~{...}~` placeholder remains), writes the publish
   ZoneMembership on the database element BEFORE any target is attached (the
   cataloguer's dependents copy it at creation), then Owner from Context.
2. Egeria's cataloguer creates the schemas' tables and columns on its next
   refresh. RE attaches one schema-kind target per chosen schema (reading the
   targets first, never attaching twice).
3. Egeria's survey measures, limited to the chosen schemas by the request
   parameter `includeSchemaNames` (never the connection configuration, which
   the service ignores; a schema whose name contains a comma cannot be scoped).

**Every state word is derived from a persisted proof row.** The tree's per-node
state comes from `catalogue_commit_proofs` (what a read-back saw) and from the
`egeria_outbox` rows this commit queued (queued, failed), never from the branch
the code took (the status-words rule). `derive_commit_state` is the one
function that does it, so the route, the header marker and the tests cannot
disagree.

Leaving a schema out has two forms, chosen per schema from a relationships read
and said in the preview before the press: soft-delete when nothing hangs off
it, archive (the delete endpoint with deleteMethod ARCHIVE; the `/archive`
endpoint answers 500) when something does. A failed read is "couldn't check
what hangs off it", never nothing. Every delete RE performs is per element,
leaf first, `forLineage` true, never a cascade.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

from resource_explorer.catalogue_gateway import (
    ARCHIVE, SOFT_DELETE, CatalogueGateway, GatewayError, like_matches,
    schema_qualified_name, schema_type_qualified_name, server_name_for)
from resource_explorer.catalogue_scope import CATALOGUE, LEAVE_OUT, current_schema_choice, md

log = logging.getLogger(__name__)

# ── words the screen uses (one place, so tests and the UI pin the same text) ──

S19_SENTENCE = "can't be re-included until Egeria restores archived elements"
WHOLE_SCHEMAS_LINE = "Egeria catalogues whole schemas · table choices are kept for when it can"
SURVEY_LINE = "Egeria's survey is limited to your chosen schemas"
LINGERING_LINE = ("Egeria's cataloguer still lists this schema until its connector restarts "
                  "· nothing is recreated")
CANT_CHECK = "couldn't check what hangs off it"
OWNER_REFUSED = "owner set by Egeria's source · can't change from RE"
NO_SCOPE_SENTENCE = "no scope declared · nothing catalogued"
NOT_COMMITTED_HEADER = "Saved in Resource Explorer · not yet catalogued in Egeria"

# ── proof kinds (rows in catalogue_commit_proofs) ────────────────────────────

P_DATABASE = "database_published"
P_ZONES = "zones_set"
P_OWNER = "owner_result"
P_REPORT = "report_published"
P_TARGET = "target_attached"
P_ELEMENTS = "elements_read_back"
P_DETACHED = "target_detached"
P_REMOVED = "removed"
P_ARCHIVED = "archived"
P_ADOPTED = "schema_type_adopted"
P_SURVEY = "survey_started"
P_CONNECTOR = "connector_read"
P_READ_FAILED = "read_failed"

#: Proofs that decide a schema's state in Egeria. Anything else is context.
STATE_PROOFS = (P_TARGET, P_ELEMENTS, P_REMOVED, P_ARCHIVED)

#: The curation record's steps, in the manifest's order.
STEPS_DB = ("publish_elements", "zone_membership", "owner", "schema_targets",
            "leave_outs", "survey_report", "survey", "refresh", "read_back")

KIND_ATTACH = "catalogue_schema_attach"
KIND_LEAVE_OUT = "catalogue_schema_leave_out"

#: Relationships that are the cataloguer's own structure, not something that
#: hangs off a schema. Everything NOT in this set counts as hanging off it, so a
#: relationship type this list has never heard of errs towards ARCHIVE (which
#: keeps it) and never towards a soft delete (which removes it). The owner's gate
#: confirms the list against a live schema with a term assignment.
STRUCTURAL_RELATIONSHIPS = frozenset({
    "CatalogTarget", "DataSetContent", "AssetSchemaType", "AttributeForSchema",
    "NestedSchemaAttribute", "SchemaTypeOption", "LinkedType", "Anchors",
    "ConnectionToAsset", "ServerAssetUse", "AssetConnection", "ReportSubject",
    "TemplateSource", "SourcedFrom", "ResourceList",
})

HANGS_OFF_WORDS = {
    "SemanticAssignment": ("term assignment", "term assignments"),
    "LineageMapping": ("lineage mapping", "lineage mappings"),
    "DataClassAssignment": ("data class assignment", "data class assignments"),
    "DataClassComposition": ("data class composition", "data class compositions"),
    "ImplementedBy": ("implementation link", "implementation links"),
}


class CommitBlocked(Exception):
    """The commit cannot be pressed. `status` is the HTTP code, `reasons` say why."""

    def __init__(self, status: int, message: str, reasons: list[str] | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.reasons = reasons or []


class SchemaRefused(Exception):
    """A schema that cannot be (re-)included. Carries the sentence the row reads."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _hm(iso: str) -> str:
    s = str(iso or "")
    return s[11:16] if len(s) >= 16 else ""


def _stamp(iso: str) -> str:
    """`2026-10-05T09:12:44` -> `10-05 09:12`."""
    return f"{md(iso)} {_hm(iso)}".strip()


# ── names ────────────────────────────────────────────────────────────────────

def names_for(db_entity) -> dict:
    server = server_name_for(db_entity)
    return {"server": server, "database": db_entity.database_name}


def schema_qn(db_entity, schema: str) -> str:
    return schema_qualified_name(server_name_for(db_entity), db_entity.database_name, schema)


def schema_type_qn(db_entity, schema: str) -> str:
    return schema_type_qualified_name(server_name_for(db_entity), db_entity.database_name, schema)


def target_name(db_entity, schema: str) -> str:
    """The catalog target's name, as the scratch runs named theirs."""
    return f"{db_entity.database_name}_schema_{schema}"


# ── the `_` and `%` collision check ──────────────────────────────────────────

def wildcard_collisions(view: dict, schema_names: list[str]) -> list[dict]:
    """Where Egeria's listing for a chosen name would also return another name.

    The cataloguer hands real names to JDBC's metadata calls as patterns, so a
    schema `a_b` also returns `aXb`'s tables, and a table `x_y` also returns
    `xZy`'s columns (the scratch runs confirmed both, behind a schema-kind
    target too). RE sees every name in its inventory, so it says so BEFORE
    attaching, and the commit stays disabled while one stands. The only way out
    is to leave the chosen schema out, because Egeria catalogues whole schemas.

    Compared against the offered (non-system) schemas and, for tables, the other
    tables of the same schema; the system schemas' names are not in the tree.
    """
    chosen = set(schema_names)
    all_schemas = [s["name"] for s in view.get("schemas") or []]
    out: list[dict] = []
    for s in view.get("schemas") or []:
        if s["name"] not in chosen:
            continue
        name = s["name"]
        if "_" in name or "%" in name:
            for other in all_schemas:
                if other != name and like_matches(name, other):
                    out.append({"kind": "schema", "schema": name, "name": name, "other": other,
                                "text": f"⚠ Egeria's listing for {name} would also return {other}"})
        tnames = [t["name"] for t in s.get("tables") or []]
        for t in tnames:
            if "_" in t or "%" in t:
                for other in tnames:
                    if other != t and like_matches(t, other):
                        out.append({"kind": "table", "schema": name, "name": t, "other": other,
                                    "text": f"⚠ Egeria's listing for {t} in {name} would also return {other}"})
    return out


# ── what hangs off a schema ──────────────────────────────────────────────────

def classify_hangs_off(rels_per_element: list[list]) -> dict:
    """Group the non-structural relationships found on a schema's elements."""
    by_type: dict[str, int] = {}
    for rels in rels_per_element:
        for r in rels:
            if r.type_name and r.type_name not in STRUCTURAL_RELATIONSHIPS:
                by_type[r.type_name] = by_type.get(r.type_name, 0) + 1
    total = sum(by_type.values())
    parts = []
    for t, n in sorted(by_type.items()):
        one, many = HANGS_OFF_WORDS.get(t, (t, t))
        parts.append(f"{n} {one if n == 1 else many}")
    return {"total": total, "by_type": by_type, "words": " · ".join(parts)}


def read_hangs_off(gateway: CatalogueGateway, db_entity, schema: str) -> dict:
    """What hangs off one catalogued schema, from a relationships read of its elements.

    Returns `{"state": "absent"}` when Egeria holds no such schema element,
    `{"state": "read", "form", "hangs_off", "element_guid", "checked"}` when the
    read completed, and `{"state": "cannot_check", "error"}` when any read
    failed. A failed read is never reported as "nothing hangs off it"."""
    qn = schema_qn(db_entity, schema)
    try:
        el = gateway.read_element(qn)
        if el is None:
            return {"state": "absent"}
        under = gateway.elements_under(qn + "::")
        rels = [gateway.relationships(el.guid)] + [gateway.relationships(u.guid) for u in under]
    except GatewayError as exc:
        return {"state": "cannot_check", "error": str(exc)}
    h = classify_hangs_off(rels)
    return {"state": "read", "form": ARCHIVE if h["total"] else SOFT_DELETE, "hangs_off": h,
            "element_guid": el.guid, "checked": 1 + len(under)}


# ── deriving every state word from proof rows ────────────────────────────────

def _by_node(proofs: list[dict]) -> dict:
    out: dict[tuple, list[dict]] = {}
    for p in proofs:
        out.setdefault((p["node_kind"], p["schema_name"], p["table_name"]), []).append(p)
    return out


def _latest(rows: list[dict], kinds: tuple[str, ...]) -> dict | None:
    for p in reversed(rows):
        if p["proof"] in kinds:
            return p
    return None


def _outbox_by_schema(outbox: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in outbox:                       # oldest first, so the last one wins
        s = (r.get("payload") or {}).get("schema")
        if s is not None:
            out[s] = r
    return out


def _egeria_word(text: str) -> str:
    """The error text without the Python class name the outbox prefixes it with."""
    return re.sub(r"^\w+(Error|Exception): ", "", str(text or "")).strip() or "no reason recorded"


def _schema_state(rows: list[dict], ob: dict | None, effective: str | None, connector: dict | None) -> dict:
    """One schema's state, from its proof rows and its newest outbox row."""
    step = ""
    if ob is not None:
        step = "leave out" if ob["element_kind"] == KIND_LEAVE_OUT else "attach"
        status = ob.get("status")
        if status in ("pending", "running"):
            return {"state": "queued", "words": f"queued · outbox #{ob['id']}",
                    "second": f"step: {step}",
                    "proof": {"kind": "outbox", "outbox_id": ob["id"], "status": status}}
        if status == "failed":
            return {"state": "failed", "words": f"failed · {_egeria_word(ob.get('last_error'))}",
                    "second": f"step: {step} · outbox #{ob['id']} · will retry",
                    "proof": {"kind": "outbox", "outbox_id": ob["id"], "status": status}}
        if status == "dead":
            return {"state": "failed", "words": f"failed · {_egeria_word(ob.get('last_error'))}",
                    "second": f"step: {step} · outbox #{ob['id']} · gave up after {ob.get('attempts')} attempts",
                    "proof": {"kind": "outbox", "outbox_id": ob["id"], "status": status}}
    last = _latest(rows, STATE_PROOFS)
    had_elements = _latest(rows, (P_ELEMENTS,)) is not None
    detached = _latest(rows, (P_DETACHED,)) is not None
    if last is None:
        if effective == LEAVE_OUT:
            return {"state": "left_out", "words": "left out", "second": "scope record · never catalogued",
                    "proof": None}
        if effective == CATALOGUE:
            return {"state": "uncommitted", "words": "not committed yet",
                    "second": "chosen in the scope · nothing read back from Egeria", "proof": None}
        return {"state": "none", "words": "", "second": "", "proof": None}
    proof = {"kind": last["proof"], "at": last["read_at"], "element_guid": last["element_guid"],
             "outbox_id": last.get("outbox_id")}
    kind = last["proof"]
    if kind == P_ELEMENTS:
        d = last["detail"]
        n = len(d.get("tables") or [])
        words = f"catalogued · {n} table{'s' if n != 1 else ''} · read back {_stamp(last['read_at'])}"
        second = "element · read back from Egeria"
        if effective == LEAVE_OUT:
            second = "scope says leave out · still in Egeria until the next commit"
        return {"state": "catalogued", "words": words, "second": second, "proof": proof}
    if kind == P_TARGET:
        ct = (connector or {}).get("last_refresh_time") or last["detail"].get("connector_last_refresh") or ""
        second = (f"connector's last refresh {_hm(ct)} (the connector's, not this schema's)"
                  if ct else "last cycle not reported")
        if effective == LEAVE_OUT:
            second = "scope says leave out · still attached until the next commit"
        return {"state": "attached_waiting", "words": "attached · waiting for Egeria's next refresh",
                "second": second, "proof": proof}
    if kind == P_REMOVED:
        was = " · was catalogued" if had_elements else ""
        second = LINGERING_LINE if detached else ""
        if effective == CATALOGUE:
            second = "scope says catalogue · the next commit re-creates it from the template"
        return {"state": "removed", "words": f"removed{was} · {_stamp(last['read_at'])}",
                "second": second, "proof": proof}
    if kind == P_ARCHIVED:
        second = S19_SENTENCE if effective == CATALOGUE else (LINGERING_LINE if detached else "")
        return {"state": "archived", "words": f"archived in Egeria · {_stamp(last['read_at'])}",
                "second": second, "proof": proof}
    return {"state": "none", "words": "", "second": "", "proof": proof}


def schema_state_of(registry, slug: str, schema: str, effective: str | None = None) -> dict:
    """One schema's derived state, straight from the rows (no scope view needed)."""
    by = _by_node(registry.list_catalogue_commit_proofs(slug))
    ob = _outbox_by_schema(registry.list_catalogue_outbox_rows(slug)).get(schema)
    return _schema_state(by.get(("schema", schema, ""), []), ob, effective, None)


def derive_commit_state(registry, slug: str, view: dict) -> dict:
    """Every state word on the scope tree, header included, from persisted rows.

    The one function the route and the tests share. Returns
    `{"schemas": {name: state}, "tables": {"s.t": state}, "header": {...},
    "database": {...}, "collisions": [...]}`. Reads only the registry; Egeria is
    never contacted here, so opening Curate stays free."""
    proofs = registry.list_catalogue_commit_proofs(slug)
    by = _by_node(proofs)
    ob_by_schema = _outbox_by_schema(registry.list_catalogue_outbox_rows(slug))
    db_rows = by.get(("database", "", ""), [])
    published = _latest(db_rows, (P_DATABASE,))
    connector = _latest(db_rows, (P_CONNECTOR,))
    conn_d = ({"last_refresh_time": connector["detail"].get("last_refresh_time", ""),
               "read_at": connector["read_at"]} if connector else None)
    failed_read = _latest(db_rows, (P_READ_FAILED,))

    schemas: dict[str, dict] = {}
    tables: dict[str, dict] = {}
    for s in view.get("schemas") or []:
        name = s["name"]
        st = _schema_state(by.get(("schema", name, ""), []), ob_by_schema.get(name), s.get("effective"), conn_d)
        schemas[name] = st
        found = None
        el = _latest(by.get(("schema", name, ""), []), (P_ELEMENTS,))
        if el is not None and st["state"] == "catalogued":
            found = set(el["detail"].get("tables") or [])
        for t in s.get("tables") or []:
            key = f"{name}.{t['name']}"
            if st["state"] == "catalogued":
                if t["name"] in found:
                    ts = {"state": "catalogued", "words": f"catalogued · read back {_stamp(el['read_at'])}",
                          "second": "element · read back from Egeria"}
                else:
                    ts = {"state": "not_read_back", "words": "in the survey · not in Egeria's listing",
                          "second": f"schema read back {_stamp(el['read_at'])}; this table was not under it"}
                if t.get("effective") == LEAVE_OUT:
                    ts["second"] = WHOLE_SCHEMAS_LINE
            elif st["state"] in ("attached_waiting", "queued", "failed", "removed", "archived"):
                ts = {"state": "follows_schema", "words": f"as its schema: {st['state'].replace('_', ' ')}",
                      "second": WHOLE_SCHEMAS_LINE if t.get("effective") == LEAVE_OUT else ""}
            else:
                ts = {"state": "none", "words": "", "second": ""}
            tables[key] = ts

    # What the chosen schemas would be, for the collision check shown on the tree.
    chosen = [n for n, s in ((x["name"], x) for x in view.get("schemas") or [])
              if s.get("effective") == CATALOGUE
              or (s.get("effective") is None and schemas[n]["state"] in ("catalogued", "attached_waiting", "queued"))]
    collisions = wildcard_collisions(view, chosen)

    counts: dict[str, int] = {}
    for s in view.get("schemas") or []:
        if s.get("effective") == CATALOGUE:
            k = schemas[s["name"]]["state"]
            counts[k] = counts.get(k, 0) + 1
    header = _header(published, counts, conn_d, failed_read, view, bool(proofs or ob_by_schema))
    return {"schemas": schemas, "tables": tables, "header": header, "collisions": collisions,
            "database": ({"guid": published["element_guid"], "short": published["element_guid"][:8],
                          "at": published["read_at"], "owner": (_latest(db_rows, (P_OWNER,)) or {}).get("detail")}
                         if published else None)}


def _header(published, counts, conn_d, failed_read, view, anything: bool) -> dict:
    """The state-derived marker line: never a constant (the owner's gate, item 6)."""
    if not anything:
        return {"state": "not_committed", "text": NOT_COMMITTED_HEADER}
    n_cat = sum(1 for s in view.get("schemas") or [] if s.get("effective") == CATALOGUE)
    parts = []
    if published:
        parts.append(f"Database element {published['element_guid'][:8]} in Egeria · published {_stamp(published['read_at'])}")
    else:
        parts.append("Database element not read back from Egeria")
    if n_cat:
        order = (("catalogued", "catalogued"), ("attached_waiting", "attached, waiting"),
                 ("queued", "queued"), ("failed", "failed"), ("uncommitted", "not committed yet"),
                 ("removed", "removed"), ("archived", "archived"))
        bits = [f"{counts[k]} {w}" for k, w in order if counts.get(k)]
        parts.append(f"{n_cat} schema{'s' if n_cat != 1 else ''} chosen: " + (", ".join(bits) or "no proof rows"))
    if conn_d and conn_d.get("last_refresh_time"):
        parts.append(f"cataloguer connector's last refresh {_stamp(conn_d['last_refresh_time'])} (the connector's, not a schema's)")
    if failed_read:
        parts.append(f"last read of Egeria failed {_stamp(failed_read['read_at'])}: {failed_read['detail'].get('error', '')}")
    return {"state": "committed", "text": " · ".join(parts)}


# ── the preview and its manifest ─────────────────────────────────────────────

def _chosen_and_kept(view: dict, states: dict) -> tuple[list[str], list[str]]:
    """Schemas to be targets: chosen ones, plus undecided ones already in Egeria.

    The scope's own rule: an undecided schema keeps what is in Egeria now; only
    an explicit leave out removes anything."""
    chosen = [s["name"] for s in view["schemas"] if s.get("effective") == CATALOGUE]
    kept = [s["name"] for s in view["schemas"]
            if s.get("effective") is None and states.get(s["name"], {}).get("state") in
            ("catalogued", "attached_waiting", "queued")]
    return chosen, kept


def survey_schema_list(names: list[str]) -> tuple[list[str], list[str]]:
    """(names the request parameter can scope, names with a comma it cannot).

    The parameter is split on commas with no trimming, so a comma inside a name
    makes it `cm` and `ma`, neither of which exists: the survey would report
    success with nothing in it. Such a name is left out of the list and said so."""
    ok = [n for n in names if "," not in n]
    bad = [n for n in names if "," in n]
    return ok, bad


def build_preview(registry, slug: str, view: dict, gateway: CatalogueGateway | None, *,
                  db_entity=None, derived: dict | None = None) -> dict:
    """What pressing Catalogue would do, with the Egeria reads it needs.

    `gateway` None means Egeria could not be reached: every leave out that needs
    a read is then "couldn't check what hangs off it" and blocked, which is the
    honest answer, never "nothing"."""
    db_entity = db_entity or registry.get_database(slug, allow_unreadable=True)
    derived = derived or derive_commit_state(registry, slug, view)
    states = derived["schemas"]
    chosen, kept = _chosen_and_kept(view, states)
    refused, attach, leave, blockers = [], [], [], []

    for name in chosen:
        st = states[name]
        if st["state"] == "archived":
            refused.append({"schema": name, "text": f"{name}: {S19_SENTENCE}"})
        else:
            attach.append(name)
    attach += [n for n in kept]

    leave_out_names = [s["name"] for s in view["schemas"] if s.get("effective") == LEAVE_OUT]
    for name in leave_out_names:
        st = states.get(name, {})
        node = next(s for s in view["schemas"] if s["name"] == name)
        tcount = node.get("table_count")
        row = {"schema": name, "tables": tcount}
        if st.get("state") in ("removed", "archived", "left_out", "none", "uncommitted"):
            row.update(form="none", blocked=False,
                       text=f"{name}: nothing to remove" + (" · already " + st["state"] if st.get("state") in ("removed", "archived") else " · never catalogued"))
            leave.append(row)
            continue
        if gateway is None:
            row.update(form="cannot_check", blocked=True, text=f"{name}: {CANT_CHECK}",
                       error="Egeria could not be reached")
            leave.append(row)
            continue
        read = read_hangs_off(gateway, db_entity, name)
        if read["state"] == "absent":
            row.update(form="none", blocked=False, text=f"{name}: not in Egeria any more · nothing to remove")
        elif read["state"] == "cannot_check":
            row.update(form="cannot_check", blocked=True, text=f"{name}: {CANT_CHECK}", error=read["error"])
        elif read["form"] == SOFT_DELETE:
            row.update(form=SOFT_DELETE, blocked=False, hangs_off=read["hangs_off"], checked=read["checked"],
                       text=f"{name}: nothing hangs off it · will be removed (soft-deleted) from Egeria"
                            + (f" with its {tcount} tables" if tcount else ""))
        else:
            row.update(form=ARCHIVE, blocked=False, hangs_off=read["hangs_off"], checked=read["checked"],
                       text=f"{name}: {read['hangs_off']['words']} hang off it · will be archived in Egeria, "
                            f"not deleted · can't be re-included until Egeria restores archived elements")
        leave.append(row)

    blocked_names = {r["schema"] for r in leave if r.get("blocked")}
    collisions = wildcard_collisions(view, attach)
    if collisions:
        blockers.append(f"{len(collisions)} name collision{'s' if len(collisions) != 1 else ''} Egeria's listing "
                        "can't tell apart: leave the schema out, or rename it in the database")
    # A leave out that cannot be checked is blocked FOR THAT SCHEMA: it is left exactly
    # where it is and the commit proceeds for the rest (the brief: "disabled for that
    # schema"). It is never read as "nothing hangs off it".

    ok_names, comma_names = survey_schema_list(attach)
    ctx = registry.get_context("database", slug) or {}
    owner = ((ctx.get("enrichment") or {}).get("owner") or {}).get("value") or ""
    from resource_explorer.egeria_identity import publish_zones
    zones = publish_zones()
    removes = [r for r in leave if r["form"] == SOFT_DELETE]
    archives = [r for r in leave if r["form"] == ARCHIVE]
    n_new = sum(1 for n in attach if states.get(n, {}).get("state") not in ("catalogued", "attached_waiting", "queued"))
    lines = [
        {"id": "re_publishes", "mechanism": 1,
         "text": ("RE publishes the server and database assets and RE's own survey report, supplying the database "
                  "description and version, and joins the deployment's publish zones: "
                  f"{', '.join(zones)}. That is written before any target is attached. "
                  + (f"Owner from Context: {owner}." if owner else "Not carried: owner, not declared on Context."))},
        {"id": "cataloguer_creates", "mechanism": 2,
         "text": (f"Egeria's cataloguer creates tables and columns for {len(attach)} schema target"
                  f"{'s' if len(attach) != 1 else ''} ({n_new} to attach now). Each is a schema-kind target, "
                  "never the database or the server. The elements arrive on the daemon's next refresh, not now.")},
        {"id": "survey_measures", "mechanism": 3,
         "text": (f"{SURVEY_LINE}: " + (", ".join(ok_names) if ok_names else "no schema chosen, so the survey is not started")
                  + (f". Not scopable, a comma in the name: {', '.join(comma_names)}" if comma_names else ""))},
    ]
    # What this commit will NOT do, named: "1 schema not committed: s_x · couldn't check what
    # hangs off it". Both per-schema holds appear here; the rest of the commit proceeds.
    held: dict[str, list[str]] = {}
    for r in leave:
        if r.get("blocked"):
            held.setdefault(CANT_CHECK, []).append(r["schema"])
    for r in refused:
        held.setdefault(S19_SENTENCE, []).append(r["schema"])
    not_committed = [{"reason": why, "schemas": names} for why, names in held.items()]
    for nc in not_committed:
        n = len(nc["schemas"])
        nc["text"] = f"{n} schema{'s' if n != 1 else ''} not committed: {', '.join(nc['schemas'])} · {nc['reason']}"
        lines.append({"id": "not_committed", "mechanism": 0, "text": nc["text"]})
    if leave:
        lines.append({"id": "leave_out", "mechanism": 0, "text": "; ".join(r["text"] for r in leave)})
    lines.append({"id": "whole_schemas", "mechanism": 0, "text": WHOLE_SCHEMAS_LINE})

    something = bool(attach or [r for r in leave if r["form"] in (SOFT_DELETE, ARCHIVE)])
    if not something and not blockers:
        blockers.append("nothing to commit: choose at least one schema to catalogue")
    label = f"Catalogue · {len(attach)} schema{'s' if len(attach) != 1 else ''}"
    if removes:
        label += f" · removes {len(removes)} from Egeria"
    if archives:
        label += f" · archives {len(archives)}"
    return {
        "can_commit": not blockers,
        "button": label,
        "blockers": blockers,
        "blocked_schemas": sorted(blocked_names),
        "blocked_notes": [r["text"] for r in leave if r.get("blocked")],
        "attach": attach,
        "refused": refused,
        "leave_out": leave,
        "collisions": collisions,
        "survey": {"schemas": ok_names, "not_scopable": comma_names, "line": SURVEY_LINE},
        "manifest": {"lines": lines, "not_committed": not_committed, "schema_targets": len(attach), "new_targets": n_new,
                     "survey_schemas": ok_names, "zones": zones, "owner": owner,
                     "whole_schemas_line": WHOLE_SCHEMAS_LINE},
        "tables_line": WHOLE_SCHEMAS_LINE,
    }


# ── what an outbox row does ──────────────────────────────────────────────────

def _proof(registry, slug: str, proof: str, *, schema: str = "", node_kind: str = "schema",
           table: str = "", **kw) -> int:
    return registry.append_catalogue_commit_proof(
        slug, proof=proof, node_kind=node_kind, schema_name=schema, table_name=table, **kw)


def _entity(registry, slug: str):
    e = registry.get_database(slug, allow_unreadable=True)
    if e is None:
        raise GatewayError(f"database {slug!r} is no longer registered")
    return e


def apply_attach(registry, gateway: CatalogueGateway, payload: dict, *, outbox_id: int | None = None) -> str:
    """Create the schema element and attach it as a schema-kind target. Idempotent.

    Reads first, always: the element by qualified name (adopting an existing one),
    the cataloguer's targets (never attaching the same schema twice), and after
    the attach the targets again, because the proof row is the read-back and not
    the call's return. Returns the schema element's GUID."""
    slug, schema = payload["slug"], payload["schema"]
    e = _entity(registry, slug)
    qn = schema_qn(e, schema)
    if current_schema_choice(registry, slug, schema) == LEAVE_OUT:
        # The person left it out after this was queued. Attaching it now would
        # undo their choice; nothing is written and the row is simply done.
        log.info("catalogue commit: %s/%s was left out after its attach was queued; not attaching", slug, schema)
        return ""
    # Re-inclusion after an archive is refused: the archived element still holds the
    # qualified name, the template create fails 400, and nothing can be adopted.
    seen = gateway.read_element(qn, for_lineage=True)
    if seen is not None and seen.archived:
        raise SchemaRefused(f"{schema}: {S19_SENTENCE}")
    el = gateway.read_element(qn)
    if el is None:
        orphan = gateway.find_schema_type(schema_type_qn(e, schema))
        guid = gateway.create_schema_element(e, schema, payload.get("database_guid", ""))
        if not guid:
            raise GatewayError(f"Egeria created no schema element for {schema}")
        if orphan:
            gateway.link_schema_type(guid, orphan)
            _proof(registry, slug, P_ADOPTED, schema=schema, element_guid=guid, qualified_name=schema_type_qn(e, schema),
                   curation_id=payload.get("curation_id", ""), outbox_id=outbox_id,
                   detail={"schema_type_guid": orphan, "note": "adopted the existing schema type rather than create a second"})
    else:
        guid = el.guid
    targets = gateway.list_catalog_targets()
    mine = [t for t in targets if t.element_guid == guid]
    if not mine:
        gateway.add_catalog_target(guid, target_name(e, schema))
        mine = [t for t in gateway.list_catalog_targets() if t.element_guid == guid]
        if not mine:
            raise GatewayError(f"the target for {schema} was added but is not in the cataloguer's list on read-back")
    status = None
    try:
        status = gateway.connector_status()
    except GatewayError:
        pass
    _proof(registry, slug, P_TARGET, schema=schema, element_guid=guid, target_guid=mine[0].relationship_guid,
           qualified_name=qn, curation_id=payload.get("curation_id", ""), outbox_id=outbox_id,
           recorded_by=payload.get("by", ""),
           detail={"targets_for_schema": len(mine),
                   "connector_last_refresh": status.last_refresh_time if status else "",
                   "connector_note": "the connector's last refresh, not this target's"})
    return guid


_RANK = {"RelationalColumn": 0, "RelationalTable": 1}


def apply_leave_out(registry, gateway: CatalogueGateway, payload: dict, *, outbox_id: int | None = None) -> str:
    """Detach the schema's target and remove or archive its element. Idempotent.

    The form is re-derived from a fresh relationships read here and the SAFER one
    wins: if the preview said soft delete and something now hangs off the schema
    it is archived; a failed read raises (nothing deleted). Deletes are per
    element, leaf first, `forLineage` true, never a cascade. An archive is one
    call on the schema element: its tables and columns are archived with it and
    a per-element archive of them would find them already archived."""
    slug, schema = payload["slug"], payload["schema"]
    e = _entity(registry, slug)
    qn = schema_qn(e, schema)
    cid = payload.get("curation_id", "")
    if current_schema_choice(registry, slug, schema) == CATALOGUE:
        log.info("catalogue commit: %s/%s was chosen again after its leave-out was queued; not removing", slug, schema)
        return ""
    el = gateway.read_element(qn)
    guid = el.guid if el else ""
    if guid:
        for t in [t for t in gateway.list_catalog_targets() if t.element_guid == guid]:
            gateway.remove_catalog_target(t.relationship_guid)
        if any(t.element_guid == guid for t in gateway.list_catalog_targets()):
            raise GatewayError(f"the target for {schema} is still in the cataloguer's list after removal")
        _proof(registry, slug, P_DETACHED, schema=schema, element_guid=guid, qualified_name=qn,
               curation_id=cid, outbox_id=outbox_id, recorded_by=payload.get("by", ""),
               detail={"note": "target gone from the cataloguer's list on read-back"})
    if el is None:
        archived = gateway.read_element(qn, for_lineage=True)
        if archived is not None and archived.archived:
            _proof(registry, slug, P_ARCHIVED, schema=schema, element_guid=archived.guid, qualified_name=qn,
                   curation_id=cid, outbox_id=outbox_id, detail={"note": "already archived when read"})
            return archived.guid
        _proof(registry, slug, P_REMOVED, schema=schema, qualified_name=qn, curation_id=cid, outbox_id=outbox_id,
               detail={"form": "absent", "note": "no schema element in Egeria when read"})
        return ""
    read = read_hangs_off(gateway, e, schema)
    if read["state"] == "cannot_check":
        raise GatewayError(f"{schema}: {CANT_CHECK}: {read['error']}")
    form = ARCHIVE if (payload.get("form") == ARCHIVE or read.get("form") == ARCHIVE) else SOFT_DELETE
    if form == ARCHIVE:
        gateway.delete_element(guid, ARCHIVE)
        now = gateway.read_element(qn)
        seen = gateway.read_element(qn, for_lineage=True)
        if now is not None or seen is None or not seen.archived:
            raise GatewayError(f"{schema}: the archive was sent but the read-back does not show it archived")
        _proof(registry, slug, P_ARCHIVED, schema=schema, element_guid=guid, qualified_name=qn, curation_id=cid,
               outbox_id=outbox_id, recorded_by=payload.get("by", ""),
               detail={"form": ARCHIVE, "hangs_off": read["hangs_off"]["by_type"]})
        return guid
    under = gateway.elements_under(qn + "::")
    under.sort(key=lambda u: (-u.qualified_name.count("::"), _RANK.get(u.type_name, 2)))
    for u in under:
        gateway.delete_element(u.guid, SOFT_DELETE)
    gateway.delete_element(guid, SOFT_DELETE)
    if gateway.read_element(qn) is not None or gateway.elements_under(qn + "::"):
        raise GatewayError(f"{schema}: the delete was sent but the read-back still finds elements")
    _proof(registry, slug, P_REMOVED, schema=schema, element_guid=guid, qualified_name=qn, curation_id=cid,
           outbox_id=outbox_id, recorded_by=payload.get("by", ""),
           detail={"form": SOFT_DELETE, "elements_deleted": len(under) + 1})
    return guid


def read_back(registry, gateway: CatalogueGateway, slug: str, schemas: list[str], *,
              curation_id: str = "", by: str = "") -> dict:
    """Read Egeria and write what it says as proof rows. The one place a schema
    becomes `catalogued`: elements found under it by qualified name.

    A failed read writes a `read_failed` row and changes no state, so "Egeria
    could not be read just now" never poses as a state of any schema."""
    e = _entity(registry, slug)
    summary = {"catalogued": 0, "attached_waiting": 0, "read_failed": 0, "schemas": {}}
    try:
        targets = gateway.list_catalog_targets()
        status = gateway.connector_status()
    except GatewayError as exc:
        _proof(registry, slug, P_READ_FAILED, node_kind="database", curation_id=curation_id,
               detail={"error": str(exc), "what": "the cataloguer's targets and connector"})
        summary["read_failed"] += 1
        return summary
    if status is not None:
        _proof(registry, slug, P_CONNECTOR, node_kind="database", curation_id=curation_id,
               detail={"last_refresh_time": status.last_refresh_time, "status": status.status,
                       "note": "the connector's own time; no per-target time exists"})
    for schema in schemas:
        qn = schema_qn(e, schema)
        try:
            el = gateway.read_element(qn)
            under = gateway.elements_under(qn + "::") if el else []
        except GatewayError as exc:
            _proof(registry, slug, P_READ_FAILED, schema=schema, curation_id=curation_id,
                   detail={"error": str(exc)})
            summary["read_failed"] += 1
            continue
        if el is None:
            continue
        tables = sorted(u.qualified_name[len(qn) + 2:] for u in under
                        if u.type_name == "RelationalTable" and "::" not in u.qualified_name[len(qn) + 2:])
        cols = sum(1 for u in under if u.type_name == "RelationalColumn")
        mine = [t for t in targets if t.element_guid == el.guid]
        if under:
            _proof(registry, slug, P_ELEMENTS, schema=schema, element_guid=el.guid, qualified_name=qn,
                   curation_id=curation_id, recorded_by=by, target_guid=mine[0].relationship_guid if mine else "",
                   detail={"tables": tables, "columns": cols, "elements": len(under)})
            summary["catalogued"] += 1
            summary["schemas"][schema] = "catalogued"
        elif mine:
            _proof(registry, slug, P_TARGET, schema=schema, element_guid=el.guid, target_guid=mine[0].relationship_guid,
                   qualified_name=qn, curation_id=curation_id, recorded_by=by,
                   detail={"connector_last_refresh": status.last_refresh_time if status else "",
                           "connector_note": "the connector's last refresh, not this target's"})
            summary["attached_waiting"] += 1
            summary["schemas"][schema] = "attached_waiting"
    return summary


# ── the commit itself ────────────────────────────────────────────────────────

def run_with_loop(fn: Callable[..., Any], *args, **kwargs):
    """Run `fn` on this thread with an event loop set: pyegeria's sync wrappers
    call `asyncio.get_event_loop()`, which a worker thread does not have."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return fn(*args, **kwargs)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def make_gateway(db_entity) -> CatalogueGateway:
    """The real gateway. Tests replace this one name."""
    from resource_explorer.catalogue_gateway import PyegeriaCatalogueGateway
    return PyegeriaCatalogueGateway(db_entity)


def start_commit(registry, slug: str, author: str, *, refresh_now: bool = False,
                 gateway: CatalogueGateway | None = None) -> dict:
    """Validate the press against a fresh preview and queue the run.

    The preview is recomputed here, with its Egeria reads: what the person saw
    is not trusted, only the rows are. Raises `CommitBlocked` (409) with the
    reasons when the commit is disabled."""
    from resource_explorer.catalogue_scope import build_scope_view
    from resource_explorer.curate_plan import Curations
    if not author:
        raise CommitBlocked(401, "Sign in to catalogue: the record needs an author.")
    db_entity = registry.get_database(slug, allow_unreadable=True)
    if db_entity is None:
        raise CommitBlocked(404, f"Database '{slug}' not found")
    if not registry.list_catalogue_scope_baselines(slug):
        # Nothing has ever been declared for this database. Catalogue-by-default is exactly
        # what the scope exists to prevent, so this stops before any Egeria call is made.
        raise CommitBlocked(409, NO_SCOPE_SENTENCE, [NO_SCOPE_SENTENCE])
    view = build_scope_view(registry, slug)
    derived = derive_commit_state(registry, slug, view)
    if gateway is None:
        try:
            gateway = make_gateway(db_entity)
        except Exception as exc:  # no client at all: every read-dependent row will say so
            log.warning("catalogue commit: no Egeria gateway for %s: %s", slug, exc)
            gateway = None
    preview = build_preview(registry, slug, view, gateway, db_entity=db_entity, derived=derived)
    if not preview["can_commit"]:
        raise CommitBlocked(409, "The commit is disabled: " + "; ".join(preview["blockers"]), preview["blockers"])
    selection = {
        "attach": preview["attach"],
        "leave_out": [{"schema": r["schema"], "form": r["form"]} for r in preview["leave_out"]
                      if r["form"] in (SOFT_DELETE, ARCHIVE)],
        "survey_schemas": preview["survey"]["schemas"],
        "survey_not_scopable": preview["survey"]["not_scopable"],
        "refresh_now": bool(refresh_now),
    }
    from resource_explorer.activity_logger import log_survey
    activity_id = log_survey(
        registry, entity_type="database", entity_slug=slug, entity_name=db_entity.display_name,
        entity_location=f"{db_entity.host}:{db_entity.port}/{db_entity.database_name}",
        intent="curate", status="running",
        summary=f"Cataloguing {db_entity.display_name}: {len(selection['attach'])} schema targets…")
    rec = Curations(registry).create("database", slug, author=author, selection=selection,
                                     manifest=preview["manifest"], steps=list(STEPS_DB), activity_id=activity_id)
    run_id = registry.enqueue_run("catalogue_commit", {"slug": slug, "curation_id": rec["id"]},
                                  result_ref=activity_id, requested_by=author)
    return {"curation": rec, "run_id": run_id, "activity_id": activity_id, "preview": preview}


def _step_from_outbox(cur, cid: str, step: str, rows: list[dict], what: str) -> None:
    done = [r for r in rows if r["status"] == "done"]
    bad = [r for r in rows if r["status"] in ("failed", "dead")]
    wait = [r for r in rows if r["status"] in ("pending", "running")]
    if not rows:
        cur.set_step(cid, step, "skipped", f"no schema to {what}")
        return
    parts = [f"{len(done)} of {len(rows)} {what}d, each with its proof row"]
    if wait:
        parts.append(f"{len(wait)} queued in the outbox (#{', #'.join(str(r['id']) for r in wait)})")
    for r in bad:
        parts.append(f"{(r['payload'] or {}).get('schema')}: {r.get('last_error')}")
    cur.set_step(cid, step, "done" if len(done) == len(rows) else "failed", " · ".join(parts))


def execute_commit(registry, curation_id: str, *, gateway: CatalogueGateway | None = None,
                   drain: Callable[..., Any] | None = None) -> dict:
    """Run the curation record's steps. Nothing raises past a step: a step that
    fails is a failed step on the record, and a step that depends on it is
    skipped with the reason, never run on a guess."""
    from resource_explorer.curate_plan import Curations
    cur = Curations(registry)
    rec = cur.get(curation_id)
    if not rec:
        raise KeyError(curation_id)
    slug = rec["entity_slug"]
    sel = rec.get("selection") or {}
    author = rec.get("author", "")
    try:
        db = registry.get_database(slug)       # credentials may be needed: not allow_unreadable
    except Exception as exc:                   # e.g. the stored password cannot be decrypted
        cur.set_step(curation_id, "publish_elements", "failed", f"{type(exc).__name__}: {exc}"[:400])
        return cur.finish(curation_id)
    if db is None:
        cur.set_step(curation_id, "publish_elements", "failed", "database no longer registered")
        return cur.finish(curation_id)
    if gateway is None:
        gateway = make_gateway(db)
    if drain is None:
        from resource_explorer.egeria_outbox import OutboxClients, drain_outbox

        def drain(run_id):  # noqa: E306
            return drain_outbox(registry, OutboxClients(catalogue_gateway=gateway, registry=registry),
                                lambda qn: "", run_id=run_id)

    db_guid = ""
    # 1 ── the server and database elements
    cur.set_step(curation_id, "publish_elements", "running")
    try:
        pub = gateway.publish_database(db, db.db_user, db.db_password, registry=registry, submitted_by=author)
        db_guid = pub.database_guid
        if not db_guid:
            raise GatewayError("Egeria returned no database element")
        registry.set_database_egeria_guid(slug, db_guid)
        _proof(registry, slug, P_DATABASE, node_kind="database", element_guid=db_guid,
               qualified_name=pub.database_qualified_name, curation_id=curation_id, recorded_by=author,
               detail={"server_guid": pub.server_guid, "server_name": pub.server_name})
        cur.set_step(curation_id, "publish_elements", "done",
                     f"server {pub.server_guid[:8]} · database {db_guid[:8]} · description and version supplied")
    except Exception as exc:
        cur.set_step(curation_id, "publish_elements", "failed", f"{type(exc).__name__}: {exc}"[:400])

    # 1b ── ZoneMembership on the database element BEFORE any target
    zones_ok = False
    if not db_guid:
        cur.set_step(curation_id, "zone_membership", "skipped", "no database element: the publish step did not produce one")
    else:
        from resource_explorer.egeria_identity import publish_zones
        zones = publish_zones()
        try:
            zones_ok = bool(gateway.set_zone_membership(db_guid, zones))
        except Exception as exc:
            log.warning("catalogue commit %s: zone write raised: %s", curation_id, exc)
            zones_ok = False
        if zones_ok:
            _proof(registry, slug, P_ZONES, node_kind="database", element_guid=db_guid,
                   curation_id=curation_id, detail={"zones": zones})
        cur.set_step(curation_id, "zone_membership", "done" if zones_ok else "failed",
                     (f"ZoneMembership {', '.join(zones)} written before any target" if zones_ok else
                      "Egeria did not accept the ZoneMembership: no target is attached, because the cataloguer's "
                      "elements copy the database's zones at creation"))

    # 1c ── owner, added after the database element is read back
    owner = (((registry.get_context("database", slug) or {}).get("enrichment") or {}).get("owner") or {}).get("value") or ""
    if not db_guid:
        cur.set_step(curation_id, "owner", "skipped", "no database element")
    elif not owner:
        cur.set_step(curation_id, "owner", "skipped", "not carried: owner, not declared on Context")
    else:
        try:
            outcome, detail = gateway.set_owner(db_guid, owner)
        except Exception as exc:
            outcome, detail = "failed", f"{type(exc).__name__}: {exc}"[:300]
        if outcome in ("set", "already", "refused"):
            _proof(registry, slug, P_OWNER, node_kind="database", element_guid=db_guid, curation_id=curation_id,
                   detail={"outcome": outcome, "owner": owner, "egeria_said": detail})
        cur.set_step(curation_id, "owner", "failed" if outcome == "failed" else "done",
                     OWNER_REFUSED if outcome == "refused" else f"{detail}")

    # 2 ── one schema-kind target per schema, through the outbox
    attach = list(sel.get("attach") or [])
    if not attach:
        cur.set_step(curation_id, "schema_targets", "skipped", "no schema to attach")
    elif not db_guid or not zones_ok:
        cur.set_step(curation_id, "schema_targets", "skipped",
                     "needs the database element and its ZoneMembership first: " +
                     ("no database element" if not db_guid else "the ZoneMembership was not written"))
    else:
        cur.set_step(curation_id, "schema_targets", "running")
        for schema in attach:
            registry.enqueue_outbox_element(
                "database", slug, KIND_ATTACH, schema_qn(db, schema),
                {"slug": slug, "schema": schema, "database_guid": db_guid, "curation_id": curation_id, "by": author},
                run_id=curation_id)
        drain(curation_id)
        rows = [r for r in registry.list_catalogue_outbox_rows(slug)
                if r["run_id"] == curation_id and r["element_kind"] == KIND_ATTACH]
        _step_from_outbox(cur, curation_id, "schema_targets", rows, "attach")

    # 2b ── leave outs
    leave = list(sel.get("leave_out") or [])
    if not leave:
        cur.set_step(curation_id, "leave_outs", "skipped", "no schema to remove or archive")
    else:
        cur.set_step(curation_id, "leave_outs", "running")
        for item in leave:
            registry.enqueue_outbox_element(
                "database", slug, KIND_LEAVE_OUT, schema_qn(db, item["schema"]) + "#leave_out",
                {"slug": slug, "schema": item["schema"], "form": item["form"], "curation_id": curation_id, "by": author},
                run_id=curation_id)
        drain(curation_id)
        rows = [r for r in registry.list_catalogue_outbox_rows(slug)
                if r["run_id"] == curation_id and r["element_kind"] == KIND_LEAVE_OUT]
        _step_from_outbox(cur, curation_id, "leave_outs", rows, "remove")

    # 3 ── RE's own survey report and annotations (no native survey started here)
    measured = registry.latest_measured_database_survey(slug)
    if not db_guid:
        cur.set_step(curation_id, "survey_report", "skipped", "no database element")
    elif measured is None:
        cur.set_step(curation_id, "survey_report", "skipped", "no measured survey of RE's own to publish: run a survey first")
    else:
        try:
            res = gateway.publish_local_report(db, db.db_user, db.db_password, measured, registry=registry, submitted_by=author)
            _proof(registry, slug, P_REPORT, node_kind="database", element_guid=res.get("report_guid", ""),
                   curation_id=curation_id, detail={"annotation_count": res.get("annotation_count"),
                                                    "surveyed_at": measured.get("surveyed_at", "")})
            cur.set_step(curation_id, "survey_report", "done",
                         f"report {str(res.get('report_guid') or '?')[:8]} · {res.get('annotation_count')} annotations")
        except Exception as exc:
            cur.set_step(curation_id, "survey_report", "failed", f"{type(exc).__name__}: {exc}"[:400])

    # 4 ── Egeria's survey, limited to the chosen schemas by request parameter
    names = list(sel.get("survey_schemas") or [])
    bad = list(sel.get("survey_not_scopable") or [])
    if not db_guid:
        cur.set_step(curation_id, "survey", "skipped", "no database element")
    elif not names:
        cur.set_step(curation_id, "survey", "skipped",
                     "no schema the survey can be limited to" + (f" (a comma in: {', '.join(bad)})" if bad else "")
                     + ": not started, because an empty list would survey every schema")
    else:
        try:
            guid, process_qn = gateway.initiate_survey(db_guid, {"includeSchemaNames": ",".join(names)})
            registry.record_native_survey_submission("database", slug, process_qn, _now(),
                                                     engine_action_guid=guid, submitted_by=author)
            _proof(registry, slug, P_SURVEY, node_kind="database", element_guid=guid, curation_id=curation_id,
                   detail={"includeSchemaNames": names, "not_scopable": bad, "process": process_qn})
            cur.set_step(curation_id, "survey", "done",
                         f"{SURVEY_LINE}: {', '.join(names)} · engine action {guid[:8]}"
                         + (f" · not scopable (comma): {', '.join(bad)}" if bad else ""))
        except Exception as exc:
            registry.record_native_survey_submission("database", slug, "PostgreSQLSurvey::survey-postgres-database", _now(),
                                                     submit_error=f"{exc}"[:300], submitted_by=author)
            cur.set_step(curation_id, "survey", "failed", f"{type(exc).__name__}: {exc}"[:400])

    # 5 ── optional forced refresh (never a restart)
    if not sel.get("refresh_now"):
        cur.set_step(curation_id, "refresh", "skipped", "not asked: the cataloguer's own cycle will pick the targets up")
    elif not attach:
        cur.set_step(curation_id, "refresh", "skipped", "no target to refresh")
    else:
        try:
            gateway.refresh_connector(120)
            cur.set_step(curation_id, "refresh", "done", "the JDBC cataloguer connector was asked to refresh (about 16 s)")
        except Exception as exc:
            cur.set_step(curation_id, "refresh", "failed", f"{type(exc).__name__}: {exc}"[:400])

    # 6 ── read back: the proof every state word rests on
    cur.set_step(curation_id, "read_back", "running")
    try:
        schemas = sorted(set(attach))
        s = read_back(registry, gateway, slug, schemas, curation_id=curation_id, by=author)
        if s["read_failed"]:
            cur.set_step(curation_id, "read_back", "failed", f"{s['read_failed']} read(s) of Egeria failed; states are unchanged")
        else:
            cur.set_step(curation_id, "read_back", "done",
                         f"{s['catalogued']} catalogued · {s['attached_waiting']} attached, waiting")
    except Exception as exc:
        cur.set_step(curation_id, "read_back", "failed", f"{type(exc).__name__}: {exc}"[:400])
    return cur.finish(curation_id)
