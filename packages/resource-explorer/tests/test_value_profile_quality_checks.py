"""The three steps of DESIGN-VALUE-PROFILE-AND-QUALITY-CHECKS.md, against a fake Postgres connection.

Every absence state the design names has a test here:
- profile: over the row ceiling and timeout/error (not_measured), no privilege (not_permitted), a view
  (not_applicable), an empty table (measured, a real zero), never a row of zeros, no inventory, no connection;
- propose: a NULL rule input (not_established, by column), an unprofiled column, an empty table, the
  rejected/accepted verdict rules;
- run: a NULL measure (not_established, never TestGen's pass), a zero baseline, division by zero, a query error
  (error), over the ceiling (not_measured), a column gone from the inventory, a parameter that does not
  validate, no accepted checks.
"""
from __future__ import annotations

import re
from contextlib import contextmanager

import pytest

from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors.database.quality.propose import run_propose
from resource_explorer.surveyors.database.quality.run_checks import run_quality_checks
from resource_explorer.surveyors.database.quality.value_profile import (
    COLUMN_MEASURES,
    ProfileBounds,
    run_value_profile,
)

SLUG = "coco_ods"
INVENTORY_AT = "2026-10-20T09:00:00+00:00"
PROFILED_AT = "2026-10-20T10:00:00+00:00"
BOUNDS = ProfileBounds(max_table_rows=5_000_000, statement_timeout_seconds=60)


class PgError(Exception):
    def __init__(self, message: str, pgcode: str | None = None):
        super().__init__(message)
        self.pgcode = pgcode


PERMISSION = PgError('permission denied for table secret', "42501")
TIMEOUT = PgError("canceling statement due to statement timeout", "57014")

#: (schema, table) -> table_type, row_count, [(column, type)]
INVENTORY = {
    ("sales", "orders"): ("BASE TABLE", 1000, [("order_id", "integer"), ("note", "text"),
                                               ("placed", "date"), ("payload", "jsonb")]),
    ("sales", "v_orders"): ("VIEW", None, [("order_id", "integer")]),
    ("sales", "big"): ("BASE TABLE", 9_000_000, [("id", "integer")]),
    ("sales", "secret"): ("BASE TABLE", 10, [("ssn", "text")]),
    ("sales", "slow"): ("BASE TABLE", 10, [("id", "integer")]),
    ("sales", "empty"): ("BASE TABLE", 0, [("d", "date")]),
}

#: Profile answers per table: record_ct and each column's measures, in ordinal order.
PROFILE = {
    ("sales", "orders"): {"record_ct": 1000, "columns": [
        {"value_ct": 1000, "distinct_value_ct": 1000, "null_value_ct": 0},
        {"value_ct": 900, "distinct_value_ct": 40, "null_value_ct": 100, "zero_length_ct": 0, "filled_value_ct": 3},
        {"value_ct": 1000, "distinct_value_ct": 365, "null_value_ct": 0, "min_date": "2020-01-01",
         "max_date": "2026-10-01", "future_date_ct": 0},
        {"value_ct": 10, "null_value_ct": 990},
    ]},
    ("sales", "secret"): PERMISSION,
    ("sales", "slow"): TIMEOUT,
    ("sales", "empty"): {"record_ct": 0, "columns": [
        {"value_ct": 0, "distinct_value_ct": 0, "null_value_ct": None, "min_date": None, "max_date": None,
         "future_date_ct": None}]},
}

_FROM = re.compile(r'FROM "([^"]+)"\."([^"]+)"\s*$')


class FakeConn:
    """Answers the profile's and the checks' SELECTs from canned values; records every statement."""

    def __init__(self, profile=None, checks=None, reltuples=None, facts=None, catalog_error=None):
        self.profile = profile or {}
        self.checks = checks or {}
        self.reltuples = {("sales", "big"): 9_000_000} if reltuples is None else reltuples
        self.facts = facts or {}  # (schema, table) -> {"relkind": ..., "rls_filters": ...}
        self.catalog_error = catalog_error
        self.statements: list[str] = []
        self.in_read_only = False

    @staticmethod
    def _psycopg2(sql, params):
        # psycopg2 applies %-substitution whenever params is not None, even an empty tuple.
        if params is not None and "%" in sql:
            raise IndexError("tuple index out of range")

    def execute_query(self, sql, params=()):
        self._psycopg2(sql, params)
        self.statements.append(sql)
        if sql == "SET TRANSACTION READ ONLY":
            self.in_read_only = True
        return []

    def end_transaction(self):
        self.statements.append("<end transaction>")
        self.in_read_only = False

    def execute_query_isolated(self, sql, params=()):
        self._psycopg2(sql, params)
        self.statements.append(sql)
        if "FROM pg_class" in sql:
            if self.catalog_error:
                raise self.catalog_error
            keys = set(self.reltuples) | set(self.facts)
            return [{"schema_name": s, "table_name": t, "reltuples": self.reltuples.get((s, t), -1),
                     "relkind": "r", "rls_filters": False, **self.facts.get((s, t), {})} for s, t in keys]
        assert self.in_read_only, "a table was read outside a read-only transaction"
        table = _FROM.search(sql).groups()
        if sql.startswith("SELECT COUNT(*) AS record_ct, "):
            return self._check(table, sql)
        spec = self.profile[table]
        if isinstance(spec, Exception):
            raise spec
        row = {"record_ct": spec["record_ct"]}
        for alias in re.findall(r"AS (c(\d+)__([a-z_]+))", sql):
            name, index, measure = alias
            row[name] = spec["columns"][int(index)].get(measure)
        return [row]

    def _check(self, table, sql):
        handler = self.checks[table]
        if isinstance(handler, Exception):
            raise handler
        body = sql[len("SELECT COUNT(*) AS record_ct, "):_FROM.search(sql).start()].rstrip()
        parts = re.split(r" AS (q\d+)(?:, )?", body)
        measures = dict(zip(parts[1::2], parts[0::2]))
        return [{"record_ct": handler.get("record_ct"), **{q: handler["measure"](m) for q, m in measures.items()}}]


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    reg.register_database(DatabaseEntity(slug=SLUG, display_name="Coco ODS", db_type="postgresql",
                                         host="localhost", port=5442, database_name="coco_ods"))
    tables, columns = [], []
    for (schema, table), (table_type, row_count, cols) in INVENTORY.items():
        tables.append({"schema_name": schema, "table_name": table, "table_type": table_type, "row_count": row_count})
        for i, (name, data_type) in enumerate(cols, start=1):
            columns.append({"schema_name": schema, "table_name": table, "column_name": name,
                            "ordinal_position": i, "data_type": data_type, "base_type": data_type})
    reg.write_detail_rows("database_tables", SLUG, INVENTORY_AT, rows=tables)
    reg.write_detail_rows("database_columns", SLUG, INVENTORY_AT, rows=columns)
    return reg


