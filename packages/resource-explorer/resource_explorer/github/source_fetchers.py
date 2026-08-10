"""Fetchers for auto-populating 'list'-type discovery sources from a
foundation's own canonical project list — the fetch_url/fetch_kind
extension point flagged (not built) when list-type sources were first
designed. Deliberately explicit/pull-based (a "Refresh from source" action
in discovery.py, not a background poll) — matches this codebase's existing
convention that state changes are always a deliberate action, never a
silent side effect (disposition, publish, etc. all work the same way).

Three fetchers are implemented, chosen because all were confirmed low-risk
via direct inspection of their real, public, unauthenticated formats:

- CNCF's landscape.yml — a static YAML file in github.com/cncf/landscape,
  no auth, well-structured `repo_url` fields.
- LF AI & Data's landscape.yml — same `landscape2` generator tool CNCF's
  own landscape site runs on (confirmed: github.com/lfai/lfai-landscape,
  same schema), just a different foundation's data file. This is the real
  fix for the exact "LF AI & Data's own `lfai` org holds governance repos,
  not member project code" gap `foundation_prefilters.json` flagged and
  deliberately left unsolved — a search-based org: qualifier was always
  going to be wrong for this foundation; its own landscape file is the
  correct source. Verified live: 367 repo URLs, includes odpi/egeria.
- Eclipse's project API — projects.eclipse.org/api, no auth for reads,
  the exact "hundreds of orgs" sprawl case that motivated 'list' sources.

Any other `landscape2`-generated site (several LF sub-foundations use the
same tool — LF Networking, LF Energy, etc.) works with the same parser via
a 'list' source's fetch_url override; only CNCF's and LF AI & Data's are
registered by name here since those are the two confirmed relevant to this
codebase's own users.

LFX Insights (the Linux Foundation's own cross-project analytics platform —
a different thing from any single foundation's landscape2 site) is
registered as a known-future slot but deliberately left unimplemented: it
needs a confirmed API key/auth flow and its schema/rate limits aren't
verified here — building it blind risks a silently-wrong fetcher, worse
than not having one.
"""
from __future__ import annotations

from typing import Callable

import httpx
import yaml

_DEFAULT_CNCF_LANDSCAPE_URL = "https://raw.githubusercontent.com/cncf/landscape/master/landscape.yml"
_DEFAULT_LFAI_LANDSCAPE_URL = "https://raw.githubusercontent.com/lfai/lfai-landscape/main/landscape.yml"
_DEFAULT_ECLIPSE_PROJECTS_URL = "https://projects.eclipse.org/api/projects"


def _fetch_landscape2_yaml(url: str) -> list[str]:
    """Shared parser for any `landscape2`-generated landscape.yml (CNCF, LF
    AI & Data, and — per the tool's own adoption — other LF sub-foundations
    that happen to use the same generator). Each item can carry a repo_url
    (github/gitlab/etc.) — only github.com URLs are kept, since discovery
    sources are GitHub-only today. Items with no repo_url (homepage-only
    entries) are skipped."""
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    data = yaml.safe_load(resp.text) or {}
    urls: list[str] = []
    for category in data.get("landscape", []) or []:
        for subcategory in category.get("subcategories", []) or []:
            for item in subcategory.get("items", []) or []:
                repo_url = (item.get("repo_url") or "").strip()
                if repo_url and "github.com" in repo_url:
                    urls.append(repo_url.rstrip("/"))
    return sorted(set(urls))


def _fetch_cncf_landscape(fetch_url: str) -> list[str]:
    return _fetch_landscape2_yaml(fetch_url or _DEFAULT_CNCF_LANDSCAPE_URL)


def _fetch_lfai_landscape(fetch_url: str) -> list[str]:
    return _fetch_landscape2_yaml(fetch_url or _DEFAULT_LFAI_LANDSCAPE_URL)


def _fetch_eclipse_projects(fetch_url: str) -> list[str]:
    """Eclipse's project API shape varies by project (github_repos vs.
    source_repo, list vs. dict) — handled defensively rather than assuming
    one fixed shape, since this is a live third-party API not under our
    control. Non-GitHub repos (some Eclipse projects use their own GitLab)
    are skipped, matching every other discovery path's GitHub-only scope."""
    url = fetch_url or _DEFAULT_ECLIPSE_PROJECTS_URL
    resp = httpx.get(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    projects = data if isinstance(data, list) else data.get("projects", data)
    iterable = projects.values() if isinstance(projects, dict) else (projects or [])

    urls: list[str] = []
    for proj in iterable:
        if not isinstance(proj, dict):
            continue
        repos = proj.get("github_repos") or proj.get("source_repo") or []
        if isinstance(repos, dict):
            repos = repos.values()
        for repo in repos:
            repo_url = (repo.get("url", "") if isinstance(repo, dict) else str(repo)).strip()
            if repo_url and "github.com" in repo_url:
                urls.append(repo_url.rstrip("/"))
    return sorted(set(urls))


def _fetch_lfx_insights(fetch_url: str) -> list[str]:
    raise NotImplementedError(
        "LFX Insights fetcher not implemented — its API needs a confirmed "
        "auth key/flow and schema that hasn't been verified. LF AI & Data "
        "itself has a real fetcher now (fetch_kind='lfai_landscape') — this "
        "one is for whatever LFX Insights adds beyond what a foundation's "
        "own landscape2 site already covers."
    )


# fetch_kind -> fetcher(fetch_url) -> sorted, deduped list[github_url].
# A plain dict, not decorator-based auto-registration — four entries
# doesn't need the extra indirection.
FETCHERS: dict[str, Callable[[str], list[str]]] = {
    "cncf_landscape": _fetch_cncf_landscape,
    "lfai_landscape": _fetch_lfai_landscape,
    "eclipse_projects": _fetch_eclipse_projects,
    "lfx_insights": _fetch_lfx_insights,
}


def fetch_source_urls(fetch_kind: str, fetch_url: str = "") -> list[str]:
    """Raises ValueError for an unknown fetch_kind, NotImplementedError for
    a registered-but-unbuilt one (lfx_insights today), or whatever the
    underlying fetcher raises (httpx.HTTPStatusError, yaml errors, etc.) —
    all translated to a clear HTTP error by the calling route."""
    fetcher = FETCHERS.get(fetch_kind)
    if fetcher is None:
        raise ValueError(f"Unknown fetch_kind '{fetch_kind}' — must be one of {sorted(FETCHERS)}")
    return fetcher(fetch_url)
