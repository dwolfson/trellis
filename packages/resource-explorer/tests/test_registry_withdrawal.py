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
