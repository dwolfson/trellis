"""RE's classification readers against REAL Egeria 6.2 answers (tests/fixtures/egeria_6_2, captured read-only
2026-10-14 from the quickstart with RE's daemon identity).

Two shapes reach RE:

* MetadataExpert (`get_metadata_element_by_guid`, `..._by_unique_name`, `find_metadata_elements_with_string`)
  answers an OpenMetadataElement: a top-level `classifications` list (Memento, Ownership, Anchors,
  ZoneMembership, DataScope all in it). This is the route every reader is fed today.
* The 6.2 ElementHeader (`AssetMaker.get_asset_by_guid`, `CollectionManager.get_collection_by_guid`, ...) has
  NO `classifications` list: each classification has its own field (`elementHeader.memento`, `.ownership`,
  `.anchor`, `.zoneMembership`, `.dataScope`), with flattened bean properties.

Each reader must read the dedicated header field first and fall back to the list. Fakes answer with the
captured JSON only, and bind pyegeria's real signatures.
"""
from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from resource_explorer import catalogue_gateway as gw
from resource_explorer import egeria_identity as ei
from resource_explorer import zone_access as za

FIXTURES = Path(__file__).parent / "fixtures" / "egeria_6_2"

COCO_DB = "0ff72014-8936-4bea-b3d1-6a4493b99b30"
OWNED_REPORT = "f2400b9e-312f-4d24-a4dd-f79351b6381f"
ZONED_PRODUCT = "2c236456-2b68-48cf-af73-42cc7d7a7de0"
MEMENTO_DB = "ad2724e6-40e9-46a9-aaff-e3352c6b04bb"


def answer(name: str):
    return copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text())["answer"])


# 6.2 ElementHeader shapes (dedicated fields, no list)
H_MEMENTO = "asset_maker_by_guid_for_lineage__memento"
H_DB_OWNED = "asset_maker_by_guid__database_ownership_anchor_datascope"
H_REPORT = "asset_maker_by_guid__survey_report_ownership_anchor_guid"
H_ZONED = "collection_manager_by_guid__product_zones_anchor"
# MetadataExpert shapes (the `classifications` list: the fallback)
L_MEMENTO = "metadata_expert_by_unique_name_for_lineage__memento_archived_qn"
L_MEMENTO_FIND = "metadata_expert_find_with_string_for_lineage__memento"
L_DB_OWNED = "metadata_expert_by_guid__database_ownership_anchors_datascope"
L_REPORT = "metadata_expert_by_guid__survey_report_ownership_anchor_guid"
L_ZONED = "metadata_expert_by_guid__product_zones_anchors"


def test_the_fixtures_are_the_two_shapes_this_file_says_they_are():
    for name in (H_MEMENTO, H_DB_OWNED, H_REPORT, H_ZONED):
        header = answer(name)["elementHeader"]
        assert "classifications" not in header and "classifications" not in answer(name)
    assert answer(H_MEMENTO)["elementHeader"]["memento"]["classificationName"] == "Memento"
    assert answer(H_DB_OWNED)["elementHeader"]["ownership"]["classificationProperties"]["owner"] == "Jules"
    assert answer(H_ZONED)["elementHeader"]["zoneMembership"]["classificationProperties"]["zoneMembership"] == [
        "digital-products"]
    for name in (L_MEMENTO, L_DB_OWNED, L_REPORT, L_ZONED):
        assert isinstance(answer(name)["classifications"], list) and "elementHeader" not in answer(name)


# ── fakes bound to pyegeria's real signatures ─────────────────────────────────────────────────────────────────

class _Bound:
    """Answers named methods with captured JSON; every call is bound to pyegeria's real signature first."""

    def __init__(self, cls, answers: dict):
        self._cls, self._answers, self.calls = cls, answers, []

    def __getattr__(self, name):
        if name not in self._answers:
            raise AttributeError(name)
        real = getattr(self._cls, name)

        def call(*args, **kwargs):
            inspect.signature(real).bind(self, *args, **kwargs)
            self.calls.append((name, args, kwargs))
            if isinstance(self._answers[name], BaseException):
                raise self._answers[name]
            return copy.deepcopy(self._answers[name])
        return call


def _metadata_expert(element):
    from pyegeria import MetadataExpert
    return _Bound(MetadataExpert, {"get_metadata_element_by_guid": element})


def _gateway(element):
    from pyegeria import ClassificationExplorer
    g = gw.PyegeriaCatalogueGateway(view_server="qs-view-server", platform_url="https://localhost:9443")
    explorer = _Bound(ClassificationExplorer, {"add_ownership_to_element": None})
    g._clients = {"MetadataExpert": _metadata_expert(element), "ClassificationExplorer": explorer}
    return g, explorer


