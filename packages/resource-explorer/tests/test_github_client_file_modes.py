"""Tests for GitHubClient.list_file_modes() — the Tier 1 "free" git mode
capture (Assessment sub-resource cataloging plan, D9). Mirrors list_files()'s
own truncation-handling shape but returns {path: mode} instead of [path]."""
from __future__ import annotations

from unittest.mock import MagicMock

from resource_explorer.github.client import GitHubClient


def _tree_entry(path, mode, entry_type="blob", sha=None, name=None):
    e = MagicMock()
    e.path = path
    e.mode = mode
    e.type = entry_type
    e.sha = sha or f"sha-{path}"
    e.name = name or path
    return e


def _client():
    c = GitHubClient.__new__(GitHubClient)
    return c


class TestListFileModes:
    def test_non_truncated_tree_returns_all_blob_modes(self):
        client = _client()
        repo = MagicMock()
        repo.default_branch = "main"
        tree = MagicMock(truncated=False)
        tree.tree = [
            _tree_entry("README.md", "100644"),
            _tree_entry("run.sh", "100755"),
            _tree_entry("link", "120000"),
            _tree_entry("src", "040000", entry_type="tree"),
        ]
        repo.get_git_tree.return_value = tree

        modes = client.list_file_modes(repo)

        assert modes == {"README.md": "100644", "run.sh": "100755", "link": "120000"}
        repo.get_git_tree.assert_called_once_with("main", recursive=True)

    def test_truncated_tree_walks_subtrees(self):
        client = _client()
        repo = MagicMock()
        repo.default_branch = "main"
        root_tree = MagicMock(truncated=True)
        root_tree.tree = [
            _tree_entry("top.py", "100644"),
            _tree_entry("sub", "040000", entry_type="tree", name="sub", sha="subsha"),
        ]
        sub_tree = MagicMock(truncated=False)
        sub_tree.tree = [_tree_entry("nested.py", "100644")]

        def fake_get_git_tree(ref, recursive=False):
            if ref == "main" and recursive:
                return root_tree
            if ref == "main" and not recursive:
                return root_tree
            if ref == "subsha":
                return sub_tree
            raise AssertionError(f"unexpected get_git_tree({ref!r}, recursive={recursive!r})")

        repo.get_git_tree.side_effect = fake_get_git_tree

        modes = client.list_file_modes(repo)

        assert modes == {"top.py": "100644", "sub/nested.py": "100644"}

    def test_failure_returns_empty_dict_not_raises(self):
        client = _client()
        repo = MagicMock()
        repo.get_git_tree.side_effect = Exception("rate limited")

        assert client.list_file_modes(repo) == {}
