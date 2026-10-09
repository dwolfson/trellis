"""Brief A (2026-10-09): Accept and Reject are decisions only; Publish writes the architecture.

Owner: "Publish should be the verb to save to Egeria". Accept used to enqueue `materialize_components`
(branch route) and to materialise + promote a blueprint (blueprint route); seven SolutionComponents were
created when "3 or so" were accepted. These tests pin the new split with no Egeria anywhere: the write
functions are replaced by ones that fail the test if reached.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from resource_explorer import architecture_publish as ap
from resource_explorer.registry import Project, ProjectRegistry

pytestmark = pytest.mark.usefixtures("mock_egeria_client_connections")

COMPS = [
    {"path": "pyegeria", "name": "pyegeria", "type": "Software Library", "confidence": 80},
    {"path": "pyegeria/commands", "name": "commands", "type": "Console Command", "confidence": 70},
    {"path": "pyegeria/commands/cat", "name": "cat", "type": "", "confidence": 40},
    {"path": "pyegeria/utils", "name": "utils", "type": "", "confidence": 30},
    {"path": "tests", "name": "tests", "type": "", "confidence": 20},
    {"path": "tools", "name": "tools", "type": "", "confidence": 20, "structural": True},
]


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P repo", github_url="https://github.com/x/p", description=""))
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda request: {"user_id": "peterprofile"})
    monkeypatch.setattr("resource_explorer.web.routes.curate._authorize_curation", lambda *a, **k: None)
    monkeypatch.setattr(
        "resource_explorer.component_tree._components",
        lambda reg, slug: [dict(c, materialized=bool(reg.get_materialized_component("repo", slug, c["path"])))
                           for c in COMPS])
    from resource_explorer.web.app import app
    return TestClient(app)


@pytest.fixture
def no_egeria(monkeypatch):
    """Every route into Egeria raises: a test that reaches one fails on the spot."""
    def boom(*a, **k):
        raise AssertionError("an Egeria write was reached")
    monkeypatch.setattr("resource_explorer.workflows.curate.materialize_component_if_accepted", boom)
    monkeypatch.setattr("resource_explorer.workflows.curate.materialize_blueprint_if_accepted", boom)
    monkeypatch.setattr("resource_explorer.workflows.curate.promote_to_publish_zones", boom)
    monkeypatch.setattr("resource_explorer.web.routes.curate._materialize_blueprint_if_accepted", boom)
    monkeypatch.setattr("resource_explorer.web.routes.curate._materialize_if_accepted", boom)
    monkeypatch.setattr("resource_explorer.surveyors.arch_recovery.materializer.ComponentMaterializer.materialize", boom)
    monkeypatch.setattr("resource_explorer.surveyors.arch_recovery.blueprint_materializer."
                        "BlueprintMaterializer.materialize_blueprint_element", boom)


def _seed_cluster(registry, name="core", perspective="physical", members=(), children=()):
    registry.upsert_finding("p", "architecture_blueprints", [{
        "check_name": "candidate_blueprint", "label": name,
        "detail": {"name": name, "perspective": perspective, "signal": "compose", "carrier": "compose.yaml",
                   "composed_into": "", "size": len(members), "members": list(members), "children": list(children),
                   "parent": "", "oversized": False, "target_size": 8, "run_scope": "", "not_a_claim": True}}],
        surveyed_at="2026-09-03T00:00:00")


def _held(registry, path):
    registry.record_materialized_component("repo", "p", path, f"SolutionComponent::repo::p::{path}", f"guid-{path}")


class TestAcceptWritesNothing:
    def test_a_branch_accept_makes_no_egeria_call_and_enqueues_no_run(self, client, registry, no_egeria):
        r = client.post("/api/projects/p/components/verdicts", json={"scope_locators": ["pyegeria"], "verdict": "accepted"})
        assert r.status_code == 200, r.text
        assert r.json()["run_id"] is None and r.json()["queued"] == 0
        assert registry.list_runs() == []
        assert registry.list_activity(entity_slug="p") == []     # not even a 'running' row nobody will close

    def test_a_blueprint_accept_makes_no_egeria_call_and_does_not_promote(self, client, registry, no_egeria):
        _seed_cluster(registry, members=["a"])
        r = client.post("/api/curate/blueprint-verdicts/repo/p", json={
            "perspective": "physical", "cluster_name": "core", "verdict": "accepted", "shape": "contents"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verdict"] == "accepted" and "materialization" not in body and "promotion" not in body
        assert registry.get_materialized_blueprint("repo", "p", "physical", "core") is None
        assert ap.blueprint_choices(body) == {"shape": "contents", "identifier": ""}

    def test_a_reject_of_something_already_in_egeria_writes_nothing_and_says_so(self, client, registry, no_egeria):
        _held(registry, "tests")
        r = client.post("/api/projects/p/components/verdicts", json={"scope_locators": ["tests"], "verdict": "rejected"})
        assert r.status_code == 200 and registry.list_runs() == []
        leaf = next(l for l in client.get("/api/projects/p/components/leaves", params={"branch": "tests"}).json()["leaves"]
                    if l["path"] == "tests")
        assert leaf["verdict"]["verdict"] == "rejected" and leaf["materialized"] is True    # the row says "still in Egeria"
        plan = client.get("/api/projects/p/architecture/publish-plan").json()
        assert plan["components"]["rejected_in_egeria"] == 1 and plan["nothing"] is True


class TestThePlan:
    def test_it_lists_exactly_the_accepted_components_not_yet_in_egeria(self, client, registry):
        client.post("/api/projects/p/components/verdicts", json={"scope_locators": ["pyegeria"], "verdict": "accepted"})
        _held(registry, "pyegeria/utils")
        plan = client.get("/api/projects/p/architecture/publish-plan").json()
        assert [c["path"] for c in plan["components"]["to_write"]] == [
            "pyegeria", "pyegeria/commands", "pyegeria/commands/cat"]
        assert plan["components"]["in_egeria"] == 1
        assert plan["label"] == "Publish 3 components"          # only the parts that exist

    def test_the_label_names_the_object_and_count_and_only_non_default_parts(self):
        assert ap.label_for(3, 1) == "Publish 3 components · 1 blueprint"
        assert ap.label_for(1, 0) == "Publish 1 component"
        assert ap.label_for(0, 2) == "Publish 2 blueprints"
        assert ap.label_for(0, 0) == "Nothing to publish"

    def test_an_accepted_blueprint_is_planned_new_then_finished_until_its_compositions_are_confirmed(self, client, registry):
        _seed_cluster(registry, members=["a"])
        client.post("/api/curate/blueprint-verdicts/repo/p", json={"perspective": "physical", "cluster_name": "core", "verdict": "accepted"})
        plan = client.get("/api/projects/p/architecture/publish-plan").json()
        assert [(b["key"], b["state"]) for b in plan["blueprints"]["to_write"]] == [("physical::core", "new")]
        registry.record_materialized_blueprint("repo", "p", "physical", "core", "SolutionBlueprint::repo::p::physical", "bp-1")
        for status in ("unconfirmed",):
            registry.append_catalogue_commit_proof(
                "p", proof="composition", node_kind="blueprint_shape", table_name="physical::core",
                element_guid="c", target_guid="k", qualified_name="SolutionComposition::c::k",
                detail={"status": status, "read_back": False})
        plan = client.get("/api/projects/p/architecture/publish-plan").json()
        assert [(b["state"], b["unconfirmed_compositions"]) for b in plan["blueprints"]["to_write"]] == [("finish", 1)]
        registry.append_catalogue_commit_proof(
            "p", proof="composition", node_kind="blueprint_shape", table_name="physical::core",
            element_guid="c", target_guid="k", qualified_name="SolutionComposition::c::k",
            detail={"status": "linked", "read_back": True})
        plan = client.get("/api/projects/p/architecture/publish-plan").json()
        assert plan["blueprints"]["to_write"] == [] and plan["blueprints"]["in_egeria"] == 1

    def test_children_are_written_before_the_blueprint_that_links_them(self, registry):
        for name, kids in (("root", ["kid"]), ("kid", [])):
            _seed_cluster(registry, name=name, members=["a"], children=kids)
            registry.record_component_verdict("repo", "p", f"physical::{name}", "accepted", "", "",
                                              verdict_target="blueprint", decided_by="x")
        keys = [b["key"] for b in ap.publish_plan(registry, "p")["blueprints"]["to_write"]]
        assert keys == ["physical::kid", "physical::root"]


class TestPublishEnqueues:
    def test_it_enqueues_one_run_for_exactly_the_planned_items(self, client, registry):
        client.post("/api/projects/p/components/verdicts", json={"scope_locators": ["pyegeria"], "verdict": "accepted"})
        _held(registry, "pyegeria/utils")
        r = client.post("/api/projects/p/architecture/publish")
        assert r.status_code == 200, r.text
        runs = registry.list_runs(kind="publish_architecture")
        assert len(runs) == 1 and r.json()["run_id"] == runs[0]["id"]
        assert json.loads(runs[0]["target"]) == {
            "slug": "p", "blueprints": [],
            "paths": ["pyegeria", "pyegeria/commands", "pyegeria/commands/cat"]}
        assert r.json()["queued"] == 3

    def test_a_second_press_while_one_runs_is_refused(self, client, registry):
        client.post("/api/projects/p/components/verdicts", json={"scope_locators": ["tests"], "verdict": "accepted"})
        assert client.post("/api/projects/p/architecture/publish").status_code == 200
        assert client.post("/api/projects/p/architecture/publish").status_code == 409
        assert len(registry.list_runs(kind="publish_architecture")) == 1

    def test_it_does_nothing_when_everything_accepted_is_already_there(self, client, registry):
        client.post("/api/projects/p/components/verdicts", json={"scope_locators": ["tests"], "verdict": "accepted"})
        _held(registry, "tests")
        r = client.post("/api/projects/p/architecture/publish")
        assert r.status_code == 200 and r.json()["queued"] == 0 and r.json()["run_id"] is None
        assert registry.list_runs() == []

    def test_anonymous_is_refused(self, client, monkeypatch):
        monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda request: None)
        assert client.post("/api/projects/p/architecture/publish").status_code == 401


class TestParentOnly:
    def test_the_parent_alone_records_one_verdict_and_leaves_the_children_undecided(self, client, registry):
        r = client.post("/api/projects/p/components/verdicts", json={
            "scope_locators": ["pyegeria"], "only_scopes": ["pyegeria"], "verdict": "accepted"})
        assert r.status_code == 200
        assert len(r.json()["verdicts"]) == 1                       # exactly one scope
        lv = {l["path"]: l for l in client.get("/api/projects/p/components/leaves", params={"branch": "pyegeria"}).json()["leaves"]}
        assert lv["pyegeria"]["verdict"]["verdict"] == "accepted" and lv["pyegeria"]["verdict"]["only"] is True
        assert all(lv[p]["verdict"] is None for p in ("pyegeria/commands", "pyegeria/commands/cat", "pyegeria/utils"))
        assert [c["path"] for c in ap.publish_plan(registry, "p")["components"]["to_write"]] == ["pyegeria"]

    def test_with_children_is_unchanged(self, client, registry):
        client.post("/api/projects/p/components/verdicts", json={"scope_locators": ["pyegeria"], "verdict": "accepted"})
        assert len(ap.publish_plan(registry, "p")["components"]["to_write"]) == 4

    def test_a_child_can_still_be_decided_under_a_parent_only_row(self, client, registry):
        client.post("/api/projects/p/components/verdicts", json={
            "scope_locators": ["pyegeria"], "only_scopes": ["pyegeria"], "verdict": "accepted"})
        client.post("/api/projects/p/components/verdicts", json={"scope_locators": ["pyegeria/utils"], "verdict": "accepted"})
        assert [c["path"] for c in ap.publish_plan(registry, "p")["components"]["to_write"]] == ["pyegeria", "pyegeria/utils"]


class TestTheRun:
    def test_per_item_results_are_proof_rows_done_skipped_failed_and_partial(self, registry, monkeypatch):
        for p in ("a", "b", "c", "d"):
            registry.record_component_verdict("repo", "p", p, "accepted", "", "", decided_by="x")
        monkeypatch.setattr("resource_explorer.component_tree._components",
                            lambda reg, slug: [{"path": p, "name": p, "type": "", "confidence": 80} for p in ("a", "b", "c", "d")])
        _held(registry, "d")                                    # in Egeria between the press and the run
        outcomes = {"a": (ap.DONE, "created in Egeria", "g-a"),
                    "b": (ap.FAILED, "OMAG-400-001 the type is not known", ""),
                    "c": (ap.PARTIAL, "written, but not promoted: x", "g-c")}
        monkeypatch.setattr(ap, "_publish_component", lambda reg, slug, path: outcomes[path])
        res = ap.run_publish(registry, "p", {"slug": "p", "paths": ["a", "b", "c", "d"], "blueprints": []}, "run-1")
        assert [(r["key"], r["status"]) for r in res] == [
            ("a", "done"), ("b", "failed"), ("c", "partial"), ("d", "skipped")]
        assert res[3]["words"] == "already in Egeria"
        last = ap.last_results(registry, "p")
        assert last["run"] == "run-1" and [(i["key"], i["status"]) for i in last["items"]] == [
            ("a", "done"), ("b", "failed"), ("c", "partial"), ("d", "skipped")]
        assert last["items"][1]["words"] == "OMAG-400-001 the type is not known"

    def test_components_are_written_before_blueprints_and_one_failure_does_not_stop_the_next(self, registry, monkeypatch):
        registry.record_component_verdict("repo", "p", "a", "accepted", "", "", decided_by="x")
        monkeypatch.setattr("resource_explorer.component_tree._components",
                            lambda reg, slug: [{"path": "a", "name": "a", "type": "", "confidence": 80}])
        _seed_cluster(registry, members=["a"])
        registry.record_component_verdict("repo", "p", "physical::core", "accepted", "", "", verdict_target="blueprint", decided_by="x")
        order = []
        monkeypatch.setattr(ap, "_publish_component", lambda reg, slug, path: order.append(("c", path)) or (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(ap, "_publish_blueprint", lambda reg, slug, item: order.append(("b", item["key"])) or (ap.DONE, "in Egeria", "bp"))
        res = ap.run_publish(registry, "p", {"slug": "p", "paths": ["a"], "blueprints": ["physical::core"]}, "run-2")
        assert order == [("c", "a"), ("b", "physical::core")]
        assert [r["status"] for r in res] == ["failed", "done"]
        assert "boom" in res[0]["words"]

    def test_a_blueprint_carries_the_shape_and_identifier_chosen_at_accept(self, registry, monkeypatch):
        _seed_cluster(registry, members=["a"])
        registry.record_component_verdict("repo", "p", "physical::core", "accepted",
                                          ap.encode_blueprint_choices("contents", "second"), "",
                                          verdict_target="blueprint", decided_by="x")
        seen = {}
        monkeypatch.setattr("resource_explorer.workflows.curate.materialize_blueprint_if_accepted",
                            lambda reg, et, slug, persp, cluster, verdict, **kw: seen.update(kw) or {"status": "materialized", "guid": ""})
        item = ap.publish_plan(registry, "p")["blueprints"]["to_write"][0]
        assert ap._publish_blueprint(registry, "p", item)[0] == ap.DONE
        assert seen == {"shape": "contents", "identifier": "second"}

    def test_a_blueprint_written_with_unconfirmed_compositions_is_partial_not_done(self, registry, monkeypatch):
        _seed_cluster(registry, members=["a"])
        registry.record_component_verdict("repo", "p", "physical::core", "accepted", "", "", verdict_target="blueprint", decided_by="x")
        monkeypatch.setattr("resource_explorer.workflows.curate.materialize_blueprint_if_accepted",
                            lambda *a, **k: {"status": "partial", "guid": "bp", "compositions": [
                                {"status": "linked"}, {"status": "unconfirmed"}]})
        monkeypatch.setattr("resource_explorer.workflows.curate.promote_to_publish_zones", lambda g: {"status": "ok"})
        item = ap.publish_plan(registry, "p")["blueprints"]["to_write"][0]
        status, words, guid = ap._publish_blueprint(registry, "p", item)
        assert status == ap.PARTIAL and "1 of 2 compositions not confirmed" in words and guid == "bp"

    def test_the_queue_handler_fails_the_run_when_any_item_failed(self, registry, monkeypatch):
        from resource_explorer import run_queue
        monkeypatch.setattr("resource_explorer.catalogue_commit.run_with_loop", lambda fn, *a: fn(*a))
        monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                            lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
        monkeypatch.setattr(ap, "run_publish", lambda reg, slug, target, run: [
            {"kind": "component", "key": "a", "name": "a", "status": "done", "words": ""},
            {"kind": "component", "key": "b", "name": "b", "status": "failed", "words": "Egeria said no"}])
        out = run_queue.HANDLERS["publish_architecture"]({"slug": "p", "paths": ["a", "b"], "blueprints": []}, "act-1")
        assert out.state == "failed" and "b: failed · Egeria said no" in out.error
