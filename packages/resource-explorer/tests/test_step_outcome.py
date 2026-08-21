"""The shared outcome vocabulary, and the one rule it exists to enforce.

Adopted 2026-08-21 from docs/approach-portfolio-model.md §3, after three parts
of this codebase independently invented a vocabulary for the same distinction:
this step's `reason` strings, arch-recovery's `run_scope`/`partial`, and §3
itself. Egeria calls it a produced guard.

The rule under test is §3's:

    An approach with no known-positive check cannot report `no_signal`,
    only `unverified`.

It is not bookkeeping. A coupling import graph came back 89% empty this session
because a resolution bug pointed it at the wrong copy of a duplicated package,
and recorded as a plain zero it read as "this repo has no structure". Four bugs
took that shape, in three subsystems, none of them raising.
"""
from __future__ import annotations

import pytest

from resource_explorer.step_outcome import (
    NO_SIGNAL,
    OUTCOMES,
    PARTIAL,
    RECOVERED,
    UNVERIFIED,
    InvalidOutcome,
    StepOutcome,
    no_signal,
)


class TestTheKnownPositiveRule:

    def test_no_signal_without_a_known_positive_is_refused(self):
        """The whole point. Claiming a provable zero without proof is claiming
        knowledge the run does not have."""
        with pytest.raises(InvalidOutcome, match="known_positive"):
            StepOutcome(NO_SIGNAL, cause="nothing found")

    def test_no_signal_with_a_known_positive_is_allowed(self):
        o = StepOutcome(NO_SIGNAL, cause="code_host", known_positive=True)
        assert o.outcome == NO_SIGNAL and o.is_conclusive

    def test_the_helper_degrades_to_unverified_rather_than_raising(self):
        """A caller that honestly has no known-positive should still record its
        run — the aim is the weaker guarantee stated, not the run blocked."""
        o = no_signal("empty_inventory", known_positive=False)
        assert o.outcome == UNVERIFIED
        assert o.cause == "empty_inventory"

    def test_the_helper_requires_known_positive_to_be_explicit(self):
        """Keyword-only and undefaulted, so claiming a provable zero is always a
        deliberate act at the call site rather than a default that drifts in."""
        with pytest.raises(TypeError):
            no_signal("something")  # type: ignore[call-arg]

    def test_the_rule_does_not_constrain_other_outcomes(self):
        """Only a zero needs proof; `recovered` carries its own evidence."""
        assert StepOutcome(RECOVERED).outcome == RECOVERED
        assert StepOutcome(PARTIAL, cause="scoped run").outcome == PARTIAL
        assert StepOutcome(UNVERIFIED, cause="could not run").outcome == UNVERIFIED


class TestVocabulary:

    def test_an_unknown_outcome_is_refused(self):
        """A typo'd label is worse than no label: it looks like data."""
        with pytest.raises(InvalidOutcome, match="unknown outcome"):
            StepOutcome("succeeded")

    def test_the_five_labels_are_the_vocabulary(self):
        assert set(OUTCOMES) == {"recovered", "partial", "no_signal",
                                 "unverified", "regression"}

    def test_only_recovered_and_no_signal_are_conclusive(self):
        """`partial` and `unverified` both mean "do not read this as complete",
        which is the question a corpus-wide sweep actually asks."""
        assert StepOutcome(RECOVERED).is_conclusive
        assert StepOutcome(NO_SIGNAL, known_positive=True).is_conclusive
        assert not StepOutcome(PARTIAL).is_conclusive
        assert not StepOutcome(UNVERIFIED).is_conclusive


class TestOutcomeAndCauseStaySeparate:
    """Forced by the model, not a preference: Egeria's
    NextGovernanceActionProcessStepProperties carries a flat
    `guard: Optional[str]` with no structured payload, so the routable label and
    the local explanation cannot be one field."""

    def test_two_causes_can_share_one_outcome(self):
        a = no_signal("self_published", known_positive=True)
        b = no_signal("code_host", known_positive=True)
        assert a.outcome == b.outcome == NO_SIGNAL
        assert a.cause != b.cause

    def test_the_persisted_row_keeps_both(self):
        row = no_signal("code_host", known_positive=True, url="https://github.com/o/r").as_row()
        assert row["outcome"] == NO_SIGNAL
        assert row["outcome_cause"] == "code_host"
        assert row["outcome_known_positive"] is True
        assert row["outcome_detail"]["url"].endswith("/o/r")

    def test_the_row_is_flat_and_prefixed(self):
        """It is merged into a step's own detail dict, so it must not collide
        with keys the step already uses (url, chunks, reason, …)."""
        row = StepOutcome(RECOVERED).as_row()
        assert all(k.startswith("outcome") for k in row)

    def test_an_empty_detail_is_omitted_rather_than_stored_empty(self):
        assert "outcome_detail" not in StepOutcome(RECOVERED).as_row()


class TestWebsiteIngestionUsesIt:
    """The first adopter. Its private `reason` vocabulary is kept alongside —
    the outcome is queryable across steps, the cause is local knowledge."""

    @pytest.fixture
    def registry(self, tmp_path):
        from resource_explorer.registry import Project, ProjectRegistry

        reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
        reg.add(Project(slug="p", display_name="P",
                        github_url="https://github.com/o/p", description=""))
        return reg

    def test_a_repo_publishing_its_own_site_is_a_provable_no_signal(self, registry):
        """The marker in its own inventory is the known-positive: something was
        found, and it is what rules the ingest out."""
        from resource_explorer.surveyors.sub_surveyors.website_ingestion import (
            WebsiteIngestionSurveyor,
        )

        registry.update_project_homepage("p", "https://egeria-project.org") if hasattr(
            registry, "update_project_homepage") else None
        project = registry.get("p")
        project.homepage_url = "https://egeria-project.org"
        registry.upsert_file_inventory("p", [("site/mkdocs.yml", 10)])

        WebsiteIngestionSurveyor(project, registry).run()
        d = (registry.query_metrics("p", "website_ingestion") or {}).get("detail") or {}
        assert d["outcome"] == NO_SIGNAL
        assert d["outcome_cause"] == "self_published"
        assert d["outcome_known_positive"] is True

    def test_no_homepage_yet_is_unverified_not_no_signal(self, registry):
        """Nothing was attempted and nothing proves the step works — the
        distinction the whole vocabulary exists for."""
        from resource_explorer.surveyors.sub_surveyors.website_ingestion import (
            WebsiteIngestionSurveyor,
        )

        WebsiteIngestionSurveyor(registry.get("p"), registry).run()
        d = (registry.query_metrics("p", "website_ingestion") or {}).get("detail") or {}
        assert d["outcome"] == UNVERIFIED
        assert d["outcome_cause"] == "no_homepage"
