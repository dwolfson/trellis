"""Turn a Survey Definition's step graph into an execution plan.

RE should not be a workflow engine. There are two coordinators and neither is
RE: Egeria coordinates and RE executes leaves as an engine host, or RE
coordinates and hands the workflow to Prefect. Today it does neither —
`survey_definition_executor.execute()` walks the step list in its own
`while i < n` loop and dispatches individual steps to Prefect, so RE is the
sequencer and Prefect is a task runner, which is the inversion of what it
should be.

This module is the seam between the two. It is pure: a definition in, a plan
out, no Prefect import and no execution. That keeps the part with the
interesting logic — what depends on what, and which edges are conditional —
testable without a Prefect server, and leaves the flow itself thin enough to
be obviously correct.

**A plan is a DAG, not a sequence.** `SurveyDefinition.steps` is a flat list
produced by walking a single chain, which is also why the reader raises on
branching. The graph is already parsed and sitting beside it in
`SurveyDefinition.links`, carrying `guard` and `mandatory_guard` per edge. So
the plan is built from the links, and the flat list is used only to recover
the steps' own metadata.

**Guards are carried, not evaluated.** An edge whose guard is anything other
than `Any` is conditional, and this module records that fact without deciding
it. Choosing a branch at runtime is the engine's job — Prefect's — and doing
it here would rebuild in this file the thing the whole design is trying to
stop RE from being.

**PRODUCES edges (design §17.1, folded in here 2026-09-24).** PR #241 built
`step_produces`/`prerequisite_resolver` and wired them into the local
execution loop only, leaving the gap its own "Gaps found" section named
explicitly: a Prefect-orchestrated definition is planned purely from its
authored `Link Next Process Step` edges, so it can dispatch a step whose
precondition (`step_preconditions.PRECONDITIONS`) has no producer scheduled
before it. `build_plan` now closes that when the caller passes
`step_registry` — the definition's own step registry (`STEP_REGISTRY` /
`DATABASE_STEP_REGISTRY`) — by adding a dependency edge from a precondition's
producer to whatever step needs it, for every producer not already an
ancestor via an authored edge.

This is deliberately a *structural* answer, not the resolver's runtime one:
a plan is built once per definition and reused for every entity it surveys,
so there is no `registry`/`entity` here to ask "does the stored data already
exist" the way `prerequisite_resolver.resolve` can. What a plan CAN know,
and now does, is whether the producer step is even declared to run — and, if
its declared cost sits above the tier the demanding step was authored at,
that the plan asked for something outside its own budget. See
`_add_produces_edges` for the two build-time errors this raises instead of
the resolver's "propose to the user" (Prefect has no such surface at build
time — this is a documented judgement call for this change, not something
§17.1 itself specifies).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

log = logging.getLogger(__name__)

#: The guard meaning "always follow this edge".
UNCONDITIONAL_GUARD = "Any"


@dataclass
class PlannedStep:
    """One step, with what must finish before it can start."""
    step_key: str
    qualified_name: str
    executes_at: str = ""
    #: step_keys that must complete first — the incoming edges.
    depends_on: list = field(default_factory=list)
    #: {upstream step_key: guard} for edges that are conditional. An entry here
    #: means this step runs only if that upstream emitted that guard.
    guarded_by: dict = field(default_factory=dict)

    @property
    def conditional(self) -> bool:
        return bool(self.guarded_by)


@dataclass
class ExecutionPlan:
    process_qualified_name: str = ""
    steps: list = field(default_factory=list)          # PlannedStep, topological
    entry_points: list = field(default_factory=list)   # step_keys with no predecessor
    unreachable: list = field(default_factory=list)    # declared but never reached

    @property
    def branches(self) -> bool:
        """Whether any step has more than one outgoing edge."""
        out: dict = {}
        for step in self.steps:
            for upstream in step.depends_on:
                out[upstream] = out.get(upstream, 0) + 1
        return any(n > 1 for n in out.values())

    @property
    def by_key(self) -> dict:
        return {s.step_key: s for s in self.steps}


class CyclicPlanError(ValueError):
    """A definition whose steps cannot be ordered — it contains a cycle.

    Raised rather than returned, and never partially ordered: a plan missing
    the steps it could not place would run part of a survey and report success
    for the whole of it.

    Also raised when PRODUCES edges (see `_add_produces_edges`) close a loop
    that the authored edges alone did not — a step and its own precondition's
    producer requiring each other transitively. Same treatment as an
    authored cycle: a declaration bug, not a partial plan.
    """


class MissingPrerequisiteError(ValueError):
    """A step's declared precondition is produced by a step that is not one
    of this definition's own steps.

    The local resolver (`prerequisite_resolver.resolve`) can run a producer
    from outside the current definition's step list, because it dispatches
    steps directly. A Prefect plan cannot: `serialise()` hands the flow one
    task per entry in `ExecutionPlan.steps`, built from THIS definition's own
    steps and their own `qualified_name`/`executes_at` — there is no step
    metadata to build a task for a producer the definition never authored.
    Raised at build time, naming the missing producer, rather than silently
    planning a definition that will still dispatch a step with absent input.
    """


class PrerequisiteTierError(ValueError):
    """A step's precondition is produced by a step whose declared cost sits
    above the tier the demanding step was authored at.

    **Judgement call, this change (2026-09-24), not specified by design
    §17.1.** On the local path, this exact situation becomes a `Proposal`
    the user confirms before the chain runs (`prerequisite_resolver.
    resolve`'s stop rule 2) — the whole point being that a user who picked a
    cheap tier is never charged an expensive fetch without asking first. A
    Prefect plan is built once, ahead of any per-run confirmation surface;
    there is nowhere to put that prompt at build time. Silently adding the
    edge would spend a tier nobody budgeted for, and silently leaving it out
    reproduces the exact gap this change closes (the step still gets no
    input). Raising here is the third option: it fails loudly, at build
    time, naming both the missing producer and the tier it crosses, so
    whoever authored or is launching this definition can decide — widen the
    tier, split the step into a definition authored at that tier, or route
    this definition through the local execution loop, which has the
    proposal surface this one does not.
    """


def build_plan(
    survey_def,
    step_registry: Mapping[str, Any] | None = None,
    max_fetch_cost: str | None = None,
    max_compute_cost: str | None = None,
) -> ExecutionPlan:
    """An ExecutionPlan from a SurveyDefinition.

    Falls back to the linear chain implied by `steps` when the definition
    carries no links at all — an older definition, or one whose links were
    lost. Stated in a log rather than assumed silently, because a chain
    inferred from list order is a guess about intent where real links are a
    declaration of it.

    `step_registry` is optional and, when passed, is this definition's own
    step registry (`STEP_REGISTRY` / `DATABASE_STEP_REGISTRY`) — the same
    mapping `prerequisite_resolver.resolve` takes. Its presence is what turns
    on PRODUCES-edge folding (`_add_produces_edges`); omitting it keeps this
    function exactly as it behaved before that existed, which every call site
    that does not (yet) have a registry handy still relies on.
    `max_fetch_cost`/`max_compute_cost` are the same explicit ceiling
    `prerequisite_resolver.Budget.for_step` accepts — a caller that already
    knows the run's budget can pass it; omitted, the budget check falls back
    to each demanding step's own declared tier, exactly as the resolver does.
    """
    steps = list(getattr(survey_def, "steps", []) or [])
    by_guid = {getattr(s, "guid", None): s for s in steps}
    plan = ExecutionPlan(
        process_qualified_name=getattr(survey_def, "qualified_name", "") or "")

    def key_of(step) -> str:
        return (getattr(step, "re_analysis_step", None)
                or getattr(step, "qualified_name", "") or "")

    edges: list = []
    links = list(getattr(survey_def, "links", []) or [])
    if links:
        for link in links:
            prev = by_guid.get(getattr(link, "previous_guid", None))
            nxt = by_guid.get(getattr(link, "next_guid", None))
            if prev is None or nxt is None:
                # An edge naming a step the definition does not contain. Not
                # ours to run, and not silently dropped either.
                log.warning("%s: link references a step outside the definition — "
                            "ignored", plan.process_qualified_name)
                continue
            edges.append((key_of(prev), key_of(nxt),
                          getattr(link, "guard", "") or UNCONDITIONAL_GUARD))
    elif len(steps) > 1:
        log.info("%s declares no step links — falling back to the order of its "
                 "step list, which is an inference about intent rather than a "
                 "declaration of it", plan.process_qualified_name)
        keys = [key_of(s) for s in steps]
        edges = [(a, b, UNCONDITIONAL_GUARD) for a, b in zip(keys, keys[1:])]

    incoming: dict = {key_of(s): [] for s in steps}
    guarded: dict = {key_of(s): {} for s in steps}
    for prev, nxt, guard in edges:
        if nxt not in incoming:
            continue
        incoming[nxt].append(prev)
        if guard != UNCONDITIONAL_GUARD:
            guarded[nxt][prev] = guard

    planned = {
        key_of(s): PlannedStep(
            step_key=key_of(s),
            qualified_name=getattr(s, "qualified_name", ""),
            executes_at=getattr(s, "executes_at", "") or "",
            depends_on=incoming[key_of(s)],
            guarded_by=guarded[key_of(s)],
        )
        for s in steps
    }

    if step_registry:
        _add_produces_edges(planned, step_registry, plan.process_qualified_name,
                            max_fetch_cost, max_compute_cost)

    # Recomputed after PRODUCES folding, not from `incoming`: a step with no
    # AUTHORED predecessor can still gain one here, and a plan that still
    # called it an entry point would be wrong about what runs first.
    plan.entry_points = [k for k, v in planned.items() if not v.depends_on]
    plan.steps = _topological(planned, plan.process_qualified_name)
    return plan


def _add_produces_edges(
    planned: dict, step_registry: Mapping[str, Any], process_name: str,
    max_fetch_cost: str | None, max_compute_cost: str | None,
) -> None:
    """Fold `PRODUCES`/precondition edges into the authored graph, in place.

    Answers the same question `prerequisite_resolver.resolve` asks — does a
    step's precondition already have its producer running first? — but
    structurally: this graph is built once per definition and reused for
    every entity it surveys, so there is no `registry`/`entity` here to check
    stored data against, and none of the resolver's runtime stop rules (a
    snapshot's `nothing_found`, a chain already run this survey) apply. What
    the graph itself can answer — is the producer even one of this
    definition's steps, and does its declared cost fit the tier the demanding
    step was authored at — is exactly what this adds, with the two
    corresponding build-time errors instead of the resolver's proposal.

    One flat pass over every step, not a recursive walk: `PRODUCES` and
    `PRECONDITIONS` are static declarations, so a producer's OWN precondition
    edges are added when this pass reaches the producer's entry — same graph,
    same pass, no separate recursion needed. A cycle across several steps
    (A's producer is B, B's producer is A) is not rejected here; it is left
    to `_topological`, which already raises `CyclicPlanError` for exactly
    this shape and is the one place that already gets tested for it.
    """
    from resource_explorer.surveyors import prerequisite_resolver, step_preconditions

    def ancestors(key: str) -> set:
        """Every step already reachable from `key` by a `depends_on` chain —
        authored edges and any PRODUCES edge already folded in earlier in
        this same pass."""
        seen: set = set()
        stack = list(planned[key].depends_on) if key in planned else []
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            if dep in planned:
                stack.extend(planned[dep].depends_on)
        return seen

    for key in list(planned):
        info = step_registry.get(key)
        if info is None:
            continue
        requires_context = dict(getattr(info, "requires_context", None) or {})
        if not requires_context:
            continue
        budget = prerequisite_resolver.Budget.for_step(info, max_fetch_cost, max_compute_cost)
        for name in requires_context:
            entry = step_preconditions.PRECONDITIONS.get(name)
            if entry is None:
                # Unknown precondition name. The runtime check
                # (`step_preconditions.evaluate`/`unmet`) already logs this
                # loudly and runs the step anyway; nothing structural to add
                # for a name that names nothing.
                continue
            producer = entry.produced_by()
            if not producer or producer == key:
                # No declared producer (a dead end the runtime check reports
                # honestly), or a step gating on the table it writes itself —
                # neither is an edge this plan can add.
                continue
            if producer not in planned:
                raise MissingPrerequisiteError(
                    f"{process_name or 'this definition'}: step {key!r} needs "
                    f"{name!r}, produced by {producer!r}, but {producer!r} is "
                    "not one of this definition's own steps. Prefect can only "
                    "schedule steps this definition authored — add "
                    f"{producer!r} to the definition, or run this definition "
                    "through the local execution loop, which can auto-run or "
                    "propose an out-of-definition producer."
                )
            if producer in ancestors(key):
                continue  # already runs first, via an authored or folded edge
            producer_info = step_registry.get(producer)
            crossed = (prerequisite_resolver._exceeds(budget, producer_info)
                       if producer_info is not None else "")
            if crossed:
                raise PrerequisiteTierError(
                    f"{process_name or 'this definition'}: step {key!r} needs "
                    f"{name!r}, produced by {producer!r}, which {crossed}. "
                    "Widen this definition's tier, author the two steps into "
                    "definitions at the same tier, or run this definition "
                    "through the local execution loop, where crossing a tier "
                    "becomes a proposal the user confirms rather than a "
                    "build-time error."
                )
            if producer not in planned[key].depends_on:
                planned[key].depends_on.append(producer)


def _topological(planned: dict, process_name: str) -> list:
    """Steps ordered so every dependency precedes its dependents.

    Kahn's algorithm, with ties broken by the order the steps were declared so
    a linear definition plans in exactly the order it was authored — the
    property that makes this change a no-op on every definition that exists
    today.
    """
    order = {key: i for i, key in enumerate(planned)}
    remaining = {k: list(v.depends_on) for k, v in planned.items()}
    out: list = []
    while remaining:
        ready = sorted((k for k, deps in remaining.items()
                        if not any(d in remaining for d in deps)),
                       key=lambda k: order[k])
        if not ready:
            raise CyclicPlanError(
                f"{process_name or 'definition'} contains a cycle among steps: "
                f"{sorted(remaining)}"
            )
        for key in ready:
            out.append(planned[key])
            del remaining[key]
    return out


def serialise(plan: ExecutionPlan) -> list:
    """The plan as plain dicts, for handing to a Prefect flow.

    Kept here rather than in the flow so the flow takes data it does not have
    to understand the shape of, and so the wire format is versioned with the
    thing that produces it.
    """
    return [{"step_key": s.step_key, "qualified_name": s.qualified_name,
             "executes_at": s.executes_at, "depends_on": list(s.depends_on),
             "guarded_by": dict(s.guarded_by)}
            for s in plan.steps]
