"""The plan is where a Survey Definition stops being a list and becomes a graph.

RE should not be a workflow engine. `survey_definition_executor` walked
`survey_def.steps` in its own `while` loop and dispatched single steps to
Prefect — RE as sequencer, Prefect as task runner, the inversion of what it
should be. The thing that forced it: `SurveyDefinition.steps` is a flat list
produced by walking a single chain, which is also why the reader raises on
branching, while the real graph sat unused beside it in `.links`.

This module builds the graph. It evaluates nothing: a guard is recorded and
carried, never decided, because deciding it here would rebuild the engine in
the file whose purpose is to stop RE from being one.
"""
from dataclasses import dataclass, field

import pytest

from resource_explorer.surveyors.survey_execution_plan import (
    CyclicPlanError,
    MissingPrerequisiteError,
    PrerequisiteTierError,
    build_plan,
    serialise,
)


@dataclass
class FakeStep:
    guid: str
    re_analysis_step: str
    qualified_name: str = ""
    executes_at: str = "resource-explorer"


@dataclass
class FakeLink:
    previous_guid: str
    next_guid: str
    guard: str = "Any"


@dataclass
class FakeDefinition:
    qualified_name: str = "GovActionProcess::T"
    steps: list = field(default_factory=list)
    links: list = field(default_factory=list)


def _linear(n: int) -> FakeDefinition:
    steps = [FakeStep(guid=f"g{i}", re_analysis_step=f"s{i}") for i in range(n)]
    links = [FakeLink(f"g{i}", f"g{i+1}") for i in range(n - 1)]
    return FakeDefinition(steps=steps, links=links)


def test_a_linear_definition_plans_in_the_order_it_was_authored():
    """The property that makes this a no-op on every definition that exists:
    ties in the topological sort break on declaration order."""
    plan = build_plan(_linear(4))
    assert [s.step_key for s in plan.steps] == ["s0", "s1", "s2", "s3"]
    assert plan.entry_points == ["s0"]
    assert plan.branches is False


def test_dependencies_come_from_links_not_from_list_order():
    """A definition whose links disagree with its list order must follow the
    links — they are the declaration; the list order is an artefact."""
    steps = [FakeStep(guid="a", re_analysis_step="a"),
             FakeStep(guid="b", re_analysis_step="b"),
             FakeStep(guid="c", re_analysis_step="c")]
    # authored c -> a -> b, listed a, b, c
    links = [FakeLink("c", "a"), FakeLink("a", "b")]
    plan = build_plan(FakeDefinition(steps=steps, links=links))
    assert [s.step_key for s in plan.steps] == ["c", "a", "b"]
    assert plan.by_key["a"].depends_on == ["c"]


def test_a_branch_is_planned_rather_than_refused():
    """The reader raises on this shape. The plan represents it."""
    steps = [FakeStep(guid=g, re_analysis_step=g) for g in ("triage", "deep", "quick")]
    links = [FakeLink("triage", "deep", "needs_deep"),
             FakeLink("triage", "quick", "good_enough")]
    plan = build_plan(FakeDefinition(steps=steps, links=links))
    assert plan.branches is True
    assert plan.by_key["deep"].guarded_by == {"triage": "needs_deep"}
    assert plan.by_key["quick"].guarded_by == {"triage": "good_enough"}
    assert plan.by_key["deep"].conditional and not plan.by_key["triage"].conditional


def test_an_unconditional_edge_is_not_recorded_as_a_guard():
    """`Any` means "always follow" — recording it as a condition would make
    every ordinary step look conditional and skippable."""
    plan = build_plan(_linear(2))
    assert plan.by_key["s1"].guarded_by == {}
    assert plan.by_key["s1"].depends_on == ["s0"]


def test_a_join_waits_for_both_sides():
    steps = [FakeStep(guid=g, re_analysis_step=g) for g in ("a", "b", "c", "join")]
    links = [FakeLink("a", "b"), FakeLink("a", "c"),
             FakeLink("b", "join"), FakeLink("c", "join")]
    plan = build_plan(FakeDefinition(steps=steps, links=links))
    assert sorted(plan.by_key["join"].depends_on) == ["b", "c"]
    order = [s.step_key for s in plan.steps]
    assert order.index("join") > max(order.index("b"), order.index("c"))


def test_a_cycle_raises_rather_than_planning_part_of_the_survey():
    """A partial plan would run some steps and report on the whole definition."""
    steps = [FakeStep(guid=g, re_analysis_step=g) for g in ("a", "b")]
    links = [FakeLink("a", "b"), FakeLink("b", "a")]
    with pytest.raises(CyclicPlanError):
        build_plan(FakeDefinition(steps=steps, links=links))


