"""Tests for Phase B's per-analysis-type results/history storage in
ProjectRegistry — dependency append-not-overwrite (D2), and the new
data-profile-snapshot/security-findings/documentation-findings/
api-structure-snapshot tables (D3/D4/D5), all mirroring
project_file_type_counts's proven append pattern.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def db(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def sample_project(db):
    p = Project(
        slug="test-project",
        display_name="Test Project",
        github_url="https://github.com/test/test-project",
    )
    db.add(p)
    return p


class TestDependenciesAppendHistory:
    def test_upsert_appends_not_replaces(self, db, sample_project):
        db.upsert_dependencies("test-project", [{"dep_name": "flask", "dep_version": "1.0", "dep_type": "runtime", "ecosystem": "python", "source_file": "requirements.txt"}])
        db.upsert_dependencies("test-project", [{"dep_name": "flask", "dep_version": "2.0", "dep_type": "runtime", "ecosystem": "python", "source_file": "requirements.txt"}])
        with db._conn() as conn:
            # project_slug is stored normalized (hyphens -> underscores) —
            # match that here, same as every registry method does internally.
            count = conn.execute("SELECT COUNT(*) as c FROM project_dependencies WHERE project_slug = ?", ("test_project",)).fetchone()["c"]
        assert count == 2  # both runs' rows kept, not deleted

    def test_query_returns_only_latest_batch(self, db, sample_project):
        db.upsert_dependencies("test-project", [{"dep_name": "old-dep", "dep_version": "1.0", "dep_type": "runtime", "ecosystem": "python", "source_file": "a"}])
        db.upsert_dependencies("test-project", [{"dep_name": "new-dep", "dep_version": "1.0", "dep_type": "runtime", "ecosystem": "python", "source_file": "a"}])
        deps = db.query_dependencies("test-project")
        names = [d["dep_name"] for d in deps]
        assert names == ["new-dep"]  # old-dep from the prior run is not in the latest batch

    def test_query_history_one_row_per_run(self, db, sample_project):
        db.upsert_dependencies("test-project", [{"dep_name": "a", "dep_version": "", "dep_type": "runtime", "ecosystem": "python", "source_file": ""}])
        db.upsert_dependencies("test-project", [
            {"dep_name": "a", "dep_version": "", "dep_type": "runtime", "ecosystem": "python", "source_file": ""},
            {"dep_name": "b", "dep_version": "", "dep_type": "runtime", "ecosystem": "python", "source_file": ""},
        ])
        history = db.query_dependencies_history("test-project")
        assert len(history) == 2
        assert history[0]["total_dependencies"] == 1
        assert history[1]["total_dependencies"] == 2

    def test_empty_deps_is_a_noop(self, db, sample_project):
        db.upsert_dependencies("test-project", [])
        assert db.query_dependencies("test-project") == []


class TestDependencyLegacyTimestampRepair:
    """The original upsert_dependencies() computed datetime.utcnow() inside
    its per-row list comprehension, so every row in one conceptual ingest
    got its own microsecond-distinct indexed_at — breaking the new
    MAX(indexed_at) latest-batch filter down to "1 row" for legacy data.
    ProjectRegistry.__init__ repairs this once, safely, on every startup."""

    def test_legacy_per_row_timestamps_are_collapsed_to_one_batch(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        db = ProjectRegistry(db_path=db_path)
        db.add(Project(slug="legacy-proj", display_name="Legacy", github_url="https://github.com/a/b"))
        # Simulate the old bug directly: 3 rows, each its own distinct timestamp.
        with db._conn() as conn:
            for i, name in enumerate(["a", "b", "c"]):
                conn.execute(
                    "INSERT INTO project_dependencies (project_slug, dep_name, dep_version, dep_type, ecosystem, source_file, indexed_at) "
                    "VALUES (?, ?, '', 'runtime', 'python', '', ?)",
                    ("legacy_proj", name, f"2026-01-01T00:00:00.00000{i}"),
                )

        # Re-opening the registry (a fresh ProjectRegistry(), as every
        # request in this app does) must repair it.
        db2 = ProjectRegistry(db_path=db_path)
        deps = db2.query_dependencies("legacy-proj")
        assert len(deps) == 3  # all 3 legacy deps visible, not just 1
        history = db2.query_dependencies_history("legacy-proj")
        assert len(history) == 1  # collapsed into one batch, not 3

    def test_does_not_touch_already_correct_multi_batch_history(self, db, sample_project):
        # A real (post-fix) multi-run history must survive the repair step
        # untouched — the self-limiting guard (COUNT(DISTINCT) < COUNT(*)).
        db.upsert_dependencies("test-project", [{"dep_name": "a", "dep_version": "", "dep_type": "runtime", "ecosystem": "python", "source_file": ""}])
        db.upsert_dependencies("test-project", [
            {"dep_name": "a", "dep_version": "", "dep_type": "runtime", "ecosystem": "python", "source_file": ""},
            {"dep_name": "b", "dep_version": "", "dep_type": "runtime", "ecosystem": "python", "source_file": ""},
        ])
        before = db.query_dependencies_history("test-project")
        assert len(before) == 2

        db._init_schema()  # re-run the migration block explicitly
        after = db.query_dependencies_history("test-project")
        assert after == before  # untouched — still 2 distinct real batches

    def test_single_dependency_project_is_a_harmless_noop(self, db, sample_project):
        db.upsert_dependencies("test-project", [{"dep_name": "only-dep", "dep_version": "", "dep_type": "runtime", "ecosystem": "python", "source_file": ""}])
        db._init_schema()
        deps = db.query_dependencies("test-project")
        assert len(deps) == 1
        assert deps[0]["dep_name"] == "only-dep"


class TestFindingEgeriaGuid:
    """docs/annotation-linking-plan.md Phase 1: egeria_annotation_guid column
    + mark_finding_guid(). New tests, not read-source assertions — every one
    below executes the real migration/update path against a real (SQLite)
    connection."""

    def _finding_id(self, db, slug="test-project", kind="security_hygiene"):
        db.upsert_finding(slug, kind, [
            {"check_name": "has_ci", "label": "pass", "summary": "", "confidence": 100, "detail": None},
        ])
        with db._conn() as conn:
            row = conn.execute(
                "SELECT id FROM project_analysis_findings WHERE project_slug = ? AND kind = ?",
                ("test_project", kind),
            ).fetchone()
        return row["id"]

    def test_new_column_defaults_to_null_not_empty_string(self, db, sample_project):
        """A freshly inserted finding row — never touched by mark_finding_guid
        — must read back NULL, not '', so it is not confusable with a
        deliberately-recorded empty value."""
        finding_id = self._finding_id(db, sample_project.slug)
        with db._conn() as conn:
            row = conn.execute(
                "SELECT egeria_annotation_guid FROM project_analysis_findings WHERE id = ?",
                (finding_id,),
            ).fetchone()
        assert row["egeria_annotation_guid"] is None

    def test_existing_rows_survive_migration_untouched(self, db, sample_project):
        """Re-running the migration block (as every ProjectRegistry() startup
        does) against a table that already has real rows must not error and
        must not disturb them — the ~68,000-row concern, exercised at small
        scale."""
        finding_id = self._finding_id(db, sample_project.slug)
        db.mark_finding_guid(finding_id, "guid-before-migration")
        db._init_schema()  # re-run the migration block explicitly
        with db._conn() as conn:
            row = conn.execute(
                "SELECT egeria_annotation_guid FROM project_analysis_findings WHERE id = ?",
                (finding_id,),
            ).fetchone()
        assert row["egeria_annotation_guid"] == "guid-before-migration"

    def test_mark_finding_guid_writes_the_guid(self, db, sample_project):
        finding_id = self._finding_id(db, sample_project.slug)
        db.mark_finding_guid(finding_id, "real-annotation-guid-123")
        with db._conn() as conn:
            row = conn.execute(
                "SELECT egeria_annotation_guid FROM project_analysis_findings WHERE id = ?",
                (finding_id,),
            ).fetchone()
        assert row["egeria_annotation_guid"] == "real-annotation-guid-123"

    def test_mark_finding_guid_only_touches_the_named_row(self, db, sample_project):
        """A second finding row in the same batch must not pick up the first
        row's GUID — the UPDATE is keyed by id, not by kind/slug."""
        db.upsert_finding(sample_project.slug, "security_hygiene", [
            {"check_name": "has_ci", "label": "pass", "summary": "", "confidence": 100, "detail": None},
            {"check_name": "has_tests", "label": "pass", "summary": "", "confidence": 100, "detail": None},
        ])
        with db._conn() as conn:
            rows = conn.execute(
                "SELECT id, check_name FROM project_analysis_findings "
                "WHERE project_slug = ? ORDER BY check_name",
                ("test_project",),
            ).fetchall()
        ci_id = next(r["id"] for r in rows if r["check_name"] == "has_ci")
        tests_id = next(r["id"] for r in rows if r["check_name"] == "has_tests")

        db.mark_finding_guid(ci_id, "ci-guid")

        with db._conn() as conn:
            ci_row = conn.execute(
                "SELECT egeria_annotation_guid FROM project_analysis_findings WHERE id = ?", (ci_id,)
            ).fetchone()
            tests_row = conn.execute(
                "SELECT egeria_annotation_guid FROM project_analysis_findings WHERE id = ?", (tests_id,)
            ).fetchone()
        assert ci_row["egeria_annotation_guid"] == "ci-guid"
        assert tests_row["egeria_annotation_guid"] is None

    def test_known_negative_empty_guid_is_not_recorded(self, db, sample_project):
        """The guard this whole column exists to prove: calling
        mark_finding_guid with a falsy GUID (the "create succeeded but Egeria
        returned no guid key" case, or a caller passing through a failed
        create's None) must NOT overwrite the column with '' — it must be a
        no-op, leaving the row exactly as unpublished-looking as before.
        Proven by first showing the call DOES write for a real GUID (so this
        isn't a no-op that "passes" only because nothing ran), then showing it
        does NOT write for an empty one."""
        finding_id = self._finding_id(db, sample_project.slug)

        # Positive control: a real GUID is recorded.
        db.mark_finding_guid(finding_id, "guid-that-should-stick")
        with db._conn() as conn:
            row = conn.execute(
                "SELECT egeria_annotation_guid FROM project_analysis_findings WHERE id = ?",
                (finding_id,),
            ).fetchone()
        assert row["egeria_annotation_guid"] == "guid-that-should-stick"

        # Known-negative: an empty-string GUID (simulating a failed/empty
        # create) must not clobber it — and, tested independently on a fresh
        # row, must not write '' at all.
        finding_id_2 = self._finding_id(db, sample_project.slug, kind="ci_quality")
        db.mark_finding_guid(finding_id_2, "")
        with db._conn() as conn:
            row2 = conn.execute(
                "SELECT egeria_annotation_guid FROM project_analysis_findings WHERE id = ?",
                (finding_id_2,),
            ).fetchone()
        assert row2["egeria_annotation_guid"] is None, (
            "mark_finding_guid('') must leave the row NULL — writing '' would "
            "make a failed/empty create indistinguishable from a real, if "
            "empty, one"
        )
