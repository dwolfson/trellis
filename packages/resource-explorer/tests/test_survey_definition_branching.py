"""Branching must survive the reconciler.

`NextGovernanceActionProcessStep` is MULTI_LINK by design — several next-steps
under different guards is how Egeria expresses branching, and it is also why
Dr.Egeria's Link commands duplicate rather than merge on re-run. The reconciler
exists to strip those duplicates.

Keyed on (previous, next) alone it could not tell the two apart: `A -> B
guard=passed` and `A -> B guard=failed` read as one edge duplicated, and the
second was deleted. Those are two different edges — the pair of them IS the
branch. So the reconciler deleted exactly the thing the multi-link relationship
exists to express, on every recovery, silently.
"""
from resource_explorer.surveyors import survey_definition_docs as D
from resource_explorer.surveyors.survey_definition_reconciler import (
    UNCONDITIONAL_GUARD,
    compute_expected_edges,
    diff_links,
    expected_edges_from_document,
)

GROUP = "S"


def _qn(key: str) -> str:
    return f"GovActionProcessStep::{GROUP}::{key}"


def _live(prev: str, nxt: str, guard: str, guid: str) -> dict:
    return {"previousProcessStep": {"uniqueName": _qn(prev)},
            "nextProcessStep": {"uniqueName": _qn(nxt)},
            "guard": guard, "nextProcessStepLinkGUID": guid}


def _doc(*links) -> D.DefinitionDoc:
    return D.DefinitionDoc(process=GROUP, steps=["a", "b", "c"], links=list(links))


def test_two_edges_differing_only_by_guard_are_both_kept():
    """The regression this file exists for."""
    expected = expected_edges_from_document(
        GROUP, _doc(("a", "b", "passed"), ("a", "c", "failed")))
    live = [_live("a", "b", "passed", "g1"), _live("a", "c", "failed", "g2")]

    result = diff_links(live, expected, "GovActionProcess::S")

    assert result.to_remove == []
    assert result.kept == 2


def test_a_true_duplicate_is_still_removed():
    """A copy left by a non-idempotent Link command is identical in all three
    values, so matching on all three removes exactly what it should."""
    expected = expected_edges_from_document(GROUP, _doc(("a", "b", "passed")))
    live = [_live("a", "b", "passed", "g1"), _live("a", "b", "passed", "g2")]

    result = diff_links(live, expected, "GovActionProcess::S")

    assert result.removed_duplicate == 1
    assert result.kept == 1
    assert result.to_remove[0].link_guid == "g2"   # the first match is kept


def test_an_edge_with_a_guard_nobody_authored_is_stale():
    """Same pair, different guard, not in the document — a leftover from a
    prior branch that was edited away."""
    expected = expected_edges_from_document(GROUP, _doc(("a", "b", "passed")))
    live = [_live("a", "b", "passed", "g1"), _live("a", "b", "withdrawn", "g2")]

    result = diff_links(live, expected, "GovActionProcess::S")

    assert result.removed_stale == 1
    assert result.to_remove[0].guard == "withdrawn"


def test_a_missing_guard_on_a_live_edge_reads_as_unconditional():
    """Absent has always meant unconditional here, not a distinct fourth
    state — otherwise every pre-existing edge would read as stale."""
    expected = expected_edges_from_document(GROUP, _doc(("a", "b", UNCONDITIONAL_GUARD)))
    live = [{"previousProcessStep": {"uniqueName": _qn("a")},
             "nextProcessStep": {"uniqueName": _qn("b")},
             "nextProcessStepLinkGUID": "g1"}]

    assert diff_links(live, expected, "GovActionProcess::S").to_remove == []


def test_the_linear_fallback_agrees_with_a_linear_document():
    """Every committed definition is linear today, so the document-derived set
    and the step-list approximation must be identical — otherwise this change
    would have rewritten what gets deleted on real data."""
    doc = _doc(("a", "b", UNCONDITIONAL_GUARD), ("b", "c", UNCONDITIONAL_GUARD))
    assert expected_edges_from_document(GROUP, doc) == \
        compute_expected_edges(GROUP, ["a", "b", "c"])


def test_the_linear_fallback_would_delete_a_branch():
    """Why reconcile_step_links prefers the document. This is not a bug in the
    fallback — a step list cannot express a branch — it is why it must not be
    the source when a document exists."""
    live = [_live("a", "b", "passed", "g1"), _live("a", "c", "failed", "g2")]
    linear = compute_expected_edges(GROUP, ["a", "b", "c"])

    result = diff_links(live, linear, "GovActionProcess::S")

    assert result.removed_total == 2   # both branch edges destroyed


def test_every_committed_definition_reconciles_to_a_no_op():
    """The real documents, against a live graph that already matches them.
    A fully-reconciled process must produce an empty removal list every time."""
    for name, doc in D.documented_definitions().items():
        expected = expected_edges_from_document(name, doc)
        live = [{"previousProcessStep": {"uniqueName": f"GovActionProcessStep::{name}::{p}"},
                 "nextProcessStep": {"uniqueName": f"GovActionProcessStep::{name}::{n}"},
                 "guard": g, "nextProcessStepLinkGUID": f"{p}->{n}"}
                for p, n, g in doc.links]
        result = diff_links(live, expected, f"GovActionProcess::{name}")
        assert result.to_remove == [], f"{name} would lose {result.removed_total} edge(s)"
        assert result.kept == len(doc.links)