def test_a_definition_with_no_links_falls_back_to_list_order():
    """Older definitions, or ones whose links were lost. An inference, and the
    module says so in a log rather than presenting it as a declaration."""
    steps = [FakeStep(guid=f"g{i}", re_analysis_step=f"s{i}") for i in range(3)]
    plan = build_plan(FakeDefinition(steps=steps, links=[]))
    assert [s.step_key for s in plan.steps] == ["s0", "s1", "s2"]
    assert plan.by_key["s1"].depends_on == ["s0"]


def test_a_link_naming_a_step_outside_the_definition_is_ignored_not_fatal():
    steps = [FakeStep(guid="a", re_analysis_step="a")]
    plan = build_plan(FakeDefinition(steps=steps, links=[FakeLink("a", "elsewhere")]))
    assert [s.step_key for s in plan.steps] == ["a"]


def test_an_empty_definition_plans_to_nothing():
    plan = build_plan(FakeDefinition(steps=[], links=[]))
    assert plan.steps == [] and plan.entry_points == []


def test_serialise_carries_exactly_what_the_flow_needs():
    steps = [FakeStep(guid=g, re_analysis_step=g, qualified_name=f"QN::{g}")
             for g in ("triage", "deep")]
    links = [FakeLink("triage", "deep", "needs_deep")]
    rows = serialise(build_plan(FakeDefinition(steps=steps, links=links)))
    assert rows[0]["step_key"] == "triage" and rows[0]["depends_on"] == []
    assert rows[1] == {"step_key": "deep", "qualified_name": "QN::deep",
                       "executes_at": "resource-explorer",
                       "depends_on": ["triage"],
                       "guarded_by": {"triage": "needs_deep"}}


# ── PRODUCES edges (design §17.1's Prefect-side gap) ────────────────────────
#
# Same technique test_prerequisite_resolver.py uses: a constructed registry
# and a monkeypatched `step_produces._registries`/`step_preconditions.
# PRECONDITIONS`, so these pin the ALGORITHM in `_add_produces_edges` rather
# than any real step's declared cost or table.


def _precondition(name, table, monkeypatch):
    from resource_explorer.surveyors import step_preconditions as sp

    monkeypatch.setitem(sp.PRECONDITIONS, name, sp.Precondition(
        sp._needs_rows(table, name), table=table))


@pytest.fixture
def produces_world(monkeypatch):
    """`consumer` needs `producer`'s table. Both api/low, so nothing here
    should ever cross a tier by default — each test that wants a tier
    mismatch changes exactly one cost."""
    from resource_explorer.surveyors import step_produces
    from resource_explorer.surveyors.repo_survey_definition_adapter import StepInfo

    registry = {
        "consumer": StepInfo("consumer", None, "", [], fetch_cost="api", compute_cost="low",
                             requires_context={"needs_thing": "consumer reads producer's rows"}),
        "producer": StepInfo("producer", None, "", [], fetch_cost="api", compute_cost="low",
                             produces=("thing_table",)),
    }
    _precondition("needs_thing", "thing_table", monkeypatch)
    monkeypatch.setattr(step_produces, "_registries", lambda: {"repo": registry})
    return registry


def test_a_producer_already_scheduled_earlier_gets_no_new_edge(produces_world):
    """The authored graph already runs `producer` before `consumer` — nothing
    for PRODUCES-folding to add."""
    steps = [FakeStep(guid="producer", re_analysis_step="producer"),
             FakeStep(guid="consumer", re_analysis_step="consumer")]
    links = [FakeLink("producer", "consumer")]
    plan = build_plan(FakeDefinition(steps=steps, links=links),
                      step_registry=produces_world)
    assert plan.by_key["consumer"].depends_on == ["producer"]
    assert [s.step_key for s in plan.steps] == ["producer", "consumer"]


def _no_op_steps_and_link():
    """Two steps with nothing to do with `producer`/`consumer`, linked to each
    other, present only so `links` is non-empty. `build_plan` infers a chain
    from list order ONLY when a definition declares NO links at all — an
    empty `links` list on a 2+-step definition would silently create its own
    producer->consumer edge via that fallback, making a test pass for the
    wrong reason. A harmless real link elsewhere keeps the "genuinely no
    authored edge between these two" case honest."""
    return ([FakeStep(guid="noop_a", re_analysis_step="noop_a"),
             FakeStep(guid="noop_b", re_analysis_step="noop_b")],
            FakeLink("noop_a", "noop_b"))


def test_a_missing_producer_edge_is_added(produces_world):
    """No authored link between the two at all — PRODUCES-folding must add
    one, so Prefect schedules `producer` first."""
    noop_steps, noop_link = _no_op_steps_and_link()
    steps = [FakeStep(guid="producer", re_analysis_step="producer"),
             FakeStep(guid="consumer", re_analysis_step="consumer"), *noop_steps]
    plan = build_plan(FakeDefinition(steps=steps, links=[noop_link]),
                      step_registry=produces_world)
    assert plan.by_key["consumer"].depends_on == ["producer"]
    assert plan.by_key["producer"].depends_on == []
    order = [s.step_key for s in plan.steps]
    assert order.index("producer") < order.index("consumer")
    # Not a guard — an unconditional dependency, same as an authored `Any` edge.
    assert plan.by_key["consumer"].guarded_by == {}


