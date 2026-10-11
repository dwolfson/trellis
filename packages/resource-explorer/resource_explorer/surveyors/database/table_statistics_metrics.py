"""Per-table statistics-currency metrics: the ONE place their names live.

Owner (2026-10-09, backlog 7i): the per-table values that say how current the
planner statistics are "should all be part of the measurement annotations ...
they provide a notion of currency and correctness on the other statistics".

Egeria's own `PostgresDatabaseStatsExtractor` names the table metrics in its
`RelationalTableMetric` enum (propertyName, data type, display name,
description) and the database-level `RelationalDatabaseMetric.
LAST_STATISTICS_RESET`. It has NO table-level analyze, vacuum, dead-tuple or
pending-change metric. These were found in RE work and are meant to go back
into Egeria, so each entry below is written in the SAME style as that enum --
a camelCase property name, a data type from Egeria's `DataType` display names
("long", "date"), a display name and a one-sentence description -- so Egeria
can take them unchanged. Metrics Egeria already names carry `in_egeria=True`
and are copied verbatim; if upstream renames any of the PROPOSED ones, this is
the only file that changes.

PROPOSED FOR UPSTREAM (`in_egeria=False`): lastAnalyze, lastAutoAnalyze,
lastVacuum, lastAutoVacuum, numberOfRowsChangedSinceAnalyze, numberOfLiveRows,
numberOfDeadRows.

Published keys are DISPLAY NAMES
--------------------------------
Egeria keys a survey annotation's `resourceProperties` by `getDisplayName()`
("Number Of Rows Inserted", "Last statistics reset"; live-confirmed in
PROBES-2026-09-21.md), so RE publishes under the display names and the keys of
`metricsNotRead` are display names too. `property_name` stays here for the
upstream proposal and for RE-internal code.

Never versus not read -- the point of the helper below
------------------------------------------------------
Postgres reports NULL for `last_analyze` when a table has never been analysed.
That is a FINDING ("never analyzed"), and it is published as the stated value
`NEVER` ("never"). A value RE could not read is different: the key is ABSENT
and `metricsNotRead` names the reason. Neither is ever 0 or an empty string.
`LAST_STATISTICS_RESET` follows the same rule, reusing the word the registry
already stores for "Postgres said NULL: never reset".
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from resource_explorer.registry import STATS_NEVER_RESET

#: The stated value for "Postgres reports NULL: this has never happened".
NEVER = STATS_NEVER_RESET

#: Egeria `DataType` display names (DataType.LONG / DATE .getDisplayName()).
_LONG = "long"
_DATE = "date"

#: Key, on a table's measurement annotation, naming the metrics that were NOT
#: read and why: `{propertyName: reason}`. A metric appears either with a
#: stated value or here, never both.
NOT_READ_KEY = "metricsNotRead"

REASON_NO_STATS_ROW = (
    "pg_stat_user_tables had no row for this table, so none of its statistics "
    "were read"
)
REASON_NO_COUNTERS = (
    "the stored row for this table carries no pg_stat_user_tables counters "
    "(it was back-filled from a survey blob that did not read them)"
)
def read_failed_reason(error: str) -> str:
    return f"read failed ({error})"


REASON_RESET_NOT_READ = (
    "this survey did not read pg_stat_database.stats_reset"
)


@dataclass(frozen=True)
class TableMetric:
    """One table metric, in the shape of Egeria's `RelationalTableMetric`."""
    property_name: str   # Egeria-style propertyName (upstream proposal); the PUBLISHED key is display_name
    data_type: str       # Egeria DataType display name
    display_name: str
    description: str
    #: `database_table_activity` column that supplies the value ("" = the
    #: database-level stats-reset time, supplied separately).
    column: str
    #: True when Egeria's own metric enum already defines this metric.
    in_egeria: bool


# ── Metrics Egeria already defines (copied from RelationalTableMetric /
# RelationalDatabaseMetric verbatim) ─────────────────────────────────────────
NUMBER_OF_ROWS_INSERTED = TableMetric(
    "numberOfRowsInserted", _LONG, "Number Of Rows Inserted",
    "Count of the number of rows inserted into this table since the last statistics reset.",
    "rows_inserted", True)
NUMBER_OF_ROWS_UPDATED = TableMetric(
    "numberOfRowsUpdated", _LONG, "Number Of Rows Updated",
    "Count of the number of rows updated in this table since the last statistics reset.",
    "rows_updated", True)
NUMBER_OF_ROWS_DELETED = TableMetric(
    "numberOfRowsDeleted", _LONG, "Number Of Rows Deleted",
    "Count of the number of rows deleted from this table since the last statistics reset.",
    "rows_deleted", True)
#: Database-level in Egeria (RelationalDatabaseMetric). Repeated on each table
#: because a counter is only interpretable against the reset that began it.
LAST_STATISTICS_RESET = TableMetric(
    "lastStatisticsReset", _DATE, "Last statistics reset",
    "Last time that the statistics were reset in the database.",
    "", True)

TABLE_NAME = TableMetric(
    "tableName", "string", "Table Name", "Name of table.", "", True)
TABLE_QNAME = TableMetric(
    "tableQualifiedName", "string", "Table Qualified Name",
    "Qualified name of table showing the database name and schema name.", "", True)

# ── PROPOSED FOR UPSTREAM: same style, not yet in Egeria ─────────────────────
LAST_ANALYZE = TableMetric(
    "lastAnalyze", _DATE, "Last Analyze",
    "Last time this table was manually analyzed to refresh its planner statistics.",
    "last_analyze", False)
