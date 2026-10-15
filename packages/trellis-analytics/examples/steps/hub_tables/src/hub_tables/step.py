"""The code: `run(inputs) -> results`. It owns the measurement and its reasons, and nothing else.

From the newest column survey's keys (`inputs.ods.table_keys`), per table:

- **foreign keys out**: the distinct OTHER tables this table's foreign keys reference. Established only when this
  table's keys were captured (a native survey leaves them unstated, and then "no foreign keys" is not known);
- **foreign keys in**: the distinct other stored tables that reference this one. Established only when EVERY table's
  keys were captured: a table whose keys were never read could be referencing this one, so 0 is only a finding when
  nothing was left unread (the rule `db_derived.derive_hub_tables` uses).

Then the second measure, `hub_table_proposal`: each table referenced by at least `HUB_MIN_REFERENCING` other tables
is proposed as a "hub table" in a ClassificationAnnotation. A proposal on the report, never a classification on the
element (owner, 2026-10-15); Curate is where a proposal becomes a fact. Self-references are not counted. A view has no
keys of its own and is not applicable.
"""
from __future__ import annotations

#: The second measure: the hub proposal, published as a ClassificationAnnotation.
PROPOSAL = "hub_table_proposal"
#: The classification proposed.
HUB = "hub table"
#: A hub is referenced by at least this many other tables.
HUB_MIN_REFERENCING = 3

CAVEAT = ("foreign keys as the column survey stored them; a degree counts distinct other tables, self-references "
          "not counted; 'foreign keys in' counts only stored tables and is established only when every table's keys "
          "were captured; a hub is a proposal, never a classification on the table")


def _is_view(t: dict) -> bool:
    return "VIEW" in str(t.get("table_type") or "").upper()


def _absent(scope: str, reason: str, words: str, measure: str = "") -> dict:
    out = {"scope": scope, "state": "not_established", "reason": reason, "summary": f"not measured · {words}"}
    if measure:
        out["measure"] = measure
    return out


def _names(keys) -> str:
    names = sorted(f"{s}.{t}" for s, t in keys)
    return ", ".join(names[:20]) + (f" (and {len(names) - 20} more)" if len(names) > 20 else "")


def run(inputs) -> list[dict]:
    slug = inputs.slug
    snap = inputs.ods.table_keys(slug)
    if snap is None:
        why = "no survey has stored this database's columns yet, so no keys were read"
        return [_absent(slug, why, "no columns stored"), _absent(slug, why, "no columns stored", PROPOSAL)]
    as_of = snap["surveyed_at"]
    views = [t for t in snap["tables"] if _is_view(t)]
    tables = [t for t in snap["tables"] if not _is_view(t)]
    captured = [t for t in tables if t["keys_captured"]]
    if not captured:
        why = (f"no keys captured for any of {len(tables)} tables in the column survey of {as_of}; hubs cannot be "
               "derived")
        return [_absent(slug, why, "no keys captured; hubs cannot be derived"),
                _absent(slug, why, "no keys captured; hubs cannot be derived", PROPOSAL)]

    keys = {(t["schema_name"], t["table_name"]) for t in tables}
    every = len(captured) == len(tables)
    referencing: dict[tuple[str, str], set] = {k: set() for k in keys}
    referenced: dict[tuple[str, str], set] = {}
    for t in tables:
        me = (t["schema_name"], t["table_name"])
        targets = {(fk["to_schema"], fk["to_table"]) for fk in t["foreign_keys"]} - {me}
        referenced[me] = targets
        if t["keys_captured"]:
            for dst in targets & keys:
                referencing[dst].add(me)
    uncaptured = len(tables) - len(captured)
    in_unknown = (f"referenced-by not established: keys not captured for {uncaptured} of {len(tables)} tables"
                  if not every else "")

    out: list[dict] = []
    for t in tables:
        me = (t["schema_name"], t["table_name"])
        scope = f"{me[0]}.{me[1]}"
        fk_out = len(referenced[me]) if t["keys_captured"] else None
        fk_in = len(referencing[me]) if every else None
        if fk_out is None and fk_in is None:
            out.append(_absent(scope, f"keys not captured for this table, and {in_unknown}",
                               "keys not captured for this table"))
            continue
        value = {"Foreign Keys Out": fk_out, "Foreign Keys In": fk_in,
                 "Referenced Tables": _names(referenced[me]) if fk_out else None,
                 "Referencing Tables": _names(referencing[me]) if fk_in else None,
                 "asOf": as_of, "basis": CAVEAT}
        bits = []
        bits.append(f"references {fk_out} other table{'s' if fk_out != 1 else ''}" if fk_out is not None
                    else "references: not established, keys not captured for this table")
        bits.append(f"referenced by {fk_in} other table{'s' if fk_in != 1 else ''}" if fk_in is not None
                    else in_unknown)
        established = [v for v in (fk_out, fk_in) if v is not None]
        reason = "" if fk_in is not None and fk_out is not None else (
            in_unknown if fk_in is None else "keys not captured for this table")
        out.append({"scope": scope, "state": "measured" if any(established) else "nothing_found", "value": value,
                    "reason": reason, "summary": f"{'; '.join(bits)} (as of {as_of})"})
    for v in views:
        out.append({"scope": f"{v['schema_name']}.{v['table_name']}", "state": "not_applicable",
                    "reason": "a view has no keys of its own", "summary": "not applicable · a view has no keys"})

    if not every:
        out.append(_absent(slug, f"{in_unknown}; a table they reference could be a hub, so no hub is proposed",
                           "keys not captured for every table; no hub proposed", PROPOSAL))
        return out
    hubs = sorted((k for k in keys if len(referencing[k]) >= HUB_MIN_REFERENCING),
                  key=lambda k: (-len(referencing[k]), k))
    if not hubs:
        out.append({"scope": slug, "measure": PROPOSAL, "state": "nothing_found",
                    "value": {"Hub Threshold": HUB_MIN_REFERENCING, "asOf": as_of, "basis": CAVEAT},
                    "summary": f"no table is referenced by {HUB_MIN_REFERENCING} or more other tables "
                               f"(as of {as_of})"})
        return out
    for k in hubs:
        n = len(referencing[k])
        out.append({"scope": f"{k[0]}.{k[1]}", "measure": PROPOSAL, "state": "measured",
                    "candidate_classifications": [HUB],
                    "value": {"Foreign Keys In": n, "Foreign Keys Out": len(referenced[k]),
                              "Hub Threshold": HUB_MIN_REFERENCING, "Referencing Tables": _names(referencing[k]),
                              "asOf": as_of, "basis": CAVEAT},
                    "summary": f"proposed: {HUB} · referenced by {n} other tables (as of {as_of})"})
    return out
