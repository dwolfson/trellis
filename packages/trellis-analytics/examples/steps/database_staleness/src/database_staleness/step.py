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


#: The native PostgreSQL survey's per-table annotation and the measurements it carries (live, 2026-10-15): the
#: cumulative pg_stat counters, NOT a row count (Egeria's survey reports none).
TABLE_MEASUREMENTS = "Capture Database Table Measurements"
_COUNTERS = (("rowsInserted", "Number Of Rows Inserted"), ("rowsUpdated", "Number Of Rows Updated"),
             ("rowsDeleted", "Number Of Rows Deleted"))


def _report_scope(props: dict) -> str:
    qualified = str(props.get("Table Qualified Name") or "")
    parts = qualified.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else str(props.get("Table Name") or qualified)


def _from_report(inputs) -> list[dict]:
    """In an Egeria process: derive from the survey that just ran (the `source_report` input), not from an older
    stored inventory. Per table, the rows written (inserted + updated + deleted) that the survey measured, which
    PostgreSQL counts since its statistics were last reset; the report is named on every result."""
    report = inputs.source_report or {}
    guid = str(report.get("guid") or "")
    tables = [a for a in report.get("annotations") or [] if a.get("annotation_type") == TABLE_MEASUREMENTS]
    if not tables:
        return [{"scope": inputs.slug, "state": "not_established",
                 "reason": f"survey report {guid} carries no table measurements"}]
    out = []
    for a in tables:
        props = a.get("resource_properties") or {}
        scope = _report_scope(props)
        if str(props.get("Table Type") or "").upper().replace("_", " ") == "VIEW":
            out.append({"scope": scope, "state": "not_applicable", "reason": "a view holds no rows of its own"})
            continue
        counts = {}
        for key, name in _COUNTERS:
            try:
                counts[key] = int(str(props.get(name)).strip())
            except (TypeError, ValueError):
                counts[key] = None
        missing = [name for key, name in _COUNTERS if counts[key] is None]
        if missing:
            out.append({"scope": scope, "state": "not_established",
                        "reason": f"{', '.join(missing)} not measured in survey report {guid}"})
            continue
        written = sum(counts.values())
        value = {**counts, "rowsWritten": written, "sourceReport": guid}
        since = f"since PostgreSQL's statistics were last reset (survey report {guid[:8]})"
        if written == 0:
            out.append({"scope": scope, "state": "nothing_found", "value": value,
                        "summary": f"no rows written {since}"})
        else:
            out.append({"scope": scope, "state": "measured", "value": value,
                        "summary": f"{written:,} rows written {since}"})
    return out


def run(inputs) -> list[dict]:
    if getattr(inputs, "source_report", None):
        return _from_report(inputs)
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
