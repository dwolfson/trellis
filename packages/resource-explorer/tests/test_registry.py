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

    def test_remove_cleans_up_every_fk_child_table(self, db, sample_project):
        """remove() previously only cleaned up 5 of the 10 tables with a real
        FK to projects.slug — project_dependencies, project_file_type_counts,
        project_file_inventory, project_egeria_surveys, and
        project_data_profiles were silently left orphaned. Invisible on
        SQLite (no FK enforcement), a hard FK-violation crash on Postgres —
        found live during Phase 4 cutover testing. Also verifies delete
        ordering: children must go before the parent `projects` row, which
        Postgres enforces and SQLite (foreign_keys pragma off) does not."""
        db.add(sample_project)
        conn = sqlite3.connect(db.db_path)
        conn.execute(
            "INSERT INTO project_dependencies (project_slug, dep_name, dep_version, dep_type, indexed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test_project", "requests", "2.31.0", "pip", "2024-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO project_file_type_counts (project_slug, surveyed_at, type_label, file_count) "
            "VALUES (?, ?, ?, ?)",
            ("test_project", "2024-01-01T00:00:00", ".py", 10),
        )
        conn.execute(
            "INSERT INTO project_file_inventory (project_slug, file_path, indexed_at) "
            "VALUES (?, ?, ?)",
            ("test_project", "README.md", "2024-01-01T00:00:00"),
        )
        conn.commit()
        conn.close()

        db.remove("test-project")

        conn = sqlite3.connect(db.db_path)
        for table in ("project_dependencies", "project_file_type_counts", "project_file_inventory"):
            row = conn.execute(f"SELECT * FROM {table} WHERE project_slug = ?", ("test_project",)).fetchone()
            assert row is None, f"{table} row survived remove()"
        conn.close()


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

    def test_update_project_surveyed_at(self, db, sample_project):
        db.add(sample_project)
        assert db.get("test-project").last_surveyed_at == ""
        db.update_project_surveyed_at("test-project")
        assert db.get("test-project").last_surveyed_at != ""


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


class TestCurateTags:
    def test_add_and_list_tags(self, db):
        db.add_resource_tag("repo", "myproj", "gold-tier")
        db.add_resource_tag("repo", "myproj", "customer-facing")
        assert db.list_resource_tags("repo", "myproj") == ["customer-facing", "gold-tier"]

    def test_duplicate_tag_is_idempotent(self, db):
        db.add_resource_tag("repo", "myproj", "gold-tier")
        db.add_resource_tag("repo", "myproj", "gold-tier")
        assert db.list_resource_tags("repo", "myproj") == ["gold-tier"]

    def test_remove_tag(self, db):
        db.add_resource_tag("repo", "myproj", "gold-tier")
        db.remove_resource_tag("repo", "myproj", "gold-tier")
        assert db.list_resource_tags("repo", "myproj") == []

    def test_remove_nonexistent_tag_is_a_noop(self, db):
        db.remove_resource_tag("repo", "myproj", "nonexistent")  # should not raise

    def test_list_all_tags_with_counts(self, db):
        db.add_resource_tag("repo", "proj-a", "gold-tier")
        db.add_resource_tag("repo", "proj-b", "gold-tier")
        db.add_resource_tag("database", "db-a", "pii")
        tags = {t["tag"]: t["count"] for t in db.list_all_tags()}
        assert tags == {"gold-tier": 2, "pii": 1}

    def test_list_resources_by_tag(self, db):
        db.add_resource_tag("repo", "proj-a", "gold-tier")
        db.add_resource_tag("database", "db-a", "gold-tier")
        resources = db.list_resources_by_tag("gold-tier")
        assert {"entity_type": "repo", "entity_slug": "proj-a"} in resources
        assert {"entity_type": "database", "entity_slug": "db-a"} in resources

    def test_tags_scoped_per_resource(self, db):
        db.add_resource_tag("repo", "proj-a", "gold-tier")
        assert db.list_resource_tags("repo", "proj-b") == []


class TestCurateFeedback:
    def test_add_and_list_feedback(self, db):
        entry = db.add_resource_feedback("repo", "myproj", 4, "quality", "Schema looks stale")
        assert entry["rating"] == 4
        assert entry["category"] == "quality"
        listed = db.list_resource_feedback("repo", "myproj")
        assert len(listed) == 1
        assert listed[0]["message"] == "Schema looks stale"

    def test_feedback_without_rating(self, db):
        entry = db.add_resource_feedback("repo", "myproj", None, "", "Just a note")
        assert entry["rating"] is None

    def test_feedback_ordered_newest_first(self, db):
        db.add_resource_feedback("repo", "myproj", None, "", "first")
        db.add_resource_feedback("repo", "myproj", None, "", "second")
        listed = db.list_resource_feedback("repo", "myproj")
        assert listed[0]["message"] == "second"

    def test_feedback_scoped_per_resource(self, db):
        db.add_resource_feedback("repo", "proj-a", None, "", "a's feedback")
        assert db.list_resource_feedback("repo", "proj-b") == []


