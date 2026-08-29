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
