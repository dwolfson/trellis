"""LS5 spike: RE's native analyses beside their Analytic Library twins, behind one flag.

`RE_SPIKE_LIBRARY_TWINS=1` makes the screens that read an analysis by its native id (the Questions rows, the publish
table, the Chat compile, the Value profile routes) read the library twin's stored result instead. Off, they read the
native path as before, and the twins' own ids are hidden from the declared lists (publish table, Chat compile) so the
native path is exactly today's. The native code is untouched either way. Nothing here writes.

The flag is read at every call (`enabled()`), never cached, so a test, or an operator restarting with it set, sees the
branch it asked for.
"""
from __future__ import annotations

import dataclasses
import os

FLAG = "RE_SPIKE_LIBRARY_TWINS"

#: native analysis id -> the library step id that is its twin.
TWINS = {"db_statistics_freshness": "re_statistics_freshness", "value_profile": "re_value_profile"}
_NATIVE_OF = {twin: native for native, twin in TWINS.items()}


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def twin_for(analysis_id: str) -> str:
    """The twin step id to read in place of `analysis_id`, or "" (flag off, or no twin)."""
    return TWINS.get(analysis_id, "") if enabled() else ""


def declared_entries(entries: list) -> list:
    """The catalogue entries a declared consumer iterates. Off: the twins' ids are left out. On: each twin's entry
    stands under its native id (its declaration, its words), so the consumer asks the fact layer for the native id and
    is answered from the twin's stored result."""
    if enabled():
        # The native entry of an id that has a twin gives way to the twin's, so the id is declared once.
        return [dataclasses.replace(e, id=_NATIVE_OF[e.id]) if e.id in _NATIVE_OF else e
                for e in entries if e.id not in TWINS]
    return [e for e in entries if e.id not in _NATIVE_OF]


def value_profile_from_twin(registry, slug: str) -> dict:
    """The shape `_value_profile_results` returns, rebuilt from `re_value_profile`'s stored per-table results ({} when
    the twin has not run). Carries what the twin stored per column (state, reason, type, record count and the four
    headline counts); the Value profile tab's per-column cells need the full measure row, which the twin does not
    carry, and are read from the native rows."""
    import json


    _run, rows = registry.query_step_annotations("database", slug, "re_value_profile")
    if not rows:
        return {}
    columns: list[dict] = []
    as_of = ran_as = ""
    for r in rows:
        props = (r.get("detail") or {}).get("resourceProperties") or {}
        as_of = as_of or props.get("asOf", "")
        ran_as = ran_as or props.get("Ran As", "")
        schema, _, table = str(r.get("scope") or "").partition(".")
        for f in json.loads(props.get("Fields") or "[]"):
            columns.append({"column_path": f"{schema}.{table}.{f['column']}", "schema_name": schema,
                            "table_name": table, "column_name": f["column"], "state": f.get("state", ""),
                            "reason": f.get("reason", ""), "general_type": f.get("type"),
                            "record_ct": f.get("record_ct"), **{k: f.get(k) for k in
                                                                ("value_ct", "distinct_value_ct", "null_value_ct",
                                                                 "filled_value_ct")}})
    states: dict[str, int] = {}
    for c in columns:
        states[c["state"]] = states.get(c["state"], 0) + 1
    return {"surveyed_at": as_of, "column_count": len(columns), "measured_count": states.get("measured", 0),
            "state_counts": states, "ran_as": ran_as, "columns": columns}
