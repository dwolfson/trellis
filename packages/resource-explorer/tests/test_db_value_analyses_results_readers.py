"""D1 (DB-RESULTS-READERS): results readers for `data_class_match`,
`reference_data_match` and `nested_column_profile`.

Those three were built and ran, but their verdicts only ever became Egeria
annotations, so a database's Survey & analyses / By analysis panes had nothing
local to read. Each now has a detail table, a reader in
`DATABASE_ANALYSIS_RESULTS_MAP` and a headline.

Never touches the shared registry: every registry here is a tmp SQLite file;
the Postgres migration SQL is checked against a fake cursor (no network), the
same way `tests/test_curate_authors.py` checks its migration.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from resource_explorer.activity_logger import log_survey
from resource_explorer.facts import (
    MEASURED, NEVER_RUN, NOT_ESTABLISHED, NOTHING_FOUND, FactLayer,
)
from resource_explorer.registry import (
    DatabaseEntity, ProjectRegistry, ProjectStatus,
    SECTION_DATA_CLASS_MATCHES, SECTION_NESTED_COLUMNS, SECTION_REFERENCE_DATA_MATCHES,
)
from resource_explorer.surveyors.database import column_matching as cm
from resource_explorer.surveyors.database.column_match_store import (
    store_column_match_results,
)
from resource_explorer.surveyors.database.sampling import SampleProvenance
from resource_explorer.surveyors.database.survey_definition_adapter import (
    DATABASE_ANALYSIS_HEADLINE_MAP, DATABASE_ANALYSIS_RESULTS_MAP,
)

THREE = ("data_class_match", "reference_data_match", "nested_column_profile")
SLUG = "d1_db"
T1 = "2026-10-02T10:00:00"
T2 = "2026-10-02T11:00:00"


@pytest.fixture
def reg(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "d1.db"))
    r.register_database(DatabaseEntity(
        slug=SLUG, display_name=SLUG, db_type="postgresql", host="localhost",
        port=5432, database_name=SLUG, status=ProjectStatus.ACTIVE,
    ))
    return r


def _prov(rows=1000, total=50_000):
    return SampleProvenance(strategy="random", sample_rows=rows, total_rows=total, seed=7)


def _dc(col, verdict, *, table="people", reason="", **kw):
    return cm.ColumnMatch(
        schema_name="public", table_name=table, column_name=col,
        question="data_class_match", verdict=verdict, provenance=_prov(),
        not_established_reason=reason, **kw,
    ).as_dict()


def _rd(col, verdict, *, table="people", reason="", **kw):
    return cm.ColumnMatch(
        schema_name="public", table_name=table, column_name=col,
        question="reference_data_match", verdict=verdict, provenance=_prov(),
        not_established_reason=reason, **kw,
    ).as_dict()


def _results(matches=None, nested=None, **extra):
    """`DatabaseSurveyor.survey()`'s dict, for the keys the store reads."""
    return {
        "column_profile": {"matches": matches} if matches is not None else {},
        "nested_columns": nested if nested is not None else {},
        **extra,
    }


def _nested(*cols, supported=True):
    return {"columns": list(cols), "value_sampling_supported": supported}


def _ncol(col, label, state="measured", schema=None, reason=""):
    return {
        "column": f"public.docs.{col}", "family": "json", "state": state, "label": label,
        "schema": schema, "schema_name": "public", "table_name": "docs", "column_name": col,
        "sample": _prov().as_dict(), "not_established_reason": reason,
    }


STRUCT = {"sample_size": 100, "max_depth": 2, "keys": [{"path": "a"}, {"path": "b"}]}


def _log_run(reg, ts, step):
    log_survey(reg, "database", SLUG, SLUG, "", "discovery", "ok", "surveyed", json.dumps({
        "source": "survey-definition", "entity_type": "database", "slug": SLUG,
        "surveyed_at": ts,
        "steps": [{"step": f"GovActionProcessStep::X::{step}",
                   "re_analysis_step": step, "status": "ok"}],
    }))


def _fact(reg, analysis_id):
    return FactLayer(reg, resource_type="database").fact(SLUG, analysis_id)


def _read(reg, analysis_id):
    reader, _ = DATABASE_ANALYSIS_RESULTS_MAP[analysis_id]
    return reader(reg, SLUG)


def _headline(reg, analysis_id):
    return (DATABASE_ANALYSIS_HEADLINE_MAP[analysis_id](reg, SLUG) or {}).get("label", "")


# ── the map ──────────────────────────────────────────────────────────────────

