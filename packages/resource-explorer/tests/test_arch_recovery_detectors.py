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


# ── Java import extraction — the adversarial-target extension ─────────────
#
# `odpi/egeria` (231 Gradle modules) has zero tracked .py files, so it was
# unreachable by coupling until imports.py grew a Java extractor/resolver
# (README's Java section: "does this generalise beyond a well-factored
# Python monorepo?" was unanswerable without this). Fixture trees mirror the
# Python finding-37 tests above: small, synthetic, built in tmp_path.

def _java(root, rel, package, body=""):
    """Write one first-party .java file with a `package` declaration —
    java_fqcn_index needs it to build fqcn -> file."""
    return _write(root, rel, f"package {package};\n\n{body}\n")


class TestJavaImportPlainClass:
    def test_plain_class_import_resolves_to_the_declaring_file(self, tmp_path):
        root = str(tmp_path)
        _java(root, "modA/src/main/java/com/example/foo/Foo.java", "com.example.foo",
              "import com.example.bar.Bar;\npublic class Foo { Bar b; }")
        _java(root, "modA/src/main/java/com/example/bar/Bar.java", "com.example.bar",
              "public class Bar {}")
        files = [
            "modA/src/main/java/com/example/foo/Foo.java",
            "modA/src/main/java/com/example/bar/Bar.java",
        ]

        graph = imports.build_graph(root, files)
        edges = {(e["source"], e["target"], e["kind"]) for e in graph["edges"]}

        assert ("modA/src/main/java/com/example/foo/Foo.java",
                "modA/src/main/java/com/example/bar/Bar.java", "class") in edges


class TestJavaImportStaticAndWildcard:
    def test_static_member_import_resolves_to_the_declaring_class_not_the_member(self, tmp_path):
        root = str(tmp_path)
        _java(root, "modA/src/main/java/com/example/Foo.java", "com.example",
              "import static com.example.Util.doThing;\npublic class Foo { { doThing(); } }")
        _java(root, "modA/src/main/java/com/example/Util.java", "com.example",
              "public class Util { public static void doThing() {} }")
        files = [
            "modA/src/main/java/com/example/Foo.java",
            "modA/src/main/java/com/example/Util.java",
        ]

        graph = imports.build_graph(root, files)
        edges = {(e["source"], e["target"], e["kind"]) for e in graph["edges"]}

        assert ("modA/src/main/java/com/example/Foo.java",
                "modA/src/main/java/com/example/Util.java", "static") in edges

    def test_class_wildcard_import_fans_out_to_every_top_level_type_in_the_package(self, tmp_path):
        root = str(tmp_path)
        _java(root, "modA/src/main/java/com/example/Foo.java", "com.example",
              "import com.example.baz.*;\npublic class Foo {}")
        _java(root, "modA/src/main/java/com/example/baz/Qux.java", "com.example.baz", "public class Qux {}")
        _java(root, "modA/src/main/java/com/example/baz/Zed.java", "com.example.baz", "public class Zed {}")
        files = [
            "modA/src/main/java/com/example/Foo.java",
            "modA/src/main/java/com/example/baz/Qux.java",
            "modA/src/main/java/com/example/baz/Zed.java",
        ]

        graph = imports.build_graph(root, files)
        edges = {(e["source"], e["target"], e["kind"]) for e in graph["edges"]}

        assert ("modA/src/main/java/com/example/Foo.java",
                "modA/src/main/java/com/example/baz/Qux.java", "wildcard") in edges
        assert ("modA/src/main/java/com/example/Foo.java",
                "modA/src/main/java/com/example/baz/Zed.java", "wildcard") in edges

    def test_stdlib_import_is_external_not_a_silent_drop(self, tmp_path):
        root = str(tmp_path)
        _java(root, "modA/src/main/java/com/example/Foo.java", "com.example",
              "import java.util.List;\npublic class Foo { List x; }")
        files = ["modA/src/main/java/com/example/Foo.java"]

        graph = imports.build_graph(root, files)

        assert graph["edge_count"] == 0
        assert graph["unresolved_import_count"] == 1
        assert graph["external_by_file"] == {"modA/src/main/java/com/example/Foo.java": 1}


