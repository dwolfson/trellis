"""Decision notes are persisted, not only logged.

Every note the architecture discoverers produce — *"2 declarations describe one
platform … identical server sets"*, *"qualified by build module, since a shared
name becomes a shared slug"* — went to `log.info` and nowhere else. That is the
*why* behind a component's name or its absence, and it evaporated unless
somebody happened to be tailing logs at INFO while the survey ran.

Evidence records say what was concluded. These say what was **decided and
rejected**, which is what a reader needs when the answer looks wrong.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.arch_recovery.ir import Component, Identity
from resource_explorer.surveyors.arch_recovery.persist import (
    DECISIONS_KIND,
    KIND,
    persist_ir,
)


@pytest.fixture
def registry(tmp_path_factory):
    return ProjectRegistry(db_path=str(tmp_path_factory.mktemp("db") / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="d", display_name="D", github_url="https://github.com/a/d")
    registry.add(p)
    return p


def _component(slug, path):
    return Component(slug=slug, name=slug, type=None,
                     identity=Identity(method="module-path", value=path),
                     files=[f"{path}/**"])


def _notes(registry, slug):
    out = {}
    for row in registry.query_findings_all_runs(slug, DECISIONS_KIND, ""):
        detail = row.get("detail_json") or "{}"
        detail = json.loads(detail) if isinstance(detail, str) else detail
        out[row["check_name"]] = detail
    return out


class TestDecisionNotes:
    def test_notes_are_stored_not_only_logged(self, registry, project):
        persist_ir(registry, project.slug, [], [], "2026-08-30T00:00:00",
                   run_label="detect", notes=["merged two declarations"])
        assert _notes(registry, project.slug)["decisions:detect"]["notes"] == [
            "merged two declarations"]

    def test_each_step_keeps_its_own_reasoning(self, registry, project):
        """Keyed by run_label for the reason persist_ir already prefixes its
        summary metric: the two steps need not share a surveyed_at, and
        query_findings returns only MAX(surveyed_at) per (slug, kind, scope) —
        so a shared check_name would let whichever ran last hide the other."""
        persist_ir(registry, project.slug, [], [], "2026-08-30T00:00:00",
                   run_label="detect", notes=["detect said X"])
        persist_ir(registry, project.slug, [], [], "2026-08-30T00:01:00",
                   run_label="coupling", notes=["coupling said Y"])
        stored = _notes(registry, project.slug)
        assert stored["decisions:detect"]["notes"] == ["detect said X"]
        assert stored["decisions:coupling"]["notes"] == ["coupling said Y"]

    def test_they_do_not_land_under_the_recovery_kind(self, registry, project):
        """DIAGRAM_KIND's lesson: a whole-resource row under KIND makes
        context_compile's query return exactly one row and suppress the
        results-reader fallback."""
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:00:00", run_label="detect", notes=["a note"])
        assert registry.query_findings(project.slug, KIND, "") == []

    def test_a_run_with_no_notes_writes_nothing(self, registry, project):
        persist_ir(registry, project.slug, [], [], "2026-08-30T00:00:00",
                   run_label="detect", notes=[])
        assert _notes(registry, project.slug) == {}

    def test_the_run_scope_travels_with_the_reasoning(self, registry, project):
        """A partial run's notes describe a partial view, and §4.1c's whole
        point is that a reader must be able to ask whether a result is complete."""
        persist_ir(registry, project.slug, [], [], "2026-08-30T00:00:00",
                   run_label="detect", notes=["a note"], run_scope="packages/foo")
        assert _notes(registry, project.slug)["decisions:detect"]["run_scope"] == "packages/foo"

    def test_a_long_note_list_is_capped_and_says_so(self, registry, project):
        """Prose for a human, not a log file in a findings row — but a silent
        truncation reads as "that was all of it"."""
        persist_ir(registry, project.slug, [], [], "2026-08-30T00:00:00",
                   run_label="detect", notes=[f"note {i}" for i in range(250)])
        detail = _notes(registry, project.slug)["decisions:detect"]
        assert len(detail["notes"]) == 200
        assert detail["truncated"] == 50

    def test_persisting_notes_cannot_fail_the_survey(self, registry, project, monkeypatch):
        """A decision trace must never break a survey that otherwise succeeded."""
        real = registry.upsert_finding

        def _boom(slug, kind, *a, **k):
            if kind == DECISIONS_KIND:
                raise RuntimeError("store is down")
            return real(slug, kind, *a, **k)

        monkeypatch.setattr(registry, "upsert_finding", _boom)
        persist_ir(registry, project.slug, [_component("a", "pkg/a")], [],
                   "2026-08-30T00:00:00", run_label="detect", notes=["a note"])
        assert registry.query_finding_scopes(project.slug, KIND, check_name="component") == ["pkg/a"]

    def test_both_real_steps_pass_their_notes(self):
        """Guards the call sites: the notes exist in both surveyors and were
        being dropped at the last hop, which is the bug this fixes."""
        import inspect

        from resource_explorer.surveyors.sub_surveyors import (
            arch_recovery_coupling,
            arch_recovery_detect,
        )
        assert "notes=notes" in inspect.getsource(arch_recovery_detect)
        assert "notes=notes" in inspect.getsource(arch_recovery_coupling)
