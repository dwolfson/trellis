"""Backlog 7i: statistics currency in the measurement annotations, and the
"Statistics freshness" analysis.

(a) Each table's published "Capture Database Table Measurements" annotation
    carries last analyze / autoanalyze / vacuum / autovacuum, changes since the
    last analyze, live and dead rows and the database's stats-reset time, named
    in Egeria's own Metric style in ONE module. "Never" (Postgres NULL, stated)
    is distinct from "not read" (key absent, reason given); neither is 0 or "".
(b) `db_statistics_freshness`: per table never analyzed / N days ago / changes
    against autovacuum's own trigger, a per-schema roll-up, from stored rows only.

The publish test drives the real path (`_survey_operations` -> `publish_step_
annotations` -> `publish_annotations`) and fakes only the database connection
and the Egeria client, then reads the bodies Egeria would have received.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from resource_explorer.registry import (
    STATE_MEASURED,
    STATE_NOT_MEASURED,
    STATS_NEVER_RESET,
    DatabaseEntity,
    ProjectRegistry,
)
from resource_explorer.surveyors.database import table_statistics_metrics as tsm
from resource_explorer.surveyors.database.db_derived import (
    DB_DERIVED_ANALYSES,
    derive_statistics_freshness,
    load_inputs,
    run_db_derived,
)

NOW = "2026-10-10T12:00:00"
ROOT = Path(__file__).resolve().parent.parent
QUESTION = "Are this database's planner statistics current?"


# ═══════════════════════════════════════════════════════════════════════════
# (a) the metric names: one module, Egeria's style
# ═══════════════════════════════════════════════════════════════════════════

class TestTheMetricNames:
    def test_egeria_names_are_copied_verbatim_and_flagged(self):
        egeria = {m.property_name: m for m in tsm.TABLE_STATISTICS_METRICS if m.in_egeria}
        assert set(egeria) == {
            "numberOfRowsInserted", "numberOfRowsUpdated", "numberOfRowsDeleted",
            "lastStatisticsReset",
        }
        # Spot-check against RelationalTableMetric / RelationalDatabaseMetric.
        assert egeria["numberOfRowsInserted"].display_name == "Number Of Rows Inserted"
        assert egeria["lastStatisticsReset"].display_name == "Last statistics reset"
        assert egeria["lastStatisticsReset"].description == (
            "Last time that the statistics were reset in the database.")

    def test_the_proposed_metrics_are_in_the_same_style(self):
        proposed = {m.property_name for m in tsm.PROPOSED_FOR_UPSTREAM}
        assert proposed == {
            "lastAnalyze", "lastAutoAnalyze", "lastVacuum", "lastAutoVacuum",
            "numberOfRowsChangedSinceAnalyze", "numberOfLiveRows", "numberOfDeadRows",
        }
        for m in tsm.PROPOSED_FOR_UPSTREAM:
            assert m.property_name[0].islower() and "_" not in m.property_name
            assert m.data_type in ("long", "date")
            assert m.display_name and m.description.endswith(".")
        assert "proposed for upstream" in tsm.__doc__.lower()

    def test_no_other_module_spells_the_proposed_names(self):
        """One place: the proposed property names appear as literals in the
        constants module only (and tests), never re-typed in a surveyor."""
        src = (ROOT / "resource_explorer")
        offenders = []
        for path in src.rglob("*.py"):
            if path.name == "table_statistics_metrics.py":
                continue
            text = path.read_text(encoding="utf-8")
            for m in tsm.PROPOSED_FOR_UPSTREAM:
                if f'"{m.property_name}"' in text:
                    offenders.append((path.name, m.property_name))
        assert offenders == []


class TestNeverIsNotUnread:
    def _row(self, **kw):
        base = {"rows_inserted": 5, "rows_updated": 0, "rows_deleted": 0, "live_tuples": 100,
                "dead_tuples": 0, "pending_changes": 7, "last_analyze": "",
                "last_autoanalyze": "2026-10-01 10:00:00+00:00", "last_vacuum": "",
                "last_autovacuum": ""}
        base.update(kw)
        return base

    def test_postgres_null_on_a_real_read_is_the_stated_word_never(self):
        props = tsm.table_statistics_properties(self._row(), "2026-09-01 00:00:00+00:00")
        assert props["lastAnalyze"] == tsm.NEVER == STATS_NEVER_RESET
        assert props["lastVacuum"] == "never"
        assert props["lastAutoAnalyze"] == "2026-10-01 10:00:00+00:00"
        assert tsm.NOT_READ_KEY not in props

    def test_a_true_zero_stays_zero(self):
        props = tsm.table_statistics_properties(self._row(dead_tuples=0, pending_changes=0), None)
        assert props["numberOfDeadRows"] == 0
        assert props["numberOfRowsChangedSinceAnalyze"] == 0

    def test_no_row_means_every_metric_is_absent_with_a_reason(self):
        props = tsm.table_statistics_properties(None, "2026-09-01")
        for name in ("lastAnalyze", "lastAutoAnalyze", "lastVacuum", "lastAutoVacuum",
                     "numberOfLiveRows", "numberOfDeadRows", "numberOfRowsChangedSinceAnalyze"):
            assert name not in props, name
            assert props[tsm.NOT_READ_KEY][name] == tsm.REASON_NO_STATS_ROW
        assert props["lastStatisticsReset"] == "2026-09-01"

    def test_a_backfilled_row_with_no_counters_does_not_claim_never(self):
        """Back-filled from an old blob: empty autoanalyze means 'that blob did
        not say', not 'Postgres said NULL'."""
        row = {"last_analyze": "2026-09-30 01:00:00", "last_vacuum": "", "last_autoanalyze": "",
               "last_autovacuum": "", "pending_changes": 4, "rows_inserted": None,
               "live_tuples": None, "dead_tuples": None}
        props = tsm.table_statistics_properties(row, None)
        assert props["lastAnalyze"] == "2026-09-30 01:00:00"      # a stated value stays
        assert "lastAutoAnalyze" not in props and "lastVacuum" not in props
        assert props[tsm.NOT_READ_KEY]["lastAutoAnalyze"] == tsm.REASON_NO_COUNTERS
        assert props["numberOfRowsChangedSinceAnalyze"] == 4

    def test_the_reset_time_has_three_states(self):
        stated = tsm.table_statistics_properties(self._row(), "2026-09-01 00:00:00+00:00")
        never = tsm.table_statistics_properties(self._row(), STATS_NEVER_RESET)
        unread = tsm.table_statistics_properties(self._row(), None)
        assert stated["lastStatisticsReset"] == "2026-09-01 00:00:00+00:00"
        assert never["lastStatisticsReset"] == "never"
        assert "lastStatisticsReset" not in unread
        assert unread[tsm.NOT_READ_KEY]["lastStatisticsReset"] == tsm.REASON_RESET_NOT_READ

    def test_no_value_is_ever_an_empty_string(self):
        for row in (self._row(), None, {"last_analyze": "", "live_tuples": None}):
            props = tsm.table_statistics_properties(row, None)
            assert all(v != "" for v in props.values())


