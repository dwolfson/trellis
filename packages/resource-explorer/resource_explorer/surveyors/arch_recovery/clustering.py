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

#: Backstop on `_wire_density_split`'s pairwise search (§10 signal 2) —
#: reached only once every declared boundary is exhausted, so it should be
#: rare, but a member set this large would still make the O(n^2) pairwise
#: scan (incrementally updated per merge, not recomputed — see that
#: function's docstring) slow enough to matter on a survey's hot path.
#: Not tuned against a measured case; revisit if a real oversized group
#: this large shows up and the cap is what's silencing its wire signal.
_MAX_WIRE_DENSITY_MEMBERS = 200

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


def _name_of(component) -> str:
    """Mirrors _slug_of — needed because interfaces.propose attributes a
    compose wire's source/target by component NAME (`_owner_of` returns
    `c.name`), not slug, while everything else here keys on slug. See
    `_resolve_wire_endpoint`."""
    value = getattr(component, "name", None) or (
        component.get("name") if isinstance(component, dict) else None
    )
    return str(value or "")


def _resolve_wire_endpoint(value: str, by_slug: dict[str, str], by_name: dict[str, str]) -> str | None:
    """A wire endpoint to a slug, or None if it matches neither — the same
    ambiguity `mermaid._resolve_endpoint` resolves, kept as its own copy
    rather than a shared import for the same reason
    ComponentMaterializer._find_element_guid duplicates
    EgeriaPublisher._find_element_guid: these two modules don't share a
    dependency relationship, and this is small enough that a shared helper
    would cost more coupling than it saves. `by_slug`/`by_name` map to
    slugs directly here (not to Component objects) since that is all a
    caller building an edge-weight graph over slugs needs.
    """
    if value in by_slug:
        return by_slug[value]
    return by_name.get(value)


def _wire_weights(components, wires: list[dict]) -> dict[frozenset, int]:
    """{{slug_a, slug_b}: wire count} — undirected, since clustering asks
    "do these talk to each other" rather than "who calls whom" (direction
    matters for the diagram, not for whether two components belong in the
    same blueprint). A self-wire (a component's dependency resolves to
    itself, or an endpoint that resolves to nothing) contributes no edge —
    an edge needs two distinct, resolved slugs to mean anything for
    grouping purposes; `mermaid.py`'s "unresolved renders as external"
    concern is about not hiding a missing edge from the diagram, which is a
    different requirement from this one.
    """
    by_slug = {_slug_of(c): _slug_of(c) for c in components if _slug_of(c)}
    by_name = {_name_of(c): _slug_of(c) for c in components if _name_of(c) and _slug_of(c)}
    weights: dict[frozenset, int] = {}
    for w in wires or []:
        src = _resolve_wire_endpoint(str(w.get("source") or ""), by_slug, by_name)
        dst = _resolve_wire_endpoint(str(w.get("target") or ""), by_slug, by_name)
        if not src or not dst or src == dst:
            continue
        key = frozenset((src, dst))
        weights[key] = weights.get(key, 0) + 1
    return weights


