"""Tests for GitHubClient.search_repos() — general repo search
("Discover repos to scout" plan, D3), which replaced the old org-only
list_org_repos()."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from resource_explorer.github.client import GitHubClient


def _fake_repo(name, fork=False, archived=False, stars=5, forks=1, license_id="mit"):
    r = MagicMock()
    r.full_name = f"my-org/{name}"
    r.html_url = f"https://github.com/my-org/{name}"
    r.description = f"{name} description"
    r.stargazers_count = stars
    r.forks_count = forks
    r.language = "Python"
    r.fork = fork
    r.archived = archived
    r.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    if license_id:
        r.license = MagicMock(spdx_id=license_id)
    else:
        r.license = None
    return r


class TestSearchRepos:
    def test_returns_lightweight_dicts_for_each_repo(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            MockGithub.return_value.search_repositories.return_value = [
                _fake_repo("repo-a"), _fake_repo("repo-b"),
            ]

            client = GitHubClient()
            result = client.search_repos("org:my-org")

        assert len(result) == 2
        assert result[0]["full_name"] == "my-org/repo-a"
        assert result[0]["html_url"] == "https://github.com/my-org/repo-a"
        assert result[0]["stars"] == 5
        assert result[0]["license"] == "mit"
        assert result[0]["forks"] == 1

    def test_respects_limit(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            MockGithub.return_value.search_repositories.return_value = [
                _fake_repo(f"repo-{i}") for i in range(10)
            ]

            result = GitHubClient().search_repos("stars:>100", limit=3)

        assert len(result) == 3

    def test_empty_result_returns_empty_list(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            MockGithub.return_value.search_repositories.return_value = []

            result = GitHubClient().search_repos("org:my-org")

        assert result == []

    def test_missing_description_language_license_default_sensibly(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            repo = _fake_repo("bare", license_id=None)
            repo.description = None
            repo.language = None
            MockGithub.return_value.search_repositories.return_value = [repo]

            result = GitHubClient().search_repos("org:my-org")

        assert result[0]["description"] == ""
        assert result[0]["language"] == ""
        assert result[0]["license"] == ""

    def test_passes_sort_and_order_through(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            MockGithub.return_value.search_repositories.return_value = []

            GitHubClient().search_repos("stars:>100", sort="forks", order="asc")

        MockGithub.return_value.search_repositories.assert_called_once_with(
            query="stars:>100", sort="forks", order="asc",
        )


class TestBaseUrl:
    def test_defaults_to_config_base_url(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            GitHubClient()

        _, kwargs = MockGithub.call_args
        assert kwargs["base_url"] == "https://api.github.com"

    def test_explicit_base_url_overrides_config(self):
        with patch("resource_explorer.github.client.Github") as MockGithub:
            GitHubClient(base_url="https://ghe.example.com/api/v3")

        _, kwargs = MockGithub.call_args
        assert kwargs["base_url"] == "https://ghe.example.com/api/v3"
