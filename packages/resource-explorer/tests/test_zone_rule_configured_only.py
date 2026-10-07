"""Brief section 5 (project owner, 2026-10-07): promotion adopts the configured-only zone rule.

No zone unless someone configured one. With nothing configured, accepting an element writes NO
`ZoneMembership` and CLEARS RE's own draft zone, and the verdict row says so; with a configured
zone, exactly that zone. The old default (`egeria-runtime`) must be unreachable from any write path.

Fake Egeria clients that RECORD every call, at the lowest layer RE owns (the classification client
and the metadata reader), so a stray write cannot hide behind a stubbed helper.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from resource_explorer import egeria_identity as ident
from resource_explorer.workflows import curate

DRAFT = "resource-explorer-draft"


def _element(guid: str, zones: list[str] | None) -> dict:
    cls = []
    if zones:
        cls.append({"classificationName": "ZoneMembership",
                    "classificationProperties": {"propertiesAsStrings": {"zoneMembership": ",".join(zones)}}})
    return {"elementGUID": guid, "type": {"typeName": "SolutionBlueprint"}, "classifications": cls}


class FakeEgeria:
    """One element's zones, a call log, and switches for the failure shapes."""

    def __init__(self, zones, *, clear_ok=True, clear_takes=True, unreadable=False):
        self.zones = list(zones)
        self.calls: list[tuple] = []
        self.clear_ok, self.clear_takes, self.unreadable = clear_ok, clear_takes, unreadable

    # the classification client
    def add_zone_membership(self, guid, body):
        self.calls.append(("add_zone_membership", guid, body))
        self.zones = list(body["properties"]["zoneMembership"])

    def clear_zone_membership(self, guid, body):
        self.calls.append(("clear_zone_membership", guid, body))
        if not self.clear_ok:
            raise RuntimeError("OMAG-SERVER-SECURITY-403 not authorized")
        if self.clear_takes:
            self.zones = []

    # the metadata reader
    def get_metadata_element_by_guid(self, guid):
        self.calls.append(("read", guid))
        if self.unreadable:
            raise RuntimeError("view server unavailable")
        return _element(guid, self.zones)

    def writes(self):
        return [c for c in self.calls if c[0] != "read"]


@pytest.fixture
def egeria(monkeypatch):
    monkeypatch.delenv("EXPLORER_PUBLISH_ZONES", raising=False)
    monkeypatch.setattr("resource_explorer.config.get_config",
                        lambda: type("c", (), {"egeria": type("e", (), {"default_catalog_zones": []})()})())

    def install(fake):
        monkeypatch.setattr(ident, "classification_client", lambda identity=None: fake)
        monkeypatch.setattr(ident, "_metadata_client", lambda identity=None: fake)
        # the lenient reader the configured path uses reads the same element
        monkeypatch.setattr(ident, "current_zones", lambda guid, identity=None: list(fake.zones))
        return fake
    return install


# ── nothing configured ─────────────────────────────────────────────────────

def test_nothing_configured_clears_the_draft_zone_and_writes_no_zone(egeria):
    fake = egeria(FakeEgeria([DRAFT]))
    out = curate.promote_to_publish_zones("bp-1")
    assert out["status"] == "promoted"
    assert out["words"] == "accepted · zones left to Egeria · everyone visible"
    assert [c[0] for c in fake.writes()] == ["clear_zone_membership"]       # one clear, no add
    assert fake.zones == []
    assert not any(c[0] == "add_zone_membership" for c in fake.calls), "a ZoneMembership was written"
    assert "egeria-runtime" not in repr(fake.calls), "the old default appeared in a body"


def test_nothing_configured_and_already_no_zone_writes_nothing(egeria):
    fake = egeria(FakeEgeria([]))
    out = curate.promote_to_publish_zones("bp-1")
    assert out["status"] == "already_unzoned"
    assert out["words"] == "accepted · zones left to Egeria · everyone visible"
    assert fake.writes() == []


def test_a_refused_clear_never_says_the_element_is_visible(egeria):
    fake = egeria(FakeEgeria([DRAFT], clear_ok=False))
    out = curate.promote_to_publish_zones("bp-1")
    assert out["status"] == "error"
    assert "everyone visible" not in out["words"]
    assert fake.zones == [DRAFT]


def test_a_clear_that_does_not_take_is_caught_by_the_read_back(egeria):
    fake = egeria(FakeEgeria([DRAFT], clear_takes=False))
    out = curate.promote_to_publish_zones("bp-1")
    assert out["status"] == "error"
    assert "everyone visible" not in out["words"]
    assert DRAFT in out["words"]


def test_an_unreadable_element_is_not_read_as_no_zone(egeria):
    fake = egeria(FakeEgeria([DRAFT], unreadable=True))
    out = curate.promote_to_publish_zones("bp-1")
    assert out["status"] == "error"
    assert "everyone visible" not in out["words"]
    assert fake.writes() == [], "wrote to an element whose zones could not be read"


