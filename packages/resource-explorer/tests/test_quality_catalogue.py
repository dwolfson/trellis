"""The vendored quality-check catalogue (DESIGN-VALUE-PROFILE-AND-QUALITY-CHECKS.md §3).

Pins every Python port to the vendored text it came from, checks SQL's three-valued logic in the selection
rules, the general_type port, default parameters, parameter validation before SQL substitution, and
`scripts/sync_quality_catalog.py --check`.
"""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from resource_explorer.surveyors.database.quality import catalogue as cat
from resource_explorer.surveyors.database.quality.general_type import (
    GENERAL_TYPE_CASE_SHA256,
    general_type,
    vendored_case_text,
)

PKG = Path(__file__).resolve().parent.parent


# ── provenance and pins ──────────────────────────────────────────────────────────────────────────────────────

def test_the_seven_slice_1_test_types_are_vendored_with_licence_and_provenance():
    assert set(cat.load_catalogue()) == set(cat.SLICE_1_TEST_TYPES)
    assert "Recency" not in cat.SLICE_1_TEST_TYPES  # slice 2: its rule reads functional_data_type
    for name in ("LICENSE", "NOTICE", "PROVENANCE.md"):
        assert (cat.CATALOGUE_DIR / name).is_file(), name
    provenance = (cat.CATALOGUE_DIR / "PROVENANCE.md").read_text()
    assert "3606859c" in provenance and "5.134.0" in provenance
    assert "DataKitchen" in (cat.CATALOGUE_DIR / "NOTICE").read_text()


@pytest.mark.parametrize("name", cat.SLICE_1_TEST_TYPES)
def test_every_predicate_is_pinned_to_the_fragment_it_was_ported_from(name):
    """A changed selection_criteria (an upstream change adopted by the sync script) fails here until the
    predicate is re-ported and its pin updated."""
    test_type = cat.load_catalogue()[name]
    predicate = cat.PREDICATES[name]
    if test_type.selection_criteria is None:
        assert predicate.fragment_sha256 is None, f"{name} gained a selection rule upstream: port it"
    else:
        assert predicate.fragment_sha256 == cat.sha256_text(test_type.selection_criteria), (
            f"{name}'s vendored selection_criteria changed: re-port the predicate, then update its pin")


def test_the_general_type_port_is_pinned_to_the_vendored_case():
    assert cat.sha256_text(vendored_case_text()) == GENERAL_TYPE_CASE_SHA256


def test_every_test_type_has_a_postgres_condition_and_a_known_operator():
    for test_type in cat.load_catalogue().values():
        assert test_type.measure and test_type.test_operator in cat.MUST_BE, test_type.test_type
        assert test_type.test_condition.strip() == "{THRESHOLD_VALUE}", test_type.test_type


def test_row_ct_pct_is_the_one_check_re_proposes_itself():
    origins = {n: t.origin for n, t in cat.load_catalogue().items()}
    assert origins.pop("Row_Ct_Pct") == "re"
    assert set(origins.values()) == {"vendored"}
    assert cat.load_catalogue()["Row_Ct_Pct"].is_table_check


def test_catalogue_ref_names_the_commit_and_fragment_hash_but_not_the_product():
    ref = cat.catalogue_ref(cat.load_catalogue()["Unique"])
    assert "3606859c" in ref and cat.PREDICATES["Unique"].fragment_sha256 in ref
    assert "testgen" not in ref.lower()


# ── three-valued logic ───────────────────────────────────────────────────────────────────────────────────────

def test_sql_and_is_false_before_it_is_null():
    assert cat._and(True, None, False) is False
    assert cat._and(True, None) is None
    assert cat._and(True, True) is True
    assert cat._not(None) is None
    assert cat._cmp(None, ">", 1) is None


def _profile(**kw):
    base = {"general_type": "A", "record_ct": 100, "value_ct": 100, "distinct_value_ct": 100, "null_value_ct": 0,
            "zero_length_ct": 0, "filled_value_ct": 0, "min_date": None, "max_date": None, "future_date_ct": None,
            "sample_ratio": None, "state": "measured"}
    base.update(kw)
    return base


def test_required_skips_a_text_column_that_required_no_placeholder_covers():
    text = _profile()
    assert cat.PREDICATES["Required_No_Placeholder"].evaluate(text) is True
    assert cat.PREDICATES["Required"].evaluate(text) is False
    number = _profile(general_type="N", zero_length_ct=None, filled_value_ct=None)
    assert cat.PREDICATES["Required"].evaluate(number) is True  # the COALESCE makes the text terms FALSE
    assert cat.PREDICATES["Required_No_Placeholder"].evaluate(number) is False


def test_a_null_input_makes_the_rule_null_not_false():
    unmeasured = _profile(record_ct=None, value_ct=None, distinct_value_ct=None)
    assert cat.PREDICATES["Missing_Pct"].evaluate(unmeasured) is None
    assert cat.PREDICATES["Unique"].evaluate(unmeasured) is None
    assert cat.not_established_inputs("Missing_Pct", unmeasured) == ["record_ct", "value_ct"]
    # A text column is never a date check, whatever was measured: the rule is FALSE, not NULL.
    assert cat.PREDICATES["Future_Date"].evaluate(unmeasured) is False


