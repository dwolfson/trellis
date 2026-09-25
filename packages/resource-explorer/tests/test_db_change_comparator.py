"""Tests for db_change_comparator.py — Phase 1 slice 14 (design §9.1),
"database change comparators on the local delivery path."

The bridge under test: `derive_change_rates`'s already-computed per-table
deltas and schema churn (slice 9), turned into a `ChangeResult` the
scheduler's Automate subscription check can act on. Nothing here
re-derives a delta — every case sets up rows the same way
tests/test_db_derived_step.py does and asserts on the resulting
`ChangeResult`, not on a parallel computation.
"""
from __future__ import annotations

from resource_explorer.notification_detector import ChangeResult
from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors.database.db_change_comparator import (
    DATABASE_CHANGE_COMPARATORS,
    detect_database_change,
)

NOW = "2026-09-21T12:00:00"
EARLIER = "2026-09-14T12:00:00"


def _table(name, *, rows=1000, size=8192, schema="public"):
    return {
        "schema_name": schema, "table_name": name, "table_type": "BASE TABLE",
        "row_count": rows, "column_count": 3, "size_bytes": size,
        "description": "", "state": "measured",
    }


def _activity(table, *, ins=0, upd=0, dele=0, reset=None, schema="public"):
    return {
        "schema_name": schema, "table_name": table,
        "rows_inserted": ins, "rows_updated": upd, "rows_deleted": dele,
        "seq_scan": 0, "idx_scan": 0, "stats_reset": reset,
        "state": "measured",
    }


def _column(table, name, *, data_type="text", position=1, schema="public"):
    return {
        "schema_name": schema, "table_name": table, "column_name": name,
        "ordinal_position": position, "data_type": data_type, "base_type": data_type,
        "is_nullable": 1, "is_primary_key": 0, "state": "measured",
    }


def _grant(*, grantee, privilege="SELECT", object_name="orders", schema="public"):
    return {
        "schema_name": schema, "object_name": object_name, "object_type": "table",
        "grantee": grantee, "grantor": "postgres", "privilege_type": privilege,
        "is_grantable": 0, "state": "measured",
    }


def _store(registry, slug, surveyed_at, *, tables=None, activity=None, columns=None, grants=None):
    tables = tables or []
    registry.record_database_survey(
        slug=slug, schema_count=1, table_count=len(tables),
        column_count=len(columns or []), survey_data={}, source="local", surveyed_at=surveyed_at,
    )
    if tables:
        registry.write_detail_rows("database_tables", slug, surveyed_at, source="local", rows=tables)
    if activity:
        registry.write_detail_rows("database_table_activity", slug, surveyed_at, source="local", rows=activity)
    if columns:
        registry.write_detail_rows("database_columns", slug, surveyed_at, source="local", rows=columns)
    if grants:
        registry.write_detail_rows("database_grants", slug, surveyed_at, source="local", rows=grants)


def _registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.register_database(DatabaseEntity(
        slug="coco_ods", display_name="Coco ODS", db_type="postgresql",
        host="localhost", port=5442, database_name="coco_ods",
    ))
    return r


