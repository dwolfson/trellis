"""compile_context() reads the resource type it is asked about, not always repo.

Root cause this pins: `compile_context()` hardcoded `"repo"` at its two catalog
calls (`get_questions("repo", ...)`, `get_analyses("repo", ...)`) and, further
down, imported `REPO_ANALYSIS_HEADLINE_MAP`/`REPO_ANALYSIS_RESULTS_MAP`
unconditionally for its results-reader/headline fallback -- with no
`resource_type` parameter on the function at all. Every chat/Ask compile,
whatever resource was actually selected, silently compiled against the repo
catalog and repo analyses. Live-confirmed: asking a real database "How many
rows?" packed `foss_scorecard`/`chaoss_metrics`/`repository_health` as the
nearest evidence and reported no answer, although `row_count_snapshot` (a real
database analysis) had it.

Mirrors tests/test_fact_layer_resource_type_dispatch.py's style: the repo path
is a refactor and must be unchanged; the database path is the one that could
not previously be expressed at all.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from resource_explorer.context_compile import compile_context


class _NullMock(MagicMock):
    """See test_context_compile.py's own _NullMock docstring: an unconfigured
    method must return None, not another MagicMock, or the results readers
    build dicts of mock-repr strings that the compiler then packs as if they
    were real content."""

    def _get_child_mock(self, **kw):
        child = _NullMock(**kw)
        child.return_value = None
        return child


def _registry(findings_by_kind=None):
    r = _NullMock()
    r.query_findings.side_effect = lambda slug, kind, *a, **k: (findings_by_kind or {}).get(kind, [])
    return r


class TestDefaultIsStillRepo:
    def test_no_resource_type_argument_compiles_as_repo(self):
        """The one thing every existing caller (pre-fix) relied on: omitting
        the new parameter must behave exactly as before."""
        c = compile_context(_registry(), "egeria", "How well documented is it?", budget=4000)
        gap_keys = {g["key"] for g in c.manifest["gaps"]}
        packed_keys = {p["key"] for p in c.manifest["packed"]}
        # A repo-only analysis id must be reachable (as a gap or packed) --
        # a database/filesystem compile would never mention this id at all.
        assert "documentation_coverage" in (gap_keys | packed_keys)

    def test_explicit_repo_matches_the_default(self):
        c_default = compile_context(_registry(), "egeria", "How well documented is it?", budget=4000)
        c_explicit = compile_context(_registry(), "egeria", "How well documented is it?",
                                     resource_type="repo", budget=4000)
        default_ids = {d["analysis_ids"][0] for d in c_default.derivation if d["analysis_ids"]}
        explicit_ids = {d["analysis_ids"][0] for d in c_explicit.derivation if d["analysis_ids"]}
        assert default_ids == explicit_ids

    def test_manifest_names_the_resource_type(self):
        c = compile_context(_registry(), "egeria", "q", budget=4000)
        assert c.manifest["resource_type"] == "repo"


class TestADatabaseScopedCompilePullsDatabaseCatalog:
    def test_gaps_and_derivation_never_name_a_repo_only_analysis(self):
        """The live bug, directly: a database question must never surface
        `foss_scorecard`/`chaoss_metrics`/`repository_health` -- those exist
        only in the repo catalog and cannot answer anything about a database."""
        c = compile_context(_registry(), "coco_ods", "How many rows?",
                            resource_type="database", budget=4000)
        named_ids = {g["key"] for g in c.manifest["gaps"]} | {p["key"] for p in c.manifest["packed"]}
        for d in c.derivation:
            named_ids |= set(d["analysis_ids"])
        repo_only = {"foss_scorecard", "chaoss_metrics", "repository_health", "community_support"}
        assert not (named_ids & repo_only), (
            f"a database compile must not reach repo-only analyses; found {named_ids & repo_only}"
        )

    def test_a_database_analysis_is_reachable(self):
        """The other half of the same bug: not just "no repo leakage" but
        "the real database analysis is actually offered"."""
        c = compile_context(_registry(), "coco_ods", "How many rows?",
                            resource_type="database", budget=4000)
        named_ids = {g["key"] for g in c.manifest["gaps"]} | {p["key"] for p in c.manifest["packed"]}
        assert "row_count_snapshot" in named_ids

    def test_a_database_finding_is_actually_packed(self):
        """Not just offered as a gap -- when a finding exists, it packs,
        proving the results-reader fallback (REPO_ANALYSIS_RESULTS_MAP before
        the fix) is now reading from the database's own map."""
        finding = [{"check_name": "row_count_snapshot", "label": "measured",
                    "summary": "12 tables measured", "surveyed_at": "2026-09-01T00:00:00"}]
        c = compile_context(_registry({"row_count_snapshot": finding}), "coco_ods",
                            "How many rows?", resource_type="database", budget=4000)
        packed_keys = {p["key"] for p in c.manifest["packed"]}
        assert "row_count_snapshot" in packed_keys

    def test_manifest_names_the_resource_type(self):
        c = compile_context(_registry(), "coco_ods", "q", resource_type="database", budget=4000)
        assert c.manifest["resource_type"] == "database"

    def test_the_results_reader_fallback_reads_the_database_map_not_repos(self, monkeypatch):
        """Direct proof the fallback dispatch is resource-type-aware: a
        DATABASE_ANALYSIS_RESULTS_MAP reader is called, and a corresponding
        REPO_ANALYSIS_RESULTS_MAP reader (if the id existed there) is not."""
        import resource_explorer.surveyors.database.survey_definition_adapter as db_adapter

        calls: list[str] = []

        def _fake_reader(reg, slug):
            calls.append(slug)
            return {"tables": 3, "measured_count": 3}

        monkeypatch.setitem(db_adapter.DATABASE_ANALYSIS_RESULTS_MAP,
                            "row_count_snapshot", (_fake_reader, None))

        compile_context(_registry(), "coco_ods", "How many rows?",
                        resource_type="database", budget=4000)
        assert calls == ["coco_ods"]


class TestAFilesystemScopedCompile:
    def test_gaps_never_name_a_repo_only_analysis(self):
        c = compile_context(_registry(), "some-fs", "What kinds of files are here?",
                            resource_type="filesystem", budget=4000)
        named_ids = {g["key"] for g in c.manifest["gaps"]} | {p["key"] for p in c.manifest["packed"]}
        for d in c.derivation:
            named_ids |= set(d["analysis_ids"])
        assert "foss_scorecard" not in named_ids
        assert "repository_health" not in named_ids

    def test_manifest_names_the_resource_type(self):
        c = compile_context(_registry(), "some-fs", "q", resource_type="filesystem", budget=4000)
        assert c.manifest["resource_type"] == "filesystem"


class TestUnknownResourceTypeDoesNotCrash:
    def test_no_adapter_registered_still_compiles(self):
        """An unrecognised resource_type must degrade to "no extra readers
        available" (same as FactLayer's own undeclared-adapter handling),
        never raise -- a compile must never be lost to a lookup failure."""
        c = compile_context(_registry(), "some-thing", "q", resource_type="model", budget=4000)
        assert c.manifest["resource_type"] == "model"