@pytest.fixture
def entity(registry):
    return registry.get_database(SLUG)


def _connect(conn):
    @contextmanager
    def connect():
        yield conn
    return connect


def _profile(registry, entity, conn=None, at=PROFILED_AT):
    conn = conn or FakeConn(profile=PROFILE)
    return run_value_profile(entity, registry, _connect(conn), bounds=BOUNDS, surveyed_at=at, ran_as="surveyor"), conn


def _rows(registry, table):
    return {(r["schema_name"], r["table_name"], r["column_name"]): r for r in registry.query_detail_rows(table, SLUG)}


def _by_key(registry, table):
    return {r["check_key"]: r for r in registry.query_detail_rows(table, SLUG)}


def _reinventory(registry, at="2026-10-20T09:30:00+00:00", tables=None, columns=None):
    """A later inventory batch: the current one with `tables` {(s, t): {field: value}} applied and `columns`
    [(schema, table, name, type)] added."""
    rows = registry.query_detail_rows("database_tables", SLUG)
    for row in rows:
        row.update((tables or {}).get((row["schema_name"], row["table_name"]), {}))
    cols = registry.query_detail_rows("database_columns", SLUG)
    for i, (schema, table, name, data_type) in enumerate(columns or [], start=100):
        cols.append({"schema_name": schema, "table_name": table, "column_name": name, "ordinal_position": i,
                     "data_type": data_type, "base_type": data_type, "state": "measured"})
    registry.write_detail_rows("database_tables", SLUG, at, rows=rows)
    registry.write_detail_rows("database_columns", SLUG, at, rows=cols)


# ── postgres_value_profile ───────────────────────────────────────────────────────────────────────────────────

def test_a_profiled_table_stores_measured_counts_under_the_catalogue_names(registry, entity):
    out, conn = _profile(registry, entity)
    rows = _rows(registry, "database_value_profiles")
    order_id, note, placed = rows["sales", "orders", "order_id"], rows["sales", "orders", "note"], \
        rows["sales", "orders", "placed"]
    assert (order_id["general_type"], order_id["record_ct"], order_id["distinct_value_ct"]) == ("N", 1000, 1000)
    assert (note["general_type"], note["value_ct"], note["filled_value_ct"], note["zero_length_ct"]) == ("A", 900, 3, 0)
    assert (placed["general_type"], placed["min_date"], placed["future_date_ct"]) == ("D", "2020-01-01", 0)
    assert order_id["zero_length_ct"] is None and order_id["min_date"] is None  # not applicable to N: NULL
    assert all(r["sample_ratio"] is None for r in rows.values())  # no sampling in slice 1
    assert order_id["ran_as"] == "surveyor"
    assert f"SET LOCAL statement_timeout = {60 * 1000}" in conn.statements
    orders_sql = next(s for s in conn.statements if s.endswith('FROM "sales"."orders"'))
    assert orders_sql.count("FROM") == 1  # one aggregate SELECT for the table
    assert "AS filled_value_ct" not in orders_sql and "AS c1__filled_value_ct" in orders_sql
    assert "COUNT(DISTINCT \"payload\")" not in orders_sql  # X types get no distinct count in slice 1
    assert out["value_profile"]["states"]["measured"] == 5


def test_an_empty_table_is_measured_with_a_real_zero(registry, entity):
    _profile(registry, entity)
    d = _rows(registry, "database_value_profiles")["sales", "empty", "d"]
    assert (d["state"], d["record_ct"], d["value_ct"]) == ("measured", 0, 0)


@pytest.mark.parametrize("table,state,words", [
    ("v_orders", "not_applicable", "a view, not a table"),
    ("big", "not_measured", "over the full-profile row ceiling (9,000,000 > 5,000,000)"),
    ("secret", "not_permitted", "permission denied"),
    ("slow", "not_measured", "statement timeout"),
])
def test_a_table_not_profiled_says_why_and_is_never_a_row_of_zeros(registry, entity, table, state, words):
    out, conn = _profile(registry, entity)
    rows = [r for k, r in _rows(registry, "database_value_profiles").items() if k[1] == table]
    assert rows
    for row in rows:
        assert row["state"] == state and words in row["reason"]
        assert row["record_ct"] is None and all(row[m] is None for m in COLUMN_MEASURES)
    assert {"table": f"sales.{table}", "state": state, "reason": rows[0]["reason"]} in \
        out["value_profile"]["tables_not_profiled"]
    if table in ("v_orders", "big"):
        assert not any(s.endswith(f'FROM "sales"."{table}"') for s in conn.statements)  # refused, not run


def test_the_ceiling_falls_back_to_the_stored_row_count_when_reltuples_is_unknown(registry, entity):
    _profile(registry, entity, FakeConn(profile=PROFILE, reltuples={}))
    assert _rows(registry, "database_value_profiles")["sales", "big", "id"]["state"] == "not_measured"


