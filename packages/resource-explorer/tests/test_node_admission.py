"""DESIGN-BLUEPRINT-NODE-ADMISSION.md: a node enters a blueprint by the evidence class of its boundary.

* a workspaces-style repository (compose files that run OTHER projects' images) admits 0 components, lists
  every service as a runtime dependency row, says the zero-component sentence, and is offered the
  Environment Deployment Blueprint;
* an egeria_git-style repository (Gradle modules, a built platform image, a published image, Kafka and
  Postgres alongside) admits its own components and no Kafka or Postgres node;
* the class is on each node; a person's reclassification with a reason is recorded and moves the node.

Synthetic fixtures in tmp_path; temp SQLite; nothing live.
"""
from __future__ import annotations

import os
import subprocess

import pytest

from resource_explorer import blueprint_kinds, dependency_table, node_admission
from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.arch_recovery import admission as adm
from resource_explorer.surveyors.sub_surveyors.arch_recovery_detect import ArchDetectSurveyor

SURVEYED = "2026-10-07T00:00:00"


def _write(root, rel, content=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _git(root):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=T", "-c", "commit.gpgsign=false",
                    "commit", "-q", "-m", "x"], cwd=root, check=True)


WORKSPACES_COMPOSE = """services:
  egeria-platform:
    image: ${EGERIA_REPO:-odpi}/egeria-platform:${EGERIA_VERSION:-latest}
    depends_on: [kafka, postgres]
    ports: ["9443:9443"]
  kafka:
    image: apache/kafka:3.7.0
  postgres:
    image: postgres:16
  jupyter:
    image: quay.io/jupyter/base-notebook:latest
    environment:
      - EGERIA_URL=https://egeria-platform:9443
"""


def _workspaces_repo(tmp_path):
    root = str(tmp_path / "workspaces")
    _write(root, "compose-configs/egeria-quickstart.yaml", WORKSPACES_COMPOSE)
    _write(root, "README.md", "# workspaces\n")
    _git(root)
    return root


EGERIA_COMPOSE = """services:
  platform:
    image: odpi/egeria-platform:latest
    build:
      context: ./platform
    depends_on: [kafka, postgres]
  ui:
    image: odpi/egeria-ui:latest
  worker:
    build: ./worker
  kafka:
    image: apache/kafka:3.7.0
  postgres:
    image: postgres:16
"""


def _egeria_repo(tmp_path):
    root = str(tmp_path / "egeria")
    _write(root, "settings.gradle", "rootProject.name = 'egeria'\ninclude 'open-metadata-implementation:core'\n"
                                    "include 'open-metadata-implementation:admin'\n")
    _write(root, "open-metadata-implementation/core/build.gradle", "plugins { id 'java' }\n")
    _write(root, "open-metadata-implementation/admin/build.gradle", "plugins { id 'java' }\n")
    _write(root, "docker/compose.yaml", EGERIA_COMPOSE)
    _write(root, "docker/platform/Dockerfile", "FROM eclipse-temurin:21\nCMD [\"java\", \"-jar\", \"platform.jar\"]\n")
    _write(root, "docker/platform/start.sh", "#!/bin/sh\n")
    _write(root, "docker/worker/Dockerfile", "FROM alpine\n")
    # the UI image is published by CI, not built from a compose context
    _write(root, ".github/workflows/publish.yml",
           "jobs:\n  publish:\n    steps:\n      - uses: docker/build-push-action@v5\n"
           "        with:\n          tags: odpi/egeria-ui:latest\n")
    _git(root)
    return root


@pytest.fixture
def registry(tmp_path_factory):
    return ProjectRegistry(db_path=str(tmp_path_factory.mktemp("db") / "t.db"))


def _survey(registry, slug, root, name=None):
    project = Project(slug=slug, display_name=name or slug, github_url=f"https://github.com/o/{slug}")
    registry.add(project)
    ArchDetectSurveyor(project, registry, local_path=root, surveyed_at=SURVEYED).run()
    return project


# ── the pure rule ───────────────────────────────────────────────────────