class TestJavaFinding37StyleModuleResolution:
    """Gradle's 231-module layout can declare the same fqcn twice (e.g. a
    same-named test fixture class in two modules) — the same duplicate-copy
    risk finding 37 found and fixed for Python's two PyegeriaWebHandler
    copies. A Java import must resolve within its own module first."""

    def test_duplicate_fqcn_across_two_modules_resolves_within_the_importing_module(self, tmp_path):
        root = str(tmp_path)
        for mod, marker in (("modA", "A"), ("modB", "B")):
            _write(root, f"{mod}/build.gradle", "// dummy\n")
            _java(root, f"{mod}/src/main/java/com/example/Shared.java", "com.example",
                  f"public class Shared {{ /* {marker} */ }}")
        _java(root, "modA/src/main/java/com/example/Foo.java", "com.example",
              "import com.example.Shared;\npublic class Foo { Shared s; }")
        files = [
            "modA/build.gradle", "modB/build.gradle",
            "modA/src/main/java/com/example/Shared.java",
            "modB/src/main/java/com/example/Shared.java",
            "modA/src/main/java/com/example/Foo.java",
        ]

        graph = imports.build_graph(root, files)
        edges = {(e["source"], e["target"]) for e in graph["edges"]}

        assert ("modA/src/main/java/com/example/Foo.java",
                "modA/src/main/java/com/example/Shared.java") in edges
        assert ("modA/src/main/java/com/example/Foo.java",
                "modB/src/main/java/com/example/Shared.java") not in edges

    def test_module_root_for_file_picks_the_nearest_enclosing_build_gradle(self):
        module_roots = {".", "modA", "modB"}
        assert imports.module_root_for_file("modA/src/main/java/com/example/Foo.java",
                                             module_roots) == "modA"


# ── finding 69/70: Go package structure ───────────────────────────────────

class TestFinding70GoSubsystems:
    """Finding 69: Prometheus scored 0/11 because three of the four proposers
    are Python/Java/npm-only, and manifest identity is structurally blind on a
    single-module Go repo — one `go.mod` spans the whole architecture. Finding
    70 added `go_subsystems()`; these regress its three rules."""

    def _repo(self, root):
        _write(root, "go.mod", "module github.com/acme/proj\n\ngo 1.22\n")
        _write(root, "main.go", "package main\n")                   # module root
        _write(root, "config/config.go", "package config\n")
        _write(root, "config/testdata/a.yml", "x: 1\n")
        _write(root, "scrape/manager.go", "package scrape\n")
        _write(root, "cmd/server/main.go", "package main\n")
        _write(root, "cmd/tool/main.go", "package main\n")
        _git_init(root)
        return {s["dir"]: s for s in detectors.go_subsystems(root, _tracked(root))}

    def test_top_level_directories_become_components(self, tmp_path):
        subs = self._repo(str(tmp_path))
        assert "config" in subs and "scrape" in subs
        assert subs["config"]["import_path"] == "github.com/acme/proj/config"

    def test_cmd_recurses_one_level_so_each_binary_is_its_own_component(self, tmp_path):
        """Go convention: every `cmd/X` is a separate binary. Collapsing them
        into one `cmd` component would merge unrelated programs."""
        subs = self._repo(str(tmp_path))
        assert "cmd/server" in subs and "cmd/tool" in subs
        assert "cmd" not in subs

    def test_files_at_the_module_root_are_not_a_component(self, tmp_path):
        """The module root is the whole module — the same 'workspace root is a
        container, not a component' rule the npm detector already applies."""
        subs = self._repo(str(tmp_path))
        assert "" not in subs and "." not in subs
        assert not any("main.go" == os.path.basename(f)
                       and "/" not in f for s in subs.values() for f in s["files"])

    def test_nested_module_wins_over_the_enclosing_one(self, tmp_path):
        """A directory owned by a deeper `go.mod` belongs to that module.
        Prometheus has six; only the root one spans the architecture."""
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "svc/svc.go", "package svc\n")
        _write(root, "tools/go.mod", "module github.com/acme/proj/tools\n")
        _write(root, "tools/gen/gen.go", "package gen\n")
        _git_init(root)
        subs = {s["dir"]: s for s in detectors.go_subsystems(root, _tracked(root))}
        assert subs["tools/gen"]["module"] == "github.com/acme/proj/tools"
        assert subs["tools/gen"]["import_path"] == "github.com/acme/proj/tools/gen"

    def test_no_go_mod_yields_no_components_rather_than_guessing(self, tmp_path):
        root = str(tmp_path)
        _write(root, "svc/svc.go", "package svc\n")
        _git_init(root)
        assert detectors.go_subsystems(root, _tracked(root)) == []