def test_a_private_element_stays_private_when_nothing_is_configured(egeria):
    fake = egeria(FakeEgeria([ident.private_zone(), "alice"]))
    out = curate.promote_to_publish_zones("bp-1")
    assert out["status"] == "skipped"
    assert fake.writes() == []


# ── a configured zone ──────────────────────────────────────────────────────

def test_a_configured_zone_is_exactly_what_is_written(egeria, monkeypatch):
    monkeypatch.setenv("EXPLORER_PUBLISH_ZONES", "team-zone")
    fake = egeria(FakeEgeria([DRAFT]))
    out = curate.promote_to_publish_zones("bp-1")
    assert out["status"] == "promoted"
    assert out["words"] == "accepted · zone team-zone"
    assert [(c[0], c[2]["properties"]["zoneMembership"]) for c in fake.writes()] == [
        ("add_zone_membership", ["team-zone"])]
    assert "egeria-runtime" not in repr(fake.calls)


def test_the_configured_zone_is_never_cleared_and_no_default_joins_it(egeria, monkeypatch):
    monkeypatch.setenv("EXPLORER_PUBLISH_ZONES", "a, b")
    fake = egeria(FakeEgeria([DRAFT]))
    curate.promote_to_publish_zones("bp-1")
    assert not any(c[0] == "clear_zone_membership" for c in fake.calls)
    assert fake.zones == ["a", "b"]


# ── the default is unreachable ─────────────────────────────────────────────

def test_the_default_publish_zone_no_longer_exists_anywhere_in_the_code():
    assert not hasattr(ident, "publish_zones")
    assert not hasattr(ident, "DEFAULT_PUBLISH_ZONES")
    root = Path(ident.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        for m in re.finditer(r"DEFAULT_PUBLISH_ZONES|\bpublish_zones\(\)|[\"']egeria-runtime[\"']", text):
            line = text[:m.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(root)}:{line}")
    assert offenders == [], f"a publish-zone default is still reachable: {offenders}"


# ── the proof row, and the queued path that used to skip promotion entirely ─

@pytest.fixture
def registry(tmp_path):
    from resource_explorer.registry import Project, ProjectRegistry
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P", github_url="https://github.com/o/p"))
    return r


def test_a_promotion_is_recorded_as_a_proof_row_the_screen_reads(registry):
    promo = {"status": "promoted", "guid": "c1", "zones": [], "from_zones": [DRAFT],
             "words": curate.ZONES_LEFT_TO_EGERIA_WORDS}
    curate.record_promotion(registry, "p", "src/a", curate.NODE_PROMOTION_COMPONENT, promo, "dan")
    got = curate.promotion_by_scope(registry, "p", curate.NODE_PROMOTION_COMPONENT)
    assert got["src/a"]["words"] == "accepted · zones left to Egeria · everyone visible"
    assert curate.promotion_by_scope(registry, "p", curate.NODE_PROMOTION_BLUEPRINT) == {}
    curate.record_promotion(registry, "p", "src/b", curate.NODE_PROMOTION_COMPONENT, None)   # never attempted
    assert "src/b" not in curate.promotion_by_scope(registry, "p", curate.NODE_PROMOTION_COMPONENT)


def test_the_queued_materialize_handler_promotes_and_records(registry, egeria, monkeypatch):
    """The Next UI accepts a branch through the run queue; that path never promoted, so every element
    stayed in RE's draft zone. It now runs the same promotion and records its proof row."""
    from resource_explorer import run_queue
    fake = egeria(FakeEgeria([DRAFT]))
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry", lambda *a, **k: registry)
    monkeypatch.setattr(curate, "materialize_component_if_accepted",
                        lambda reg, et, slug, path, verdict: {"status": "materialized", "guid": "c1"})
    out = run_queue._handle_materialize_components({"slug": "p", "paths": ["src/a"]}, "act-1")
    assert out.state == "succeeded"
    assert [c[0] for c in fake.writes()] == ["clear_zone_membership"]
    got = curate.promotion_by_scope(registry, "p", curate.NODE_PROMOTION_COMPONENT)
    assert got["src/a"]["words"] == "accepted · zones left to Egeria · everyone visible"


def test_the_component_tree_leaf_carries_the_promotion_words(registry, monkeypatch):
    from resource_explorer import component_tree
    curate.record_promotion(registry, "p", "src/a", curate.NODE_PROMOTION_COMPONENT,
                            {"status": "promoted", "guid": "c1", "words": "accepted · zone team-zone"})
    monkeypatch.setattr(component_tree, "_components", lambda reg, slug: [{"path": "src/a", "name": "a"}])
    monkeypatch.setattr(component_tree, "_ports_by_component", lambda reg, slug: ({}, 0, 0))
    rows = component_tree.leaves(registry, "p", "src")
    assert rows[0]["promotion"]["words"] == "accepted · zone team-zone"
