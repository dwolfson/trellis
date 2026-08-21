"""Regression tests for resource_explorer/surveyors/arch_recovery — the
port of scripts/arch-spike into real package code (Phase 1 plan §4.2-4.5).

Every test below regresses a specific, numbered finding from
scripts/arch-spike/README.md — these were real bugs the spike hit and fixed
(§4.5's own instruction: "every finding in the spike README that was a bug
becomes a regression test"). Fixture trees are small and synthetic, built
in tmp_path — never against the real repos or the pre-registered
architecture-ground-truth fixtures.
"""
from __future__ import annotations

import os
import subprocess

import pytest

from resource_explorer.surveyors.arch_recovery import (
    code_markers,
    coupling,
    detectors,
    exclusion,
    imports,
)

pytestmark = pytest.mark.skipif(
    code_markers._binary() is None, reason="ast-grep binary not available in this environment"
)


def _write(root, rel, content=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return rel


def _git_init(root):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def _tracked(root):
    return exclusion.scan(root).first_party


# ── finding 3: compose files are identified by content, not filename ──────

class TestFinding3ComposeByContent:
    def test_solution_deployment_named_after_the_solution_is_detected(self, tmp_path):
        """`egeria-quickstart-local.yaml` has no "compose" substring anywhere
        in the name — a filename-based rule missed it entirely (the spike's
        first, wrong, version)."""
        root = str(tmp_path)
        rel = _write(root, "egeria-quickstart-local.yaml", "services:\n  web:\n    image: foo\n")

        assert detectors._is_compose(root, rel) is True

    def test_a_yaml_file_with_no_services_key_is_not_a_compose_file(self, tmp_path):
        root = str(tmp_path)
        rel = _write(root, "config.yaml", "some: config\nother: value\n")

        assert detectors._is_compose(root, rel) is False


# ── finding 4: Dockerfile-without-manifest still yields a component ───────

class TestFinding4DockerfileWithoutManifest:
    def test_deployment_unit_with_no_manifest_becomes_a_component(self, tmp_path):
        root = str(tmp_path)
        _write(root, "handler/Dockerfile", "FROM python:3.12\nCMD [\"python\", \"app.py\"]\n")
        _write(root, "handler/app.py", "print('hi')\n")
        files = ["handler/Dockerfile", "handler/app.py"]

        components, evidence, notes = detectors.build_components(root, files)

        assert len(components) == 1
        comp = components[0]
        assert comp.identity.method == "deployment-unit"
        assert comp.type == "Long Running Daemon"

    def test_a_directory_of_only_dockerfiles_is_not_a_component(self, tmp_path):
        """A build-context directory with no first-party code alongside the
        Dockerfile is reported as a build context, not a component."""
        root = str(tmp_path)
        _write(root, "buildctx/Dockerfile", "FROM alpine\n")
        files = ["buildctx/Dockerfile"]

        components, evidence, notes = detectors.build_components(root, files)

        assert components == []
        assert any("build context" in n for n in notes)


# ── finding 5: deployment context qualifies the slug — two copies stay two ─

class TestFinding5DeploymentContextQualifiesSlug:
    def test_two_identically_named_handlers_under_different_deployments_stay_distinct(self, tmp_path):
        root = str(tmp_path)
        files = []
        for deployment in ("egeria-quickstart", "egeria-freshstart"):
            _write(root, f"{deployment}/PyegeriaWebHandler/Dockerfile",
                   "FROM python:3.12\nCMD [\"python\", \"app.py\"]\n")
            _write(root, f"{deployment}/PyegeriaWebHandler/app.py", "print('hi')\n")
            # A compose file directly under the deployment's own root — real
            # egeria-workspaces layout — is what establishes the ENCLOSING
            # deployment unit that qualifies the nested Dockerfile unit's
            # slug (§8.2). Without it, neither Dockerfile unit has a
            # strictly-containing unit and both slug to the same bare
            # "PyegeriaWebHandler", which is exactly the bug finding 5 fixed.
            _write(root, f"{deployment}/{deployment}-local.yaml",
                   f"services:\n  web:\n    build: ./PyegeriaWebHandler\n")
            files += [
                f"{deployment}/PyegeriaWebHandler/Dockerfile", f"{deployment}/PyegeriaWebHandler/app.py",
                f"{deployment}/{deployment}-local.yaml",
            ]

        components, evidence, notes = detectors.build_components(root, files)
        components = [c for c in components if c.type == "Long Running Daemon"]

        slugs = sorted(c.slug for c in components)
        assert slugs == ["egeria-freshstart::PyegeriaWebHandler", "egeria-quickstart::PyegeriaWebHandler"]
        assert len(components) == 2   # not collapsed into one by an unqualified slug


# ── finding 9: container_name preferred over the service key ──────────────

class TestFinding9ContainerNamePreferred:
    def test_container_name_wins_over_the_internal_service_key(self, tmp_path):
        root = str(tmp_path)
        rel = _write(root, "compose.yaml", (
            "services:\n"
            "  apache-web:\n"
            "    container_name: quickstart-web-server\n"
            "    build: .\n"
        ))

        out = detectors.compose_services(root, rel)

        assert len(out) == 1
        key, name, _line = out[0]
        assert key == "apache-web"
        assert name == "quickstart-web-server"

    def test_service_with_no_container_name_falls_back_to_the_key(self, tmp_path):
        root = str(tmp_path)
        rel = _write(root, "compose.yaml", "services:\n  kafka:\n    image: kafka\n")

        out = detectors.compose_services(root, rel)

        assert out == [("kafka", "kafka", 2)]


# ── finding 11: layered compose (base + override) merges across files ─────

class TestFinding11LayeredComposeMerges:
    def test_container_name_from_an_override_file_is_not_lost(self, tmp_path):
        root = str(tmp_path)
        _write(root, "deploy/base.yaml", "services:\n  apache-web:\n    build: .\n")
        _write(root, "deploy/override.yaml", "services:\n  apache-web:\n    container_name: quickstart-web-server\n")
        files = ["deploy/base.yaml", "deploy/override.yaml"]

        components, evidence, notes = detectors.build_components(root, files)

        names = sorted(c.name for c in components)
        assert names == ["quickstart-web-server"]     # merged into ONE component
        assert not any(c.name == "apache-web" for c in components)


# ── §3a: tracked node_modules is excluded from first-party ────────────────

class TestSection3aVendorExclusion:
    def test_tracked_node_modules_is_excluded(self, tmp_path):
        root = str(tmp_path)
        _write(root, "node_modules/leftpad/index.js", "module.exports = {};\n")
        _write(root, "src/app.py", "print('hi')\n")
        _git_init(root)

        census = exclusion.scan(root)

        assert census.tracked_by_git is True
        assert "src/app.py" in census.first_party
        assert not any(f.startswith("node_modules/") for f in census.first_party)
        assert census.excluded_by_rule["node_modules"] == 1


# ── finding 37: per-file import resolution, own-copy-first ────────────────

class TestFinding37PerFileImportResolution:
    def test_sibling_import_resolves_within_its_own_copy_not_a_duplicate_elsewhere(self, tmp_path):
        root = str(tmp_path)
        for deployment, marker in (("egeria-quickstart", "QUICK"), ("egeria-freshstart", "FRESH")):
            _write(root, f"{deployment}/PyegeriaWebHandler/pyproject.toml",
                   f'[project]\nname = "{deployment}-handler"\n')
            _write(root, f"{deployment}/PyegeriaWebHandler/common.py", f"MARKER = '{marker}'\n")
            _write(root, f"{deployment}/PyegeriaWebHandler/handler.py", "from common import MARKER\n")
        files = [
            "egeria-quickstart/PyegeriaWebHandler/pyproject.toml",
            "egeria-quickstart/PyegeriaWebHandler/common.py",
            "egeria-quickstart/PyegeriaWebHandler/handler.py",
            "egeria-freshstart/PyegeriaWebHandler/pyproject.toml",
            "egeria-freshstart/PyegeriaWebHandler/common.py",
            "egeria-freshstart/PyegeriaWebHandler/handler.py",
        ]

        graph = imports.build_graph(root, files)
        edges = {(e["source"], e["target"]) for e in graph["edges"]}

        assert ("egeria-quickstart/PyegeriaWebHandler/handler.py",
                "egeria-quickstart/PyegeriaWebHandler/common.py") in edges
        assert ("egeria-freshstart/PyegeriaWebHandler/handler.py",
                "egeria-freshstart/PyegeriaWebHandler/common.py") in edges
        # The bug: quickstart's handler resolving into freshstart's common.py (or vice versa).
        assert ("egeria-quickstart/PyegeriaWebHandler/handler.py",
                "egeria-freshstart/PyegeriaWebHandler/common.py") not in edges
        assert ("egeria-freshstart/PyegeriaWebHandler/handler.py",
                "egeria-quickstart/PyegeriaWebHandler/common.py") not in edges

    def test_roots_for_file_orders_the_importing_files_own_root_first(self):
        roots = ["egeria-freshstart/PyegeriaWebHandler", "egeria-quickstart/PyegeriaWebHandler", "."]
        ordered = imports.roots_for_file("egeria-quickstart/PyegeriaWebHandler/handler.py", roots)
        assert ordered[0] == "egeria-quickstart/PyegeriaWebHandler"


# ── finding 34: coupling shape classification (cohesive / connective / merge) ─

class TestFinding34CouplingShapes:
    def test_high_internal_ratio_is_cohesive(self):
        shape, confidence, _why = coupling.classify_subtree(internal=10, fan_in={}, fan_out={"other": 1})
        assert shape == "cohesive"

    def test_low_cohesion_with_dispersed_fan_in_is_connective_library(self):
        # A shared-library shape: almost no internal edges, fan-in spread
        # across many neighbours (README finding 34's "Core"/"Observability" case).
        fan_in = {f"n{i}": 5 for i in range(10)}
        shape, _confidence, _why = coupling.classify_subtree(internal=1, fan_in=fan_in, fan_out={})
        assert shape == "connective-library"

    def test_low_cohesion_concentrated_on_one_neighbour_is_merge_candidate(self):
        shape, confidence, _why = coupling.classify_subtree(internal=0, fan_in={}, fan_out={"owner": 10})
        assert shape == "merge-candidate"
        assert confidence == 0


# ── finding 44: the residue rule — an unproposed nested bucket is adopted ──

class TestFinding44ResidueRule:
    def test_unproposed_nested_bucket_is_adopted_by_its_parent(self, tmp_path):
        root = str(tmp_path)
        # scripts/ has a manifest at the root; scripts/tool_a.py and
        # scripts/subtool/*.py never import each other, so import cohesion
        # proposes nothing for "scripts/subtool" — the residue rule should
        # still fold it into "scripts" rather than leaving it unowned.
        _write(root, "pyproject.toml", '[project]\nname = "root-pkg"\n')
        _write(root, "scripts/tool_a.py", "X = 1\n")
        _write(root, "scripts/tool_b.py", "Y = 2\n")
        _write(root, "scripts/subtool/helper.py", "Z = 3\n")
        _write(root, "scripts/subtool/other.py", "W = 4\n")
        files = [
            "pyproject.toml", "scripts/tool_a.py", "scripts/tool_b.py",
            "scripts/subtool/helper.py", "scripts/subtool/other.py",
        ]
        # Give "scripts" (one segment) cohesion by having its two files
        # import each other, so it clears COHESIVE_BAR and gets proposed —
        # "scripts/subtool" gets no import edges at all, so nothing proposes it.
        _write(root, "scripts/tool_a.py", "from scripts.tool_b import Y\n")

        edges = [{"source": "scripts/tool_a.py", "target": "scripts/tool_b.py", "weight": 5}]
        components, _evidence, notes = coupling.propose(set(files), ["."], edges)

        scripts_comp = next((c for c in components if c.identity.value == "scripts"), None)
        assert scripts_comp is not None, "expected 'scripts' to be proposed as cohesive"
        assert "scripts/subtool/**" in scripts_comp.files
        assert any("adopted unproposed subtree" in n for n in notes)