def test_a_producer_outside_the_definition_is_a_build_time_error(produces_world):
    """`producer` is never one of this definition's own steps. Prefect cannot
    schedule a task for a step it was not authored with — this cannot be
    silently skipped the way the local resolver's dead-end can, because
    nothing here re-checks stored data at runtime."""
    steps = [FakeStep(guid="consumer", re_analysis_step="consumer")]
    with pytest.raises(MissingPrerequisiteError, match="producer"):
        build_plan(FakeDefinition(steps=steps, links=[]),
                  step_registry=produces_world)


def test_a_cycle_between_produces_edges_raises_the_existing_cycle_error(
    produces_world, monkeypatch,
):
    """`producer` itself needs `consumer`'s table — a cycle PRODUCES-folding
    creates rather than one authored directly. Reuses `CyclicPlanError`
    rather than inventing a second cycle error, since the failure mode (an
    unorderable graph) is identical."""
    from resource_explorer.surveyors import step_preconditions as sp
    from resource_explorer.surveyors.repo_survey_definition_adapter import StepInfo

    produces_world["producer"] = StepInfo(
        "producer", None, "", [], fetch_cost="api", compute_cost="low",
        produces=("thing_table",),
        requires_context={"needs_other": "producer reads consumer's rows"})
    produces_world["consumer"] = StepInfo(
        "consumer", None, "", [], fetch_cost="api", compute_cost="low",
        produces=("other_table",),
        requires_context={"needs_thing": "consumer reads producer's rows"})
    _precondition("needs_other", "other_table", monkeypatch)

    noop_steps, noop_link = _no_op_steps_and_link()
    steps = [FakeStep(guid="producer", re_analysis_step="producer"),
             FakeStep(guid="consumer", re_analysis_step="consumer"), *noop_steps]
    with pytest.raises(CyclicPlanError):
        build_plan(FakeDefinition(steps=steps, links=[noop_link]),
                  step_registry=produces_world)


def test_a_producer_above_the_definitions_tier_is_a_build_time_error(produces_world):
    """`producer` is raised to `download`, above `consumer`'s `api` tier. On
    the local path this becomes a proposal the user confirms; a Prefect plan
    has no such surface at build time, so this is the judgement call this
    change makes: fail loudly, naming the mismatch, rather than silently
    adding a tier the caller never budgeted for."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import StepInfo

    produces_world["producer"] = StepInfo(
        "producer", None, "", [], fetch_cost="download", compute_cost="low",
        produces=("thing_table",))
    noop_steps, noop_link = _no_op_steps_and_link()
    steps = [FakeStep(guid="producer", re_analysis_step="producer"),
             FakeStep(guid="consumer", re_analysis_step="consumer"), *noop_steps]
    with pytest.raises(PrerequisiteTierError, match="download"):
        build_plan(FakeDefinition(steps=steps, links=[noop_link]),
                  step_registry=produces_world)


def test_no_step_registry_keeps_the_old_behaviour(produces_world):
    """Omitting `step_registry` (every call site before this change) must not
    start folding PRODUCES edges in — the whole point of the parameter being
    optional. Authored here in the "wrong" order from PRODUCES' point of view
    (`consumer` before `producer`) precisely so a silent reorder would be
    caught: with no registry passed, `build_plan` has no way to know
    `consumer` needs `producer`'s table at all, so the authored order must
    survive untouched."""
    steps = [FakeStep(guid="producer", re_analysis_step="producer"),
             FakeStep(guid="consumer", re_analysis_step="consumer")]
    links = [FakeLink("consumer", "producer")]
    plan = build_plan(FakeDefinition(steps=steps, links=links))
    assert plan.by_key["producer"].depends_on == ["consumer"]
    assert [s.step_key for s in plan.steps] == ["consumer", "producer"]


def test_every_live_definition_plans_to_its_existing_order():
    """The regression guarantee, against the real documents rather than
    fixtures: if the plan reordered anything, this change would alter what
    runs today."""
    from resource_explorer.surveyors.survey_definition_docs import documented_definitions

    for name, doc in documented_definitions().items():
        steps = [FakeStep(guid=k, re_analysis_step=k) for k in doc.steps]
        links = [FakeLink(p, n, g) for p, n, g in doc.links]
        plan = build_plan(FakeDefinition(qualified_name=name, steps=steps, links=links))
        assert [s.step_key for s in plan.steps] == doc.steps, name
        assert plan.branches is False, name
