"""A Survey Definition reference without `::` resolves, and a lookup that raised is not reported as "not found".

Found live 2026-10-30: the Q3 batch carries the bare name `DatabaseQualitySurvey`; Egeria's by-name and find calls answer
"No elements found" for it and resolve `GovActionProcess::DatabaseQualitySurvey`. The reader only tried the string it
was given, so a batch run failed at once with "No Survey Definition found matching".
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors import survey_definition_reader as sdr
from resource_explorer.surveyors.survey_definition_executor import SurveyDefinitionExecutor, SurveyDefinitionExecutorError

QN = "GovActionProcess::DatabaseQualitySurvey"
GUID = "616c51d4-0000-0000-0000-000000000000"


def _element(guid=GUID, qualified=QN, display="Database Quality Survey", type_name="GovernanceActionProcess"):
    return {"elementHeader": {"guid": guid, "type": {"typeName": type_name}},
            "properties": {"qualifiedName": qualified, "displayName": display}}


class _OnlyKnowsTheQualifiedName:
    """Egeria as probed: both calls answer only for the qualified name (or, for the display name, only the by-name call)."""

    def __init__(self, by_name_raises=False, find_raises=False, display_too=False):
        self.by_name_raises, self.find_raises, self.display_too = by_name_raises, find_raises, display_too
        self.calls: list[tuple[str, str]] = []

    def get_governance_definitions_by_name(self, name, output_format="JSON"):
        self.calls.append(("by_name", name))
        if self.by_name_raises:
            raise RuntimeError("view server unreachable")
        if name == QN or (self.display_too and name == "Database Quality Survey"):
            return [_element()]
        return "No elements found"

    def find_governance_definitions(self, search_string, starts_with=True, output_format="JSON"):
        self.calls.append(("find", search_string))
        if self.find_raises:
            raise RuntimeError("find failed")
        return [_element()] if search_string == QN else "No elements found"


def _reader(officer):
    reader = sdr.SurveyDefinitionReader.__new__(sdr.SurveyDefinitionReader)
    reader._governance_officer = officer
    reader.connect = lambda: None
    return reader


def test_the_bare_name_resolves_through_the_qualified_name():
    officer = _OnlyKnowsTheQualifiedName()
    assert _reader(officer).find_process_guid_by_name("DatabaseQualitySurvey") == GUID
    assert ("by_name", QN) in officer.calls


def test_the_qualified_name_still_resolves_directly_and_is_tried_alone():
    officer = _OnlyKnowsTheQualifiedName()
    assert _reader(officer).find_process_guid_by_name(QN) == GUID
    assert {name for _, name in officer.calls} == {QN}


def test_an_unknown_name_is_none_with_no_errors():
    reader = _reader(_OnlyKnowsTheQualifiedName())
    found = reader.lookup_process("NoSuchSurvey")
    assert found.guid is None and found.errors == []
    assert found.tried == ["NoSuchSurvey", "GovActionProcess::NoSuchSurvey", "No Such Survey"]


def test_the_display_name_is_the_last_resort():
    officer = _OnlyKnowsTheQualifiedName(display_too=True)
    officer.get_governance_definitions_by_name = lambda name, output_format="JSON": (
        [_element()] if name == "Database Quality Survey" else "No elements found")
    assert _reader(officer).find_process_guid_by_name("DatabaseQualitySurvey") == GUID


def test_a_lookup_that_raised_is_reported_apart_from_not_found():
    reader = _reader(_OnlyKnowsTheQualifiedName(by_name_raises=True, find_raises=True))
    assert reader.find_process_guid_by_name("DatabaseQualitySurvey") is None
    assert reader.last_lookup_errors and "view server unreachable" in reader.last_lookup_errors[0]
    found = reader.lookup_process("DatabaseQualitySurvey")
    assert found.guid is None and len(found.errors) == 2 * len(found.tried)


def test_a_failure_on_one_call_does_not_hide_a_hit_on_the_other():
    reader = _reader(_OnlyKnowsTheQualifiedName(by_name_raises=True))
    assert reader.find_process_guid_by_name("DatabaseQualitySurvey") == GUID


def test_a_non_process_hit_is_not_taken_for_the_definition():
    officer = _OnlyKnowsTheQualifiedName()
    officer.get_governance_definitions_by_name = lambda name, output_format="JSON": [_element(type_name="GovernanceRule")]
    officer.find_governance_definitions = lambda **k: [_element(type_name="GovernanceRule")]
    assert _reader(officer).find_process_guid_by_name("DatabaseQualitySurvey") is None


class _Registry:
    def set_survey_definition_guid(self, *a, **k):
        pass


def _executor(reader):
    executor = SurveyDefinitionExecutor.__new__(SurveyDefinitionExecutor)
    executor.reader, executor.registry = reader, _Registry()
    return executor


def test_the_executor_says_could_not_look_up_when_the_calls_raised():
    reader = _reader(_OnlyKnowsTheQualifiedName(by_name_raises=True, find_raises=True))
    with pytest.raises(SurveyDefinitionExecutorError) as raised:
        _executor(reader)._resolve_process_guid("database", "x", "PostgreSQL Database", "DatabaseQualitySurvey", False)
    assert "Could not look up" in str(raised.value) and "not a finding that it does not exist" in str(raised.value)


def test_the_executor_still_says_not_found_when_nothing_raised():
    reader = _reader(_OnlyKnowsTheQualifiedName())
    with pytest.raises(SurveyDefinitionExecutorError) as raised:
        _executor(reader)._resolve_process_guid("database", "x", "PostgreSQL Database", "NoSuchSurvey", False)
    assert "No Survey Definition found matching 'NoSuchSurvey'" in str(raised.value)


def test_the_executor_resolves_the_bare_quality_definition():
    reader = _reader(_OnlyKnowsTheQualifiedName())
    guid, ref = _executor(reader)._resolve_process_guid("database", "x", "PostgreSQL Database", "DatabaseQualitySurvey", False)
    assert (guid, ref) == (GUID, "DatabaseQualitySurvey")