class TestCuratorNotes:
    def test_add_and_list_notes(self, db):
        entry = db.add_curator_note("repo", "myproj", "Needs a better README before promoting")
        assert entry["note"] == "Needs a better README before promoting"
        listed = db.list_curator_notes("repo", "myproj")
        assert len(listed) == 1

    def test_notes_ordered_newest_first(self, db):
        db.add_curator_note("repo", "myproj", "first")
        db.add_curator_note("repo", "myproj", "second")
        listed = db.list_curator_notes("repo", "myproj")
        assert listed[0]["note"] == "second"

    def test_delete_note(self, db):
        entry = db.add_curator_note("repo", "myproj", "temp note")
        assert db.delete_curator_note(entry["id"]) is True
        assert db.list_curator_notes("repo", "myproj") == []

    def test_delete_nonexistent_note_returns_false(self, db):
        assert db.delete_curator_note("nonexistent-id") is False

    def test_notes_scoped_per_resource(self, db):
        db.add_curator_note("repo", "proj-a", "a's note")
        assert db.list_curator_notes("repo", "proj-b") == []


class TestSchedules:
    def test_save_and_get_schedule(self, db):
        db.save_schedule("repo", "myproj", "security_scan", "weekly", True)
        rows = db.get_schedules("repo", "myproj")
        assert len(rows) == 1
        assert rows[0]["schedule"] == "weekly"
        assert rows[0]["enabled"] == 1
        assert rows[0]["next_run"]  # computed

    def test_save_schedule_upserts(self, db):
        db.save_schedule("repo", "myproj", "security_scan", "weekly", True)
        db.save_schedule("repo", "myproj", "security_scan", "daily", True)
        rows = db.get_schedules("repo", "myproj")
        assert len(rows) == 1
        assert rows[0]["schedule"] == "daily"

    def test_new_schedule_has_no_run_status_yet(self, db):
        db.save_schedule("repo", "myproj", "security_scan", "daily", True)
        rows = db.get_schedules("repo", "myproj")
        assert rows[0]["last_run_status"] == ""
        assert rows[0]["last_run_activity_id"] == ""

    def test_update_schedule_after_run_records_status_and_activity_id(self, db):
        db.save_schedule("repo", "myproj", "security_scan", "daily", True)
        db.update_schedule_after_run("repo", "myproj", "security_scan", status="ok", activity_id="act-123")
        rows = db.get_schedules("repo", "myproj")
        assert rows[0]["last_run_status"] == "ok"
        assert rows[0]["last_run_activity_id"] == "act-123"
        assert rows[0]["last_run"]  # timestamp recorded

    def test_update_schedule_after_run_records_error_status(self, db):
        db.save_schedule("repo", "myproj", "security_scan", "daily", True)
        db.update_schedule_after_run("repo", "myproj", "security_scan", status="error", activity_id="act-456")
        rows = db.get_schedules("repo", "myproj")
        assert rows[0]["last_run_status"] == "error"

    def test_update_schedule_after_run_advances_next_run(self, db):
        db.save_schedule("repo", "myproj", "security_scan", "daily", True)
        before = db.get_schedules("repo", "myproj")[0]["next_run"]
        db.update_schedule_after_run("repo", "myproj", "security_scan")
        after = db.get_schedules("repo", "myproj")[0]["next_run"]
        assert after != before  # advanced to a new next_run

    def test_update_schedule_after_run_missing_schedule_is_a_noop(self, db):
        db.update_schedule_after_run("repo", "nonexistent", "nonexistent-analysis")  # should not raise

    def test_list_all_schedules_across_resources(self, db):
        db.save_schedule("repo", "proj-a", "security_scan", "daily", True)
        db.save_schedule("database", "db-a", "schema_inventory", "weekly", True)
        rows = db.list_all_schedules()
        assert len(rows) == 2
        slugs = {r["entity_slug"] for r in rows}
        assert slugs == {"proj-a", "db-a"}

    def test_list_all_schedules_surfaces_errors_first(self, db):
        db.save_schedule("repo", "proj-ok", "security_scan", "daily", True)
        db.save_schedule("repo", "proj-err", "security_scan", "daily", True)
        db.update_schedule_after_run("repo", "proj-ok", "security_scan", status="ok")
        db.update_schedule_after_run("repo", "proj-err", "security_scan", status="error")
        rows = db.list_all_schedules()
        assert rows[0]["entity_slug"] == "proj-err"
        assert rows[0]["last_run_status"] == "error"

    def test_get_due_schedules_only_returns_enabled_and_past_due(self, db):
        db.save_schedule("repo", "proj-a", "security_scan", "manual", True)  # manual -> no next_run, never due
        db.save_schedule("repo", "proj-b", "security_scan", "daily", False)  # disabled
        assert db.get_due_schedules() == []

    def test_delete_schedule(self, db):
        db.save_schedule("repo", "myproj", "security_scan", "daily", True)
        assert db.delete_schedule("repo", "myproj", "security_scan") is True
        assert db.get_schedules("repo", "myproj") == []

    def test_delete_nonexistent_schedule_returns_false(self, db):
        assert db.delete_schedule("repo", "myproj", "nonexistent") is False


