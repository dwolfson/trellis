"""Derive the parent a scope locator already encodes.

`projection.py` collapses a hierarchy to a level. It has never had one to
collapse: measured 2026-08-25, milvus reports **204 components at every depth**
and genaicomps 311, because `project_rows` is an identity function over a flat
set.

**Why it is flat, and it is not what either earlier diagnosis said.** The
backlog held that persistence filtered out intermediate candidates; the
presentation session then found that persisting them changed nothing. Measured
directly, the truth is simpler and larger:

```
milvus     217 component rows — 201 with parent_slug = "", 16 with one
genaicomps 311 component rows — 301 with parent_slug = ""
```

Only `code::` components ever received a hierarchy at all. Manifest-,
deployment- and coupling-derived components — the overwhelming majority — are
**parentless by construction**, so no amount of persisting code-marker ancestors
could have helped them.

**The evidence was already there, in the scope locator.** Every component is
keyed by one, and the locator is not opaque:

```
internal/agg           a PATH  -> its parent is internal/
compose::agent         an IDENTITY -> its parent is the compose stack
cluster::milvus-proxy  -> the cluster stack
```

Both halves are recorded fact, not a naming heuristic. `compose::agent` means
"the `agent` service declared in that compose file", and the compose file is a
real deployment unit that a person would name. Grouping by it is reading what
the detector already wrote down.

```
milvus      174 path scopes ->  6 groups   +  31 identity ->  5   (ground truth: 8)
genaicomps   23 path scopes ->  1 group    + 289 identity ->  4
```

**A derived parent is a structural node, never a component.** These ancestors
have no marker evidence of their own — nothing detected `internal/`, its
children were detected — so they carry no type, no confidence and no proposer.
Emitting them as ordinary components would invent evidence, which is exactly
what design §5's "no metric, no number" rule exists to prevent.

**A parent of one child is not a parent.** It collapses nothing and adds a node
a reader has to step through, so a group must have at least two members to
exist.
"""
from __future__ import annotations

from collections import defaultdict

#: Below this a group is not worth a node: it collapses nothing and adds a level
#: a reader must traverse to reach a single child.
MIN_GROUP = 2


def _path_parent(scope: str) -> str:
    parts = [p for p in scope.split("/") if p]
    return "/".join(parts[:-1]) if len(parts) > 1 else ""


def _identity_parent(scope: str) -> str:
    """`compose::agent` -> `compose`. The prefix is the deployment unit the
    detector recorded, not a string we are splitting hopefully.

    `.` is kept as a parent rather than discarded: milvus has eight
    `.::<service>` components from a root compose file, and `.` is itself a
    scope. Dropping it left all eight as separate roots when the file that
    declares them is exactly the thing that groups them.
    """
    head, sep, _ = scope.partition("::")
    return head if sep and head != "" else ""


def parent_of(scope: str) -> str:
    """The parent this scope locator names, or `""` if it names none."""
    if "::" in scope:
        return _identity_parent(scope)
    return _path_parent(scope)


def _ancestors(scope: str) -> list:
    """Every ancestor of a scope, nearest first."""
    if "::" in scope:
        head = _identity_parent(scope)
        return [head] if head else []
    parts = [p for p in scope.split("/") if p]
    return ["/".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]


def derive(scopes: list, min_group: int = MIN_GROUP) -> tuple:
    """`(parents, structural)` for a set of scope locators.

    `parents` maps scope -> parent scope, for scopes whose parent groups at
    least `min_group` of them. `structural` is the set of parents that are not
    themselves scopes — the nodes that must be persisted as structural, with no
    type and no confidence.

    A scope that is already a parent of others keeps its own parent too, so a
    two-level path (`internal/querycoordv2/x`) produces both levels rather than
    flattening to the top.
    """
    # Which ancestors group enough scopes to be worth existing. Counted over
    # EVERY ancestor, not only the immediate one: `internal/parser/planparserv2`
    # has one sibling under `internal/parser` and dozens under `internal`, and
    # attaching only to the immediate parent left it a root three levels deep
    # while `internal` sat there grouping the rest.
    counts: dict = defaultdict(set)
    for scope in scopes:
        for anc in _ancestors(scope):
            counts[anc].add(scope)

    qualifying = {a for a, members in counts.items()
                  if len(members) >= min_group and a not in ("", ".")} | {
        a for a in counts if a == "." and len(counts[a]) >= min_group}

    parents: dict = {}
    for scope in scopes:
        for anc in _ancestors(scope):        # nearest first
            if anc in qualifying and anc != scope:
                parents[scope] = anc
                break

    known = set(scopes)
    structural = {p for p in set(parents.values()) if p not in known}
    return parents, structural


def missing_ancestors(components) -> list:
    """Parent slugs referenced by `components` that are not themselves components.

    These are the structural grouping nodes: `persist.py` synthesises exactly
    this set as `structural_node` findings (confidence 0, no type), and
    `mermaid.py` draws exactly this set as grouping-only nodes. Both callers
    must agree — a node drawn as a component but persisted as structural, or
    the reverse, shows a curator a different architecture from the one the
    findings describe — so the computation lives here rather than in each.
    """
    present = {c.slug for c in components}
    referenced = {c.parent_slug for c in components if c.parent_slug}
    return sorted(referenced - present)


def summarise(scopes: list, parents: dict) -> str:
    """One line for the run notes — never a bare count, since a hierarchy that
    collapsed nothing and one that collapsed everything both report a number."""
    roots = [s for s in scopes if s not in parents]
    return (f"{len(scopes)} scope(s) -> {len(roots)} root(s) "
            f"via {len(set(parents.values()))} parent group(s)")
