"""Tests for the catalog-only schema-enumeration fallback (design: REPLY-
DATABASE-CREDENTIAL-CAPABILITY-VISIBILITY.md §0, replying to
ASK-DATABASE-CREDENTIAL-CAPABILITY-VISIBILITY.md #251).

`information_schema.tables`/`.columns` (the source `PostgreSQLConnection.
get_schema_info()`/`_get_tables_for_schema()` normally reads) are
privilege-filtered by Postgres: a table with no `SELECT` grant on it simply
does not appear. `pg_class`/`pg_attribute`/`pg_namespace` are catalog
metadata and are not — any connected role can read them regardless of
`USAGE`/`SELECT` grants (the same fact `get_credential_capability()` relies
on, PR #253). `_catalog_only_fallback()` uses that gap to recover table
names, column names/types and an ANALYZE-time row estimate
(`pg_class.reltuples`) for tables `information_schema` hid entirely, tagging
them `STATE_CATALOG_ESTIMATE` rather than letting them look identical to a
fully, exactly measured row.

No live Postgres is used. `_FakeCursorConnection` is a real
`PostgreSQLConnection` with `execute_query` replaced by a fake dispatcher
keyed on substrings of the SQL text — the same "duck-typed stand-in records
the SQL it was asked to run" pattern `test_postgres_column_profile.py`'s
`_FakeSamplingConnection` uses, adapted to a connection that must answer
several *different* queries (schemas, PK, FK, information_schema tables/
columns, and now the two catalog-only queries) rather than one.

Three scenarios, matching the task's own three cases:

1. **Full access** — `information_schema` already sees every table in the
   schema; the fallback must never trigger, and behaviour (including exact
   PK/FK/nullable/default data) is unchanged.
2. **Zero access to a schema** — `information_schema` returns nothing for
   the schema; the fallback provides every table's name, column names/types
   and an estimated row count, all clearly marked.
3. **Partial access** — one table visible via `information_schema`, one
   only via the catalog; both appear, correctly and distinctly labeled.

A second block of tests covers the two downstream consumers this must flow
through to make "How big is this database" honest:
`database_rows_from_survey_data()` (turns the connection's dict into
`database_tables`/`database_columns` detail rows) and
`_schema_inventory_results`/`_row_count_snapshot_results` (the results
readers `facts.py` calls) plus `facts.py`'s own note text.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import (
    DatabaseEntity,
    ProjectRegistry,
    STATE_CATALOG_ESTIMATE,
    STATE_MEASURED,
)
from resource_explorer.surveyors.database.connection import PostgreSQLConnection
from resource_explorer.surveyors.result_materializer import database_rows_from_survey_data
from resource_explorer.surveyors.database.survey_definition_adapter import (
    _row_count_snapshot_results,
    _schema_inventory_results,
)


# ── low-level: PostgreSQLConnection._get_tables_for_schema() ───────────────


class _FakeCursorConnection(PostgreSQLConnection):
    """A real PostgreSQLConnection with `execute_query` swapped for a fake
    dispatcher, so `_get_tables_for_schema()`/`_catalog_only_fallback()` run
    for real against canned SQL responses — no live Postgres, no psycopg2.
    """

    def __init__(self, information_schema_tables, catalog_tables, catalog_columns):
        super().__init__(host="localhost", port=5432, database="x", user="u", password="p")
        #: {table_name: {"table_type": ..., "columns": [col_row, ...]}} — what
        #: information_schema.tables/columns would return for this schema.
        self._info_schema_tables = information_schema_tables
        #: {table_name: {"relkind": "r", "reltuples": N}} — what pg_class
        #: (unfiltered) says exists in this schema.
        self._catalog_tables = catalog_tables
        #: {table_name: [{"column_name", "ordinal_position", "data_type"}]}
        #: — what pg_attribute (unfiltered) says about a table's columns.
        self._catalog_columns = catalog_columns
        self.executed: list[str] = []

    def execute_query(self, query, params=()):
        self.executed.append(query)
        if "information_schema.table_constraints" in query and "PRIMARY KEY" in query:
            return []
        if "information_schema.table_constraints" in query and "FOREIGN KEY" in query:
            return []
        if "FROM information_schema.tables t" in query:
            rows = []
            for name, info in self._info_schema_tables.items():
                for col in info["columns"] or [None]:
                    row = {
                        "table_name": name,
                        "table_type": info["table_type"],
                        "table_description": "",
                        "column_name": col["column_name"] if col else None,
                        "data_type": col["data_type"] if col else None,
                        "udt_name": col["data_type"] if col else None,
                        "is_nullable": "YES" if col and col.get("nullable", True) else "NO",
                        "column_default": None,
                        "ordinal_position": col["ordinal_position"] if col else None,
                        "character_maximum_length": None,
                        "numeric_precision": None,
                        "numeric_scale": None,
                        "column_description": "",
                    }
                    rows.append(row)
            return rows
        if "c.relkind IN ('r', 'p', 'v', 'm')" in query:
            return [
                {"table_name": name, "relkind": info["relkind"], "reltuples": info["reltuples"]}
                for name, info in self._catalog_tables.items()
            ]
        if "FROM pg_attribute a" in query:
            table_name = params[1] if len(params) > 1 else None
            return list(self._catalog_columns.get(table_name, []))
        raise AssertionError(f"unexpected query in test fake: {query}")


def _schema(name="public"):
    return name


class TestFullAccessNeverTriggersFallback:
    def test_information_schema_already_has_every_catalog_table(self):
        conn = _FakeCursorConnection(
            information_schema_tables={
                "customers": {
                    "table_type": "BASE TABLE",
                    "columns": [
                        {"column_name": "id", "data_type": "integer",
                         "ordinal_position": 1, "nullable": False},
                    ],
                },
            },
            catalog_tables={"customers": {"relkind": "r", "reltuples": 20}},
            catalog_columns={},
        )
        tables = conn._get_tables_for_schema(_schema())
        assert len(tables) == 1
        assert tables[0]["name"] == "customers"
        assert tables[0]["source"] == "information_schema"
        assert tables[0]["columns"][0]["source"] == "information_schema"
        # No pg_attribute query should even have been issued, because the
        # catalog fallback has nothing to add.
        assert not any("FROM pg_attribute a" in q for q in conn.executed)


class TestZeroAccessToASchema:
    def test_catalog_fallback_recovers_every_table_and_its_columns(self):
        conn = _FakeCursorConnection(
            information_schema_tables={},  # egeria_user: no SELECT anywhere in coco_ods
            catalog_tables={
                "orders": {"relkind": "r", "reltuples": 1500},
                "line_items": {"relkind": "r", "reltuples": 42000},
            },
            catalog_columns={
                "orders": [
                    {"column_name": "id", "ordinal_position": 1, "data_type": "integer"},
                    {"column_name": "customer_id", "ordinal_position": 2, "data_type": "integer"},
                ],
                "line_items": [
                    {"column_name": "id", "ordinal_position": 1, "data_type": "bigint"},
                ],
            },
        )
        tables = conn._get_tables_for_schema(_schema("coco_ods"))
        by_name = {t["name"]: t for t in tables}
        assert set(by_name) == {"orders", "line_items"}

        orders = by_name["orders"]
        assert orders["source"] == "catalog_fallback"
        assert orders["row_count_estimate"] == 1500
        assert orders["row_count_basis"] == "estimated"
        assert [c["name"] for c in orders["columns"]] == ["id", "customer_id"]
        for col in orders["columns"]:
            assert col["source"] == "catalog_fallback"
            # Never guessed — see connection.py's docstring on why these
            # stay unestablished rather than a fabricated False.
            assert col["nullable"] is None
            assert col["is_primary_key"] is None
            assert col["type"]  # a real Postgres type name, not blank

        assert by_name["line_items"]["row_count_estimate"] == 42000


class TestPartialAccess:
    def test_visible_table_and_hidden_table_both_appear_correctly_labeled(self):
        conn = _FakeCursorConnection(
            information_schema_tables={
                "public_view_table": {
                    "table_type": "BASE TABLE",
                    "columns": [
                        {"column_name": "id", "data_type": "integer",
                         "ordinal_position": 1, "nullable": False},
                    ],
                },
            },
            catalog_tables={
                "public_view_table": {"relkind": "r", "reltuples": 5},
                "hidden_table": {"relkind": "r", "reltuples": 999},
            },
            catalog_columns={
                "hidden_table": [
                    {"column_name": "secret_id", "ordinal_position": 1, "data_type": "uuid"},
                ],
            },
        )
        tables = conn._get_tables_for_schema(_schema())
        by_name = {t["name"]: t for t in tables}
        assert set(by_name) == {"public_view_table", "hidden_table"}
        assert by_name["public_view_table"]["source"] == "information_schema"
        assert "row_count_estimate" not in by_name["public_view_table"]
        assert by_name["hidden_table"]["source"] == "catalog_fallback"
        assert by_name["hidden_table"]["row_count_estimate"] == 999


# ── database_rows_from_survey_data(): connection dict -> detail rows ───────


def _survey_data_with(schema_tables):
    return {
        "schema_info": {
            "schemas": [
                {"name": "coco_ods", "description": "", "tables": schema_tables},
            ],
            "total_tables": len(schema_tables),
            "total_columns": sum(len(t.get("columns") or []) for t in schema_tables),
        },
        "statistics": {},
        "views": [],
    }


class TestDatabaseRowsFromSurveyData:
    def test_catalog_fallback_table_gets_state_catalog_estimate(self):
        survey_data = _survey_data_with([
            {
                "name": "orders", "type": "BASE TABLE", "description": "",
                "source": "catalog_fallback",
                "row_count_estimate": 1500,
                "row_count_basis": "estimated",
                "columns": [
                    {"name": "id", "type": "integer", "base_type": "integer",
                     "nullable": None, "default": None, "position": 1,
                     "description": "", "is_primary_key": None,
                     "foreign_key": None, "source": "catalog_fallback"},
                ],
            },
        ])
        rows = database_rows_from_survey_data(survey_data)
        [table_row] = rows["database_tables"]
        assert table_row["state"] == STATE_CATALOG_ESTIMATE
        # No pg_stat_user_tables match was simulated (row_count absent) —
        # the reltuples estimate is what should have been used.
        assert table_row["row_count"] == 1500

        [col_row] = rows["database_columns"]
        assert col_row["state"] == STATE_CATALOG_ESTIMATE
        assert col_row["is_nullable"] is None
        assert col_row["is_primary_key"] is None

    def test_information_schema_table_still_gets_state_measured(self):
        survey_data = _survey_data_with([
            {
                "name": "customers", "type": "BASE TABLE", "description": "",
                "source": "information_schema", "row_count": 20,
                "columns": [
                    {"name": "id", "type": "integer", "base_type": "integer",
                     "nullable": False, "default": None, "position": 1,
                     "description": "", "is_primary_key": True,
                     "foreign_key": None, "source": "information_schema"},
                ],
            },
        ])
        rows = database_rows_from_survey_data(survey_data)
        [table_row] = rows["database_tables"]
        assert table_row["state"] == STATE_MEASURED
        assert table_row["row_count"] == 20
        [col_row] = rows["database_columns"]
        assert col_row["state"] == STATE_MEASURED
        assert col_row["is_nullable"] == 0
        assert col_row["is_primary_key"] == 1

    def test_catalog_fallback_table_with_a_real_stats_match_uses_that_not_the_estimate(self):
        # A rare case (design REPLY doc §3): a credential granted pg_monitor
        # can see pg_stat_user_tables for a table it still cannot SELECT
        # from. database_surveyor.py's _store_results would set a real
        # `row_count` in that case; this checks the materializer prefers it
        # over `row_count_estimate` when both are present.
        survey_data = _survey_data_with([
            {
                "name": "orders", "type": "BASE TABLE", "description": "",
                "source": "catalog_fallback", "row_count": 1502,
                "row_count_estimate": 1500, "row_count_basis": "estimated",
                "columns": [],
            },
        ])
        rows = database_rows_from_survey_data(survey_data)
        [table_row] = rows["database_tables"]
        assert table_row["row_count"] == 1502


# ── results readers: what facts.py actually sees ───────────────────────────


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def db_entity(registry):
    entity = DatabaseEntity(
        slug="coco_pharma", display_name="Coco Pharma", db_type="postgresql",
        host="localhost", port=5432, database_name="coco_pharma",
        db_user="egeria_user", db_password="secret",
    )
    registry.register_database(entity)
    return entity


def _write_tables(registry, slug, rows, surveyed_at="2026-09-24T00:00:00"):
    registry.write_detail_rows("database_tables", slug, surveyed_at, rows=rows)


def _write_columns(registry, slug, rows, surveyed_at="2026-09-24T00:00:00"):
    registry.write_detail_rows("database_columns", slug, surveyed_at, rows=rows)


class TestSchemaInventoryResultsSurfaceTheEstimate:
    def test_mixed_measured_and_catalog_estimate_tables(self, registry, db_entity):
        slug = db_entity.slug
        _write_tables(registry, slug, [
            {"schema_name": "public", "table_name": "customers",
             "table_type": "BASE TABLE", "row_count": 5, "state": STATE_MEASURED},
            {"schema_name": "coco_ods", "table_name": "orders",
             "table_type": "BASE TABLE", "row_count": 1500,
             "state": STATE_CATALOG_ESTIMATE},
        ])
        _write_columns(registry, slug, [
            {"schema_name": "public", "table_name": "customers",
             "column_name": "id", "state": STATE_MEASURED},
            {"schema_name": "coco_ods", "table_name": "orders",
             "column_name": "id", "state": STATE_CATALOG_ESTIMATE},
        ])

        value = _schema_inventory_results(registry, slug)
        assert value["table_count"] == 2
        assert value["catalog_only_table_count"] == 1
        by_name = {t["table_name"]: t for t in value["tables"]}
        assert by_name["customers"]["row_count_is_estimate"] is False
        assert by_name["orders"]["row_count_is_estimate"] is True

    def test_fully_measured_database_reports_zero_catalog_only(self, registry, db_entity):
        slug = db_entity.slug
        _write_tables(registry, slug, [
            {"schema_name": "public", "table_name": "customers",
             "table_type": "BASE TABLE", "row_count": 5, "state": STATE_MEASURED},
        ])
        value = _schema_inventory_results(registry, slug)
        assert value["catalog_only_table_count"] == 0
        assert value["tables"][0]["row_count_is_estimate"] is False


class TestRowCountSnapshotResultsLabelEstimates:
    def test_estimated_count_reported_alongside_measured_count(self, registry, db_entity):
        slug = db_entity.slug
        _write_tables(registry, slug, [
            {"schema_name": "public", "table_name": "customers",
             "table_type": "BASE TABLE", "row_count": 5, "state": STATE_MEASURED},
            {"schema_name": "coco_ods", "table_name": "orders",
             "table_type": "BASE TABLE", "row_count": 1500,
             "state": STATE_CATALOG_ESTIMATE},
        ])
        value = _row_count_snapshot_results(registry, slug)
        assert value["measured_count"] == 2
        assert value["estimated_count"] == 1
        assert value["total_row_count"] == 1505
        by_name = {t["table_name"]: t for t in value["tables"]}
        assert by_name["orders"]["row_count_is_estimate"] is True
        assert by_name["customers"]["row_count_is_estimate"] is False


# ── facts.py: the note a reader actually sees ───────────────────────────────


class TestFactsNoteCarriesTheCatalogCaveat:
    def test_note_states_catalog_visible_count_and_select_fraction(self):
        from resource_explorer.facts import FactLayer
        from resource_explorer.surveyors.result_status import MEASURED_WITHIN_CREDENTIAL_SCOPE

        value = {
            "table_count": 23,
            "catalog_only_table_count": 20,
            "_status": {
                "state": MEASURED_WITHIN_CREDENTIAL_SCOPE,
                "connected_as": "egeria_user",
                "fraction": "3 of 23 tables in 6 of 8 schemas",
            },
        }
        note = FactLayer._note_for(MEASURED_WITHIN_CREDENTIAL_SCOPE, value, {})
        # REPLY-COPY-REVIEW-CREDENTIAL-AND-FIT-LANGUAGE.md §3: the headline
        # (the count and who can read how much of it) leads, not the
        # parenthetical, and "catalog-only ones" -- a term coined in the same
        # sentence it's used -- became "the other N", computed rather than
        # left for the reader to work out.
        assert "23 tables, of which" in note
        assert "can read 3" in note
        assert "the other 20" in note
        assert "planner estimates, not exact" in note

    def test_note_falls_back_to_the_bare_fraction_with_no_catalog_recovery(self):
        from resource_explorer.facts import FactLayer
        from resource_explorer.surveyors.result_status import MEASURED_WITHIN_CREDENTIAL_SCOPE

        value = {
            "table_count": 3,
            "catalog_only_table_count": 0,
            "_status": {
                "state": MEASURED_WITHIN_CREDENTIAL_SCOPE,
                "connected_as": "egeria_user",
                "fraction": "3 of 26 tables in 6 of 8 schemas",
            },
        }
        note = FactLayer._note_for(MEASURED_WITHIN_CREDENTIAL_SCOPE, value, {})
        assert "visible via catalog" not in note
        assert "3 of 26 tables in 6 of 8 schemas" in note