def test_an_unknown_row_count_is_refused_not_scanned_without_a_bound(registry, entity):
    _reinventory(registry, tables={("sales", "orders"): {"row_count": None}})
    _, conn = _profile(registry, entity, FakeConn(profile=PROFILE, reltuples={("sales", "orders"): -1}))
    note = _rows(registry, "database_value_profiles")["sales", "orders", "note"]
    assert note["state"] == "not_measured" and "row count unknown" in note["reason"] and "ANALYZE" in note["reason"]
    assert not any(s.endswith('FROM "sales"."orders"') for s in conn.statements)


def test_a_partitioned_parent_is_not_read_its_partitions_are(registry, entity):
    _, conn = _profile(registry, entity, FakeConn(profile=PROFILE, facts={("sales", "orders"): {"relkind": "p"}}))
    row = _rows(registry, "database_value_profiles")["sales", "orders", "order_id"]
    assert row["state"] == "not_applicable" and "partitioned parent" in row["reason"]
    assert not any(s.endswith('FROM "sales"."orders"') for s in conn.statements)


def test_row_level_security_that_filters_this_account_is_not_permitted_not_a_count(registry, entity):
    _profile(registry, entity, FakeConn(profile=PROFILE, facts={("sales", "orders"): {"rls_filters": True}}))
    row = _rows(registry, "database_value_profiles")["sales", "orders", "order_id"]
    assert (row["state"], row["record_ct"]) == ("not_permitted", None) and "row-level security" in row["reason"]


def test_without_the_catalog_the_stored_row_security_flag_still_refuses(registry, entity):
    _reinventory(registry, tables={("sales", "orders"): {"has_row_security": 1}})
    _profile(registry, entity, FakeConn(profile=PROFILE, catalog_error=PgError("permission denied for pg_roles")))
    assert _rows(registry, "database_value_profiles")["sales", "orders", "note"]["state"] == "not_permitted"
    assert _rows(registry, "database_value_profiles")["sales", "empty", "d"]["state"] == "measured"


def test_each_table_is_read_in_its_own_read_only_transaction(registry, entity):
    _, conn = _profile(registry, entity)
    reads = [i for i, s in enumerate(conn.statements) if s.startswith("SELECT\n")]
    assert reads
    for i in reads:
        assert conn.statements[i - 2:i] == ["SET TRANSACTION READ ONLY", "SET LOCAL statement_timeout = 60000"]
        assert conn.statements[i + 1] == "<end transaction>"


def test_a_percent_sign_in_a_name_is_not_a_parameter_marker(registry, entity):
    _reinventory(registry, columns=[("sales", "empty", "pct%done", "integer")])
    profile = {**PROFILE, ("sales", "empty"): {"record_ct": 4, "columns": [
        {"value_ct": 4, "distinct_value_ct": 4, "null_value_ct": 0, "min_date": "2026-01-01",
         "max_date": "2026-01-04", "future_date_ct": 0},
        {"value_ct": 4, "distinct_value_ct": 2, "null_value_ct": 0}]}}
    _profile(registry, entity, FakeConn(profile=profile))
    row = _rows(registry, "database_value_profiles")["sales", "empty", "pct%done"]
    assert (row["state"], row["value_ct"]) == ("measured", 4)
    _accept(registry, "sales.empty.pct%done::Required", "Required")
    _, rows, _ = _run(registry, entity, {("sales", "empty"): {"record_ct": 4, "measure": lambda s: 0}})
    assert rows["sales.empty.pct%done::Required"]["status"] == "pass"


def test_every_assembled_statement_parses_as_postgres():
    """No live Postgres in the default tier: sqlglot's Postgres dialect checks the SQL we build is well formed."""
    import sqlglot

    from resource_explorer.surveyors.database.quality import catalogue as cat
    from resource_explorer.surveyors.database.quality.run_checks import _select
    from resource_explorer.surveyors.database.quality.value_profile import (
        TABLE_FACTS_SQL,
        build_table_query,
    )

    cols = [("a", "A"), ("b", "N"), ("c", "D"), ("d", "B"), ("e", "X"), ('we"ird', "A"), ("pct%", "T")]
    sql, aliases = build_table_query("sales", "orders", cols, "2026-10-20 12:00:00")
    # value_ct + null_value_ct for all 7, distinct + zero_length + filled for the 2 text columns, 3 date measures,
    # distinct for B, D, N and T (none for X).
    assert len(aliases) == 2 * 7 + 3 * 2 + 3 + 4
    sqlglot.parse_one(sql, read="postgres")
    sqlglot.parse_one(TABLE_FACTS_SQL, read="postgres")
    params = {"baseline_ct": 10, "baseline_value_ct": 9, "baseline_value": "2020-01-01", "threshold_value": 2}
    measures = []
    for name, test_type in cat.load_catalogue().items():
        p = dict(params, baseline_value='"",n/a,it\'s' if name == "Required_No_Placeholder" else "2020-01-01")
        measures.append(cat.render_measure(test_type, "" if test_type.is_table_check else "col", p,
                                           "2026-10-20 12:00:00"))
    sqlglot.parse_one(_select("sales", "orders", measures), read="postgres")


def test_the_profile_annotations(registry, entity):
    out, _ = _profile(registry, entity)
    kinds = [type(a).__name__ for a in out["annotations"]]
    assert kinds.count("ResourceProfileAnnotation") == 5
    unprofiled = {a.item_key: a for a in out["annotations"] if type(a).__name__ == "ResourceMeasureAnnotation"}
    assert set(unprofiled) == {"sales.v_orders", "sales.big", "sales.secret", "sales.slow"}
    placed = next(a for a in out["annotations"] if a.item_key == "sales.orders.placed")
    assert placed.value_count["record_ct"] == 1000 and placed.json_properties["profileDates"]["min_date"] == "2020-01-01"


