"""Phase 2 — the architecture proposal, as annotations.

docs/architecture-recovery-report-then-curate.md §5. What is worth pinning is
not the annotation-building mechanics but the promises the design makes: that a
proposal is an observation and never an assertion, that projecting for
legibility loses nothing, and that absent data is reported as absent rather than
as zero.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.surveyors.arch_recovery.proposal import (
    MAX_NAMED_COMPONENTS,
    TYPE_CLUSTERS,
    TYPE_COMPONENT,
    TYPE_STRUCTURE,
    TYPE_SUMMARY,
    build_proposal_annotations,
)


class _Registry:
    """Only the two methods the builder touches."""

    def __init__(self, clusters=()):
        self._clusters = list(clusters)

    def query_finding_scopes(self, slug, kind, check_name=None):
        if kind == "architecture_blueprints":
            return list(self._clusters)
        return []


def _component(path, depth=0, **kw):
    return {
        "path": path, "name": kw.get("name", path), "type": kw.get("type", "Software Service"),
        "confidence": kw.get("confidence", 70), "perspective": kw.get("perspective", "physical"),
        "proposed_by": kw.get("proposed_by", ["spring"]), "depth": depth,
        "parent_path": kw.get("parent_path", ""), "evidence": kw.get("evidence", []),
        "structural": kw.get("structural", False),
    }


def _reader(projected, full, interfaces=()):
    def read(registry, slug, max_depth=None):
        base = {"interfaces": list(interfaces)}
        return {**base, "components": list(full if max_depth is None else projected)}
    return read


class TestItReportsRatherThanAsserts:
    def test_a_component_annotation_says_it_is_a_proposal(self, ):
        anns = build_proposal_annotations(
            _Registry(), "p",
            results_reader=_reader([_component("a")], [_component("a")]),
        )
        comp = [a for a in anns if a.annotation_type_name == TYPE_COMPONENT]
        assert len(comp) == 1
        # The whole point of report-then-curate: an annotation is what one dated
        # analysis believed, never a claim that the component exists.
        assert "not an assertion" in comp[0].explanation
        assert "Proposed component" in comp[0].summary

    def test_the_four_kinds_are_individually_named(self):
        # Without annotation_type_name they all derive one per-step name and a
        # curator cannot tell a proposed component from the structural payload.
        anns = build_proposal_annotations(
            _Registry(clusters=["c1"]), "p",
            results_reader=_reader([_component("a")], [_component("a")]),
        )
        names = {a.annotation_type_name for a in anns}
        assert names == {TYPE_COMPONENT, TYPE_STRUCTURE, TYPE_CLUSTERS, TYPE_SUMMARY}

    def test_a_component_with_no_type_is_reported_as_undetermined(self):
        # Not defaulted into a plausible-looking guess — "nothing matched the
        # 13-value vocabulary" is a real state.
        anns = build_proposal_annotations(
            _Registry(), "p",
            results_reader=_reader([_component("a", type=None)], [_component("a", type=None)]),
        )
        comp = next(a for a in anns if a.annotation_type_name == TYPE_COMPONENT)
        assert comp.candidate_classifications == []
        assert "type not determined" in comp.summary


class TestProjectionLosesNothing:
    def test_the_full_hierarchy_survives_projection(self):
        projected = [_component("a")]
        full = [_component("a"), _component("a/b", depth=1), _component("a/b/c", depth=2)]
        anns = build_proposal_annotations(
            _Registry(), "p", results_reader=_reader(projected, full),
        )
        assert len([a for a in anns if a.annotation_type_name == TYPE_COMPONENT]) == 1
        struct = next(a for a in anns if a.annotation_type_name == TYPE_STRUCTURE)
        hierarchy = json.loads(struct.resource_properties["hierarchy_json"])
        assert [h["path"] for h in hierarchy] == ["a", "a/b", "a/b/c"], (
            "projection decides what is NAMED; it must not decide what is RECORDED"
        )

    def test_grouping_nodes_stay_flagged_and_are_never_named(self):
        # scope_hierarchy refuses to emit derived ancestors as components
        # because that would invent evidence; §3 requires a grouping node
        # render as a grouping node. Erasing the flag here undoes both.
        full = [_component("a"), _component("grp", structural=True, type="", confidence=0)]
        anns = build_proposal_annotations(
            _Registry(), "p", results_reader=_reader(full, full),
        )
        named = [a for a in anns if a.annotation_type_name == TYPE_COMPONENT]
        assert [a.summary.split(": ")[1].split(" —")[0] for a in named] == ["a"]

        struct = next(a for a in anns if a.annotation_type_name == TYPE_STRUCTURE)
        hierarchy = json.loads(struct.resource_properties["hierarchy_json"])
        assert [h["structural"] for h in hierarchy] == [False, True]
        assert struct.resource_properties["structural_node_count"] == 1

    def test_the_naming_cap_is_reported_not_silent(self):
        # A silent truncation reads as "these are all the components".
        full = [_component(f"c{i}") for i in range(MAX_NAMED_COMPONENTS + 25)]
        anns = build_proposal_annotations(
            _Registry(), "p", results_reader=_reader(full, full),
        )
        named = [a for a in anns if a.annotation_type_name == TYPE_COMPONENT]
        assert len(named) == MAX_NAMED_COMPONENTS
        summary = next(a for a in anns if a.annotation_type_name == TYPE_SUMMARY)
        assert summary.resource_properties["components_not_named"] == 25
        assert "not named" in summary.summary


class TestPortsAndWiresComeFromInterfaces:
    """The reader returns `interfaces`, NOT top-level `ports`/`wires`.

    The first version of this module read the IR's field names against the
    reader's result, got [] from both, and published "0 port(s), 0 wire(s)" for
    a repo with real ports and wires recorded. Reporting zero for data that
    exists is the failure the whole surrounding design exists to prevent.
    """

    def test_ports_and_wires_are_extracted_from_interface_groups(self):
        interfaces = [{
            "components": [{"name": "svc", "ports": [{"port": 8080}, {"port": 9090}]}],
            "wires": [{"source": "svc", "target": "db", "protocol": "JDBC"}],
        }]
        anns = build_proposal_annotations(
            _Registry(), "p",
            results_reader=_reader([_component("svc")], [_component("svc")], interfaces),
        )
        struct = next(a for a in anns if a.annotation_type_name == TYPE_STRUCTURE)
        ports = json.loads(struct.resource_properties["ports_json"])
        wires = json.loads(struct.resource_properties["wires_json"])
        assert len(ports) == 2 and ports[0]["component"] == "svc"
        assert len(wires) == 1 and wires[0]["protocol"] == "JDBC"
        assert "2 port(s), 1 wire(s)" in struct.summary

    def test_genuinely_absent_interfaces_report_zero(self):
        # Zero is the right answer when there is nothing — what must not happen
        # is zero because we read the wrong key.
        anns = build_proposal_annotations(
            _Registry(), "p",
            results_reader=_reader([_component("a")], [_component("a")], interfaces=[]),
        )
        struct = next(a for a in anns if a.annotation_type_name == TYPE_STRUCTURE)
        assert "0 port(s), 0 wire(s)" in struct.summary


class TestNothingDerived:
    def test_no_components_publishes_no_proposal(self):
        # An empty proposal would be an annotation asserting nothing was found,
        # which is a claim the caller has not asked to make. The recovery
        # surveyor's own summary already reports "no components detected".
        assert build_proposal_annotations(
            _Registry(), "p", results_reader=_reader([], []),
        ) == []


class TestSummaryCarriesProvenance:
    def test_analyzer_version_is_published(self):
        # §6.2: without analyzerVersion, a metric that moves between two runs is
        # ambiguous — did the code change, or did the detector improve?
        anns = build_proposal_annotations(
            _Registry(), "p", results_reader=_reader([_component("a")], [_component("a")]),
        )
        summary = next(a for a in anns if a.annotation_type_name == TYPE_SUMMARY)
        assert summary.resource_properties["analyzerVersion"]
        assert summary.resource_properties["analyzerName"]
        assert summary.resource_properties["projection_depth"] == 1
