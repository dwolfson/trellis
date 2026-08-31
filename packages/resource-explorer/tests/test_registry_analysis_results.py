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
