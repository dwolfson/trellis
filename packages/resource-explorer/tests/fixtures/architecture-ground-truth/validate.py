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

# docs/architecture-recovery-design.md §3.1 — SolutionComponentType.java
VALID_TYPES = {
    "Automated Action", "Long Running Daemon", "Multi-Step Process",
    "Third Party Process", "Manual Process", "Data Storage", "Software Service",
    "Software Library", "User Interface", "Console Command", "Data Distribution",
    "Publishing", "Insight Model",
}

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
            section = ("blueprints" if title.startswith("blueprint")
                       else "components" if title.startswith("component")
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
                elif attr in ("identity", "notes"):
                    comp[attr] = value
                elif attr == "files" and value:
                    comp["files"].append(value)
            elif indented and attr == "files":
                comp["files"].append(value)
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
        if tracked is None:
            warnings.append("not a git checkout — counting files on disk, which may "
                            "include untracked build output the detector never sees")

    for field in ("written by", "written at"):
        v = doc["meta"].get(field, "")
        if not v or PLACEHOLDER.search(v):
            errors.append(f"metadata '{field}' is still a placeholder — "
                          f"pre-registration needs a real name and date")

    real = {n: c for n, c in doc["components"].items() if not PLACEHOLDER.search(n)}
    if not real:
        errors.append("no components defined (only template placeholders)")

    for name, comp in real.items():
        if not comp["type"]:
            errors.append(f"component {name!r}: no **Type:**")
        elif comp["type"] not in VALID_TYPES:
            errors.append(f"component {name!r}: type {comp['type']!r} is not one of the 13 "
                          f"§3.1 values")
        files = [f for f in comp["files"] if not PLACEHOLDER.search(f)]
        if not files:
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

    print(f"{args.file}: {len(real)} components, {len(doc['blueprints'])} blueprints, "
          f"{len(doc['unassigned_ok'])} unassigned-ok, {len(doc['excluded'])} excluded")
    if root and tracked is not None:
        pct = 100 * assigned / len(tracked) if tracked else 0
        print(f"  coverage: {assigned}/{len(tracked)} tracked files assigned "
              f"to a component ({pct:.1f}%)")
    for w in dict.fromkeys(warnings):
        print(f"  warn:  {w}")
    for e in errors:
        print(f"  ERROR: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
