"""Repo discovery — "how do we decide where to scout in the first place."

A general GitHub search for candidate repos, independent of any specific org
(generalizes and retires the old org-only discovery flow that used to live in
Admin > Groups — see git history for `GET /api/projects/discover/{org}`).
Deliberately separate from projects.py, which manages already-registered
projects — this module is "find repos worth considering," not "manage repos
you already have." Reuses OrgImporter/_run_import_batch
(github/org_importer.py) for the actual catalog-only registration, and
GitHubClient.search_repos() for the search itself.

Also owns repo triage disposition (undecided/tracking/investigating/ignored,
registry.py's repo_dispositions table) — since a disposition can apply to a
repo that was never imported at all, it's surfaced here on every search
result, not just on already-registered projects (see projects.py's
ProjectSummary.disposition for the registered-repo side of the same data).

"Discover repos to scout" plan, D4-D6, D10.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# Curated pre-filter list, loaded from configdata/foundation_prefilters.json —
# a plain JSON file (not a Python constant) so new entries can be added
# without a code change/deploy, same spirit as configdata/analysis_catalog.yaml
# and technology_type_processes.yaml (D5). Read fresh on every request —
# the file is tiny and this lets an edit take effect without restarting the
# server.
#
# Each entry maps to a single GitHub `org:` search qualifier, which only
# works for foundations whose member projects actually live under one
# umbrella org (true for cncf/apache/python/linuxfoundation below). It does
# NOT work for foundations that curate a *list* of member projects hosted in
# many separate orgs — e.g. LF AI & Data, whose own "lfai" org holds
# governance/website repos, not member project code (Egeria itself lives at
# odpi/egeria, not under lfai). Adding an `org:lfai`-style entry for those
# would silently return the wrong repos rather than the intended ones — so
# it's deliberately left out here rather than added as a broken chip.
#
# LF AI & Data's own case is now solved properly, just not through this
# file — its landscape.yml (same landscape2 tool CNCF's own site runs on)
# is a real, working discovery-source fetch_kind ("lfai_landscape",
# github/source_fetchers.py). GET /quick-list-sources below is the actual
# one-click equivalent for this shape — a search chip doesn't fit (there's
# no org:/topic: qualifier to prefill), but a "create + populate + run" list
# source does.
_FOUNDATION_PREFILTERS_PATH = Path(__file__).parent.parent.parent / "configdata" / "foundation_prefilters.json"

# Foundations with a real, working fetch_kind (github/source_fetchers.py) —
# NOT the same list as foundation_prefilters.json above. cncf_landscape is
# deliberately excluded here even though it's a real fetcher: CNCF's own
# search chip (org:cncf) already covers it well, so a second, redundant
# "quick add a list source too" button would just be confusing. lfx_insights
# is excluded because it's a registered-but-unimplemented fetch_kind (see
# source_fetchers.py) — nothing to quick-add yet.
_QUICK_LIST_SOURCES_PATH = Path(__file__).parent.parent.parent / "configdata" / "quick_list_sources.json"


def _load_foundation_prefilters() -> dict:
    try:
        return json.loads(_FOUNDATION_PREFILTERS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _load_quick_list_sources() -> dict:
    try:
        return json.loads(_QUICK_LIST_SOURCES_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


@router.get("/quick-list-sources")
async def list_quick_list_sources() -> dict:
    """fetch_kind -> {label, display_name} for foundations with a real
    fetch_kind implementation, worth a one-click 'add + populate + run'
    button on the Discover view — the list-source equivalent of
    /foundations' search-chip prefills, for foundations a GitHub search
    genuinely can't cover (Eclipse's hundreds of orgs, LF AI & Data's
    governance-vs-code-org split)."""
    return _load_quick_list_sources()


@router.get("/foundations")
async def list_foundation_prefilters() -> dict:
    return _load_foundation_prefilters()


class GithubBaseUrlSetting(BaseModel):
    base_url: str
    is_override: bool  # False = showing config.py's .env-configured default, not a runtime override


@router.get("/github-base-url", response_model=GithubBaseUrlSetting)
async def get_github_base_url() -> GithubBaseUrlSetting:
    """Backs the minimal inline "GitHub source: <base_url> [edit]" control
    on the Discover-repos view (D1/D2/D8) — the only runtime setting this
    plan introduces, so a small dedicated pair of routes rather than a full
    generic /api/settings/{key} REST surface."""
    from resource_explorer.config import get_config
    from resource_explorer.registry import ProjectRegistry

    override = ProjectRegistry().get_setting("github_base_url")
    return GithubBaseUrlSetting(
        base_url=override or get_config().github.base_url, is_override=bool(override),
    )


class GithubBaseUrlUpdate(BaseModel):
    base_url: str  # "" clears the override, reverting to the .env default


@router.post("/github-base-url", response_model=GithubBaseUrlSetting)
async def set_github_base_url(body: GithubBaseUrlUpdate) -> GithubBaseUrlSetting:
    from resource_explorer.config import get_config
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.set_setting("github_base_url", body.base_url.strip())
    override = registry.get_setting("github_base_url")
    return GithubBaseUrlSetting(
        base_url=override or get_config().github.base_url, is_override=bool(override),
    )


class RepoSearchRequest(BaseModel):
    keyword: str = ""
    min_stars: int = 0
    language: str = ""
    license: str = ""
    pushed_after: str = ""  # "YYYY-MM-DD" — GitHub search's pushed:>DATE qualifier
    org: str = ""
    topic: str = ""
    sort: str = "stars"     # stars | forks | updated
    limit: int = 100
    # The old org-only discovery flow (GitHubClient.list_org_repos(), retired)
    # excluded forks and archived repos by default — that default was lost
    # when it generalized into this general search; restored explicitly here
    # rather than relying on GitHub's own (inconsistent) API defaults.
    include_archived: bool = False
    include_forks: bool = False


def _build_query(req: RepoSearchRequest) -> str:
    """Translate structured filter fields into GitHub's qualifier-string
    query language, server-side — keeps the frontend/API contract
    provider-agnostic; a future GitLab client would take the same
    structured filters and build its own query shape (D4)."""
    parts = []
    if req.keyword:
        parts.append(req.keyword)
    if req.min_stars:
        parts.append(f"stars:>={req.min_stars}")
    if req.language:
        parts.append(f"language:{req.language}")
    if req.license:
        parts.append(f"license:{req.license}")
    if req.pushed_after:
        parts.append(f"pushed:>{req.pushed_after}")
    if req.org:
        parts.append(f"org:{req.org}")
    if req.topic:
        parts.append(f"topic:{req.topic}")
    if not parts:
        # Checked before the archived:false/fork:false defaults below are
        # appended — those aren't user-provided filters, so a request with
        # nothing else would otherwise silently produce a valid-looking
        # query and match "everything not archived and not a fork."
        raise ValueError("At least one search filter is required.")
    if not req.include_archived:
        parts.append("archived:false")
    if not req.include_forks:
        parts.append("fork:false")
    return " ".join(parts)


class DiscoveredRepo(BaseModel):
    full_name: str
    html_url: str
    description: str = ""
    stars: int = 0
    language: str = ""
    license: str = ""
    forks: int = 0
    already_registered: bool = False
    # Surfaced from repo_dispositions regardless of already_registered — a
    # previously-ignored candidate should say so even if it was never
    # imported (D10, the actual "remind them what was decided" ask).
    disposition: str = "undecided"
    disposition_reason: str = ""
    disposition_decided_at: str = ""


def _enrich_repos(repos: list[dict], registry) -> list["DiscoveredRepo"]:
    """Shared tail for every discovery path (ad-hoc search, a saved 'search'
    source, or a saved 'list' source) — attaches already_registered/
    disposition context to each raw repo dict."""
    out = []
    for r in repos:
        disp = registry.get_disposition(r["html_url"]) or {}
        out.append(DiscoveredRepo(
            full_name=r["full_name"], html_url=r["html_url"], description=r["description"],
            stars=r["stars"], language=r["language"],
            license=r.get("license", ""), forks=r.get("forks", 0),
            already_registered=registry.get_by_github_url(r["html_url"]) is not None,
            disposition=disp.get("disposition", "undecided"),
            disposition_reason=disp.get("reason", ""),
            disposition_decided_at=disp.get("decided_at", ""),
        ))
    return out


async def _run_search_query(req: "RepoSearchRequest", registry) -> list[dict]:
    """Raw repo dicts for a 'search' source (or the ad-hoc form) — shared
    by POST /search and POST /sources/{slug}/run."""
    from github import GithubException

    from resource_explorer.github.client import GitHubClient

    try:
        query = _build_query(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Runtime override (set via the Scouting > Discover repos inline
    # setting) takes precedence over the .env-configured deployment default
    # (config.py's GitHubConfig.base_url, applied inside GitHubClient itself
    # when base_url=None) — D2.
    base_url = registry.get_setting("github_base_url") or None

    def _search():
        return GitHubClient(base_url=base_url).search_repos(
            query, sort=req.sort, order="desc", limit=req.limit,
        )

    try:
        return await asyncio.to_thread(_search)
    except GithubException as exc:
        if exc.status in (401, 403):
            raise HTTPException(
                status_code=502,
                detail="GitHub authentication/rate-limit error — check GITHUB_TOKEN in .env",
            ) from exc
        if exc.status == 422:
            raise HTTPException(status_code=400, detail=f"Invalid search query: {query}") from exc
        raise HTTPException(status_code=502, detail=f"GitHub API error: {exc}") from exc


async def _run_list_urls(urls: list[str], registry) -> list[dict]:
    """Raw repo dicts for a 'list' source — a manually-curated set of
    github_urls (Eclipse-style many-orgs foundations, or a user's own
    enterprise repos), best-effort enriched via one GitHubClient.get_repo()
    call per URL. A URL that 404s or otherwise fails is skipped, not fatal
    to the rest of the batch ("Scouting workflow redesign" plan, D1)."""
    from resource_explorer.github.client import GitHubClient

    base_url = registry.get_setting("github_base_url") or None
    client = GitHubClient(base_url=base_url)

    def _fetch_all():
        out = []
        for url in urls:
            try:
                out.append(client._repo_to_dict(client.get_repo(url)))
            except Exception:
                continue
        return out

    return await asyncio.to_thread(_fetch_all)


@router.post("/search", response_model=list[DiscoveredRepo])
async def search_repos(req: RepoSearchRequest) -> list[DiscoveredRepo]:
    """Read-only — does not touch the registry except to read
    already_registered/disposition context for each result."""
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    repos = await _run_search_query(req, registry)
    return _enrich_repos(repos, registry)


class ImportRepoSpec(BaseModel):
    github_url: str
    display_name: str
    description: str = ""


class ImportRequest(BaseModel):
    repos: list[ImportRepoSpec]
    group_slug: str = ""
    # Whatever produced this batch — a foundation/org name or a search
    # description (e.g. "search: language:python stars:>=500") — threaded
    # into the activity-log summary text (D7).
    source_label: str = "search"


class ImportResponse(BaseModel):
    queued: int
    skipped: list[str]  # github_urls already registered, not re-queued


@router.post("/import", response_model=ImportResponse)
async def import_repos(body: ImportRequest) -> ImportResponse:
    """Queues a background import — see resource_explorer/github/org_importer.py.
    Returns immediately; progress is written to the activity log (operation
    'scout') as each repo completes, not polled from this response."""
    import threading

    from resource_explorer.github.org_importer import _run_import_batch
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    if body.group_slug and not registry.get_group(body.group_slug):
        raise HTTPException(status_code=404, detail=f"Group '{body.group_slug}' not found")

    to_queue = []
    skipped = []
    for r in body.repos:
        if registry.get_by_github_url(r.github_url):
            skipped.append(r.github_url)
        else:
            to_queue.append(r.model_dump())

    if to_queue:
        t = threading.Thread(
            target=_run_import_batch,
            args=(body.source_label, to_queue, body.group_slug),
            daemon=True,
            name="resource-explorer-discovery-import",
        )
        t.start()

    return ImportResponse(queued=len(to_queue), skipped=skipped)


# undecided -> tracking/investigating -> {abandoned, ignored}. "ignored" =
# passed on it early/cheaply, never got past scouting; "abandoned" = went
# further (investigated, maybe surveyed/analyzed) and then decided against
# it — same hiding-from-sidebar treatment, but the history reads honestly
# instead of collapsing both into one word (Scouting workflow redesign, D3).
_VALID_DISPOSITIONS = {"undecided", "tracking", "investigating", "abandoned", "ignored"}


class DispositionRequest(BaseModel):
    github_url: str
    disposition: str
    reason: str = ""


class DispositionResponse(BaseModel):
    status: str
    github_url: str
    disposition: str


@router.post("/disposition", response_model=DispositionResponse)
async def set_repo_disposition(body: DispositionRequest) -> DispositionResponse:
    """The one write endpoint every disposition control calls — the
    Scouting overview card for a registered repo, and each row's control in
    the search-results table for a not-yet-imported candidate (D10)."""
    from resource_explorer.registry import ProjectRegistry

    if body.disposition not in _VALID_DISPOSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid disposition '{body.disposition}' — must be one of {sorted(_VALID_DISPOSITIONS)}",
        )

    registry = ProjectRegistry()
    project = registry.get_by_github_url(body.github_url)
    registry.set_disposition(
        body.github_url, body.disposition, reason=body.reason,
        project_slug=project.slug if project else "",
    )
    return DispositionResponse(status="ok", github_url=body.github_url, disposition=body.disposition)


# ── named discovery sources (D1/D2) ─────────────────────────────────────────

class DiscoverySourceConfig(BaseModel):
    """Union of both source_type shapes — callers only populate the fields
    relevant to their source_type; the rest stay at their defaults. Kept as
    one flat model rather than a Pydantic discriminated union so the Admin
    UI's single form doesn't need to branch its request-building logic."""
    # 'search' fields (same as RepoSearchRequest, minus limit/sort which stay
    # per-run rather than saved):
    keyword: str = ""
    min_stars: int = 0
    language: str = ""
    license: str = ""
    pushed_after: str = ""
    org: str = ""
    topic: str = ""
    # 'list' fields:
    urls: list[str] = []
    # Optional auto-refresh binding for a 'list' source — populated urls
    # can still be hand-edited even when set. fetch_kind selects a fetcher
    # from github/source_fetchers.py (e.g. "cncf_landscape",
    # "eclipse_projects"); fetch_url overrides that fetcher's own default
    # endpoint, mainly useful for pointing at a pinned/mirrored copy.
    # Never auto-runs — see POST /sources/{slug}/refresh.
    fetch_kind: str = ""
    fetch_url: str = ""


class DiscoverySourceCreate(BaseModel):
    slug: str
    display_name: str
    source_type: str  # "search" | "list"
    config: DiscoverySourceConfig


class DiscoverySource(BaseModel):
    slug: str
    display_name: str
    source_type: str
    config: DiscoverySourceConfig
    created_at: str


_VALID_SOURCE_TYPES = {"search", "list"}


@router.get("/sources", response_model=list[DiscoverySource])
async def list_discovery_sources() -> list[DiscoverySource]:
    from resource_explorer.registry import ProjectRegistry
    return [DiscoverySource(**s) for s in ProjectRegistry().list_discovery_sources()]


@router.post("/sources", response_model=DiscoverySource)
async def create_discovery_source(body: DiscoverySourceCreate) -> DiscoverySource:
    if body.source_type not in _VALID_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source_type '{body.source_type}' — must be one of {sorted(_VALID_SOURCE_TYPES)}",
        )
    # A fetch_kind-backed list source can legitimately start with zero URLs —
    # the whole point is that refresh-apply populates them, so requiring a
    # seed URL first would defeat a one-click "add this foundation" flow.
    # Only a purely-manual list (no fetch_kind) needs at least one URL up
    # front, since nothing would ever populate it otherwise.
    if body.source_type == "list" and not body.config.urls and not body.config.fetch_kind:
        raise HTTPException(
            status_code=400,
            detail="A 'list' source needs at least one URL, unless it has a fetch_kind set.",
        )

    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    registry.create_discovery_source(
        body.slug, body.display_name, body.source_type, body.config.model_dump(),
    )
    return DiscoverySource(**registry.get_discovery_source(body.slug))


@router.delete("/sources/{slug}")
async def delete_discovery_source(slug: str) -> dict:
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if not registry.get_discovery_source(slug):
        raise HTTPException(status_code=404, detail=f"Discovery source '{slug}' not found")
    registry.delete_discovery_source(slug)
    return {"removed": slug}


@router.post("/sources/{slug}/run", response_model=list[DiscoveredRepo])
async def run_discovery_source(slug: str) -> list[DiscoveredRepo]:
    """Dispatches to the search path or the list-enrichment path depending
    on the source's source_type — same DiscoveredRepo shape either way, so
    the frontend's results table needs no branch per source type."""
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    source = registry.get_discovery_source(slug)
    if not source:
        raise HTTPException(status_code=404, detail=f"Discovery source '{slug}' not found")

    if source["source_type"] == "search":
        req = RepoSearchRequest(**{k: v for k, v in source["config"].items() if k != "urls"})
        repos = await _run_search_query(req, registry)
    else:
        repos = await _run_list_urls(source["config"].get("urls", []), registry)

    return _enrich_repos(repos, registry)