# ═══════════════════════════════════════════════════════════════════════════
# (a) end to end through the real publish path
# ═══════════════════════════════════════════════════════════════════════════

class FakeConn:
    """Only what `_survey_operations` reads when just tuple_counters is on."""

    def __init__(self, activity, reset_evidence, reset=""):
        self._activity, self._evidence, self._reset = activity, reset_evidence, reset

    def get_table_activity(self):
        return self._activity

    def get_stats_reset(self):
        return self._reset

    def get_stats_reset_evidence(self):
        return self._evidence


def _pg_row(table, *, schema="public", analyze="", auto="", vac="", autovac="",
            live=1000, dead=0, pending=0, ins=10, upd=0, dele=0):
    return {
        "schemaname": schema, "tablename": table, "rows_inserted": ins,
        "rows_updated": upd, "rows_deleted": dele, "hot_updates": 0,
        "live_tuples": live, "dead_tuples": dead, "seq_scan": 1, "idx_scan": 1,
        "last_vacuum": vac, "last_autovacuum": autovac, "last_analyze": analyze,
        "last_autoanalyze": auto, "pending_changes": pending,
    }


def _publish(activity, reset_evidence, schema_tables, monkeypatch=None):
    """Run the real fetch + publish path; return the annotation bodies Egeria
    received, keyed by table (item key)."""
    from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor
    from resource_explorer.surveyors.database.connection import NO_CAPABILITIES
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor

    entity = DatabaseEntity(slug="coco", display_name="Coco", db_type="postgresql",
                            host="h", port=5432, database_name="coco")
    schema_info = {"schemas": [{"name": "public", "tables": [
        {"name": t, "columns": []} for t in schema_tables]}]}
    caps = dataclasses.replace(NO_CAPABILITIES, tuple_counters=True)
    operations = DatabaseSurveyor(entity, {}, None)._survey_operations(
        FakeConn(activity, reset_evidence), caps, schema_info)

    s = EgeriaDatabaseSurveyor(platform_url="https://localhost:9443", view_server="v",
                               user_id="u", user_password="p")
    s.connect = lambda: None
    s._find_by_qualified_name = lambda qn: "db-guid"
    s._find_element_guid = lambda qn: ""
    s._asset_maker = MagicMock()
    s._asset_maker.create_asset.return_value = "report-guid"
    s._discovery = MagicMock()
    s._discovery.create_annotation.side_effect = lambda body: f"ann-{len(s._discovery.create_annotation.call_args_list)}"
    s.publish_step_annotations(entity, schema_info, None, NOW, None, operations=operations)
    bodies = [c.kwargs["body"]["properties"] for c in s._discovery.create_annotation.call_args_list]
    return {b["qualifiedName"].rsplit("::", 1)[-1]: b for b in bodies
            if "table_statistics" in b["qualifiedName"]}


