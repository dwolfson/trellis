"""The words on a proposed quality check: a test type's name, its parameters, and why it was not established."""
from __future__ import annotations

from resource_explorer.quality_words import parameter_items, reason_in_words, name_of_test_type
from resource_explorer.surveyors.database.quality.catalogue import load_catalogue

CATALOGUE = load_catalogue()


def test_a_test_type_is_named_by_testgens_own_short_name():
    assert name_of_test_type(CATALOGUE["Alpha_Trunc"]) == CATALOGUE["Alpha_Trunc"].name_short != "Alpha_Trunc"
    assert name_of_test_type(None) == "", "a type the catalogue does not know has no name; the screen shows its identifier"


def test_a_parameter_without_a_value_is_not_listed():
    entry = CATALOGUE["Row_Ct_Pct"]
    items = parameter_items(entry, {"baseline_ct": None, "baseline_value": None, "threshold_value": 0, "severity": "error",
                                    "profile_surveyed_at": "2026-10-30"})
    assert [i["key"] for i in items] == ["threshold_value", "severity"]
    assert all(i["text"] in ("0", "error") for i in items), "zero is a value, not an absence"


def test_the_default_placeholder_list_is_summarised_as_standard_with_its_count():
    entry = CATALOGUE["Required_No_Placeholder"]
    standard = entry.default_parm_values.split("',")[0].lstrip("'")
    [listed] = [i for i in parameter_items(entry, {"baseline_value": standard}) if i["key"] == "baseline_value"]
    assert listed["summary"].startswith("standard ") and f"· {len(listed['list'])} values" in listed["summary"]
    [custom] = parameter_items(entry, {"baseline_value": ",".join(f"v{i}" for i in range(12))})
    assert not custom["summary"].startswith("standard "), "a list that is not the catalogue's is not called standard"


def test_a_reason_names_the_missing_input_in_a_persons_words():
    assert reason_in_words("its selection rule reads frequent_patterns, which the profile did not measure") == (
        "needs the common text patterns, which this profile did not collect")
    said = reason_in_words("type not inferred · needs date_months_present, date_weeks_present, which the profile does not take")
    assert "date_months_present" not in said and "months that hold dates" in said and "selection rule" not in said


def test_an_unnamed_input_says_the_rule_did_not_name_it():
    said = reason_in_words("its selection rule reads an input, which the profile did not measure")
    assert "does not say which" in said and "selection rule" not in said


def test_a_reason_it_does_not_know_comes_back_unchanged():
    assert reason_in_words("something new") == "something new"
    assert reason_in_words("") == ""
