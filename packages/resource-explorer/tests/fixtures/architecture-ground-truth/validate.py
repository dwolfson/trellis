#!/usr/bin/env python3
"""Parse and validate a hand-written ground-truth partition (see README.md).

Two jobs: prove the markdown format is machine-readable (score.py will consume
the same parse), and catch the mistakes that are easy to make by hand — an
invented component type, a glob matching nothing, a blueprint naming a component
that isn't defined.

    python3 validate.py trellis.md [--root /path/to/checkout]

Exit code is non-zero if any error is found. Warnings do not fail.
"""
from __future__ import annotations

import argparse
import glob as globlib
import os
import re
import subprocess
import sys

# Three vocabularies, one per perspective — design doc §4.2. They are NOT
# interchangeable and must not be merged: `Application` is a deployed capability
# and `Software Service` is a designed component, the same system seen from two
# layers, joined by ImplementedBy.
#
# An earlier version of this validator enforced SolutionComponentType against
# every file, which rejected the entire (correct) deployment-perspective ground
# truth for egeria-workspaces. The validator was encoding the single-perspective
# model the design has since abandoned.

# Logical — SolutionComponentType.java refdata enum, closed at 13 (§3.1)
LOGICAL_TYPES = {
    "Automated Action", "Long Running Daemon", "Multi-Step Process",
    "Third Party Process", "Manual Process", "Data Storage", "Software Service",
    "Software Library", "User Interface", "Console Command", "Data Distribution",
    "Publishing", "Insight Model",
}

# Deployment — Area 0 SoftwareCapability subtypes (open; extend as Egeria does)
DEPLOYMENT_TYPES = {
    "SoftwareCapability", "Application", "APIManager", "EventBroker", "DataManager",
    "DatabaseManager", "FileManager", "FileSystem", "ContentCollectionManager",
    "SoftwareService", "UserAuthenticationManager", "ReportingEngine",
    "AnalyticsEngine", "WorkflowEngine", "InventoryCatalog", "MasterDataManager",
    "NetworkGateway", "CloudPlatform", "CloudTenant", "SoftwareArchive",
    "DeployedSoftwareComponent", "DataProcessingEngine",
}

# Physical / dev — Area 0 model 0280 Software Development Assets
PHYSICAL_TYPES = {
    "SourceCodeFile", "BuildInstructionFile", "ExecutableFile", "ScriptFile",
    "PropertiesFile", "YAMLFile", "SourceControlLibrary", "SoftwareLibrary",
}

VOCABULARIES = {
    "logical": LOGICAL_TYPES,
    "deployment": DEPLOYMENT_TYPES,
    "physical": PHYSICAL_TYPES,
    "dev": PHYSICAL_TYPES,
}

# Only perspectives whose components are defined by code they own need file
# globs. A deployment component is often a third-party image with no
# first-party files at all (kafka, postgres, kroki) — demanding globs there
# would force either a fabricated path or a missing component.
FILES_REQUIRED = {"logical", "physical", "dev"}

PLACEHOLDER = re.compile(r"<[^>]+>")
BULLET = re.compile(r"^\s*-\s+(?:\*\*(?P<label>[^*]+):\*\*\s*)?(?P<value>.*)$")
CODE_SPAN = re.compile(r"`([^`]+)`")


