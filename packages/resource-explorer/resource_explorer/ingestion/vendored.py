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

#: Directory names that mean "not this repository's own code". Matched on
#: any path segment, so `a/b/node_modules/c.js` is vendored and so is
#: `node_modules/c.js`. Kept deliberately short and conventional; a repo
#: with an unusual vendoring layout is a case for a per-repo rule, not for
#: growing this list until it matches everything.
VENDORED_DIRS = frozenset({
    ".git", ".hg", ".svn",
    ".venv", "venv", "env", "virtualenv", "site-packages",
    "node_modules", "bower_components", "vendor",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", "target", "out", ".next", ".nuxt",
    ".idea", ".vscode", ".gradle", ".eggs",
})


def is_vendored(rel_path: str | Path) -> bool:
    """True when any DIRECTORY on the path is a vendored name. The file's own
    name is never tested, so a file called `vendor` is not vendored and a
    file inside `vendor/` is."""
    parts = Path(rel_path).parts
    return any(p in VENDORED_DIRS for p in parts[:-1])


def is_vendored_abs(path: Path, root: Path) -> bool:
    """The same test for an absolute path under a walk root."""
    try:
        return is_vendored(path.relative_to(root))
    except ValueError:
        return False