def test_images_are_compared_by_name_not_tag_registry_or_variable():
    assert adm.normalise_image("${R:-odpi}/egeria-platform:${V:-latest}") == "odpi/egeria-platform"
    assert adm.normalise_image("ghcr.io/odpi/egeria-platform@sha256:abc") == "odpi/egeria-platform"
    assert adm.same_image("egeria-platform", "odpi/egeria-platform:1")
    assert not adm.same_image("postgres", "odpi/egeria-platform")


def test_a_build_context_is_built_an_unpublished_image_is_referenced_a_published_one_shipped():
    pub = {"odpi/egeria-ui": "ci.yml:3"}
    assert adm.classify_compose_service({"image": "x/y", "build": "./y"}, "c.yaml", pub)[0] == adm.BUILT
    assert adm.classify_compose_service({"image": "odpi/egeria-ui:1", "build": ""}, "c.yaml", pub)[0] == adm.SHIPPED
    cls, why = adm.classify_compose_service({"image": "postgres:16", "build": ""}, "c.yaml", pub)
    assert (cls, why) == (adm.REFERENCED, "image postgres · from c.yaml")


# ── a workspaces-style repository ───────────────────────────────────────

class TestWorkspacesStyle:
    def test_admits_no_component_and_says_why(self, registry, tmp_path):
        _survey(registry, "workspaces", _workspaces_repo(tmp_path))
        assert registry.query_finding_scopes("workspaces", "architecture_recovery", check_name="component") == []
        s = node_admission.summary(registry, "workspaces")
        assert s["admitted"] == 0 and s["referenced"] == 4
        assert s["sentence"] == ("this repository deploys other software and builds none of its own: "
                                 "see Dependencies · runtime")
        assert s["left_out"][0] == "4 services referenced only · listed as runtime dependencies"

    def test_every_service_is_a_runtime_dependency_row_with_its_compose_source(self, registry, tmp_path):
        _survey(registry, "workspaces", _workspaces_repo(tmp_path))
        t = dependency_table.build_table(registry, "workspaces")
        refs = {r["name"]: r for r in t["rows"] if r["style"] == "referenced only"}
        assert set(refs) == {"egeria-platform", "kafka", "postgres", "jupyter"}
        assert refs["kafka"]["target"] == "apache/kafka"
        assert refs["egeria-platform"]["target"] == "odpi/egeria-platform"
        assert refs["kafka"]["state"] == "proposed"
        assert "compose-configs/egeria-quickstart.yaml" in refs["kafka"]["state_words"]
        assert t["deploys_only"].startswith("this repository deploys other software")
        assert t["counts"]["runtime"] >= 4

    def test_the_environment_deployment_blueprint_is_offered_and_only_then(self, registry, tmp_path):
        _survey(registry, "workspaces", _workspaces_repo(tmp_path))
        env = node_admission.environment(registry, "workspaces")
        assert len(env["nodes"]) == 4 and env["linked"] == 0
        assert {n["words"] for n in env["nodes"]} == {"builder not known"}
        kinds = blueprint_kinds.blueprint_kind_rows(
            label="Workspaces", blueprints=[], artifact_count=1, build_files=[], logical_unconfirmed=None,
            environment_services=4, environment_linked=0)
        row = next(k for k in kinds if k["kind"] == "environment")
        assert row["name"] == "Workspaces Environment Deployment Blueprint"
        assert row["state"] == "proposed" and "4 services run other projects' images" in row["source"]
        none = blueprint_kinds.blueprint_kind_rows(
            label="X", blueprints=[], artifact_count=0, build_files=[], logical_unconfirmed=None)
        assert [k["kind"] for k in none] == ["deployment", "build", "logical"]

    def test_the_environment_links_a_service_to_the_repository_that_builds_its_image(self, registry, tmp_path):
        _survey(registry, "egeria_git", _egeria_repo(tmp_path))
        _survey(registry, "workspaces", _workspaces_repo(tmp_path))
        env = node_admission.environment(registry, "workspaces")
        by = {n["name"]: n for n in env["nodes"]}
        assert by["egeria-platform"]["built_by"] == "egeria_git"
        assert by["egeria-platform"]["words"] == "built by egeria_git"
        assert by["kafka"]["built_by"] == "" and env["linked"] == 1


# ── an egeria_git-style repository ──────────────────────────────────────

