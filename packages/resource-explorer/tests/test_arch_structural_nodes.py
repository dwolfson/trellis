"""Structural nodes: the ancestors that make projection able to project.

`code_markers` emits a component per subtree with marker-rule hits, while
`parent_slug` comes from `build_hierarchy`, which holds every candidate subtree.
An intermediate directory whose children carry the markers is in the second set
and not the first, so children referenced a parent nobody stored. Measured
2026-08-24: milvus persisted 16 `code::` components, referenced 6 parents, and
0 of them existed — so `project_rows` returned 204 components at every depth.

These nodes close that gap WITHOUT inventing evidence: separate check_name, no
type, no confidence, and excluded from the recovered-component count.
"""
from __future__ import annotations

from resource_explorer.surveyors.arch_recovery import projection as P


def _rows(triples):
    return [{"path": p, "parent_path": par, "depth": d} for p, par, d in triples]


def test_the_milvus_shape_collapses_once_the_ancestor_exists():
    """The real case, reduced: five siblings under an unstored parent.

    Without the ancestor row every node is root-attached and projection is an
    identity function. With it, the five collapse to their group — which is the
    grouping milvus's own published architecture uses.
    """
    kids = [
        ("internal/distributed/datanode", "", 1),
        ("internal/distributed/mixcoord", "", 1),
        ("internal/distributed/proxy", "", 1),
        ("internal/distributed/querynode", "", 1),
        ("internal/distributed/streamingnode", "", 1),
    ]
    orphaned = _rows(kids)
    assert len(P.project_rows(orphaned, max_depth=0)) == 5, "precondition: orphans do not collapse"

    with_ancestor = _rows(
        [("internal/distributed", "", 0)]
        + [(p, "internal/distributed", 1) for p, _, _ in kids]
    )
    collapsed = P.project_rows(with_ancestor, max_depth=0)
    assert len(collapsed) == 1, f"expected the group to collapse to its ancestor, got {len(collapsed)}"
    assert collapsed[0]["path"] == "internal/distributed"

    # and nothing is lost — the full view still has every node
    assert len(P.project_rows(with_ancestor, max_depth=None)) == 6


def test_deeper_levels_still_resolve():
    """Depth must remain a dial, not an on/off switch."""
    rows = _rows([
        ("a", "", 0),
        ("a/b", "a", 1),
        ("a/b/c", "a/b", 2),
        ("a/b/d", "a/b", 2),
    ])
    assert len(P.project_rows(rows, max_depth=0)) == 1
    assert len(P.project_rows(rows, max_depth=None)) == 4
    mid = len(P.project_rows(rows, max_depth=1))
    assert 1 <= mid <= 4


class _StubRegistry:
    """Captures upsert_finding calls; everything else is a no-op."""

    def __init__(self):
        self.findings = []

    def upsert_finding(self, slug, kind, rows, surveyed_at="", scope_locator=""):
        for r in rows:
            self.findings.append({**r, "scope_locator": scope_locator, "_ts": surveyed_at})

    def upsert_metric(self, *a, **k):
        pass

    def query_findings_history_raw(self, slug, kind):
        """Every row this stub has captured, in `persist_ir`'s read shape.

        Real, not a no-op returning []: `_withdraw_vacated` reads history to
        decide what to withdraw, and a stub that always answers "no history"
        would make these tests pass while withdrawal was broken.
        """
        return [{**f, "check_name": f.get("check_name", ""),
                 "detail_json": f.get("detail"), "surveyed_at": f.get("_ts", "")}
                for f in self.findings]


def _component(slug, path, parent_slug=""):
    from resource_explorer.surveyors.arch_recovery.ir import Component, Identity
    return Component(
        slug=slug, name=path.rsplit("/", 1)[-1], type="Software Service",
        identity=Identity("module-path", path), files=[f"{path}/**"],
        confidence=85, confidence_level="Derived", perspective="logical",
        parent_slug=parent_slug, depth=path.count("/"),
    )


def test_persist_writes_a_structural_node_for_a_referenced_but_missing_ancestor():
    from resource_explorer.surveyors.arch_recovery.persist import persist_ir

    reg = _StubRegistry()
    comps = [
        _component("code::internal::distributed::datanode",
                   "internal/distributed/datanode", "code::internal::distributed"),
        _component("code::internal::distributed::proxy",
                   "internal/distributed/proxy", "code::internal::distributed"),
    ]
    persist_ir(reg, "demo", comps, [], "2026-08-24T00:00:00")

    structural = [f for f in reg.findings if f["check_name"] == "structural_node"]
    assert len(structural) == 1, f"expected exactly one ancestor row, got {len(structural)}"
    node = structural[0]
    assert node["detail"]["slug"] == "code::internal::distributed"
    assert node["detail"]["path"] == "internal/distributed"
    assert node["detail"]["structural"] is True


def test_a_structural_node_carries_no_type_and_no_confidence():
    """The constraint that made this a separate row kind at all.

    These ancestors have no marker evidence. Giving them a type or a score
    would invent evidence so a grouping could look like a finding — the exact
    failure `no metric, no number` (design §5) exists to prevent.
    """
    from resource_explorer.surveyors.arch_recovery.persist import persist_ir

    reg = _StubRegistry()
    persist_ir(reg, "demo",
               [_component("code::a::b", "a/b", "code::a")], [],
               "2026-08-24T00:00:00")
    node = next(f for f in reg.findings if f["check_name"] == "structural_node")
    assert node["confidence"] == 0
    assert node["detail"].get("type") in (None, "")
    assert "no evidence of its own" in node["summary"]


def test_an_ancestor_that_IS_a_component_gets_no_structural_row():
    """No duplication: only genuinely missing ancestors are synthesised."""
    from resource_explorer.surveyors.arch_recovery.persist import persist_ir

    reg = _StubRegistry()
    comps = [
        _component("code::a", "a"),
        _component("code::a::b", "a/b", "code::a"),
    ]
    persist_ir(reg, "demo", comps, [], "2026-08-24T00:00:00")
    assert [f for f in reg.findings if f["check_name"] == "structural_node"] == []
