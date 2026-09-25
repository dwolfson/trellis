"""Tests for the postgres_operations step (Phase 1 slice 8,
COORDINATOR-BRIEF-MULTI-RESOURCE.md, design §5.5/§5.7): privilege_audit,
db_activity_signals, db_resilience, db_external_dependencies.

No live Postgres is used — `_FakeOpsConnection` is a duck-typed stand-in for
`PostgreSQLConnection`, exercising the real `DatabaseSurveyor._survey_operations`
/ `_create_operations_annotations` code path end to end, same pattern as
`test_postgres_schema_and_stats_extension.py` (slice 7).

Covered here, one class per concern:

* privilege_audit — RFA fires on a PUBLIC grant, and does not fire when
  there is none.
* db_resilience — all three absence states: capability-absent, a genuine
  standalone-with-no-replication positive finding, and a replica-with-lag
  case.
* db_external_dependencies — detects an FDW and an extension.
* db_activity_signals — reuses (does not re-derive) slice #7's
  get_table_activity()/get_stats_reset() data.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors.database.connection import EngineCapabilities
from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor
from resource_explorer.surveyors.survey_report import (
    RequestForActionAnnotation,
    ResourceMeasureAnnotation,
    ResourcePhysicalStatusAnnotation,
    SchemaAnalysisAnnotation,
)


class _FakeOpsConnection:
    """Duck-typed stand-in for PostgreSQLConnection covering exactly the
    methods DatabaseSurveyor's "operations" step calls: get_schema_info(),
    the six new get_*() reads, and the `capabilities` property. Each test
    wires only what it needs; unused reads default to empty.
    """

    def __init__(
        self,
        capabilities: EngineCapabilities,
        schema_info: dict | None = None,
        privilege_audit: dict | None = None,
        table_activity: list[dict] | None = None,
        stats_reset: str = "",
        replication_status: dict | None = None,
        wal_archiving: dict | None = None,
        backup_tool_signals: dict | None = None,
        clustering: dict | None = None,
        external_dependencies: dict | None = None,
    ):
        self._capabilities = capabilities
        self._schema_info = schema_info or {"schemas": [], "total_tables": 0, "total_columns": 0}
        self._privilege_audit = privilege_audit or {"roles": [], "table_grants": [], "default_acl": []}
        self._table_activity = table_activity or []
        self._stats_reset = stats_reset
        self._replication_status = replication_status or {"is_in_recovery": None, "replicas": []}
        self._wal_archiving = wal_archiving or {
            "archive_mode": "", "archived_count": None, "failed_count": None,
            "last_archived_time": "", "last_failed_time": "",
        }
        self._backup_tool_signals = backup_tool_signals or {"detected_extensions": []}
        self._clustering = clustering or {"citus_detected": False, "citus_version": None}
        self._external_dependencies = external_dependencies or {
            "extensions": [], "foreign_servers": [], "foreign_tables": [],
            "publications": [], "subscriptions": [],
        }

    @property
    def capabilities(self):
        return self._capabilities

    def get_schema_info(self):
        return self._schema_info

    def get_statistics(self):
        return {}

    def get_privilege_audit(self):
        return self._privilege_audit

    def get_table_activity(self):
        return self._table_activity

    def get_stats_reset(self):
        return self._stats_reset

    def get_replication_status(self):
        return self._replication_status

    def get_wal_archiving_status(self):
        return self._wal_archiving

    def get_backup_tool_signals(self):
        return self._backup_tool_signals

    def get_clustering_info(self):
        return self._clustering

    def get_external_dependencies(self):
        return self._external_dependencies


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


FULL_OPS_CAPS = EngineCapabilities(
    replication_status=True, resilience=True, external_dependencies=True, privileges=True,
    tuple_counters=True,
)
NO_OPS_CAPS = EngineCapabilities()


def _run_operations(db_entity, registry, conn):
    surveyor = DatabaseSurveyor(db_entity, {"user": "a", "password": "b"}, registry)
    with _patched_connection(conn):
        return surveyor.survey(steps=["operations"])


def _by_type(annotations, cls):
    return [a for a in annotations if isinstance(a, cls)]


class TestPrivilegeAuditPublicGrantRFA:
    def test_rfa_fires_on_a_public_grant(self, registry, db_entity):
        conn = _FakeOpsConnection(
            FULL_OPS_CAPS,
            privilege_audit={
                "roles": [{"rolname": "app_user", "rolsuper": False}],
                "table_grants": [
                    {"table_schema": "public", "table_name": "customers",
                     "grantee": "PUBLIC", "privilege_type": "SELECT", "is_grantable": "NO"},
                ],
                "default_acl": [],
            },
        )
        result = _run_operations(db_entity, registry, conn)

        rfas = _by_type(result["annotations"], RequestForActionAnnotation)
        public_rfas = [a for a in rfas if "PUBLIC" in a.summary]
        assert len(public_rfas) == 1
        assert public_rfas[0].action_target_name == "public.customers"
        assert "SELECT" in public_rfas[0].summary

    def test_no_rfa_when_no_public_grants(self, registry, db_entity):
        conn = _FakeOpsConnection(
            FULL_OPS_CAPS,
            privilege_audit={
                "roles": [{"rolname": "app_user", "rolsuper": False}],
                "table_grants": [
                    {"table_schema": "public", "table_name": "customers",
                     "grantee": "app_user", "privilege_type": "SELECT", "is_grantable": "NO"},
                ],
                "default_acl": [],
            },
        )
        result = _run_operations(db_entity, registry, conn)

        rfas = _by_type(result["annotations"], RequestForActionAnnotation)
        assert not any("PUBLIC" in a.summary for a in rfas)
        # Still a measured summary annotation, just no RFA.
        measures = _by_type(result["annotations"], ResourceMeasureAnnotation)
        assert any("1 role" in a.summary for a in measures)

    def test_capability_absent_renders_not_supported_not_zero(self, registry, db_entity):
        conn = _FakeOpsConnection(NO_OPS_CAPS)
        result = _run_operations(db_entity, registry, conn)

        measures = _by_type(result["annotations"], ResourceMeasureAnnotation)
        not_supported = [
            a for a in measures
            if a.resource_properties.get("capability") == "privileges"
        ]
        assert len(not_supported) == 1
        assert not_supported[0].confidence == 0
        assert not_supported[0].resource_properties["supported"] is False


class TestDbResilienceThreeAbsenceStates:
    def test_capability_absent(self, registry, db_entity):
        conn = _FakeOpsConnection(NO_OPS_CAPS)
        result = _run_operations(db_entity, registry, conn)

        measures = _by_type(result["annotations"], ResourceMeasureAnnotation)
        not_supported = [
            a for a in measures if a.resource_properties.get("capability") == "resilience"
        ]
        assert len(not_supported) == 1
        assert not_supported[0].confidence == 0
        # No ResourcePhysicalStatusAnnotation at all when the capability is absent.
        assert not _by_type(result["annotations"], ResourcePhysicalStatusAnnotation)

    def test_standalone_with_no_replicas_is_a_real_positive_finding(self, registry, db_entity):
        conn = _FakeOpsConnection(
            FULL_OPS_CAPS,
            replication_status={"is_in_recovery": False, "replicas": []},
        )
        result = _run_operations(db_entity, registry, conn)

        statuses = _by_type(result["annotations"], ResourcePhysicalStatusAnnotation)
        assert len(statuses) == 1
        status = statuses[0]
        assert status.confidence == 100
        assert "Standalone" in status.summary
        assert status.physical_properties["role"] == "standalone"
        assert status.physical_properties["replica_count"] == 0
        # Enrichment half explicitly pending, never silently omitted.
        assert status.physical_properties["last_backup_date"] is None
        assert "last_backup_date" in status.physical_properties["enrichment_pending"]
        assert "restore_test_date" in status.physical_properties["enrichment_pending"]

    def test_replica_with_lag(self, registry, db_entity):
        conn = _FakeOpsConnection(
            FULL_OPS_CAPS,
            replication_status={
                "is_in_recovery": False,
                "replicas": [
                    {"application_name": "standby1", "client_addr": "10.0.0.5",
                     "state": "streaming", "sync_state": "async",
                     "replay_lag_seconds": 42.0},
                ],
            },
        )
        result = _run_operations(db_entity, registry, conn)

        statuses = _by_type(result["annotations"], ResourcePhysicalStatusAnnotation)
        assert len(statuses) == 1
        status = statuses[0]
        assert status.confidence == 100
        assert "Primary with 1 replica" in status.summary
        assert "42" in status.summary
        assert status.physical_properties["role"] == "primary"
        assert status.physical_properties["replica_count"] == 1
        assert status.physical_properties["replicas"][0]["replay_lag_seconds"] == 42.0

    def test_mixed_envelope_says_which_half_answered(self, registry, db_entity):
        conn = _FakeOpsConnection(
            FULL_OPS_CAPS,
            replication_status={"is_in_recovery": False, "replicas": []},
            wal_archiving={
                "archive_mode": "on", "archived_count": 10, "failed_count": 0,
                "last_archived_time": "2026-09-20T00:00:00", "last_failed_time": "",
            },
            backup_tool_signals={"detected_extensions": []},
        )
        result = _run_operations(db_entity, registry, conn)
        status = _by_type(result["annotations"], ResourcePhysicalStatusAnnotation)[0]
        assert status.physical_properties["archive_mode"] == "on"
        assert "MIXED" in status.explanation
        assert "not machine-observable" in status.explanation.lower() or \
               "not machine-observable" in status.explanation


class TestDbExternalDependencies:
    def test_detects_fdw_and_extension(self, registry, db_entity):
        conn = _FakeOpsConnection(
            FULL_OPS_CAPS,
            external_dependencies={
                "extensions": [{"extname": "postgres_fdw", "extversion": "1.1"}],
                "foreign_servers": [{"srvname": "remote_srv", "fdwname": "postgres_fdw"}],
                "foreign_tables": [{"schema_name": "public", "table_name": "remote_orders", "srvname": "remote_srv"}],
                "publications": [],
                "subscriptions": [],
            },
        )
        result = _run_operations(db_entity, registry, conn)

        schemas = _by_type(result["annotations"], SchemaAnalysisAnnotation)
        deps = [a for a in schemas if a.schema_type == "external_dependencies"]
        assert len(deps) == 1
        assert "1 extension" in deps[0].summary
        assert "1 foreign server" in deps[0].summary
        assert "postgres_fdw" in deps[0].json_properties["extensions"]
        assert "remote_srv" in deps[0].json_properties["foreign_servers"]
        assert "public.remote_orders" in deps[0].json_properties["foreign_tables"]

    def test_capability_absent_renders_not_supported(self, registry, db_entity):
        conn = _FakeOpsConnection(NO_OPS_CAPS)
        result = _run_operations(db_entity, registry, conn)

        measures = _by_type(result["annotations"], ResourceMeasureAnnotation)
        not_supported = [
            a for a in measures
            if a.resource_properties.get("capability") == "external_dependencies"
        ]
        assert len(not_supported) == 1
        assert not_supported[0].confidence == 0


class TestDbActivitySignalsReusesSliceSevenData:
    def test_rolls_up_table_activity_without_requerying(self, registry, db_entity):
        activity_rows = [
            {"schemaname": "public", "tablename": "orders",
             "rows_inserted": 100, "rows_updated": 10, "rows_deleted": 1,
             "seq_scan": 0, "idx_scan": 50},
            {"schemaname": "public", "tablename": "audit_log",
             "rows_inserted": 5, "rows_updated": 0, "rows_deleted": 0,
             "seq_scan": 0, "idx_scan": 0},
        ]
        conn = _FakeOpsConnection(
            FULL_OPS_CAPS,
            schema_info={"schemas": [], "total_tables": 2, "total_columns": 0},
            table_activity=activity_rows,
            stats_reset="2026-01-01T00:00:00",
        )
        result = _run_operations(db_entity, registry, conn)

        measures = _by_type(result["annotations"], ResourceMeasureAnnotation)
        rollup = [a for a in measures if "Database-wide activity" in a.summary]
        assert len(rollup) == 1
        props = rollup[0].resource_properties
        assert props["tables_measured"] == 2
        assert props["rows_inserted_total"] == 105
        assert props["rows_updated_total"] == 10
        assert props["rows_deleted_total"] == 1
        assert props["tables_with_no_reads"] == ["public.audit_log"]
        assert props["stats_reset"] == "2026-01-01T00:00:00"

        # The operations step's own fetch reused get_table_activity()/
        # get_stats_reset() rather than a second query path — verified by
        # construction: _FakeOpsConnection has no other activity source, so
        # a mismatch here would mean the surveyor invented its own numbers.
        assert result["operations"]["activity_signals"]["table_activity"] == activity_rows

    def test_capability_absent_renders_not_supported_not_zero_activity(self, registry, db_entity):
        conn = _FakeOpsConnection(NO_OPS_CAPS)
        result = _run_operations(db_entity, registry, conn)

        measures = _by_type(result["annotations"], ResourceMeasureAnnotation)
        not_supported = [
            a for a in measures if a.resource_properties.get("capability") == "tuple_counters"
        ]
        assert len(not_supported) == 1
        assert not_supported[0].confidence == 0

    def test_tables_in_catalog_but_no_stats_rows_is_not_collected_not_zero(self, registry, db_entity):
        conn = _FakeOpsConnection(
            FULL_OPS_CAPS,
            schema_info={"schemas": [], "total_tables": 3, "total_columns": 0},
            table_activity=[],
        )
        result = _run_operations(db_entity, registry, conn)

        measures = _by_type(result["annotations"], ResourceMeasureAnnotation)
        not_collected = [a for a in measures if "not yet accumulated" in a.summary]
        assert len(not_collected) == 1
        assert not_collected[0].confidence == 0
        assert not_collected[0].resource_properties["table_count"] == 3


class TestOperationsIsOptInNotDefault:
    def test_default_survey_does_not_run_operations(self, registry, db_entity):
        """"operations" is deliberately not in _ALL_STEPS — a default
        survey() (no explicit steps) must not silently pay for it."""
        conn = _FakeOpsConnection(FULL_OPS_CAPS)
        surveyor = DatabaseSurveyor(db_entity, {"user": "a", "password": "b"}, registry)
        with _patched_connection(conn):
            result = surveyor.survey()

        assert result["operations"] == {}
        assert not _by_type(result["annotations"], ResourcePhysicalStatusAnnotation)