def test_no_stored_inventory_profiles_nothing_and_stores_nothing(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "empty.db"))
    reg.register_database(DatabaseEntity(slug=SLUG, display_name="x", db_type="postgresql", host="h", port=1,
                                         database_name="d"))
    out = run_value_profile(reg.get_database(SLUG), reg, _connect(FakeConn()), bounds=BOUNDS)
    assert out["value_profile"]["state"] == "not_established" and out["annotations"] == []
    assert reg.query_detail_rows("database_value_profiles", SLUG) == []


def test_a_connection_failure_raises_and_stores_nothing(registry, entity):
    @contextmanager
    def refused():
        raise PgError("could not connect to server")
        yield  # pragma: no cover

    with pytest.raises(PgError):
        run_value_profile(entity, registry, refused, bounds=BOUNDS)
    assert registry.query_detail_rows("database_value_profiles", SLUG) == []


# ── propose_quality_checks ───────────────────────────────────────────────────────────────────────────────────

def _propose(registry, at="2026-10-20T11:00:00+00:00", threshold=10):
    return run_propose(registry, SLUG, row_ct_pct_threshold=threshold, surveyed_at=at)


def test_proposals_follow_the_selection_rules(registry, entity):
    _profile(registry, entity)
    out = _propose(registry)["quality_proposals"]
    rows = _by_key(registry, "database_quality_proposals")
    proposed = {k for k, r in rows.items() if r["state"] == "proposed"}
    assert proposed == {
        "sales.orders.order_id::Required", "sales.orders.order_id::Unique", "sales.orders.note::Missing_Pct",
        "sales.orders.placed::Required", "sales.orders.placed::Future_Date", "sales.orders.placed::Min_Date",
        "sales.orders.payload::Missing_Pct", "sales.orders::Row_Ct_Pct",
    }
    # note is text with placeholders (filled_value_ct 3): neither Required nor Required_No_Placeholder.
    assert "sales.orders.note::Required_No_Placeholder" not in rows
    # A jsonb column has no distinct count in slice 1, so Unique cannot be decided for it: said, not hidden.
    assert rows["sales.orders.payload::Unique"]["state"] == "not_established"
    assert "distinct_value_ct" in rows["sales.orders.payload::Unique"]["reason"]
    missing = rows["sales.orders.note::Missing_Pct"]
    assert missing["params_json"] == {"baseline_ct": 1000, "baseline_value_ct": 900, "baseline_value": None,
                                      "threshold_value": 2, "severity": "warning",
                                      "profile_surveyed_at": PROFILED_AT}
    assert (missing["origin"], missing["profile_surveyed_at"]) == ("vendored", PROFILED_AT)
    row_ct = rows["sales.orders::Row_Ct_Pct"]
    assert (row_ct["origin"], row_ct["params_json"]["threshold_value"], row_ct["column_name"]) == ("re", 10, "")
    assert "vendored-catalog@3606859c" in row_ct["catalogue_ref"]
    assert out["proposed_ct"] == 8 and out["not_applicable_ct"] > 0


def test_an_unprofiled_column_is_not_established_by_column_never_a_silent_no(registry, entity):
    _profile(registry, entity)
    out = _propose(registry)["quality_proposals"]
    rows = _by_key(registry, "database_quality_proposals")
    big = rows["sales.big.id::Missing_Pct"]
    assert big["state"] == "not_established" and "not profiled (not_measured: over the full-profile row ceiling" \
        in big["reason"]
    assert rows["sales.big::Row_Ct_Pct"]["state"] == "not_established"
    assert rows["sales.secret.ssn::Required_No_Placeholder"]["state"] == "not_established"
    assert "sales.slow.id" in out["not_established_by_column"]
    # a view is not applicable, not unestablished
    assert not any(k.startswith("sales.v_orders") for k in rows)


def test_an_empty_table_leaves_the_date_rule_undefined_and_proposes_no_row_count_range(registry, entity):
    _profile(registry, entity)
    _propose(registry)
    rows = _by_key(registry, "database_quality_proposals")
    future = rows["sales.empty.d::Future_Date"]
    assert future["state"] == "not_established"
    assert "the table was empty when profiled, so future_date_ct is undefined" in future["reason"]
    assert "sales.empty::Row_Ct_Pct" not in rows  # record_ct = 0: not selected


def test_no_profile_proposes_nothing_and_stores_nothing(registry):
    out = _propose(registry)["quality_proposals"]
    assert out["state"] == "not_established"
    assert registry.query_detail_rows("database_quality_proposals", SLUG) == []


def test_an_accepted_check_reports_drift_and_is_not_proposed_again(registry, entity):
    _profile(registry, entity)
    _propose(registry)
    row_ct = _by_key(registry, "database_quality_proposals")["sales.orders::Row_Ct_Pct"]
    registry.record_quality_verdict(SLUG, row_ct["check_key"], "accepted", row_ct["params_json"],
                                    proposal_id=row_ct["id"], decided_by="steward")
    _propose(registry, at="2026-10-20T12:00:00+00:00")
    again = _by_key(registry, "database_quality_proposals")["sales.orders::Row_Ct_Pct"]
    assert (again["state"], again["reason"]) == ("accepted", "accepted; no drift from the accepted baseline")

    grown = {**PROFILE, ("sales", "orders"): {**PROFILE["sales", "orders"], "record_ct": 1200}}
    _profile(registry, entity, FakeConn(profile=grown), at="2026-10-21T10:00:00+00:00")
    _propose(registry, at="2026-10-21T11:00:00+00:00")
    drifted = _by_key(registry, "database_quality_proposals")["sales.orders::Row_Ct_Pct"]
    assert drifted["state"] == "accepted" and "baseline_ct 1000 -> 1200" in drifted["reason"]