def parse(path: str) -> dict:
    """Markdown → {meta, blueprints, components, unassigned_ok, excluded}."""
    doc = {"meta": {}, "blueprints": {}, "components": {},
           "unassigned_ok": [], "excluded": []}
    section = None          # 'blueprints' | 'components' | 'unassigned' | 'excluded'
    current = None          # current h3 name within a section
    attr = None             # current **Label:** being continued by sub-bullets

    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if line.lstrip().startswith(">"):
            continue                                    # blockquote = guidance

        if m := re.match(r"^\*\*(?P<k>[^*]+):\*\*\s*(?P<v>.*)$", line):
            doc["meta"][m.group("k").strip().lower()] = m.group("v").strip()
            continue

        if m := re.match(r"^##\s+(?!#)(?P<t>.+)$", line):
            title = m.group("t").strip().lower()
            # Any section whose title contains "component" collects components,
            # so a file may group them (e.g. "Optional runtime add-ons" vs the
            # main set) without the parser losing half the partition.
            # Deliberately stricter than `"component" in title`: a prose heading such as
            # "Sub-structure — which components can be nested at all" matched that and turned
            # narrative subheadings into phantom components.
            section = ("blueprints" if title.startswith("blueprint")
                       else "components" if (title.startswith("component")
                                             or title.startswith("assignment")
                                             or "add-on" in title)
                       else "unassigned" if title.startswith("unassigned")
                       else "excluded" if title.startswith("excluded")
                       else None)
            current = attr = None
            continue

        if m := re.match(r"^###\s+(?P<t>.+)$", line):
            current, attr = m.group("t").strip(), None
            if section == "blueprints":
                doc["blueprints"].setdefault(current, [])
            elif section == "components":
                doc["components"].setdefault(
                    current, {"type": None, "files": [], "identity": "", "notes": ""})
            continue

        if not (m := BULLET.match(line)):
            continue
        label, value = m.group("label"), m.group("value").strip()
        indented = len(raw) - len(raw.lstrip()) >= 2

        if section == "blueprints" and current:
            doc["blueprints"][current].append(value)
        elif section == "components" and current:
            comp = doc["components"][current]
            if label:
                attr = label.strip().lower()
                if attr == "type":
                    comp["type"] = value
                elif attr == "files":
                    if value:
                        comp["files"].append(value)
                else:
                    # Generic capture — identity/notes plus anything not yet
                    # named here (provenance, per-component perspective, …).
                    # score.py reads `provenance` off this without a second
                    # parser (README.md: "score.py consumes the same parse").
                    comp[attr] = value
            elif indented and attr:
                # An indented bullet continues whatever label opened above it. This used to be
                # hardcoded to `files`, so `- **Sub-components:**` followed by a list silently
                # captured nothing — the revision file recorded a decision no reader could see.
                if attr == "files":
                    comp["files"].append(value)
                else:
                    cur = comp.get(attr)
                    comp[attr] = (cur + [value]) if isinstance(cur, list) else (
                        [value] if not cur else [cur, value])
        elif section in ("unassigned", "excluded") and not label:
            doc["unassigned_ok" if section == "unassigned" else "excluded"].append(value)

    return doc


def unquote(v: str) -> str:
    m = CODE_SPAN.search(v)
    return (m.group(1) if m else v).strip()


