"""Tests for resource_explorer.github.doc_locations — offline and hermetic
(no network). GitHubException/Github are mocked the same way
test_github_client_org_discovery.py mocks them.

Covers: tombstone detection (incl. "a real docs dir is not a tombstone"),
sibling-repo name matching, all four find_artifact() outcomes, and
graceful degradation when there's no token / the API errors."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from github import GithubException

from resource_explorer.github import doc_locations as dl


# ---------------------------------------------------------------------------
# Pure-function tests: tombstone detection
# ---------------------------------------------------------------------------

class TestIsTombstone:
    def test_gitignore_and_owners_only_is_a_tombstone(self):
        # the exact kubernetes/kubernetes/docs/ case, finding 68(b)
        assert dl._is_tombstone([".gitignore", "OWNERS"]) is True

    def test_empty_dir_is_a_tombstone(self):
        assert dl._is_tombstone([]) is True

    def test_readme_and_stub_only_is_a_tombstone(self):
        assert dl._is_tombstone(["README.md", ".gitignore", "OWNERS"]) is True

    def test_case_insensitive(self):
        assert dl._is_tombstone(["Owners", ".GITIGNORE"]) is True

    def test_real_docs_dir_is_not_a_tombstone(self):
        # milvus-io/milvus's docs/: README.md, design-docs/, agent_guides/, archive/
        assert dl._is_tombstone(
            ["README.md", "design-docs", "agent_guides", "archive"]
        ) is False

    def test_single_real_file_among_stubs_is_not_a_tombstone(self):
        assert dl._is_tombstone([".gitignore", "OWNERS", "internal_architecture.md"]) is False

    def test_five_year_stale_but_real_content_is_not_a_tombstone(self):
        # prometheus/prometheus's documentation/ — stale, but real prose, not stubs
        assert dl._is_tombstone(["README.md", "content", "images", "internal_architecture.md"]) is False


# ---------------------------------------------------------------------------
# Pure-function tests: sibling-repo name matching
# ---------------------------------------------------------------------------

class TestMatchSiblingNames:
    def test_matches_repo_dash_docs_suffix(self):
        matches = dl._match_sibling_names("milvus", ["milvus", "milvus-docs", "milvus-sdk-go"])
        assert "milvus-docs" in matches

    def test_matches_bare_docs_name(self):
        matches = dl._match_sibling_names("prometheus", ["prometheus", "docs", "alertmanager"])
        assert "docs" in matches

    def test_matches_bare_website_name(self):
        matches = dl._match_sibling_names("kubernetes", ["kubernetes", "website", "kubectl"])
        assert "website" in matches

    def test_matches_github_io_pages_repo(self):
        matches = dl._match_sibling_names("egeria", ["egeria", "egeria.github.io"])
        assert "egeria.github.io" in matches

    def test_never_matches_the_project_itself(self):
        matches = dl._match_sibling_names("egeria", ["egeria", "egeria-docs"])
        assert "egeria" not in matches

    def test_no_match_returns_empty(self):
        matches = dl._match_sibling_names("egeria-workspaces", ["egeria", "egeria-docs"])
        assert matches == {}

    def test_case_insensitive_match(self):
        matches = dl._match_sibling_names("kafka", ["Kafka-Docs"])
        assert "Kafka-Docs" in matches


# ---------------------------------------------------------------------------
# Pure-function tests: README off-site architecture links
# ---------------------------------------------------------------------------

class TestExtractOffsiteArchitectureLinks:
    def test_finds_offsite_architecture_link(self):
        readme = "See our [Architecture Overview](https://milvus.io/docs/architecture_overview.md)."
        links = dl._extract_offsite_architecture_links(readme, "milvus-io/milvus")
        assert len(links) == 1
        assert links[0].url == "https://milvus.io/docs/architecture_overview.md"

    def test_ignores_links_back_into_same_repo(self):
        readme = "See [architecture](https://github.com/milvus-io/milvus/blob/master/docs/README.md)."
        links = dl._extract_offsite_architecture_links(readme, "milvus-io/milvus")
        assert links == []

    def test_ignores_unrelated_offsite_links(self):
        readme = "Chat on [Slack](https://slack.com/invite/xyz)."
        links = dl._extract_offsite_architecture_links(readme, "milvus-io/milvus")
        assert links == []

    def test_no_links_returns_empty(self):
        assert dl._extract_offsite_architecture_links("plain text, no links", "o/r") == []


# ---------------------------------------------------------------------------
# Helpers for the mocked-Github tests
# ---------------------------------------------------------------------------

def _content_file(name, path=None, type_="file"):
    c = MagicMock()
    c.name = name
    c.path = path or name
    c.type = type_
    return c


def _fake_repo(full_name="owner/repo", homepage="", owner_login="owner", repo_name="repo"):
    r = MagicMock()
    r.full_name = full_name
    r.homepage = homepage
    r.owner.login = owner_login
    r.name = repo_name
    return r


def _with_siblings(gh, main_repo, siblings=None):
    """Route `gh.get_repo(full_name)` to the main repo or a named sibling.

    Sibling lookup PROBES enumerated names (`gh.get_repo("<owner>/<repo>-docs")`)
    rather than listing an organisation — listing paged ~2,700 repos on `apache`
    and made the step 3 repos per 10 minutes. These stubs previously fed
    `org.get_repos()`, which nothing calls any more; with `gh.get_repo` returning
    the main repo for every probe, every candidate name appeared to exist.
    """
    from github import GithubException
    table = {main_repo.full_name: main_repo}
    for r in (siblings or []):
        # A sibling must declare its owner: probing follows GitHub renames, and
        # a redirect can land on a different account entirely
        # (`prometheus/prometheus.github.io` -> `prometheus-junkyard/...`), so
        # the owner is checked. Mocks without one would be filtered out, which
        # would make these tests pass for the wrong reason.
        r.owner.login = r.full_name.split("/")[0]
        table[r.full_name] = r

    def _get(full_name, *a, **k):
        try:
            return table[full_name]
        except KeyError:
            raise GithubException(404, {"message": "Not Found"}, None)

    gh.get_repo.side_effect = _get
    return gh


def _fake_gh():
    return MagicMock()


# ---------------------------------------------------------------------------
# resolve_doc_locations() — integration-shaped, but fully mocked
# ---------------------------------------------------------------------------

class TestResolveDocLocations:
    def test_tombstone_in_repo_dir_is_reported_as_tombstone(self):
        gh = _fake_gh()
        repo = _fake_repo(full_name="kubernetes/kubernetes", repo_name="kubernetes",
                           owner_login="kubernetes")
        gh.get_repo.return_value = repo
        _with_siblings(gh, repo)

        def get_contents(path):
            if path == "docs":
                return [_content_file(".gitignore"), _content_file("OWNERS")]
            raise GithubException(404, data={"message": "Not Found"})

        repo.get_contents.side_effect = get_contents
        commit = MagicMock()
        commit.commit.committer.date = datetime(2022, 12, 1, tzinfo=UTC)
        repo.get_commits.return_value = [commit]
        repo.get_readme.side_effect = GithubException(404, data={"message": "Not Found"})

        org = MagicMock()
        website = MagicMock(name="website")
        website.name = "website"
        website.full_name = "kubernetes/website"
        website.pushed_at = datetime(2026, 8, 21, tzinfo=UTC)
        _with_siblings(gh, repo, [website])

        result = dl.resolve_doc_locations("kubernetes/kubernetes", client=gh)

        assert len(result.in_repo_dirs) == 1
        assert result.in_repo_dirs[0].path == "docs"
        assert result.in_repo_dirs[0].is_tombstone is True
        assert result.tombstoned_dirs == result.in_repo_dirs
        assert result.real_doc_dirs == []
        assert any(s.full_name == "kubernetes/website" for s in result.sibling_repos)

    def test_real_in_repo_dir_plus_sibling_both_reported(self):
        # prometheus/prometheus: both in-repo documentation/ (real) and sibling prometheus/docs
        gh = _fake_gh()
        repo = _fake_repo(full_name="prometheus/prometheus", repo_name="prometheus",
                           owner_login="prometheus", homepage="https://prometheus.io")
        gh.get_repo.return_value = repo
        _with_siblings(gh, repo)

        def get_contents(path):
            if path == "documentation":
                return [_content_file("README.md"), _content_file("content", type_="dir")]
            raise GithubException(404, data={"message": "Not Found"})

        repo.get_contents.side_effect = get_contents
        commit = MagicMock()
        commit.commit.committer.date = datetime(2021, 6, 1, tzinfo=UTC)
        repo.get_commits.return_value = [commit]
        repo.get_readme.side_effect = GithubException(404, data={"message": "Not Found"})

        org = MagicMock()
        docs_repo = MagicMock()
        docs_repo.name = "docs"
        docs_repo.full_name = "prometheus/docs"
        docs_repo.pushed_at = datetime(2026, 8, 20, tzinfo=UTC)
        _with_siblings(gh, repo, [docs_repo])

        result = dl.resolve_doc_locations("prometheus/prometheus", client=gh)

        assert len(result.real_doc_dirs) == 1
        assert result.real_doc_dirs[0].path == "documentation"
        assert result.homepage == "https://prometheus.io"
        assert any(s.full_name == "prometheus/docs" for s in result.sibling_repos)

    def test_no_in_repo_dir_sibling_and_homepage_reported(self):
        # odpi/egeria: sibling odpi/egeria-docs, homepage egeria-project.org, no in-repo dir
        gh = _fake_gh()
        repo = _fake_repo(full_name="odpi/egeria", repo_name="egeria", owner_login="odpi",
                           homepage="https://egeria-project.org")
        gh.get_repo.return_value = repo
        _with_siblings(gh, repo)
        repo.get_contents.side_effect = GithubException(404, data={"message": "Not Found"})
        repo.get_readme.side_effect = GithubException(404, data={"message": "Not Found"})

        org = MagicMock()
        docs_repo = MagicMock()
        docs_repo.name = "egeria-docs"
        docs_repo.full_name = "odpi/egeria-docs"
        docs_repo.pushed_at = datetime(2026, 8, 22, tzinfo=UTC)
        _with_siblings(gh, repo, [docs_repo])

        result = dl.resolve_doc_locations("odpi/egeria", client=gh)

        assert result.in_repo_dirs == []
        assert result.homepage == "https://egeria-project.org"
        assert [s.full_name for s in result.sibling_repos] == ["odpi/egeria-docs"]

    def test_no_token_or_network_failure_degrades_gracefully(self):
        gh = _fake_gh()
        gh.get_repo.side_effect = GithubException(403, data={"message": "rate limit exceeded"})

        result = dl.resolve_doc_locations("owner/repo", client=gh)

        assert result.in_repo_dirs == []
        assert result.sibling_repos == []
        assert result.homepage is None
        assert result.notes  # a clear note explaining the degraded result
        assert "owner/repo" in result.notes[0]

    def test_sibling_listing_failure_does_not_prevent_other_signals(self):
        gh = _fake_gh()
        repo = _fake_repo(full_name="owner/repo", homepage="https://example.com")
        gh.get_repo.return_value = repo
        _with_siblings(gh, repo)
        repo.get_contents.side_effect = GithubException(404, data={"message": "Not Found"})
        repo.get_readme.side_effect = GithubException(404, data={"message": "Not Found"})
        # Probing, not listing: a rate limit now surfaces on `get_repo` for the
        # candidate names rather than on `get_organization`, which is no longer
        # called. The main repo must still resolve — otherwise this would test
        # "everything fails", not "one signal fails". The property under test is
        # unchanged: one failed signal must not suppress the others.
        def _rate_limited(full_name, *a, **k):
            if full_name == repo.full_name:
                return repo
            raise GithubException(403, data={"message": "rate limit"})

        gh.get_repo.side_effect = _rate_limited
        gh.get_user.side_effect = GithubException(403, data={"message": "rate limit"})

        result = dl.resolve_doc_locations("owner/repo", client=gh)

        assert result.homepage == "https://example.com"
        assert result.sibling_repos == []
        assert result.notes  # sibling failure recorded


# ---------------------------------------------------------------------------
# find_artifact() — all four outcomes
# ---------------------------------------------------------------------------

class TestFindArtifact:
    def test_in_repo_outcome(self):
        gh = _fake_gh()
        repo = _fake_repo(full_name="prometheus/prometheus", repo_name="prometheus",
                           owner_login="prometheus")
        gh.get_repo.return_value = repo
        _with_siblings(gh, repo)

        def get_contents(path):
            if path == "documentation":
                return [_content_file("internal_architecture.md", "documentation/internal_architecture.md"),
                        _content_file("README.md", "documentation/README.md")]
            raise GithubException(404, data={"message": "Not Found"})

        repo.get_contents.side_effect = get_contents
        commit = MagicMock()
        commit.commit.committer.date = datetime(2021, 6, 1, tzinfo=UTC)
        repo.get_commits.return_value = [commit]
        repo.get_readme.side_effect = GithubException(404, data={"message": "Not Found"})
        gh.get_organization.side_effect = GithubException(404, data={"message": "Not Found"})
        gh.get_user.return_value.get_repos.return_value = []

        result = dl.find_artifact("prometheus/prometheus", "architecture", client=gh)

        assert result.outcome == "in-repo"
        assert result.evidence == "documentation/internal_architecture.md"
        assert result.date is not None

    def test_sibling_repo_outcome_when_in_repo_is_tombstoned(self):
        gh = _fake_gh()
        repo = _fake_repo(full_name="kubernetes/kubernetes", repo_name="kubernetes",
                           owner_login="kubernetes")
        gh.get_repo.side_effect = None

        def get_repo(name):
            if name == "kubernetes/kubernetes":
                return repo
            # owner_login matters: probing follows renames, and a redirect can
            # land on another account, so the owner is checked.
            website = _fake_repo(full_name="kubernetes/website", repo_name="website",
                                 owner_login="kubernetes")
            return website

        gh.get_repo.side_effect = get_repo

        def get_contents(path):
            if path == "docs":
                return [_content_file(".gitignore"), _content_file("OWNERS")]
            raise GithubException(404, data={"message": "Not Found"})

        repo.get_contents.side_effect = get_contents
        commit = MagicMock()
        commit.commit.committer.date = datetime(2022, 1, 1, tzinfo=UTC)
        repo.get_commits.return_value = [commit]
        repo.get_readme.side_effect = GithubException(404, data={"message": "Not Found"})

        org = MagicMock()
        website_repo = MagicMock()
        website_repo.name = "website"
        website_repo.full_name = "kubernetes/website"
        website_repo.pushed_at = datetime(2026, 8, 23, tzinfo=UTC)
        org.get_repos.return_value = [website_repo]
        gh.get_organization.return_value = org

        # sibling repo root search finds nothing specific either — still
        # sibling-repo, not not-found (finding 68's cautionary case)
        website_obj = get_repo("kubernetes/website")
        website_obj.get_contents.side_effect = GithubException(404, data={"message": "Not Found"})

        result = dl.find_artifact("kubernetes/kubernetes", "architecture", client=gh)

        assert result.outcome == "sibling-repo"
        assert "kubernetes/website" in result.evidence

    def test_doc_site_outcome_when_only_homepage_known(self):
        gh = _fake_gh()
        repo = _fake_repo(full_name="owner/repo", homepage="https://example.com/docs")
        gh.get_repo.return_value = repo
        _with_siblings(gh, repo)
        repo.get_contents.side_effect = GithubException(404, data={"message": "Not Found"})
        repo.get_readme.side_effect = GithubException(404, data={"message": "Not Found"})
        gh.get_organization.side_effect = GithubException(404, data={"message": "Not Found"})
        gh.get_user.return_value.get_repos.return_value = []

        result = dl.find_artifact("owner/repo", "architecture", client=gh)

        assert result.outcome == "doc-site"
        assert result.evidence == "https://example.com/docs"
        assert result.date is None

    def test_not_found_outcome_when_nothing_resolves(self):
        gh = _fake_gh()
        repo = _fake_repo(full_name="owner/repo", homepage="")
        gh.get_repo.return_value = repo
        _with_siblings(gh, repo)
        repo.get_contents.side_effect = GithubException(404, data={"message": "Not Found"})
        repo.get_readme.side_effect = GithubException(404, data={"message": "Not Found"})
        gh.get_organization.side_effect = GithubException(404, data={"message": "Not Found"})
        gh.get_user.return_value.get_repos.return_value = []

        result = dl.find_artifact("owner/repo", "architecture", client=gh)

        assert result.outcome == "not-found"
        assert result.evidence == ""

    def test_not_found_when_repo_itself_unreachable(self):
        gh = _fake_gh()
        gh.get_repo.side_effect = GithubException(401, data={"message": "Bad credentials"})

        result = dl.find_artifact("owner/repo", "architecture", client=gh)

        assert result.outcome == "not-found"
        assert result.note
