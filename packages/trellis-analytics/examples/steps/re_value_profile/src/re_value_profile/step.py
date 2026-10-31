"""The code: `run(inputs) -> results`. One result per table of the latest value-profile batch, then one for the database.

A table is ``measured`` when at least one of its columns was; otherwise its most common column state stands in
(``not_measured``, ``not_permitted``, ``not_applicable``) with the most common reason, as RE's native screen groups
them. A table with no measured column is ``not_established`` and says why, never an empty profile. Per-field numbers
travel as one JSON text field (`Fields`): column, type, state, value, distinct, null and filled counts.
"""
from __future__ import annotations

import json

SUMMARY = "re_value_profile_summary"

STATE_ORDER = ("measured", "not_measured", "not_permitted", "not_applicable")
FIELD_NUMBERS = ("value_ct", "distinct_value_ct", "null_value_ct", "filled_value_ct")


def _plural(n: int, one: str) -> str:
    return f"{n:,} {one if n == 1 else one + 's'}"


def _rows_words(rec) -> str:
    return "rows not counted" if rec is None else ("0 rows · empty table" if rec == 0 else _plural(rec, "row"))


def _field(c: dict) -> dict:
    out = {"column": c["column_name"], "state": c.get("state") or "", "type": c.get("general_type") or "X",
           "record_ct": c.get("record_ct")}
    if out["state"] == "measured":
        out.update({k: c.get(k) for k in FIELD_NUMBERS})
    elif c.get("reason"):
        out["reason"] = c["reason"]
    return out


def _table(schema: str, table: str, columns: list[dict], as_of: str, ran_as: str = "") -> dict:
    scope = f"{schema}.{table}"
    counts: dict[str, int] = {}
    reasons: dict[str, int] = {}
    record = None
    for c in columns:
        st = c.get("state") or ""
        counts[st] = counts.get(st, 0) + 1
        if st == "measured":
            if record is None and c.get("record_ct") is not None:
                record = c["record_ct"]
        elif c.get("reason"):
            reasons[c["reason"]] = reasons.get(c["reason"], 0) + 1
    measured = counts.get("measured", 0)
    if not measured:
        state = max(counts, key=lambda s: counts[s]) if counts else ""
        reason = max(reasons, key=lambda r: reasons[r]) if reasons else ""
        why = reason or f"no column of this table was profiled ({state.replace('_', ' ') or 'state not recorded'})"
        # The columns' states and reasons travel too: a table that was not profiled is listed with why, per column.
        value = {"Table State": state, "Record Count": None, "Columns": len(columns), "Columns Measured": 0,
                 "Fields": json.dumps([_field(c) for c in columns], separators=(",", ":")), "asOf": as_of,
                 "Ran As": ran_as}
        return {"scope": scope, "state": "not_established", "reason": why, "value": value,
                "summary": f"{scope} · {state.replace('_', ' ') or 'state not recorded'}"
                           + (f" · {reason}" if reason else "")}
    total = len(columns)
    cols = (_plural(measured, "column") + " measured" if measured == total
            else f"{measured:,} of {_plural(total, 'column')} measured")
    value = {"Table State": "measured", "Record Count": record, "Columns": total, "Columns Measured": measured,
             "Fields": json.dumps([_field(c) for c in columns], separators=(",", ":")), "asOf": as_of,
                 "Ran As": ran_as}
    return {"scope": scope, "state": "measured", "value": value,
            "summary": f"{scope} · {_rows_words(record)} · {cols}"}


def run(inputs) -> list[dict]:
    batch = inputs.ods.value_profile_columns(inputs.slug)
    columns = batch.get("columns") or []
    if not batch.get("surveyed_at") or not columns:
        why = "no value profile is stored for this database yet: the quality survey has not run"
        return [{"scope": inputs.slug, "measure": SUMMARY, "state": "not_established", "reason": why,
                 "summary": "not measured · no value profile stored"}]
    as_of = str(batch["surveyed_at"])
    grouped: dict[tuple[str, str], list[dict]] = {}
    for c in columns:
        grouped.setdefault((c["schema_name"], c["table_name"]), []).append(c)
    results = [_table(s, t, grouped[(s, t)], as_of, str(batch.get("ran_as") or "")) for s, t in sorted(grouped)]
    states: dict[str, int] = {}
    for c in columns:
        states[c.get("state") or ""] = states.get(c.get("state") or "", 0) + 1
    tables_measured = sum(1 for r in results if r["state"] == "measured")
    rest = {k: n for k, n in states.items() if k != "measured" and n}
    tail = "".join(f" · {n:,} {k.replace('_', ' ')}" for k, n in sorted(rest.items()))
    value = {"Columns": len(columns), "Columns Measured": states.get("measured", 0), "Tables": len(results),
             "Tables Measured": tables_measured, "asOf": as_of}
    results.append({"scope": inputs.slug, "measure": SUMMARY, "state": "measured", "value": value,
                    "summary": f"{states.get('measured', 0):,} of {_plural(len(columns), 'column')} profiled{tail}."})
    return results
