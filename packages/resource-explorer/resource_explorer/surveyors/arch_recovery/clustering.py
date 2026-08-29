"""Propose candidate blueprints — which components belong together, and why.

Design: `docs/architecture-recovery-clustering.md`.

**A blueprint is a solution boundary, and a repo is not.** A repo may hold
several (design §3.3a, corrected 2026-08-29), and the same repo clustered for
two different purposes yields two legitimately different sets. So this proposes
*candidates* rather than deciding: under report-then-curate a curator decides
whether any of them becomes a real Egeria blueprint.

**Clustering is per perspective, and that is the whole trick.** §4.1's four
perspectives are not interchangeable views — the Phase 0 spike scored 16/16 on
one repo and 1-of-10 on another purely because a deployment-perspective
detector was scored against a logical-perspective ground truth. Mixing
perspectives in one cluster repeats that error inside a single blueprint.

Note this is the **§4.1 architectural perspective** carried on
`Component.perspective` (physical / deployment / logical / dev), NOT the
question-catalog's twelve Title-Case Perspectives, which were measured on
2026-08-24 and cannot discriminate — every one of them reaches a strict subset
of what another reaches (`investigation-framing-design.md` §3).

**Every signal here reads a boundary something already declared** — a compose
file, a directory, a deployment unit. None of it invents a grouping from
similarity. That is the difference between recovering an architecture and
proposing a plausible one.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import scope_hierarchy

log = logging.getLogger(__name__)

#: Dan, 2026-08-29: "Blueprints that are too complicated aren't very useful —
#: we should try to keep the number of components small — lets say around 10 or
#: less — there will be exceptions — this is not a hard rule — just a goal for
#: presentability and usefulness." Measured against the corpus, 102 of 115
#: deployment clusters already sit within it.
TARGET_CLUSTER_SIZE = 10

#: Affinity is what separates a composed component from a Collection (Dan,
#: 2026-08-29: *"no affinity leads you to collections"*). The bar is
#: `coupling.COHESIVE_BAR` — **reused, never redefined here**: it is the
#: import-cohesion bar the coupling surveyor already classifies `cohesive` at,
#: and coupling.py carries an explicit task rule against re-tuning it.
#:
#: Measured 2026-08-29 across milvus, egeria and egeria-workspaces (1,085
#: import_cohesion values), the metric is sharply bimodal:
#:
#:     exactly 0      1020   94.0%
#:     0 < x < 0.1      54    5.0%
#:     0.1 - 0.3         4    0.4%
#:     0.3 - 0.5         0    0.0%
#:     0.5 - 0.9         3    0.3%
#:     0.9 - 1.0         4    0.4%
#:
#: Two values in the whole set fall in 0.3-0.7. A component's imports either
#: almost all stay inside its subtree or almost all leave it, so the exact bar
#: barely matters — anything in that empty middle classifies all but two
#: components identically. That is why no per-repo relative rule is needed.
def _cohesive_bar() -> float:
    from . import coupling
    return coupling.COHESIVE_BAR


#: A cluster of one is not a cluster: it collapses nothing and adds a level a
#: reader steps through to reach a single component. Same reasoning as
#: `scope_hierarchy.MIN_GROUP`, applied to the blueprint rather than the group.
MIN_CLUSTER_SIZE = 2


@dataclass
class Cluster:
    """One candidate blueprint."""

    name: str
    perspective: str
    members: list[str] = field(default_factory=list)   # component slugs
    #: Which declared boundary produced this grouping. Recorded because a
    #: curator judging a proposal needs to know what it read, not just what it
    #: concluded — and because two signals disagreeing is information (§6).
    signal: str = "scope-hierarchy"
    #: "collection" — the members are co-located and the group is not itself a
    #: thing, so it becomes a blueprint. "composition" — the members cohere,
    #: which is evidence for a containing component, so they become
    #: sub-components of it rather than a Collection. Affinity is the test
    #: (§7 of the clustering design).
    carrier: str = "collection"
    #: For carrier="composition": the slug of the component the members compose.
    composed_into: str = ""
    #: Sub-blueprints, when this cluster is a rollup level (see `rollup`). A
    #: cluster has either members or children, never both.
    children: list["Cluster"] = field(default_factory=list)
    #: Set when the cluster is over TARGET_CLUSTER_SIZE and could not be
    #: subdivided further. Reported rather than silently emitted, and never
    #: truncated: an arbitrarily cut blueprint is a different blueprint.
    oversized: bool = False

    @property
    def size(self) -> int:
        """Components, counting through children."""
        if self.children:
            return sum(child.size for child in self.children)
        return len(self.members)

    def all_members(self) -> list[str]:
        if not self.children:
            return list(self.members)
        return [slug for child in self.children for slug in child.all_members()]


def _scope_of(component) -> str:
    """The scope locator a component is keyed by.

    Prefers an explicit `path` (what `persist.scope_locator_for` writes) and
    falls back to the slug, so this works over both in-memory `Component`
    objects and the dicts a results reader hands back.
    """
    for attr in ("scope_locator", "path"):
        value = getattr(component, attr, None) or (
            component.get(attr) if isinstance(component, dict) else None
        )
        if value:
            return str(value)
    slug = getattr(component, "slug", None) or (
        component.get("slug") if isinstance(component, dict) else ""
    )
    return str(slug or "")


def _perspective_of(component) -> str:
    value = getattr(component, "perspective", None) or (
        component.get("perspective") if isinstance(component, dict) else None
    )
    return str(value or "physical")


def _slug_of(component) -> str:
    value = getattr(component, "slug", None) or (
        component.get("slug") if isinstance(component, dict) else None
    )
    return str(value or "")


def _deployment_context_of(component) -> str:
    """The path whose deployment artifact declared this component.

    `Identity.deployment_context` (design §8.2) records the directory the
    compose file / manifest lived in — `comps/animation/deployment/docker_compose`
    — while the scope locator keeps only its last segment. For a monorepo that
    difference is total: genaicomps has 203 deployment components whose locators
    all begin `docker_compose::`, so the locator says they are one stack while
    the deployment context says they come from dozens of separate compose files.

    This is a **declared** boundary, not a similarity heuristic: a person put
    those services in that file. That is what makes it usable here — grouping by
    a shared name prefix would read the same way on this corpus and would be an
    inference about intent rather than a record of it.
    """
    identity = getattr(component, "identity", None)
    if identity is None and isinstance(component, dict):
        identity = component.get("identity")
    if identity is None:
        return ""
    value = getattr(identity, "deployment_context", None)
    if value is None and isinstance(identity, dict):
        value = identity.get("deployment_context")
    return str(value or "")


def _subdivide(scopes: list[str]) -> dict[str, list[str]]:
    """One level deeper, for a cluster that is over the goal.

    Hierarchies are the abstraction mechanism (design §4): a 203-member group is
    not a clustering failure, it is a group that needs another level. Re-deriving
    within the group's own members finds it if the scope locators encode one.
    Returns {} when they do not, which is the honest answer and the caller then
    marks the cluster oversized rather than inventing a split.
    """
    parents, _structural = scope_hierarchy.derive(sorted(set(scopes)))
    if not parents:
        return {}
    grouped: dict[str, list[str]] = {}
    for scope in scopes:
        grouped.setdefault(parents.get(scope, scope), []).append(scope)
    # A "split" that puts everything back in one bucket has not split anything.
    return grouped if len(grouped) > 1 else {}


def propose(components, perspective: str, *,
            cohesion: dict[str, float] | None = None,
            target_size: int = TARGET_CLUSTER_SIZE,
            max_depth: int = 3) -> list[Cluster]:
    """Candidate blueprints for one perspective, ordered largest first.

    `components` may be `Component` objects or persisted-finding dicts.
    Components of other perspectives are ignored rather than reclassified —
    they belong to a different clustering of the same repo, not to this one.

    Components that no boundary groups are left out entirely. "No signal, no
    cluster" is the same rule as design §5's "no metric, no number": a component
    swept into the nearest blueprint to avoid an empty space is a claim nothing
    measured.

    `cohesion` maps a scope locator to its `import_cohesion`. Where a group's
    own scope is cohesive at or above `coupling.COHESIVE_BAR`, the group is
    emitted as a **composition** rather than a Collection: its members cohere,
    which is evidence that the containing thing exists, and a component is the
    honest carrier for that. Without cohesion data every group is a Collection,
    which is the correct default — co-location says where things were declared,
    not that they belong to one another.
    """
    scoped = [c for c in components if _perspective_of(c) == perspective]
    if not scoped:
        return []

    by_scope: dict[str, list[str]] = {}
    by_scope_components: dict[str, list] = {}
    for c in scoped:
        by_scope.setdefault(_scope_of(c), []).append(_slug_of(c))
        by_scope_components.setdefault(_scope_of(c), []).append(c)

    scopes = sorted(by_scope)
    parents, _structural = scope_hierarchy.derive(scopes)

    # First pass: the groups the scope locators already declare.
    groups: dict[str, list[str]] = {}
    for scope in scopes:
        groups.setdefault(parents.get(scope, scope), []).append(scope)

    clusters: list[Cluster] = []
    for name, member_scopes in sorted(groups.items()):
        clusters.extend(
            _build(name, member_scopes, by_scope, by_scope_components,
                   perspective, target_size, max_depth)
        )

    # Affinity promotes a Collection to a composition. Applied after grouping
    # rather than inside it because it does not change WHICH components group
    # together — the same members, carried differently. A cohesive group is not
    # subdivided by the ~10 goal either: cohesion is the evidence that this is
    # one thing, and splitting it to hit a presentation target would discard the
    # very signal that justified asserting it.
    if cohesion:
        bar = _cohesive_bar()
        for cluster in clusters:
            value = cohesion.get(cluster.name)
            if value is not None and value >= bar:
                cluster.carrier = "composition"
                cluster.composed_into = cluster.name
                cluster.signal = f"import-cohesion {value:.2f}"
                cluster.oversized = False

    kept = [c for c in clusters if c.size >= MIN_CLUSTER_SIZE]
    dropped = len(clusters) - len(kept)
    if dropped:
        log.debug("%s: %d single-component group(s) left unclustered", perspective, dropped)
    return sorted(kept, key=lambda c: (-c.size, c.name))


def _build(name: str, member_scopes: list[str], by_scope: dict[str, list[str]],
           by_scope_components: dict[str, list], perspective: str,
           target_size: int, depth_left: int) -> list[Cluster]:
    """One group, subdivided while it is over the goal and structure remains."""
    slugs = [s for scope in member_scopes for s in by_scope.get(scope, [])]

    if len(slugs) <= target_size or depth_left <= 0:
        return [Cluster(name=name, perspective=perspective, members=sorted(slugs),
                        oversized=len(slugs) > target_size)]

    # Prefer the deployment context: for identity-scoped components the scope
    # locator has already thrown away the declaring file, so re-deriving over
    # the locators finds nothing while the context still distinguishes them.
    by_context: dict[str, list[str]] = {}
    for scope in member_scopes:
        for component in by_scope_components.get(scope, []):
            context = _deployment_context_of(component)
            if context:
                by_context.setdefault(context, []).append(scope)
    if len(by_context) > 1:
        out: list[Cluster] = []
        for context, ctx_scopes in sorted(by_context.items()):
            out.extend(_build(context, sorted(set(ctx_scopes)), by_scope,
                              by_scope_components, perspective, target_size,
                              depth_left - 1))
        return out

    sub = _subdivide(member_scopes)
    if not sub:
        # Over the goal and nothing further to read. Say so; do not truncate.
        log.debug("%s: cluster %r has %d members and no further structure",
                  perspective, name, len(slugs))
        return [Cluster(name=name, perspective=perspective, members=sorted(slugs),
                        oversized=True)]

    out: list[Cluster] = []
    for sub_name, sub_scopes in sorted(sub.items()):
        out.extend(_build(sub_name, sub_scopes, by_scope, perspective,
                          target_size, depth_left - 1))
    return out


def rollup(clusters: list[Cluster], *, target: int = TARGET_CLUSTER_SIZE) -> list[Cluster]:
    """Group clusters under parent clusters while there are too many of them.

    **The ~10 goal binds at every level, not only the leaves.** Splitting
    genaiexamples' one 546-component group by deployment context produced 87
    clusters of a readable size each — and 87 blueprints for one repo is no more
    usable than one blueprint of 546. The goal is presentability, and a flat list
    long enough to scroll fails it just as surely.

    Hierarchies are the abstraction that resolves this (design §4), and blueprints
    nest: a `SolutionBlueprint` is a `Collection` and `CollectionMembership` admits
    any `Referenceable`, so a blueprint may hold blueprints (§3.3a, corrected
    2026-08-29). A repo-level blueprint whose members are sub-blueprints is the
    natural shape for a monorepo.

    The parent is the **shared path prefix** of its children's names — still a
    declared boundary (`comps/animation/deployment` and
    `comps/arb_post_hearing_assistant/deployment` share `comps`, a directory a
    person made), never a similarity measure.

    Returns the top level. Each returned cluster carries `children`; a cluster
    with children has no `members` of its own, exactly as a structural grouping
    node has no evidence of its own.
    """
    if len(clusters) <= target:
        return clusters

    def prefix_of(name: str) -> str:
        head = name.split("::", 1)[0]
        parts = [p for p in head.split("/") if p]
        return parts[0] if parts else head

    grouped: dict[str, list[Cluster]] = {}
    for cluster in clusters:
        grouped.setdefault(prefix_of(cluster.name), []).append(cluster)

    # A rollup giving one bucket per cluster has abstracted nothing — it adds a
    # level a reader steps through for no gain. A rollup giving ONE bucket is
    # different and is kept: twenty sibling blueprints under one parent takes the
    # top level from twenty to one, which is the goal. The parent is then marked
    # oversized if it still holds more than the target, so the remaining problem
    # is reported rather than buried a level down.
    if len(grouped) >= len(clusters):
        return clusters

    out: list[Cluster] = []
    for name, children in sorted(grouped.items()):
        if len(children) == 1:
            out.append(children[0])
            continue
        out.append(Cluster(
            name=name,
            perspective=children[0].perspective,
            members=[],
            children=sorted(children, key=lambda c: (-c.size, c.name)),
            signal="rollup",
            oversized=len(children) > target,
        ))
    return sorted(out, key=lambda c: (-c.size, c.name))


def assign(components, clusters: list[Cluster]) -> int:
    """Write each cluster's name onto its members' `blueprint` field.

    Returns how many components were assigned. Components in no cluster are
    left with `blueprint` unset rather than given a default one — the renderer
    draws those ungrouped, which is the truthful picture.
    """
    membership: dict[str, str] = {}
    composed: dict[str, str] = {}

    def walk(cluster: Cluster) -> None:
        if cluster.children:
            for child in cluster.children:
                walk(child)
            return
        if cluster.carrier == "composition":
            # Members become sub-components of the thing they compose; they get
            # no blueprint, because a Collection is not what the evidence
            # supports here.
            for slug in cluster.members:
                if slug != cluster.composed_into:
                    composed[slug] = cluster.composed_into
            return
        for slug in cluster.members:
            membership[slug] = cluster.name

    for cluster in clusters:
        walk(cluster)

    assigned = 0
    for component in components:
        slug = _slug_of(component)
        parent = composed.get(slug)
        if parent:
            if isinstance(component, dict):
                component["parent_slug"] = parent
            else:
                component.parent_slug = parent
            assigned += 1
            continue
        name = membership.get(slug)
        if not name:
            continue
        if isinstance(component, dict):
            component["blueprint"] = name
        else:
            component.blueprint = name
        assigned += 1
    return assigned
