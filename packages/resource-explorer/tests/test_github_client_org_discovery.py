"""Tests for GitHubClient.list_org_repos() — GitHub-org auto-discovery."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from resource_explorer.github.client import GitHubClient


def _fake_repo(name, fork=False, archived=False, stars=5):
    r = MagicMock()
    r.full_name = f"my-org/{name}"
    r.html_url = f"https://github.com/my-org/{name}"
    r.description = f"{name} description"
    r.stargazers_count = stars
    r.language = "Python"
    r.fork = fork
    r.archived = archived
    r.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    return r


class TestListOrgRepos:
    def test_returns_lightweight_dicts_for_each_repo(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            org = MagicMock()
            org.get_repos.return_value = [_fake_repo("repo-a"), _fake_repo("repo-b")]
            MockGithub.return_value.get_organization.return_value = org

            client = GitHubClient()
            result = client.list_org_repos("my-org")

        assert len(result) == 2
        assert result[0]["full_name"] == "my-org/repo-a"
        assert result[0]["html_url"] == "https://github.com/my-org/repo-a"
        assert result[0]["stars"] == 5

    def test_excludes_forks_by_default(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            org = MagicMock()
            org.get_repos.return_value = [_fake_repo("real"), _fake_repo("forked", fork=True)]
            MockGithub.return_value.get_organization.return_value = org

            result = GitHubClient().list_org_repos("my-org")

        assert len(result) == 1
        assert result[0]["full_name"] == "my-org/real"

    def test_includes_forks_when_requested(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            org = MagicMock()
            org.get_repos.return_value = [_fake_repo("real"), _fake_repo("forked", fork=True)]
            MockGithub.return_value.get_organization.return_value = org

            result = GitHubClient().list_org_repos("my-org", include_forks=True)

        assert len(result) == 2

    def test_excludes_archived_by_default(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            org = MagicMock()
            org.get_repos.return_value = [_fake_repo("active"), _fake_repo("old", archived=True)]
            MockGithub.return_value.get_organization.return_value = org

            result = GitHubClient().list_org_repos("my-org")

        assert len(result) == 1
        assert result[0]["full_name"] == "my-org/active"

    def test_includes_archived_when_requested(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            org = MagicMock()
            org.get_repos.return_value = [_fake_repo("active"), _fake_repo("old", archived=True)]
            MockGithub.return_value.get_organization.return_value = org

            result = GitHubClient().list_org_repos("my-org", include_archived=True)

        assert len(result) == 2

    def test_empty_org_returns_empty_list(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            org = MagicMock()
            org.get_repos.return_value = []
            MockGithub.return_value.get_organization.return_value = org

            result = GitHubClient().list_org_repos("my-org")

        assert result == []

    def test_missing_description_and_language_default_to_empty_string(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            repo = _fake_repo("bare")
            repo.description = None
            repo.language = None
            org = MagicMock()
            org.get_repos.return_value = [repo]
            MockGithub.return_value.get_organization.return_value = org

            result = GitHubClient().list_org_repos("my-org")

        assert result[0]["description"] == ""
        assert result[0]["language"] == ""
