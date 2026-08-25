"""Distillation — §5.2 step 1, ported from the spike (findings 76-80).

Each filter is a claim about what a component IS, so each test names the claim
rather than the mechanics.
"""
from __future__ import annotations

from resource_explorer.surveyors.arch_recovery import distill as D
from resource_explorer.surveyors.arch_recovery.ir import Component, Identity


def _c(slug, files, type_=None, perspective="physical"):
    return Component(slug=slug, name=slug, type=type_, identity=Identity(method="path", value=slug),
                     files=list(files), perspective=perspective)


class TestSupportOnly:
    def test_a_candidate_made_entirely_of_tests_is_not_a_component(self):
        kept, dropped, _ = D.distill([_c("t", ["tests/**"]), _c("real", ["server/**"])])
        assert [c.slug for c in kept] == ["real"]
        assert dropped[0][1] == D.DROP_SUPPORT_ONLY

    def test_a_component_that_merely_contains_tests_survives(self):
        """Prometheus's `config/` owns `config/testdata/` and the ground truth
        says so. 'Contains support material' is not 'is support material'."""
        kept, _, _ = D.distill([_c("config", ["config/**", "config/testdata/**"])])
        assert [c.slug for c in kept] == ["config"]


class TestWholeRepoClaim:
    def test_a_candidate_claiming_the_root_is_a_container_not_a_component(self):
        """Measured on Kubernetes: leaving these in made every real component
        look like a refinement and collapsed 3303 candidates to 4, taking the
        entire ground truth with it."""
        kept, dropped, stats = D.distill([_c("all", ["."]), _c("api", ["api/**"])])
        assert [c.slug for c in kept] == ["api"]
        assert stats[f"dropped_{D.DROP_WHOLE_REPO}"] == 1

    def test_a_bare_glob_normalises_to_the_root_and_still_counts(self):
        """`"**"` and `"/**"` both strip to `""`, which is how the empty-root
        branch is actually reached — a literal `""` in `files` is discarded as
        falsy before the check ever sees it."""
        kept, _, _ = D.distill([_c("all", ["**"]), _c("api", ["api/**"])])
        assert [c.slug for c in kept] == ["api"]

    def test_a_candidate_with_no_usable_globs_is_kept_not_dropped(self):
        """No roots means no filter can assess it. Keeping it is the
        conservative choice: dropping what you cannot evaluate is how a
        precision filter quietly becomes a recall bug."""
        kept, dropped, _ = D.distill([_c("opaque", []), _c("api", ["api/**"])])
        assert set(c.slug for c in kept) == {"opaque", "api"}
        assert dropped == []


class TestRefinement:
    def test_a_child_of_a_classified_parent_adds_nothing(self):
        kept, _, _ = D.distill([
            _c("parent", ["pkg/**"], type_="Software Library"),
            _c("child", ["pkg/scheduler/**"], type_="Software Library"),
        ])
        assert [c.slug for c in kept] == ["parent"]

    def test_an_untyped_parent_does_not_swallow_its_child(self):
        """`pkg` (proposed by coupling, no type) swallowed `pkg/scheduler`,
        which is half of Kubernetes' kube-scheduler. Deferring to a parent
        claims the parent is the better answer — only true once something
        actually classified it."""
        kept, _, _ = D.distill([
            _c("pkg", ["pkg/**"], type_=None),
            _c("sched", ["pkg/scheduler/**"], type_="Software Library"),
        ])
        assert set(c.slug for c in kept) == {"pkg", "sched"}


class TestPerspectivesAreNotMerged:
    """§4.2: 'map, never merge'. The spike distilled one perspective at a time;
    this runs where all four coexist, so refinement is computed per perspective.
    Crossing them would enforce a merge the design forbids — and would look like
    a precision win while destroying the physical/deployment distinction."""

    def test_a_deployment_parent_does_not_suppress_a_physical_child(self):
        kept, _, _ = D.distill([
            _c("stack", ["svc/**"], type_="Software Service", perspective="deployment"),
            _c("svc-img", ["svc/api/**"], type_="Software Service", perspective="physical"),
        ])
        assert set(c.slug for c in kept) == {"stack", "svc-img"}, (
            "a deployment candidate suppressed a physical one — findings 15/16"
        )

    def test_refinement_still_applies_within_one_perspective(self):
        kept, _, _ = D.distill([
            _c("stack", ["svc/**"], type_="Software Service", perspective="deployment"),
            _c("inner", ["svc/api/**"], type_="Software Service", perspective="deployment"),
        ])
        assert [c.slug for c in kept] == ["stack"]

    def test_stats_report_the_surviving_split_by_perspective(self):
        _, _, stats = D.distill([
            _c("a", ["a/**"], perspective="physical"),
            _c("b", ["b/**"], perspective="deployment"),
        ])
        assert stats["by_perspective"] == {"deployment": 1, "physical": 1}


class TestNothingVanishesSilently:
    def test_every_dropped_candidate_carries_the_rule_that_dropped_it(self):
        comps = [_c("t", ["tests/**"]), _c("all", ["."]),
                 _c("p", ["pkg/**"], type_="Software Library"),
                 _c("c", ["pkg/x/**"], type_="Software Library")]
        kept, dropped, stats = D.distill(comps)
        assert len(kept) + len(dropped) == len(comps), "a candidate went missing"
        assert {r for _, r in dropped} == {
            D.DROP_SUPPORT_ONLY, D.DROP_WHOLE_REPO, D.DROP_REFINEMENT}

    def test_the_summary_never_reports_a_bare_output_count(self):
        """202 -> 12 with no reason attached is indistinguishable from a broken
        detector, which is the failure this codebase keeps meeting."""
        _, _, stats = D.distill([_c("t", ["tests/**"]), _c("real", ["server/**"])])
        line = D.summarise(stats)
        assert "2 candidates" in line and "kept" in line
        assert D.DROP_SUPPORT_ONLY in line

    def test_input_plus_output_are_both_always_reported(self):
        _, _, stats = D.distill([])
        assert stats["input"] == 0 and stats["output"] == 0


class TestAPrecisionRuleMustNotBecomeARecallBug:
    """`docling-parse` yields exactly one candidate, covering the whole repo.
    Dropping it as a container left zero components — a correct one-component
    answer turned into an empty result. In the spike this never happened
    because a whole-repo claim always sat among thousands of siblings."""

    def test_a_sole_whole_repo_claim_is_kept(self):
        kept, dropped, stats = D.distill([_c("only", ["."], type_="Software Library")])
        assert [c.slug for c in kept] == ["only"]
        assert dropped == []
        assert stats["whole_repo_claims_kept_as_sole_candidates"] == 1

    def test_it_is_still_dropped_when_something_else_survives(self):
        kept, _, _ = D.distill([_c("all", ["."]), _c("api", ["api/**"])])
        assert [c.slug for c in kept] == ["api"]

    def test_distillation_never_empties_a_non_empty_candidate_set(self):
        """The general invariant. Support-only and refinement filters can
        legitimately empty it — a repo of pure test material has no
        architecture — but a container-only repo does."""
        kept, _, _ = D.distill([_c("a", ["."]), _c("b", ["**"])])
        assert kept, "every candidate was a container and all were dropped"
