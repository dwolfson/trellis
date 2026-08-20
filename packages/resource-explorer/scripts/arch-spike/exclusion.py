"""Exclusion pass — decide which files are first-party source.

Runs BEFORE any detector. Phase 0 plan §3a: this is not tidiness. Vendored
dependency trees are committed to git in real repos (in egeria-workspaces,
1697 of 1703 tracked .js files are node_modules), and every vendored package
carries a manifest declaring a package name — which is identity precedence 1
in the design doc's §8.2. A detector applying that rule to an unfiltered tree
emits hundreds of spurious components, each with a real name, a real manifest
and real evidence behind it.

Two distinct kinds of noise, deliberately handled by two different mechanisms
because they have different implications (plan §3a):

  (a) Committed vendor code — in git, therefore in every zipball and clone.
      A production problem. Handled by VENDOR_RULES below.
  (b) Untracked build artifacts (.venv, site-packages, __pycache__) — never
      in a zipball, but present in the local checkouts Phase 0 reads. A
      property of the spike's local-path shortcut, not of production.
      Handled for free by asking git for tracked files only.

On (b): the plan says ".gitignore-aware", and the honest implementation of
that is `git ls-files` rather than reimplementing gitignore semantics —
git already solved this, and its answer is authoritative in a way a
hand-rolled matcher would not be. The non-git fallback is best-effort.

Every exclusion is attributed to the rule that caused it, so over-exclusion
is visible in the census rather than silently shrinking the corpus.
"""
from __future__ import annotations

import os
import subprocess
from collections import Counter
from dataclasses import dataclass, field


# Committed-vendor rules. Matched against path segments, so "node_modules"
# catches it at any depth. Kept small and explicit — a long speculative list
# is how real source gets silently dropped.
VENDOR_RULES: dict[str, str] = {
    "node_modules": "vendored npm packages",
    "site-packages": "vendored Python distributions",
    "vendor": "vendored dependencies (Go/PHP/Ruby convention)",
    ".venv": "virtualenv",
    "venv": "virtualenv",
    "__pycache__": "Python bytecode cache",
    ".git": "git internals",
    ".tox": "tox environments",
    ".mypy_cache": "mypy cache",
    ".pytest_cache": "pytest cache",
    ".ruff_cache": "ruff cache",
    "egg-info": "setuptools metadata",
}

# Deliberately NOT excluded by default: build/, dist/, target/. They are
# conventional output directories, but they are also real source directories
# in some projects, and when they are output they are almost always untracked
# — so the tracked-files filter already removes them. Excluding them blindly
# risks dropping first-party code to solve a problem git has already solved.
# Pass --exclude to add them for a specific target.


@dataclass
class Census:
    """What the exclusion pass saw and did — plan §3a requires reporting
    first-party vs total, because a detector that silently includes vendor
    code looks productive while being wrong."""
    root: str
    tracked_by_git: bool
    total: int = 0
    first_party: list[str] = field(default_factory=list)
    excluded_by_rule: Counter = field(default_factory=Counter)

    @property
    def excluded(self) -> int:
        return self.total - len(self.first_party)

    @property
    def first_party_ratio(self) -> float:
        return len(self.first_party) / self.total if self.total else 0.0

    def as_dict(self) -> dict:
        return {
            "root": self.root,
            "source": "git ls-files" if self.tracked_by_git else "filesystem walk",
            "total": self.total,
            "first_party": len(self.first_party),
            "excluded": self.excluded,
            "first_party_ratio": round(self.first_party_ratio, 4),
            "excluded_by_rule": dict(self.excluded_by_rule.most_common()),
        }

    def summary(self) -> str:
        pct = 100 * self.first_party_ratio
        head = (f"{len(self.first_party)}/{self.total} files first-party "
                f"({pct:.1f}%) via {'git' if self.tracked_by_git else 'walk'}")
        if not self.excluded_by_rule:
            return head
        worst = ", ".join(f"{r}={n}" for r, n in self.excluded_by_rule.most_common(4))
        return f"{head}; excluded: {worst}"


def _git_tracked(root: str) -> list[str] | None:
    """Tracked files, relative to root. None if this is not a git checkout.

    Tracked-only is the point: it excludes everything .gitignore covers,
    which is exactly noise kind (b), without parsing a single gitignore rule.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", root, "ls-files", "-z"],
            capture_output=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def _walk(root: str) -> list[str]:
    """Fallback for a non-git directory. Best-effort: without git we cannot
    know what is ignored, so the vendor rules carry the whole load."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _rule_for(d)]
        for fn in filenames:
            out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return out


def _rule_for(segment: str) -> str | None:
    """The vendor rule a single path segment trips, if any."""
    if segment in VENDOR_RULES:
        return segment
    if segment.endswith(".egg-info"):
        return "egg-info"
    return None


def scan(root: str, extra_excludes: tuple[str, ...] = ()) -> Census:
    """Partition `root` into first-party source and excluded noise."""
    root = os.path.abspath(root)
    files = _git_tracked(root)
    census = Census(root=root, tracked_by_git=files is not None)
    if files is None:
        files = _walk(root)

    rules = dict(VENDOR_RULES)
    rules.update({e: "excluded by --exclude" for e in extra_excludes})

    for rel in files:
        census.total += 1
        hit = next((seg for seg in rel.split(os.sep)
                    if seg in rules or seg.endswith(".egg-info")), None)
        if hit is None:
            census.first_party.append(rel)
        else:
            census.excluded_by_rule[_rule_for(hit) or hit] += 1

    census.first_party.sort()
    return census


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root")
    ap.add_argument("--exclude", action="append", default=[],
                    help="extra path segment to exclude (repeatable)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    c = scan(args.root, tuple(args.exclude))
    print(json.dumps(c.as_dict(), indent=2) if args.json else c.summary())