LAST_AUTO_ANALYZE = TableMetric(
    "lastAutoAnalyze", _DATE, "Last Auto Analyze",
    "Last time this table was analyzed by the autovacuum daemon to refresh its planner statistics.",
    "last_autoanalyze", False)
LAST_VACUUM = TableMetric(
    "lastVacuum", _DATE, "Last Vacuum",
    "Last time this table was manually vacuumed, not counting VACUUM FULL.",
    "last_vacuum", False)
LAST_AUTO_VACUUM = TableMetric(
    "lastAutoVacuum", _DATE, "Last Auto Vacuum",
    "Last time this table was vacuumed by the autovacuum daemon.",
    "last_autovacuum", False)
NUMBER_OF_ROWS_CHANGED_SINCE_ANALYZE = TableMetric(
    "numberOfRowsChangedSinceAnalyze", _LONG, "Number Of Rows Changed Since Analyze",
    "Estimated number of rows inserted, updated or deleted since this table's planner statistics "
    "were last analyzed.",
    "pending_changes", False)
NUMBER_OF_LIVE_ROWS = TableMetric(
    "numberOfLiveRows", _LONG, "Number Of Live Rows",
    "Estimated number of live rows in this table, from the statistics collector.",
    "live_tuples", False)
NUMBER_OF_DEAD_ROWS = TableMetric(
    "numberOfDeadRows", _LONG, "Number Of Dead Rows",
    "Estimated number of dead rows in this table that a vacuum has not yet reclaimed.",
    "dead_tuples", False)

#: Every metric a table's measurement annotation carries, in display order.
TABLE_STATISTICS_METRICS: tuple[TableMetric, ...] = (
    LAST_ANALYZE, LAST_AUTO_ANALYZE, LAST_VACUUM, LAST_AUTO_VACUUM,
    NUMBER_OF_ROWS_CHANGED_SINCE_ANALYZE, NUMBER_OF_LIVE_ROWS, NUMBER_OF_DEAD_ROWS,
    NUMBER_OF_ROWS_INSERTED, NUMBER_OF_ROWS_UPDATED, NUMBER_OF_ROWS_DELETED,
    LAST_STATISTICS_RESET,
)

#: The subset RE proposes for upstream.
PROPOSED_FOR_UPSTREAM: tuple[TableMetric, ...] = tuple(
    m for m in TABLE_STATISTICS_METRICS if not m.in_egeria)

_TIMESTAMP_METRICS = (LAST_ANALYZE, LAST_AUTO_ANALYZE, LAST_VACUUM, LAST_AUTO_VACUUM)
_COUNTER_FIELDS = (
    "rows_inserted", "rows_updated", "rows_deleted", "live_tuples", "dead_tuples",
    "seq_scan", "idx_scan",
)


def row_was_read_from_pg_stat(row: dict | None) -> bool:
    """Did this stored/fetched activity row come from a real
    `pg_stat_user_tables` read?

    `n_live_tup` is never NULL on a real read, so `live_tuples` is the proof.
    The native Egeria materializer writes inserted/updated/deleted counters
    too (`source='egeria'`) but never `live_tuples`, so counters alone are NOT
    proof, and a row from source 'egeria' never counts: a native row must not
    turn "not read" into "never". A row back-filled from an old survey blob
    carries timestamps at most.
    """
    if not row:
        return False
    if (row.get("source") or "") == "egeria":
        return False
    return row.get("live_tuples") is not None


def table_statistics_properties(
    row: dict | None, stats_reset: str | None,
    no_row_reason: str = REASON_NO_STATS_ROW,
) -> dict:
    """The `resourceProperties` for one table's statistics-currency metrics.

    `row` is a `database_table_activity`-shaped dict (or the identical
    `get_table_activity()` dict); `None` means the table has no row at all.
    `stats_reset` is the database's reset EVIDENCE: a timestamp string,
    `NEVER`, or `None` for "not read" (see `registry.STATS_NEVER_RESET`).

    Returns `{display name: value}` for every metric with a stated value, plus
    `metricsNotRead` ({display name: reason}) for the rest. Values are ints or
    strings; a counter that is a true zero stays `0`, and a NULL never becomes
    one.
    """
    props: dict = {}
    not_read: dict[str, str] = {}
    from_pg_stat = row_was_read_from_pg_stat(row)

    for metric in _TIMESTAMP_METRICS:
        value = (row or {}).get(metric.column)
        if value:
            props[metric.display_name] = str(value)
        elif from_pg_stat:
            props[metric.display_name] = NEVER      # Postgres said NULL
        else:
            not_read[metric.display_name] = (
                no_row_reason if row is None else REASON_NO_COUNTERS)

    for metric in (NUMBER_OF_ROWS_CHANGED_SINCE_ANALYZE, NUMBER_OF_LIVE_ROWS,
                   NUMBER_OF_DEAD_ROWS, NUMBER_OF_ROWS_INSERTED,
                   NUMBER_OF_ROWS_UPDATED, NUMBER_OF_ROWS_DELETED):
        value = (row or {}).get(metric.column)
        if value is None:
            not_read[metric.display_name] = (
                no_row_reason if row is None else REASON_NO_COUNTERS)
        else:
            props[metric.display_name] = int(value)

    if stats_reset:
        props[LAST_STATISTICS_RESET.display_name] = str(stats_reset)
    else:
        not_read[LAST_STATISTICS_RESET.display_name] = REASON_RESET_NOT_READ

    if not_read:
        props[NOT_READ_KEY] = not_read
    return props


def not_read_of(properties: dict) -> dict[str, str]:
    """`metricsNotRead` from a properties dict that may have been through
    `to_string_map` (where the dict became JSON text)."""
    value = properties.get(NOT_READ_KEY) or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, dict) else {}
