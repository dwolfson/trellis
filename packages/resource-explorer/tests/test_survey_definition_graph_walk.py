"""The reader walks a graph, not a line.

`_parse_graph` followed one outgoing edge and raised
UnsupportedSurveyDefinitionError on a second. That refusal was honest while
nothing could run a branch, but it made a branching definition *unreadable* as
well as unrunnable — it could not be displayed, diffed against its authored
document, or repaired. With the plan and the Prefect flow both able to express
and run one, the refusal was the last thing in the way.

Cycles still raise, and the distinction is the point: a branch is a shape RE
can order, a cycle is one that cannot be ordered at all, and any order for it
would be a fiction.
"""
import pytest

from resource_explorer.surveyors.survey_definition_reader import (
    UnsupportedSurveyDefinitionError,
    _walk_graph,
)


def _nodes(*guids):
    return {g: {"guid": g} for g in guids}


def test_a_linear_chain_keeps_exactly_its_old_order():
    """A linear chain's topological order is unique, so the new walk returns
    what the old one did — the regression guarantee for every definition that
    exists today."""
    edges = {"a": ["b"], "b": ["c"]}
    ordered, unreachable = _walk_graph(edges, _nodes("a", "b", "c"), "a", "P")
    assert ordered == ["a", "b", "c"]
    assert unreachable == set()


def test_a_branch_is_ordered_instead_of_refused():
    edges = {"t": ["deep", "quick"], "deep": ["join"], "quick": ["join"]}
    ordered, _ = _walk_graph(edges, _nodes("t", "deep", "quick", "join"), "t", "P")
    assert ordered[0] == "t"
    assert ordered[-1] == "join"
    assert set(ordered) == {"t", "deep", "quick", "join"}


def test_a_join_comes_after_both_of_its_upstreams():
    """Topological, not merely reachable: a step must never precede something
    it depends on, or the order is not an order."""
    edges = {"t": ["deep", "quick"], "deep": ["join"], "quick": ["join"]}
    ordered, _ = _walk_graph(edges, _nodes("t", "deep", "quick", "join"), "t", "P")
    assert ordered.index("join") > ordered.index("deep")
    assert ordered.index("join") > ordered.index("quick")


def test_branch_order_is_deterministic_and_follows_declaration():
    """Two runs of the same definition must list its steps the same way, or a
    document-versus-Egeria diff reports drift that is only sort order."""
    edges = {"t": ["b", "a"]}
    nodes = _nodes("t", "a", "b")
    first = _walk_graph(edges, nodes, "t", "P")[0]
    assert first == _walk_graph(edges, nodes, "t", "P")[0]
    assert first == ["t", "b", "a"]   # declared order, not alphabetical


def test_a_cycle_still_raises():
    edges = {"a": ["b"], "b": ["a"]}
    with pytest.raises(UnsupportedSurveyDefinitionError) as exc:
        _walk_graph(edges, _nodes("a", "b"), "a", "P")
    assert "cycle" in str(exc.value)


def test_a_cycle_downstream_of_a_valid_prefix_still_raises():
    """Ordering the reachable prefix and stopping would run part of a survey
    and report on all of it."""
    edges = {"a": ["b"], "b": ["c"], "c": ["b"]}
    with pytest.raises(UnsupportedSurveyDefinitionError):
        _walk_graph(edges, _nodes("a", "b", "c"), "a", "P")


def test_unreachable_steps_are_reported_not_dropped():
    """Previously the walk simply never arrived at these: a step present in the
    definition, absent from every report, indistinguishable from one never
    authored."""
    edges = {"a": ["b"]}
    ordered, unreachable = _walk_graph(edges, _nodes("a", "b", "orphan"), "a", "P")
    assert ordered == ["a", "b"]
    assert unreachable == {"orphan"}


def test_a_definition_with_no_first_step_orders_nothing():
    ordered, unreachable = _walk_graph({}, _nodes("a"), None, "P")
    assert ordered == []
    assert unreachable == {"a"}


def test_a_diamond_visits_each_step_once():
    """Two paths reach `join`; it must appear once, not twice."""
    edges = {"t": ["l", "r"], "l": ["join"], "r": ["join"]}
    ordered, _ = _walk_graph(edges, _nodes("t", "l", "r", "join"), "t", "P")
    assert len(ordered) == len(set(ordered)) == 4


def test_every_live_definition_reads_back_to_its_authored_order():
    """Against the real documents, not fixtures. If the walk reordered
    anything, what runs today would change."""
    from resource_explorer.surveyors.survey_definition_docs import documented_definitions
    from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader

    docs = documented_definitions()
    try:
        reader = SurveyDefinitionReader()
        candidates = reader.find_candidate_process_guids("Git Repository")
    except Exception as exc:                      # pragma: no cover
        pytest.skip(f"Egeria unreachable: {type(exc).__name__}")
    if not candidates:                            # pragma: no cover
        pytest.skip("no live Survey Definitions")

    for cand in candidates:
        name = cand["qualified_name"].split("::")[-1]
        if name not in docs:
            continue
        live = [s.re_analysis_step for s in reader.fetch(cand["guid"]).steps]
        assert live == docs[name].steps, name