class TestEgeriaStyle:
    def test_no_kafka_or_postgres_node_and_its_own_components_stay(self, registry, tmp_path):
        _survey(registry, "egeria_git", _egeria_repo(tmp_path))
        from resource_explorer.surveyors.repo_survey_definition_adapter import _architecture_recovery_results
        comps = {c["name"]: c for c in _architecture_recovery_results(registry, "egeria_git", max_depth=None)["components"]}
        names = " ".join(comps)
        assert "kafka" not in names and "postgres" not in names
        assert comps["platform"]["admission"] == "built_here"
        assert comps["ui"]["admission"] == "shipped_here"
        assert comps["ui"]["admission_evidence"].startswith("image odpi/egeria-ui · published by")
        assert any("open-metadata-implementation" in n for n in comps)        # Gradle modules, built here
        s = node_admission.summary(registry, "egeria_git")
        assert s["referenced"] == 2 and s["sentence"] == ""
        assert s["counts"]["shipped_here"] == 1 and s["counts"]["built_here"] >= 4

    def test_the_class_is_on_each_leaf(self, registry, tmp_path):
        from resource_explorer.component_tree import leaves
        _survey(registry, "egeria_git", _egeria_repo(tmp_path))
        classes = {l["name"]: (l["admission"], l["admission_evidence"]) for b in
                   ("docker", "docker::worker", "docker::ui", "open-metadata-implementation") for l in leaves(registry, "egeria_git", b)}
        assert classes["platform"][0] == "built_here" and classes["platform"][1] == "from docker/platform/Dockerfile"
        assert classes["worker"] == ("built_here", "from docker/compose.yaml · build ./worker")
        assert classes["ui"][0] == "shipped_here"

    def test_the_manifest_lists_what_was_found_and_not_admitted(self, registry, tmp_path):
        _survey(registry, "egeria_git", _egeria_repo(tmp_path))
        left = node_admission.summary(registry, "egeria_git")["left_out"]
        assert "2 services referenced only · listed as runtime dependencies" in left

    def test_the_environment_blueprint_is_offered_to_egeria_git_with_its_two_referenced_services(self, registry, tmp_path):
        _survey(registry, "egeria_git", _egeria_repo(tmp_path))
        assert len(node_admission.environment(registry, "egeria_git")["nodes"]) == 2


# ── a person reclassifies ───────────────────────────────────────────────