class TestDbChangeRatesComparator:
    def test_no_snapshots_is_not_established_and_not_changed(self, tmp_path):
        registry = _registry(tmp_path)
        result = detect_database_change(registry, "coco_ods", "db_change_rates")
        assert result == ChangeResult(changed=False, established=False, summary=result.summary)
        assert not result.changed
        assert not result.established

    def test_one_snapshot_is_insufficient_history_not_established(self, tmp_path):
        """The brief's absence-discipline case, carried through the
        comparator: one snapshot must not read the same as "measured, no
        change" — it must not fire a notification, but the reason recorded
        (`established=False`) is different from a real negative."""
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", NOW,
               tables=[_table("orders")], activity=[_activity("orders", ins=100)])
        result = detect_database_change(registry, "coco_ods", "db_change_rates")
        assert result.changed is False
        assert result.established is False
        assert "insufficient" in result.summary.lower() or "snapshot" in result.summary.lower()

    def test_two_idle_snapshots_are_measured_no_change(self, tmp_path):
        """A real negative: two comparable snapshots, nothing moved. Must be
        distinguishable from the insufficient-history case above."""
        registry = _registry(tmp_path)
        for at in (EARLIER, NOW):
            _store(registry, "coco_ods", at,
                   tables=[_table("orders")],
                   activity=[_activity("orders", ins=100, reset="2026-09-01T00:00:00")])
        result = detect_database_change(registry, "coco_ods", "db_change_rates")
        assert result.changed is False
        assert result.established is True

    def test_row_activity_between_snapshots_is_a_real_change(self, tmp_path):
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", EARLIER,
               tables=[_table("orders", rows=100)],
               activity=[_activity("orders", ins=1_000, reset="2026-09-01T00:00:00")])
        _store(registry, "coco_ods", NOW,
               tables=[_table("orders", rows=800)],
               activity=[_activity("orders", ins=8_000, reset="2026-09-01T00:00:00")])
        result = detect_database_change(registry, "coco_ods", "db_change_rates")
        assert result.changed is True
        assert result.established is True
        assert "orders" in result.summary
        assert "7000" in result.summary or "7,000" in result.summary

    def test_a_new_table_is_a_real_change_via_schema_churn(self, tmp_path):
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", EARLIER,
               tables=[_table("orders")], activity=[_activity("orders", ins=10)])
        _store(registry, "coco_ods", NOW,
               tables=[_table("orders"), _table("shipments")],
               activity=[_activity("orders", ins=10), _activity("shipments", ins=5)])
        result = detect_database_change(registry, "coco_ods", "db_change_rates")
        assert result.changed is True
        assert "shipments" in result.summary
        assert "added" in result.summary

    def test_a_dropped_table_is_a_real_change(self, tmp_path):
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", EARLIER,
               tables=[_table("orders"), _table("legacy")],
               activity=[_activity("orders", ins=10)])
        _store(registry, "coco_ods", NOW,
               tables=[_table("orders")], activity=[_activity("orders", ins=10)])
        result = detect_database_change(registry, "coco_ods", "db_change_rates")
        assert result.changed is True
        assert "legacy" in result.summary
        assert "removed" in result.summary

    def test_a_counter_reset_alone_does_not_count_as_row_activity(self, tmp_path):
        """derive_change_rates marks a reset table `counters_reset`, not
        `active` — the comparator must not treat that as a change, since a
        reset carries no real delta at all (it is explicitly `not measured`
        for that table)."""
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", EARLIER,
               tables=[_table("orders")],
               activity=[_activity("orders", ins=50_000, reset="2026-09-01T00:00:00")])
        _store(registry, "coco_ods", NOW,
               tables=[_table("orders")],
               activity=[_activity("orders", ins=10_000, reset="2026-09-20T00:00:00")])
        result = detect_database_change(registry, "coco_ods", "db_change_rates")
        assert result.changed is False
        assert result.established is True


class TestSchemaDiffComparator:
    def test_no_snapshots_is_not_established_and_not_changed(self, tmp_path):
        registry = _registry(tmp_path)
        result = detect_database_change(registry, "coco_ods", "schema_diff")
        assert result.changed is False
        assert result.established is False

    def test_one_snapshot_is_insufficient_history_not_established(self, tmp_path):
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", NOW, columns=[_column("orders", "id")])
        result = detect_database_change(registry, "coco_ods", "schema_diff")
        assert result.changed is False
        assert result.established is False
        assert "insufficient" in result.summary.lower() or "snapshot" in result.summary.lower()

    def test_two_identical_snapshots_are_measured_no_change(self, tmp_path):
        registry = _registry(tmp_path)
        cols = [_column("orders", "id"), _column("orders", "total", position=2, data_type="numeric")]
        for at in (EARLIER, NOW):
            _store(registry, "coco_ods", at, columns=cols)
        result = detect_database_change(registry, "coco_ods", "schema_diff")
        assert result.changed is False
        assert result.established is True

    def test_a_new_column_on_an_existing_table_is_a_real_change(self, tmp_path):
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", EARLIER, columns=[_column("orders", "id")])
        _store(registry, "coco_ods", NOW, columns=[
            _column("orders", "id"),
            _column("orders", "customer_id", position=2, data_type="integer"),
        ])
        result = detect_database_change(registry, "coco_ods", "schema_diff")
        assert result.changed is True
        assert result.established is True
        assert "orders.customer_id" in result.summary
        assert "added" in result.summary

    def test_a_dropped_column_is_a_real_change(self, tmp_path):
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", EARLIER, columns=[
            _column("orders", "id"), _column("orders", "legacy_flag", position=2),
        ])
        _store(registry, "coco_ods", NOW, columns=[_column("orders", "id")])
        result = detect_database_change(registry, "coco_ods", "schema_diff")
        assert result.changed is True
        assert "orders.legacy_flag" in result.summary
        assert "dropped" in result.summary

    def test_a_retyped_column_is_a_real_change(self, tmp_path):
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", EARLIER, columns=[_column("orders", "amount", data_type="integer")])
        _store(registry, "coco_ods", NOW, columns=[_column("orders", "amount", data_type="numeric")])
        result = detect_database_change(registry, "coco_ods", "schema_diff")
        assert result.changed is True
        assert "retyped" in result.summary
        assert "integer" in result.summary and "numeric" in result.summary

    def test_a_brand_new_table_columns_are_not_double_reported(self, tmp_path):
        """A whole new table's columns are db_change_rates's schema-churn
        story, not schema_diff's — schema_diff is scoped to tables present
        in both snapshots."""
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", EARLIER, columns=[_column("orders", "id")])
        _store(registry, "coco_ods", NOW, columns=[
            _column("orders", "id"),
            _column("shipments", "id"),
        ])
        result = detect_database_change(registry, "coco_ods", "schema_diff")
        assert result.changed is False
        assert result.established is True


