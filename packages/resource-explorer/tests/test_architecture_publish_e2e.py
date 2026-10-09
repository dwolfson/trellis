"""Brief A round 4: the plan and the write must agree, so one press settles the plan.

Drives `run_publish` END TO END with nothing of RE's own mocked: the real component and blueprint workflows, the real
materializers, the real shape plan, proof rows and plan. Only the client boundary is faked: one fake Egeria that
answers like 6.2 (a component with no children carries no children key; the composition relationship read answers
"No elements found" or a list with `elementAtEnd1`), the outbox enqueue, and the zone client. Components A and B and
blueprint P are accepted and published in ONE press, in the three shapes; the NEXT `publish_plan` must be empty.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from resource_explorer import architecture_publish as ap
from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.arch_recovery import admission as adm
from resource_explorer.surveyors.arch_recovery import blueprint_materializer as bm
from resource_explorer.surveyors.arch_recovery import materializer as cm

G = "{:08d}-0000-0000-0000-000000000000".format


class FakeEgeria:
    """Every Egeria client the two materializers use, in one recording fake."""

    def __init__(self):
        self.n = 100
        self.qn_to_guid: dict[str, str] = {}
        self.types: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.subs: dict[str, list[str]] = {}
        self.calls: list[tuple] = []

    def _new(self, qn, type_name):
        self.n += 1
        guid = G(self.n)
        self.qn_to_guid[qn] = guid
        self.types[guid] = type_name
        return guid

    # AutomatedCuration
    def get_guid_for_name(self, qn, **kw):
        g = self.qn_to_guid.get(qn)
        return [g] if g else []

    # SolutionArchitect
    def create_solution_component(self, body):
        self.calls.append(("create_solution_component", body["properties"]["qualifiedName"]))
        return self._new(body["properties"]["qualifiedName"], "SolutionComponent")

    def create_solution_blueprint(self, body):
        self.calls.append(("create_solution_blueprint", body["properties"]["qualifiedName"]))
        return self._new(body["properties"]["qualifiedName"], "SolutionBlueprint")

    def get_solution_blueprint_by_guid(self, guid, **kw):
        qn = next((q for q, g in self.qn_to_guid.items() if g == guid), "")
        return {"elementHeader": {"guid": guid, "type": {"typeName": "SolutionBlueprint"}},
                "properties": {"qualifiedName": qn}, "collectionMembers": []}

    def get_solution_component_by_guid(self, guid, **kw):      # 6.2: no children key at all
        return {"elementHeader": {"guid": guid, "type": {"typeName": "SolutionComponent"}}, "properties": {}}

    def get_solution_components_by_name(self, name, **kw):
        return "No elements found"

    def link_subcomponent(self, container, child, body):
        self.calls.append(("link_subcomponent", container, child))
        self.subs.setdefault(container, []).append(child)

    # MetadataExpert
    def get_related_metadata_elements(self, guid, relationship_type, body, **kw):
        kids = self.subs.get(guid, [])
        if not kids:
            return "No elements found"
        return {"elementList": [{"element": {"elementGUID": k}, "elementAtEnd1": False} for k in kids]}


@pytest.fixture
def world(tmp_path, monkeypatch):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="p", display_name="P repo", github_url="https://github.com/x/p"))
    fake = FakeEgeria()
    outbox: list[tuple] = []

    def comp_connect(self):
        self._solution_architect = fake
        self._automated_curation = fake
    monkeypatch.setattr(cm.ComponentMaterializer, "_connect", comp_connect)
    monkeypatch.setattr("resource_explorer.egeria_identity.classification_client", lambda identity=None: MagicMock())

    real = bm.BlueprintMaterializer

    def factory(registry=None):
        m = real(platform_url="https://fake", registry=registry)
        m._solution_architect = fake
        m._automated_curation = fake
        m._metadata_expert = fake
        m._connect = lambda: None
        return m
    monkeypatch.setattr(bm, "BlueprintMaterializer", factory)
    monkeypatch.setattr("resource_explorer.egeria_outbox.enqueue_blueprint_members",
                        lambda registry, et, slug, bp, guids, **k: outbox.append((bp, list(guids))) or [1] * len(guids))
    monkeypatch.setattr("resource_explorer.workflows.curate.promote_to_publish_zones",
                        lambda guid: {"status": "already_unzoned", "words": "left as is"})
    return reg, fake, outbox


def _seed(reg, cluster, a_admission=adm.BUILT):
    for slug, admission in (("a", a_admission), ("b", adm.BUILT)):
        reg.upsert_finding("p", "architecture_recovery", [{
            "check_name": "component", "label": "x",
            "detail": {"name": slug.upper(), "slug": slug, "type": "Software Service", "admission": admission}}],
            surveyed_at="2026-10-09T00:00:00", scope_locator=f"src/{slug}")
        reg.record_component_verdict("repo", "p", f"src/{slug}", "accepted", "", "", decided_by="x")
    reg.upsert_finding("p", "architecture_blueprints", [{
        "check_name": "candidate_blueprint", "label": cluster,
        "detail": {"name": cluster, "perspective": "deployment", "members": ["a", "b"], "children": [],
                   "parent": "", "oversized": False, "composed_into": ""}}], surveyed_at="2026-10-09T00:00:00")
    reg.record_component_verdict("repo", "p", f"deployment::{cluster}", "accepted", "", "",
                                 verdict_target="blueprint", decided_by="x")


def _press(reg):
    plan = ap.publish_plan(reg, "p")
    target = {"slug": "p", "paths": [c["path"] for c in plan["components"]["to_write"]],
              "blueprints": [b["key"] for b in plan["blueprints"]["to_write"]]}
    assert len(target["paths"]) == 2 and len(target["blueprints"]) == 1, "A, B and P are all waiting"
    return ap.run_publish(reg, "p", target, "run-1")


def _settled(reg):
    plan = ap.publish_plan(reg, "p")
    assert plan["components"]["to_write"] == []
    assert plan["blueprints"]["to_write"] == [], plan["blueprints"]["to_write"]
    assert plan["nothing"] is True


class TestOnePressSettlesThePlan:
    def test_a_container_shape(self, world):
        reg, fake, outbox = world
        _seed(reg, "A")                                   # the cluster is named after A, a real component: A is the container
        res = _press(reg)
        assert [(r["kind"], r["status"]) for r in res] == [("component", "done"), ("component", "done"), ("blueprint", "done")]
        a, b = (fake.qn_to_guid[f"SolutionComponent::repo::p::src/{s}"] for s in "ab")
        assert [c for c in fake.calls if c[0] == "link_subcomponent"] == [("link_subcomponent", a, b)]
        assert [g for _, g in outbox] == [[a]]            # only the container is a member
        _settled(reg)

    def test_b_contents_shape_with_no_root(self, world):
        reg, fake, outbox = world
        _seed(reg, "a grouping of services")              # no member is the root
        res = _press(reg)
        assert [r["status"] for r in res] == ["done", "done", "done"]
        a, b = (fake.qn_to_guid[f"SolutionComponent::repo::p::src/{s}"] for s in "ab")
        assert not [c for c in fake.calls if c[0] == "link_subcomponent"]
        assert sorted(outbox[0][1]) == sorted([a, b])     # both are direct members
        _settled(reg)

    def test_c_contents_shape_where_root_a_is_only_referenced_but_cached(self, world):
        reg, fake, outbox = world
        _seed(reg, "A", a_admission=adm.REFERENCED)       # named after A, but A is referenced only: contents, A left out
        res = _press(reg)
        assert [r["status"] for r in res] == ["done", "done", "done"]
        a, b = (fake.qn_to_guid[f"SolutionComponent::repo::p::src/{s}"] for s in "ab")
        assert reg.get_materialized_component("repo", "p", "src/a")["guid"] == a    # A is cached ...
        assert outbox[0][1] == [b]                                                    # ... but is not a member
        _settled(reg)                                     # and the plan does not ask for it for ever