def tracked_files(root: str) -> set[str] | None:
    """Files git tracks, relative to root — or None outside a git checkout.

    Scoring MUST use the same file set the detector sees, and the detector's
    exclusion pass uses `git ls-files`. Globbing the filesystem instead counts
    untracked build output: `frontend-build/**` matches 6 tracked files and
    1440 on disk, because an untracked node_modules sits under it. Coverage
    computed the wrong way would have been off by 200x for that component.
    """
    try:
        proc = subprocess.run(["git", "-C", root, "ls-files", "-z"],
                              capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return {p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p}


def expand(pattern: str, root: str, tracked: set[str] | None) -> set[str]:
    """Files a glob matches, restricted to tracked files where git is available."""
    p = unquote(pattern)
    if p.endswith("/**"):
        p = p[:-3] + "/**/*"
    hits = {os.path.relpath(h, root)
            for h in globlib.glob(os.path.join(root, p), recursive=True)
            if os.path.isfile(h)}
    return hits & tracked if tracked is not None else hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--root", help="checkout root; defaults to the Checkout: field")
    args = ap.parse_args()

    doc = parse(args.file)
    errors: list[str] = []
    warnings: list[str] = []
    tracked: set[str] | None = None

    root = args.root or unquote(doc["meta"].get("checkout", ""))
    if root and not os.path.isdir(root):
        warnings.append(f"checkout path does not exist, skipping glob checks: {root}")
        root = ""
    if root:
        tracked = tracked_files(root)
        # A Scope: line narrows the denominator. Without it, coverage on a
        # monorepo is meaningless — trellis ground truth deliberately excludes
        # packages/egeria-advisor (879 files), so whole-repo coverage reads 15%
        # when in-scope coverage is 50%. Scoring must use the same scope on both
        # sides or the numbers describe nothing.
        scope = doc["meta"].get("scope", "")
        if tracked is not None and scope:
            prefixes = [unquote(x).rstrip("/") for x in CODE_SPAN.findall(scope)] \
                       or [x.strip().rstrip("/") for x in scope.split(",") if x.strip()]
            if prefixes:
                tracked = {f for f in tracked
                           if any(f == p or f.startswith(p + "/") for p in prefixes)}
        if tracked is None:
            warnings.append("not a git checkout — counting files on disk, which may "
                            "include untracked build output the detector never sees")

    for field in ("written by", "written at"):
        v = doc["meta"].get(field, "")
        if not v or PLACEHOLDER.search(v):
            errors.append(f"metadata '{field}' is still a placeholder — "
                          f"pre-registration needs a real name and date")

    perspective = doc["meta"].get("perspective", "logical").strip().lower()
    valid_types = VOCABULARIES.get(perspective)
    if valid_types is None:
        errors.append(f"unknown Perspective {perspective!r} — expected one of "
                      f"{', '.join(sorted(VOCABULARIES))}")
        valid_types = LOGICAL_TYPES
    files_required = perspective in FILES_REQUIRED

    real = {n: c for n, c in doc["components"].items() if not PLACEHOLDER.search(n)}
    if not real:
        errors.append("no components defined (only template placeholders)")

    for name, comp in real.items():
        if not comp["type"]:
            errors.append(f"component {name!r}: no **Type:**")
        elif comp["type"] not in valid_types:
            errors.append(f"component {name!r}: type {comp['type']!r} is not in the "
                          f"{perspective} vocabulary (§4.2)")
        files = [f for f in comp["files"] if not PLACEHOLDER.search(f)]
        if not files and files_required:
            errors.append(f"component {name!r}: no file globs")
        for g in files:
            if root and not expand(g, root, tracked):
                errors.append(f"component {name!r}: glob {unquote(g)!r} matches no "
                              f"{'tracked ' if tracked is not None else ''}files")

    for bp, members in doc["blueprints"].items():
        if PLACEHOLDER.search(bp):
            continue
        for member in members:
            if PLACEHOLDER.search(member):
                continue
            if member not in doc["components"]:
                errors.append(f"blueprint {bp!r} lists {member!r}, which has no "
                              f"### section under ## Components")
        if not [m for m in members if not PLACEHOLDER.search(m)]:
            warnings.append(f"blueprint {bp!r} has no components")

    # Overlapping globs are legal (a file can be in two components) but usually a slip.
    seen: dict[str, str] = {}
    assigned = 0
    if root:
        for name, comp in real.items():
            for g in comp["files"]:
                if PLACEHOLDER.search(g):
                    continue
                for hit in expand(g, root, tracked):
                    if hit in seen and seen[hit] != name:
                        warnings.append(f"file claimed by both {seen[hit]!r} and {name!r}: {hit}")
                    seen[hit] = name
        assigned = len(seen)

    print(f"{args.file} [{perspective}]: {len(real)} components, "
          f"{len(doc['blueprints'])} blueprints, "
          f"{len(doc['unassigned_ok'])} unassigned-ok, {len(doc['excluded'])} excluded")
    if root and tracked is not None:
        in_scope = len(tracked)
        with_files = sum(1 for c in real.values()
                         if [f for f in c["files"] if not PLACEHOLDER.search(f)])
        if files_required:
            pct = 100 * assigned / in_scope if in_scope else 0
            scoped = " in scope" if doc["meta"].get("scope") else ""
            print(f"  coverage: {assigned}/{in_scope} tracked files{scoped} assigned "
                  f"to a component ({pct:.1f}%)")
        else:
            # File-partition scoring does not apply here (plan §5a): only
            # component-set agreement does.
            print(f"  perspective={perspective}: file coverage N/A — "
                  f"{with_files}/{len(real)} components own first-party files")
    for w in dict.fromkeys(warnings):
        print(f"  warn:  {w}")
    for e in errors:
        print(f"  ERROR: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