def _wire_density_split(member_scopes: list[str], by_scope: dict[str, list[str]],
                        wire_weights: dict[frozenset, int], target_size: int) -> dict[str, list[str]]:
    """Signal 2 (design §10): group by which components talk to each other,
    when no declared boundary (deployment context, scope hierarchy) is left
    to read. A cluster is a densely-wired subgraph — this builds one via
    greedy agglomerative merging, the simplest thing that reads as "these
    keep talking to each other" rather than inventing structure from
    similarity: repeatedly merge whichever two groups have the strongest
    total wire weight between them, stopping at target_size so growth stays
    bounded the same way rollup()'s prefix-merge does.

    Operates at SCOPE granularity (member_scopes), not slug — a scope may
    hold several slugs (component hierarchy nesting predates clustering),
    and the wire graph is over slugs, so a scope pair's weight is the sum
    of wire weight across every slug pair one scope contributes and the
    other receives.

    Returns {} exactly like _subdivide when nothing merged — "no signal, no
    cluster" (design §5) applies here too: a member set with zero wires
    between any of them is not evidence of a boundary, and returning a
    single bucket covering everyone would be indistinguishable from a real
    finding to a curator reading it.

    Pairwise weights are computed ONCE up front and updated incrementally
    on each merge (a merged group's weight to any third group is the sum of
    its two parents' weights to that group — wires are additive) rather
    than rescanning the full slug-level graph every iteration, which would
    make the search cost grow with the number of merges as well as the
    number of members. `_MAX_WIRE_DENSITY_MEMBERS` is a backstop on top of
    that, not a substitute for it: this is a fallback branch, reached only
    once every declared boundary is exhausted, and a pathological group
    must not turn into a slow survey run — reported via log.debug rather
    than silently skipped, since a silent skip reads as "no wires" instead
    of "not attempted".
    """
    scopes = sorted(set(member_scopes))
    if len(scopes) < 2:
        return {}
    if len(scopes) > _MAX_WIRE_DENSITY_MEMBERS:
        log.debug("wire-density: %d members exceeds the cap of %d, skipping",
                  len(scopes), _MAX_WIRE_DENSITY_MEMBERS)
        return {}

    scope_slugs = {scope: by_scope.get(scope, []) for scope in scopes}
    sizes: dict[str, int] = {scope: len(scope_slugs[scope]) for scope in scopes}
    groups: dict[str, set[str]] = {scope: {scope} for scope in scopes}  # group name -> member scopes

    pair_w: dict[frozenset, int] = {}
    for i, sa in enumerate(scopes):
        for sb in scopes[i + 1:]:
            total = sum(
                wire_weights.get(frozenset((slug_a, slug_b)), 0)
                for slug_a in scope_slugs[sa] for slug_b in scope_slugs[sb]
            )
            if total:
                pair_w[frozenset((sa, sb))] = total

    merged_any = False
    while len(groups) > 1:
        best: tuple[int, str, str] | None = None  # (weight, name_a, name_b), name_a < name_b
        names = sorted(groups)
        for i, name_a in enumerate(names):
            for name_b in names[i + 1:]:
                if sizes[name_a] + sizes[name_b] > target_size:
                    continue
                weight = pair_w.get(frozenset((name_a, name_b)), 0)
                if weight <= 0:
                    continue
                candidate = (weight, name_a, name_b)
                # Highest weight first; deterministic tie-break by name pair
                # so the same input always merges the same way.
                if best is None or candidate[0] > best[0] or (
                    candidate[0] == best[0] and (candidate[1], candidate[2]) < (best[1], best[2])
                ):
                    best = candidate
        if best is None:
            break
        _, name_a, name_b = best
        merged_name = sorted(groups[name_a] | groups[name_b])[0] + "~wired"
        merged_members = groups.pop(name_a) | groups.pop(name_b)
        merged_size = sizes.pop(name_a) + sizes.pop(name_b)
        groups[merged_name] = merged_members
        sizes[merged_name] = merged_size
        merged_any = True

        for other in list(groups):
            if other == merged_name:
                continue
            combined = pair_w.pop(frozenset((name_a, other)), 0) + pair_w.pop(frozenset((name_b, other)), 0)
            if combined:
                pair_w[frozenset((merged_name, other))] = combined

    if not merged_any:
        return {}
    result = {name: sorted(member_scopes_set) for name, member_scopes_set in groups.items()}
    return result if len(result) > 1 else {}


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
            wires: list[dict] | None = None,
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

    `wires` (§10 signal 2, `interfaces.propose`'s own output — the same edge
    list `mermaid.render` draws) is the fallback signal, tried only where
    every declared boundary (deployment context, scope hierarchy) is
    exhausted and a group is still over `target_size`. It is not blended
    with the declared-boundary signals or given a vote alongside them —
    weaker evidence used only where stronger evidence ran out, not averaged
    against it. Without wires, behaviour is unchanged from before this
    signal existed.
    """
    scoped = [c for c in components if _perspective_of(c) == perspective]
    if not scoped:
        return []

    by_scope: dict[str, list[str]] = {}
    by_scope_components: dict[str, list] = {}
    for c in scoped:
        by_scope.setdefault(_scope_of(c), []).append(_slug_of(c))
        by_scope_components.setdefault(_scope_of(c), []).append(c)

    wire_weights = _wire_weights(scoped, wires) if wires else None

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
                   perspective, target_size, max_depth, wire_weights)
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
           target_size: int, depth_left: int,
           wire_weights: "dict[frozenset[str], int] | None" = None) -> list[Cluster]:
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
                              depth_left - 1, wire_weights))
        return out

    sub = _subdivide(member_scopes)
    if sub:
        # Bug fixed 2026-08-30: this recursive call was missing
        # by_scope_components (6 args into a 7-parameter function with no
        # defaults) — a live TypeError, unreached by any existing test
        # because the oversized-cluster tests use flat scope locators
        # specifically so scope_hierarchy.derive() never finds anything to
        # subdivide, which is exactly what avoids this branch.
        out: list[Cluster] = []
        for sub_name, sub_scopes in sorted(sub.items()):
            out.extend(_build(sub_name, sub_scopes, by_scope, by_scope_components,
                              perspective, target_size, depth_left - 1, wire_weights))
        return out

    # Declared structure is exhausted. Wire density (§10 signal 2) is the
    # fallback, not the first resort: every earlier branch reads a boundary
    # something declared, and wires are a measured graph rather than a
    # declaration — weaker evidence, tried only once nothing stronger is
    # left. "No signal, no cluster" still applies: a member set with no
    # wires between any of them returns {} from _wire_density_split just
    # like _subdivide does, and this function falls through to oversized.
    if wire_weights:
        wired = _wire_density_split(member_scopes, by_scope, wire_weights, target_size)
        if wired:
            out = []
            for wired_name, wired_scopes in sorted(wired.items()):
                out.extend(_build(wired_name, wired_scopes, by_scope, by_scope_components,
                                  perspective, target_size, depth_left - 1, wire_weights))
            # Leaf clusters this pass actually produced (not further
            # recursion — a wire-derived group that still exceeds target_size
            # recurses through scope_hierarchy/wire-density again, in which
            # case a NESTED signal earned the tag, not this one) get their
            # provenance recorded, since a curator judging a proposal needs
            # to know it read a measured graph, not a directory a person
            # declared — the same reason `signal` exists on Cluster at all.
            for cluster in out:
                if cluster.name in wired and not cluster.children:
                    cluster.signal = "wire-density"
            return out

    # Over the goal and nothing further to read. Say so; do not truncate.
    log.debug("%s: cluster %r has %d members and no further structure",
              perspective, name, len(slugs))
    return [Cluster(name=name, perspective=perspective, members=sorted(slugs),
                    oversized=True)]


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