def test_the_three_are_in_the_results_and_headline_maps():
    for analysis_id in THREE:
        reader, trend = DATABASE_ANALYSIS_RESULTS_MAP[analysis_id]
        assert callable(reader) and trend is None
        assert callable(DATABASE_ANALYSIS_HEADLINE_MAP[analysis_id])


# ── each reader returns the stored result for a survey run ───────────────────

def test_data_class_match_reads_what_a_run_stored(reg):
    store_column_match_results(reg, SLUG, T1, _results(matches=[
        _dc("email", cm.MATCH_MATCHED, matched_display_name="Email Address",
            confidence=96, evidence="value_pattern", sampled_conformance=0.97,
            privacy_relevant=True),
        _dc("notes", cm.MATCH_NO_MATCH),
        _dc("blob", cm.MATCH_NOT_APPLICABLE, reason="binary"),
        _rd("status", cm.MATCH_MATCHED),     # the other question: must not leak in
    ]))
    value = _read(reg, "data_class_match")
    assert value["column_count"] == 3
    assert (value["matched_count"], value["no_match_count"], value["not_applicable_count"]) == (1, 1, 1)
    assert value["privacy_relevant_count"] == 1
    email = next(c for c in value["columns"] if c["column_name"] == "email")
    assert email["matched_display_name"] == "Email Address"
    assert email["sampled_conformance"] == 0.97 and email["sample_rows"] == 1000
    assert "1 of 2 columns tested matched a known Data Class" in _headline(reg, "data_class_match")


def test_reference_data_match_reads_what_a_run_stored(reg):
    store_column_match_results(reg, SLUG, T1, _results(matches=[
        _rd("country", cm.MATCH_MATCHED, matched_display_name="ISO countries", value_coverage=1.0),
        _rd("tier", cm.MATCH_PARTIAL, matched_display_name="Tiers", value_coverage=0.8,
            unmatched_values=["x", "y"]),
        _rd("code", cm.MATCH_UNMATCHED_PATTERNED, proposed_values=["a", "b"]),
        _rd("id", cm.MATCH_NOT_APPLICABLE, reason="not low-cardinality"),
        _dc("email", cm.MATCH_MATCHED),
    ]))
    value = _read(reg, "reference_data_match")
    assert value["column_count"] == 4
    assert value["matched_count"] == 1 and value["partial_count"] == 1
    assert value["proposed_count"] == 1 and value["not_applicable_count"] == 1
    tier = next(c for c in value["columns"] if c["column_name"] == "tier")
    assert tier["unmatched_values_json"] == ["x", "y"]
    assert tier["value_coverage"] == 0.8
    assert _headline(reg, "reference_data_match").startswith(
        "1 of 3 low-cardinality columns tested matched a known Valid Value Set")


def test_nested_column_profile_reads_what_a_run_stored(reg):
    store_column_match_results(reg, SLUG, T1, _results(nested=_nested(
        _ncol("payload", "structured", schema=STRUCT),
        _ncol("flag", "scalar_only", schema={"keys": []}),
        _ncol("junk", "mixed", schema={"keys": [{"path": "k"}]}),
    )))
    value = _read(reg, "nested_column_profile")
    assert value["column_count"] == 3
    assert (value["structured_count"], value["scalar_only_count"], value["mixed_count"]) == (1, 1, 1)
    payload = next(c for c in value["columns"] if c["column_name"] == "payload")
    assert payload["key_count"] == 2 and payload["max_depth"] == 2
    assert payload["schema_json"]["keys"][0]["path"] == "a"
    assert "3 JSON, JSONB or XML columns" in _headline(reg, "nested_column_profile")


# ── two runs are two sets of rows; a re-run of the same run is idempotent ────

def _count(reg, table):
    with reg._conn() as conn:
        return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def test_two_runs_keep_both_and_a_rerun_of_one_run_does_not_duplicate(reg):
    first = _results(matches=[_dc("a", cm.MATCH_NO_MATCH), _dc("b", cm.MATCH_NO_MATCH)])
    second = _results(matches=[_dc("a", cm.MATCH_MATCHED)])
    store_column_match_results(reg, SLUG, T1, first)
    store_column_match_results(reg, SLUG, T2, second)
    assert _count(reg, "database_data_class_matches") == 3          # 2 + 1, no overwrite
    # The reader reads the NEWEST run...
    assert _read(reg, "data_class_match")["column_count"] == 1
    # ...and the older run is still there.
    assert len(reg.query_detail_rows("database_data_class_matches", SLUG, surveyed_at=T1)) == 2

    store_column_match_results(reg, SLUG, T1, first)                # same run again
    store_column_match_results(reg, SLUG, T2, second)
    assert _count(reg, "database_data_class_matches") == 3
    with reg._conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM database_survey_coverage WHERE section = ?",
            (SECTION_DATA_CLASS_MATCHES,)).fetchone()["n"]
    assert n == 2                                                   # one per run