def test_min_date_reads_null_min_date_as_a_value():
    all_null_dates = _profile(general_type="D", min_date=None, distinct_value_ct=0, future_date_ct=0)
    assert cat.PREDICATES["Min_Date"].evaluate(all_null_dates) is False
    assert cat.not_established_inputs("Min_Date", all_null_dates) == []


def test_unique_needs_more_than_500_rows():
    assert cat.PREDICATES["Unique"].evaluate(_profile(record_ct=501, value_ct=501, distinct_value_ct=501)) is True
    assert cat.PREDICATES["Unique"].evaluate(_profile(record_ct=500, value_ct=500, distinct_value_ct=500)) is False


# ── general_type ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("catalog_type,expected", [
    ("character varying", "A"), ("character varying(20)", "A"), ("text", "A"), ("character(3)", "A"),
    ("boolean", "B"), ("bit", "X"), ("bit(1)", "B"),
    ("date", "D"), ("timestamp without time zone", "D"), ("timestamp(3) with time zone", "D"),
    ("time with time zone", "T"), ("time without time zone", "T"),  # upstream's ILIKE 'time with%'
    ("integer", "N"), ("numeric(10,2)", "N"), ("double precision", "N"), ("money", "N"),
    ("uuid", "X"), ("jsonb", "X"), ("ARRAY", "X"), ("character varying[]", "X"), ("USER-DEFINED", "X"), ("", "X"),
])
def test_general_type_follows_the_vendored_case(catalog_type, expected):
    assert general_type(catalog_type) == expected


# ── default parameters ───────────────────────────────────────────────────────────────────────────────────────

def test_default_params_read_the_profile_and_the_catalogue():
    catalogue = cat.load_catalogue()
    missing = cat.default_params(catalogue["Missing_Pct"], _profile(value_ct=90), 10)
    assert (missing["baseline_ct"], missing["baseline_value_ct"], missing["threshold_value"]) == (100, 90, 2)
    assert missing["severity"] == "warning"
    min_date = cat.default_params(catalogue["Min_Date"], _profile(general_type="D", min_date="2020-01-01"), 10)
    assert (min_date["baseline_value"], min_date["threshold_value"], min_date["severity"]) == ("2020-01-01", 0, "error")
    row_ct = cat.default_params(catalogue["Row_Ct_Pct"], _profile(), 12.5)
    assert (row_ct["baseline_ct"], row_ct["threshold_value"]) == (100, 12.5)


def test_the_default_placeholder_list_parses_like_upstream():
    params = cat.default_params(cat.load_catalogue()["Required_No_Placeholder"], _profile(), 10)
    items = cat.parse_value_list(params["baseline_value"])
    assert items[0] == "" and "n/a" in items and "(null)" in items and "UNKNOWN" in items
    assert params["threshold_value"] == 0


def test_a_default_that_reads_a_null_measure_is_refused():
    with pytest.raises(cat.ParameterError):
        cat.default_params(cat.load_catalogue()["Missing_Pct"], _profile(value_ct=None), 10)


# ── rendering: validated by type before substitution ────────────────────────────────────────────────────────

RUN_DATE = "2026-10-20 12:00:00"


def test_each_measure_renders_from_validated_values():
    catalogue = cat.load_catalogue()
    sql = cat.render_measure(catalogue["Required"], 'we"ird', {"threshold_value": 0}, RUN_DATE)
    assert sql == 'COUNT(*) - COUNT("we""ird")'
    future = cat.render_measure(catalogue["Future_Date"], "d", {"threshold_value": 0}, RUN_DATE)
    assert f"'{RUN_DATE}'::DATE" in future
    missing = cat.render_measure(catalogue["Missing_Pct"], "c", {"baseline_ct": 10, "baseline_value_ct": 9,
                                                                 "threshold_value": 2}, RUN_DATE)
    assert "9::FLOAT / 10::FLOAT" in missing
    row_ct = cat.render_measure(catalogue["Row_Ct_Pct"], "", {"baseline_ct": 250, "threshold_value": 10}, RUN_DATE)
    assert "COUNT(*) - 250" in row_ct


def test_the_placeholder_list_is_escaped_item_by_item():
    sql = cat.render_measure(cat.load_catalogue()["Required_No_Placeholder"], "c",
                             {"baseline_value": "\"\",n/a,\"it's\",back\\slash", "threshold_value": 0}, RUN_DATE)
    assert "E''" in sql and "E'n/a'" in sql and "E'it''s'" in sql and "E'back\\\\slash'" in sql


def test_an_empty_placeholder_list_renders_null_like_upstream():
    sql = cat.render_measure(cat.load_catalogue()["Required_No_Placeholder"], "c",
                             {"baseline_value": "", "threshold_value": 0}, RUN_DATE)
    assert "IN (NULL)" in sql