class TestPublishedTableAnnotations:
    def test_each_table_is_published_with_its_currency_metrics(self):
        out = _publish(
            [_pg_row("orders", analyze="2026-09-30 08:00:00+00:00", vac="2026-09-29 08:00:00+00:00",
                     live=5000, dead=12, pending=321, ins=40, upd=3, dele=1),
             _pg_row("audit", dead=0, pending=0)],
            "2026-09-01 00:00:00+00:00", ["orders", "audit"])
        assert set(out) == {"public.orders", "public.audit"}
        orders = out["public.orders"]
        assert orders["annotationType"] == "Capture Database Table Measurements"
        rp = orders["resourceProperties"]
        assert rp["lastAnalyze"] == "2026-09-30 08:00:00+00:00"
        assert rp["lastAutoAnalyze"] == "never"            # Postgres NULL, stated
        assert rp["lastVacuum"] == "2026-09-29 08:00:00+00:00"
        assert rp["numberOfRowsChangedSinceAnalyze"] == "321"
        assert rp["numberOfLiveRows"] == "5000" and rp["numberOfDeadRows"] == "12"
        assert rp["numberOfRowsInserted"] == "40" and rp["numberOfRowsDeleted"] == "1"
        assert rp["lastStatisticsReset"] == "2026-09-01 00:00:00+00:00"
        assert rp["tableName"] == "orders" and rp["tableQualifiedName"] == "coco.public.orders"
        assert "metricsNotRead" not in rp
        # A real zero is published as 0.
        assert out["public.audit"]["resourceProperties"]["numberOfDeadRows"] == "0"

    def test_a_table_with_no_statistics_row_is_published_as_not_read(self):
        out = _publish([_pg_row("orders")], "2026-09-01", ["orders", "ghost"])
        rp = out["public.ghost"]["resourceProperties"]
        assert "lastAnalyze" not in rp and "numberOfLiveRows" not in rp
        reasons = json.loads(rp["metricsNotRead"])
        assert reasons["lastAnalyze"] == tsm.REASON_NO_STATS_ROW
        assert reasons["numberOfDeadRows"] == tsm.REASON_NO_STATS_ROW
        assert out["public.ghost"]["confidence"] < out["public.orders"]["confidence"]

    def test_an_unread_reset_time_is_absent_and_a_never_reset_is_stated(self):
        unread = _publish([_pg_row("orders")], None, ["orders"])["public.orders"]["resourceProperties"]
        assert "lastStatisticsReset" not in unread
        assert json.loads(unread["metricsNotRead"])["lastStatisticsReset"] == tsm.REASON_RESET_NOT_READ
        never = _publish([_pg_row("orders")], STATS_NEVER_RESET, ["orders"])["public.orders"]["resourceProperties"]
        assert never["lastStatisticsReset"] == "never"

    def test_qualified_names_are_per_table_and_unique(self):
        from resource_explorer.surveyors.survey_report import annotation_qualified_name  # noqa: F401

        out = _publish([_pg_row("a"), _pg_row("b")], None, ["a", "b"])
        assert len(out) == 2   # two distinct identities, neither collapsed