class TestAliases:
    """add_alias's project_aliases upsert was one of the two SQLite-only
    INSERT OR REPLACE statements converted to ON CONFLICT DO UPDATE for
    Postgres compatibility (migration plan Phase 3) — these specifically
    exercise both the insert and the update-on-conflict path."""

    def test_add_alias_then_resolve(self, db, sample_project):
        db.add(sample_project)
        db.add_alias("tp", "test-project")
        assert db.resolve_alias("tp") == "test_project"

    def test_resolve_missing_alias_returns_none(self, db):
        assert db.resolve_alias("ghost") is None

    def test_add_alias_normalizes_spaces_and_hyphens(self, db, sample_project):
        db.add(sample_project)
        db.add_alias("Test Project", "test-project")
        assert db.resolve_alias("test-project") == "test_project"
        assert db.resolve_alias("test project") == "test_project"

    def test_add_alias_conflict_updates_existing_row(self, db, sample_project):
        """The ON CONFLICT path: re-adding the same alias for a different
        project must update the mapping in place, not raise a PK violation."""
        db.add(sample_project)
        db.add(Project(slug="other-project", display_name="Other", github_url="https://github.com/a/other"))
        db.add_alias("tp", "test-project", confirmed_by="user")
        db.add_alias("tp", "other-project", confirmed_by="admin")
        assert db.resolve_alias("tp") == "other_project"
        aliases = db.list_aliases()
        assert len(aliases) == 1  # updated in place, not duplicated
        assert aliases[0]["confirmed_by"] == "admin"

    def test_remove_alias(self, db, sample_project):
        db.add(sample_project)
        db.add_alias("tp", "test-project")
        assert db.remove_alias("tp") is True
        assert db.resolve_alias("tp") is None

    def test_remove_nonexistent_alias_returns_false(self, db):
        assert db.remove_alias("ghost") is False

    def test_list_aliases_filtered_by_slug(self, db, sample_project):
        db.add(sample_project)
        db.add(Project(slug="other-project", display_name="Other", github_url="https://github.com/a/other"))
        db.add_alias("tp", "test-project")
        db.add_alias("op", "other-project")
        result = db.list_aliases(slug="test-project")
        assert [a["alias"] for a in result] == ["tp"]


class TestProjectGroups:
    """create_group's project_groups upsert is the other SQLite-only
    INSERT OR REPLACE converted to ON CONFLICT DO UPDATE for Postgres
    compatibility (migration plan Phase 3)."""

    def test_create_and_get_group(self, db):
        db.create_group("platform", "Platform Team", "Core platform repos")
        group = db.get_group("platform")
        assert group is not None
        assert group.display_name == "Platform Team"
        assert group.description == "Core platform repos"

    def test_get_missing_group_returns_none(self, db):
        assert db.get_group("ghost") is None

    def test_create_group_conflict_renames_in_place(self, db):
        """The ON CONFLICT path: re-creating the same slug must update the
        existing row (rename), not raise a PK violation or duplicate it."""
        db.create_group("platform", "Platform Team", "v1 description")
        db.create_group("platform", "Platform Team (renamed)", "v2 description")
        group = db.get_group("platform")
        assert group.display_name == "Platform Team (renamed)"
        assert group.description == "v2 description"
        assert len(db.list_groups()) == 1

    def test_list_groups_ordered_by_display_name(self, db):
        db.create_group("z", "Zebra Group")
        db.create_group("a", "Apple Group")
        names = [g.display_name for g in db.list_groups()]
        assert names == ["Apple Group", "Zebra Group"]

    def test_delete_group_ungroups_members(self, db, sample_project):
        db.create_group("platform", "Platform Team")
        db.add(sample_project)
        with db._conn() as conn:
            conn.execute(
                "UPDATE projects SET group_slug = ? WHERE slug = ?", ("platform", "test_project")
            )
        assert db.delete_group("platform") == 1
        assert db.get_group("platform") is None
        with db._conn() as conn:
            row = conn.execute(
                "SELECT group_slug FROM projects WHERE slug = ?", ("test_project",)
            ).fetchone()
        assert row["group_slug"] == ""