# ── never run reads "not run", not zero ──────────────────────────────────────

@pytest.mark.parametrize("analysis_id", THREE)
def test_an_analysis_never_run_is_not_run_and_not_a_zero(reg, analysis_id):
    from resource_explorer.workflows.scouting import question_has_data, results_have_data

    assert results_have_data(_read(reg, analysis_id)) is False
    assert _headline(reg, analysis_id) == ""
    fact = _fact(reg, analysis_id)
    assert fact.state == NEVER_RUN and not fact.value
    assert question_has_data(reg, SLUG, [analysis_id], entity_type="database") is False


@pytest.mark.parametrize("analysis_id,step", [
    ("data_class_match", "postgres_column_profile"),
    ("reference_data_match", "postgres_column_profile"),
    ("nested_column_profile", "postgres_nested_columns"),
])
def test_a_run_from_before_results_were_stored_is_not_established_never_a_zero(
        reg, analysis_id, step):
    """coco_pharma's real case: the step ran, nothing was stored. The old
    behaviour for a reader answering {} is `NOTHING_FOUND`, a measured zero."""
    _log_run(reg, T1, step)
    fact = _fact(reg, analysis_id)
    assert fact.state == NOT_ESTABLISHED
    assert fact.state != NOTHING_FOUND


# ── found nothing is a real zero ─────────────────────────────────────────────

def test_a_run_that_found_nothing_reads_a_real_zero(reg):
    store_column_match_results(reg, SLUG, T1, _results(matches=[
        _dc("a", cm.MATCH_NO_MATCH), _dc("b", cm.MATCH_NO_MATCH),
        _rd("a", cm.MATCH_NO_MATCH), _rd("b", cm.MATCH_NOT_APPLICABLE, reason="high cardinality"),
    ]))
    value = _read(reg, "data_class_match")
    assert value["matched_count"] == 0 and value["no_match_count"] == 2
    assert "0 of 2 columns tested matched a known Data Class" in _headline(reg, "data_class_match")
    assert _fact(reg, "data_class_match").state == NOTHING_FOUND
    assert _fact(reg, "reference_data_match").state == NOTHING_FOUND


def test_nested_with_no_json_columns_is_a_real_zero_not_never_run(reg):
    store_column_match_results(reg, SLUG, T1, _results(nested=_nested()))
    value = _read(reg, "nested_column_profile")
    assert value["column_count"] == 0 and "no JSON, JSONB or XML columns" in value["explanation"]
    assert _fact(reg, "nested_column_profile").state == NOTHING_FOUND
    assert _headline(reg, "nested_column_profile").startswith("0 JSON, JSONB or XML columns")


def test_zero_matched_while_some_columns_could_not_be_tested_is_not_a_clean_zero(reg):
    store_column_match_results(reg, SLUG, T1, _results(matches=[
        _dc("a", cm.MATCH_NO_MATCH),
        _dc("b", cm.MATCH_NOT_SAMPLED, reason="the sampler could not reach it"),
    ]))
    fact = _fact(reg, "data_class_match")
    assert fact.state != NOTHING_FOUND
    assert "1 could not be tested" in _headline(reg, "data_class_match")


# ── a run that could not measure says so ─────────────────────────────────────

def test_a_run_that_established_nothing_is_not_established_not_zero_matched(reg):
    store_column_match_results(reg, SLUG, T1, _results(matches=[
        _dc("a", cm.MATCH_NO_CANDIDATES, reason="the Egeria platform's Data Classes could not be read"),
        _dc("b", cm.MATCH_NO_CANDIDATES, reason="the Egeria platform's Data Classes could not be read"),
    ]))
    value = _read(reg, "data_class_match")
    assert value["state"] == "not_established"
    assert "could not be read" in value["explanation"]
    # Nothing was established, so no count of matches may exist to be read as zero.
    for absent in ("matched_count", "no_match_count", "proposed_count"):
        assert absent not in value, absent
    assert value["not_established_count"] == 2
    label = _headline(reg, "data_class_match")
    assert label.startswith("Not established") and "0 of" not in label
    assert _fact(reg, "data_class_match").state == NOT_ESTABLISHED


def test_a_failed_step_is_recorded_as_could_not_measure(reg):
    store_column_match_results(reg, SLUG, T1, _results(
        column_profile_failed="permission denied for table people",
        nested_columns_failed="connection reset"))
    for analysis_id, text in (("data_class_match", "permission denied"),
                              ("reference_data_match", "permission denied"),
                              ("nested_column_profile", "connection reset")):
        value = _read(reg, analysis_id)
        assert value["state"] == "not_established" and text in value["explanation"], analysis_id
        assert _headline(reg, analysis_id).startswith("Not established")