# ═══════════════════════════════════════════════════════════════════════════
# (b) the analysis
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "fresh.db"))
    r.register_database(DatabaseEntity(
        slug="coco_ods", display_name="Coco ODS", db_type="postgresql",
        host="localhost", port=5442, database_name="coco_ods"))
    return r


def _table(name, *, schema="public", ttype="BASE TABLE"):
    return {"schema_name": schema, "table_name": name, "table_type": ttype,
            "row_count": 1000, "column_count": 3, "size_bytes": 8192,
            "description": "", "state": STATE_MEASURED}


def _act(table, *, schema="public", analyze="", auto="", live=1000, dead=0, pending=0,
         counters=True, reset="never"):
    return {
        "schema_name": schema, "table_name": table,
        "rows_inserted": 5 if counters else None, "rows_updated": 0 if counters else None,
        "rows_deleted": 0 if counters else None, "seq_scan": 1 if counters else None,
        "idx_scan": 1 if counters else None,
        "live_tuples": live if counters else None, "dead_tuples": dead if counters else None,
        "last_analyze": analyze, "last_autoanalyze": auto, "last_vacuum": "", "last_autovacuum": "",
        "pending_changes": pending, "stats_reset": reset, "state": STATE_MEASURED,
    }


def _store(registry, tables, activity, slug="coco_ods"):
    registry.record_database_survey(
        slug=slug, schema_count=1, table_count=len(tables), column_count=0,
        survey_data={}, source="local", surveyed_at=NOW)
    registry.write_detail_rows("database_tables", slug, NOW, source="local", rows=tables)
    if activity is not None:
        registry.write_detail_rows("database_table_activity", slug, NOW, source="local", rows=activity)


def _fresh(registry):
    return derive_statistics_freshness(load_inputs(registry, "coco_ods"))


def _by_table(result):
    return {e["table"]: e for e in result["tables"]}


class TestDeclared:
    def test_it_is_a_db_derived_check_and_a_catalog_analysis(self):
        import yaml

        assert "db_statistics_freshness" in DB_DERIVED_ANALYSES
        catalog = yaml.safe_load(
            (ROOT / "resource_explorer/configdata/analysis_catalog.yaml").read_text())
        [entry] = [a for a in catalog["database_analyses"] if a["id"] == "db_statistics_freshness"]
        assert entry["name"] == "Statistics Freshness"
        assert entry["resource_types"] == ["database"]

    def test_the_results_and_headline_maps_know_it(self):
        from resource_explorer.surveyors.database import survey_definition_adapter as sda

        assert "db_statistics_freshness" in sda.DATABASE_ANALYSIS_RESULTS_MAP
        assert "db_statistics_freshness" in sda.DATABASE_ANALYSIS_HEADLINE_MAP


