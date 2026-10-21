"""`run_quality_checks`: execute the accepted checks with the vendored Postgres SQL.

DESIGN-VALUE-PROFILE-AND-QUALITY-CHECKS.md §6. The input is the accepted verdicts (their parameters as accepted);
the SQL always comes from the vendored catalogue, keyed by test type, with every parameter validated by type
(`catalogue.render_measure`). Checks are batched one aggregate SELECT per table; if a batch errors, each of its
checks is re-run alone so one bad check cannot hide the others. Results go to `database_quality_results`.

**TestGen's NULL-means-pass trap is not copied.** TestGen computes `CASE WHEN measure op condition THEN fail
ELSE pass END`, so a NULL measure (Missing_Pct on an empty table, a zero baseline) falls through to pass. Here the
measure itself is read and mapped:

    NULL measure, or division by zero          -> not_established ("measure undefined ...")
    query error or timeout                     -> error, with Postgres's words
    privilege error, or row-level security     -> not_permitted
      that filters this account
    fails, severity error / warning / info     -> fail / warning / logged
    satisfies the condition                    -> pass
    table over the row ceiling, of unknown     -> not_measured (`value_profile.refusal`, shared with the profile)
      size, a partitioned parent or not a table
    parameter that does not validate           -> not_established, quoting the value
    column or table gone from the inventory    -> not_established ("... no longer in inventory")

**Egeria.** Accepted checks are not yet published as DataQualityRules (Publish is a later change), so every
check runs from its verdict row and is labelled `rule_source = unpublished`. When Publish lands, the rule read
from Egeria overrides the verdict's threshold, operator and severity here (design §6's table).

The baseline is the last ACCEPTED one, never the current profile, so a scheduled run of this step on its own is
valid; each result records the profile run it was measured against. Each table is read in its own read-only
transaction, ended at once, so no lock outlives its table.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from decimal import Decimal

from resource_explorer.surveyors.database.quality.catalogue import (
    MUST_BE,
    ParameterError,
    as_number,
    fails,
    load_catalogue,
    quote_identifier,
    render_measure,
    threshold,
)
from resource_explorer.surveyors.database.quality.value_profile import (
    ProfileBounds,
    begin_read,
    classify_error,
    error_text,
    read_table_facts,
    refusal,
    run_date_text,
)

RESULTS_TABLE = "database_quality_results"
ANALYSIS_STEP = "run_quality_checks"

#: severity -> the status a failing check gets (TestGen's Fail / Warning / Log).
FAIL_STATUS = {"error": "fail", "warning": "warning", "info": "logged"}
#: Statuses that reached a conclusion; only these will become QualityAnnotations when publishing lands.
CONCLUDED = frozenset({"pass", "warning", "fail", "logged"})
#: A table the shared refusal rules will not read: its state -> the check's status.
_REFUSED_STATUS = {"not_applicable": "not_measured", "not_measured": "not_measured", "not_permitted": "not_permitted"}
RULE_UNPUBLISHED = "unpublished"
UNDEFINED = "measure undefined (empty table / zero baseline)"


def _resolve(registry, key: str, verdict: dict) -> tuple[str, str, str, str] | None:
    """(schema, table, column, test_type) for an accepted check: from the proposal it accepted, else parsed from
    the key when that is unambiguous. None when it cannot be told."""
    proposal = registry.get_quality_proposal(verdict.get("proposal_id"))
    if proposal and proposal.get("check_key") == key and proposal.get("database_slug") == verdict.get("database_slug"):
        return (proposal["schema_name"], proposal["table_name"], proposal.get("column_name") or "",
                proposal["test_type"])
    path, sep, test_type = key.rpartition("::")
    parts = path.split(".")
    if not sep or len(parts) not in (2, 3):
        return None
    return parts[0], parts[1], parts[2] if len(parts) == 3 else "", test_type


def _number(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value) if isinstance(value, (int, float)) else value


def run_quality_checks(
    db_entity, registry, connect: Callable[[], AbstractContextManager], *,
    bounds: ProfileBounds, surveyed_at: str | None = None, ran_as: str = "",
) -> dict:
    slug = db_entity.slug
    surveyed_at = surveyed_at or datetime.now(UTC).isoformat()
    accepted = {k: v for k, v in registry.get_quality_verdicts(slug).items() if v.get("verdict") == "accepted"}
    if not accepted:
        return {"quality_checks": {
            "surveyed_at": surveyed_at, "state": "not_established",
            "reason": "no accepted quality checks: accept proposals in Curate first; nothing was run",
        }}

    catalogue = load_catalogue()
    columns = registry.query_detail_rows("database_columns", slug)
    column_set = {(c["schema_name"], c["table_name"], c["column_name"]) for c in columns}
    table_set = {(c["schema_name"], c["table_name"]) for c in columns}
    tables = {(t["schema_name"], t["table_name"]): t for t in registry.query_detail_rows("database_tables", slug)}
    run_date = run_date_text(surveyed_at)

    results: list[dict] = []
    runnable: dict[tuple[str, str], list[dict]] = {}

    for key, verdict in sorted(accepted.items()):
        params = verdict.get("params_json")
        row = {"check_key": key, "schema_name": "", "table_name": "", "column_name": "", "test_type": "",
               "measure": None, "record_ct": None, "status": "not_established", "reason": "",
               "severity": "", "comparison_operator": "", "threshold_values_json": None,
               "params_json": params if isinstance(params, dict) else None,
               "baseline_profile_surveyed_at": (params or {}).get("profile_surveyed_at", "")
               if isinstance(params, dict) else "",
               "rule_source": RULE_UNPUBLISHED, "rule_guid": "", "ran_as": ran_as, "state": "not_measured"}
        results.append(row)
        resolved = _resolve(registry, key, verdict)
        if resolved is None:
            row["reason"] = f"cannot tell which column {key!r} names"
            continue
        schema, table, column, type_name = resolved
        row.update(schema_name=schema, table_name=table, column_name=column, test_type=type_name)
        test_type = catalogue.get(type_name)
        if test_type is None:
            row["reason"] = f"{type_name!r} is not a test type in the vendored catalog"
            continue
        if test_type.is_table_check == bool(column):
            scope = "a table" if test_type.is_table_check else "a column"
            row["reason"] = f"{type_name} is {scope} check, but {key!r} does not name {scope}"
            continue
        if not isinstance(params, dict):
            row["reason"] = f"the accepted parameters are not a JSON object: {params!r}"
            continue
        if (schema, table) not in table_set:
            row["reason"] = "table no longer in inventory"
            continue
        if column and (schema, table, column) not in column_set:
            row["reason"] = "column no longer in inventory"
            continue
        severity = params.get("severity")
        if severity not in FAIL_STATUS:
            row["reason"] = f"severity must be one of {sorted(FAIL_STATUS)}, got {severity!r}"
            continue
        row["severity"] = severity
        row["comparison_operator"] = MUST_BE.get(test_type.test_operator, test_type.test_operator)
        try:
            limit = threshold(test_type, params)
            row["threshold_values_json"] = [limit]
            if "{BASELINE_CT}" in test_type.measure and as_number("baseline_ct", params.get("baseline_ct")) == 0:
                row["reason"] = f"{UNDEFINED}: baseline_ct is 0"
                continue
            sql = render_measure(test_type, column, params, run_date)
        except ParameterError as exc:
            row["reason"] = str(exc)
            continue
        runnable.setdefault((schema, table), []).append({"row": row, "sql": sql, "type": test_type, "limit": limit})

    if runnable:
        with connect() as conn:
            facts = read_table_facts(conn)
            for (schema, table), checks in sorted(runnable.items()):
                refused = refusal(tables.get((schema, table)) or {}, (facts or {}).get((schema, table)),
                                  facts is not None, bounds)
                if refused:
                    for check in checks:
                        check["row"].update(status=_REFUSED_STATUS[refused[0]], reason=refused[1])
                    continue
                _run_table(conn, schema, table, checks, bounds)

    for row in results:
        if row["status"] in CONCLUDED:
            row["state"] = "measured"
    registry.write_detail_rows(RESULTS_TABLE, slug, surveyed_at, rows=results)
    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"quality_checks": {
        "surveyed_at": surveyed_at,
        "state": "measured" if any(r["status"] in CONCLUDED for r in results) else "not_established",
        "check_count": len(results),
        "status_counts": counts,
        "ran_as": ran_as,
    }}


def _select(schema: str, table: str, measures: list[str]) -> str:
    items = ["COUNT(*) AS record_ct"] + [f"{m} AS q{i}" for i, m in enumerate(measures)]
    return "SELECT " + ", ".join(items) + f" FROM {quote_identifier(schema)}.{quote_identifier(table)}"


def _conclude(check: dict, measure, record_ct) -> None:
    row = check["row"]
    row["record_ct"] = int(record_ct) if record_ct is not None else None
    value = _number(measure)
    if value is None:
        row.update(status="not_established", reason=UNDEFINED)
        return
    row["measure"] = value
    test_type = check["type"]
    if fails(test_type, value, check["limit"]):
        row["status"] = FAIL_STATUS[row["severity"]]
        row["reason"] = f"{test_type.measure_uom or 'measure'} {value:g} {test_type.test_operator} {check['limit']}"
    else:
        row["status"] = "pass"
        row["reason"] = f"{test_type.measure_uom or 'measure'} {value:g} (fails when {test_type.test_operator} " \
                        f"{check['limit']})"


def _failed(check: dict, exc: Exception) -> None:
    text = error_text(exc)
    if "division by zero" in text.lower():
        check["row"].update(status="not_established", reason=f"{UNDEFINED}: {text}")
    elif classify_error(exc) == "not_permitted":
        check["row"].update(status="not_permitted", reason=text)
    else:
        check["row"].update(status="error", reason=text)


def _query(conn, sql: str, bounds: ProfileBounds) -> list[dict]:
    """One read-only transaction for one statement, ended at once so no lock outlives it. Params None, so
    psycopg2 never reads a "%" in a name or a placeholder value as a parameter marker."""
    try:
        begin_read(conn, bounds)
        return conn.execute_query_isolated(sql, None)
    finally:
        conn.end_transaction()


def _no_row(check: dict) -> None:
    check["row"].update(status="error", reason="the aggregate query returned no row")


def _run_table(conn, schema: str, table: str, checks: list[dict], bounds: ProfileBounds) -> None:
    """One aggregate SELECT for the table's checks; on error, each check alone (TestGen's CAT fallback)."""
    try:
        result = _query(conn, _select(schema, table, [c["sql"] for c in checks]), bounds)
    except Exception:
        result = None
    if result is not None:
        for i, check in enumerate(checks):
            if result:
                _conclude(check, result[0].get(f"q{i}"), result[0].get("record_ct"))
            else:
                _no_row(check)
        return
    for check in checks:
        try:
            result = _query(conn, _select(schema, table, [check["sql"]]), bounds)
        except Exception as exc:
            _failed(check, exc)
            continue
        if result:
            _conclude(check, result[0].get("q0"), result[0].get("record_ct"))
        else:
            _no_row(check)
