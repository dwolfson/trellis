"""Gradle dependency parsing — deliberately partial, and honest about it.

Before 2026-08-31 `dependency_parser.py` read six manifest kinds and none of them
was Gradle, so Egeria — 239 `build.gradle` files — had **zero** dependency rows.
`dependency_analysis` had nothing to report and `cve_scan` could never run,
which capped `security_summary` at 7 of 8 inputs for the project this tool is
built around.

`build.gradle` is Groovy (or Kotlin) *code*, not a data format, so this reads the
literal forms and cannot resolve version catalogs, `ext` properties or plugins.
That is acceptable only because of what it does with what it cannot resolve, and
that is what these tests pin: an unresolvable version becomes **empty**, never a
guess and never the raw variable, and internal module references are **excluded**
rather than recorded as packages that exist in no registry.
"""
from __future__ import annotations

import textwrap

import pytest

from resource_explorer.ingestion.dependency_parser import DependencyParser


def _parse(tmp_path, body: str, name: str = "build.gradle"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body))
    return DependencyParser()._parse_gradle(p)


def test_a_pinned_coordinate_keeps_its_version(tmp_path):
    got = _parse(tmp_path, """
        dependencies {
            implementation 'org.slf4j:slf4j-api:2.0.13'
        }
    """)
    assert len(got) == 1, got
    assert got[0]["dep_name"] == "org.slf4j:slf4j-api"
    assert got[0]["dep_version"] == "2.0.13"
    assert got[0]["ecosystem"] == "java"


def test_a_coordinate_with_no_version_is_recorded_not_dropped(tmp_path):
    """Egeria's real shape: versions come from a BOM, so `group:artifact` is the
    norm rather than an error. Dropping these would leave the project with zero
    dependencies, which is what it had before this parser existed.

    `cve_scan` classifies an empty version as "no pinned version to query" —
    unqueryable, explicitly not clean — so recording them turns "we never looked"
    into "we looked and cannot answer without the BOM".
    """
    got = _parse(tmp_path, """
        dependencies {
            testImplementation 'org.springframework.boot:spring-boot'
        }
    """)
    assert len(got) == 1, got
    assert got[0]["dep_name"] == "org.springframework.boot:spring-boot"
    assert got[0]["dep_version"] == ""


def test_an_unresolved_variable_is_not_recorded_as_a_version(tmp_path):
    """`${jacksonVersion}` is a Groovy variable, not a version.

    Passing it through would put a string no registry can match into
    `dep_version`; `cve_scan` would then reject it as "a range or unparseable",
    which is a true statement about the wrong thing. Empty says what actually
    happened: declared here, resolved elsewhere.
    """
    got = _parse(tmp_path, """
        dependencies {
            implementation 'com.fasterxml.jackson.core:jackson-databind:${jacksonVersion}'
        }
    """)
    assert len(got) == 1, got
    assert got[0]["dep_name"] == "com.fasterxml.jackson.core:jackson-databind"
    assert got[0]["dep_version"] == "", (
        f"recorded {got[0]['dep_version']!r} as a version — it is an unresolved variable"
    )


def test_internal_project_references_are_not_dependencies(tmp_path):
    """`project(':x')` is a module of this build, not a package.

    Recording them would invent dependencies that exist in no registry, and every
    one would come back unmatched from a CVE lookup — noise indistinguishable
    from a clean result. Egeria's test modules are mostly these.
    """
    got = _parse(tmp_path, """
        dependencies {
            testImplementation project(':open-metadata-implementation:admin-services')
            implementation project(":frameworks:audit-log-framework")
            implementation 'org.slf4j:slf4j-api:2.0.13'
        }
    """)
    names = [d["dep_name"] for d in got]
    assert names == ["org.slf4j:slf4j-api"], names
    assert not any(n.startswith(":") for n in names)


def test_kotlin_dsl_parenthesised_form(tmp_path):
    got = _parse(tmp_path, """
        dependencies {
            implementation("org.jetbrains.kotlin:kotlin-stdlib:1.9.0")
            testImplementation("io.mockk:mockk")
        }
    """, name="build.gradle.kts")
    by = {d["dep_name"]: d for d in got}
    assert by["org.jetbrains.kotlin:kotlin-stdlib"]["dep_version"] == "1.9.0"
    assert by["io.mockk:mockk"]["dep_version"] == ""


def test_the_map_form(tmp_path):
    got = _parse(tmp_path, """
        dependencies {
            implementation group: 'commons-io', name: 'commons-io', version: '2.15.1'
            compileOnly group: 'org.projectlombok', name: 'lombok'
        }
    """)
    by = {d["dep_name"]: d for d in got}
    assert by["commons-io:commons-io"]["dep_version"] == "2.15.1"
    assert by["org.projectlombok:lombok"]["dep_version"] == ""


@pytest.mark.parametrize("config,expected", [
    ("implementation", "runtime"),
    ("api", "runtime"),
    ("runtimeOnly", "runtime"),
    # compileOnly is on the compile classpath and absent at runtime, so calling
    # it runtime would overstate what actually ships.
    ("compileOnly", "dev"),
    ("annotationProcessor", "dev"),
    ("testImplementation", "test"),
    ("testRuntimeOnly", "test"),
])
def test_configuration_maps_to_dep_type(tmp_path, config, expected):
    got = _parse(tmp_path, f"""
        dependencies {{
            {config} 'g:a:1.0'
        }}
    """)
    assert len(got) == 1, got
    assert got[0]["dep_type"] == expected


def test_comments_and_unrelated_lines_are_ignored(tmp_path):
    got = _parse(tmp_path, """
        plugins { id 'java' }
        // implementation 'commented:out:1.0'
        description = 'not a dependency'
        dependencies {
            implementation 'real:dep:1.0'  // trailing comment
        }
    """)
    assert [d["dep_name"] for d in got] == ["real:dep"], got


def test_the_real_egeria_checkout_yields_dependencies(tmp_path):
    """Non-vacuity against the actual project this was written for.

    Skipped rather than failed when the checkout is absent — but when it is
    present, zero results means the parser has regressed to the state that
    motivated it.
    """
    from pathlib import Path
    root = Path("/Users/dwolfson/localGit/egeria-v6/egeria")
    if not (root / "build.gradle").exists():  # pragma: no cover
        pytest.skip("no local egeria checkout")

    deps = [d for d in DependencyParser().parse(root, "egeria_git")
            if d["source_file"].startswith("build.gradle")]
    assert len(deps) > 50, f"only {len(deps)} parsed from 229 build.gradle files"
    assert all(not d["dep_name"].startswith(":") for d in deps), "project() refs leaked in"
    assert all("$" not in d["dep_version"] for d in deps), "an unresolved variable reached dep_version"
    assert all(d["ecosystem"] == "java" for d in deps)
