"""Curate — the plan, the record, the commit, and the population rule.

Repo Handoff item 6 and the Curate wireframe: three columns answering
one question, candidates with evidence never auto-applied, testimony
copied and measurements linked, only worthy things curated.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resource_explorer.curate_plan import CURATE_POPULATION, Curations, build_plan
from resource_explorer.registry import Project, ProjectRegistry


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
    from resource_explorer.web.app import app
    return TestClient(app)


def _seed(registry):
    """A repo with a declared distribution, implied interfaces, Dockerfiles,
    sub-resources, and one enrichment judgement."""
    registry.upsert_finding("p", "distribution", [{
        "check_name": "python:pyegeria", "label": "published",
        "summary": "pyegeria — python distribution declared in pyproject.toml; 3 command-line entry point(s): a, b, c; publish workflow: release.yml.",
        "detail": {"name": "pyegeria", "ecosystem": "python", "scripts": ["a", "b", "c"], "packages": [], "manifest": "pyproject.toml", "publish_workflow": "release.yml"}}])
    registry.upsert_finding("p", "interface_surface", [
        {"check_name": "cli", "label": "implied", "summary": "Depends on click — suggests a cli"},
        {"check_name": "http_api", "label": "implied", "summary": "Depends on fastapi — suggests a http api"},
        {"check_name": "published_spec", "label": "no", "summary": "No specification file found"}])
    registry.upsert_finding("p", "repo_conventions", [
        {"check_name": "deployment_docker", "label": "pass", "summary": "Deployment/container evidence found", "detail": {"files": ["Dockerfile", "a/Dockerfile"]}}])
    registry.upsert_finding("p", "repo_sub_resource_survey", [
        {"check_name": "docs", "label": "worthy", "summary": "top_level_structural_folder", "detail": {"path": "docs", "kind": "folder"}},
        {"check_name": "docs/guide.md", "label": "worthy", "summary": "well_known_file", "detail": {"path": "docs/guide.md", "kind": "file"}},
        {"check_name": ".idea", "label": "not_worthy", "summary": "generated", "detail": {"path": ".idea", "kind": "folder"}}])
    # The fact layer credits an analysis only for a recorded run; without
    # these, everything above reads as never_run and the plan stays honest
    # about it -- which is the third test below.
    from resource_explorer.activity_logger import log_analysis_run
    for aid in ("interface_surface", "repo_conventions", "sub_resource_survey", "data_file_profiling",
                "architecture_recovery", "dependency_analysis", "manifest_parse"):
        log_analysis_run(registry, "repo", "p", "P repo", "success", f"{aid} ran", aid)
    registry.save_context("repo", "p", {"enrichment": {
        "sensitivity": {"value": "internal", "kind": "judgement", "author": "peterprofile", "set_at": "2026-09-01T00:00:00+00:00"},
        "owner": {"value": "peterprofile", "kind": "judgement", "author": "peterprofile", "set_at": "2026-09-01T00:00:00+00:00", "interim": True},
    }})


class TestThePlan:
    def test_the_three_columns_are_candidates_with_evidence(self, registry):
        _seed(registry)
        plan = build_plan(registry, "p")
        kinds = {r["kind"]: r for r in plan["what_it_is"]}
        assert kinds["SoftwareLibrary"]["label"] == "Software Library · pyegeria, on PyPI"
        assert kinds["SoftwareLibrary"]["source"] == "manifest_parse"
        assert kinds["Endpoint"]["label"] == "Endpoint × 2 · cli, http_api · implied, no contract"
        assert kinds["InfrastructureAsset"]["label"] == "Infrastructure Asset? 2 Dockerfiles"   # a question mark, not "(suggested)"
        assert kinds["SoftwareCapability"]["state"] == "needs_human"                            # no intended use recorded
        assert all(r["candidate"] for r in plan["what_it_is"])
        assert all(r["source"] and r["evidence"] for r in plan["what_it_is"])
        holds = {r["kind"]: r for r in plan["what_it_holds"]}
        assert holds["SubResource"]["count"] == 2 and holds["SubResource"]["label"].startswith("2 of 3 sub-resources")
        assert holds["DataFile"]["candidate"] is False        # none profiled: a count of zero is not a thing to confirm
        assert plan["relates"][0]["candidate"] is False        # already-catalogued deps: not looked up, said so

    def test_the_manifest_copies_testimony_and_links_measurements(self, registry):
        _seed(registry)
        w = build_plan(registry, "p")["writes"]
        assert w["classifications"] == [{"key": "sensitivity", "classification": "Confidentiality", "value": "internal",
                                         "author": "peterprofile", "set_at": "2026-09-01T00:00:00+00:00", "interim": False, "review": False}]
        assert w["owner"] == {"value": "peterprofile", "interim": True, "author": "peterprofile"}
        assert w["catalogued"] is False and w["survey_reports_linked"] == 0

    def test_the_population_is_tracking_or_using_and_the_plan_says_which(self, registry):
        plan = build_plan(registry, "p")
        assert plan["disposition"] == "undecided" and plan["in_population"] is False
        registry.set_disposition("https://github.com/x/p", "tracking", resource_slug="p")
        assert build_plan(registry, "p")["in_population"] is True
        assert tuple(CURATE_POPULATION) == ("tracking", "using")

    def test_a_name_not_yet_read_is_said_not_guessed(self, registry):
        registry.upsert_finding("p", "manifest_parse", [])
        registry.upsert_metric("p", "manifest_parse", {"dependency_count": 3}, detail={"dependencies": {"manifests": ["pyproject.toml"]}})
        row = next(r for r in build_plan(registry, "p")["what_it_is"] if r["kind"] == "SoftwareLibrary")
        assert "not read" in row["label"] or "Software Library?" in row["label"]


class TestTheRecord:
    def test_the_record_is_append_only_and_tracks_each_step(self, registry):
        c = Curations(registry)
        rec = c.create("repo", "p", author="peterprofile", selection={"confirm": ["SoftwareLibrary"]},
                       manifest={"entities": ["SoftwareLibrary"]}, steps=["publish_asset", "classifications"])
        assert rec["state"] == "queued" and [s["state"] for s in rec["steps"]] == ["pending", "pending"]
        c.set_step(rec["id"], "publish_asset", "done", "asset 123")
        c.set_step(rec["id"], "classifications", "failed", "no client")
        out = c.finish(rec["id"])
        assert out["state"] == "failed" and out["finished_at"]
        assert [s["state"] for s in out["steps"]] == ["done", "failed"]
        assert c.for_resource("repo", "p")[0]["id"] == rec["id"]
        with pytest.raises(ValueError):
            c.create("repo", "p", author="", selection={}, manifest={}, steps=[])


class TestTheCommitRoute:
    def test_it_refuses_outside_the_population(self, client, registry):
        _seed(registry)
        r = client.post("/api/projects/p/curate/commit", json={"confirm": ["SoftwareLibrary"]})
        assert r.status_code == 409 and "tracking or using" in r.json()["detail"]

    def test_it_records_the_act_and_enqueues_the_run(self, client, registry):
        _seed(registry)
        registry.set_disposition("https://github.com/x/p", "using", resource_slug="p")
        r = client.post("/api/projects/p/curate/commit",
                        json={"confirm": ["SoftwareLibrary", "Endpoint"], "sub_resources": ["docs"], "note": "go"})
        assert r.status_code == 200, r.text
        body = r.json()
        rec = body["curation"]
        assert rec["author"] == "peterprofile" and rec["state"] == "queued"
        assert rec["manifest"]["entities"] == ["SoftwareLibrary", "Endpoint"]
        assert rec["manifest"]["contained"] == {"data_files": 0, "sub_resources": 1}
        assert [s["name"] for s in rec["steps"]] == ["publish_asset", "classifications", "sub_resources", "components"]
        run = registry.get_run(body["run_id"]) if hasattr(registry, "get_run") else None
        if run is not None:
            assert run["kind"] == "curate_commit" and json.loads(run["target"])["curation_id"] == rec["id"]
        assert client.get(f"/api/projects/p/curate/commits/{rec['id']}").json()["id"] == rec["id"]

    def test_a_non_candidate_is_refused(self, client, registry):
        _seed(registry)
        registry.set_disposition("https://github.com/x/p", "using", resource_slug="p")
        r = client.post("/api/projects/p/curate/commit", json={"confirm": ["Spaceship"]})
        assert r.status_code == 400

    def test_anonymous_is_refused(self, client, registry, monkeypatch):
        monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda request: None)
        assert client.post("/api/projects/p/curate/commit", json={"confirm": []}).status_code == 401


class TestTheCommitSteps:
    """The workflow with Egeria faked: each step lands on the record, a
    failure is a failed step and the rest still run, and the
    classifications carry the author and date."""

    def test_each_step_writes_its_outcome(self, registry, monkeypatch):
        _seed(registry)
        from resource_explorer.workflows import curate_commit as wf
        registry.set_project_context("repo", "p", status="personal")
        calls = []

        class FakeSurvey:
            annotations = [1, 2, 3]

        class FakeOrch:
            def __init__(self, registry=None): pass
            def run(self, slug, steps=None): return FakeSurvey()

        class FakePublisher:
            def __init__(self, registry=None): pass
            def publish(self, survey):
                registry.set_egeria_asset_guid("p", "asset-1") if hasattr(registry, "set_egeria_asset_guid") else None
                return "report-9"
            def publish_sub_resources(self, slug, url, guid, locators):
                calls.append(("subs", guid, list(locators)))
                return {l: f"g-{l}" for l in locators}

        class FakeClient:
            def set_confidentiality_classification(self, guid, body):
                calls.append(("conf", guid, body["properties"]["confidentialityLevel"], body["properties"]["notes"]))

        monkeypatch.setattr("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator", FakeOrch)
        monkeypatch.setattr("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher", FakePublisher)
        monkeypatch.setattr("resource_explorer.egeria_identity.classification_client", lambda *a, **k: FakeClient())
        monkeypatch.setattr(registry, "get_egeria_asset_guid", lambda slug: "asset-1")

        rec = Curations(registry).create("repo", "p", author="peterprofile",
                                         selection={"confirm": ["SoftwareLibrary"], "sub_resources": ["docs/guide.md"]},
                                         manifest={}, steps=list(wf.STEPS))
        out = wf.execute_curation(registry, rec["id"])
        by = {s["name"]: s for s in out["steps"]}
        assert by["publish_asset"]["state"] == "done" and "report-9" in by["publish_asset"]["detail"]
        assert by["classifications"]["state"] == "done" and "Confidentiality · internal" in by["classifications"]["detail"]
        assert by["sub_resources"]["state"] == "done"
        assert by["components"]["state"] == "skipped"
        assert out["state"] == "done"
        conf = next(c for c in calls if c[0] == "conf")
        assert conf[2] == 1 and "set by peterprofile on 2026-09-01" in conf[3]
        subs = next(c for c in calls if c[0] == "subs")
        assert subs[2] == ["docs", "docs/guide.md"]          # the ancestor folder was catalogued too
        assert {r["locator"] for r in registry.list_sub_resources("repo", "p")} == {"docs", "docs/guide.md"}

    def test_a_failed_publish_is_a_failed_step_and_the_rest_say_why(self, registry, monkeypatch):
        _seed(registry)
        from resource_explorer.workflows import curate_commit as wf
        registry.set_project_context("repo", "p", status="personal")

        class Boom:
            def __init__(self, registry=None): pass
            def run(self, slug, steps=None): raise RuntimeError("Egeria unreachable")

        monkeypatch.setattr("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator", Boom)
        rec = Curations(registry).create("repo", "p", author="peterprofile",
                                         selection={"sub_resources": ["docs"]}, manifest={}, steps=list(wf.STEPS))
        out = wf.execute_curation(registry, rec["id"])
        by = {s["name"]: s for s in out["steps"]}
        assert by["publish_asset"]["state"] == "failed" and "Egeria unreachable" in by["publish_asset"]["detail"]
        assert by["classifications"]["state"] == "failed" and "no asset" in by["classifications"]["detail"]
        assert by["sub_resources"]["state"] == "failed" and "no parent asset" in by["sub_resources"]["detail"]
        assert out["state"] == "failed"

    def test_no_project_context_stops_before_egeria_and_names_the_remedy(self, registry, monkeypatch):
        from resource_explorer.workflows import curate_commit as wf
        rec = Curations(registry).create("repo", "p", author="a", selection={}, manifest={}, steps=list(wf.STEPS))
        out = wf.execute_curation(registry, rec["id"])
        assert "no Egeria Project context" in out["steps"][0]["detail"]


class TestTheDistributionParser:
    def test_it_reads_what_the_manifests_declare(self, tmp_path):
        from resource_explorer.ingestion.distribution_parser import DistributionParser
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "pyegeria"\nversion = "1.0"\n[project.scripts]\nhey = "x:main"\n[tool.setuptools]\npackages = ["pyegeria"]\n')
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        (tmp_path / ".github" / "workflows" / "release.yml").write_text("uses: pypa/gh-action-pypi-publish@release/v1\n")
        (tmp_path / "ui").mkdir()
        (tmp_path / "ui" / "package.json").write_text('{"name": "@odpi/ui", "bin": {"ui": "cli.js"}}')
        (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
        (tmp_path / "node_modules" / "left-pad" / "package.json").write_text('{"name": "left-pad"}')
        found = {f["check_name"]: f for f in DistributionParser().parse(tmp_path)}
        assert set(found) == {"python:pyegeria", "javascript:@odpi/ui"}       # the vendored one is not this repo's
        py = found["python:pyegeria"]
        assert py["label"] == "published" and py["detail"]["publish_workflow"] == "release.yml"
        assert py["detail"]["scripts"] == ["hey"] and py["detail"]["packages"] == ["pyegeria"]
        assert found["javascript:@odpi/ui"]["label"] == "declared"
        assert "1 command-line entry point(s): hey" in py["summary"]


class TestTheMembersBehindTheCounts:
    """Every count on the Curate screen is a link to its members (the design:
    "you cannot confirm ninety contained datasets without reading them").
    The sub-resource count opened an empty rail because the findings are
    stored as `repo_sub_resource_survey`, not `sub_resource_survey`."""

    def test_the_sub_resource_count_opens_its_members(self, registry):
        _seed(registry)
        from resource_explorer.members import members_for
        ms = members_for(registry, "p", "sub_resource_survey", scope="all")
        assert ms.total == 3
        assert {g.name: g.count for g in ms.groups} == {"worthy": 2, "not_worthy": 1}