def test_nested_without_value_sampling_says_so(reg):
    store_column_match_results(reg, SLUG, T1, _results(nested=_nested(
        _ncol("payload", "empty", state="not_supported",
              reason="this connection's engine declares no value_sampling capability"),
        supported=False)))
    value = _read(reg, "nested_column_profile")
    assert value["state"] == "not_established"
    assert "value_sampling" in value["explanation"]
    assert "structured_count" not in value and "scalar_only_count" not in value


def test_a_credential_scope_limited_run_says_so(reg):
    reg.record_database_survey(
        slug=SLUG, schema_count=8, table_count=3, column_count=9,
        survey_data={"schema_info": {"schemas": [{"name": "public"}]},
                     "credential_capability": {
                         "connected_as": "analyst_ro", "schema_total": 8, "schema_visible": 2,
                         "relation_total": 26, "relation_select": 3}},
        surveyed_at=T1)
    store_column_match_results(reg, SLUG, T1, _results(matches=[
        _dc("a", cm.MATCH_NO_MATCH), _dc("b", cm.MATCH_NO_MATCH)]))
    value = _read(reg, "data_class_match")
    assert value["_status"]["state"] == "measured_within_credential_scope"
    assert "3 of 26" in value["_status"]["fraction"]
    # A bare zero over 3 of 26 relations must not be reported as the database's zero.
    assert _fact(reg, "data_class_match").state == "measured_within_credential_scope"


# ── the surveyor writes the tables when the step runs ────────────────────────

def test_the_surveyor_step_writes_the_new_tables(reg):
    from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor

    entity = reg.get_database(SLUG)
    surveyor = DatabaseSurveyor(entity, {"user": "u", "password": "p"}, reg)
    results = {
        "surveyed_at": T1, "annotations": [], "errors": [],
        "schema_info": {"schemas": [], "total_tables": 0, "total_columns": 0},
        "statistics": {},
        **_results(
            matches=[_dc("email", cm.MATCH_MATCHED), _rd("tier", cm.MATCH_NO_MATCH)],
            nested=_nested(_ncol("payload", "structured", schema=STRUCT))),
    }
    surveyor._store_results(results)
    assert _count(reg, "database_data_class_matches") == 1
    assert _count(reg, "database_reference_data_matches") == 1
    assert _count(reg, "database_nested_columns") == 1
    cov = reg.get_section_coverage("database", SLUG, surveyed_at=T1)
    assert cov[SECTION_DATA_CLASS_MATCHES]["state"] == "measured"
    assert cov[SECTION_REFERENCE_DATA_MATCHES]["row_count"] == 1
    assert cov[SECTION_NESTED_COLUMNS]["row_count"] == 1
    # Re-materialising the same run does not duplicate.
    surveyor._store_results(results)
    assert _count(reg, "database_data_class_matches") == 1


def test_a_survey_that_never_asked_for_the_steps_writes_no_coverage(reg):
    """The two `{}` defaults survey() seeds mean "did not run", not "ran empty"."""
    from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor

    surveyor = DatabaseSurveyor(reg.get_database(SLUG), {"user": "u", "password": "p"}, reg)
    surveyor._store_results({
        "surveyed_at": T1, "annotations": [], "errors": [],
        "schema_info": {"schemas": [], "total_tables": 0, "total_columns": 0},
        "statistics": {}, "column_profile": {}, "nested_columns": {},
    })
    assert reg.get_latest_section_coverage("database", SLUG, SECTION_DATA_CLASS_MATCHES) is None
    assert reg.get_latest_section_coverage("database", SLUG, SECTION_NESTED_COLUMNS) is None
    assert _read(reg, "data_class_match")["_status"]["state"] == "not_established"


# ── Survey & analyses / By analysis ──────────────────────────────────────────

@pytest.mark.parametrize("analysis_id", THREE)
def test_the_by_analysis_response_carries_a_real_summary(reg, analysis_id):
    from resource_explorer.workflows.analysis import build_survey_results

    store_column_match_results(reg, SLUG, T1, _results(
        matches=[_dc("email", cm.MATCH_MATCHED), _rd("tier", cm.MATCH_NO_MATCH)],
        nested=_nested(_ncol("payload", "structured", schema=STRUCT))))
    got = build_survey_results(reg, "database", SLUG, board_id=analysis_id)
    (board,) = got["dashboards"]
    assert board["id"] == analysis_id and board["has_results"] is True
    label = board["analyses"][0]["headline"]["label"]
    # The /next card prints "ran; no summary reader yet." only for a board that
    # has results and NO headline; a headline here means that branch is not taken.
    assert label and "no summary reader" not in label