class SourceRefreshPreview(BaseModel):
    added: list[str]
    removed: list[str]
    fetched_count: int
    current_count: int


def _require_fetch_binding(source: dict) -> tuple[str, str]:
    if source["source_type"] != "list":
        raise HTTPException(
            status_code=400,
            detail="Only 'list'-type sources support fetch/refresh — 'search' sources always run live.",
        )
    fetch_kind = source["config"].get("fetch_kind", "")
    if not fetch_kind:
        raise HTTPException(
            status_code=400,
            detail="This source has no fetch_kind configured — set one (e.g. 'cncf_landscape') to enable refresh.",
        )
    return fetch_kind, source["config"].get("fetch_url", "")


async def _fetch_source_urls(source: dict, registry) -> list[str]:
    """Shared by both refresh routes so the preview and the apply always
    run the exact same fetch — no separate 'apply the previewed diff'
    endpoint that could drift from what a second fetch would actually
    return."""
    from resource_explorer.github.source_fetchers import fetch_source_urls

    fetch_kind, fetch_url = _require_fetch_binding(source)
    try:
        return await asyncio.to_thread(fetch_source_urls, fetch_kind, fetch_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:  # httpx.HTTPStatusError, yaml errors, etc. — the fetcher hit a live third-party source
        raise HTTPException(status_code=502, detail=f"Fetch failed: {exc}") from exc


@router.post("/sources/{slug}/refresh", response_model=SourceRefreshPreview)
async def preview_discovery_source_refresh(slug: str) -> SourceRefreshPreview:
    """Read-only — fetches fresh URLs from the source's fetch_kind and
    diffs against its currently-saved list, but does NOT persist anything.
    Matches this codebase's convention that state changes are always a
    deliberate, separate action (see disposition/publish) — the frontend
    shows this diff and a human clicks Apply to actually save it."""
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    source = registry.get_discovery_source(slug)
    if not source:
        raise HTTPException(status_code=404, detail=f"Discovery source '{slug}' not found")

    fetched = await _fetch_source_urls(source, registry)
    current = set(source["config"].get("urls", []))
    fetched_set = set(fetched)
    return SourceRefreshPreview(
        added=sorted(fetched_set - current),
        removed=sorted(current - fetched_set),
        fetched_count=len(fetched_set),
        current_count=len(current),
    )


@router.post("/sources/{slug}/refresh-apply", response_model=DiscoverySource)
async def apply_discovery_source_refresh(slug: str) -> DiscoverySource:
    """Re-runs the same fetch as the preview (cheap — one HTTP call) and
    overwrites the source's urls with the result. Re-fetching rather than
    trusting a client-supplied diff means the applied state always matches
    a fetch that actually just happened, not a stale preview."""
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    source = registry.get_discovery_source(slug)
    if not source:
        raise HTTPException(status_code=404, detail=f"Discovery source '{slug}' not found")

    fetched = await _fetch_source_urls(source, registry)
    new_config = dict(source["config"])
    new_config["urls"] = fetched
    registry.create_discovery_source(slug, source["display_name"], source["source_type"], new_config)
    return DiscoverySource(**registry.get_discovery_source(slug))


# ── personal working set (D4) ────────────────────────────────────────────

class WorkingSetRequest(BaseModel):
    entity_type: str  # "repo" | "database" | "filesystem"
    entity_slug: str
    hidden: bool


@router.post("/working-set")
async def set_working_set(body: WorkingSetRequest) -> dict:
    """Toggles whether a resource is hidden from the caller's working set —
    a personal view preference, separate from repo_dispositions' canonical
    judgment about the resource. Global for now (no per-person auth exists
    yet), but its own table so this stays true per-user later without
    touching disposition's model ("Scouting workflow redesign" plan, D4)."""
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.set_working_set_hidden(body.entity_type, body.entity_slug, body.hidden)
    return {"entity_type": body.entity_type, "entity_slug": body.entity_slug, "hidden": body.hidden}


@router.get("/disposition-history")
async def get_disposition_history(github_url: str) -> list[dict]:
    """Every disposition ever set for a repo, oldest first — backs the
    Scouting Disposition sub-tab's timeline view ("Scouting workflow
    redesign" plan, D6)."""
    from resource_explorer.registry import ProjectRegistry
    return ProjectRegistry().get_disposition_history(github_url)
