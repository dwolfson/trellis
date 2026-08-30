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
