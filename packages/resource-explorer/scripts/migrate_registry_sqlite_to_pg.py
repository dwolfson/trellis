"""
One-time migration: copy every row of RE's SQLite registry.db into the new
Postgres `resource_explorer` schema (Egeria Advisor's shared egeria_advisor
database — see PgVectorConfig/RegistryConfig in resource_explorer/config.py).

Generic, schema-introspecting migration (not one hand-written INSERT per
table like Egeria Advisor's own scripts/migrate_sqlite_to_pg.py, which this
otherwise mirrors structurally) — reads each table's real column list and
primary-key columns straight from SQLite's own PRAGMA table_info(), so it
can't drift out of sync with registry.py's schema the way a hand-maintained
column list would.

Idempotent/resumable: every insert is `ON CONFLICT (<pk>) DO UPDATE`, so
re-running after an interruption just re-applies the same rows. Writes go
through ProjectRegistry()'s own _conn()/PostgresCursorWrapper — the same
?-placeholder-translation and search_path machinery the app itself uses, not
a separate hand-rolled psycopg2 connection — so this migration exercises
exactly the same code path production writes will use.

Tables are migrated in dependency order (parents before FK-referencing
children — projects/databases/file_systems first) so foreign-key
constraints (enforced by Postgres, not by SQLite's default configuration)
never reject a row.

Usage:
    uv run --package resource-explorer \\
        python packages/resource-explorer/scripts/migrate_registry_sqlite_to_pg.py \\
        [--sqlite-path data/registry.db] [--dry-run] [--table NAME]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

# Dependency-safe order: parents (projects, databases, file_systems, and the
# handful of tables with no FK at all) before every table with a real FK to
# one of those three.
TABLE_ORDER = [
    "projects",
    "project_groups",
    "databases",
    "db_servers",
    "file_systems",
    "project_stats",
    "project_commits",
    "project_code_symbols",
    "project_aliases",
    "project_contributor_stats",
    "project_dependencies",
    "project_file_type_counts",
    "project_file_inventory",
    "project_egeria_surveys",
    "project_data_profiles",
    "database_surveys",
    "filesystem_surveys",
    "conversation_history",
    "activity_log",
    "resource_context",
    "resource_tags",
    "resource_feedback",
    "resource_curator_notes",
    "resource_schedules",
    "survey_definition_cache",
    "rfa_actions",
    "annotation_types",
]

# Tables with INTEGER PRIMARY KEY AUTOINCREMENT in SQLite (-> SERIAL in
# Postgres) — their sequence needs syncing to max(id)+1 after a data
# migration that explicitly supplies id values, or the next native INSERT
# would collide with a migrated row.
AUTOINCREMENT_TABLES = [
    "project_stats", "project_commits", "project_code_symbols",
    "project_contributor_stats", "conversation_history", "project_dependencies",
    "project_file_type_counts", "project_file_inventory", "project_egeria_surveys",
    "project_data_profiles", "database_surveys", "filesystem_surveys",
]


def table_columns_and_pk(sqlite_conn: sqlite3.Connection, table: str) -> tuple[list[str], list[str]]:
    """Returns (all_columns, pk_columns) straight from SQLite's own catalog —
    pk_columns ordered by their position within a composite key (PRAGMA
    table_info's `pk` field is 1-indexed position, 0 = not part of the PK)."""
    rows = sqlite_conn.execute(f"PRAGMA table_info({table})").fetchall()
    all_cols = [r["name"] for r in rows]
    pk_cols = [r["name"] for r in sorted((r for r in rows if r["pk"]), key=lambda r: r["pk"])]
    return all_cols, pk_cols


def migrate_table(sqlite_conn, registry, table: str, dry_run: bool) -> tuple[int, int]:
    """Returns (sqlite_row_count, migrated_count)."""
    all_cols, pk_cols = table_columns_and_pk(sqlite_conn, table)
    if not all_cols:
        print(f"  {table}: not found in source SQLite db — skipping")
        return (0, 0)

    rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
    if not rows:
        print(f"  {table}: empty — skipping")
        return (0, 0)

    print(f"  {table}: {len(rows)} rows" + (" (dry run)" if dry_run else " — migrating..."))
    if dry_run:
        return (len(rows), 0)

    col_list = ", ".join(all_cols)
    placeholders = ", ".join("?" for _ in all_cols)
    if pk_cols:
        conflict_cols = ", ".join(pk_cols)
        non_pk = [c for c in all_cols if c not in pk_cols]
        if non_pk:
            update_set = ", ".join(f"{c} = excluded.{c}" for c in non_pk)
            sql = (
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_set}"
            )
        else:
            sql = (
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_cols}) DO NOTHING"
            )
    else:
        sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"

    migrated = 0
    with registry._conn() as conn:
        for row in rows:
            values = tuple(row[c] for c in all_cols)
            conn.execute(sql, values)
            migrated += 1

    print(f"    -> {migrated} rows written")
    return (len(rows), migrated)


def sync_sequences(registry, tables: list[str]) -> None:
    """One connection/transaction PER TABLE — not one shared across the
    whole loop. Postgres aborts an entire transaction on its first failing
    statement (further statements on that same connection raise
    InFailedSqlTransaction regardless of Python-level try/except around
    them), so isolating each table's sync to its own transaction keeps one
    bad table from taking every table after it down with it."""
    print("Syncing Postgres sequences for AUTOINCREMENT tables...")
    for table in tables:
        if table not in TABLE_ORDER:
            continue
        try:
            with registry._conn() as conn:
                cur = conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}")
                max_id = cur.fetchone()[0]
                if max_id > 0:
                    # Postgres sequences start at 1 (min value 1) — setval(seq, 0, ...)
                    # is itself an out-of-bounds error, not a no-op. An empty table's
                    # sequence is already correctly at its default start; nothing to sync.
                    conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), ?, true)", (max_id,))
            print(f"  {table}: sequence synced to {max_id}" if max_id > 0 else f"  {table}: empty, nothing to sync")
        except Exception as exc:
            print(f"  {table}: sequence sync skipped ({exc})", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", default="data/registry.db")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--table", action="append", help="Restrict to specific table(s); repeatable")
    args = parser.parse_args()

    from resource_explorer.registry import ProjectRegistry

    sqlite_conn = sqlite3.connect(args.sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    registry = ProjectRegistry()  # picks up the Postgres default from config
    if not registry.database_url.startswith("postgresql"):
        print(
            f"registry.database_url is '{registry.database_url}', not Postgres — "
            "refusing to run (this script is only meaningful once Phase 4's cutover "
            "is live). Nothing was written.",
            file=sys.stderr,
        )
        return 1

    tables = args.table or TABLE_ORDER
    print(f"Migrating {len(tables)} table(s) from {args.sqlite_path} into {registry.database_url}"
          f"{' (dry run)' if args.dry_run else ''}:")

    grand_source = grand_migrated = 0
    for table in tables:
        src, mig = migrate_table(sqlite_conn, registry, table, args.dry_run)
        grand_source += src
        grand_migrated += mig

    sqlite_conn.close()

    print(f"\nTotals: {grand_migrated}/{grand_source} rows across {len(tables)} tables.")

    if not args.dry_run:
        sync_sequences(registry, [t for t in tables if t in AUTOINCREMENT_TABLES])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
