"""`postgres_value_profile`: measured (not estimated) per-column counts and date bounds, whole table.

DESIGN-VALUE-PROFILE-AND-QUALITY-CHECKS.md §4. One aggregate SELECT per table, assembled from the vendored
measure lines (`configdata/quality/testgen/postgresql/profile_measures.sql`) with each column's blocks chosen by
its `general_type`. Results are stored in `database_value_profiles` under the catalogue's own column names.

No sampling in slice 1: a table is profiled whole, or refused. Two bounds, both settings
(`config.ValueProfileSettings`): a row ceiling judged by `pg_class.reltuples` (over it, the table is
`not_measured` with the reason), and a statement timeout per query (a timeout or error is `not_measured` with
Postgres's words; a permission error is `not_permitted`). A view, materialized view or foreign table is
`not_applicable`. Every column the inventory names gets a row; a column that was not profiled has every measure
NULL, never zeros.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache

from resource_explorer.surveyors.database.quality.catalogue import POSTGRES_DIR, quote_identifier
from resource_explorer.surveyors.database.quality.general_type import (
    general_type as derive_general_type,
)

log = logging.getLogger(__name__)

PROFILE_TABLE = "database_value_profiles"
ANALYSIS_STEP = "postgres_value_profile"
PROFILE_MEASURES_SQL = POSTGRES_DIR / "profile_measures.sql"

#: The measures a profile row carries, in the vendored names. `record_ct` is per table.
COLUMN_MEASURES = ("value_ct", "distinct_value_ct", "null_value_ct", "zero_length_ct", "filled_value_ct",
                   "min_date", "max_date", "future_date_ct")
DATE_MEASURES = frozenset({"min_date", "max_date"})

#: Postgres's target-list limit is 1664 entries; columns are profiled in chunks well under it (each column
#: contributes at most six measures). Each chunk is its own scan.
COLUMNS_PER_QUERY = 200

_AS = re.compile(r"^(?P<expr>.*?)\s+AS\s+(?P<alias>[a-z_]+),?\s*$", re.DOTALL)


@lru_cache(maxsize=1)
def measure_blocks() -> dict[str, tuple[tuple[str, str], ...]]:
    """{TG-IF flag: ((expression, measure name), ...)} from the vendored subset, each expression verbatim."""
    blocks: dict[str, list[tuple[str, str]]] = {}
    flag: str | None = None
    pending: list[str] = []
    for line in PROFILE_MEASURES_SQL.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("-- TG-IF "):
            flag = stripped[len("-- TG-IF "):].strip()
            blocks.setdefault(flag, [])
            continue
        if stripped == "-- TG-ENDIF":
            if pending:
                raise ValueError(f"profile_measures.sql: unterminated measure in block {flag}: {pending}")
            flag = None
            continue
        if flag is None or not stripped or stripped.startswith("--"):
            continue
        pending.append(line)
        match = _AS.match("\n".join(pending).strip())
        if match and re.search(r"\bAS\s+[a-z_]+,?\s*$", line):
            blocks[flag].append((match.group("expr").strip(), match.group("alias")))
            pending = []
    return {k: tuple(v) for k, v in blocks.items()}


def flags_for(general_type: str) -> list[str]:
    """The vendored blocks that apply to a column of this general_type (upstream's flag meanings)."""
    flags = ["is_type_A"] if general_type == "A" else ["is_not_A"]
    if general_type not in ("A", "X"):
        flags.append("is_distinct_countable")
    if general_type == "D":
        flags.append("is_type_D")
    return flags


def run_date_text(surveyed_at: str) -> str:
    """The `{RUN_DATE}` literal: the profile's own instant as 'YYYY-MM-DD HH:MM:SS' (UTC)."""
    try:
        instant = datetime.fromisoformat(surveyed_at)
    except ValueError:
        instant = datetime.now(UTC)
    if instant.tzinfo is not None:
        instant = instant.astimezone(UTC)
    return instant.strftime("%Y-%m-%d %H:%M:%S")


def _fill(expr: str, column: str, run_date: str) -> str:
    # The template quotes "{COL_NAME}" itself, so the name goes in with only its double quotes doubled.
    return expr.replace('"{COL_NAME}"', quote_identifier(column)).replace("{RUN_DATE}", run_date)


def build_table_query(schema: str, table: str, columns: list[tuple[str, str]], run_date: str
                      ) -> tuple[str, dict[str, tuple[int, str]]]:
    """One SELECT over `schema.table` for `columns` [(name, general_type)]. Returns the SQL and
    {result alias: (column index, measure name)}; `record_ct` comes back under its own name."""
    blocks = measure_blocks()
    items = [f"{expr} AS record_ct" for expr, _ in blocks.get("is_table", ())]
    aliases: dict[str, tuple[int, str]] = {}
    for i, (name, gtype) in enumerate(columns):
        for flag in flags_for(gtype):
            for expr, measure in blocks.get(flag, ()):
                alias = f"c{i}__{measure}"
                items.append(f"{_fill(expr, name, run_date)} AS {alias}")
                aliases[alias] = (i, measure)
    sql = "SELECT\n" + ",\n".join(items) + f"\nFROM {quote_identifier(schema)}.{quote_identifier(table)}"
    return sql, aliases


def _value(measure: str, value):
    if value is None:
        return None
    if measure in DATE_MEASURES:
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        if isinstance(value, date):
            return value.isoformat()
        return str(value)
    if isinstance(value, Decimal):
        return int(value)
    return int(value) if isinstance(value, (int, float)) else value


def classify_error(exc: Exception) -> str:
    """not_permitted for a privilege error, not_measured for anything else (timeouts included)."""
    code = getattr(exc, "pgcode", None)
    text = str(exc).lower()
    if code == "42501" or "permission denied" in text:
        return "not_permitted"
    return "not_measured"


def error_text(exc: Exception) -> str:
    return " ".join(str(exc).split()) or type(exc).__name__


@dataclass
class ProfileBounds:
    max_table_rows: int
    statement_timeout_seconds: int


def _empty_row(schema: str, table: str, column: str, gtype: str, state: str, reason: str, ran_as: str) -> dict:
    row = {"schema_name": schema, "table_name": table, "column_name": column, "general_type": gtype,
           "record_ct": None, "sample_ratio": None, "state": state, "reason": reason, "ran_as": ran_as}
    row.update({m: None for m in COLUMN_MEASURES})
    return row


@dataclass(frozen=True)
class TableFacts:
    """What the catalog says about one table before it is read: its row estimate (None when never analysed),
    whether it is a partitioned parent, and whether row-level security would filter what this account sees."""

    estimate: int | None
    partitioned: bool
    rls_filters: bool


#: One catalog read for every table. `rls_filters`: RLS is on and this account neither bypasses it (superuser,
#: BYPASSRLS) nor owns the table without FORCE ROW LEVEL SECURITY, so COUNT(*) would count only its rows.
TABLE_FACTS_SQL = (
    "SELECT n.nspname AS schema_name, c.relname AS table_name, c.reltuples::BIGINT AS reltuples, "
    "c.relkind AS relkind, "
    "(c.relrowsecurity AND NOT (r.rolsuper OR r.rolbypassrls) "
    "AND (c.relforcerowsecurity OR NOT pg_has_role(c.relowner, 'USAGE'))) AS rls_filters "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "CROSS JOIN (SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user) r "
    "WHERE c.relkind IN ('r', 'p')"
)


def read_table_facts(conn) -> dict[tuple[str, str], TableFacts] | None:
    """{(schema, table): TableFacts}, or None when the catalog could not be read (callers then judge from the
    stored inventory). Ends its own transaction."""
    try:
        rows = conn.execute_query_isolated(TABLE_FACTS_SQL, None)
    except Exception as exc:
        log.warning("value profile: could not read pg_class: %s", exc)
        return None
    finally:
        conn.end_transaction()
    facts = {}
    for r in rows:
        tuples = r.get("reltuples")
        facts[(r["schema_name"], r["table_name"])] = TableFacts(
            estimate=int(tuples) if tuples is not None and int(tuples) >= 0 else None,
            partitioned=r.get("relkind") == "p",
            rls_filters=bool(r.get("rls_filters")),
        )
    return facts


def refusal(info: dict, facts: TableFacts | None, catalog_read: bool, bounds: ProfileBounds
            ) -> tuple[str, str] | None:
    """(state, reason) when a table must not be read, else None. Shared by the profile and the checks, so both
    refuse the same tables for the same reasons:

    - not a table (view, materialized view, foreign table) -> not_applicable;
    - a partitioned parent -> not_applicable (its partitions are read; reading the parent would scan them twice);
    - row-level security would filter this account's view -> not_permitted (a count of some rows is not a count);
    - size unknown (never analysed, and no stored count) -> not_measured: the scan is bounded, never open-ended;
    - over the row ceiling -> not_measured."""
    from resource_explorer.table_kinds import PARTITIONED_TABLE, is_table_type

    table_type = (info.get("table_type") or "").upper().replace("_", " ")
    if table_type and not is_table_type(table_type):
        return "not_applicable", f"a {table_type.lower()}, not a table: only tables are read"
    if table_type == PARTITIONED_TABLE or (facts is not None and facts.partitioned):
        return "not_applicable", "a partitioned parent: its partitions are read instead"
    if (facts is not None and facts.rls_filters) or (not catalog_read and info.get("has_row_security")):
        return "not_permitted", ("row-level security is on and this account does not bypass it, so its counts "
                                 "would cover only the rows it may see")
    estimate = facts.estimate if facts is not None and facts.estimate is not None else info.get("row_count")
    if estimate is None:
        return "not_measured", ("row count unknown (the table has never been analysed and no count is stored): "
                                "run ANALYZE so the row ceiling can be checked")
    if int(estimate) > bounds.max_table_rows:
        return "not_measured", (f"over the full-profile row ceiling ({int(estimate):,} > {bounds.max_table_rows:,}); "
                                "slice 1 reads whole tables only, never a sample")
    return None


def begin_read(conn, bounds: ProfileBounds) -> None:
    """Open one table's transaction: read-only, with the statement timeout. Pair with `conn.end_transaction()`."""
    conn.execute_query("SET TRANSACTION READ ONLY", None)
    conn.execute_query(f"SET LOCAL statement_timeout = {int(bounds.statement_timeout_seconds) * 1000}", None)


def run_value_profile(
    db_entity, registry, connect: Callable[[], AbstractContextManager], *,
    bounds: ProfileBounds, surveyed_at: str | None = None, ran_as: str = "",
) -> dict:
    """Profile every table the stored inventory names; store and return the batch.

    `connect()` returns a context manager yielding a DatabaseConnection (the adapter passes
    `database_connection(db_entity, credentials)`; tests pass a fake). A connection failure raises: the step
    failed, and nothing is stored, so the run cannot read as "profiled, nothing found"."""
    slug = db_entity.slug
    surveyed_at = surveyed_at or datetime.now(UTC).isoformat()
    columns = registry.query_detail_rows("database_columns", slug)
    if not columns:
        return {
            "value_profile": {
                "surveyed_at": surveyed_at, "state": "not_established",
                "reason": "no stored schema inventory: run the schema step first; nothing was profiled",
                "column_count": 0,
            },
            "annotations": [],
        }
    tables = {(t["schema_name"], t["table_name"]): t for t in registry.query_detail_rows("database_tables", slug)}
    by_table: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for col in columns:
        key = (col["schema_name"], col["table_name"])
        by_table.setdefault(key, []).append(
            (col["column_name"], derive_general_type(col.get("base_type") or col.get("data_type"),
                                                     col.get("column_size"))))

    run_date = run_date_text(surveyed_at)
    rows: list[dict] = []
    table_outcomes: list[dict] = []
    with connect() as conn:
        facts = read_table_facts(conn)
        for (schema, table), cols in sorted(by_table.items()):
            info = tables.get((schema, table)) or {}
            refused = refusal(info, (facts or {}).get((schema, table)), facts is not None, bounds)
            if refused:
                state, reason = refused
                rows.extend(_empty_row(schema, table, c, g, state, reason, ran_as) for c, g in cols)
                table_outcomes.append({"table": f"{schema}.{table}", "state": state, "reason": reason})
                continue
            failures: list[tuple[str, str]] = []
            for start in range(0, len(cols), COLUMNS_PER_QUERY):
                chunk = cols[start:start + COLUMNS_PER_QUERY]
                sql, aliases = build_table_query(schema, table, chunk, run_date)
                try:
                    # One read-only transaction per query, ended at once: no lock outlives its table. Params None,
                    # so psycopg2 never reads a "%" in a name as a placeholder.
                    begin_read(conn, bounds)
                    result = conn.execute_query_isolated(sql, None)
                except Exception as exc:
                    state, reason = classify_error(exc), error_text(exc)
                    failures.append((state, reason))
                    rows.extend(_empty_row(schema, table, c, g, state, reason, ran_as) for c, g in chunk)
                    continue
                finally:
                    conn.end_transaction()
                if not result:
                    reason = "the aggregate query returned no row"
                    failures.append(("not_measured", reason))
                    rows.extend(_empty_row(schema, table, c, g, "not_measured", reason, ran_as) for c, g in chunk)
                    continue
                values = result[0]
                record_ct = _value("record_ct", values.get("record_ct"))
                chunk_rows = [_empty_row(schema, table, c, g, "measured", "", ran_as) for c, g in chunk]
                for row in chunk_rows:
                    row["record_ct"] = record_ct
                for alias, (i, measure) in aliases.items():
                    chunk_rows[i][measure] = _value(measure, values.get(alias))
                rows.extend(chunk_rows)
            if failures:
                state, reason = failures[0]
                table_outcomes.append({"table": f"{schema}.{table}", "state": state, "reason": reason})

    registry.write_detail_rows(PROFILE_TABLE, slug, surveyed_at, rows=rows)
    states: dict[str, int] = {}
    for row in rows:
        states[row["state"]] = states.get(row["state"], 0) + 1
    return {
        "value_profile": {
            "surveyed_at": surveyed_at,
            "state": "measured" if states.get("measured") else "not_measured",
            "table_count": len(by_table),
            "column_count": len(rows),
            "states": states,
            "tables_not_profiled": table_outcomes,
            "ran_as": ran_as,
            "bounds": {"max_table_rows": bounds.max_table_rows,
                       "statement_timeout_seconds": bounds.statement_timeout_seconds},
        },
        "annotations": build_annotations(rows, table_outcomes),
    }


def build_annotations(rows: list[dict], table_outcomes: list[dict]) -> list:
    """One ResourceProfileAnnotation per measured column (counts in `value_count`, date bounds and the
    general_type in `json_properties`), and one ResourceMeasureAnnotation per table not profiled, carrying why."""
    from resource_explorer.surveyors.survey_report import (
        ResourceMeasureAnnotation,
        ResourceProfileAnnotation,
    )

    out: list = []
    for row in rows:
        if row["state"] != "measured":
            continue
        path = f"{row['schema_name']}.{row['table_name']}.{row['column_name']}"
        counts = {k: row[k] for k in ("record_ct",) + COLUMN_MEASURES
                  if k not in DATE_MEASURES and row.get(k) is not None}
        out.append(ResourceProfileAnnotation(
            summary=f"Value profile: {path} ({row['record_ct']:,} rows, {row.get('value_ct') or 0:,} with a value)"
            if row.get("record_ct") is not None else f"Value profile: {path}",
            analysis_step=ANALYSIS_STEP,
            annotation_type_name="Value Profile",
            check_name="value_profile",
            item_key=path,
            label="measured",
            value_count=counts,
            json_properties={
                "generalType": row["general_type"],
                "profileDates": {k: row.get(k) for k in DATE_MEASURES if row.get(k) is not None},
                "sampleRatio": None,
                "ranAs": row.get("ran_as", ""),
            },
        ))
    for outcome in table_outcomes:
        out.append(ResourceMeasureAnnotation(
            summary=f"Value profile: {outcome['table']} not profiled ({outcome['state']})",
            analysis_step=ANALYSIS_STEP,
            annotation_type_name="Value Profile",
            check_name="value_profile",
            item_key=outcome["table"],
            label=outcome["state"],
            confidence=0,
            explanation=outcome["reason"],
            resource_properties={"state": outcome["state"], "reason": outcome["reason"]},
        ))
    return out