class TestGrantChangeComparator:
    def test_no_snapshots_is_not_established_and_not_changed(self, tmp_path):
        registry = _registry(tmp_path)
        result = detect_database_change(registry, "coco_ods", "grant_change")
        assert result.changed is False
        assert result.established is False

    def test_one_snapshot_is_insufficient_history_not_established(self, tmp_path):
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", NOW, grants=[_grant(grantee="app_user")])
        result = detect_database_change(registry, "coco_ods", "grant_change")
        assert result.changed is False
        assert result.established is False
        assert "insufficient" in result.summary.lower() or "snapshot" in result.summary.lower()

    def test_two_identical_snapshots_are_measured_no_change(self, tmp_path):
        registry = _registry(tmp_path)
        grants = [_grant(grantee="app_user")]
        for at in (EARLIER, NOW):
            _store(registry, "coco_ods", at, grants=grants)
        result = detect_database_change(registry, "coco_ods", "grant_change")
        assert result.changed is False
        assert result.established is True

    def test_a_new_grant_to_public_is_unambiguously_flagged(self, tmp_path):
        """The coordinator brief's own done-test case: a new PUBLIC grant
        must not be buried in a generic 'grants changed' message."""
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", EARLIER, grants=[_grant(grantee="app_user")])
        _store(registry, "coco_ods", NOW, grants=[
            _grant(grantee="app_user"), _grant(grantee="PUBLIC"),
        ])
        result = detect_database_change(registry, "coco_ods", "grant_change")
        assert result.changed is True
        assert result.established is True
        assert "PUBLIC" in result.summary

    def test_a_new_non_public_grant_is_a_real_change(self, tmp_path):
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", EARLIER, grants=[_grant(grantee="app_user")])
        _store(registry, "coco_ods", NOW, grants=[
            _grant(grantee="app_user"), _grant(grantee="reporting_user", privilege="SELECT"),
        ])
        result = detect_database_change(registry, "coco_ods", "grant_change")
        assert result.changed is True
        assert "reporting_user" in result.summary
        assert "PUBLIC" not in result.summary

    def test_a_revoked_grant_is_a_real_change(self, tmp_path):
        registry = _registry(tmp_path)
        _store(registry, "coco_ods", EARLIER, grants=[
            _grant(grantee="app_user"), _grant(grantee="reporting_user"),
        ])
        _store(registry, "coco_ods", NOW, grants=[_grant(grantee="app_user")])
        result = detect_database_change(registry, "coco_ods", "grant_change")
        assert result.changed is True
        assert "reporting_user" in result.summary
        assert "revoked" in result.summary


class TestDispatch:
    def test_unknown_analysis_id_is_not_established_not_a_measured_negative(self, tmp_path):
        registry = _registry(tmp_path)
        result = detect_database_change(registry, "coco_ods", "db_classification")
        assert result.changed is False
        assert result.established is False
        assert "no change comparator" in result.summary.lower()

    def test_the_dispatch_table_is_the_single_source_the_function_reads(self, tmp_path):
        """Guards against a future analysis_id being handled by an
        `if`/`elif` chain that this dict-driven dispatcher's docstring
        promises not to be."""
        assert set(DATABASE_CHANGE_COMPARATORS) == {"db_change_rates", "schema_diff", "grant_change"}
