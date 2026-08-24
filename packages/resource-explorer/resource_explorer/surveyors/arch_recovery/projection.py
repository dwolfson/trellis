"""Project the stored component hierarchy to a level a consumer wants —
approach-portfolio-model.md §2a: "store the hierarchy; project a level."

Nothing here discards data. `code_markers.build_hierarchy` and
`coupling.propose` emit every candidate subtree they find, tagged with
`depth`/`parent_slug` (design §3.3a — `SolutionComposition` nests
`SolutionComponent`s natively, so retaining depth is what the target model
already expects). This module only picks which of those already-computed
Components to SHOW for a given purpose:

  - Discovery ("which subsystem is this?") wants coarse — a UI rendering a
    few thousand nodes flat is unusable (item 3's own point: projection is
    a display requirement, not only a scoring rule).
  - Analysis (component-scoped metrics, §6 of the design doc) wants fine —
    the whole hierarchy, unprojected.

Works over both `Component` dataclass instances (the in-memory IR, before
`persist_ir` writes it) and the plain dicts a results reader gets back from
the registry (same three keys: `slug`/`parent_slug`, `depth`) — the two
`project*` entry points below cover each shape.
"""
from __future__ import annotations

from typing import Any, Protocol

from .ir import Component

# The default a results reader should use — deep enough to distinguish real
# subsystems, shallow enough that a corpus with thousands of raw candidates
# (the `egeria` case this whole redesign exists for) still renders as a
# handful of top-level nodes. Not a scoring threshold — see ARI note below.
DEFAULT_PROJECTION_DEPTH = 1

# "The level a stage wants" (item 3) — Discovery answers "which subsystem is
# this?", which the coarsest useful level answers; Analysis is where
# component-scoped metrics (design §6) need the fine-grained partition, so
# it gets the unprojected hierarchy (None = no cap). Any stage not listed
# here falls back to DEFAULT_PROJECTION_DEPTH, which is itself Discovery's
# level — a reasonable default for an unspecified caller.
STAGE_PROJECTION_DEPTH: dict[str, int | None] = {
    "discovery": 0,
    "scouting": 0,
    "assessment": 1,
    "analysis": None,
}


class _Node(Protocol):
    slug: str
    parent_slug: str
    depth: int


def _shallowest_within(slug: str, by_slug: dict[str, _Node], max_depth: int) -> str:
    """Walk `slug`'s ancestor chain up to the shallowest node at or below
    `max_depth`. A branch whose candidates are all deeper than `max_depth`
    (its shallowest node has `parent_slug == ""` yet `depth > max_depth`)
    keeps that node rather than vanishing — it is the coarsest reading
    available for that branch, and dropping it would silently lose the
    branch instead of merely coarsening it."""
    node = by_slug.get(slug)
    if node is None:
        return slug
    while node.depth > max_depth and getattr(node, "parent_slug", ""):
        parent = by_slug.get(node.parent_slug)
        if parent is None:
            break
        node = parent
    return node.slug


def project(components: list[Component],
           max_depth: int | None = DEFAULT_PROJECTION_DEPTH) -> list[Component]:
    """The partition of `components` at `max_depth` — every leaf's
    shallowest-within-depth ancestor, deduplicated. `max_depth=None` returns
    the full, unprojected hierarchy (Analysis's level)."""
    if max_depth is None:
        return list(components)
    by_slug = {c.slug: c for c in components}
    chosen: dict[str, Component] = {}
    for c in components:
        rep_slug = _shallowest_within(c.slug, by_slug, max_depth)
        chosen[rep_slug] = by_slug[rep_slug]
    return sorted(chosen.values(), key=lambda c: c.slug)


def project_for_stage(components: list[Component], stage: str) -> list[Component]:
    """`project()` at "the level a stage wants" (item 3) — see
    `STAGE_PROJECTION_DEPTH`."""
    return project(components, STAGE_PROJECTION_DEPTH.get(stage, DEFAULT_PROJECTION_DEPTH))


class _DictNode:
    """Adapts a persisted-finding-shaped dict (`path`/`parent_path`/`depth`
    keys — see repo_survey_definition_adapter.py's `_architecture_recovery_
    results`) to the `_Node` protocol `_shallowest_within` walks, without
    that reader needing to round-trip through `Component`."""
    __slots__ = ("slug", "parent_slug", "depth", "row")

    def __init__(self, row: dict[str, Any]) -> None:
        self.slug = row["path"]
        self.parent_slug = row.get("parent_path") or ""
        self.depth = row.get("depth", 0)
        self.row = row


def project_rows(rows: list[dict[str, Any]],
                 max_depth: int | None = DEFAULT_PROJECTION_DEPTH) -> list[dict[str, Any]]:
    """Same projection, over the dict rows a results reader already
    assembled (keyed by `path`, the scope_locator, with a `parent_path`
    added alongside it) — so a reader can default to a coarse view without
    recomputing anything the survey steps already persisted."""
    if max_depth is None:
        return list(rows)
    nodes = {r["path"]: _DictNode(r) for r in rows}
    chosen: dict[str, dict[str, Any]] = {}
    for r in rows:
        rep = _shallowest_within(r["path"], nodes, max_depth)
        chosen[rep] = nodes[rep].row
    return sorted(chosen.values(), key=lambda r: r["path"])