@pytest.mark.parametrize("name,params,quoted", [
    ("Missing_Pct", {"baseline_ct": "10; DROP TABLE x", "baseline_value_ct": 9, "threshold_value": 2},
     "'10; DROP TABLE x'"),
    ("Min_Date", {"baseline_value": "2020-01-01'; DROP TABLE x; --", "threshold_value": 0}, "2020-01-01'"),
    ("Min_Date", {"baseline_value": "2020-13-45", "threshold_value": 0}, "2020-13-45"),
    ("Row_Ct_Pct", {"baseline_ct": True, "threshold_value": 10}, "True"),
    ("Required_No_Placeholder", {"baseline_value": ["ok", 3], "threshold_value": 0}, "3"),
])
def test_a_value_that_does_not_validate_is_refused_quoting_it(name, params, quoted):
    with pytest.raises(cat.ParameterError) as info:
        cat.render_measure(cat.load_catalogue()[name], "c", params, RUN_DATE)
    assert quoted in str(info.value)


def test_a_bad_threshold_is_refused():
    with pytest.raises(cat.ParameterError, match="'abc'"):
        cat.threshold(cat.load_catalogue()["Unique"], {"threshold_value": "abc"})
    with pytest.raises(cat.ParameterError):
        cat.threshold(cat.load_catalogue()["Unique"], {"threshold_value": float("nan")})


def test_an_unknown_placeholder_in_the_vendored_sql_is_refused(monkeypatch):
    import dataclasses

    changed = dataclasses.replace(cat.load_catalogue()["Unique"], measure="COUNT({SUBSET_CONDITION})")
    with pytest.raises(cat.ParameterError, match="SUBSET_CONDITION"):
        cat.render_measure(changed, "c", {"threshold_value": 0}, RUN_DATE)


def test_the_fail_when_operator_and_its_must_be_inverse():
    unique = cat.load_catalogue()["Unique"]
    assert cat.fails(unique, 1, 0) and not cat.fails(unique, 0, 0)
    assert cat.MUST_BE[unique.test_operator] == "mustBeLessOrEqualTo"
    assert cat.MUST_BE[cat.load_catalogue()["Missing_Pct"].test_operator] == "mustBeLessThan"


def test_check_key_shape():
    assert cat.check_key("sales", "orders", "order_id", "Unique") == "sales.orders.order_id::Unique"
    assert cat.check_key("sales", "orders", "", "Row_Ct_Pct") == "sales.orders::Row_Ct_Pct"


# ── scripts/sync_quality_catalog.py --check ──────────────────────────────────────────────────────────────────

def _sync_module():
    spec = importlib.util.spec_from_file_location("sync_quality_catalog", PKG / "scripts" / "sync_quality_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_upstream(root: Path) -> Path:
    """An upstream-shaped tree built from the vendored files themselves, plus one test type we do not vendor."""
    types = root / "testgen/template/dbsetup_test_types"
    types.mkdir(parents=True)
    for name in cat.SLICE_1_TEST_TYPES:
        shutil.copy(cat.TEST_TYPES_DIR / f"{name}.yaml", types / f"test_types_{name}.yaml")
    shutil.copy(cat.TEST_TYPES_DIR / "Unique.yaml", types / "test_types_Recency.yaml")
    flavor = root / "testgen/template/flavors/postgresql"
    (flavor / "profiling").mkdir(parents=True)
    (flavor / "data_chars").mkdir(parents=True)
    shutil.copy(cat.POSTGRES_DIR / "profile_measures.sql", flavor / "profiling/project_profiling_query.sql")
    shutil.copy(cat.POSTGRES_DIR / "general_type.sql", flavor / "data_chars/get_schema_ddf.sql")
    return root


def test_sync_check_reports_in_step_and_lists_new_test_types(tmp_path, capsys):
    upstream = _fake_upstream(tmp_path / "up")
    before = sorted(p.read_bytes() for p in cat.CATALOGUE_DIR.rglob("*") if p.is_file())
    assert _sync_module().main(["--check", "--upstream", str(upstream)]) == 0
    out = capsys.readouterr().out
    assert "in step with upstream" in out and "Recency" in out
    assert sorted(p.read_bytes() for p in cat.CATALOGUE_DIR.rglob("*") if p.is_file()) == before  # writes nothing


def test_sync_check_fails_on_a_changed_selection_rule_or_measure(tmp_path, capsys):
    upstream = _fake_upstream(tmp_path / "up")
    path = upstream / "testgen/template/dbsetup_test_types/test_types_Unique.yaml"
    path.write_text(path.read_text().replace("record_ct > 500", "record_ct > 400"))
    sql = upstream / "testgen/template/flavors/postgresql/profiling/project_profiling_query.sql"
    sql.write_text(sql.read_text().replace("MAX(\"{COL_NAME}\") AS max_date", "MAX(x) AS max_date"))
    assert _sync_module().main(["--check", "--upstream", str(upstream)]) == 1
    out = capsys.readouterr().out
    assert "Unique.selection_criteria" in out and "max_date" in out


def test_sync_check_refuses_a_directory_that_is_not_a_checkout(tmp_path):
    assert _sync_module().main(["--check", "--upstream", str(tmp_path)]) == 2