class TestFinding70GoImports:
    """Go resolution: an import path is absolute and module-qualified, so
    resolution needs neither Python's per-file search path nor Java's global
    type index — but a Go import names a *package*, so one import fans out to
    every file in that directory."""

    def test_first_party_import_resolves_to_every_file_in_the_package(self, tmp_path):
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "config/a.go", "package config\n")
        _write(root, "config/b.go", "package config\n")
        _write(root, "scrape/s.go",
               'package scrape\n\nimport (\n\t"fmt"\n\t"github.com/acme/proj/config"\n)\n')
        _git_init(root)
        graph = imports.build_graph(root, _tracked(root))

        assert graph["go_files_scanned"] == 3
        go_edges = [e for e in graph["edges"] if e["language"] == "go"]
        assert {e["target"] for e in go_edges} == {"config/a.go", "config/b.go"}

    def test_one_import_carries_total_weight_one_however_many_files(self, tmp_path):
        """Elsewhere weight means 'symbols crossing this edge'. A Go import
        names a whole package, so its share is split across the package's
        files — otherwise a 40-file package would outweigh a 2-file one purely
        on file count, and since every Go import is package-level the
        distortion would be universal rather than occasional."""
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        for n in "abcd":
            _write(root, f"big/{n}.go", "package big\n")
        _write(root, "one/x.go",
               'package one\n\nimport "github.com/acme/proj/big"\n')
        _git_init(root)
        graph = imports.build_graph(root, _tracked(root))

        total = sum(e["weight"] for e in graph["edges"] if e["language"] == "go")
        assert total == pytest.approx(1.0)

    def test_stdlib_and_third_party_are_external_not_edges(self, tmp_path):
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "a/a.go",
               'package a\n\nimport (\n\t"fmt"\n\t"github.com/other/lib"\n)\n')
        _git_init(root)
        graph = imports.build_graph(root, _tracked(root))

        assert [e for e in graph["edges"] if e["language"] == "go"] == []
        assert graph["unresolved_import_count"] == 2

    def test_aliased_and_blank_imports_are_kept(self, tmp_path):
        """A blank `_` import is a side-effect dependency — architecturally
        more interesting than a plain one, not less."""
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "reg/r.go", "package reg\n")
        _write(root, "app/app.go",
               'package app\n\nimport (\n\tcfg "github.com/acme/proj/reg"\n)\n')
        _write(root, "app2/app.go",
               'package app2\n\nimport (\n\t_ "github.com/acme/proj/reg"\n)\n')
        _git_init(root)
        graph = imports.build_graph(root, _tracked(root))

        kinds = {e["kind"] for e in graph["edges"] if e["language"] == "go"}
        assert kinds == {"alias", "blank"}


class TestFinding72GoContainerDirectories:
    """Finding 72: a directory is a Go package only if it holds `.go` files
    *directly*. `go_subsystems` originally hardcoded a `cmd/` carve-out, which
    collapsed Milvus's entire architecture into one `internal/**` component —
    `internal/` and `internal/distributed/` are both pure containers."""

    def test_a_directory_with_no_go_files_is_descended_past(self, tmp_path):
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "internal/proxy/p.go", "package proxy\n")
        _write(root, "internal/coord/c.go", "package coord\n")
        _git_init(root)
        subs = {s["dir"] for s in detectors.go_subsystems(root, _tracked(root))}

        assert subs == {"internal/proxy", "internal/coord"}
        assert "internal" not in subs

    def test_it_descends_more_than_one_level_when_needed(self, tmp_path):
        """`internal/distributed/proxy` — two container levels deep. A rule
        that recursed a fixed single level would stop at `internal/distributed`
        and merge every component's distributed wrapper into one."""
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "internal/distributed/proxy/p.go", "package proxy\n")
        _write(root, "internal/distributed/datanode/d.go", "package datanode\n")
        _git_init(root)
        subs = {s["dir"] for s in detectors.go_subsystems(root, _tracked(root))}

        assert subs == {"internal/distributed/proxy", "internal/distributed/datanode"}

    def test_a_package_owns_its_whole_subtree(self, tmp_path):
        """Once a directory IS a package, its child packages are its internals
        — Prometheus's `config/` owns `config/testdata/` and that is the match
        the ground truth expects."""
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "config/config.go", "package config\n")
        _write(root, "config/sub/s.go", "package sub\n")
        _git_init(root)
        subs = {s["dir"] for s in detectors.go_subsystems(root, _tracked(root))}

        assert subs == {"config"}

    def test_cmd_recursion_now_falls_out_of_the_general_rule(self, tmp_path):
        """The hardcoded `cmd/` carve-out is gone; `cmd/` holding no direct
        `.go` files gets the same treatment as any other container."""
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "cmd/server/main.go", "package main\n")
        _write(root, "cmd/tool/main.go", "package main\n")
        _git_init(root)
        subs = {s["dir"] for s in detectors.go_subsystems(root, _tracked(root))}

        assert subs == {"cmd/server", "cmd/tool"}


