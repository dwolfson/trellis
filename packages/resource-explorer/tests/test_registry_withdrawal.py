"""Withdrawn scopes and `query_finding_scopes` — step 2 of
`docs/architecture-recovery-scope-tombstoning.md`.

The leak that note identified is here, not in the missing row:
`query_finding_scopes` had **no notion of currency** — no timestamp, no recency,
no filter — so a scope, once written, was enumerable forever. Measured
2026-08-30 on a refreshed store: 165 of `egeria_git`'s 1035 component scopes
were written by no current run, and 27 of its 35 deployment components were
dead, each rendered at its original confidence.

Nothing writes a withdrawal yet. These tests define the contract the writer will
have to satisfy.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import WITHDRAWN_LABEL, Project, ProjectRegistry

KIND = "architecture_recovery"


@pytest.fixture
def registry(tmp_path_factory):
    return ProjectRegistry(db_path=str(tmp_path_factory.mktemp("db") / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="w", display_name="W", github_url="https://github.com/a/w")
    registry.add(p)
    return p


def _component(registry, slug, scope, ts, check_name="component"):
    registry.upsert_finding(slug, KIND,
                            [{"check_name": check_name, "label": "Software Service"}],
                            surveyed_at=ts, scope_locator=scope)


def _withdraw(registry, slug, scope, ts, check_name="component_withdrawn"):
    registry.upsert_finding(slug, KIND,
                            [{"check_name": check_name, "label": WITHDRAWN_LABEL,
                              "detail": {"cause": "unclaimed"}}],
                            surveyed_at=ts, scope_locator=scope)


class TestWithdrawal:
    def test_a_withdrawn_scope_stops_being_enumerated(self, registry, project):
        _component(registry, project.slug, "pkg/a", "2026-08-30T00:00:00")
        _withdraw(registry, project.slug, "pkg/a", "2026-08-30T00:01:00")
        assert registry.query_finding_scopes(project.slug, KIND) == []

    def test_nothing_changes_when_nothing_is_withdrawn(self, registry, project):
        """Step 2's success criterion: on a store with no withdrawals the
        enumerated set must not move at all. Verified against the real store the
        same day — egeria_git stayed at 1035, workspaces at 175."""
        for scope in ("pkg/a", "pkg/b", "pkg/c"):
            _component(registry, project.slug, scope, "2026-08-30T00:00:00")
        assert registry.query_finding_scopes(project.slug, KIND) == ["pkg/a", "pkg/b", "pkg/c"]

    def test_include_withdrawn_returns_it_again(self, registry, project):
        _component(registry, project.slug, "pkg/a", "2026-08-30T00:00:00")
        _withdraw(registry, project.slug, "pkg/a", "2026-08-30T00:01:00")
        assert registry.query_finding_scopes(
            project.slug, KIND, include_withdrawn=True) == ["pkg/a"]

    def test_a_later_proposal_revives_a_withdrawn_scope(self, registry, project):
        """Revival falls out of the ordering and needs no special case — which
        matters because detect and coupling write the SAME kind, so a scope one
        step still proposes must survive the other withdrawing it."""
        _component(registry, project.slug, "pkg/a", "2026-08-30T00:00:00")
        _withdraw(registry, project.slug, "pkg/a", "2026-08-30T00:01:00")
        _component(registry, project.slug, "pkg/a", "2026-08-30T00:02:00")
        assert registry.query_finding_scopes(project.slug, KIND) == ["pkg/a"]

    def test_a_concurrent_proposal_at_the_same_instant_wins(self, registry, project):
        """Both steps can share one `surveyed_at`. A withdrawal from one and a
        live component from the other at the SAME instant means the scope is
        still claimed — the rule is "newest information says withdrawn AND
        nothing at that instant says otherwise"."""
        _component(registry, project.slug, "pkg/a", "2026-08-30T00:00:00")
        _withdraw(registry, project.slug, "pkg/a", "2026-08-30T00:01:00")
        _component(registry, project.slug, "pkg/a", "2026-08-30T00:01:00")
        assert registry.query_finding_scopes(project.slug, KIND) == ["pkg/a"]

    def test_withdrawal_does_not_leak_across_scopes(self, registry, project):
        _component(registry, project.slug, "pkg/a", "2026-08-30T00:00:00")
        _component(registry, project.slug, "pkg/b", "2026-08-30T00:00:00")
        _withdraw(registry, project.slug, "pkg/a", "2026-08-30T00:01:00")
        assert registry.query_finding_scopes(project.slug, KIND) == ["pkg/b"]

    def test_withdrawal_does_not_leak_across_kinds(self, registry, project):
        _component(registry, project.slug, "pkg/a", "2026-08-30T00:00:00")
        registry.upsert_finding(project.slug, "architecture_interfaces",
                                [{"check_name": "port:x", "label": "ok"}],
                                surveyed_at="2026-08-30T00:00:00", scope_locator="pkg/a")
        _withdraw(registry, project.slug, "pkg/a", "2026-08-30T00:01:00")
        assert registry.query_finding_scopes(project.slug, KIND) == []
        assert registry.query_finding_scopes(
            project.slug, "architecture_interfaces") == ["pkg/a"]

    def test_a_check_name_filtered_call_still_honours_withdrawal(self, registry, project):
        """A withdrawal is about the SCOPE, so it must be visible to a caller
        narrowing to one check_name — which is how the results reader queries."""
        _component(registry, project.slug, "pkg/a", "2026-08-30T00:00:00")
        _withdraw(registry, project.slug, "pkg/a", "2026-08-30T00:01:00")
        assert registry.query_finding_scopes(
            project.slug, KIND, check_name="component") == []

    def test_withdrawal_deletes_nothing(self, registry, project):
        """The provenance view must keep answering "who proposed what, ever"
        after the current answer changes."""
        _component(registry, project.slug, "pkg/a", "2026-08-30T00:00:00")
        _withdraw(registry, project.slug, "pkg/a", "2026-08-30T00:01:00")
        rows = registry.query_findings_all_runs(project.slug, KIND, "pkg/a")
        assert len(rows) == 2
        assert registry.query_findings(project.slug, KIND, "pkg/a")


