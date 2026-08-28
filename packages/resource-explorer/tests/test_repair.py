"""Tests for resource_explorer/repair.py and ProjectRegistry.rename_project_slug —
the four repair operations from docs/repair-operations-design.md: rename,
github_url correction, drift-flagged collection enablement, and investigation
membership repoint/drop.

pgvector and GitHub calls are mocked throughout (this repo's tests run
without either service reachable by default); the SQLite-layer rename itself
runs for real against a temp registry, with PRAGMA foreign_keys=ON exactly
like production Postgres enforces (registry._conn()'s own comment).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.repair import (
    RepairError,
    change_github_url,
    drop_investigation_member,
    enable_collection,
    list_repo_investigation_memberships,
    rename_repo,
    repoint_investigation_member,
)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def repo(registry):
    slug = "old_slug"
    registry.add(Project(
        slug=slug, display_name="Old Slug", github_url="https://github.com/o/old",
        collections=[f"{slug}_python_code", f"{slug}_markdown_docs",
                     "web_docs_shared_org"],  # a shared collection this repo does NOT own
    ))
    registry.upsert_file_type_counts(slug, {".py": 10})
    registry.add_alias("Old Thing", slug)
    registry.set_disposition("https://github.com/o/old", "tracking", reason="looks useful")
    return slug


class TestRenameProjectSlugSQL:
    """The registry-layer rename — no pgvector involved, exercises every
    table it touches."""

    def test_renames_the_projects_row(self, registry, repo):
        registry.rename_project_slug(repo, "new_slug")
        assert registry.get(repo) is None
        renamed = registry.get("new_slug")
        assert renamed is not None
        assert renamed.display_name == "Old Slug"
        assert renamed.github_url == "https://github.com/o/old"

    def test_carries_project_slug_tables(self, registry, repo):
        registry.rename_project_slug(repo, "new_slug")
        counts = registry.query_file_type_counts("new_slug")
        assert any(c["type_label"] == ".py" and c["file_count"] == 10 for c in counts)
        assert registry.query_file_type_counts(repo) == []

    def test_carries_aliases(self, registry, repo):
        registry.rename_project_slug(repo, "new_slug")
        assert registry.resolve_alias("Old Thing") == "new_slug"

    def test_carries_disposition(self, registry, repo):
        registry.rename_project_slug(repo, "new_slug")
        disp = registry.get_disposition("https://github.com/o/old")
        assert disp["disposition"] == "tracking"

    def test_carries_entity_slug_tables(self, registry, repo):
        registry.add_resource_tag("repo", repo, "reference-implementation")
        registry.rename_project_slug(repo, "new_slug")
        assert registry.list_resource_tags("repo", "new_slug") == ["reference-implementation"]
        assert registry.list_resource_tags("repo", repo) == []

    def test_carries_sub_projects_parent_slug(self, registry, repo):
        registry.add(Project(slug="child", display_name="Child",
                             github_url="https://github.com/o/old", parent_slug=repo))
        registry.rename_project_slug(repo, "new_slug")
        assert registry.get("child").parent_slug == "new_slug"

    def test_can_override_collections_json(self, registry, repo):
        new_cols = json.dumps(["new_slug_python_code", "web_docs_shared_org"])
        registry.rename_project_slug(repo, "new_slug", new_collections_json=new_cols)
        assert registry.get("new_slug").collections == ["new_slug_python_code", "web_docs_shared_org"]

    def test_refuses_missing_source(self, registry):
        with pytest.raises(ValueError, match="not registered"):
            registry.rename_project_slug("nope", "new_slug")

    def test_refuses_collision(self, registry, repo):
        registry.add(Project(slug="taken", display_name="Taken", github_url="https://github.com/x/y"))
        with pytest.raises(ValueError, match="already exists"):
            registry.rename_project_slug(repo, "taken")

    def test_refuses_same_slug(self, registry, repo):
        with pytest.raises(ValueError, match="same"):
            registry.rename_project_slug(repo, repo)


class TestRenameRepoOrchestration:
    """repair.rename_repo() — the pgvector + registry combination."""

    def test_renames_only_owned_collections(self, registry, repo):
        store = MagicMock()
        with patch("resource_explorer.vector_store_pg.MultiCollectionStore", return_value=store):
            result = rename_repo(repo, "new_slug", registry=registry)

        renamed_names = {call.args for call in store.rename_collection.call_args_list}
        assert ("old_slug_python_code", "new_slug_python_code") in renamed_names
        assert ("old_slug_markdown_docs", "new_slug_markdown_docs") in renamed_names
        # The shared collection was never handed to rename_collection at all.
        assert not any("web_docs_shared_org" in pair for pair in renamed_names)
        assert result.unchanged_shared_collections == ["web_docs_shared_org"]
        assert set(registry.get("new_slug").collections) == {
            "new_slug_python_code", "new_slug_markdown_docs", "web_docs_shared_org",
        }

    def test_rolls_back_on_partial_pgvector_failure(self, registry, repo):
        store = MagicMock()
        # First rename succeeds, second raises -- registry must be untouched
        # and the first rename must be reversed.
        store.rename_collection.side_effect = [None, RuntimeError("boom")]
        with patch("resource_explorer.vector_store_pg.MultiCollectionStore", return_value=store):
            with pytest.raises(RepairError, match="boom"):
                rename_repo(repo, "new_slug", registry=registry)

        assert registry.get(repo) is not None
        assert registry.get("new_slug") is None
        # rename_collection called 3 times: 2 forward attempts + 1 rollback
        # of the one that succeeded.
        assert store.rename_collection.call_count == 3
        rollback_call = store.rename_collection.call_args_list[-1]
        assert rollback_call.args == ("new_slug_python_code", "old_slug_python_code")

    def test_refuses_unregistered_repo(self, registry):
        with pytest.raises(RepairError, match="not registered"):
            rename_repo("nope", "new_slug", registry=registry)

    def test_refuses_collision(self, registry, repo):
        registry.add(Project(slug="taken", display_name="Taken", github_url="https://github.com/x/y"))
        with pytest.raises(RepairError, match="already exists"):
            rename_repo(repo, "taken", registry=registry)


class TestChangeGithubUrl:
    def test_refuses_without_confirm(self, registry, repo):
        with pytest.raises(RepairError, match="invalidates"):
            change_github_url(repo, "https://github.com/o/correct", registry=registry)
        # Nothing changed.
        assert registry.get(repo).github_url == "https://github.com/o/old"

    def test_confirmed_drops_collections_and_invalidates(self, registry, repo):
        store = MagicMock()
        with patch("resource_explorer.vector_store_pg.MultiCollectionStore", return_value=store):
            result = change_github_url(repo, "https://github.com/o/correct", confirm=True, registry=registry)

        assert store.drop_collection.call_count == 3
        updated = registry.get(repo)
        assert updated.github_url == "https://github.com/o/correct"
        assert updated.collections == []
        assert updated.last_indexed_at == ""
        assert len(result["dropped_collections"]) == 3

    def test_refuses_unregistered_repo(self, registry):
        with pytest.raises(RepairError, match="not registered"):
            change_github_url("nope", "https://github.com/a/b", confirm=True, registry=registry)

    def test_refuses_noop(self, registry, repo):
        with pytest.raises(RepairError, match="nothing to change"):
            change_github_url(repo, "https://github.com/o/old", confirm=True, registry=registry)


class TestEnableCollection:
    def test_enables_and_records_collection(self, registry, repo):
        pipeline = MagicMock()
        pipeline._ingest_collection.return_value = 42
        client = MagicMock()
        with patch("resource_explorer.github.client.GitHubClient", return_value=client), \
             patch("resource_explorer.ingestion.pipeline.IngestionPipeline", return_value=pipeline):
            result = enable_collection(repo, "pdfs", registry=registry)

        assert result["chunks_inserted"] == 42
        assert result["collection"] == "old_slug_pdfs"
        assert "old_slug_pdfs" in registry.get(repo).collections

    def test_refuses_zero_chunks(self, registry, repo):
        pipeline = MagicMock()
        pipeline._ingest_collection.return_value = 0
        with patch("resource_explorer.github.client.GitHubClient", return_value=MagicMock()), \
             patch("resource_explorer.ingestion.pipeline.IngestionPipeline", return_value=pipeline):
            with pytest.raises(RepairError, match="0 chunks"):
                enable_collection(repo, "pdfs", registry=registry)
        assert "old_slug_pdfs" not in registry.get(repo).collections

    def test_refuses_already_enabled(self, registry, repo):
        with pytest.raises(RepairError, match="already enabled"):
            enable_collection(repo, "python_code", registry=registry)

    def test_refuses_unknown_type(self, registry, repo):
        with pytest.raises(RepairError, match="unknown collection type"):
            enable_collection(repo, "not_a_real_type", registry=registry)


class TestInvestigationMembershipRepair:
    @pytest.fixture
    def two_investigations(self, registry, repo):
        a = registry.create_investigation("Investigation A")
        b = registry.create_investigation("Investigation B")
        ws = registry.get_or_create_working_set(a["slug"])
        registry.add_working_set_member(ws["slug"], "repo", repo, membership_rationale="scoped here first")
        return a["slug"], b["slug"]

    def test_list_memberships(self, registry, repo, two_investigations):
        a_slug, _ = two_investigations
        rows = list_repo_investigation_memberships(repo, registry=registry)
        assert [r["investigation_slug"] for r in rows] == [a_slug]

    def test_list_ignores_other_repos(self, registry, repo, two_investigations):
        registry.add(Project(slug="other", display_name="Other", github_url="https://github.com/o/other"))
        assert list_repo_investigation_memberships("other", registry=registry) == []

    def test_repoint_moves_membership(self, registry, repo, two_investigations):
        a_slug, b_slug = two_investigations
        repoint_investigation_member(repo, a_slug, b_slug, registry=registry)
        rows = list_repo_investigation_memberships(repo, registry=registry)
        assert [r["investigation_slug"] for r in rows] == [b_slug]

    def test_repoint_refuses_if_not_a_member(self, registry, repo, two_investigations):
        a_slug, b_slug = two_investigations
        with pytest.raises(RepairError, match="not currently a member"):
            repoint_investigation_member(repo, b_slug, a_slug, registry=registry)

    def test_drop_removes_membership(self, registry, repo, two_investigations):
        a_slug, _ = two_investigations
        drop_investigation_member(repo, a_slug, registry=registry)
        assert list_repo_investigation_memberships(repo, registry=registry) == []

    def test_drop_refuses_unknown_investigation(self, registry, repo):
        with pytest.raises(RepairError, match="not found"):
            drop_investigation_member(repo, "no-such-investigation", registry=registry)
