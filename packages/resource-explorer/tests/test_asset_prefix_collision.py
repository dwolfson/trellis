"""A repo must not adopt a sibling's Egeria asset.

`_find_or_create_asset` searches Egeria by qualifiedName with
`starts_with=True` and used to take `existing[0]`. Where one repo's URL is a
prefix of another's — `docling-project/docling` against `docling-project/
docling-eval` — the search matches both and the first result wins.

Measured live 2026-08-25: `docling` and `docling_eval` shared one asset GUID, so
one repo's survey reports were attaching to the other's catalog entry. Nothing
raised, nothing logged an error; the catalog was simply wrong about which
project it was describing.
"""
from __future__ import annotations

from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher


class _Result:
    resource_slug = "docling"
    project_display_name = "docling"
    github_url = "https://github.com/docling-project/docling"


def _element(qname, guid):
    return {"properties": {"qualifiedName": qname}, "elementHeader": {"guid": guid}}


class _Maker:
    """Returns what a prefix search really returns: siblings first."""

    def __init__(self, elements):
        self.elements = elements
        self.created = False

    def find_software_capabilities(self, **kw):
        return self.elements

    def create_software_capability(self, *a, **kw):
        self.created = True
        return "newly-created-guid"


def _publisher(maker):
    pub = EgeriaPublisher.__new__(EgeriaPublisher)
    pub._asset_maker = maker
    pub._registry = None
    # Only what the create path reads; this test is about WHICH asset is
    # chosen, not about how one is built.
    pub.zone_names = None
    pub._zone_names = None
    return pub


def test_a_sibling_prefix_match_is_not_adopted():
    """docling must not take docling-eval's asset just because it sorted first."""
    maker = _Maker([
        _element("SourceControlLibrary::https://github.com/docling-project/docling-eval", "eval-guid"),
        _element("SourceControlLibrary::https://github.com/docling-project/docling-core", "core-guid"),
    ])
    pub = _publisher(maker)
    guid = pub._find_or_create_asset(_Result())
    assert guid != "eval-guid", "adopted a sibling repo's asset — the live docling bug"
    assert maker.created, "should have created its own asset instead"


def test_the_exact_match_is_still_adopted():
    """The reuse path must keep working — this is not 'always create'."""
    maker = _Maker([
        _element("SourceControlLibrary::https://github.com/docling-project/docling-eval", "eval-guid"),
        _element("SourceControlLibrary::https://github.com/docling-project/docling", "mine"),
    ])
    pub = _publisher(maker)
    assert pub._find_or_create_asset(_Result()) == "mine"
    assert not maker.created, "created a duplicate instead of reusing the exact match"
