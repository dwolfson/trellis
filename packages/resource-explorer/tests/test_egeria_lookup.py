"""Exact qualifiedName lookups go through Egeria's unique-name read, not the exact-value search.

Live 2026-10-21/22: `get_guid_for_name(qn, property_name=["qualifiedName"])` timed out (30 s) on every adoption
lookup, blocking every new publish; `MetadataExpert.get_metadata_element_by_unique_name` answered in under 0.1 s
on the same repository. `resource_explorer.egeria_lookup.guid_by_qualified_name` is the one helper; this file
pins its contract and, per migrated site, that the fast method is called, `get_guid_for_name` is not, and a
lookup that fails still refuses to create.

Fakes are `create_autospec(..., spec_set=True)`: every call binds the real pyegeria signature.
"""
from __future__ import annotations

import ast
import pathlib
from unittest.mock import create_autospec

import pytest
from pyegeria import AutomatedCuration, MetadataExpert
from pyegeria.core._exceptions import PyegeriaConnectionException

from resource_explorer.egeria_lookup import (
    NoAnswer, QualifiedNameLookupError, QualifiedNameTypeMismatch, guid_by_qualified_name)
from tests.qn_lookup_bridge import element_answer

MISS = "No elements found"
GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
QN = "SolutionComponent::x::y::z"

pytestmark = pytest.mark.usefixtures("signed_in_caller")


def expert(answer=None, *, raises=None):
    fake = create_autospec(MetadataExpert, instance=True, spec_set=True)
    if raises is not None:
        fake.get_metadata_element_by_unique_name.side_effect = raises
    else:
        fake.get_metadata_element_by_unique_name.return_value = answer
    return fake


# ── the helper's contract ────────────────────────────────────────────────

def test_found_returns_the_guid_and_asks_for_qualified_name():
    fake = expert(element_answer(GUID, "FileFolder"))
    assert guid_by_qualified_name(fake, QN) == GUID
    fake.get_metadata_element_by_unique_name.assert_called_once_with(QN, property_name="qualifiedName")


def test_the_explicit_not_found_answer_is_none_and_a_fake_raising_raises():
    """The architect's one test: a fake returning the string gives None, a fake raising gives the raise."""
    assert guid_by_qualified_name(expert(MISS), QN) is None
    assert guid_by_qualified_name(expert("No element found"), QN) is None
    boom = PyegeriaConnectionException()
    with pytest.raises(PyegeriaConnectionException):
        guid_by_qualified_name(expert(raises=boom), QN)


@pytest.mark.parametrize("odd", ["Server busy", "", "   ", {}, [], [element_answer(GUID)], 7, {"x": 1},
                                 {"elementGUID": "not-a-guid"}])
def test_an_answer_of_an_unknown_shape_raises_never_absent(odd):
    with pytest.raises(QualifiedNameLookupError):
        guid_by_qualified_name(expert(odd), QN)


def test_no_answer_at_all_raises_and_says_so():
    from resource_explorer.egeria_absence import lookup_could_not_be_made

    with pytest.raises(NoAnswer) as info:
        guid_by_qualified_name(expert(None), QN)
    assert "Egeria gave no answer" in lookup_could_not_be_made(QN, info.value)


def test_the_asset_graph_shape_is_read_too():
    answer = {"elementHeader": {"guid": GUID, "type": {"typeName": "RelationalDatabase"}}}
    assert guid_by_qualified_name(expert(answer), QN) == GUID


def test_type_is_checked_against_the_type_and_its_supertypes():
    answer = element_answer(GUID, "RelationalDatabase", supers=["Database", "DataAsset", "Referenceable"])
    assert guid_by_qualified_name(expert(answer), QN, type_name="RelationalDatabase") == GUID
    assert guid_by_qualified_name(expert(answer), QN, type_name="DataAsset") == GUID


def test_another_type_holding_the_name_raises_it_is_not_absent():
    answer = element_answer(GUID, "DataFile", supers=["Referenceable"])
    with pytest.raises(QualifiedNameTypeMismatch):
        guid_by_qualified_name(expert(answer), QN, type_name="FileFolder")


def test_a_miss_with_a_type_is_still_none():
    assert guid_by_qualified_name(expert(MISS), QN, type_name="FileFolder") is None


# ── the guard: the slow endpoint does not come back ──────────────────────