def test_a_rejected_check_stays_suppressed_until_the_selection_outcome_flips(registry, entity):
    _profile(registry, entity)
    _propose(registry)
    note = _by_key(registry, "database_quality_proposals")["sales.orders.note::Missing_Pct"]
    registry.record_quality_verdict(SLUG, note["check_key"], "rejected", note["params_json"],
                                    proposal_id=note["id"], decided_by="steward")
    _propose(registry, at="2026-10-20T12:00:00+00:00")
    assert _by_key(registry, "database_quality_proposals")[note["check_key"]]["state"] == "suppressed"

    full = {("sales", "orders"): {"record_ct": 1000, "columns": [
        PROFILE["sales", "orders"]["columns"][0],
        {"value_ct": 1000, "distinct_value_ct": 40, "null_value_ct": 0, "zero_length_ct": 0, "filled_value_ct": 3},
        *PROFILE["sales", "orders"]["columns"][2:]]}}
    _profile(registry, entity, FakeConn(profile={**PROFILE, **full}), at="2026-10-22T10:00:00+00:00")
    _propose(registry, at="2026-10-22T11:00:00+00:00")
    assert note["check_key"] not in _by_key(registry, "database_quality_proposals")  # the rule said no

    _profile(registry, entity, at="2026-10-23T10:00:00+00:00")
    _propose(registry, at="2026-10-23T11:00:00+00:00")
    assert _by_key(registry, "database_quality_proposals")[note["check_key"]]["state"] == "proposed"


def test_a_rejected_check_is_proposed_again_when_the_general_type_changes(registry, entity):
    _profile(registry, entity)
    _propose(registry)
    note = _by_key(registry, "database_quality_proposals")["sales.orders.note::Missing_Pct"]
    registry.record_quality_verdict(SLUG, note["check_key"], "rejected", {}, proposal_id=note["id"])
    rows = registry.query_detail_rows("database_value_profiles", SLUG)
    for row in rows:
        if row["column_name"] == "note":
            row["general_type"] = "X"
    registry.write_detail_rows("database_value_profiles", SLUG, "2026-10-24T10:00:00+00:00", rows=rows)
    _propose(registry, at="2026-10-24T11:00:00+00:00")
    assert _by_key(registry, "database_quality_proposals")[note["check_key"]]["state"] == "proposed"


def test_the_propose_step_opens_no_connection(registry, entity, monkeypatch):
    from resource_explorer.surveyors.database import connection
    from resource_explorer.surveyors.database.survey_definition_adapter import _ADAPTER

    _profile(registry, entity)
    monkeypatch.setattr(connection, "database_connection", lambda *a, **k: pytest.fail("connected"))
    out = _ADAPTER.re_analysis_steps["propose_quality_checks"](entity, registry, scan_surveyed_at=None)
    assert out["quality_proposals"]["proposed_ct"] == 8


# ── run_quality_checks ───────────────────────────────────────────────────────────────────────────────────────

def _accept(registry, key, test_type, **params):
    base = {"baseline_ct": None, "baseline_value_ct": None, "baseline_value": None, "threshold_value": 0,
            "severity": "error", "profile_surveyed_at": PROFILED_AT}
    base.update(params)
    registry.record_quality_verdict(SLUG, key, "accepted", base, decided_by="steward")


def _orders_measure(sql):
    if 'COUNT(*) - COUNT(DISTINCT "order_id")' in sql:
        return 0
    if 'COUNT(*) - COUNT("placed")' in sql:
        return 5
    if 'COUNT( "note" )' in sql:
        return 2.5
    if 'SIGN("placed"::DATE' in sql:
        return 3
    raise AssertionError(sql)


def _run(registry, entity, checks, at="2026-10-20T13:00:00+00:00"):
    conn = FakeConn(checks=checks)
    out = run_quality_checks(entity, registry, _connect(conn), bounds=BOUNDS, surveyed_at=at, ran_as="surveyor")
    return out, _by_key(registry, "database_quality_results"), conn


def test_run_maps_each_measure_to_a_status_by_severity(registry, entity):
    _accept(registry, "sales.orders.order_id::Unique", "Unique")
    _accept(registry, "sales.orders.placed::Required", "Required")
    _accept(registry, "sales.orders.note::Missing_Pct", "Missing_Pct", baseline_ct=1000, baseline_value_ct=900,
            threshold_value=2, severity="warning")
    _accept(registry, "sales.orders.placed::Future_Date", "Future_Date", severity="info")
    out, rows, conn = _run(registry, entity, {("sales", "orders"): {"record_ct": 1000, "measure": _orders_measure}})
    assert {k: r["status"] for k, r in rows.items()} == {
        "sales.orders.order_id::Unique": "pass", "sales.orders.placed::Required": "fail",
        "sales.orders.note::Missing_Pct": "warning", "sales.orders.placed::Future_Date": "logged"}
    unique = rows["sales.orders.order_id::Unique"]
    assert (unique["measure"], unique["record_ct"], unique["comparison_operator"], unique["threshold_values_json"]) \
        == (0, 1000, "mustBeLessOrEqualTo", [0])
    assert (unique["rule_source"], unique["baseline_profile_surveyed_at"]) == ("unpublished", PROFILED_AT)
    assert rows["sales.orders.note::Missing_Pct"]["comparison_operator"] == "mustBeLessThan"
    assert sum(s.endswith('FROM "sales"."orders"') and s.startswith("SELECT COUNT(*)") for s in conn.statements) == 1
    assert out["quality_checks"]["status_counts"] == {"pass": 1, "fail": 1, "warning": 1, "logged": 1}


def test_a_null_measure_is_not_established_never_a_pass(registry, entity):
    """TestGen's CASE would fall through to pass: Missing_Pct over an empty table divides by NULLIF(0, 0)."""
    _accept(registry, "sales.empty.d::Missing_Pct", "Missing_Pct", baseline_ct=10, baseline_value_ct=9,
            threshold_value=2, severity="warning")
    _, rows, _ = _run(registry, entity, {("sales", "empty"): {"record_ct": 0, "measure": lambda sql: None}})
    row = rows["sales.empty.d::Missing_Pct"]
    assert (row["status"], row["measure"]) == ("not_established", None)
    assert "measure undefined (empty table / zero baseline)" in row["reason"]


