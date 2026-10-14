"""Level 1: the code. A plain callable, `run(inputs) -> results`.

It owns the measurement and its reason, and nothing else. `inputs` is what the wrapper hands it (here only the
ODS reader, because that is all the manifest declares); each result names its scope, its state and, when the
state is not a measurement, why.
"""
from __future__ import annotations


def _key(t: dict) -> str:
    return f"{t['schema_name']}.{t['table_name']}"


def _is_view(t: dict) -> bool:
    return str(t.get("table_type") or "").upper().replace("_", " ") == "VIEW"


def run(inputs) -> list[dict]:
    snaps = inputs.ods.row_count_snapshots(inputs.slug, limit=2)
    if not snaps:
        return [{"scope": inputs.slug, "state": "not_established",
                 "reason": "no survey has measured row counts for this database yet"}]
    latest = snaps[0]
    previous = {_key(t): t for t in snaps[1]["tables"]} if len(snaps) > 1 else None
    out = []
    for t in latest["tables"]:
        scope = _key(t)
        if _is_view(t):
            out.append({"scope": scope, "state": "not_applicable", "reason": "a view holds no rows of its own"})
            continue
        if previous is None:
            out.append({"scope": scope, "state": "not_established",
                        "reason": f"only one survey has measured row counts ({latest['surveyed_at']}); a change "
                                  "needs two"})
            continue
        before = previous.get(scope)
        if before is None:
            out.append({"scope": scope, "state": "not_established",
                        "reason": f"not in the previous survey ({snaps[1]['surveyed_at']})"})
            continue
        missing = [at for at, row in ((snaps[1]["surveyed_at"], before), (latest["surveyed_at"], t))
                   if row.get("row_count") is None]
        if missing:
            out.append({"scope": scope, "state": "not_established",
                        "reason": f"row count not measured in the survey of {' and '.join(missing)}"})
            continue
        b, a = int(before["row_count"]), int(t["row_count"])
        value = {"rowsBefore": b, "rowsAfter": a, "rowsChanged": a - b,
                 "previousSurvey": snaps[1]["surveyed_at"], "latestSurvey": latest["surveyed_at"]}
        if a == b:
            out.append({"scope": scope, "state": "nothing_found", "value": value,
                        "summary": f"no rows changed since {snaps[1]['surveyed_at']} ({a:,} rows)"})
        else:
            out.append({"scope": scope, "state": "measured", "value": value,
                        "summary": f"{a - b:+,} rows since {snaps[1]['surveyed_at']} ({b:,} → {a:,})"})
    return out