class TestWithdrawalIsNotEvidence:
    """A withdrawal row has `check_name != "component"`, so every reader that
    splits rows that way treats it as evidence unless told otherwise.

    Found by looking at the rendered page rather than the JSON: egeria's
    withdrawn components displayed `spring, withdrawn` on their provenance
    line, as though a detector called "withdrawn" had proposed them.

    (Seen on a server predating the withdrawal filter, but it is not a
    stale-server artifact — a REVIVED scope is live and carries a withdrawal in
    its history, so the pollution is reachable in current code.)
    """

    def test_a_withdrawal_is_not_listed_as_an_approach(self, registry, project):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _architecture_recovery_results,
        )
        registry.upsert_finding(project.slug, KIND, [{
            "check_name": "component", "label": "Software Service",
            "detail": {"name": "svc", "slug": "svc", "perspective": "deployment"},
        }], surveyed_at="2026-08-30T00:00:00", scope_locator="pkg/a")
        registry.upsert_finding(project.slug, KIND, [{
            "check_name": "manifest:python", "label": "manifest",
        }], surveyed_at="2026-08-30T00:00:00", scope_locator="pkg/a")
        # REVIVAL is the reachable case: once withdrawn, a scope stops being
        # enumerated, so the pollution can only be seen on a scope that came
        # back — which is exactly what happens when the other step still
        # proposes it, or the next run re-detects it.
        _withdraw(registry, project.slug, "pkg/a", "2026-08-30T00:01:00")
        registry.upsert_finding(project.slug, KIND, [{
            "check_name": "component", "label": "Software Service",
            "detail": {"name": "svc", "slug": "svc", "perspective": "deployment"},
        }], surveyed_at="2026-08-30T00:02:00", scope_locator="pkg/a")

        result = _architecture_recovery_results(registry, project.slug, max_depth=None)
        rows = [c for c in result["components"] if c["path"] == "pkg/a"]
        assert rows, "fixture produced no component — the test would pass vacuously"
        assert WITHDRAWN_LABEL not in rows[0]["proposed_by"]
        assert "manifest" in rows[0]["proposed_by"]


class TestCuratorVerdictMergedIntoResults:
    """docs/Backlog.md "take architecture results into Curate" — a curator's
    verdict lives in its own table (architecture_component_verdicts), not
    mixed into this kind's findings (see that entry's "evidence of a
    different kind, not a rewrite" constraint), so the results reader has to
    merge it in by scope_locator rather than get it for free."""

    def _propose(self, registry, slug, scope, ts="2026-08-30T00:00:00"):
        registry.upsert_finding(slug, KIND, [{
            "check_name": "component", "label": "Software Service",
            "detail": {"name": "svc", "slug": "svc", "perspective": "deployment"},
        }], surveyed_at=ts, scope_locator=scope)

    def test_a_component_with_no_verdict_reports_none(self, registry, project):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _architecture_recovery_results,
        )
        self._propose(registry, project.slug, "pkg/a")
        result = _architecture_recovery_results(registry, project.slug, max_depth=None)
        row = next(c for c in result["components"] if c["path"] == "pkg/a")
        assert row["verdict"] is None

    def test_a_recorded_verdict_is_attached_by_scope_locator(self, registry, project):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _architecture_recovery_results,
        )
        self._propose(registry, project.slug, "pkg/a")
        registry.record_component_verdict("repo", project.slug, "pkg/a", "accepted")
        result = _architecture_recovery_results(registry, project.slug, max_depth=None)
        row = next(c for c in result["components"] if c["path"] == "pkg/a")
        assert row["verdict"]["verdict"] == "accepted"

    def test_only_the_latest_verdict_is_attached(self, registry, project):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _architecture_recovery_results,
        )
        self._propose(registry, project.slug, "pkg/a")
        registry.record_component_verdict("repo", project.slug, "pkg/a", "accepted")
        registry.record_component_verdict("repo", project.slug, "pkg/a", "rejected")
        result = _architecture_recovery_results(registry, project.slug, max_depth=None)
        row = next(c for c in result["components"] if c["path"] == "pkg/a")
        assert row["verdict"]["verdict"] == "rejected"

    def test_a_verdict_on_one_component_does_not_leak_onto_another(self, registry, project):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _architecture_recovery_results,
        )
        self._propose(registry, project.slug, "pkg/a")
        self._propose(registry, project.slug, "pkg/b")
        registry.record_component_verdict("repo", project.slug, "pkg/a", "accepted")
        result = _architecture_recovery_results(registry, project.slug, max_depth=None)
        row_b = next(c for c in result["components"] if c["path"] == "pkg/b")
        assert row_b["verdict"] is None