class TestPerTable:
    def test_the_four_statuses(self, registry):
        _store(registry,
               [_table(n) for n in ("fresh", "stale", "never", "unread")],
               [_act("fresh", analyze="2026-10-08T12:00:00", live=1000, pending=100),
                _act("stale", auto="2026-09-10T12:00:00", live=1000, pending=5000),
                _act("never", pending=10),
                _act("unread", counters=False, pending=None)])
        t = _by_table(_fresh(registry))
        assert t["fresh"]["status"] == "current"
        assert t["stale"]["status"] == "stale"
        assert t["never"]["status"] == "never_analyzed"
        assert t["unread"]["status"] == "not_read"

    def test_a_table_with_no_activity_row_is_not_read_not_never(self, registry):
        _store(registry, [_table("a"), _table("b")], [_act("a", analyze="2026-10-09T00:00:00")])
        t = _by_table(_fresh(registry))
        assert t["b"]["status"] == "not_read"
        assert t["b"]["last_analyzed"] is None and t["b"]["days_since_analyze"] is None

    def test_the_threshold_is_autovacuums_own_and_the_boundary_is_exact(self, registry):
        # 50 + 0.1 * 1000 = 150: 150 changes is not past it, 151 is.
        _store(registry, [_table("at"), _table("over")],
               [_act("at", analyze="2026-10-09T00:00:00", live=1000, pending=150),
                _act("over", analyze="2026-10-09T00:00:00", live=1000, pending=151)])
        t = _by_table(_fresh(registry))
        assert t["at"]["threshold"] == 150.0 and t["at"]["above_threshold"] is False
        assert t["at"]["status"] == "current"
        assert t["over"]["above_threshold"] is True and t["over"]["status"] == "stale"
        assert t["over"]["changes_share"] == pytest.approx(0.151)

    def test_never_analyzed_uses_reltuples_zero_like_autovacuum(self, registry):
        _store(registry, [_table("n")], [_act("n", live=9_000_000, pending=51)])
        e = _by_table(_fresh(registry))["n"]
        assert e["status"] == "never_analyzed"
        assert e["threshold"] == 50.0 and e["above_threshold"] is True
        assert "reltuples taken as 0" in e["threshold_basis"]

    def test_days_since_analyze_is_relative_to_the_snapshot_not_to_now(self, registry):
        _store(registry, [_table("a")], [_act("a", analyze="2026-10-03 12:00:00+00:00")])
        e = _by_table(_fresh(registry))["a"]
        assert e["days_since_analyze"] == 7.0
        # The latest of analyze and autoanalyze is what counts.
        _store_again = _act("a", analyze="2026-09-01T00:00:00", auto="2026-10-09T12:00:00")
        registry.write_detail_rows("database_table_activity", "coco_ods", NOW, source="local",
                                   rows=[_store_again])
        e = _by_table(_fresh(registry))["a"]
        assert e["days_since_analyze"] == 1.0

    def test_analysed_but_change_count_unread_is_not_called_current(self, registry):
        _store(registry, [_table("a")], [_act("a", analyze="2026-10-09T00:00:00", pending=None)])
        e = _by_table(_fresh(registry))["a"]
        assert e["status"] == "not_read"
        assert e["changes_since_analyze"] is None

    def test_views_are_not_tables(self, registry):
        _store(registry, [_table("t"), _table("v", ttype="VIEW")], [_act("t", analyze="2026-10-09T00:00:00")])
        assert [e["table"] for e in _fresh(registry)["tables"]] == ["t"]

    def test_each_entry_carries_the_same_metrics_the_annotation_publishes(self, registry):
        _store(registry, [_table("a")], [_act("a", analyze="2026-10-09T00:00:00", dead=4, pending=9)])
        e = _by_table(_fresh(registry))["a"]
        assert e["metrics"] == tsm.table_statistics_properties(
            _act("a", analyze="2026-10-09T00:00:00", dead=4, pending=9), "never")