# ── catalogue_gateway._is_memento (S19's archived flag) ───────────────────────────────────────────────────────

def test_memento_in_a_6_2_header_reads_archived():
    assert gw.parse_element_answer(answer(H_MEMENTO)).archived is True


def test_memento_in_the_classifications_list_still_reads_archived():
    assert gw.parse_element_answer(answer(L_MEMENTO)).archived is True
    assert [e.archived for e in gw.parse_elements_answer(answer(L_MEMENTO_FIND))] == [True]


@pytest.mark.parametrize("name", [H_DB_OWNED, H_REPORT, L_DB_OWNED, L_REPORT])
def test_no_memento_reads_not_archived(name):
    assert gw.parse_element_answer(answer(name)).archived is False


def test_an_unreadable_memento_field_raises_rather_than_reading_not_archived():
    el = answer(H_MEMENTO)
    el["elementHeader"]["memento"] = "Memento"
    with pytest.raises(gw.GatewayError, match="Memento"):
        gw.parse_element_answer(el)


# ── catalogue_gateway.set_owner (the Ownership read before classifying) ──────────────────────────────────────

@pytest.mark.parametrize("name", [H_DB_OWNED, L_DB_OWNED])
def test_ownership_already_naming_the_owner_is_read_and_nothing_is_written(name):
    g, explorer = _gateway(answer(name))
    assert g.set_owner(COCO_DB, "Jules") == ("already", "Ownership already names Jules")
    assert explorer.calls == []


@pytest.mark.parametrize("name", [H_DB_OWNED, L_DB_OWNED])
def test_ownership_naming_someone_else_is_read_and_a_refusal_reports(name):
    """An existing Ownership found means a refused add reports 'refused' (it did not before 6.2's field was read)."""
    g, explorer = _gateway(answer(name))
    explorer._answers["add_ownership_to_element"] = RuntimeError("Egeria refused")
    assert g.set_owner(COCO_DB, "Dana") == ("refused", "Egeria refused")


# ── zone_access.element_facts (zones, owners, anchor) ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [H_ZONED, L_ZONED])
def test_zones_are_read_from_either_shape(name):
    facts = za.element_facts(answer(name), ZONED_PRODUCT)
    assert facts.zones == ["digital-products"]
    assert facts.anchor == ""                         # Anchors without anchorGUID: its own anchor


@pytest.mark.parametrize("name", [H_REPORT, L_REPORT])
def test_anchor_naming_another_element_is_read_from_either_shape(name):
    facts = za.element_facts(answer(name), OWNED_REPORT)
    assert facts.anchor == COCO_DB
    assert facts.zones == []


@pytest.mark.parametrize("name", [H_DB_OWNED, L_DB_OWNED])
def test_ownership_without_user_ids_reads_no_owner_list_from_either_shape(name):
    """Egeria's isUserAnOwner reads Ownership.userIds; 6.2's Ownership carries owner/ownerTypeName, so None."""
    facts = za.element_facts(answer(name), COCO_DB)
    assert facts.owners is None and facts.anchor == "" and facts.zones == []


def test_an_unreadable_zone_field_raises_rather_than_reading_no_zones():
    el = answer(H_ZONED)
    el["elementHeader"]["zoneMembership"] = ["digital-products"]
    with pytest.raises(za.AccessUnreadable):
        za.element_facts(el, ZONED_PRODUCT)


def test_an_unreadable_anchor_field_raises_rather_than_reading_its_own_anchor():
    el = answer(H_REPORT)
    el["elementHeader"]["anchor"] = COCO_DB
    with pytest.raises(za.AccessUnreadable):
        za.element_facts(el, OWNED_REPORT)


# ── catalogue_gateway.read_zones / zones_of_element ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [H_ZONED, L_ZONED])
def test_gateway_read_zones_from_either_shape(name):
    g, _ = _gateway(answer(name))
    assert g.read_zones(ZONED_PRODUCT) == ["digital-products"]


# ── egeria_identity.read_zones / current_zones ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [H_ZONED, L_ZONED])
def test_identity_zone_reads_from_either_shape(name, monkeypatch):
    monkeypatch.setattr(ei, "_metadata_client", lambda identity=None: _metadata_expert(answer(name)))
    assert ei.read_zones(ZONED_PRODUCT) == ["digital-products"]
    assert ei.current_zones(ZONED_PRODUCT) == ["digital-products"]


@pytest.mark.parametrize("name", [H_DB_OWNED, L_DB_OWNED])
def test_identity_zone_reads_of_an_unzoned_element(name, monkeypatch):
    monkeypatch.setattr(ei, "_metadata_client", lambda identity=None: _metadata_expert(answer(name)))
    assert ei.read_zones(COCO_DB) == [] and ei.current_zones(COCO_DB) == []
