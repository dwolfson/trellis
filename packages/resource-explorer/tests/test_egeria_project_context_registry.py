"""Tests for entity_egeria_project_context — the Egeria Project context
registry table (Discovery-tier Part 5). Always "Egeria Project" — RE's own
Project class is a distinct, unrelated concept that happens to share the
word (see registry.py's table docstring).
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


class TestGetProjectContext:
    def test_returns_none_when_never_decided(self, registry):
        assert registry.get_project_context("repo", "myproj") is None

    def test_returns_row_after_set(self, registry):
        registry.set_project_context("repo", "myproj", "personal")
        row = registry.get_project_context("repo", "myproj")
        assert row["status"] == "personal"
        assert row["entity_type"] == "repo"
        assert row["entity_slug"] == "myproj"
        assert row["decided_at"]


class TestSetProjectContext:
    def test_upsert_not_append_only_one_current_row(self, registry):
        registry.set_project_context("repo", "myproj", "personal")
        registry.set_project_context("repo", "myproj", "declined")
        row = registry.get_project_context("repo", "myproj")
        assert row["status"] == "declined"

        with registry._conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) c FROM entity_egeria_project_context "
                "WHERE entity_type='repo' AND entity_slug='myproj'"
            ).fetchone()["c"]
        assert count == 1

    def test_linked_stores_egeria_project_identity(self, registry):
        registry.set_project_context(
            "repo", "myproj", "linked",
            egeria_project_guid="guid-123",
            egeria_project_qualified_name="Project::Foo::1.0",
        )
        row = registry.get_project_context("repo", "myproj")
        assert row["egeria_project_guid"] == "guid-123"
        assert row["egeria_project_qualified_name"] == "Project::Foo::1.0"

    def test_deferred_stores_free_text_name(self, registry):
        registry.set_project_context("repo", "myproj", "deferred", free_text_name="Q3 Data Migration")
        row = registry.get_project_context("repo", "myproj")
        assert row["free_text_name"] == "Q3 Data Migration"

    def test_scoped_independently_per_entity_type_and_slug(self, registry):
        registry.set_project_context("repo", "myproj", "personal")
        registry.set_project_context("database", "myproj", "declined")
        registry.set_project_context("repo", "otherproj", "deferred", free_text_name="X")

        assert registry.get_project_context("repo", "myproj")["status"] == "personal"
        assert registry.get_project_context("database", "myproj")["status"] == "declined"
        assert registry.get_project_context("repo", "otherproj")["status"] == "deferred"

    def test_slug_normalized_same_as_other_entity_scoped_tables(self, registry):
        registry.set_project_context("repo", "MyProj", "personal")
        # _normalize_slug() is the same helper resource_working_set/
        # repo_dispositions already rely on — confirm this table uses it too.
        row = registry.get_project_context("repo", "myproj")
        assert row is not None
        assert row["status"] == "personal"

    def test_can_be_reset_back_to_unset(self, registry):
        registry.set_project_context("repo", "myproj", "personal")
        registry.set_project_context("repo", "myproj", "unset")
        row = registry.get_project_context("repo", "myproj")
        assert row["status"] == "unset"
