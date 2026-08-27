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
