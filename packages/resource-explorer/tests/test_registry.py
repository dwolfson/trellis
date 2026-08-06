"""Tests for ProjectRegistry — SQLite CRUD, schema migration, stats."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from resource_explorer.registry import Project, ProjectRegistry, ProjectStatus


@pytest.fixture
def db(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def sample_project():
    return Project(
        slug="test-project",
        display_name="Test Project",
        github_url="https://github.com/test/test-project",
        description="A test project",
    )


class TestCRUD:
    def test_add_and_get(self, db, sample_project):
        db.add(sample_project)
        result = db.get("test-project")
        assert result is not None
        assert result.slug == "test_project"
        assert result.display_name == "Test Project"

    def test_get_missing_returns_none(self, db):
        assert db.get("nonexistent") is None

    def test_exists(self, db, sample_project):
        assert not db.exists("test-project")
        db.add(sample_project)
        assert db.exists("test-project")

    def test_list_all_empty(self, db):
        assert db.list_all() == []

    def test_list_all_ordered_by_display_name(self, db):
        db.add(Project(slug="z", display_name="Zebra", github_url="https://github.com/a/z"))
        db.add(Project(slug="a", display_name="Apple", github_url="https://github.com/a/a"))
        names = [p.display_name for p in db.list_all()]
        assert names == ["Apple", "Zebra"]

    def test_remove(self, db, sample_project):
        db.add(sample_project)
        db.remove("test-project")
        assert db.get("test-project") is None

    def test_remove_also_removes_stats(self, db, sample_project):
        db.add(sample_project)
        conn = sqlite3.connect(db.db_path)
        conn.execute(
            "INSERT INTO project_stats (project_slug, fetched_at, stars) VALUES (?, ?, ?)",
            ("test_project", "2024-01-01T00:00:00", 100),
        )
        conn.commit()
        conn.close()
        db.remove("test-project")
        conn = sqlite3.connect(db.db_path)
        row = conn.execute(
            "SELECT * FROM project_stats WHERE project_slug = ?", ("test_project",)
        ).fetchone()
        conn.close()
        assert row is None


class TestStatusUpdates:
    def test_update_status(self, db, sample_project):
        db.add(sample_project)
        db.update_status("test-project", ProjectStatus.INDEXING)
        assert db.get("test-project").status == ProjectStatus.INDEXING

    def test_update_status_with_error(self, db, sample_project):
        db.add(sample_project)
        db.update_status("test-project", ProjectStatus.ERROR, "connection failed")
        p = db.get("test-project")
        assert p.status == ProjectStatus.ERROR
        assert p.error_message == "connection failed"

    def test_update_indexed_at(self, db, sample_project):
        db.add(sample_project)
        db.update_indexed_at("test-project", ["test-project_python_code"])
        p = db.get("test-project")
        assert "test-project_python_code" in p.collections
        assert p.last_indexed_at != ""

    def test_update_commit_sha(self, db, sample_project):
        db.add(sample_project)
        db.update_commit_sha("test-project", "abc123def456")
        assert db.get("test-project").last_commit_sha == "abc123def456"


class TestSchemaMigration:
    def test_migration_adds_last_commit_sha_to_old_db(self, tmp_path):
        db_path = str(tmp_path / "old.db")
        # Create a database without last_commit_sha (simulating pre-migration schema)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE projects (
                slug TEXT PRIMARY KEY, display_name TEXT NOT NULL,
                github_url TEXT NOT NULL, description TEXT DEFAULT '',
                homepage_url TEXT DEFAULT '', docs_url TEXT DEFAULT '',
                github_token_encrypted TEXT DEFAULT '', collections TEXT DEFAULT '[]',
                status TEXT DEFAULT 'active', last_indexed_at TEXT DEFAULT '',
                last_stats_fetched_at TEXT DEFAULT '', created_at TEXT NOT NULL,
                error_message TEXT DEFAULT ''
            )
        """)
        conn.execute(
            "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("old", "Old", "https://github.com/a/b", "", "", "", "[]", "[]",
             "active", "", "", "2024-01-01T00:00:00", ""),
        )
        conn.commit()
        conn.close()

        # Opening with ProjectRegistry should apply the migration
        db = ProjectRegistry(db_path=db_path)
        p = db.get("old")
        assert p is not None
        assert p.last_commit_sha == ""  # default applied by migration
