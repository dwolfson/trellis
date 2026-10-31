"""LS5 spike: the two library twins (re_statistics_freshness, re_value_profile) and the RE_SPIKE_LIBRARY_TWINS flag.

The flag is tested both ways (configured AND read): off, the native ids answer from the native path and the twins' own ids
are hidden from the declared lists; on, the native ids answer from the twin's stored result. The twins run through the
host on a registry seeded with the rows the native analyses read, and their numbers are held to the native ones.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer import spike_twins
from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from tests.library_step_install import install_steps  # noqa: F401 - the fixture


def _db(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "db.db"))
    reg.register_database(DatabaseEntity(slug="coco", display_name="Coco", db_type="postgresql", host="localhost",
                                         egeria_host="h", port=5442, database_name="coco"))
    return reg


def _seed_profile(reg):
    cols = [("public", "orders", "id", "measured", "", "N", 100, 100, 100, 0, 100),
            ("public", "orders", "note", "measured", "", "A", 100, 80, 20, 20, 80),
            ("public", "v_orders", "id", "not_applicable", "a view, not profiled", "X", None, None, None, None, None)]
    with reg._conn() as conn:
        for sch, tab, col, state, reason, gt, rec, val, dist, nul, fil in cols:
            conn.execute(
                "INSERT INTO database_value_profiles (database_slug, surveyed_at, source, schema_name, table_name, "
                "column_name, state, reason, general_type, record_ct, value_ct, distinct_value_ct, null_value_ct, "
                "filled_value_ct) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("coco", "2026-10-30T10:00:00", "local", sch, tab, col, state, reason, gt, rec, val, dist, nul, fil))


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv(spike_twins.FLAG, raising=False)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv(spike_twins.FLAG, "1")


# ── the flag ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_flag_is_read_each_time_and_off_by_default(monkeypatch):
    monkeypatch.delenv(spike_twins.FLAG, raising=False)
    assert not spike_twins.enabled() and spike_twins.twin_for("value_profile") == ""
    monkeypatch.setenv(spike_twins.FLAG, "1")
    assert spike_twins.enabled() and spike_twins.twin_for("value_profile") == "re_value_profile"
    assert spike_twins.twin_for("db_statistics_freshness") == "re_statistics_freshness"
    assert spike_twins.twin_for("schema_inventory") == ""        # no twin: unchanged either way
    monkeypatch.setenv(spike_twins.FLAG, "0")
    assert not spike_twins.enabled()


def test_declared_lists_hide_the_twins_when_off_and_show_them_under_the_native_id_when_on(install_steps, monkeypatch):
    from resource_explorer import declared_context

    install_steps("re_statistics_freshness", "re_value_profile")
    monkeypatch.delenv(spike_twins.FLAG, raising=False)
    off = declared_context.declarations("database")
    assert "re_value_profile" not in off and "re_statistics_freshness" not in off
    monkeypatch.setenv(spike_twins.FLAG, "1")
    on = declared_context.declarations("database")
    assert "re_value_profile" not in on and "value_profile" in on and "db_statistics_freshness" in on
    assert on["value_profile"].result_kind == "list"             # the twin's declaration, under the native id


def test_the_fact_layer_answers_a_native_id_from_the_twin_only_when_flagged(tmp_path, monkeypatch):
    from resource_explorer.facts import Fact, FactLayer

    layer = FactLayer(_db(tmp_path), resource_type="database")
    asked = []

    def fake(self, slug, analysis_id, level="resource"):
        asked.append(analysis_id)
        return Fact(analysis_id=analysis_id, state="measured")

    monkeypatch.setattr(FactLayer, "_fact", fake)
    monkeypatch.delenv(spike_twins.FLAG, raising=False)
    assert layer.fact("coco", "value_profile").analysis_id == "value_profile"
    assert asked == ["value_profile"]
    asked.clear()
    monkeypatch.setenv(spike_twins.FLAG, "1")
    fact = layer.fact("coco", "value_profile")
    assert asked == ["re_value_profile"] and fact.analysis_id == "value_profile"     # read the twin, named as asked
    asked.clear()
    layer.fact("coco", "schema_inventory")
    assert asked == ["schema_inventory"]


# ── the typed read ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_value_profile_read_is_two_statements_and_in_the_step_allowlist(tmp_path):
    from trellis_analytics.readers.ods import OdsReader

    from resource_explorer.surveyors.survey_step_host import STEP_ODS_METHODS

    assert "value_profile_columns" in STEP_ODS_METHODS
    reg = _db(tmp_path)
    _seed_profile(reg)
    seen = []

    class Counting(OdsReader):
        def __init__(self):
            pass

        def query(self, sql, params=()):
            seen.append(sql)
            return reg_rows(sql, params)

    def reg_rows(sql, params):
        with reg._conn() as conn:
            return [dict(r) for r in conn.execute(sql.replace("?", "?"), params).fetchall()]

    out = Counting().value_profile_columns("coco")
    assert len(seen) == 2 and out["surveyed_at"] == "2026-10-30T10:00:00" and len(out["columns"]) == 3
    seen.clear()
    assert Counting().value_profile_columns("nobody") == {"surveyed_at": None, "ran_as": "", "columns": []}
    assert len(seen) == 1


# ── the steps, run through the host ─────────────────────────────────────────────────────────────────────────────

def test_re_value_profile_runs_through_the_host_and_matches_the_native_reader(install_steps, tmp_path):
    from resource_explorer.surveyors.database.survey_definition_adapter import _value_profile_results
    from resource_explorer.surveyors.survey_step_host import SurveyStepHost, discover_steps

    install_steps("re_value_profile")
    reg = _db(tmp_path)
    _seed_profile(reg)
    out = SurveyStepHost(discover_steps("database")["re_value_profile"], "database")(
        type("E", (), {"slug": "coco"})(), reg)
    assert out["timing"]["run_ms"] >= 0 and "first_load_ms" in out["timing"]
    states = {a["scope"]: a["additionalProperties"]["resultState"] for a in out["step_annotations"]}
    assert states == {"public.orders": "measured", "public.v_orders": "not_established", "coco": "measured"}
    native = _value_profile_results(reg, "coco")
    twin = spike_twins.value_profile_from_twin(reg, "coco")
    for key in ("column_count", "measured_count", "state_counts"):
        assert twin[key] == native[key]
    assert [c["column_path"] for c in twin["columns"]] == [c["column_path"] for c in native["columns"]]
    assert [c["state"] for c in twin["columns"]] == [c["state"] for c in native["columns"]]
    orders = next(c for c in twin["columns"] if c["column_name"] == "note")
    assert (orders["distinct_value_ct"], orders["null_value_ct"], orders["filled_value_ct"]) == (20, 20, 80)


def test_the_value_profile_screen_reads_the_twin_only_when_flagged(install_steps, tmp_path, monkeypatch):
    from resource_explorer import value_profile_screen
    from resource_explorer.surveyors.survey_step_host import SurveyStepHost, discover_steps

    install_steps("re_value_profile")
    reg = _db(tmp_path)
    _seed_profile(reg)
    monkeypatch.delenv(spike_twins.FLAG, raising=False)
    native = value_profile_screen.build_summary(reg, "coco")
    assert value_profile_screen._profile(reg, "coco")["columns"][0].get("min_date", "absent") != "absent"   # native: full row
    SurveyStepHost(discover_steps("database")["re_value_profile"], "database")(type("E", (), {"slug": "coco"})(), reg)
    monkeypatch.setenv(spike_twins.FLAG, "1")
    twin = value_profile_screen.build_summary(reg, "coco")
    assert "min_date" not in value_profile_screen._profile(reg, "coco")["columns"][0]                        # the twin's rows
    assert twin["tables"] == native["tables"] and twin["header"] == native["header"]


def test_re_statistics_freshness_has_the_numbers_of_the_native_analysis(install_steps, tmp_path):
    from resource_explorer.surveyors.database.db_derived import FRESH_CURRENT, FRESH_NEVER, FRESH_STALE
    from resource_explorer.surveyors.survey_step_host import SurveyStepHost, discover_steps

    install_steps("re_statistics_freshness")
    reg = _db(tmp_path)
    ts = "2026-10-26T01:00:00"
    rows = [("public", "never", None, None, 10, 5), ("public", "stale", "2026-09-01T00:00:00", None, 1000, 900),
            ("public", "fine", "2026-10-25T00:00:00", None, 1000, 3)]
    with reg._conn() as conn:
        for sch, tab, la, laa, live, pend in rows:
            conn.execute(
                "INSERT INTO database_table_activity (database_slug, surveyed_at, source, schema_name, table_name, "
                "live_tuples, last_analyze, last_autoanalyze, pending_changes, rows_inserted) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("coco", ts, "local", sch, tab, live, la, laa, pend, 1))
    out = SurveyStepHost(discover_steps("database")["re_statistics_freshness"], "database")(
        type("E", (), {"slug": "coco"})(), reg)
    recs = out["step_annotations"]
    status = {a["scope"]: a["resourceProperties"].get("Statistics Status") for a in recs if a["scope"] != "coco"}
    assert status == {"public.never": "never analyzed", "public.stale": "stale", "public.fine": "current"}
    summary = next(a for a in recs if a["scope"] == "coco")["resourceProperties"]
    assert (summary["Never Analyzed"], summary["Stale"], summary["Current"]) == ("1", "1", "1")
    assert (FRESH_NEVER, FRESH_STALE, FRESH_CURRENT) == ("never_analyzed", "stale", "current")


# ── the timing hooks ────────────────────────────────────────────────────────────────────────────────────────────

def test_the_start_up_line_says_how_long_the_steps_took_to_load(monkeypatch):
    from resource_explorer.engine_host import EngineHostLoop
    from resource_explorer.surveyors import survey_step_host

    monkeypatch.setitem(survey_step_host.LOAD_MS, "database", 12.5)
    assert EngineHostLoop._library_line().count(" · loaded in 12.5 ms") == 1


def test_flag_on_declares_a_twinned_id_once_the_twins_entry_replacing_the_natives(monkeypatch):
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class Entry:
        id: str
        tag: str

    entries = [Entry("value_profile", "native"), Entry("re_value_profile", "twin"), Entry("schema_inventory", "x")]
    monkeypatch.setenv(spike_twins.FLAG, "1")
    on = spike_twins.declared_entries(entries)
    assert [(e.id, e.tag) for e in on] == [("value_profile", "twin"), ("schema_inventory", "x")]
    monkeypatch.delenv(spike_twins.FLAG)
    assert [(e.id, e.tag) for e in spike_twins.declared_entries(entries)] == [("value_profile", "native"),
                                                                              ("schema_inventory", "x")]