class TestFinding75NestedModuleRoots:
    """Finding 75: files directly at a module root are skipped as "the module
    is the whole repo" — true for the OUTERMOST module, wrong for a nested one.
    k8s's `staging/src/k8s.io/cloud-provider` carries its own go.mod, four .go
    files and eight metadata files; skipping them orphaned exactly those 12 and
    left the component at 107/119."""

    def test_a_nested_module_root_is_itself_a_component(self, tmp_path):
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "svc/s.go", "package svc\n")
        _write(root, "staging/lib/go.mod", "module k8s.io/lib\n")
        _write(root, "staging/lib/lib.go", "package lib\n")
        _write(root, "staging/lib/OWNERS", "owners\n")
        _write(root, "staging/lib/sub/s.go", "package sub\n")
        _git_init(root)
        subs = {s["dir"]: s for s in detectors.go_subsystems(root, _tracked(root))}

        assert "staging/lib" in subs
        assert subs["staging/lib"]["module"] == "k8s.io/lib"
        assert "staging/lib/lib.go" in subs["staging/lib"]["files"]

    def test_the_outermost_module_root_is_still_skipped(self, tmp_path):
        """Prometheus has `rules.go` at the repo root. Treating the outermost
        module root as a component would emit one `**` component claiming the
        entire repository."""
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "rules.go", "package proj\n")
        _write(root, "svc/s.go", "package svc\n")
        _git_init(root)
        subs = {s["dir"] for s in detectors.go_subsystems(root, _tracked(root))}

        assert subs == {"svc"}
        assert "" not in subs and "." not in subs


class TestFinding78EntryPointDetection:
    """Finding 78: a Go executable is a package declaring `package main`, not a
    directory containing a file named `main.go`. Kubernetes's entry points are
    `cmd/kube-scheduler/scheduler.go`, `cmd/kubelet/kubelet.go` and so on, so
    the filename test missed every component that mattered."""

    def test_entry_point_not_named_main_go_is_still_detected(self, tmp_path):
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "cmd/server/server.go", "package main\n\nfunc main() {}\n")
        _git_init(root)
        subs = {s["dir"]: s for s in detectors.go_subsystems(root, _tracked(root))}

        assert subs["cmd/server"]["has_main"] is True

    def test_a_library_package_is_not_an_entry_point(self, tmp_path):
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "lib/main.go", "package lib\n")   # named main.go, NOT package main
        _git_init(root)
        subs = {s["dir"]: s for s in detectors.go_subsystems(root, _tracked(root))}

        assert subs["lib"]["has_main"] is False

    def test_a_nested_package_main_does_not_type_the_parent(self, tmp_path):
        """Scanning the whole subtree typed `pkg/controlplane` as an executable
        because some nested test helper declares `package main`."""
        root = str(tmp_path)
        _write(root, "go.mod", "module github.com/acme/proj\n")
        _write(root, "pkg/lib/lib.go", "package lib\n")
        _write(root, "pkg/lib/testhelper/gen.go", "package main\n\nfunc main() {}\n")
        _git_init(root)
        subs = {s["dir"]: s for s in detectors.go_subsystems(root, _tracked(root))}

        assert subs["pkg/lib"]["has_main"] is False
