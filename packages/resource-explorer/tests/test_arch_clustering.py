"""Candidate blueprint proposal (arch_recovery/clustering.py).

The rules these tests pin, all of which come from the design rather than from
the implementation: clustering is per §4.1 perspective; every signal reads a
boundary something declared; a component nothing groups stays ungrouped; and an
oversized cluster is reported rather than truncated or silently split.
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors.arch_recovery import clustering
from resource_explorer.surveyors.arch_recovery.clustering import Cluster


def _c(slug, scope=None, perspective="deployment", context=""):
    return {
        "slug": slug,
        "scope_locator": scope if scope is not None else slug,
        "perspective": perspective,
        "identity": {"method": "deployment-unit", "value": slug,
                     "deployment_context": context},
    }


class TestPerspectiveScoping:
    """§4.1's perspectives are not interchangeable views. The Phase 0 spike
    scored 16/16 on one repo and 1-of-10 on another purely by scoring a
    deployment detector against logical ground truth; mixing them inside one
    blueprint repeats that error."""

    def test_only_the_requested_perspective_is_clustered(self):
        comps = [_c("a/x", perspective="deployment"), _c("a/y", perspective="deployment"),
                 _c("b/x", perspective="logical"), _c("b/y", perspective="logical")]
        clusters = clustering.propose(comps, "deployment")
        assert all(m.startswith("a/") for c in clusters for m in c.members)

    def test_a_perspective_with_no_components_yields_nothing(self):
        assert clustering.propose([_c("a/x"), _c("a/y")], "logical") == []

    def test_components_of_another_perspective_are_ignored_not_reclassified(self):
        comps = [_c("a/x"), _c("a/y"), _c("z", perspective="physical")]
        assert "z" not in {m for c in clustering.propose(comps, "deployment") for m in c.members}


class TestGrouping:
    def test_siblings_group_together(self):
        comps = [_c("svc/a"), _c("svc/b"), _c("svc/c")]
        clusters = clustering.propose(comps, "deployment")
        assert len(clusters) == 1
        assert set(clusters[0].members) == {"svc/a", "svc/b", "svc/c"}

    def test_a_lone_component_is_left_unclustered(self):
        """No signal, no cluster — the same rule as design §5's 'no metric, no
        number'. A component swept into the nearest blueprint is a claim
        nothing measured."""
        comps = [_c("svc/a"), _c("svc/b"), _c("solo")]
        assert "solo" not in {m for c in clustering.propose(comps, "deployment") for m in c.members}

    def test_clusters_are_ordered_largest_first(self):
        comps = [_c("big/1"), _c("big/2"), _c("big/3"), _c("small/1"), _c("small/2")]
        sizes = [c.size for c in clustering.propose(comps, "deployment")]
        assert sizes == sorted(sizes, reverse=True)


class TestDeploymentContextSignal:
    """The scope locator keeps only the last path segment, so genaicomps' 203
    deployment components all read as one `docker_compose` stack while their
    `identity.deployment_context` records dozens of separate compose files. The
    boundary was declared; the locator discarded it."""

    def test_context_subdivides_a_cluster_the_locator_cannot(self):
        comps = [_c(f"docker_compose::s{i}", scope=f"docker_compose::s{i}",
                    context=f"comps/app{i % 3}/deployment/docker_compose")
                 for i in range(12)]
        clusters = clustering.propose(comps, "deployment")
        assert len(clusters) == 3
        assert all(c.size <= clustering.TARGET_CLUSTER_SIZE for c in clusters)

    def test_a_shared_context_does_not_split(self):
        """One real compose file with many services is one declared boundary."""
        comps = [_c(f"docker_compose::s{i}", context="comps/one/deployment/docker_compose")
                 for i in range(14)]
        clusters = clustering.propose(comps, "deployment")
        assert len(clusters) == 1
        assert clusters[0].oversized is True

    def test_components_without_a_context_still_cluster_by_locator(self):
        comps = [_c("svc/a"), _c("svc/b")]
        assert clustering.propose(comps, "deployment")[0].size == 2


class TestOversizedIsReportedNotHidden:
    def test_an_unsplittable_oversized_cluster_is_flagged(self):
        comps = [_c(f"flat::s{i}") for i in range(25)]
        clusters = clustering.propose(comps, "deployment")
        assert any(c.oversized for c in clusters)

    def test_an_oversized_cluster_keeps_every_member(self):
        """Never truncated: an arbitrarily cut blueprint is a different one."""
        comps = [_c(f"flat::s{i}") for i in range(25)]
        got = {m for c in clustering.propose(comps, "deployment") for m in c.members}
        assert len(got) == 25

    def test_a_cluster_within_the_goal_is_not_flagged(self):
        comps = [_c(f"svc/s{i}") for i in range(4)]
        assert not any(c.oversized for c in clustering.propose(comps, "deployment"))


class TestSubdivideRecursionBugFix:
    """Regression: `_build`'s recursive call in the `_subdivide`-succeeded
    branch used to pass 6 positional args into a 7-parameter function with
    no defaults (missing `by_scope_components`) — a live TypeError on any
    call. Unreached by every other test in this file because they all use
    scope shapes `scope_hierarchy.derive` genuinely cannot subdivide
    further (`flat::sN` has one ancestor level; a shared deployment context
    is tested via TestDeploymentContextSignal, which takes the by_context
    branch, not this one). Exercises `_build` directly rather than via
    `propose()`, since propose()'s own first pass already finds the finest
    qualifying split in one shot for realistic path hierarchies — this
    branch is about `_build`'s own recursive contract, not about proving a
    natural path into it through the full pipeline.
    """

    def test_a_second_level_of_subdivision_does_not_raise(self):
        scopes = ([f"pkg/sub{i}/leaf" for i in range(6)]
                  + [f"pkg/sub{i}/leaf2" for i in range(6)])
        by_scope = {s: [s] for s in scopes}
        by_scope_components = {s: [_c(s)] for s in scopes}
        # target_size=1 forces every group above to read as oversized,
        # deterministically driving execution into the branch that used to
        # crash, regardless of how propose() would naturally chunk this.
        clusters = clustering._build(
            "pkg", scopes, by_scope, by_scope_components,
            "deployment", target_size=1, depth_left=3,
        )
        assert {m for c in clusters for m in c.members} == set(scopes)

    def test_the_second_level_split_is_real_not_one_bucket(self):
        scopes = ([f"pkg/sub{i}/leaf" for i in range(6)]
                  + [f"pkg/sub{i}/leaf2" for i in range(6)])
        by_scope = {s: [s] for s in scopes}
        by_scope_components = {s: [_c(s)] for s in scopes}
        clusters = clustering._build(
            "pkg", scopes, by_scope, by_scope_components,
            "deployment", target_size=1, depth_left=3,
        )
        assert len(clusters) == 6  # one per pkg/subN, per _subdivide's own split


class TestWireDensitySignal:
    """Design §10 signal 2 — the fallback tried once every declared boundary
    (deployment context, scope hierarchy) is exhausted. `flat::sN` scopes
    are the same genuinely-unsplittable shape TestOversizedIsReportedNotHidden
    uses; the only difference here is that wires now exist between some of
    them."""

    @staticmethod
    def _wire(a, b):
        return {"source": f"flat::s{a}", "target": f"flat::s{b}"}

    def test_a_densely_wired_subset_clusters_even_though_the_locator_cannot_split_it(self):
        comps = [_c(f"flat::s{i}") for i in range(25)]
        # Every pair among s0..s9 wired — a fully-connected, densely-wired
        # subgraph within an otherwise flat, unsplittable set of 25.
        wires = [self._wire(a, b) for a in range(10) for b in range(a + 1, 10)]
        clusters = clustering.propose(comps, "deployment", wires=wires)
        wired = [c for c in clusters if c.signal == "wire-density"]
        assert len(wired) == 1
        assert set(wired[0].members) == {f"flat::s{i}" for i in range(10)}
        assert wired[0].size <= clustering.TARGET_CLUSTER_SIZE

    def test_components_with_no_wires_are_left_ungrouped(self):
        """'No signal, no cluster' applies to wire density too — a component
        no wire touches must not be swept into the nearest wired group."""
        comps = [_c(f"flat::s{i}") for i in range(25)]
        wires = [self._wire(a, b) for a in range(10) for b in range(a + 1, 10)]
        clustered = {m for c in clustering.propose(comps, "deployment", wires=wires)
                    for m in c.members}
        assert clustered == {f"flat::s{i}" for i in range(10)}

    def test_zero_wires_among_the_members_yields_no_split(self):
        """Without any connecting wire, wire-density must not invent a
        single bucket covering everyone — that would be indistinguishable
        from a real finding to a curator reading it."""
        comps = [_c(f"flat::s{i}") for i in range(25)]
        clusters = clustering.propose(comps, "deployment", wires=[])
        assert not any(c.signal == "wire-density" for c in clusters)
        assert any(c.oversized for c in clusters)  # falls through exactly as before wires existed

    def test_without_the_wires_kwarg_behaviour_is_unchanged(self):
        """Backward compatibility: every existing caller of propose() that
        never passes wires= must see identical behaviour to before this
        signal existed."""
        comps = [_c(f"flat::s{i}") for i in range(25)]
        with_none = clustering.propose(comps, "deployment")
        with_empty = clustering.propose(comps, "deployment", wires=None)
        assert [(c.name, tuple(sorted(c.members))) for c in with_none] == \
               [(c.name, tuple(sorted(c.members))) for c in with_empty]

    def test_wire_derived_clusters_respect_target_size(self):
        comps = [_c(f"flat::s{i}") for i in range(25)]
        # Fully connect ALL 25 — without a size bound this would merge into
        # one 25-member blob.
        wires = [self._wire(a, b) for a in range(25) for b in range(a + 1, 25)]
        clusters = clustering.propose(comps, "deployment", wires=wires,
                                      target_size=8)
        wired = [c for c in clusters if c.signal == "wire-density"]
        assert wired
        assert all(c.size <= 8 for c in wired)

    def test_deterministic_across_repeated_calls(self):
        comps = [_c(f"flat::s{i}") for i in range(25)]
        wires = [self._wire(a, b) for a in range(10) for b in range(a + 1, 10)]
        first = clustering.propose(comps, "deployment", wires=wires)
        second = clustering.propose(comps, "deployment", wires=wires)
        assert [(c.name, tuple(c.members)) for c in first] == \
               [(c.name, tuple(c.members)) for c in second]

    def test_self_wires_and_unresolved_endpoints_contribute_no_edge(self):
        comps = [_c(f"flat::s{i}") for i in range(3)]
        wires = [
            {"source": "flat::s0", "target": "flat::s0"},       # self-wire
            {"source": "flat::s1", "target": "ghost::unknown"},  # unresolved
        ]
        clusters = clustering.propose(comps, "deployment", wires=wires)
        assert not any(c.signal == "wire-density" for c in clusters)

    def test_only_tried_after_declared_boundaries_are_exhausted(self):
        """A deployment context is stronger evidence than a wire — a
        densely-wired set must still split by context first if the context
        split alone already meets the goal, with wire-density never
        consulted at that level."""
        comps = [
            {"slug": f"flat::s{i}", "scope_locator": f"flat::s{i}",
             "perspective": "deployment",
             "identity": {"deployment_context": "comps/one" if i < 5 else "comps/two"}}
            for i in range(10)
        ]
        wires = [self._wire(a, b) for a in range(10) for b in range(a + 1, 10)]
        # target_size=5: each context group (5 members) already meets the
        # goal on its own, so wire-density has nothing left to contribute.
        clusters = clustering.propose(comps, "deployment", wires=wires,
                                      target_size=5)
        assert not any(c.signal == "wire-density" for c in clusters)
        assert {c.name for c in clusters} == {"comps/one", "comps/two"}

    def test_wire_density_still_helps_within_an_oversized_context_group(self):
        """Signals compose per level: a deployment-context split narrows the
        problem, and wire-density can still refine further within a
        resulting group that is still over the goal on its own."""
        comps = [
            {"slug": f"flat::s{i}", "scope_locator": f"flat::s{i}",
             "perspective": "deployment",
             "identity": {"deployment_context": "comps/one" if i < 5 else "comps/two"}}
            for i in range(10)
        ]
        wires = [self._wire(a, b) for a in range(10) for b in range(a + 1, 10)]
        clusters = clustering.propose(comps, "deployment", wires=wires,
                                      target_size=4)
        assert any(c.signal == "wire-density" for c in clusters)


class TestSharedInterfaceSignal:
    """Design §10 signal 3 — the LAST fallback, tried only once deployment
    context, scope hierarchy, AND wire density have all found nothing
    further. `flat::sN` scopes reuse TestOversizedIsReportedNotHidden's
    genuinely-unsplittable shape; the difference here is a declared
    interface name shared by some of them."""

    @staticmethod
    def _port(scope, name):
        return {"component": f"flat::{scope}", "additionalProperties": {"interfaceName": name}}

    def test_components_sharing_a_declared_interface_name_cluster(self):
        comps = [_c(f"flat::s{i}") for i in range(25)]
        ports = [self._port(f"s{i}", "orders.OrderService") for i in range(6)]
        clusters = clustering.propose(comps, "deployment", ports=ports)
        shared = [c for c in clusters if c.signal == "shared-interface"]
        assert len(shared) == 1
        assert set(shared[0].members) == {f"flat::s{i}" for i in range(6)}

    def test_a_lone_interface_name_is_not_a_shared_signal(self):
        """One component presenting an interface nobody else presents is not
        evidence of a shared surface — 'no signal, no cluster' bars a
        one-member 'group'."""
        comps = [_c(f"flat::s{i}") for i in range(25)]
        ports = [self._port("s0", "orders.OrderService")]
        clusters = clustering.propose(comps, "deployment", ports=ports)
        assert not any(c.signal == "shared-interface" for c in clusters)

    def test_components_with_no_interface_are_left_ungrouped(self):
        comps = [_c(f"flat::s{i}") for i in range(25)]
        ports = [self._port(f"s{i}", "orders.OrderService") for i in range(6)]
        clustered = {m for c in clustering.propose(comps, "deployment", ports=ports)
                    for m in c.members}
        assert clustered == {f"flat::s{i}" for i in range(6)}

    def test_without_the_ports_kwarg_behaviour_is_unchanged(self):
        comps = [_c(f"flat::s{i}") for i in range(25)]
        with_none = clustering.propose(comps, "deployment")
        with_empty = clustering.propose(comps, "deployment", ports=None)
        assert [(c.name, tuple(sorted(c.members))) for c in with_none] == \
               [(c.name, tuple(sorted(c.members))) for c in with_empty]

    def test_wire_density_wins_when_both_signals_apply_to_the_same_group(self):
        """A wire is stronger evidence than a shared interface name — where
        the exact same subset is both densely wired AND shares a declared
        interface name, wire-density must claim it, never shared-interface."""
        comps = [_c(f"flat::s{i}") for i in range(25)]
        wires = [{"source": f"flat::s{a}", "target": f"flat::s{b}"}
                for a in range(10) for b in range(a + 1, 10)]
        ports = [self._port(f"s{i}", "orders.OrderService") for i in range(10)]
        clusters = clustering.propose(comps, "deployment", wires=wires, ports=ports)
        wired = [c for c in clusters if set(c.members) == {f"flat::s{i}" for i in range(10)}]
        assert len(wired) == 1
        assert wired[0].signal == "wire-density"
        assert not any(c.signal == "shared-interface" for c in clusters)

    def test_shared_interface_still_fires_where_wire_density_finds_nothing(self):
        """Signals compose per level, same as wire-density composes with
        deployment context: a context split narrows the problem, wire
        density finds nothing within the interface-only context group (no
        wires connect those scopes), and shared-interface still gets its
        turn there."""
        comps = [
            {"slug": f"flat::s{i}", "scope_locator": f"flat::s{i}",
             "perspective": "deployment",
             "identity": {"deployment_context": "comps/wired" if i < 5 else "comps/api"}}
            for i in range(10)
        ]
        wires = [{"source": f"flat::s{a}", "target": f"flat::s{b}"}
                for a in range(5) for b in range(a + 1, 5)]
        ports = (
            [self._port(f"s{i}", "orders.OrderService") for i in (5, 6, 7)]
            + [self._port("s8", "billing.BillingService")]
        )
        clusters = clustering.propose(comps, "deployment", wires=wires, ports=ports,
                                      target_size=3)
        assert any(c.signal == "wire-density" for c in clusters)
        shared = [c for c in clusters if c.signal == "shared-interface"]
        assert len(shared) == 1
        assert set(shared[0].members) == {"flat::s5", "flat::s6", "flat::s7"}

    def test_deterministic_across_repeated_calls(self):
        comps = [_c(f"flat::s{i}") for i in range(25)]
        ports = [self._port(f"s{i}", "orders.OrderService") for i in range(6)]
        first = clustering.propose(comps, "deployment", ports=ports)
        second = clustering.propose(comps, "deployment", ports=ports)
        assert [(c.name, tuple(c.members)) for c in first] == \
               [(c.name, tuple(c.members)) for c in second]

    def test_a_component_presenting_two_interfaces_goes_to_the_larger_group(self):
        comps = [_c(f"flat::s{i}") for i in range(25)]
        ports = (
            [self._port(f"s{i}", "orders.OrderService") for i in range(6)]
            + [self._port(f"s{i}", "billing.BillingService") for i in range(6, 8)]
            + [self._port("s0", "billing.BillingService")]  # s0 presents both
        )
        clusters = clustering.propose(comps, "deployment", ports=ports)
        shared = {c.name: set(c.members) for c in clusters if c.signal == "shared-interface"}
        orders_group = next(m for m in shared.values() if "flat::s1" in m)
        assert "flat::s0" in orders_group


class TestRollup:
    """The ~10 goal binds at every level. Splitting genaiexamples by deployment
    context produced 87 readable clusters — and 87 blueprints for one repo is no
    more usable than one blueprint of 546."""

    def test_many_clusters_roll_up_under_a_shared_prefix(self):
        flat = [Cluster(name=f"comps/app{i}/deployment", perspective="deployment",
                        members=[f"m{i}a", f"m{i}b"]) for i in range(20)]
        top = clustering.rollup(flat)
        assert len(top) == 1
        assert top[0].name == "comps"
        assert len(top[0].children) == 20

    def test_a_short_list_is_left_flat(self):
        flat = [Cluster(name=f"comps/app{i}", perspective="deployment", members=[f"m{i}"])
                for i in range(3)]
        assert clustering.rollup(flat) == flat

    def test_a_rollup_that_abstracts_nothing_is_not_added(self):
        """One bucket per cluster adds a level a reader steps through for no gain."""
        flat = [Cluster(name=f"top{i}/x", perspective="deployment", members=[f"m{i}"])
                for i in range(20)]
        assert clustering.rollup(flat) == flat

    def test_size_counts_through_children(self):
        parent = Cluster(name="p", perspective="deployment", children=[
            Cluster(name="a", perspective="deployment", members=["1", "2"]),
            Cluster(name="b", perspective="deployment", members=["3"]),
        ])
        assert parent.size == 3
        assert set(parent.all_members()) == {"1", "2", "3"}

    def test_a_parent_holds_children_rather_than_members(self):
        flat = [Cluster(name=f"comps/app{i}", perspective="deployment", members=[f"m{i}", f"n{i}"])
                for i in range(20)]
        top = clustering.rollup(flat)
        assert top[0].members == []
        assert top[0].children


class TestAssign:
    def test_assign_writes_the_blueprint_onto_members(self):
        comps = [_c("svc/a"), _c("svc/b")]
        clusters = clustering.propose(comps, "deployment")
        assert clustering.assign(comps, clusters) == 2
        assert {c["blueprint"] for c in comps} == {clusters[0].name}

    def test_unclustered_components_are_left_unassigned(self):
        """The renderer draws those ungrouped, which is the truthful picture."""
        comps = [_c("svc/a"), _c("svc/b"), _c("solo")]
        clustering.assign(comps, clustering.propose(comps, "deployment"))
        solo = [c for c in comps if c["slug"] == "solo"][0]
        assert not solo.get("blueprint")

    def test_assign_reaches_through_a_rollup(self):
        flat = [Cluster(name=f"comps/app{i}", perspective="deployment", members=[f"m{i}"])
                for i in range(20)]
        comps = [_c(f"m{i}") for i in range(20)]
        top = clustering.rollup(flat)
        assert clustering.assign(comps, top) == 20
        # The LEAF blueprint is what a component belongs to, not the rollup.
        assert comps[0]["blueprint"] == "comps/app0"


class TestDeterminism:
    def test_input_order_does_not_change_the_proposal(self):
        comps = [_c("a/1"), _c("a/2"), _c("b/1"), _c("b/2")]
        a = [(c.name, tuple(c.members)) for c in clustering.propose(comps, "deployment")]
        b = [(c.name, tuple(c.members)) for c in clustering.propose(list(reversed(comps)), "deployment")]
        assert a == b


class TestAffinityPromotesToComposition:
    """Dan's rule, 2026-08-29: *no affinity leads you to collections.* Where the
    members cohere there is evidence the containing thing exists, and a
    component is the honest carrier; where they are merely co-located, a
    Collection is.

    The bar is `coupling.COHESIVE_BAR`, reused rather than redefined — and
    measured to be robust: across 1,085 import_cohesion values from milvus,
    egeria and egeria-workspaces, only 2 fall between 0.3 and 0.7. The metric is
    bimodal, so the exact bar barely matters.
    """

    def _comps(self):
        return [_c("svc/a"), _c("svc/b"), _c("svc/c")]

    def test_without_cohesion_data_a_group_stays_a_collection(self):
        """The correct default: co-location says where things were declared,
        not that they belong to one another."""
        clusters = clustering.propose(self._comps(), "deployment")
        assert clusters[0].carrier == "collection"

    def test_low_cohesion_stays_a_collection(self):
        clusters = clustering.propose(self._comps(), "deployment", cohesion={"svc": 0.05})
        assert clusters[0].carrier == "collection"

    def test_high_cohesion_becomes_a_composition(self):
        clusters = clustering.propose(self._comps(), "deployment", cohesion={"svc": 0.98})
        assert clusters[0].carrier == "composition"
        assert clusters[0].composed_into == "svc"
        assert "import-cohesion" in clusters[0].signal

    def test_the_bar_is_couplings_own_constant_not_a_new_one(self):
        from resource_explorer.surveyors.arch_recovery import coupling
        just_over = clustering.propose(self._comps(), "deployment",
                                       cohesion={"svc": coupling.COHESIVE_BAR})
        just_under = clustering.propose(self._comps(), "deployment",
                                        cohesion={"svc": coupling.COHESIVE_BAR - 0.01})
        assert just_over[0].carrier == "composition"
        assert just_under[0].carrier == "collection"

    def test_a_cohesive_group_is_not_split_to_meet_the_presentation_goal(self):
        """Cohesion is the evidence that this is ONE thing. Splitting it to hit
        a display target would discard the signal that justified asserting it."""
        comps = [_c(f"svc/s{i}") for i in range(25)]
        clusters = clustering.propose(comps, "deployment", cohesion={"svc": 0.9})
        assert len(clusters) == 1
        assert clusters[0].oversized is False
        assert clusters[0].size == 25

    def test_assign_makes_members_sub_components_not_blueprint_members(self):
        comps = self._comps()
        clusters = clustering.propose(comps, "deployment", cohesion={"svc": 0.98})
        clustering.assign(comps, clusters)
        assert all(not c.get("blueprint") for c in comps)
        assert {c["parent_slug"] for c in comps} == {"svc"}

    def test_a_component_is_not_made_its_own_parent(self):
        comps = [_c("svc"), _c("svc/a"), _c("svc/b")]
        clusters = clustering.propose(comps, "deployment", cohesion={"svc": 0.98})
        clustering.assign(comps, clusters)
        me = [c for c in comps if c["slug"] == "svc"][0]
        assert me.get("parent_slug") != "svc"

    def test_collections_and_compositions_can_coexist_in_one_proposal(self):
        comps = [_c("tight/a"), _c("tight/b"), _c("loose/a"), _c("loose/b")]
        clusters = clustering.propose(comps, "deployment", cohesion={"tight": 0.9, "loose": 0.01})
        carriers = {c.name: c.carrier for c in clusters}
        assert carriers["tight"] == "composition"
        assert carriers["loose"] == "collection"


class TestWiresReachClusteringThroughPersistIr:
    """The plumbing, end to end: arch_recovery_detect.py already calls
    interfaces.propose() and passes `wires=wires` into persist_ir() — this
    proves persist_ir actually threads that value all the way through
    _cluster() into clustering.propose(), rather than the parameter existing
    on paper. A unit test of clustering.propose(wires=...) alone would not
    have caught a broken _cluster()/persist_ir() wire-up in between.
    """

    class _StubRegistry:
        """Real enough to exercise persist_ir's withdrawal-check history
        read, same shape test_arch_mermaid.py's stub uses."""

        def __init__(self):
            self.findings = []

        def upsert_finding(self, slug, kind, rows, surveyed_at="", scope_locator=""):
            for r in rows:
                self.findings.append({**r, "kind": kind, "scope_locator": scope_locator,
                                      "_ts": surveyed_at})

        def upsert_metric(self, *a, **k):
            pass

        def query_findings_history_raw(self, slug, kind):
            return [{**f, "check_name": f.get("check_name", ""),
                     "detail_json": f.get("detail"), "surveyed_at": f.get("_ts", "")}
                    for f in self.findings if f.get("kind") == kind]

    @staticmethod
    def _comp(slug):
        from resource_explorer.surveyors.arch_recovery.ir import Component, Identity
        return Component(slug=slug, name=slug, type="Software Service",
                         identity=Identity(method="deployment-unit", value=slug))

    def test_a_wire_derived_blueprint_is_persisted(self):
        from resource_explorer.surveyors.arch_recovery.persist import persist_ir, BLUEPRINT_KIND

        components = [self._comp(f"flat::s{i}") for i in range(25)]
        wires = [{"source": f"flat::s{a}", "target": f"flat::s{b}"}
                for a in range(10) for b in range(a + 1, 10)]
        reg = self._StubRegistry()
        persist_ir(reg, "demo", components, [], "2026-08-30T00:00:00",
                  wires=wires)

        blueprints = [f for f in reg.findings if f["kind"] == BLUEPRINT_KIND]
        assert any(
            (f.get("detail") or {}).get("signal") == "wire-density"
            for f in blueprints
        ), [f.get("detail") for f in blueprints]

    def test_a_shared_interface_derived_blueprint_is_persisted(self):
        from resource_explorer.surveyors.arch_recovery.persist import persist_ir, BLUEPRINT_KIND

        components = [self._comp(f"flat::s{i}") for i in range(25)]
        ports = [{"component": f"flat::s{i}",
                 "additionalProperties": {"interfaceName": "orders.OrderService"}}
                for i in range(6)]
        reg = self._StubRegistry()
        persist_ir(reg, "demo", components, [], "2026-08-30T00:00:00",
                  ports=ports)

        blueprints = [f for f in reg.findings if f["kind"] == BLUEPRINT_KIND]
        assert any(
            (f.get("detail") or {}).get("signal") == "shared-interface"
            for f in blueprints
        ), [f.get("detail") for f in blueprints]