#: Every remaining `get_guid_for_name(` in resource_explorer, with why it is NOT an exact-qualifiedName lookup.
ALLOWED_GET_GUID_FOR_NAME = {
    "bootstrap.py": 1,                                            # a displayName canary (no qualifiedName declared)
    "surveyors/survey_definition_reader.py": 1,                   # a GlossaryTerm question by displayName
    "surveyors/filesystem/egeria_filesystem_surveyor.py": 2,      # a file's / mount's pathName, not a qualifiedName
}


def test_get_guid_for_name_does_not_come_back_for_qualified_names():
    root = pathlib.Path(__file__).resolve().parent.parent / "resource_explorer"
    found: dict[str, int] = {}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        n = sum(1 for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get_guid_for_name")
        if n:
            found[path.relative_to(root).as_posix()] = n
    assert found == ALLOWED_GET_GUID_FOR_NAME, (
        "a get_guid_for_name( call came back (or an allowed one went): look up an exact qualifiedName with "
        "egeria_lookup.guid_by_qualified_name; add to ALLOWED only a search by display/resource/path name")


# ── per site: the fast method is called, the slow one is not, a failure still creates nothing ──

def _no_slow(ac):
    ac.get_guid_for_name.assert_not_called()


def test_publisher_find_element_guid():
    from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher

    pub = EgeriaPublisher()
    pub._automated_curation = create_autospec(AutomatedCuration, instance=True, spec_set=True)
    pub._metadata_expert = expert(element_answer(GUID))
    assert pub._find_element_guid(QN) == GUID
    pub._metadata_expert = expert(MISS)
    assert pub._find_element_guid(QN) == ""
    pub._metadata_expert = expert(raises=PyegeriaConnectionException())
    with pytest.raises(PyegeriaConnectionException):
        pub._find_element_guid(QN)                    # never "" : the caller's create does not run
    _no_slow(pub._automated_curation)


@pytest.mark.parametrize("modname, cls_name", [
    ("resource_explorer.surveyors.arch_recovery.materializer", "ComponentMaterializer"),
    ("resource_explorer.surveyors.arch_recovery.blueprint_materializer", "BlueprintMaterializer"),
])
def test_materializers_find_element_guid(modname, cls_name):
    import importlib

    m = getattr(importlib.import_module(modname), cls_name)(platform_url="https://fake")
    m._metadata_expert = expert(element_answer(GUID))
    assert m._find_element_guid(QN) == GUID
    m._metadata_expert = expert(MISS)
    assert m._find_element_guid(QN) == ""
    m._metadata_expert = expert(raises=PyegeriaConnectionException())
    with pytest.raises(PyegeriaConnectionException):
        m._find_element_guid(QN)


def test_blueprint_find_blueprint_uses_the_fast_read_and_verifies_on_read_back():
    from unittest.mock import MagicMock

    from resource_explorer.surveyors.arch_recovery.blueprint_materializer import BlueprintMaterializer

    m = BlueprintMaterializer(platform_url="https://fake")
    m._metadata_expert = expert(MISS)
    m._solution_architect = MagicMock()
    assert m._find_blueprint("SolutionBlueprint::a") is None
    m._metadata_expert.get_metadata_element_by_unique_name.assert_called_once_with(
        "SolutionBlueprint::a", property_name="qualifiedName")
    m._metadata_expert = expert(raises=PyegeriaConnectionException())
    with pytest.raises(PyegeriaConnectionException):
        m._find_blueprint("SolutionBlueprint::a")
    m._solution_architect.create_solution_blueprint.assert_not_called()


def test_database_surveyor_finders():
    from resource_explorer.surveyors.database.egeria_database_surveyor import (
        EgeriaDatabaseSurveyor, EgeriaDatabaseSurveyorError)

    s = EgeriaDatabaseSurveyor(platform_url="https://fake", view_server="v")
    s._automated_curation = create_autospec(AutomatedCuration, instance=True, spec_set=True)
    for finder in (s._find_element_guid, s._find_by_qualified_name):
        s._metadata_expert = expert(element_answer(GUID))
        assert finder(QN) == GUID
        s._metadata_expert = expert(MISS)
        assert finder(QN) == ""
        s._metadata_expert = expert(raises=PyegeriaConnectionException())
        with pytest.raises(EgeriaDatabaseSurveyorError, match="Egeria"):
            finder(QN)
    _no_slow(s._automated_curation)


def test_filesystem_surveyor_root_folder_is_the_fast_read_typed_and_paths_keep_the_name_search():
    from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import (
        EgeriaFileSystemSurveyor, EgeriaFileSystemSurveyorError)

    s = EgeriaFileSystemSurveyor(platform_url="https://fake", view_server="v")
    s._automated_curation = create_autospec(AutomatedCuration, instance=True, spec_set=True)
    s._metadata_expert = expert(element_answer(GUID, "FileFolder"))
    assert s._find_element_guid(QN, type_name="FileFolder", qualified_name=True) == GUID
    s._metadata_expert = expert(MISS)
    assert s._find_element_guid(QN, type_name="FileFolder", qualified_name=True) == ""
    s._metadata_expert = expert(raises=PyegeriaConnectionException())
    with pytest.raises(EgeriaFileSystemSurveyorError, match="could not be made"):
        s._find_element_guid(QN, type_name="FileFolder", qualified_name=True)
    _no_slow(s._automated_curation)
    # a file's path is a pathName, not a qualifiedName: still the name search
    s._automated_curation.get_guid_for_name.return_value = MISS
    assert s._find_element_guid("/mnt/x/a.csv") == ""
    s._automated_curation.get_guid_for_name.assert_called_once()


def test_doc_source_find_ref_guid_is_bounded_and_fast():
    from resource_explorer.doc_source_egeria import DocSourceLookupError, _find_ref_guid

    class Clients:
        def __init__(self, fake):
            self.fake = fake

        def of(self, cls):
            assert cls is MetadataExpert, "the slow AutomatedCuration search must not be built for this"
            return self.fake

    assert _find_ref_guid(Clients(expert(element_answer(GUID))), "ExternalReference::u") == GUID
    assert _find_ref_guid(Clients(expert(MISS)), "ExternalReference::u") == ""
    with pytest.raises(DocSourceLookupError, match="could not be made"):
        _find_ref_guid(Clients(expert(raises=PyegeriaConnectionException())), "ExternalReference::u")


def test_investigation_purposes_lookup_is_typed_and_fast():
    from resource_explorer import investigation_purposes as ip

    assert ip._lookup(expert(element_answer(GUID, "ValidValueDefinition", supers=[])), "q") == GUID
    assert ip._lookup(expert(MISS), "q") == ""
    for bad in (expert(raises=PyegeriaConnectionException()), expert(element_answer(GUID, "DataClass", supers=[])), None):
        with pytest.raises(ip.CouldNotCheck):
            ip._lookup(bad, "q")


def test_data_class_seed_lookup_is_typed_and_fast():
    from resource_explorer.surveyors.database import bootstrap_data_classes as bdc

    assert bdc._existing_guid(expert(element_answer(GUID, "DataClass", supers=[])), "q") == GUID
    assert bdc._existing_guid(expert(MISS), "q", "ValidValueDefinition") is None
    for bad in (expert(raises=PyegeriaConnectionException()), expert(element_answer(GUID, "DataClass", supers=[])), None):
        with pytest.raises(bdc.CouldNotCheck):
            bdc._existing_guid(bad, "q", "ValidValueDefinition")


def test_proposal_find_existing_is_typed_and_fast():
    from resource_explorer.surveyors.database.egeria_reference_catalog import ProposalLookupError, _find_existing

    assert _find_existing(expert(element_answer(GUID, "DataClass", supers=[])), "q", "DataClass") == GUID
    assert _find_existing(expert(MISS), "q", "DataClass") == ""
    for bad in (expert(raises=PyegeriaConnectionException()), expert(element_answer(GUID, "DataField", supers=[])), None):
        with pytest.raises(ProposalLookupError):
            _find_existing(bad, "q", "DataClass")


def test_bootstrap_canary_by_qualified_name_is_the_fast_read_and_a_failure_is_unknown_not_missing(tmp_path):
    from resource_explorer import bootstrap as bs

    batch = bs.Batch(batch_id="b", path=tmp_path, display_name="b", files=[], canary={"qualified_name": "Q::b"})
    assert bs.canary_present(batch, expert=expert(element_answer(GUID))) is True
    assert bs.canary_present(batch, expert=expert(MISS)) is False
    assert bs.canary_present(batch, expert=expert(raises=PyegeriaConnectionException())) is None
    assert bs.canary_present(batch, expert=expert("Server busy")) is None