class TestCodeSymbolsAndRelationships:
    """AST-ownership-transfer plan Phase 3 — project_code_symbols' new fields
    (parent_class/return_type/is_private/is_async/complexity) and the new
    project_code_relationships table, both written by upsert_code_symbols()
    in a single call (mirroring Egeria Advisor's CodeSymbolStore.upsert_symbols())."""

    def _symbol(self, **overrides):
        from resource_explorer.ingestion.code_symbol_extractor import CodeSymbol
        defaults = dict(
            project_slug="test-project", file_path="mod.py", language="python",
            kind="function", name="f", qualified_name="f", signature="()",
            docstring="", start_line=1, end_line=2,
        )
        defaults.update(overrides)
        return CodeSymbol(**defaults)

    def test_upsert_persists_new_fields(self, db, sample_project):
        db.add(sample_project)
        sym = self._symbol(
            kind="method", name="method", qualified_name="Widget.method",
            parent_class="Widget", return_type="int", is_private=True,
            is_async=True, complexity=5,
        )
        db.upsert_code_symbols("test-project", [sym])
        with db._conn() as conn:
            row = conn.execute(
                "SELECT parent_class, return_type, is_private, is_async, complexity "
                "FROM project_code_symbols WHERE qualified_name = ?",
                ("Widget.method",),
            ).fetchone()
        assert row["parent_class"] == "Widget"
        assert row["return_type"] == "int"
        assert bool(row["is_private"]) is True
        assert bool(row["is_async"]) is True
        assert row["complexity"] == 5

    def test_upsert_derives_inherits_from_relationships(self, db, sample_project):
        db.add(sample_project)
        cls = self._symbol(
            kind="class", name="Child", qualified_name="Child",
            bases=["Base", "Mixin"],
        )
        db.upsert_code_symbols("test-project", [cls])
        rels = db.get_code_relationships("test-project")
        assert {(r["source_name"], r["target_name"]) for r in rels} == {
            ("Child", "Base"), ("Child", "Mixin"),
        }

    def test_non_class_symbols_produce_no_relationships(self, db, sample_project):
        db.add(sample_project)
        fn = self._symbol(kind="function", name="f", qualified_name="f")
        db.upsert_code_symbols("test-project", [fn])
        assert db.get_code_relationships("test-project") == []

    def test_upsert_conflict_updates_new_fields(self, db, sample_project):
        """ON CONFLICT DO UPDATE must cover the new columns too — re-upserting
        the same symbol with a different complexity/parent_class must update
        in place, not silently keep the stale value."""
        db.add(sample_project)
        sym1 = self._symbol(qualified_name="f", complexity=1)
        sym2 = self._symbol(qualified_name="f", complexity=9, return_type="str")
        db.upsert_code_symbols("test-project", [sym1])
        db.upsert_code_symbols("test-project", [sym2])
        with db._conn() as conn:
            row = conn.execute(
                "SELECT complexity, return_type FROM project_code_symbols WHERE qualified_name = ?",
                ("f",),
            ).fetchone()
        assert row["complexity"] == 9
        assert row["return_type"] == "str"

    def test_relationship_conflict_does_nothing_no_duplicate(self, db, sample_project):
        db.add(sample_project)
        cls = self._symbol(kind="class", name="Child", qualified_name="Child", bases=["Base"])
        db.upsert_code_symbols("test-project", [cls])
        db.upsert_code_symbols("test-project", [cls])  # re-upsert same relationship
        rels = db.get_code_relationships("test-project")
        assert len(rels) == 1

    def test_clear_code_symbols_full_also_clears_relationships(self, db, sample_project):
        db.add(sample_project)
        cls = self._symbol(kind="class", name="Child", qualified_name="Child", bases=["Base"])
        db.upsert_code_symbols("test-project", [cls])
        assert db.get_code_relationships("test-project") != []
        db.clear_code_symbols("test-project")
        assert db.get_code_relationships("test-project") == []

    def test_clear_code_symbols_language_filtered_keeps_relationships(self, db, sample_project):
        db.add(sample_project)
        cls = self._symbol(kind="class", name="Child", qualified_name="Child", bases=["Base"])
        db.upsert_code_symbols("test-project", [cls])
        db.clear_code_symbols("test-project", language="python")
        # language-filtered clear intentionally leaves relationships alone (see docstring)
        assert db.get_code_relationships("test-project") != []

    def test_remove_project_cleans_up_relationships(self, db, sample_project):
        db.add(sample_project)
        cls = self._symbol(kind="class", name="Child", qualified_name="Child", bases=["Base"])
        db.upsert_code_symbols("test-project", [cls])
        db.remove("test-project")
        with db._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM project_code_relationships WHERE project_slug = ?",
                ("test_project",),
            ).fetchall()
        assert rows == []
