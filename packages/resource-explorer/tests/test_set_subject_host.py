"""A set as the subject, on RE's host (brief 2026-10-30, Part C): one run for a work list's members, 3 + 1 annotations
under one run, a member of another kind skipped with a reason row, and a price line that sums."""
from __future__ import annotations

import pytest
from trellis_analytics.manifest import StepManifest

from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors import survey_step_host as host

SET = "wl_coco"


def _manifest() -> StepManifest:
    return StepManifest(name="set_probe", function="tests.set_step_fixture.run", source="ods", version="1",
                        resource_types=["database"], subject="set", display_name="Set Probe")


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "set.db"))
    for slug in ("a", "b", "c"):
        reg.register_database(DatabaseEntity(slug=slug, display_name=slug.upper(), db_type="postgresql", host="localhost",
                                             egeria_host="h", port=5442, database_name=slug))
    return reg


MEMBERS = [("database", "a"), ("database", "b"), ("database", "c")]


def test_a_set_run_over_three_members_stores_three_plus_one_annotations_under_one_run(registry):
    out = host.run_set_step(_manifest(), registry, SET, MEMBERS)
    assert out["per_member"] == 3 and out["rollups"] == 1 and out["annotation_count"] == 4
    for slug in "abc":
        run, rows = registry.query_step_annotations("database", slug, "set_probe")
        assert run == out["run"] and [r["scope"] for r in rows] == [slug]
    run, rows = registry.query_step_annotations(host.SET_ENTITY, SET, "set_probe")
    assert run == out["run"] and [r["scope"] for r in rows] == [SET] and rows[0]["summary"] == "3 members read"


def test_a_member_that_is_not_of_the_steps_resource_types_is_skipped_with_a_reason_row(registry):
    out = host.run_set_step(_manifest(), registry, SET, [*MEMBERS, ("filesystem", "fs1")])
    assert out["per_member"] == 4 and out["state_counts"] == {"measured": 4, "not_applicable": 1}
    run, rows = registry.query_step_annotations("filesystem", "fs1", "set_probe")
    assert run == out["run"] and rows[0]["scope"] == "fs1"
    assert "fs1 is a filesystem; step 'set_probe' measures database" in rows[0]["detail"]["additionalProperties"]["resultStateReason"]


def test_the_price_line_sums_its_members_and_never_turns_an_unmeasured_time_into_zero(registry):
    price = host.set_price(registry, _manifest(), [*MEMBERS, ("filesystem", "fs1")])
    assert price["members"] == 4 and price["priced"] == 3 and price["skipped"] == 1
    assert price["total"]["seconds"] is None and "not measured yet" in price["total"]["words"]
    assert [r["entity_slug"] for r in price["rows"]] == ["a", "b", "c", "fs1"]
    assert price["rows"][-1]["words"].startswith("skipped · fs1 is a filesystem")


def test_the_price_total_is_the_sum_of_the_members_when_every_member_is_measured(registry, monkeypatch):
    from resource_explorer import quality_batch

    seconds = {"a": 30.0, "b": 45.0, "c": 15.0}
    monkeypatch.setattr(quality_batch, "price_row", lambda reg, slug, definition="": {
        "entity_slug": slug, "can_run": True, "tables": {"count": 10}, "time": {"seconds": seconds[slug]}})
    price = host.set_price(registry, _manifest(), MEMBERS)
    assert price["total"]["seconds"] == 90.0 and price["tables"] == 30
    assert "the sum of its members' measured times" in price["total"]["words"]


def test_the_per_resource_host_refuses_a_set_step_and_says_where_to_run_it(registry):
    with pytest.raises(host.StepNotInstalled, match="run it from a work list"):
        host.SurveyStepHost(_manifest(), "database")(registry.get_database("a"), registry)


def test_a_set_step_is_not_a_per_resource_analysis_but_is_offered_by_the_list(registry, monkeypatch):
    m = _manifest()
    monkeypatch.setattr("trellis_analytics.discovery.discover", lambda: {"set_probe": m})
    assert "set_probe" not in host.discover_steps("database")
    assert "set_probe" in host.discover_set_steps("database")
    offers = host.set_step_offers(registry, {"entity_type": "database",
                                             "members": [{"entity_slug": s} for s in "abc"]})
    assert [o["step"] for o in offers] == ["set_probe"] and offers[0]["price"]["priced"] == 3


def test_the_work_lists_page_offers_the_set_step_priced_and_runs_it(registry, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from resource_explorer.web.routes import work_lists as routes

    m = _manifest()
    wl = {"slug": SET, "entity_type": "database", "members": [{"entity_slug": s, "entity_type": "database"} for s in "abc"]}

    class FakeLists:
        def __init__(self):
            self.registry = registry

        def get(self, slug):
            return wl if slug == SET else None

    monkeypatch.setattr(routes, "WorkLists", FakeLists)
    monkeypatch.setattr(routes, "_requested_by", lambda: "")
    monkeypatch.setattr("trellis_analytics.discovery.discover", lambda: {"set_probe": m})
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/work-lists")
    client = TestClient(app)
    offers = client.get(f"/api/work-lists/{SET}/set-steps").json()
    assert offers["members"] == 3 and offers["offers"][0]["price"]["words"].startswith("3 member(s)")
    assert client.post(f"/api/work-lists/{SET}/set-steps/set_probe/run").status_code == 401       # nobody signed in
    monkeypatch.setattr(routes, "_requested_by", lambda: "erinoverview")
    ran = client.post(f"/api/work-lists/{SET}/set-steps/set_probe/run").json()
    assert ran["requested_by"] == "erinoverview"
    assert ran["per_member"] == 3 and ran["rollups"] == 1
    assert client.post(f"/api/work-lists/{SET}/set-steps/nope/run").status_code == 404
    assert client.get("/api/work-lists/missing/set-steps").status_code == 404
