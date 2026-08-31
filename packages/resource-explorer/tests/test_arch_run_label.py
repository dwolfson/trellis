"""`run_label` on component rows — step 1 of
`docs/architecture-recovery-scope-tombstoning.md`.

Additive and unread: nothing consumes this yet. It exists because that note's
**R2** — a step may only withdraw scopes IT wrote — is unimplementable without
it. `repo_arch_detect` and `repo_arch_coupling` write the SAME analysis kind, so
an unattributed withdrawal would make them erase each other's components
alternately and forever.

`persist_ir` already solved that exact collision once, for metrics, by prefixing
`run_label` into the metric name. This puts the same key where component rows can
be grouped by it.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.arch_recovery.ir import Component, Identity
from resource_explorer.surveyors.arch_recovery.persist import KIND, persist_ir


@pytest.fixture
def registry(tmp_path_factory):
    return ProjectRegistry(db_path=str(tmp_path_factory.mktemp("db") / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="rl", display_name="RL", github_url="https://github.com/a/rl")
    registry.add(p)
    return p


def _component(slug, path):
    return Component(
        slug=slug, name=slug, type=None,
        identity=Identity(method="module-path", value=path),
        files=[f"{path}/**"],
    )


def _labels(registry, slug, scope):
    out = []
    for row in registry.query_findings_all_runs(slug, KIND, scope):
        if row["check_name"] != "component":
            continue
        detail = row.get("detail_json") or "{}"
        detail = json.loads(detail) if isinstance(detail, str) else detail
        out.append(detail.get("run_label"))
    return out


class TestRunLabelOnComponentRows:
    def test_the_writing_step_is_recorded_on_the_row(self, registry, project):
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:00:00", run_label="detect")
        assert _labels(registry, project.slug, "pkg/a") == ["detect"]

    def test_two_steps_writing_the_same_scope_stay_distinguishable(self, registry, project):
        """The whole point. Both steps write the same KIND, and before this the
        rows they produced for one scope were indistinguishable — so "scopes I
        wrote" could not be computed, and R2 could not be enforced."""
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:00:00", run_label="detect")
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:01:00", run_label="coupling")
        assert sorted(_labels(registry, project.slug, "pkg/a")) == ["coupling", "detect"]

    def test_scopes_can_be_grouped_by_writing_step(self, registry, project):
        """R2's actual query: which scopes did THIS step write?"""
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:00:00", run_label="detect")
        persist_ir(registry, project.slug, [_component("b", "pkg/b")], [],
                   "2026-08-30T00:01:00", run_label="coupling")
        by_step = {}
        for scope in registry.query_finding_scopes(project.slug, KIND, check_name="component"):
            for label in _labels(registry, project.slug, scope):
                by_step.setdefault(label, set()).add(scope)
        assert by_step == {"detect": {"pkg/a"}, "coupling": {"pkg/b"}}

    def test_it_defaults_rather_than_raising_for_a_caller_that_omits_it(self, registry, project):
        """Additive: an existing caller that never passes `run_label` still
        writes a valid row, it is simply unattributed."""
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:00:00")
        assert _labels(registry, project.slug, "pkg/a") == ["run"]

    def test_the_real_steps_pass_distinct_labels(self):
        """Guards the two call sites: identical labels would silently defeat R2
        while every test above still passed."""
        import inspect

        from resource_explorer.surveyors.sub_surveyors import (
            arch_recovery_coupling,
            arch_recovery_detect,
        )
        assert 'run_label="detect"' in inspect.getsource(arch_recovery_detect)
        assert 'run_label="coupling"' in inspect.getsource(arch_recovery_coupling)


