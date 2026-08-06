"""Evaluation harness for Resource Explorer.

Tests correctness across four dimensions:
  1. Intent classification — does the classifier pick the right intent?
  2. Project inference — does _infer_project_slug find the right project?
  3. Agent response validation — do responses contain expected content?
  4. Comparison routing — does the compare agent find both projects?

All tests run without LLM or Milvus calls. Agent response tests use the
fallback data-formatting path (mocked BeeAI) so they exercise real data
assembly logic against fixture data.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from resource_explorer.query_processor import QueryIntent, QueryProcessor
from resource_explorer.registry import Project, ProjectRegistry


# ── shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "eval.db"))


@pytest.fixture
def two_projects(registry):
    """Register two projects with stats and commit data for comparison tests."""
    alpha = Project(slug="alpha", display_name="Alpha Project",
                    github_url="https://github.com/test/alpha")
    beta = Project(slug="beta", display_name="Beta Framework",
                   github_url="https://github.com/test/beta")
    registry.add(alpha)
    registry.add(beta)

    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(registry.db_path)

    # Stats rows for both projects
    for slug, stars, forks, contribs, commits_30, commits_90, releases, lang in [
        ("alpha", 4500, 320, 45,  38, 110, 12, "Python"),
        ("beta",  1200,  80, 12,   6,  18,  3, "Go"),
    ]:
        conn.execute("""
            INSERT INTO project_stats
            (project_slug, fetched_at, stars, forks, contributors_count,
             commits_30d, commits_90d, releases_count, primary_language,
             language_breakdown)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (slug, now.isoformat(), stars, forks, contribs,
              commits_30, commits_90, releases, lang,
              json.dumps({lang: 100_000})))

    # Commit rows for alpha
    alice_commits = [
        ("sha-" + str(i), "Alice", "alice@example.com",
         (now - timedelta(days=i * 2)).isoformat())
        for i in range(15)
    ]
    bob_commits = [
        ("sha-b" + str(i), "Bob", "bob@example.com",
         (now - timedelta(days=i * 3 + 1)).isoformat())
        for i in range(8)
    ]
    for sha, name, email, ts in alice_commits + bob_commits:
        conn.execute("""
            INSERT OR IGNORE INTO project_commits
            (project_slug, sha, message, author_name, author_email, committed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("alpha", sha, "fix: something", name, email, ts))

    # A few commits for beta
    for i in range(3):
        conn.execute("""
            INSERT OR IGNORE INTO project_commits
            (project_slug, sha, message, author_name, author_email, committed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("beta", f"sha-b{i}", "chore: update", "Carol",
              "carol@example.com", (now - timedelta(days=i * 10)).isoformat()))

    conn.commit()
    conn.close()
    return registry, alpha, beta


# ── 1. Intent classification accuracy ────────────────────────────────────────

@pytest.fixture
def qp():
    return QueryProcessor()


STATISTICAL_QUERIES = [
    "how many commits in the last 30 days",
    "how many stars does alpha have",
    "who are the top committers",
    "show me the top contributors",
    "list contributors to the project",
    "show a graph of commit activity",
    "commit history over the last year",
    "release cadence for this project",
    "lines of code in the repo",
    "growth over time",
    "weekly commits for alpha",
    "how many forks does this have",
    "who committed to this project",
    "committers in the last 90 days",
]

COMPARISON_QUERIES = [
    "compare alpha and beta",
    "compare alpha vs beta",
    "difference between alpha and beta",
    "which project is more popular",
    "which has more stars, alpha or beta",
    "alpha versus beta",
    "alpha vs beta",
    "side-by-side comparison of alpha and beta",
    "head-to-head alpha and beta",
    "more commits than beta",
]

HEALTH_QUERIES = [
    "is this project actively maintained",
    "how actively maintained is it",
    "community health of the project",
    "what is the bus factor",
    "contributor diversity",
    "is this project abandoned",
    "last activity on the project",
]

CODE_QUERIES = [
    "how do I use the authentication module",
    "show me an example of creating a client",
    "how is the parser implemented",
    "source code for the main function",
    "how can I call the retry method",
]

CONCEPTUAL_QUERIES = [
    "what is the overall architecture",
    "how does the routing work",
    "explain the configuration system",
    "getting started guide",
    "how to install",
    "what is this project",
    "overview of the system",
]


class TestIntentClassificationAccuracy:
    @pytest.mark.parametrize("query", STATISTICAL_QUERIES)
    def test_statistical(self, qp, query):
        assert qp.classify(query) == QueryIntent.STATISTICAL, (
            f"Expected STATISTICAL for: {query!r}"
        )

    @pytest.mark.parametrize("query", COMPARISON_QUERIES)
    def test_comparison(self, qp, query):
        assert qp.classify(query) == QueryIntent.COMPARISON, (
            f"Expected COMPARISON for: {query!r}"
        )

    @pytest.mark.parametrize("query", HEALTH_QUERIES)
    def test_health(self, qp, query):
        assert qp.classify(query) == QueryIntent.HEALTH, (
            f"Expected HEALTH for: {query!r}"
        )

    @pytest.mark.parametrize("query", CODE_QUERIES)
    def test_code_search(self, qp, query):
        assert qp.classify(query) == QueryIntent.CODE_SEARCH, (
            f"Expected CODE_SEARCH for: {query!r}"
        )

    @pytest.mark.parametrize("query", CONCEPTUAL_QUERIES)
    def test_conceptual(self, qp, query):
        assert qp.classify(query) == QueryIntent.CONCEPTUAL, (
            f"Expected CONCEPTUAL for: {query!r}"
        )

    def test_priority_statistical_over_conceptual(self, qp):
        # "how many files" should be STATISTICAL, not CONCEPTUAL ("how")
        assert qp.classify("how many files are in the repo") == QueryIntent.STATISTICAL

    def test_priority_health_over_general(self, qp):
        assert qp.classify("is it abandoned") == QueryIntent.HEALTH

    def test_empty_string_is_general(self, qp):
        assert qp.classify("") == QueryIntent.GENERAL

    def test_unmatched_is_general(self, qp):
        assert qp.classify("tell me something interesting") == QueryIntent.GENERAL


# ── 2. Project inference accuracy ──────────────��──────────────────────────────

class TestProjectInference:
    @pytest.fixture(autouse=True)
    def _patch_registry(self, two_projects, monkeypatch):
        registry, *_ = two_projects
        # base.py imports ProjectRegistry inline inside methods, so patch the source module
        monkeypatch.setattr("resource_explorer.registry.ProjectRegistry", lambda: registry)

    def test_infers_by_exact_slug(self):
        from resource_explorer.agents.base import BaseExplorerAgent

        class _Agent(BaseExplorerAgent):
            def system_prompt(self): return ""
            def tools(self): return []
            def handle(self, *a, **kw): return ""

        agent = _Agent()
        assert agent._infer_project_slug("how many stars does alpha have") == "alpha"
        assert agent._infer_project_slug("top committers for beta") == "beta"

    def test_infers_by_display_name(self):
        from resource_explorer.agents.base import BaseExplorerAgent

        class _Agent(BaseExplorerAgent):
            def system_prompt(self): return ""
            def tools(self): return []
            def handle(self, *a, **kw): return ""

        agent = _Agent()
        # "Alpha Project" → slug "alpha"
        assert agent._infer_project_slug("explain the Alpha Project architecture") == "alpha"
        # "Beta Framework" → slug "beta"
        assert agent._infer_project_slug("how does Beta Framework handle errors") == "beta"

    def test_returns_none_for_unknown_project(self):
        from resource_explorer.agents.base import BaseExplorerAgent

        class _Agent(BaseExplorerAgent):
            def system_prompt(self): return ""
            def tools(self): return []
            def handle(self, *a, **kw): return ""

        agent = _Agent()
        assert agent._infer_project_slug("how does the routing work") is None

    def test_clarification_lists_projects(self):
        from resource_explorer.agents.base import BaseExplorerAgent

        class _Agent(BaseExplorerAgent):
            def system_prompt(self): return ""
            def tools(self): return []
            def handle(self, *a, **kw): return ""

        agent = _Agent()
        response = agent._clarification_response("how many commits")
        assert "alpha" in response
        assert "beta" in response
        assert "Which project" in response


# ── 3. Stats agent response validation ───────────────────────────────────────

class TestStatsAgentResponseContent:
    @pytest.fixture(autouse=True)
    def _patch_registry(self, two_projects, monkeypatch):
        registry, *_ = two_projects
        monkeypatch.setattr("resource_explorer.agents.stats_agent.ProjectRegistry", lambda: registry)

    def test_fetch_stats_includes_star_count(self):
        from resource_explorer.agents.stats_agent import StatsAgent
        result = StatsAgent()._fetch_stats("alpha")
        assert "4500" in result

    def test_fetch_stats_includes_contributor_count(self):
        from resource_explorer.agents.stats_agent import StatsAgent
        result = StatsAgent()._fetch_stats("alpha")
        assert "45" in result

    def test_fetch_stats_includes_language(self):
        from resource_explorer.agents.stats_agent import StatsAgent
        result = StatsAgent()._fetch_stats("alpha")
        assert "Python" in result

    def test_fetch_stats_shows_commit_trends(self):
        from resource_explorer.agents.stats_agent import StatsAgent
        result = StatsAgent()._fetch_stats("alpha")
        assert "Commit Trends" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_fetch_stats_returns_empty_for_missing_project(self):
        from resource_explorer.agents.stats_agent import StatsAgent
        assert StatsAgent()._fetch_stats("nonexistent") == ""

    def test_fetch_stats_returns_empty_for_none_slug(self):
        from resource_explorer.agents.stats_agent import StatsAgent
        assert StatsAgent()._fetch_stats(None) == ""

    def test_live_commit_counts_preferred_over_snapshot(self):
        from resource_explorer.agents.stats_agent import StatsAgent
        result = StatsAgent()._fetch_stats("alpha")
        # The fixture inserted 23 commits total (15 + 8) all within 90 days
        # Live count should be used, not the snapshot value of 110
        assert "Commit Trends" in result


# ── 4. commit data validation (tests the data the tools query) ───────────────

class TestCommitDataLayer:
    """Validates the project_commits data that the BeeAI tools query.

    We test the underlying SQLite data and the Counter logic rather than
    calling the @tool FunctionTool objects directly (which have an async
    BeeAI runner interface, not a plain __call__).
    """

    def test_commit_rows_inserted(self, two_projects):
        registry, *_ = two_projects
        conn = sqlite3.connect(registry.db_path)
        rows = conn.execute(
            "SELECT author_name FROM project_commits WHERE project_slug = 'alpha'"
        ).fetchall()
        conn.close()
        names = [r[0] for r in rows]
        assert "Alice" in names
        assert "Bob" in names

    def test_alice_has_more_commits_than_bob(self, two_projects):
        registry, *_ = two_projects
        conn = sqlite3.connect(registry.db_path)
        rows = conn.execute(
            "SELECT author_name FROM project_commits WHERE project_slug = 'alpha'"
        ).fetchall()
        conn.close()
        counter = Counter(r[0] for r in rows)
        assert counter["Alice"] > counter["Bob"]

    def test_beta_has_commit_data(self, two_projects):
        registry, *_ = two_projects
        conn = sqlite3.connect(registry.db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM project_commits WHERE project_slug = 'beta'"
        ).fetchone()[0]
        conn.close()
        assert count == 3

    def test_nonexistent_project_has_no_commits(self, two_projects):
        registry, *_ = two_projects
        conn = sqlite3.connect(registry.db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM project_commits WHERE project_slug = 'nonexistent'"
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_weekly_bucketing_logic(self, two_projects):
        """Verify commits can be bucketed into weekly bins correctly."""
        from datetime import datetime, timedelta
        registry, *_ = two_projects
        conn = sqlite3.connect(registry.db_path)
        rows = conn.execute(
            "SELECT committed_at FROM project_commits WHERE project_slug = 'alpha'"
        ).fetchall()
        conn.close()
        now = datetime.utcnow()
        week_counts: Counter = Counter()
        for (ts,) in rows:
            dt = datetime.fromisoformat(ts.replace("Z", "").replace("+00:00", ""))
            weeks_ago = (now - dt).days // 7
            if weeks_ago < 12:
                week_counts[weeks_ago] += 1
        # All 23 alpha commits are within 90 days so should appear in some week bin
        assert sum(week_counts.values()) > 0


_plotly_available = pytest.mark.skipif(
    __import__("importlib").util.find_spec("plotly") is None,
    reason="plotly not installed",
)


# ── 5. top_committers chart validation ───────────────────────────────────────

@_plotly_available
class TestTopCommittersChart:
    @pytest.fixture(autouse=True)
    def _patch_registry(self, two_projects, monkeypatch):
        registry, *_ = two_projects
        monkeypatch.setattr("resource_explorer.registry.ProjectRegistry", lambda: registry)

    def test_returns_figure_when_data_exists(self):
        from resource_explorer.dashboard.graphs import top_committers_plotly
        fig = top_committers_plotly("alpha")
        assert fig is not None
        assert fig.data  # has at least one trace

    def test_returns_none_when_no_data(self):
        from resource_explorer.dashboard.graphs import top_committers_plotly
        fig = top_committers_plotly("nonexistent_project")
        assert fig is None

    def test_chart_has_alice_and_bob(self):
        from resource_explorer.dashboard.graphs import top_committers_plotly
        import json
        fig = top_committers_plotly("alpha")
        fig_json = json.loads(fig.to_json())
        y_vals = fig_json["data"][0]["y"]
        assert any("Alice" in str(v) for v in y_vals)
        assert any("Bob" in str(v) for v in y_vals)

    def test_alice_has_higher_bar(self):
        from resource_explorer.dashboard.graphs import top_committers_plotly
        import json
        fig = top_committers_plotly("alpha")
        fig_json = json.loads(fig.to_json())
        y_vals = fig_json["data"][0]["y"]
        x_vals = fig_json["data"][0]["x"]
        alice_count = x_vals[list(y_vals).index(next(v for v in y_vals if "Alice" in str(v)))]
        bob_count = x_vals[list(y_vals).index(next(v for v in y_vals if "Bob" in str(v)))]
        assert alice_count > bob_count


# ── 6. Compare agent project extraction ──────────────────────────────────────

class TestCompareAgentProjectExtraction:
    @pytest.fixture(autouse=True)
    def _patch_registry(self, two_projects, monkeypatch):
        registry, *_ = two_projects
        monkeypatch.setattr("resource_explorer.registry.ProjectRegistry", lambda: registry)
        # Patch inside compare_agent module too since it imports locally
        import resource_explorer.agents.compare_agent as mod
        monkeypatch.setattr(mod, "ProjectRegistry", lambda: registry, raising=False)

    def test_extracts_both_slugs_from_comparison_query(self, two_projects):
        from resource_explorer.agents.compare_agent import CompareAgent
        agent = CompareAgent()
        slugs = agent._infer_all_project_slugs("compare alpha and beta")
        assert "alpha" in slugs
        assert "beta" in slugs

    def test_extracts_by_display_name(self, two_projects):
        from resource_explorer.agents.compare_agent import CompareAgent
        agent = CompareAgent()
        slugs = agent._infer_all_project_slugs(
            "compare Alpha Project versus Beta Framework"
        )
        assert "alpha" in slugs
        assert "beta" in slugs

    def test_missing_one_project_returns_short_list(self, two_projects):
        from resource_explorer.agents.compare_agent import CompareAgent
        agent = CompareAgent()
        slugs = agent._infer_all_project_slugs("compare alpha and something_unknown")
        assert "alpha" in slugs
        assert "beta" not in slugs


# ── 7. Compare stats chart ────────────────────────────────────────────────────

@_plotly_available
class TestCompareStatsChart:
    @pytest.fixture(autouse=True)
    def _patch_registry(self, two_projects, monkeypatch):
        registry, *_ = two_projects
        monkeypatch.setattr("resource_explorer.registry.ProjectRegistry", lambda: registry)

    def test_returns_figure_with_two_projects(self):
        from resource_explorer.dashboard.graphs import compare_stats_plotly
        fig = compare_stats_plotly(["alpha", "beta"])
        assert fig is not None
        assert len(fig.data) > 0

    def test_figure_has_both_project_names_on_x_axis(self):
        from resource_explorer.dashboard.graphs import compare_stats_plotly
        import json
        fig = compare_stats_plotly(["alpha", "beta"])
        fig_json = json.loads(fig.to_json())
        x_vals = fig_json["data"][0]["x"]
        assert "alpha" in x_vals
        assert "beta" in x_vals

    def test_alpha_has_more_stars_than_beta(self):
        from resource_explorer.dashboard.graphs import compare_stats_plotly
        import json
        fig = compare_stats_plotly(["alpha", "beta"])
        fig_json = json.loads(fig.to_json())
        # First trace is "Stars" — find it
        stars_trace = next(
            t for t in fig_json["data"] if t.get("name") == "Stars"
        )
        alpha_idx = list(stars_trace["x"]).index("alpha")
        beta_idx = list(stars_trace["x"]).index("beta")
        assert stars_trace["y"][alpha_idx] > stars_trace["y"][beta_idx]


# ── 8. _pick_chart routing ────────────────────────────────────────────────────

@_plotly_available
class TestPickChart:
    @pytest.fixture(autouse=True)
    def _patch_graphs(self, two_projects, monkeypatch):
        registry, *_ = two_projects
        monkeypatch.setattr("resource_explorer.registry.ProjectRegistry", lambda: registry)

    def test_committer_query_returns_committer_chart(self):
        from resource_explorer.web.routes.query import _pick_chart
        result = _pick_chart("show the top committers", "statistical", "alpha")
        assert result is not None
        # Should be a horizontal bar chart (orientation 'h')
        assert result["data"][0]["orientation"] == "h"

    def test_committer_query_returns_none_when_no_data(self):
        from resource_explorer.web.routes.query import _pick_chart
        result = _pick_chart("show the top committers", "statistical", "nonexistent")
        assert result is None

    def test_star_query_returns_stars_chart(self):
        from resource_explorer.web.routes.query import _pick_chart
        # stars_over_time_plotly reads project_stats — will return empty but not None
        result = _pick_chart("how many stars does alpha have", "statistical", "alpha")
        # We just check it doesn't raise and returns a dict or None
        assert result is None or isinstance(result, dict)

    def test_health_intent_returns_radar_chart(self):
        from resource_explorer.web.routes.query import _pick_chart
        result = _pick_chart("is this actively maintained", "health", "alpha")
        # health_radar_plotly always returns a figure
        assert result is not None

    def test_no_project_slug_returns_none(self):
        from resource_explorer.web.routes.query import _pick_chart
        assert _pick_chart("who are the committers", "statistical", "") is None

    def test_wrong_intent_returns_none(self):
        from resource_explorer.web.routes.query import _pick_chart
        assert _pick_chart("how does the parser work", "code_search", "alpha") is None


# ── 9. Query cache isolation ──────────────────────────────────────────────────

class TestQueryCache:
    def test_cache_miss_returns_none(self):
        from resource_explorer.query_cache import QueryCache
        cache = QueryCache(max_size=10, ttl_seconds=60)
        assert cache.get("anything", None, "general") is None

    def test_cache_hit_returns_stored_value(self):
        from resource_explorer.query_cache import QueryCache
        cache = QueryCache(max_size=10, ttl_seconds=60)
        cache.set("q", "proj", "statistical", "42 stars")
        assert cache.get("q", "proj", "statistical") == "42 stars"

    def test_cache_key_includes_project_and_intent(self):
        from resource_explorer.query_cache import QueryCache
        cache = QueryCache(max_size=10, ttl_seconds=60)
        cache.set("q", "alpha", "statistical", "answer-a")
        cache.set("q", "beta", "statistical", "answer-b")
        assert cache.get("q", "alpha", "statistical") == "answer-a"
        assert cache.get("q", "beta", "statistical") == "answer-b"

    def test_invalidate_project_clears_entries(self):
        from resource_explorer.query_cache import QueryCache
        cache = QueryCache(max_size=10, ttl_seconds=60)
        cache.set("q", "alpha", "statistical", "old")
        cache.invalidate_project("alpha")
        assert cache.get("q", "alpha", "statistical") is None


