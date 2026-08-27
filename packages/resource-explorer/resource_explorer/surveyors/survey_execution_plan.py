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
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

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
    """


def build_plan(survey_def) -> ExecutionPlan:
    """An ExecutionPlan from a SurveyDefinition.

    Falls back to the linear chain implied by `steps` when the definition
    carries no links at all — an older definition, or one whose links were
    lost. Stated in a log rather than assumed silently, because a chain
    inferred from list order is a guess about intent where real links are a
    declaration of it.
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
    plan.entry_points = [k for k, v in incoming.items() if not v]
    plan.steps = _topological(planned, plan.process_qualified_name)
    return plan


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