class TestWithdrawalOnCompleteRuns:
    """Step 3 of `docs/architecture-recovery-scope-tombstoning.md` — a complete
    run withdraws the scopes it used to write and no longer does."""

    def _scopes(self, registry, slug):
        return registry.query_finding_scopes(slug, KIND, check_name="component")

    def test_a_vacated_scope_is_withdrawn_and_stops_enumerating(self, registry, project):
        persist_ir(registry, project.slug, [_component("a", "pkg/a"), _component("b", "pkg/b")],
                   [], "2026-08-30T00:00:00", run_label="detect")
        assert sorted(self._scopes(registry, project.slug)) == ["pkg/a", "pkg/b"]
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:01:00", run_label="detect")
        assert self._scopes(registry, project.slug) == ["pkg/a"]

    def test_a_scoped_run_withdraws_nothing(self, registry, project):
        """R1 — a run narrowed to a subtree saw only part of the repo, so its
        absences mean nothing. This is the worst failure mode in the design."""
        persist_ir(registry, project.slug, [_component("a", "pkg/a"), _component("b", "pkg/b")],
                   [], "2026-08-30T00:00:00", run_label="detect")
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:01:00", run_label="detect", run_scope="pkg/a")
        assert sorted(self._scopes(registry, project.slug)) == ["pkg/a", "pkg/b"]

    def test_a_partial_outcome_withdraws_nothing(self, registry, project):
        """The other half of R1: a caller-supplied PARTIAL is as disqualifying
        as a run_scope, and a caller's outcome always wins over the computed one."""
        from resource_explorer.step_outcome import PARTIAL, StepOutcome
        persist_ir(registry, project.slug, [_component("a", "pkg/a"), _component("b", "pkg/b")],
                   [], "2026-08-30T00:00:00", run_label="detect")
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:01:00", run_label="detect",
                   outcome=StepOutcome(PARTIAL, cause="interrupted"))
        assert sorted(self._scopes(registry, project.slug)) == ["pkg/a", "pkg/b"]

    def test_one_step_never_withdraws_anothers_scopes(self, registry, project):
        """R2, and the reason step 1 existed. detect and coupling write the SAME
        kind; without attribution they erase each other alternately, forever."""
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:00:00", run_label="coupling")
        persist_ir(registry, project.slug, [_component("b", "pkg/b")], [],
                   "2026-08-30T00:01:00", run_label="detect")
        # detect's run wrote only pkg/b and must not touch coupling's pkg/a.
        assert sorted(self._scopes(registry, project.slug)) == ["pkg/a", "pkg/b"]

    def test_unattributed_history_is_never_withdrawn(self, registry, project):
        """Rows written before `run_label` existed belong to no step, so no step
        may withdraw them — which is exactly why the pre-existing orphan
        population needs the step-4 backfill and can never be cleared by an
        ordinary run."""
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:00:00")           # no run_label -> "run"
        persist_ir(registry, project.slug, [_component("b", "pkg/b")], [],
                   "2026-08-30T00:01:00", run_label="detect")
        assert sorted(self._scopes(registry, project.slug)) == ["pkg/a", "pkg/b"]

    def test_the_withdrawal_records_an_unclaimed_cause_not_a_removal(self, registry, project):
        """R3 — "we renamed it" and "it is gone from the repo" look identical
        from inside the pipeline and mean opposite things."""
        persist_ir(registry, project.slug, [_component("a", "pkg/a"), _component("b", "pkg/b")],
                   [], "2026-08-30T00:00:00", run_label="detect")
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:01:00", run_label="detect")
        rows = registry.query_findings(project.slug, KIND, "pkg/b")
        detail = json.loads(rows[0]["detail_json"])
        assert detail["cause"] == "unclaimed"
        assert detail["run_label"] == "detect"

    def test_withdrawing_is_reported_not_silent(self, registry, project):
        """A cleanup that leaves no trace is indistinguishable from data loss to
        whoever comes looking in six months."""
        persist_ir(registry, project.slug, [_component("a", "pkg/a"), _component("b", "pkg/b")],
                   [], "2026-08-30T00:00:00", run_label="detect")
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:01:00", run_label="detect")
        metrics = registry.query_metrics(project.slug, KIND, "")
        assert metrics.get("detect_withdrawn_count") == 1.0

    def test_a_steady_run_withdraws_nothing_and_stays_quiet(self, registry, project):
        """Idempotence: comparing against the PREVIOUS run rather than all
        history is what stops a withdrawn scope being re-withdrawn forever."""
        for ts in ("2026-08-30T00:00:00", "2026-08-30T00:01:00", "2026-08-30T00:02:00"):
            persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                       ts, run_label="detect")
        assert self._scopes(registry, project.slug) == ["pkg/a"]
        assert not registry.query_metrics(project.slug, KIND, "").get("detect_withdrawn_count")

    def test_a_revived_scope_comes_back(self, registry, project):
        persist_ir(registry, project.slug, [_component("a", "pkg/a"), _component("b", "pkg/b")],
                   [], "2026-08-30T00:00:00", run_label="detect")
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:01:00", run_label="detect")
        assert self._scopes(registry, project.slug) == ["pkg/a"]
        persist_ir(registry, project.slug, [_component("a", "pkg/a"), _component("b", "pkg/b")],
                   [], "2026-08-30T00:02:00", run_label="detect")
        assert sorted(self._scopes(registry, project.slug)) == ["pkg/a", "pkg/b"]