def test_a_zero_baseline_is_not_established_without_running(registry, entity):
    _accept(registry, "sales.empty::Row_Ct_Pct", "Row_Ct_Pct", baseline_ct=0, threshold_value=10)
    _, rows, conn = _run(registry, entity, {})
    assert rows["sales.empty::Row_Ct_Pct"]["status"] == "not_established"
    assert "baseline_ct is 0" in rows["sales.empty::Row_Ct_Pct"]["reason"]
    assert not any("sales\".\"empty" in s for s in conn.statements)


def test_the_rejected_flip_rule_does_not_depend_on_the_wall_clock(registry, entity, monkeypatch):
    """H1: "since" is the judged proposal's surveyed_at, so a verdict recorded long after the batches (as on any
    machine whose clock has passed these fixed scan times) still sees the flip."""
    import resource_explorer.registry as reg_module

    class Later(reg_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return reg_module.datetime(2030, 1, 1, tzinfo=tz)

    _profile(registry, entity)
    _propose(registry)
    note = _by_key(registry, "database_quality_proposals")["sales.orders.note::Missing_Pct"]
    monkeypatch.setattr(reg_module, "datetime", Later)
    registry.record_quality_verdict(SLUG, note["check_key"], "rejected", {}, proposal_id=note["id"])
    monkeypatch.undo()
    full = {("sales", "orders"): {"record_ct": 1000, "columns": [
        PROFILE["sales", "orders"]["columns"][0],
        {"value_ct": 1000, "distinct_value_ct": 40, "null_value_ct": 0, "zero_length_ct": 0, "filled_value_ct": 3},
        *PROFILE["sales", "orders"]["columns"][2:]]}}
    _profile(registry, entity, FakeConn(profile={**PROFILE, **full}), at="2026-10-22T10:00:00+00:00")
    _propose(registry, at="2026-10-22T11:00:00+00:00")
    _profile(registry, entity, at="2026-10-23T10:00:00+00:00")
    _propose(registry, at="2026-10-23T11:00:00+00:00")
    assert _by_key(registry, "database_quality_proposals")[note["check_key"]]["state"] == "proposed"


def test_run_refuses_partitioned_rls_and_unknown_size_tables_like_the_profile(registry, entity):
    _reinventory(registry, tables={("sales", "slow"): {"row_count": None}})
    _accept(registry, "sales.orders.order_id::Unique", "Unique")
    _accept(registry, "sales.secret.ssn::Required", "Required")
    _accept(registry, "sales.slow.id::Required", "Required")
    conn = FakeConn(checks={}, facts={("sales", "orders"): {"relkind": "p"}, ("sales", "secret"): {"rls_filters": True}})
    run_quality_checks(entity, registry, _connect(conn), bounds=BOUNDS, surveyed_at="2026-10-20T13:00:00+00:00")
    rows = _by_key(registry, "database_quality_results")
    assert rows["sales.orders.order_id::Unique"]["status"] == "not_measured"
    assert "partitioned parent" in rows["sales.orders.order_id::Unique"]["reason"]
    assert rows["sales.secret.ssn::Required"]["status"] == "not_permitted"
    assert rows["sales.slow.id::Required"]["status"] == "not_measured"
    assert not any(s.startswith("SELECT COUNT(*)") for s in conn.statements)


def test_an_accepted_check_whose_proposal_names_another_key_is_parsed_from_its_own_key(registry, entity):
    _profile(registry, entity)
    _propose(registry)
    other = _by_key(registry, "database_quality_proposals")["sales.orders.placed::Required"]
    registry.record_quality_verdict(SLUG, "sales.orders.order_id::Unique", "accepted",
                                    {"threshold_value": 0, "severity": "error"}, proposal_id=other["id"])
    _, rows, _ = _run(registry, entity, {("sales", "orders"): {"record_ct": 1000, "measure": _orders_measure}})
    row = rows["sales.orders.order_id::Unique"]
    assert (row["column_name"], row["test_type"], row["status"]) == ("order_id", "Unique", "pass")


def test_an_empty_result_set_is_an_error_not_an_empty_table(registry, entity):
    _accept(registry, "sales.orders.order_id::Unique", "Unique")

    class NoRow(FakeConn):
        def _check(self, table, sql):
            return []

    conn = NoRow(checks={("sales", "orders"): {}})
    run_quality_checks(entity, registry, _connect(conn), bounds=BOUNDS, surveyed_at="2026-10-20T13:00:00+00:00")
    row = _by_key(registry, "database_quality_results")["sales.orders.order_id::Unique"]
    assert (row["status"], row["reason"]) == ("error", "the aggregate query returned no row")


def test_division_by_zero_is_not_established_and_other_errors_are_errors(registry, entity):
    _accept(registry, "sales.orders::Row_Ct_Pct", "Row_Ct_Pct", baseline_ct=1000, threshold_value=10)
    _, rows, _ = _run(registry, entity, {("sales", "orders"): PgError("division by zero", "22012")})
    assert rows["sales.orders::Row_Ct_Pct"]["status"] == "not_established"
    _accept(registry, "sales.secret.ssn::Required", "Required")
    _, rows, _ = _run(registry, entity, {("sales", "orders"): {"record_ct": 1, "measure": lambda s: 0},
                                         ("sales", "secret"): PERMISSION}, at="2026-10-20T14:00:00+00:00")
    assert rows["sales.secret.ssn::Required"]["status"] == "not_permitted"  # L4: a privilege error
    assert "permission denied" in rows["sales.secret.ssn::Required"]["reason"]


def test_one_bad_check_does_not_hide_the_others(registry, entity):
    _accept(registry, "sales.orders.order_id::Unique", "Unique")
    _accept(registry, "sales.orders.placed::Required", "Required")

    def measure(sql):
        if "placed" in sql:
            raise PgError('column "placed" does not exist')
        return 0

    _, rows, conn = _run(registry, entity, {("sales", "orders"): {"record_ct": 1000, "measure": measure}})
    assert rows["sales.orders.order_id::Unique"]["status"] == "pass"
    assert rows["sales.orders.placed::Required"]["status"] == "error"
    assert 'column "placed" does not exist' in rows["sales.orders.placed::Required"]["reason"]
    assert sum(s.startswith("SELECT COUNT(*)") for s in conn.statements) == 3  # the batch, then each alone


def test_over_the_ceiling_is_not_measured(registry, entity):
    _accept(registry, "sales.big.id::Required", "Required")
    _, rows, _conn = _run(registry, entity, {})
    assert rows["sales.big.id::Required"]["status"] == "not_measured"
    assert "9,000,000 > 5,000,000" in rows["sales.big.id::Required"]["reason"]


def test_a_key_that_does_not_fit_its_test_types_scope_is_not_established(registry, entity):
    _accept(registry, "sales.orders::Unique", "Unique")
    _accept(registry, "sales.orders.order_id::Row_Ct_Pct", "Row_Ct_Pct", baseline_ct=10, threshold_value=10)
    _accept(registry, "no-separator", "Unique")
    _, rows, conn = _run(registry, entity, {})
    assert "Unique is a column check" in rows["sales.orders::Unique"]["reason"]
    assert "Row_Ct_Pct is a table check" in rows["sales.orders.order_id::Row_Ct_Pct"]["reason"]
    assert "cannot tell which column" in rows["no-separator"]["reason"]
    assert {r["status"] for r in rows.values()} == {"not_established"} and conn.statements == []


def test_a_column_gone_from_the_inventory_is_not_established(registry, entity):
    _accept(registry, "sales.orders.gone::Required", "Required")
    _accept(registry, "sales.dropped.id::Required", "Required")
    _, rows, _ = _run(registry, entity, {})
    assert rows["sales.orders.gone::Required"]["reason"] == "column no longer in inventory"
    assert rows["sales.dropped.id::Required"]["reason"] == "table no longer in inventory"
    assert {r["status"] for r in rows.values()} == {"not_established"}


@pytest.mark.parametrize("params,quoted", [
    ({"threshold_value": "abc"}, "'abc'"),
    ({"severity": "critical"}, "'critical'"),
    ({"baseline_value": "2020-01-01'; DROP TABLE sales.orders; --"}, "DROP TABLE"),
])
def test_a_parameter_that_does_not_validate_is_not_established_and_never_run(registry, entity, params, quoted):
    _accept(registry, "sales.orders.placed::Min_Date", "Min_Date", **{"baseline_value": "2020-01-01", **params})
    _, rows, conn = _run(registry, entity, {})
    row = rows["sales.orders.placed::Min_Date"]
    assert row["status"] == "not_established" and quoted in row["reason"]
    assert not any(s.startswith("SELECT COUNT(*)") for s in conn.statements)


def test_only_accepted_checks_run_and_none_accepted_runs_nothing(registry, entity):
    out, rows, conn = _run(registry, entity, {})
    assert out["quality_checks"]["state"] == "not_established" and rows == {}
    assert conn.statements == []
    registry.record_quality_verdict(SLUG, "sales.orders.order_id::Unique", "rejected", {})
    out, rows, conn = _run(registry, entity, {})
    assert rows == {} and conn.statements == []


def test_the_latest_verdict_wins(registry, entity):
    _accept(registry, "sales.orders.order_id::Unique", "Unique")
    registry.record_quality_verdict(SLUG, "sales.orders.order_id::Unique", "retired", {})
    assert registry.get_quality_verdicts(SLUG)["sales.orders.order_id::Unique"]["verdict"] == "retired"
    assert len(registry.list_quality_verdict_history(SLUG, "sales.orders.order_id::Unique")) == 2
    with pytest.raises(ValueError):
        registry.record_quality_verdict(SLUG, "k", "maybe", {})


def test_an_accepted_proposal_resolves_its_column_from_the_proposal_row(registry, entity):
    _profile(registry, entity)
    _propose(registry)
    unique = _by_key(registry, "database_quality_proposals")["sales.orders.order_id::Unique"]
    registry.record_quality_verdict(SLUG, unique["check_key"], "accepted", unique["params_json"],
                                    proposal_id=unique["id"])
    _, rows, _ = _run(registry, entity, {("sales", "orders"): {"record_ct": 1000, "measure": _orders_measure}})
    assert rows["sales.orders.order_id::Unique"]["status"] == "pass"


# ── readers and registration ─────────────────────────────────────────────────────────────────────────────────

def test_the_readers_are_empty_when_nothing_ran_and_count_by_status_after(registry, entity):
    from resource_explorer.surveyors.database.survey_definition_adapter import (
        DATABASE_ANALYSIS_HEADLINE_MAP,
        DATABASE_ANALYSIS_RESULTS_MAP,
    )

    profile_reader, _ = DATABASE_ANALYSIS_RESULTS_MAP["value_profile"]
    checks_reader, _ = DATABASE_ANALYSIS_RESULTS_MAP["quality_checks"]
    assert profile_reader(registry, SLUG) == {} and checks_reader(registry, SLUG) == {}
    assert DATABASE_ANALYSIS_HEADLINE_MAP["quality_checks"](registry, SLUG) is None

    _profile(registry, entity)
    _propose(registry)
    assert "check(s) proposed, none accepted" in DATABASE_ANALYSIS_HEADLINE_MAP["quality_checks"](registry, SLUG)["label"]
    profile = profile_reader(registry, SLUG)
    assert profile["measured_count"] == 5 and profile["state_counts"]["not_measured"] == 2
    assert "5 of " in DATABASE_ANALYSIS_HEADLINE_MAP["value_profile"](registry, SLUG)["label"]

    _accept(registry, "sales.orders.order_id::Unique", "Unique")
    _accept(registry, "sales.orders.placed::Required", "Required")
    _accept(registry, "sales.big.id::Required", "Required")
    _run(registry, entity, {("sales", "orders"): {"record_ct": 1000, "measure": _orders_measure}})
    headline = DATABASE_ANALYSIS_HEADLINE_MAP["quality_checks"](registry, SLUG)
    assert headline == {"label": "1 pass · 1 fail · 1 not evaluated.", "status": "warning"}


def test_the_three_steps_are_registered():
    from resource_explorer.surveyors.database.survey_definition_adapter import (
        _ADAPTER,
        DATABASE_ANALYSIS_RE_STEP_MAP,
        DATABASE_STEP_REGISTRY,
    )

    for key in ("postgres_value_profile", "propose_quality_checks", "run_quality_checks"):
        assert key in DATABASE_STEP_REGISTRY and key in _ADAPTER.re_analysis_steps, key
    assert DATABASE_STEP_REGISTRY["propose_quality_checks"].fetch_cost == "none"
    assert DATABASE_STEP_REGISTRY["postgres_value_profile"].produces == ("database_value_profiles",)
    assert DATABASE_ANALYSIS_RE_STEP_MAP["value_profile"] == ["postgres_value_profile"]
    assert DATABASE_ANALYSIS_RE_STEP_MAP["quality_checks"] == ["propose_quality_checks", "run_quality_checks"]


def test_the_value_profile_runner_uses_the_settings(registry, entity, monkeypatch):
    from resource_explorer.config import get_config
    from resource_explorer.surveyors.database import connection
    from resource_explorer.surveyors.database.survey_definition_adapter import _ADAPTER

    conn = FakeConn(profile=PROFILE)
    monkeypatch.setattr(connection, "database_connection", lambda *a, **k: _connect(conn)())
    monkeypatch.setattr(get_config().value_profile, "max_table_rows", 100)
    monkeypatch.setattr(get_config().value_profile, "statement_timeout_seconds", 5)
    out = _ADAPTER.re_analysis_steps["postgres_value_profile"](entity, registry, db_user="u", db_pwd="p",
                                                              scan_surveyed_at=PROFILED_AT)
    assert out["value_profile"]["bounds"] == {"max_table_rows": 100, "statement_timeout_seconds": 5}
    assert "SET LOCAL statement_timeout = 5000" in conn.statements
    assert _rows(registry, "database_value_profiles")["sales", "orders", "note"]["state"] == "not_measured"


def test_the_engine_host_declares_the_three_steps():
    from pathlib import Path

    doc = (Path(__file__).resolve().parent.parent / "docs" / "dr-egeria" / "engine-host" / "steps"
           / "database-steps.md").read_text()
    assert "postgres_value_profile" in doc
    # Held: until results are published they would complete with empty survey-completed reports.
    for key in ("propose_quality_checks", "run_quality_checks"):
        assert key not in doc, key
    from resource_explorer import engine_host

    assert "not run by Resource Explorer's engine host" in engine_host.out_of_scope_reason("run_quality_checks")
    assert engine_host.out_of_scope_reason("postgres_value_profile") == ""


# ── the per-card Run (one predicate since #795) ──────────────────────────────────────────────────────────────

def test_both_analyses_have_a_per_card_runner_that_needs_the_stored_credential():
    from resource_explorer.surveyors.database.database_surveyor import (
        DATABASE_REGISTRY_STEP_ANALYSES,
        database_analysis_has_runner,
        database_analysis_needs_credentials,
    )
    from resource_explorer.surveyors.database.survey_definition_adapter import (
        DATABASE_ANALYSIS_RE_STEP_MAP,
    )
    from resource_explorer.workflows.stage_page import _credential_use, runnable_and_reason

    for analysis_id, steps in DATABASE_REGISTRY_STEP_ANALYSES.items():
        assert list(steps) == DATABASE_ANALYSIS_RE_STEP_MAP[analysis_id], analysis_id
        assert database_analysis_has_runner(analysis_id) and database_analysis_needs_credentials(analysis_id)
        assert runnable_and_reason(analysis_id, "database") == (True, "")
        assert _credential_use("database", analysis_id) == "stored"


def test_a_per_card_value_profile_run_goes_through_the_executor_and_publishes_nothing(registry, monkeypatch):
    from resource_explorer.surveyors.database import connection
    from resource_explorer.workflows.analysis import run_database_analysis

    registry.update_database_credentials(SLUG, "surveyor", "pw")
    fake = FakeConn(profile=PROFILE)
    seen = {}

    def fake_connection(entity, credentials, **_):
        seen.update(credentials)
        return _connect(fake)()

    monkeypatch.setattr(connection, "database_connection", fake_connection)
    result = run_database_analysis(SLUG, "value_profile", registry=registry)
    assert result.status == "ok", result.error
    assert "postgres_value_profile" in result.summary
    assert seen.get("user") == "surveyor"  # the executor handed the step the stored credential
    assert _rows(registry, "database_value_profiles")["sales", "orders", "note"]["state"] == "measured"


def test_a_per_card_quality_checks_run_stops_when_propose_cannot_run(registry):
    """With no value profile stored, propose is not run (its prerequisite is unmet): the run says so, it does not
    go on to run checks or report ok."""
    from resource_explorer.workflows.analysis import run_database_analysis

    result = run_database_analysis(SLUG, "quality_checks", registry=registry)
    assert result.status == "error" and "No stored database credentials" in result.error  # refused before any step
    registry.update_database_credentials(SLUG, "surveyor", "pw")
    result = run_database_analysis(SLUG, "quality_checks", registry=registry)
    assert result.status == "error" and "propose_quality_checks" in result.error
    assert registry.query_detail_rows("database_quality_results", SLUG) == []
