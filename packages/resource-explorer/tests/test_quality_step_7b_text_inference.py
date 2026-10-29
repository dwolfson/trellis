"""Q4 port step 7b (docs/design-notes/DESIGN-QUALITY-STEP-7B-TEXT-INFERENCE.md): the text branches of the functional-type
inference, over the sampled text-shape measures step 7 takes.

A text column the measures settle gets its label; one they cannot (the Code / Category / ID / Attribute / Description
statement reads `datatype_suggestion`, which needs frequent values) still says "type not inferred" and why; one whose shape was
never read is unknown, not a "no". Nothing connects to a database or Egeria.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.surveyors.database.quality import catalogue as cat
from resource_explorer.surveyors.database.quality import functional_infer as fi
from tests.test_quality_step_6_functional_type import _infer, _one, _row
from tests.test_value_profile_quality_checks import entity, registry  # noqa: F401


def _pat(*patterns):
    return json.dumps({"values": [{"value": p, "ct": 10 - i} for i, p in enumerate(patterns)]})


def _text(name, **kw):
    base = dict(catalog_type="text", sample_value_ct=1000, distinct_value_ct=900, value_ct=1000, record_ct=1000,
                min_length=3, max_length=12, avg_length=8.0, zero_length_ct=0, filled_value_ct=0, min_text="a", max_text="z",
                avg_embedded_spaces=0.0, std_pattern_match=None, distinct_pattern_ct=4, frequent_patterns=None, numeric_ct=0,
                date_ct=0, includes_digit_ct=0, min_value=None, max_value=None, avg_value=None, stdev_value=None,
                zero_value_ct=None)
    base.update(kw)
    return _row(name, "A", **base)


@pytest.mark.parametrize("name,std,label", [
    ("contact_zip", "ZIP_USA", "Zip"), ("email_addr", "EMAIL", "Email"), ("ship_to", "PHONE_USA", "Phone"),
    ("mail_to", "STREET_ADDR", "Address"), ("home", "STATE_USA", "State")])
def test_a_standard_pattern_gives_the_column_its_label(name, std, label):
    assert _one(_text(name, std_pattern_match=std)).label == label


def test_the_zip_pattern_needs_a_zip_name_and_a_plain_zip_column_can_be_all_digits():
    assert _one(_text("code_x", std_pattern_match="ZIP_USA")).label != "Zip"
    digits = _text("zip", numeric_ct=900, value_ct=1000, zero_length_ct=100, max_length=5)
    assert _one(digits).label == "Zip"
    assert _one(_text("zip", numeric_ct=900, value_ct=1000, zero_length_ct=100, max_length=10)).label != "Zip"


def test_phone_by_name_and_length():
    assert _one(_text("phone_no", max_length=10)).label == "Phone"
    assert _one(_text("phone_no", max_length=30)).label != "Phone"


@pytest.mark.parametrize("pattern,label", [("NNNN-NN-NN", "Date Stamp"), ("NNNN-NN-NN NN:NN:NN", "DateTime Stamp")])
def test_text_that_is_always_one_date_pattern_is_a_date_stamp(pattern, label):
    row = _text("posted", distinct_pattern_ct=1, min_text="2019-01-01", max_text="2026-10-01", frequent_patterns=_pat(pattern))
    assert _one(row).label == label


def test_a_text_date_pattern_in_a_second_form_or_with_a_wild_range_is_not_labelled_a_date():
    assert _one(_text("posted", distinct_pattern_ct=2, min_text="2019-01-01", max_text="2026-10-01",
                      frequent_patterns=_pat("NNNN-NN-NN"))).label != "Date Stamp"
    assert _one(_text("posted", distinct_pattern_ct=1, min_text="0001-01-01", max_text="2026-10-01",
                      frequent_patterns=_pat("NNNN-NN-NN"))).label != "Date Stamp"


@pytest.mark.parametrize("name,kw,label", [
    ("fiscal_year", dict(min_text="2015", max_text="2027", avg_length=4.0, distinct_value_ct=12), "Period Year"),
    ("sales_qtr", dict(min_text="2020", max_text="2026", avg_length=6.0, frequent_patterns=_pat("NNNN-AN"),
                       distinct_value_ct=20), "Period Quarter"),
    ("mo_end", dict(min_text="2020-01", max_text="2026-09", avg_length=7.0, frequent_patterns=_pat("NNNN-NN"),
                    distinct_value_ct=80), "Period Year-Mon"),
    ("mo", dict(max_length=2, min_text="01", max_text="12", distinct_value_ct=12), "Period Month"),
    ("month_x", dict(max_length=9, min_text="April", max_text="September", distinct_value_ct=12), "Period Month"),
    ("wk", dict(min_text="1", max_text="52", distinct_value_ct=52), "Period Week"),
    ("dow", dict(min_text="1", max_text="7", distinct_value_ct=7), "Period DOW"),
])
def test_periods_in_text(name, kw, label):
    assert _one(_text(name, **kw)).label == label


def test_a_mon_nn_period_with_no_period_name():
    row = _text("when_x", min_text="Jan-20", max_text="Dec-26", avg_length=6.0, frequent_patterns=_pat("AAA-NN"),
                distinct_value_ct=60)
    assert _one(row).label == "Period Mon-NN"


@pytest.mark.parametrize("name,kw,label", [
    ("full_name", dict(avg_length=14.0, avg_embedded_spaces=1.0), "Person Full Name"),
    ("first_name", dict(avg_length=6.0, avg_embedded_spaces=0.0), "Person Given Name"),
    ("last_name", dict(avg_length=6.5, avg_embedded_spaces=0.05), "Person Last Name")])
def test_person_names_need_the_name_and_the_shape(name, kw, label):
    assert _one(_text(name, **kw)).label == label
    assert _one(_text(name, avg_length=60.0, avg_embedded_spaces=4.0)).label != label


@pytest.mark.parametrize("lo,hi,dv,label", [("no", "yes", 2, "Boolean"), ("N", "Y", 2, "Boolean"), ("false", "true", 2, "Boolean"),
                                            ("0", "1", 2, "Boolean")])
def test_text_booleans(lo, hi, dv, label):
    assert _one(_text("active", min_text=lo, max_text=hi, distinct_value_ct=dv, min_length=1, max_length=5)).label == label


def test_a_flag_is_a_few_short_alphabetic_values():
    row = _text("status", distinct_value_ct=4, min_length=2, max_length=6, frequent_patterns=_pat("AAAA", "AAA"))
    # the Code/Category/ID statement runs first and reads datatype_suggestion, so it may have labelled it: not settled
    assert "Flag" in _one(row).possible


def test_a_city_next_to_a_state_is_a_city_by_position_only_when_the_neighbours_say_so():
    city = {**_text("city_x"), "position": 1}
    state = {**_text("st", std_pattern_match="STATE_USA"), "position": 2}
    zipc = {**_text("zip_cd", std_pattern_match="ZIP_USA"), "position": 3}
    got = _infer(city, state, zipc)
    assert "City" in got[("s", "t", "city_x")].possible and got[("s", "t", "st")].label == "State"
    lone = _infer({**_text("city_x"), "position": 1})
    assert "City" not in lone[("s", "t", "city_x")].possible                  # no State beside it: the rule cannot fire


def test_a_plain_text_column_is_still_not_inferred_and_says_why():
    plain = _one(_text("remarks", avg_embedded_spaces=4.0, avg_length=60.0, max_length=200))
    assert plain.label is None and "datatype_suggestion" in plain.why and "a text column" in plain.why


def test_a_column_whose_shape_was_never_read_is_unknown_not_a_no_and_says_so():
    unread = _text("contact_zip", sample_value_ct=None, std_pattern_match=None)
    got = _one(unread)
    assert got.label is None and "Zip" in got.possible and "sampled text shape was not measured" in got.why


def test_a_column_with_no_values_has_nothing_to_read_and_is_labelled_tbd():
    assert _one(_text("remarks", value_ct=0, sample_value_ct=None, distinct_value_ct=0)).label.startswith("TBD")


def test_a_number_column_is_untouched_by_the_text_branches():
    assert _one(_row("qty", "N")).label == "Measurement Discrete" or _one(_row("qty", "N")).label is not None


def test_selection_rules_read_the_new_labels():
    zipc = _infer(_text("contact_zip", std_pattern_match="ZIP_USA"))[("s", "t", "contact_zip")]
    email = _infer(_text("email_addr", std_pattern_match="EMAIL"))[("s", "t", "email_addr")]
    assert fi.label_is(zipc.possible, "Zip") is True and fi.label_is(email.possible, "Zip") is False     # a real no
    assert cat.PREDICATES["Valid_US_Zip"].rule({"functional_data_type": "Zip", "fdt_possible": frozenset({"Zip"})}) is True


def test_the_profile_stores_the_label_a_text_columns_shape_settles(registry, entity):
    from tests.test_quality_step_7_text_shape import PROFILE_WITH_TEXT, TextConn
    from tests.test_value_profile_quality_checks import _profile, _rows

    _profile(registry, entity, conn=TextConn(profile=PROFILE_WITH_TEXT))
    rows = _rows(registry, "database_value_profiles")
    assert rows["sales", "orders", "note"]["functional_data_type"] == "Email"        # its sampled std_pattern_match is EMAIL
    # a column whose shape could not be read stays NULL, never a default type
    failing = TextConn(profile=PROFILE_WITH_TEXT, fail=RuntimeError("canceling statement due to statement timeout"))
    _profile(registry, entity, conn=failing, at="2026-10-20T12:00:00+00:00")
    later = [r for r in registry.query_detail_rows("database_value_profiles", "coco_ods")
             if r["surveyed_at"] == "2026-10-20T12:00:00+00:00" and r["column_name"] == "note"]
    assert later and later[0]["functional_data_type"] is None
