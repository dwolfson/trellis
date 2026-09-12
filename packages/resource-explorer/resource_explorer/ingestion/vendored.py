"""Is this file the repository's own, or somebody else's library checked in?

One rule, read by every walk. Until 2026-09-11 it lived in line_census.py
as a private set and only the line census used it, so "how much code is
there" was answered honestly while every other count was not: on
egeria-workspaces 68% of the file inventory, 77% of the extracted symbols
and 99% of the JavaScript chunks in the vector store were
node_modules/typescript. The symbol count, the documentation ratio, the
public/internal split, the component graph fed to Curate, and chat's
citations all shared an inflated denominator — and chat would cite
somebody else's library as this repository's, with a citation, which is
worse than a wrong answer because it looks checkable.

The inventory RECORDS provenance rather than dropping the files: a vendored
file is still a file in the repository, and "6,423 files · 4,425 vendored"
is the honest number one click from the misleading one instead of a silent
replacement. The derived analytics — symbols, chunks, profiles, the
census — skip vendored paths, because a measurement of this repository's
code should not measure TypeScript's.

Vendored-vs-own is public-vs-internal one ring out, and "is this ours?" is
a question the catalog should ask: a repo that vendors a dependency differs
materially from one that declares it. The inventory now holds the answer.
"""
from __future__ import annotations

from pathlib import Path

#: Two sets, because they are two different claims (review, 2026-09-12).
#: VENDORED is provenance -- somebody else's code checked in. GENERATED is
#: this repository's own output -- build artefacts, caches, tool state --
#: which is not source but is not somebody else's either. Every walk skips
#: both; the inventory records WHICH, so the rail can say "vendored" about
#: node_modules and "generated" about dist/ rather than calling a
#: repository's own build output vendored. Matched on any path segment, so
#: `a/b/node_modules/c.js` is vendored and so is `node_modules/c.js`. Kept
#: deliberately short and conventional; a repo with an unusual layout is a
#: case for a per-repo rule, not for growing these until they match
#: everything.
VENDORED_DIRS = frozenset({
    "node_modules", "bower_components", "vendor",
    ".venv", "venv", "env", "virtualenv", "site-packages",
})
GENERATED_DIRS = frozenset({
    ".git", ".hg", ".svn",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", "target", "out", ".next", ".nuxt",
    ".idea", ".vscode", ".gradle", ".eggs",
})
#: Everything a walk over "this repository's code" skips.
SKIPPED_DIRS = VENDORED_DIRS | GENERATED_DIRS

#: How the inventory column `vendored` spells the two. 0 is own code; a
#: row indexed before 2026-09-12 carries 1 for either kind.
OWN, VENDORED, GENERATED = 0, 1, 2


def provenance(rel_path: str | Path) -> int:
    """OWN, VENDORED or GENERATED for a path relative to the walk root. Only
    DIRECTORIES on the path are tested, never the file's own name: a file
    called `vendor` is not vendored and a file inside `vendor/` is. The
    first matching segment from the root decides, so `vendor/build/x.js`
    is vendored (somebody else's build output is still somebody else's)."""
    for part in Path(rel_path).parts[:-1]:
        if part in VENDORED_DIRS:
            return VENDORED
        if part in GENERATED_DIRS:
            return GENERATED
    return OWN


def is_vendored(rel_path: str | Path) -> bool:
    """True when the path is not this repository's own source -- vendored OR
    generated. The name predates the split; every walk that asks "should I
    measure this?" wants both answers to be no, so it keeps meaning that."""
    return provenance(rel_path) != OWN


def is_vendored_abs(path: Path, root: Path) -> bool:
    """The same test for an absolute path under a walk root. A path that is
    not under `root` is a caller bug -- the extra-docs PDF walk passed the
    clone root for a directory outside it and this silently returned False
    for every file -- so it raises rather than failing open."""
    try:
        rel = path.relative_to(root)
    except ValueError as e:
        raise ValueError(f"{path} is not under walk root {root}; pass the root the walk started from") from e
    return is_vendored(rel)
