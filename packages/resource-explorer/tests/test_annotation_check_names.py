"""Every annotation carries a stable identity, and no two collide.

The qualifiedName an annotation publishes under is built from `check_name`
(+ `item_key`). Two failures are possible and neither announces itself:

- **A missing check_name** falls back to the enumeration index, which is not
  stable across runs — the defect the whole scheme exists to remove. A new
  surveyor added without one silently rejoins the old behaviour.
- **A colliding qualifiedName** loses an element on publish: Egeria rejects
  the duplicate, apply_element adopts the existing GUID, and the run reports
  success having written one where two were produced.

`assert_unique_qualified_names` catches the second at publish time, but that
is a broken publish. These tests catch both at edit time.
"""
from __future__ import annotations

import ast
import collections
import itertools
import pathlib

import pytest

SURVEYORS = pathlib.Path(__file__).parent.parent / "resource_explorer" / "surveyors"

ANNOTATION_CTORS = {
    "Annotation", "ClassificationAnnotation", "RequestForActionAnnotation",
    "ResourceMeasureAnnotation", "QualityScoreAnnotation",
    "SchemaAnalysisAnnotation", "DataClassAnnotation", "RelationshipAnnotation",
}

#: FS and DB surveying is deferred until the repo path is finished (2026-09-02),
#: so their annotation sites are deliberately not migrated yet. Removing a name
#: from here is how that work gets picked up — the test then demands it.
DEFERRED = {
    "database/database_surveyor.py",
    "filesystem/egeria_filesystem_surveyor.py",
}

#: (file, check_name) pairs where several annotation sites deliberately share
#: one name because their branches are mutually exclusive — a check reporting
#: "measured" or "could not measure" is ONE check with two outcomes, and giving
#: the outcomes different names would make a check unfollowable exactly when it
#: starts failing.
#:
#: Each was verified when added: 24 of the 26 by structural analysis (different
#: branches of one if/else or try/except), and two by reading, because the
#: structure does not show it —
#:   file_structure.code_volume: separated by an early `return`, not a branch.
#:   secret_scan.scan_summary:   three sites in three different methods, each
#:                               call site immediately followed by `return`.
#:
#: A pair NOT listed here fails the test. That is the point: adding one should
#: cost a deliberate check that the branches really cannot both run.
KNOWN_EXCLUSIVE = {
    ("sub_surveyors/arch_lens.py", "architecture_doc_lens"),
    ("sub_surveyors/arch_recovery_detect.py", "architecture_recovery"),
    ("sub_surveyors/arch_summary.py", "architecture_summary"),
    ("sub_surveyors/chaoss_metrics.py", "chaoss_metrics"),
    ("sub_surveyors/community_support.py", "community_support"),
    ("sub_surveyors/cve_scan.py", "cve_scan"),
    ("sub_surveyors/data_profiler.py", "data_profiling"),
    ("sub_surveyors/documentation.py", "api_docstring_coverage"),
    ("sub_surveyors/file_inventory.py", "file_inventory"),
    ("sub_surveyors/file_structure.py", "code_volume"),
    ("sub_surveyors/file_structure.py", "language_breakdown"),
    ("sub_surveyors/git_statistics.py", "git_statistics"),
    ("sub_surveyors/homepage.py", "homepage"),
    ("sub_surveyors/interface_surface.py", "interface_surface"),
    ("sub_surveyors/manifest_parse.py", "ci_workflow_manifest"),
    ("sub_surveyors/manifest_parse.py", "dependency_manifest"),
    ("sub_surveyors/manifest_parse.py", "repo_conventions_manifest"),
    ("sub_surveyors/manifest_parse.py", "supply_chain_manifest"),
    ("sub_surveyors/rag_ingestion.py", "rag_ingestion"),
    ("sub_surveyors/secret_scan.py", "scan_summary"),
    ("sub_surveyors/security_hygiene.py", "ci_config"),
    ("sub_surveyors/security_hygiene.py", "license"),
    ("sub_surveyors/security_hygiene.py", "security_policy"),
    ("sub_surveyors/sla_content.py", "sla_content"),
    ("sub_surveyors/sub_resource_survey.py", "sub_resource_survey"),
    ("sub_surveyors/telemetry_scan.py", "telemetry_scan"),
}