def test_the_by_analysis_board_for_a_database_never_run_is_empty_not_a_zero(reg):
    from resource_explorer.workflows.analysis import build_survey_results

    got = build_survey_results(reg, "database", SLUG, include_empty=True)
    boards = {d["id"]: d for d in got["dashboards"]}
    for analysis_id in THREE:
        assert boards[analysis_id]["has_results"] is False
        assert not boards[analysis_id]["analyses"][0]["headline"]


def test_the_question_answer_reads_the_stored_result(reg):
    store_column_match_results(reg, SLUG, T1, _results(matches=[
        _dc("email", cm.MATCH_MATCHED), _dc("notes", cm.MATCH_NO_MATCH)]))
    fact = _fact(reg, "data_class_match")
    assert fact.state == MEASURED and fact.value["matched_count"] == 1
    assert fact.headline.startswith("1 of 2 columns tested matched")
    assert "no summary reader" not in (fact.note or "")
    from resource_explorer.workflows.scouting import question_has_data
    assert question_has_data(reg, SLUG, ["data_class_match"], entity_type="database") is True


# ── migration: additive, idempotent, both dialects ───────────────────────────

NEW_TABLES = ("database_data_class_matches", "database_reference_data_matches",
              "database_nested_columns")


def test_sqlite_migration_is_additive_and_idempotent(tmp_path):
    path = str(tmp_path / "m.db")
    ProjectRegistry(db_path=path)
    con = sqlite3.connect(path)
    for t in NEW_TABLES:                      # an older registry that lacks them
        con.execute(f"DROP TABLE {t}")
    con.commit()
    con.close()
    ProjectRegistry(db_path=path)             # first start creates them
    ProjectRegistry(db_path=path)             # second start is a no-op
    con = sqlite3.connect(path)
    for t in NEW_TABLES:
        cols = {r[1]: r for r in con.execute(f"PRAGMA table_info({t})")}
        assert {"database_slug", "surveyed_at", "source", "state", "verdict" if "matches" in t else "label"} <= set(cols)
        # no NOT NULL column without a default beyond the key/verdict/state set
        for name, r in cols.items():
            if r[3] and name not in ("database_slug", "surveyed_at", "schema_name", "table_name",
                                     "column_name", "verdict", "label"):
                assert r[4] is not None, f"{t}.{name} is NOT NULL with no default"
    con.close()


def test_postgres_migration_sql_without_a_connection():
    """Dialect check against a fake cursor: every new statement is a
    `CREATE TABLE/INDEX IF NOT EXISTS` and the SQLite spelling of the key is
    rewritten to `SERIAL PRIMARY KEY`. Nothing is run against a server."""
    import resource_explorer.registry as r

    seen: list[str] = []

    class _Raw:
        def execute(self, sql, params=None): seen.append(" ".join(sql.split()))

    wrapper = r.PostgresCursorWrapper(_Raw())
    new_ddl = [d for d in r._DB_FS_DETAIL_TABLE_DDL if any(t in d for t in NEW_TABLES)]
    assert len(new_ddl) == 3
    for ddl in new_ddl:
        wrapper.execute(ddl)
    new_idx = [i for i in r._DB_FS_DETAIL_TABLE_INDEXES if any(t in i for t in NEW_TABLES)]
    assert len(new_idx) == 3
    for idx in new_idx:
        wrapper.execute(idx)
    assert len(seen) == 6
    for sql in seen:
        assert sql.startswith(("CREATE TABLE IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS")), sql
        assert "AUTOINCREMENT" not in sql and "?" not in sql
        for word in ("DROP", "ALTER", "DELETE", "TRUNCATE"):
            assert word not in sql.upper().split()
    assert all("id SERIAL PRIMARY KEY" in s for s in seen[:3])
    # The tables carry no column migration (they are created whole).
    for t in NEW_TABLES:
        assert (t, ()) in r._DB_FS_DETAIL_TABLE_MIGRATIONS


def test_the_new_tables_are_driven_by_the_generic_detail_machinery():
    import resource_explorer.registry as r

    for t in NEW_TABLES:
        spec = r._DETAIL_TABLE_SPECS[t]
        assert spec.slug_column == "database_slug" and spec.resource_type == "database"
        assert "state" in spec.value_columns
    assert r._DETAIL_TABLE_SPECS["database_nested_columns"].json_columns == {"schema_json"}
