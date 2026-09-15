"""resource_explorer/destinations.py — where a finding belongs.

SPEC-ACTIONABLE-AND-HONEST.md §3: every finding about the repository names
one of judgement/task/context; a finding about the ANALYSIS (a disagreement,
or a check that could not be established) is computed as `ours`, never
declared. These tests exercise each resolution rule in isolation, the basis
strings a caller can assert on, that `ours` always wins over a declared
default, and a registry-coverage report that turns "how many checks have no
declared destination" into a fact rather than a surprise.
"""
from __future__ import annotations

from resource_explorer.destinations import (
    CONTEXT,
    DISAGREEMENT,
    JUDGEMENT,
    OURS,
    TASK,
    BASIS_DISAGREEMENT,
    BASIS_LABEL_OVERRIDE,
    BASIS_NOT_ESTABLISHED,
    BASIS_REGISTRY_DEFAULT,
    BASIS_UNDECLARED,
    all_check_refs,
    checks_lacking_declared_destination,
    checks_per_analysis,
    judgement_field_for,
    resolve_destination,
)
from resource_explorer.surveyors.result_status import NOT_ESTABLISHED


class TestRule1ComputedOurs:
    """Rule (1): disagreement or not-established wins over everything else,
    and is never something a check declares statically."""

    def test_disagreement_state_is_ours(self):
        dest, basis = resolve_destination("chaoss_metrics", "elephant_factor", "sole", DISAGREEMENT)
        assert dest == OURS
        assert basis == BASIS_DISAGREEMENT

    def test_not_established_state_is_ours(self):
        dest, basis = resolve_destination("interface_surface", "cli", "implied", NOT_ESTABLISHED)
        assert dest == OURS
        assert basis == BASIS_NOT_ESTABLISHED

    def test_not_established_label_is_ours_even_with_a_different_state(self):
        """Check-level finding rows only carry a `label`, not a Fact-layer
        `state` — community_support/interface_surface write
        label="not_established" directly (see their surveyors). The label
        alone must trigger the computed destination."""
        dest, basis = resolve_destination("community_support", "responsiveness", NOT_ESTABLISHED, "measured")
        assert dest == OURS
        assert basis == BASIS_NOT_ESTABLISHED

    def test_ours_wins_over_a_declared_default(self):
        """elephant_factor declares default: judgement — a disagreement or
        not-established state must override that declaration, not merge
        with it."""
        dest, _ = resolve_destination("chaoss_metrics", "elephant_factor", "sole", NOT_ESTABLISHED)
        assert dest == OURS
        dest, _ = resolve_destination("chaoss_metrics", "elephant_factor", "sole", DISAGREEMENT)
        assert dest == OURS

    def test_ours_is_never_a_declarable_static_value(self):
        """A check_registry.yaml entry cannot declare `ours` — it is outside
        the DECLARABLE set, so even a (hypothetical) registry default/label of
        "ours" would not be returned as one via that path; the module's own
        contract, checked directly."""
        from resource_explorer.destinations import DECLARABLE

        assert OURS not in DECLARABLE


class TestRule2LabelOverride:
    def test_published_spec_no_is_a_task(self):
        """The designer's own worked example (§3 table row 2)."""
        dest, basis = resolve_destination("interface_surface", "published_spec", "no", "measured")
        assert dest == TASK
        assert basis == BASIS_LABEL_OVERRIDE

    def test_published_spec_yes_is_context(self):
        dest, basis = resolve_destination("interface_surface", "published_spec", "yes", "measured")
        assert dest == CONTEXT
        assert basis == BASIS_LABEL_OVERRIDE

    def test_a_label_not_in_the_override_map_falls_through_to_default(self):
        dest, basis = resolve_destination("interface_surface", "published_spec", "sideways", "measured")
        assert dest == CONTEXT  # published_spec's default
        assert basis == BASIS_REGISTRY_DEFAULT


class TestRule3RegistryDefault:
    def test_elephant_factor_is_a_judgement(self):
        """The designer's own worked example (§3 table row 1)."""
        dest, basis = resolve_destination("chaoss_metrics", "elephant_factor", "sole", "measured")
        assert dest == JUDGEMENT
        assert basis == BASIS_REGISTRY_DEFAULT

    def test_project_maturity_is_context(self):
        """The designer's own worked example (§3 table row 3)."""
        dest, basis = resolve_destination("maturity", "project_maturity", "established", "measured")
        assert dest == CONTEXT
        assert basis == BASIS_REGISTRY_DEFAULT

    def test_whole_analysis_only_id_resolves_via_its_own_section(self):
        """architecture_summary has no `checks` list at all — check_name ==
        analysis_id reaches whole_analysis_destinations instead."""
        dest, basis = resolve_destination("architecture_summary", "architecture_summary", "", "measured")
        assert dest == CONTEXT
        assert basis == BASIS_REGISTRY_DEFAULT


class TestRule4Undeclared:
    def test_unknown_kind_and_check_is_context_undeclared(self):
        dest, basis = resolve_destination("nonexistent_analysis", "nonexistent_check", "x", "measured")
        assert dest == CONTEXT
        assert basis == BASIS_UNDECLARED


class TestJudgementField:
    def test_declared_judgement_with_no_field_yet_is_none_not_a_guess(self):
        """§3: "the honest position ... naming one now would be inventing a
        field this layer does not own" — every judgement check declared in
        this pass has judgement_field: null, and that must come back as
        Python None, not an empty string or an invented key."""
        assert judgement_field_for("chaoss_metrics", "elephant_factor") is None

    def test_a_check_with_no_declaration_has_no_judgement_field(self):
        assert judgement_field_for("nonexistent_analysis", "nonexistent_check") is None


class TestRegistryCoverageReport:
    """Not a pass/fail assertion that every check has a destination — a
    report-with-threshold, so the gap is a visible, shrinking fact rather
    than a merge-blocker the day this feature lands. See this test's own
    threshold for the count as of this change; lower it as more checks gain
    declarations, never raise it silently."""

    #: Every check_registry.yaml check declared a destination in this same
    #: change (2026-09-14) — the threshold documents that, and catches a
    #: FUTURE regression (a new check added with no destination) rather than
    #: describing today's population as an aspiration.
    THRESHOLD = 0

    def test_undeclared_checks_do_not_exceed_the_threshold(self):
        missing = checks_lacking_declared_destination()
        assert len(missing) <= self.THRESHOLD, (
            f"{len(missing)} (analysis, check) pairs have no declared "
            f"destination (threshold {self.THRESHOLD}): {sorted(missing)}"
        )

    def test_every_check_ref_is_a_real_pair(self):
        """all_check_refs() itself should return something — an empty list
        here would make the report above vacuously pass."""
        refs = all_check_refs()
        assert len(refs) > 50
        assert ("chaoss_metrics", "elephant_factor") in refs
        assert ("architecture_summary", "architecture_summary") in refs


class TestChecksPerAnalysis:
    def test_a_per_check_analysis_counts_its_checks(self):
        assert checks_per_analysis()["chaoss_metrics"] == 5

    def test_a_whole_analysis_only_id_counts_as_one(self):
        assert checks_per_analysis()["architecture_summary"] == 1
