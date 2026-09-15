"""The GitHub SourceControlLibrary is a singleton, not one per repo.

Corrects the type error named in docs/Backlog.md ("Catalogue in layers",
2026-09-14): a repository is what GitHub manages, not a resource manager
itself. `_find_or_create_github_scl` finds or creates the ONE
SourceControlLibrary representing GitHub, cached as a global `app_settings`
row rather than a per-project column -- there is exactly one across the
whole catalog, unlike the per-repo Asset `_find_or_create_asset` still
caches under `projects.egeria_asset_guid`.
"""
from __future__ import annotations

from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher


def _element(qname, guid):
    return {"properties": {"qualifiedName": qname}, "elementHeader": {"guid": guid}}


class _Registry:
    """Just enough of ProjectRegistry's setting store to exercise the cache."""

    def __init__(self, initial: str | None = None):
        self._settings: dict[str, str] = {}
        if initial:
            self._settings["egeria.github_source_control_library_guid"] = initial

    def get_setting(self, key, default=None):
        return self._settings.get(key, default)

    def set_setting(self, key, value):
        self._settings[key] = value


class _Maker:
    def __init__(self, existing=None):
        self.existing = existing or []
        self.created = False
        self.searched = 0

    def find_software_capabilities(self, **kw):
        self.searched += 1
        return self.existing

    def create_software_capability(self, *a, **kw):
        self.created = True
        return "freshly-created-scl-guid"


def _publisher(maker, registry=None):
    pub = EgeriaPublisher.__new__(EgeriaPublisher)
    pub._asset_maker = maker
    pub._registry = registry
    pub.zone_names = None
    return pub


def test_a_verified_cached_guid_is_reused_with_no_create():
    reg = _Registry(initial="cached-guid")
    maker = _Maker(existing=[_element(EgeriaPublisher._GITHUB_SCL_QUALIFIED_NAME, "cached-guid")])
    pub = _publisher(maker, reg)
    assert pub._find_or_create_github_scl() == "cached-guid"
    assert not maker.created


def test_a_stale_cached_guid_falls_through_to_search_then_create():
    reg = _Registry(initial="dead-guid")
    maker = _Maker(existing=[])  # the cached GUID no longer resolves
    pub = _publisher(maker, reg)
    guid = pub._find_or_create_github_scl()
    assert guid == "freshly-created-scl-guid"
    assert maker.created
    assert reg.get_setting("egeria.github_source_control_library_guid") == "freshly-created-scl-guid"


def test_no_cache_but_egeria_already_has_one_is_found_not_duplicated():
    reg = _Registry()
    maker = _Maker(existing=[_element(EgeriaPublisher._GITHUB_SCL_QUALIFIED_NAME, "found-guid")])
    pub = _publisher(maker, reg)
    assert pub._find_or_create_github_scl() == "found-guid"
    assert not maker.created
    # Found via search, so the cache is backfilled for next time.
    assert reg.get_setting("egeria.github_source_control_library_guid") == "found-guid"


def test_nothing_cached_nothing_found_creates_exactly_one():
    reg = _Registry()
    maker = _Maker(existing=[])
    pub = _publisher(maker, reg)
    guid = pub._find_or_create_github_scl()
    assert guid == "freshly-created-scl-guid"
    assert maker.created


def test_it_works_with_no_registry_at_all():
    """publish() without a registry is a supported path elsewhere in this
    file -- the singleton lookup must degrade the same way, not crash on a
    None registry."""
    maker = _Maker(existing=[])
    pub = _publisher(maker, registry=None)
    assert pub._find_or_create_github_scl() == "freshly-created-scl-guid"
