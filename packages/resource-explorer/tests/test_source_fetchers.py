"""Tests for github/source_fetchers.py — the fetch_kind registry backing
'list'-type discovery sources' optional auto-refresh."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from resource_explorer.github.source_fetchers import FETCHERS, fetch_source_urls

_LANDSCAPE_YAML = """
landscape:
  - subcategories:
      - items:
          - repo_url: https://github.com/cncf/foo
          - repo_url: https://github.com/cncf/bar/
          - homepage_url: https://example.com/no-repo
          - repo_url: https://gitlab.com/cncf/not-github
"""

_ECLIPSE_JSON_LIST = [
    {"github_repos": [{"url": "https://github.com/eclipse/one"}]},
    {"source_repo": [{"url": "https://github.com/eclipse/two/"}]},
    {"github_repos": []},
]


class TestCncfLandscapeFetcher:
    def test_parses_repo_urls_dedupes_and_sorts(self):
        resp = MagicMock(text=_LANDSCAPE_YAML)
        resp.raise_for_status.return_value = None
        with patch("httpx.get", return_value=resp) as mock_get:
            urls = fetch_source_urls("cncf_landscape")
        assert urls == ["https://github.com/cncf/bar", "https://github.com/cncf/foo"]
        assert "landscape/master/landscape.yml" in mock_get.call_args[0][0]

    def test_custom_fetch_url_overrides_default(self):
        resp = MagicMock(text=_LANDSCAPE_YAML)
        resp.raise_for_status.return_value = None
        with patch("httpx.get", return_value=resp) as mock_get:
            fetch_source_urls("cncf_landscape", "https://example.com/mirror.yml")
        assert mock_get.call_args[0][0] == "https://example.com/mirror.yml"

    def test_http_error_propagates(self):
        with patch("httpx.get", side_effect=httpx.HTTPStatusError("boom", request=MagicMock(), response=MagicMock())):
            with pytest.raises(httpx.HTTPStatusError):
                fetch_source_urls("cncf_landscape")


class TestLfaiLandscapeFetcher:
    """LF AI & Data's own landscape.yml — same landscape2 tool/schema as
    CNCF's (confirmed live against github.com/lfai/lfai-landscape: 367 repo
    URLs, includes odpi/egeria) — the real fix for the exact gap
    foundation_prefilters.json flagged and left unsolved (lfai's own GitHub
    org holds governance repos, not member project code, so a search-based
    org: qualifier was always going to be wrong for this foundation)."""

    def test_parses_repo_urls_via_shared_landscape2_parser(self):
        resp = MagicMock(text=_LANDSCAPE_YAML)
        resp.raise_for_status.return_value = None
        with patch("httpx.get", return_value=resp) as mock_get:
            urls = fetch_source_urls("lfai_landscape")
        assert urls == ["https://github.com/cncf/bar", "https://github.com/cncf/foo"]
        assert "lfai-landscape/main/landscape.yml" in mock_get.call_args[0][0]

    def test_custom_fetch_url_overrides_default(self):
        resp = MagicMock(text=_LANDSCAPE_YAML)
        resp.raise_for_status.return_value = None
        with patch("httpx.get", return_value=resp) as mock_get:
            fetch_source_urls("lfai_landscape", "https://example.com/mirror.yml")
        assert mock_get.call_args[0][0] == "https://example.com/mirror.yml"


class TestEclipseProjectsFetcher:
    def test_parses_github_repos_and_source_repo_shapes(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = _ECLIPSE_JSON_LIST
        with patch("httpx.get", return_value=resp):
            urls = fetch_source_urls("eclipse_projects")
        assert urls == ["https://github.com/eclipse/one", "https://github.com/eclipse/two"]

    def test_handles_dict_of_projects_shape(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"projects": {"p1": {"github_repos": [{"url": "https://github.com/eclipse/x"}]}}}
        with patch("httpx.get", return_value=resp):
            urls = fetch_source_urls("eclipse_projects")
        assert urls == ["https://github.com/eclipse/x"]


class TestLfxInsightsFetcher:
    def test_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            fetch_source_urls("lfx_insights")


class TestUnknownFetchKind:
    def test_raises_value_error(self):
        with pytest.raises(ValueError):
            fetch_source_urls("not-a-real-kind")


def test_all_registered_fetchers_are_callable():
    assert set(FETCHERS) == {"cncf_landscape", "lfai_landscape", "eclipse_projects", "lfx_insights"}
    for fn in FETCHERS.values():
        assert callable(fn)
