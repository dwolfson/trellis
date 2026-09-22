"""Tests for the postgres_schema_and_stats extension (Phase 1 slice 7,
COORDINATOR-BRIEF-MULTI-RESOURCE.md): pg_stats column profiling,
pg_stat_user_tables tuple counters, and pg_stat_user_indexes/pg_index index
usage — plus the engine capability declaration on DatabaseConnection.

Three absence states are the point of this file, not an afterthought:

1. Normal — a fresh ANALYZE and a populated pg_stat_user_tables produce
   STATE_MEASURED rows with real values.
2. "Stats never collected" — a table/column is in the catalog but pg_stats
   has no row for it (ANALYZE never ran). Must render as STATE_NOT_COLLECTED,
   never as an empty/zero profile.
3. "Capability not supported" — the connection's engine capability
   declaration says a capability is absent. Must render as
   STATE_NOT_SUPPORTED, distinct from both of the above, and the surveyor
   must not even attempt the query.

Index usage (used vs. unused) is covered separately: an index with idx_scan
> 0 is reported as a plain measurement, and one with idx_scan == 0 (and not
a primary key) additionally raises a RequestForActionAnnotation candidate.

No live Postgres is used. `_FakeConnection` is a duck-typed stand-in for
`PostgreSQLConnection` implementing exactly the methods DatabaseSurveyor
calls, so these tests exercise the real DatabaseSurveyor/_survey_extended_
statistics code path end to end, including the registry writes, without a
database.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from resource_explorer.registry import (
    DatabaseEntity,
    ProjectRegistry,
    STATE_MEASURED,
    STATE_NOT_COLLECTED,
    STATE_NOT_SUPPORTED,
    STATS_SOURCE_DATABASE,
)
from resource_explorer.surveyors.database.connection import EngineCapabilities
from resource_explorer.surveyors.database.database_surveyor import (
    DatabaseSurveyor,
    _resolve_n_distinct,
)
from resource_explorer.surveyors.survey_report import RequestForActionAnnotation


class _FakeConnection:
    """Duck-typed stand-in for PostgreSQLConnection.

    Only implements what DatabaseSurveyor actually calls: get_schema_info(),
    get_statistics(), and the `capabilities` property. Each test configures
    the two data methods and the capability declaration independently, which
    is the point — capability and data are orthogonal here on purpose (a
    capability-absent test never even has get_statistics() asked for the
    corresponding rows).
    """

    def __init__(self, schema_info, statistics, capabilities):
        self._schema_info = schema_info
        self._statistics = statistics
        self._capabilities = capabilities

    def get_schema_info(self):
        return self._schema_info

    def get_statistics(self):
        return self._statistics

    @property
    def capabilities(self):
        return self._capabilities


def _schema_info(columns=("id", "email")):
    return {
        "schemas": [{
            "name": "public",
            "description": "",
            "tables": [{
                "name": "customers",
                "type": "BASE TABLE",
                "description": "",
                "columns": [
                    {"name": c, "type": "text", "base_type": "text",
                     "nullable": True, "position": i + 1,
                     "is_primary_key": c == "id", "foreign_key": None}
                    for i, c in enumerate(columns)
                ],
            }],
        }],
        "total_tables": 1,
        "total_columns": len(columns),
    }


@contextmanager
def _patched_connection(conn):
    with patch(
        "resource_explorer.surveyors.database.database_surveyor.database_connection",
    ) as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = conn
        mock_ctx.return_value.__exit__.return_value = False
        yield


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def db_entity(registry):
    entity = DatabaseEntity(
        slug="mydb", display_name="My DB", db_type="postgresql",
        host="localhost", port=5432, database_name="mydb",
        db_user="admin", db_password="secret",
    )
    registry.register_database(entity)
    return entity


FULL_CAPS = EngineCapabilities(column_stats=True, tuple_counters=True, index_stats=True)


class TestNormalCase:
    """Fresh ANALYZE + populated pg_stat_user_tables: real measured rows."""

    def test_column_profile_rows_are_measured(self, registry, db_entity):
        schema_info = _schema_info()
        statistics = {
            "column_stats": [
                {"schemaname": "public", "tablename": "customers", "attname": "id",
                 "null_frac": 0.0, "n_distinct": -1.0, "avg_width": 4,
                 "correlation": 1.0, "most_common_vals": None,
                 "most_common_freqs": None, "histogram_bounds": None,
                 "reltuples": 995.0},
                {"schemaname": "public", "tablename": "customers", "attname": "email",
                 "null_frac": 0.02, "n_distinct": 950.0, "avg_width": 24,
                 "correlation": 0.1, "most_common_vals": '{"a@x.com","b@x.com"}',
                 "most_common_freqs": '{0.01,0.008}', "histogram_bounds": None,
                 "reltuples": 995.0},
            ],
            "table_activity": [
                {"schemaname": "public", "tablename": "customers",
                 "rows_inserted": 1000, "rows_updated": 50, "rows_deleted": 5,
                 "hot_updates": 10, "live_tuples": 995, "dead_tuples": 5,
                 "seq_scan": 3, "idx_scan": 120,
                 "last_vacuum": "2026-09-20T00:00:00", "last_autovacuum": "",
                 "last_analyze": "2026-09-20T00:00:00", "last_autoanalyze": "",
                 "pending_changes": 0},
            ],
            "index_stats": [],
            "stats_reset": "2026-01-01T00:00:00",
        }
        conn = _FakeConnection(schema_info, statistics, FULL_CAPS)
        surveyor = DatabaseSurveyor(db_entity, {"user": "a", "password": "b"}, registry)
        with _patched_connection(conn):
            result = surveyor.survey()

        assert result["engine_capabilities"] == FULL_CAPS.as_dict()

        profiles = registry.query_detail_rows("database_column_profiles", db_entity.slug)
        by_col = {r["column_name"]: r for r in profiles}
        assert by_col["email"]["state"] == STATE_MEASURED
        assert by_col["email"]["null_fraction"] == pytest.approx(0.02)
        assert by_col["email"]["distinct_count"] == pytest.approx(950.0)
        assert by_col["email"]["stats_source"] == STATS_SOURCE_DATABASE
        assert by_col["email"]["stats_computed_at"] == "2026-09-20T00:00:00"
        assert by_col["email"]["most_common_values_json"] == ["a@x.com", "b@x.com"]

        # "id" carries pg_stats' NEGATIVE n_distinct convention (-1.0 means
        # "unique, scales with row count" -- a ratio, not a count). Found
        # live in design review round 2, 2026-09-21: passing this through
        # unresolved renders as a negative cardinality ("distinct: -0.8"),
        # never a real answer. Must resolve to a positive estimated count
        # using pg_class.reltuples (995 here) -- the SAME analyze run's row
        # count, not a separately-read live tuple count that can drift from
        # it (a second design-review finding, same day).
        assert by_col["id"]["distinct_count"] == pytest.approx(995.0)

        activity = registry.query_detail_rows("database_table_activity", db_entity.slug)
        assert len(activity) == 1
        row = activity[0]
        assert row["state"] == STATE_MEASURED
        assert row["rows_inserted"] == 1000
        assert row["live_tuples"] == 995
        assert row["dead_tuples"] == 5
        assert row["seq_scan"] == 3
        assert row["idx_scan"] == 120
        assert row["stats_reset"] == "2026-01-01T00:00:00"


class TestResolveNDistinct:
    """pg_stats.n_distinct's sign convention, resolved in isolation.

    A non-negative value is an absolute count; a negative value is
    -(distinct/rowcount), a ratio -- found live in design review round 2,
    2026-09-21, where passing a negative ratio straight through would have
    rendered a negative cardinality. The multiplier must be pg_class.reltuples
    (the SAME analyze run's row count), not a separately-read live tuple
    count that can drift from it -- a second design-review finding, same day.
    """

    def test_non_negative_value_passes_through_unchanged(self):
        assert _resolve_n_distinct(950.0, reltuples=995) == 950.0

    def test_negative_ratio_resolves_against_reltuples(self):
        assert _resolve_n_distinct(-1.0, reltuples=995) == pytest.approx(995.0)
        assert _resolve_n_distinct(-0.5, reltuples=1000) == pytest.approx(500.0)

    def test_negative_ratio_with_no_reltuples_is_not_established(self):
        # Silently returning the raw ratio would be a wrong number, not an
        # honest absence -- must say "not established" instead.
        assert _resolve_n_distinct(-0.8, reltuples=None) is None

    def test_negative_ratio_with_never_analyzed_placeholder_is_not_established(self):
        # reltuples == -1 is Postgres's own "never analyzed" placeholder
        # (PG14+) -- untrustworthy as a multiplier, even though n_distinct
        # existing at all should mean an analyze already ran; handled
        # explicitly rather than trusted away.
        assert _resolve_n_distinct(-0.8, reltuples=-1) is None

    def test_negative_ratio_against_a_confirmed_empty_analyzed_table_is_zero(self):
        # reltuples == 0 with ever_analyzed=True (last_analyze/last_autoanalyze
        # non-null) is a confirmed, real empty table -- 0 is a legitimate
        # answer, not "not established".
        assert _resolve_n_distinct(-1.0, reltuples=0, ever_analyzed=True) == 0

    def test_reltuples_zero_without_confirmed_analyze_is_not_established(self):
        # On PG13 and earlier, reltuples == 0 means BOTH "analyzed, empty"
        # and "never analyzed" -- without independent confirmation via
        # last_analyze/last_autoanalyze, a table with real rows that was
        # never ANALYZEd would otherwise resolve to a confident, wrong 0.
        assert _resolve_n_distinct(-1.0, reltuples=0, ever_analyzed=False) is None
        assert _resolve_n_distinct(-1.0, reltuples=0) is None  # ever_analyzed defaults to unknown

    def test_none_input_is_none(self):
        assert _resolve_n_distinct(None, reltuples=995) is None


class TestStatsNeverCollected:
    """ANALYZE has never run: pg_stats has no row for a cataloged column."""

    def test_column_missing_from_pg_stats_is_not_collected(self, registry, db_entity):
        schema_info = _schema_info(columns=("id", "email"))
        statistics = {
            # pg_stats reports nothing at all for this table — ANALYZE never ran.
            "column_stats": [],
            "table_activity": [
                {"schemaname": "public", "tablename": "customers",
                 "rows_inserted": 0, "rows_updated": 0, "rows_deleted": 0,
                 "hot_updates": 0, "live_tuples": 0, "dead_tuples": 0,
                 "seq_scan": 0, "idx_scan": 0,
                 "last_vacuum": "", "last_autovacuum": "",
                 "last_analyze": "", "last_autoanalyze": "",
                 "pending_changes": 0},
            ],
            "index_stats": [],
            "stats_reset": "",
        }
        conn = _FakeConnection(schema_info, statistics, FULL_CAPS)
        surveyor = DatabaseSurveyor(db_entity, {"user": "a", "password": "b"}, registry)
        with _patched_connection(conn):
            surveyor.survey()

        profiles = registry.query_detail_rows("database_column_profiles", db_entity.slug)
        assert len(profiles) == 2
        for row in profiles:
            assert row["state"] == STATE_NOT_COLLECTED
            # Never rendered as a measured zero-profile.
            assert row["null_fraction"] is None
            assert row["distinct_count"] is None
            assert row["stats_source"] == STATS_SOURCE_DATABASE
            assert row["stats_computed_at"] is None

    def test_not_collected_is_distinct_from_measured_empty(self, registry, db_entity):
        """A column WITH a pg_stats row reporting null_frac=0 is a real
        measured zero, not "not collected" — the two must not collapse."""
        schema_info = _schema_info(columns=("id",))
        statistics = {
            "column_stats": [
                {"schemaname": "public", "tablename": "customers", "attname": "id",
                 "null_frac": 0.0, "n_distinct": -1.0, "avg_width": 4,
                 "correlation": 1.0, "most_common_vals": None,
                 "most_common_freqs": None, "histogram_bounds": None},
            ],
            "table_activity": [],
            "index_stats": [],
            "stats_reset": "",
        }
        conn = _FakeConnection(schema_info, statistics, FULL_CAPS)
        surveyor = DatabaseSurveyor(db_entity, {"user": "a", "password": "b"}, registry)
        with _patched_connection(conn):
            surveyor.survey()

        profiles = registry.query_detail_rows("database_column_profiles", db_entity.slug)
        assert len(profiles) == 1
        assert profiles[0]["state"] == STATE_MEASURED
        assert profiles[0]["null_fraction"] == 0.0


class TestCapabilityNotSupported:
    """The engine's capability declaration says a capability is absent —
    must render as not_supported, and the surveyor must not query for it."""

    def test_column_stats_capability_absent(self, registry, db_entity):
        schema_info = _schema_info(columns=("id", "email"))
        no_column_stats = EngineCapabilities(
            column_stats=False, tuple_counters=True, index_stats=True,
        )
        statistics = {
            # Even if this were populated, an unsupported engine must not
            # use it — capability is checked before the data, not inferred
            # from whether the data happens to be present.
            "column_stats": [
                {"schemaname": "public", "tablename": "customers", "attname": "id",
                 "null_frac": 0.0},
            ],
            "table_activity": [
                {"schemaname": "public", "tablename": "customers",
                 "rows_inserted": 1, "rows_updated": 0, "rows_deleted": 0,
                 "hot_updates": 0, "live_tuples": 1, "dead_tuples": 0,
                 "seq_scan": 1, "idx_scan": 0,
                 "last_vacuum": "", "last_autovacuum": "",
                 "last_analyze": "", "last_autoanalyze": "", "pending_changes": 0},
            ],
            "index_stats": [],
            "stats_reset": "",
        }
        conn = _FakeConnection(schema_info, statistics, no_column_stats)
        surveyor = DatabaseSurveyor(db_entity, {"user": "a", "password": "b"}, registry)
        with _patched_connection(conn):
            result = surveyor.survey()

        assert result["engine_capabilities"]["column_stats"] is False

        profiles = registry.query_detail_rows("database_column_profiles", db_entity.slug)
        assert len(profiles) == 2
        for row in profiles:
            assert row["state"] == STATE_NOT_SUPPORTED
            assert row["null_fraction"] is None

        # Table activity, whose capability IS declared, is unaffected.
        activity = registry.query_detail_rows("database_table_activity", db_entity.slug)
        assert activity[0]["state"] == STATE_MEASURED

    def test_no_capabilities_at_all_marks_everything_not_supported(self, registry, db_entity):
        schema_info = _schema_info(columns=("id",))
        statistics = {"column_stats": [], "table_activity": [], "index_stats": [], "stats_reset": ""}
        conn = _FakeConnection(schema_info, statistics, EngineCapabilities())
        surveyor = DatabaseSurveyor(db_entity, {"user": "a", "password": "b"}, registry)
        with _patched_connection(conn):
            result = surveyor.survey()

        assert result["engine_capabilities"] == EngineCapabilities().as_dict()
        profiles = registry.query_detail_rows("database_column_profiles", db_entity.slug)
        assert profiles[0]["state"] == STATE_NOT_SUPPORTED
        activity = registry.query_detail_rows("database_table_activity", db_entity.slug)
        assert activity[0]["state"] == STATE_NOT_SUPPORTED

        # Distinct annotation explaining WHY, not silence.
        not_established = [
            a for a in result["annotations"]
            if getattr(a, "resource_properties", {}).get("supported") is False
        ]
        capabilities_flagged = {a.resource_properties["capability"] for a in not_established}
        assert capabilities_flagged == {"column_stats", "tuple_counters", "index_stats"}


class TestIndexUsageDetection:
    """pg_stat_user_indexes / pg_index: used vs. unused indexes."""

    def test_used_index_produces_plain_measurement_no_rfa(self, registry, db_entity):
        schema_info = _schema_info(columns=("id",))
        statistics = {
            "column_stats": [], "table_activity": [],
            "index_stats": [
                {"schemaname": "public", "tablename": "customers",
                 "indexrelname": "customers_pkey", "idx_scan": 500,
                 "idx_tup_read": 500, "idx_tup_fetch": 500,
                 "is_unique": True, "is_primary": True, "index_size_bytes": 8192},
            ],
            "stats_reset": "2026-01-01T00:00:00",
        }
        conn = _FakeConnection(schema_info, statistics, FULL_CAPS)
        surveyor = DatabaseSurveyor(db_entity, {"user": "a", "password": "b"}, registry)
        with _patched_connection(conn):
            result = surveyor.survey()

        rfas = [a for a in result["annotations"] if isinstance(a, RequestForActionAnnotation)]
        assert rfas == []
        measures = [
            a for a in result["annotations"]
            if getattr(a, "resource_properties", {}).get("index") == "customers_pkey"
        ]
        assert len(measures) == 1
        assert measures[0].resource_properties["idx_scan"] == 500

    def test_unused_non_primary_index_raises_rfa(self, registry, db_entity):
        schema_info = _schema_info(columns=("id", "email"))
        statistics = {
            "column_stats": [], "table_activity": [],
            "index_stats": [
                {"schemaname": "public", "tablename": "customers",
                 "indexrelname": "idx_customers_email", "idx_scan": 0,
                 "idx_tup_read": 0, "idx_tup_fetch": 0,
                 "is_unique": False, "is_primary": False, "index_size_bytes": 16384},
            ],
            "stats_reset": "2026-01-01T00:00:00",
        }
        conn = _FakeConnection(schema_info, statistics, FULL_CAPS)
        surveyor = DatabaseSurveyor(db_entity, {"user": "a", "password": "b"}, registry)
        with _patched_connection(conn):
            result = surveyor.survey()

        rfas = [a for a in result["annotations"] if isinstance(a, RequestForActionAnnotation)]
        assert len(rfas) == 1
        assert "idx_customers_email" in rfas[0].action_target_name

    def test_unused_primary_key_index_does_not_raise_rfa(self, registry, db_entity):
        """A zero-scan primary key is not flagged — PKs are frequently
        enforced for uniqueness rather than queried directly."""
        schema_info = _schema_info(columns=("id",))
        statistics = {
            "column_stats": [], "table_activity": [],
            "index_stats": [
                {"schemaname": "public", "tablename": "customers",
                 "indexrelname": "customers_pkey", "idx_scan": 0,
                 "idx_tup_read": 0, "idx_tup_fetch": 0,
                 "is_unique": True, "is_primary": True, "index_size_bytes": 8192},
            ],
            "stats_reset": "",
        }
        conn = _FakeConnection(schema_info, statistics, FULL_CAPS)
        surveyor = DatabaseSurveyor(db_entity, {"user": "a", "password": "b"}, registry)
        with _patched_connection(conn):
            result = surveyor.survey()

        rfas = [a for a in result["annotations"] if isinstance(a, RequestForActionAnnotation)]
        assert rfas == []

    def test_index_capability_absent_produces_no_per_index_annotations(self, registry, db_entity):
        schema_info = _schema_info(columns=("id",))
        no_index_caps = EngineCapabilities(
            column_stats=True, tuple_counters=True, index_stats=False,
        )
        statistics = {
            "column_stats": [], "table_activity": [],
            # Present in the data, but capability says this engine can't —
            # must not be used.
            "index_stats": [
                {"schemaname": "public", "tablename": "customers",
                 "indexrelname": "customers_pkey", "idx_scan": 0,
                 "is_unique": True, "is_primary": True},
            ],
            "stats_reset": "",
        }
        conn = _FakeConnection(schema_info, statistics, no_index_caps)
        surveyor = DatabaseSurveyor(db_entity, {"user": "a", "password": "b"}, registry)
        with _patched_connection(conn):
            result = surveyor.survey()

        per_index = [
            a for a in result["annotations"]
            if getattr(a, "resource_properties", {}).get("index")
        ]
        assert per_index == []
        rfas = [a for a in result["annotations"] if isinstance(a, RequestForActionAnnotation)]
        assert rfas == []
        not_established = [
            a for a in result["annotations"]
            if getattr(a, "resource_properties", {}).get("capability") == "index_stats"
        ]
        assert len(not_established) == 1
        assert not_established[0].resource_properties["supported"] is False


class TestEngineCapabilitiesDeclaration:
    def test_postgres_connection_declares_the_three_slice_7_capabilities(self):
        from resource_explorer.surveyors.database.connection import PostgreSQLConnection

        conn = PostgreSQLConnection(
            host="localhost", port=5432, database="x", user="u", password="p",
        )
        caps = conn.capabilities
        assert caps.column_stats is True
        assert caps.tuple_counters is True
        assert caps.index_stats is True
        # query_stats: still not implemented anywhere — declaring it True
        # would be a promise this build does not keep (design §5.1's
        # honest-absence rule).
        assert caps.query_stats is False
        # replication_status/resilience/external_dependencies/privileges:
        # Phase 1 slice 8 (postgres_operations, design §5.5/§5.7) implements
        # these — see test_postgres_operations_step.py for the dedicated
        # coverage of what they gate.
        assert caps.replication_status is True
        assert caps.resilience is True
        assert caps.external_dependencies is True
        assert caps.privileges is True

    def test_default_capabilities_are_all_false(self):
        from resource_explorer.surveyors.database.connection import (
            DatabaseConnection,
            NO_CAPABILITIES,
        )

        assert NO_CAPABILITIES == type(NO_CAPABILITIES)()
        assert all(v is False for v in NO_CAPABILITIES.as_dict().values())