class TestReclassify:
    def test_a_reason_is_required_and_the_scope_must_be_a_node(self, registry, tmp_path):
        _survey(registry, "workspaces", _workspaces_repo(tmp_path))
        scope = node_admission.referenced_rows(registry, "workspaces")[0]["scope"]
        with pytest.raises(ValueError, match="reason"):
            node_admission.reclassify(registry, "workspaces", scope, "built_here", "  ", "dan")
        with pytest.raises(ValueError, match="not a node"):
            node_admission.reclassify(registry, "workspaces", "nope", "built_here", "r", "dan")
        with pytest.raises(ValueError, match="built_here or referenced_only"):
            node_admission.reclassify(registry, "workspaces", scope, "shipped_here", "r", "dan")

    def test_referenced_to_built_moves_it_out_of_the_table_and_into_the_tree_with_the_reason(self, registry, tmp_path):
        from resource_explorer.component_tree import leaves
        _survey(registry, "workspaces", _workspaces_repo(tmp_path))
        row = next(r for r in node_admission.referenced_rows(registry, "workspaces") if r["name"] == "jupyter")
        entry = node_admission.reclassify(registry, "workspaces", row["scope"], "built_here",
                                          "we maintain this notebook image", "dan")
        assert entry["by"] == "dan" and entry["reason"] == "we maintain this notebook image"
        names = {r["name"] for r in dependency_table.build_table(registry, "workspaces")["rows"]
                 if r["style"] == "referenced only"}
        assert names == {"egeria-platform", "kafka", "postgres"}
        leaf = [l for l in leaves(registry, "workspaces", row["scope"]) if l["path"] == row["scope"]][0]
        assert leaf["admission"] == "built_here"
        assert "reclassified by dan · we maintain this notebook image" == leaf["admission_evidence"]
        assert leaf["reclassified"]["reason"] == "we maintain this notebook image"
        assert node_admission.summary(registry, "workspaces")["admitted"] == 1

    def test_built_to_referenced_moves_a_component_into_the_table(self, registry, tmp_path):
        from resource_explorer.component_tree import leaves
        _survey(registry, "egeria_git", _egeria_repo(tmp_path))
        scope = next(l["path"] for l in leaves(registry, "egeria_git", "docker") if l["name"] == "platform")
        node_admission.reclassify(registry, "egeria_git", scope, "referenced_only", "vendored build we do not own", "dan")
        assert all(l["name"] != "platform" for l in leaves(registry, "egeria_git", "docker"))
        rows = {r["name"]: r for r in dependency_table.build_table(registry, "egeria_git")["rows"]
                if r["style"] == "referenced only"}
        assert "platform" in rows and "reclassified by dan: vendored build we do not own" in rows["platform"]["state_words"]

    def test_the_next_survey_honours_the_trail(self, registry, tmp_path):
        root = _workspaces_repo(tmp_path)
        project = _survey(registry, "workspaces", root)
        row = next(r for r in node_admission.referenced_rows(registry, "workspaces") if r["name"] == "jupyter")
        node_admission.reclassify(registry, "workspaces", row["scope"], "built_here", "ours", "dan")
        ArchDetectSurveyor(project, registry, local_path=root, surveyed_at="2026-10-08T00:00:00").run()
        scopes = registry.query_finding_scopes("workspaces", "architecture_recovery", check_name="component")
        assert any("jupyter" in s for s in scopes)
        assert node_admission.summary(registry, "workspaces")["referenced"] == 3

    def test_a_confirmed_referenced_row_publishes_as_an_annotation_only(self, registry, tmp_path):
        _survey(registry, "workspaces", _workspaces_repo(tmp_path))
        key = next(r["key"] for r in dependency_table.build_table(registry, "workspaces")["rows"]
                   if r["style"] == "referenced only" and r["name"] == "kafka")
        dependency_table.record_confirmations(registry, "workspaces", [key], "confirmed", "dan")
        ann = dependency_table.runtime_annotations(registry, "workspaces")
        assert [a.json_properties["target"] for a in ann] == ["apache/kafka"]


# ── the routes ──────────────────────────────────────────────────────────

class TestRoutes:
    @pytest.fixture
    def client(self, registry, monkeypatch):
        from fastapi.testclient import TestClient
        monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                            lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
        monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
        monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda request: {"user_id": "dan"})
        monkeypatch.setattr("resource_explorer.web.routes.curate._authorize_curation", lambda *a, **k: None)
        from resource_explorer.web.app import app
        return TestClient(app)

    def test_the_selector_offers_the_environment_kind_only_when_services_are_referenced(self, client, registry, tmp_path):
        _survey(registry, "workspaces", _workspaces_repo(tmp_path))
        out = client.get("/api/projects/workspaces/components/blueprints").json()
        assert [k["kind"] for k in out["kinds"]] == ["deployment", "build", "logical", "environment"]
        assert out["admission"]["sentence"].startswith("this repository deploys other software")
        env = client.get("/api/projects/workspaces/environment-blueprint").json()
        assert len(env["nodes"]) == 4

    def test_a_repository_with_nothing_referenced_is_not_offered_it(self, client, registry):
        registry.add(Project(slug="p", display_name="P", github_url="https://github.com/o/p"))
        out = client.get("/api/projects/p/components/blueprints").json()
        assert "environment" not in [k["kind"] for k in out["kinds"]]

    def test_reclassify_records_the_person_and_the_reason_and_refuses_no_reason(self, client, registry, tmp_path):
        _survey(registry, "workspaces", _workspaces_repo(tmp_path))
        scope = next(r["scope"] for r in node_admission.referenced_rows(registry, "workspaces") if r["name"] == "jupyter")
        bad = client.post("/api/projects/workspaces/components/reclassify",
                          json={"scope_locator": scope, "to": "built_here", "reason": ""})
        assert bad.status_code == 400
        ok = client.post("/api/projects/workspaces/components/reclassify",
                         json={"scope_locator": scope, "to": "built_here", "reason": "ours"})
        assert ok.status_code == 200 and ok.json()["reclassified"]["by"] == "dan"
        assert node_admission.read_reclassifications(registry, "workspaces")[scope][-1]["reason"] == "ours"
