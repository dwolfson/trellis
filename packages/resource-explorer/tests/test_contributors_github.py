"""Contributors: top 10 over 12 months and all time, from the GitHub API (BRIEF-CONTRIBUTORS-GITHUB.md).

Every GitHub call is faked: `GitHubClient` is autospec'd (spec_set) and `rest_get` answers `(headers, json)` in the
shapes GitHub's REST docs give for `GET /repos/{o}/{r}/commits` (each item: sha, commit.author {name, email, date},
author {login, type} or null, committer {login, type} or null) and `GET /repos/{o}/{r}/contributors?anon=1` (User/Bot
rows: login, type, contributions; Anonymous rows: name, email, type, contributions). Refusals are the real
`github.GithubException(status, data, headers)`. No test reaches GitHub, Egeria or a shared database.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import create_autospec, patch

import pytest
from github import GithubException

from resource_explorer import contributors as C
from resource_explorer.github.client import GitHubClient
from resource_explorer.registry import PROJECT_CONTRIBUTORS_DDL, Project, ProjectRegistry

NOW = datetime(2026, 10, 23, 12, 0, 0)
FULL = "acme/widget"
RATE = {"remaining": 5000, "limit": 5000, "reset_at": "2026-10-23T13:00:00"}


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "reg.db"))
    reg.add(Project(slug="widget", display_name="Widget", github_url=f"https://github.com/{FULL}", description=""))
    return reg


def _commit(i: int, name: str, login: str | None, kind: str = "User", days_ago: float = 1.0) -> dict:
    when = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"sha": f"{i:040x}",
            "commit": {"author": {"name": name, "email": f"{name.lower().replace(' ', '.')}@example.org",
                                  "date": when},
                       "committer": {"name": "GitHub", "email": "noreply@github.com", "date": when},
                       "message": f"change {i}"},
            "author": {"login": login, "id": abs(hash(login)) % 10_000, "type": kind} if login else None,
            "committer": {"login": "web-flow", "id": 19864447, "type": "User"}}


def _user(login: str, n: int, kind: str = "User") -> dict:
    return {"login": login, "id": abs(hash(login)) % 10_000, "type": kind, "site_admin": False, "contributions": n}


def _anon(name: str, n: int) -> dict:
    return {"email": f"{name.lower()}@example.org", "name": name, "type": "Anonymous", "contributions": n}


def _client(commits: list[dict], contributors: list[dict], *, rate=RATE, refuse: str = "") -> GitHubClient:
    """An autospec'd client paging `commits` and `contributors` by `page`/`per_page`, counting calls."""
    client = create_autospec(GitHubClient, instance=True, spec_set=True)
    client.check_rate_limit.return_value = rate

    def rest_get(path, params=None):
        params = params or {}
        if refuse and path.endswith(refuse):
            raise GithubException(403, {"message": "API rate limit exceeded"},
                                  {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1761224400"})
        items = commits if path.endswith("/commits") else contributors
        page, per = int(params.get("page", 1)), int(params.get("per_page", 30))
        return {"x-ratelimit-remaining": "4999"}, items[(page - 1) * per: page * per]

    client.rest_get.side_effect = rest_get
    return client


#: The end-to-end fixture: 230 commits by 7 authors, 2 of them bots.
SPEC_12 = [("Alice Ng", "alice", "User", 100), ("Bob Ruiz", "bob", "User", 50), ("Carol Ode", "carol", "User", 30),
           ("Dave Iyer", None, "User", 20), ("Erin Holt", "erin", "User", 10),
           ("dependabot[bot]", "dependabot[bot]", "Bot", 15), ("github-actions[bot]", "github-actions[bot]", "Bot", 5)]
ALL_TIME = [_user("alice", 400), _user("bob", 300), _user("dependabot[bot]", 100, "Bot"), _user("carol", 100),
            _user("erin", 30), _user("github-actions[bot]", 20, "Bot"), _anon("Dave Iyer", 50)]


def _commits_230() -> list[dict]:
    out, i = [], 0
    for name, login, kind, n in SPEC_12:
        for _ in range(n):
            out.append(_commit(i, name, login, kind, days_ago=1 + i * 0.5))
            i += 1
    out.sort(key=lambda c: c["commit"]["author"]["date"], reverse=True)   # GitHub answers newest first
    return out


# ── the DDL: the owner's go was for this one table, additive and idempotent ─────────────────────────────────────────

def test_the_ddl_is_one_additive_idempotent_create_table_that_survives_the_postgres_translator():
    from resource_explorer.registry import PostgresCursorWrapper

    assert len(PROJECT_CONTRIBUTORS_DDL) == 1
    stmt = PROJECT_CONTRIBUTORS_DDL[0]
    assert stmt.lstrip().upper().startswith("CREATE TABLE IF NOT EXISTS PROJECT_CONTRIBUTORS")
    assert not re.search(r"\b(ALTER|DROP|INSERT|UPDATE|DELETE)\b", stmt.upper())
    assert "?" not in stmt and not re.search(r"(?<!:):[A-Za-z_]", stmt)
    out = PostgresCursorWrapper(None)._translate_sql(stmt)
    assert "SERIAL PRIMARY KEY" in out and "AUTOINCREMENT" not in out and "%" not in out
    # WINDOW is reserved in Postgres: the column is list_window.
    assert not re.search(r"^\s*window\s", stmt, re.MULTILINE)


def test_the_table_is_created_on_a_fresh_registry_and_a_reopen_is_idempotent(tmp_path):
    path = str(tmp_path / "ddl.db")
    ProjectRegistry(db_path=path)
    ProjectRegistry(db_path=path)
    cols = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(project_contributors)")]
    assert cols == ["id", "project_slug", "list_window", "rank", "login", "display_name", "author_email", "commits",
                    "share", "is_bot", "fetched_at", "lookback_days", "source", "capped"]


# ── the fetch ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_fetch_records_lookback_365_and_fetched_at_on_every_row(registry):
    client = _client(_commits_230(), ALL_TIME)
    out = C.fetch_contributors(registry, client, "widget", FULL, now=NOW)
    rows12 = registry.latest_contributor_fetch("widget", C.WINDOW_12)
    assert rows12 and all(r["lookback_days"] == 365 and r["fetched_at"] == NOW.isoformat() for r in rows12)
    assert all(r["source"] == "github:commits" for r in rows12)
    rows_all = registry.latest_contributor_fetch("widget", C.WINDOW_ALL)
    assert rows_all and all(r["fetched_at"] == NOW.isoformat() and r["lookback_days"] is None for r in rows_all)
    # the since bound is 365 days back, 100 per page; 230 commits are 3 calls, 7 contributors 1
    first = client.rest_get.call_args_list[0]
    assert first.args[0] == f"/repos/{FULL}/commits"
    assert first.args[1]["since"] == "2025-10-23T12:00:00Z" and first.args[1]["per_page"] == 100
    assert out[C.WINDOW_12]["pages"] == 3 and out[C.WINDOW_ALL]["pages"] == 1
    assert client.rest_get.call_args_list[-1].args[1] == {"per_page": 100, "anon": 1, "page": 1}
    assert "GitHub call" in out["cost_line"]


def test_the_cap_stops_at_50_calls_with_capped_and_the_cut_date_and_the_card_says_so(registry):
    commits = [_commit(i, f"Dev {i % 7}", f"dev{i % 7}", days_ago=i * 0.01) for i in range(6000)]   # 60 pages
    client = _client(commits, [_user("dev0", 9)])
    out = C.fetch_contributors(registry, client, "widget", FULL, now=NOW)
    commit_calls = [c for c in client.rest_get.call_args_list if c.args[0].endswith("/commits")]
    assert len(commit_calls) == 50 and out[C.WINDOW_12]["pages"] == 50
    cut = commits[4999]["commit"]["author"]["date"]
    assert out[C.WINDOW_12]["capped"] == cut
    cl = C.contributors(registry, "widget", C.WINDOW_12)
    assert cl.capped is True and cl.cut_at == cut and cl.total == 5000
    assert f"12-month list from the most recent 5,000 commits (window cut at {cut[:10]})" in cl.words()


def test_a_403_is_not_permitted_with_the_reset_time_and_writes_no_rows(registry):
    client = _client(_commits_230(), ALL_TIME, refuse="/commits")
    out = C.fetch_contributors(registry, client, "widget", FULL, now=NOW)
    assert out[C.WINDOW_12]["absence"] == C.NOT_PERMITTED
    assert out[C.WINDOW_12]["reset_at"] == "2025-10-23T13:00:00"
    assert registry.latest_contributor_fetch("widget", C.WINDOW_12) == []
    cl = C.contributors(registry, "widget", C.WINDOW_12)
    assert cl.absence == C.NO_FETCH_YET and cl.words() == ["no contributor fetch yet"]
    assert C.not_permitted_words("2025-10-23T13:00:00") == "GitHub refused the read (rate limit resets 2025-10-23T13:00:00)"


def test_too_few_calls_left_refuses_before_the_first_call(registry):
    client = _client(_commits_230(), ALL_TIME, rate={"remaining": 0, "limit": 5000, "reset_at": "2026-10-23T13:00:00"})
    out = C.fetch_contributors(registry, client, "widget", FULL, now=NOW)
    assert client.rest_get.call_count == 0
    assert out[C.WINDOW_12]["absence"] == out[C.WINDOW_ALL]["absence"] == C.NOT_PERMITTED
    assert out[C.WINDOW_ALL]["reset_at"] == "2026-10-23T13:00:00"


def test_bots_are_counted_and_left_out_of_the_share_and_anonymous_rows_kept(registry):
    C.fetch_contributors(registry, _client(_commits_230(), ALL_TIME), "widget", FULL, now=NOW)
    cl = C.contributors(registry, "widget", C.WINDOW_ALL)
    assert cl.bots_excluded == 2 and "2 bots excluded" in cl.words()
    assert [r.name for r in cl.rows] == ["alice", "bob", "carol", "Dave Iyer", "erin"]
    dave = next(r for r in cl.rows if r.name == "Dave Iyer")
    assert dave.kind == "Anonymous" and dave.login == ""
    with_bots = C.contributors(registry, "widget", C.WINDOW_ALL, include_bots=True)
    assert {r.name for r in with_bots.rows if r.is_bot} == {"dependabot[bot]", "github-actions[bot]"}
    stored = registry.latest_contributor_fetch("widget", C.WINDOW_ALL)
    assert sum(1 for r in stored if r["is_bot"]) == 2          # kept as rows


def test_the_500_author_line_sets_linking_limit(registry):
    linked = [_user(f"u{i}", 1000 - i) for i in range(500)]
    anon = [_anon(f"Anon{i}", 1) for i in range(40)]
    C.fetch_contributors(registry, _client([], linked + anon), "widget", FULL, now=NOW)
    cl = C.contributors(registry, "widget", C.WINDOW_ALL)
    assert cl.absence == C.LINKING_LIMIT_REACHED and cl.total_rows == 540
    assert "GitHub links only the first 500 authors; 40 more are anonymous" in cl.words()
    small = C.contributors(registry, "widget", C.WINDOW_12)
    assert small.absence == C.EMPTY_REPOSITORY and small.words() == ["no commits in the last 12 months"]


def test_shares_sum_to_one_over_all_rows_and_the_top_share_is_against_the_total(registry):
    people = [_user(f"p{i}", 20 - i) for i in range(15)]           # 15 rows, 195 contributions
    C.fetch_contributors(registry, _client([], people), "widget", FULL, now=NOW)
    stored = [r for r in registry.latest_contributor_fetch("widget", C.WINDOW_ALL) if r["rank"] >= 1]
    assert abs(sum(r["share"] for r in stored) - 1.0) < 1e-9
    cl = C.contributors(registry, "widget", C.WINDOW_ALL)
    assert len(cl.rows) == 10 and cl.total == 195
    assert abs(cl.top_share - sum(20 - i for i in range(10)) / 195) < 1e-9     # 155/195, not 1.0
    assert cl.top_share < 1.0


def test_never_fetched_is_not_the_same_as_fetched_and_empty(registry):
    assert C.contributors(registry, "widget", C.WINDOW_ALL).absence == C.NO_FETCH_YET
    C.fetch_contributors(registry, _client([], []), "widget", FULL, now=NOW)
    cl = C.contributors(registry, "widget", C.WINDOW_ALL)
    assert cl.absence == C.EMPTY_REPOSITORY and cl.row_ids             # the fetch's own row proves the read


def test_older_fetches_are_pruned_per_list(registry):
    for d in range(C.FETCHES_KEPT + 2):
        C.fetch_contributors(registry, _client([], [_user("a", 1)]), "widget", FULL, now=NOW + timedelta(days=d))
    with registry._conn() as conn:
        n = conn.execute("SELECT COUNT(DISTINCT fetched_at) FROM project_contributors WHERE list_window = ?",
                         (C.WINDOW_ALL,)).fetchone()[0]
    assert n == C.FETCHES_KEPT


# ── chaoss_metrics ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_chaoss_falls_back_to_git_authors_and_says_so_when_the_table_is_empty(registry):
    from resource_explorer.surveyors.sub_surveyors import chaoss_metrics as CM

    rows = [{"author_email": "a@x.org", "author_name": "a", "committed_at": "2026-10-01T00:00:00"}] * 3
    ef = next(m for m in CM.assess(rows, {}, all_time=C.contributors(registry, "widget", C.WINDOW_ALL))
              if m["check_name"] == "elephant_factor")
    assert "(from git authors, 90-day fetch)" in ef["summary"]
    assert ef["detail"]["basis"] == "from git authors, 90-day fetch"


def test_chaoss_concentration_comes_from_the_all_time_list_when_stored(registry):
    from resource_explorer.surveyors.sub_surveyors import chaoss_metrics as CM

    C.fetch_contributors(registry, _client(_commits_230(), ALL_TIME), "widget", FULL, now=NOW)
    ef = next(m for m in CM.assess([], {}, all_time=C.contributors(registry, "widget", C.WINDOW_ALL, top=10_000))
              if m["check_name"] == "elephant_factor")
    # humans 400+300+100+50+30 = 880; alice+bob = 700 >= 440 -> 2
    assert ef["detail"]["value"] == 2 and ef["detail"]["commits"] == 880
    assert ef["detail"]["basis"] == "contributions all time" and "90-day" not in ef["summary"]


# ── the publish annotations ───────────────────────────────────────────────────────────────────────────────────────

def test_one_resource_measure_annotation_per_list_identified_by_window(registry):
    from resource_explorer.surveyors.annotation_props import build_annotation_props
    from resource_explorer.surveyors.survey_report import annotation_qualified_name

    assert C.annotations(registry, "widget") == []                   # never fetched publishes nothing
    C.fetch_contributors(registry, _client(_commits_230(), ALL_TIME), "widget", FULL, now=NOW)
    anns = C.annotations(registry, "widget")
    assert [a.item_key for a in anns] == [C.WINDOW_12, C.WINDOW_ALL]
    names = {annotation_qualified_name("RPT", i, a) for i, a in enumerate(anns)}
    assert names == {"RPT::contributors::months_12", "RPT::contributors::all_time"}
    body = build_annotation_props(anns[1], "RPT::contributors::all_time")
    assert body["class"] == "ResourceMeasureAnnotationProperties" and body["annotationType"] == "Contributors"
    top10 = json.loads(body["resourceProperties"]["top10"])
    assert top10[0] == {"login": "alice", "commits": 400, "share": round(400 / 1000, 4)}
    assert body["additionalProperties"]["measurementName"] == "all_time"
    assert body["additionalProperties"]["as_of"] == NOW.isoformat()
    assert body["additionalProperties"]["basis"] == "contributions all time"


# ── end to end: 230 commits by 7 authors (2 bots) ────────────────────────────────────────────────────────────────

def test_end_to_end_both_lists_the_question_headlines_and_the_row_ids_on_the_stored_answer(registry):
    from resource_explorer.agents.tools import query_top_committers_raw
    from resource_explorer.context_compile import compile_context
    from resource_explorer.facts import FactLayer
    from resource_explorer.surveyors.question_catalog_reader import find_question_by_id
    from resource_explorer.surveyors.sub_surveyors.chaoss_metrics import ChaossMetricsSurveyor

    C.fetch_contributors(registry, _client(_commits_230(), ALL_TIME), "widget", FULL, now=NOW)

    twelve = C.contributors(registry, "widget", C.WINDOW_12)
    assert twelve.total == 230 and twelve.bots_excluded == 2
    assert [(r.name, r.commits) for r in twelve.rows] == [
        ("alice", 100), ("bob", 50), ("carol", 30), ("Dave Iyer", 20), ("erin", 10)]
    assert next(r for r in twelve.rows if r.name == "Dave Iyer").kind == "unlinked"   # GitHub did not link him
    every = C.contributors(registry, "widget", C.WINDOW_ALL)
    assert [r.name for r in every.rows][:2] == ["alice", "bob"] and every.total == 1000

    surveyed_at = "2026-10-23T12:05:00"
    project = registry.get("widget")
    ChaossMetricsSurveyor(project, registry, surveyed_at=surveyed_at).run()
    registry.record_step_run("widget", "repo_chaoss_metrics", surveyed_at, entity_type="repo")

    layer = FactLayer(registry)
    q3 = layer.answer("widget", find_question_by_id("Q-0003", "repo"))
    q51 = layer.answer("widget", find_question_by_id("Q-0051", "repo"))
    # Q-0003 is answered from the resource's own state (facts._r_maintainers), now read from the lists
    f3 = next(f for f in q3.facts if f.analysis_id == "project_commits")
    h3 = f3.headline
    assert set(f3.value["row_ids"]) == set(twelve.row_ids) | set(every.row_ids)
    h51 = next(f.headline for f in q51.facts if f.analysis_id == "chaoss_metrics")
    # Q-0003 names the top contributor and the top-3 share (against the total, bots included in the total)
    assert "top contributor alice (40% of contributions all time)" in h3 and "top 3 hold 80% all time" in h3
    # Q-0051: the concentration, and the list is its extent
    assert "CHAOSS elephant factor" in h51
    value = next(f.value for f in q51.facts if f.analysis_id == "chaoss_metrics")
    assert [r["name"] for r in value["contributors"]["all_time"]["rows"]][:3] == ["alice", "bob", "carol"]

    compiled = compile_context(registry, "widget", find_question_by_id("Q-0003", "repo")["question"])
    assert "chaoss_metrics" in {p["key"] for p in compiled.manifest["packed"]}
    assert "1. alice: 400 (40.0%)" in compiled.text
    assert compiled.manifest["lists"]["chaoss_metrics"]["contributors.all_time"]["total"] == 7
    seen = compiled.manifest["rows_seen"]["chaoss_metrics"]["project_contributors"]
    expected = set(twelve.row_ids) | set(every.row_ids)
    assert set(seen["FULL"]) == expected
    # stored: the recorded compile carries the same ids
    with registry._conn() as conn:
        stored = conn.execute("SELECT manifest FROM context_compiles WHERE compile_id = ?",
                              (compiled.compile_id,)).fetchone()[0]
    assert set(json.loads(stored)["rows_seen"]["chaoss_metrics"]["project_contributors"]["FULL"]) == expected

    # the chat tool names the same people
    with patch("resource_explorer.registry.ProjectRegistry", return_value=registry):
        chat = query_top_committers_raw("widget")
    assert "1. alice: 400 (40.0%)" in chat and "1. alice: 100" in chat and C.COMPARE_WORDS in chat