class TestRollupAndAbsence:
    def test_per_schema_roll_up_counts_every_status_separately(self, registry):
        _store(registry,
               [_table("a"), _table("b"), _table("c", schema="ops"), _table("d", schema="ops")],
               [_act("a", analyze="2026-10-09T00:00:00", pending=1),
                _act("b", analyze="2026-10-09T00:00:00", pending=900),
                _act("c", pending=3),
                _act("d", schema="ops", counters=False, pending=None)])
        result = _fresh(registry)
        schemas = {s["schema"]: s for s in result["schemas"]}
        assert schemas["public"]["tables"] == 2 and schemas["public"]["stale"] == 1
        assert schemas["ops"]["tables"] == 2
        assert schemas["ops"]["never_analyzed"] + schemas["ops"]["not_read"] == 2
        assert result["counts"]["not_read"] >= 1
        assert sum(result["counts"].values()) == result["table_count"] == 4

    def test_an_unread_schema_has_none_not_zero_for_its_figures(self, registry):
        _store(registry, [_table("a")], [_act("a", counters=False, pending=None)])
        # Only one table and it is unreadable: nothing was measured at all.
        result = _fresh(registry)
        assert result["state"] == STATE_NOT_MEASURED
        assert result["reason"] == "no_pg_stat_user_tables_rows"
        assert "NOT a finding" in result["explanation"]

    def test_no_stored_tables_is_not_established(self, registry):
        result = _fresh(registry)
        assert result["state"] == STATE_NOT_MEASURED and result["reason"] == "no_schema_rows"

    def test_the_settings_are_said_to_be_defaults(self, registry):
        _store(registry, [_table("a")], [_act("a", analyze="2026-10-09T00:00:00")])
        result = _fresh(registry)
        assert result["settings"] == {"autovacuum_analyze_threshold": 50,
                                      "autovacuum_analyze_scale_factor": 0.1}
        assert "defaults" in result["settings_source"] and "defaults" in result["explanation"]

    def test_the_step_returns_annotations_for_both_branches(self, registry):
        _store(registry, [_table("a"), _table("b")],
               [_act("a", analyze="2026-10-09T00:00:00"), _act("b", pending=2)])
        measured = [a for a in run_db_derived(registry, "coco_ods")["annotations"]
                    if a.check_name == "db_statistics_freshness"]
        [ann] = measured
        assert ann.confidence > 0
        assert ann.json_properties["attention_total"] == 1
        assert ann.json_properties["schemas"][0]["never_analyzed"] == 1

    def test_the_absence_annotation_is_unverified(self, registry):
        _store(registry, [_table("a")], None)
        [ann] = [a for a in run_db_derived(registry, "coco_ods")["annotations"]
                 if a.check_name == "db_statistics_freshness"]
        assert ann.label == "unverified" and ann.confidence == 0


# ═══════════════════════════════════════════════════════════════════════════
# The question
# ═══════════════════════════════════════════════════════════════════════════

def _question():
    from resource_explorer.surveyors.question_catalog_reader import get_questions

    return next(q for q in get_questions("database") if q["question"] == QUESTION)


class TestTheQuestion:
    def test_it_is_answered_by_the_analysis(self):
        q = _question()
        assert q["answering"]["kind"] == "analysis"
        assert q["answering"]["analysis_ids"] == ["db_statistics_freshness"]

    def test_it_answers_on_a_database_and_names_what_it_read(self, registry):
        from resource_explorer.facts import FactLayer
        from resource_explorer.surveyors.result_status import MEASURED

        _store(registry, [_table("a"), _table("b")],
               [_act("a", analyze="2026-10-09T00:00:00"), _act("b", pending=2)])
        env = FactLayer(registry, resource_type="database").answer("coco_ods", _question())
        assert env.answerable and not env.level_mismatch, env.level_note
        [fact] = env.facts
        assert fact.analysis_id == "db_statistics_freshness" and fact.state == MEASURED
        assert "never analyzed" in fact.headline
        assert fact.value["provenance"]["read_snapshot"] == NOW
        assert fact.value["counts"]["never_analyzed"] == 1

    def test_a_database_with_no_readable_statistics_is_not_answered(self, registry):
        from resource_explorer.facts import FactLayer

        _store(registry, [_table("a")], [_act("a", counters=False, pending=None)])
        env = FactLayer(registry, resource_type="database").answer("coco_ods", _question())
        assert not env.answerable