def _alias_names(tree):
    """Names bound to an annotation class rather than called directly.

    cve_scan picks its class at runtime —
        annotation = RequestForActionAnnotation if findings else ResourceMeasure...
        out.append(annotation(...))
    — so a scan matching only literal constructor names reports it as absent.
    That is exactly how this check first returned "118/118 named" while a real
    survey found an unnamed annotation: the constructor reached the call
    through a variable. Resolving the alias is the difference between the scan
    checking the code and the scan checking the spelling.
    """
    aliases = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not targets:
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Name) and sub.id in ANNOTATION_CTORS:
                aliases.update(targets)
    return aliases


def _sites():
    """(relative path, lineno, ctor, keyword names) for every annotation built
    under surveyors/, excluding the deferred FS/DB path."""
    for f in sorted(SURVEYORS.rglob("*.py")):
        rel = str(f.relative_to(SURVEYORS))
        if rel in DEFERRED:
            continue
        tree = ast.parse(f.read_text())
        callable_names = ANNOTATION_CTORS | _alias_names(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in callable_names):
                yield rel, node.lineno, node.func.id, {k.arg for k in node.keywords}


def test_every_annotation_declares_a_check_name():
    missing = [f"{rel}:{line} {ctor}" for rel, line, ctor, kws in _sites()
               if "check_name" not in kws]
    assert not missing, (
        "These annotations would publish under their position in the run, which "
        "is not stable between runs:\n  " + "\n  ".join(missing))


def test_there_are_annotations_to_check():
    """Guards the guard: an import error or a moved directory would empty the
    scan and make every test above pass by finding nothing."""
    assert sum(1 for _ in _sites()) > 100


def test_shared_check_names_are_declared_mutually_exclusive():
    by_name = collections.defaultdict(list)
    for rel, line, _ctor, kws in _sites():
        if "check_name" in kws and "item_key" not in kws:
            by_name[(rel, line)] = None
    # re-walk to capture the literal names (ast keyword values, not just arg names)
    shared = collections.defaultdict(list)
    for f in sorted(SURVEYORS.rglob("*.py")):
        rel = str(f.relative_to(SURVEYORS))
        if rel in DEFERRED:
            continue
        for node in ast.walk(ast.parse(f.read_text())):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ANNOTATION_CTORS):
                continue
            kw = {k.arg: k.value for k in node.keywords}
            if "check_name" not in kw or "item_key" in kw:
                continue
            name = kw["check_name"]
            if isinstance(name, ast.Constant):        # a dynamic name varies per item
                shared[(rel, name.value)].append(node.lineno)

    undeclared = {k: v for k, v in shared.items()
                  if len(v) > 1 and k not in KNOWN_EXCLUSIVE}
    assert not undeclared, (
        "These sites share a check_name with no item_key, so they publish the "
        "same qualifiedName if both run in one survey. Either give them an "
        "item_key, or verify the branches cannot both execute and add them to "
        "KNOWN_EXCLUSIVE:\n  "
        + "\n  ".join(f"{r}: {n} at lines {sorted(ls)}" for (r, n), ls in undeclared.items()))


def test_the_exclusivity_allowlist_has_no_stale_entries():
    """A name left in the allowlist after its second site is deleted would
    silently permit a future collision under that name."""
    live = collections.defaultdict(list)
    for f in sorted(SURVEYORS.rglob("*.py")):
        rel = str(f.relative_to(SURVEYORS))
        if rel in DEFERRED:
            continue
        for node in ast.walk(ast.parse(f.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ANNOTATION_CTORS):
                kw = {k.arg: k.value for k in node.keywords}
                n = kw.get("check_name")
                if isinstance(n, ast.Constant) and "item_key" not in kw:
                    live[(rel, n.value)].append(node.lineno)
    stale = [k for k in KNOWN_EXCLUSIVE if len(live.get(k, [])) < 2]
    assert not stale, f"KNOWN_EXCLUSIVE entries that no longer share a name: {stale}"


def test_the_scan_resolves_a_class_reached_through_a_variable():
    """Known-positive for the scanner itself.

    cve_scan.py:403 calls its annotation class through a variable bound one
    line earlier. A scan matching only literal constructor names reports
    "every annotation is named" while that one is not — which is what happened:
    the static check said 118/118 and a real survey of `workshops` found an
    unnamed RequestForActionAnnotation from CveScan.

    If this site ever stops being seen, the whole file is checking spelling
    rather than code, and every other test here weakens silently.
    """
    aliased = [(rel, line) for rel, line, ctor, _ in _sites()
               if ctor not in ANNOTATION_CTORS]
    assert aliased, (
        "The scan no longer resolves any variable-bound annotation class. "
        "Either the pattern was removed from the code (check cve_scan.py) or "
        "_alias_names() stopped working — the second is the dangerous one.")
