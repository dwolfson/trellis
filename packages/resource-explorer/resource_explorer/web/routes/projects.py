"""Project management endpoints — list, get, remove, refresh."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ProjectSummary(BaseModel):
    slug: str
    display_name: str
    github_url: str
    description: str
    status: str
    collections: list[str]
    last_indexed_at: str
    last_commit_sha: str
    group_slug: str = ""
    last_surveyed_at: str = ""  # "" = never surveyed (coarse scan or deep)
    is_published: bool = False  # egeria_asset_guid set — boolean only, not the raw GUID


def _to_summary(p) -> ProjectSummary:
    return ProjectSummary(
        slug=p.slug,
        display_name=p.display_name,
        github_url=p.github_url,
        description=p.description,
        status=p.status.value,
        collections=p.collections,
        last_indexed_at=p.last_indexed_at,
        last_commit_sha=p.last_commit_sha,
        group_slug=getattr(p, "group_slug", "") or "",
        last_surveyed_at=getattr(p, "last_surveyed_at", "") or "",
        is_published=bool(getattr(p, "egeria_asset_guid", "") or ""),
    )


@router.get("/", response_model=list[ProjectSummary])
async def list_projects() -> list[ProjectSummary]:
    from resource_explorer.registry import ProjectRegistry
    return [_to_summary(p) for p in ProjectRegistry().list_all()]


class GroupStats(BaseModel):
    project_count: int
    database_count: int
    filesystem_count: int
    stars: int
    forks: int
    watchers: int
    open_issues: int
    commits_30d: int
    commits_90d: int
    contributors_count: int
    languages: dict[str, int]
    db_schema_count: int
    db_table_count: int
    db_column_count: int
    fs_file_count: int
    fs_data_file_count: int


class GroupSummary(BaseModel):
    slug: str
    display_name: str
    description: str = ""
    projects: list[str]
    databases: list[str]
    filesystems: list[str]
    stats: GroupStats


class GroupCreate(BaseModel):
    slug: str
    display_name: str
    description: str = ""


class GroupAssign(BaseModel):
    resource_type: str  # "repo", "database", "filesystem"
    group_slug: str     # "" clears the assignment


@router.get("/groups", response_model=list[GroupSummary])
async def list_groups() -> list[GroupSummary]:
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    out = []
    for g in registry.list_groups():
        repos = registry.list_projects_in_group(g.slug)
        dbs = registry.list_databases_in_group(g.slug)
        fss = registry.list_filesystems_in_group(g.slug)
        stats = registry.get_group_aggregate_stats(g.slug)
        out.append(GroupSummary(
            slug=g.slug, display_name=g.display_name, description=g.description,
            projects=[m.slug for m in repos],
            databases=[m.slug for m in dbs],
            filesystems=[m.slug for m in fss],
            stats=GroupStats(**stats),
        ))
    return out


@router.post("/groups", response_model=GroupSummary)
async def create_group(body: GroupCreate) -> GroupSummary:
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    registry.create_group(body.slug, body.display_name, body.description)
    group = registry.get_group(body.slug)
    stats = registry.get_group_aggregate_stats(group.slug)
    return GroupSummary(
        slug=group.slug, display_name=group.display_name, description=group.description,
        projects=[], databases=[], filesystems=[], stats=GroupStats(**stats),
    )


@router.delete("/groups/{slug}")
async def delete_group(slug: str) -> dict:
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if not registry.get_group(slug):
        raise HTTPException(status_code=404, detail=f"Group '{slug}' not found")
    unassigned = registry.delete_group(slug)
    return {"removed": slug, "resources_unassigned": unassigned}


@router.post("/{slug}/group")
async def assign_group(slug: str, body: GroupAssign) -> dict:
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    
    if body.group_slug and not registry.get_group(body.group_slug):
        raise HTTPException(status_code=404, detail=f"Group '{body.group_slug}' not found")
        
    if body.resource_type == "repo":
        if not registry.get(slug):
            raise HTTPException(status_code=404, detail=f"Repository '{slug}' not found")
        registry.set_project_group(slug, body.group_slug)
    elif body.resource_type == "database":
        if not registry.get_database(slug):
            raise HTTPException(status_code=404, detail=f"Database '{slug}' not found")
        registry.set_database_group(slug, body.group_slug)
    elif body.resource_type == "filesystem":
        if not registry.get_filesystem(slug):
            raise HTTPException(status_code=404, detail=f"Filesystem '{slug}' not found")
        registry.set_filesystem_group(slug, body.group_slug)
    else:
        raise HTTPException(status_code=400, detail=f"Invalid resource type '{body.resource_type}'")
        
    return {"slug": slug, "resource_type": body.resource_type, "group_slug": body.group_slug}


class DiscoveredRepo(BaseModel):
    full_name: str
    html_url: str
    description: str = ""
    stars: int = 0
    language: str = ""
    already_registered: bool = False


class ImportRepoSpec(BaseModel):
    github_url: str
    display_name: str
    description: str = ""


class ImportRequest(BaseModel):
    repos: list[ImportRepoSpec]
    group_slug: str = ""


class ImportResponse(BaseModel):
    queued: int
    skipped: list[str]  # github_urls already registered, not re-queued


@router.get("/discover/{org}", response_model=list[DiscoveredRepo])
async def discover_org_repos(
    org: str, include_forks: bool = False, include_archived: bool = False
) -> list[DiscoveredRepo]:
    """Read-only — lists an org's repos via the GitHub API, flagging which
    are already registered. Does not touch the registry."""
    from github import GithubException

    from resource_explorer.github.client import GitHubClient
    from resource_explorer.registry import ProjectRegistry

    def _list():
        return GitHubClient().list_org_repos(org, include_forks=include_forks, include_archived=include_archived)

    try:
        repos = await asyncio.to_thread(_list)
    except GithubException as exc:
        if exc.status == 404:
            raise HTTPException(status_code=404, detail=f"GitHub org '{org}' not found") from exc
        if exc.status in (401, 403):
            raise HTTPException(
                status_code=502,
                detail="GitHub authentication/rate-limit error — check GITHUB_TOKEN in .env",
            ) from exc
        raise HTTPException(status_code=502, detail=f"GitHub API error: {exc}") from exc

    registry = ProjectRegistry()
    out = []
    for r in repos:
        out.append(DiscoveredRepo(
            full_name=r["full_name"], html_url=r["html_url"], description=r["description"],
            stars=r["stars"], language=r["language"],
            already_registered=registry.get_by_github_url(r["html_url"]) is not None,
        ))
    out.sort(key=lambda r: r.stars, reverse=True)
    return out


@router.post("/discover/{org}/import", response_model=ImportResponse)
async def import_org_repos(org: str, body: ImportRequest) -> ImportResponse:
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
            args=(org, to_queue, body.group_slug),
            daemon=True,
            name=f"resource-explorer-org-import-{org}",
        )
        t.start()

    return ImportResponse(queued=len(to_queue), skipped=skipped)


@router.get("/{slug}", response_model=ProjectSummary)
async def get_project(slug: str) -> ProjectSummary:
    from resource_explorer.registry import ProjectRegistry
    project = ProjectRegistry().get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return _to_summary(project)


class ScoutingOverview(BaseModel):
    """Light, fast-to-render Scouting-tier facts — GitHub API-derived only
    (no Enrichment data, which isn't available yet at this lifecycle stage —
    see the plan's discussion of purpose vs. description). Deliberately
    thin: "enough to answer 'should I analyze this further?'", not the deep
    survey report (still reachable via the "View full report" link, unchanged)."""
    slug: str
    display_name: str
    github_url: str
    description: str = ""       # GitHub's own repo description, not Enrichment's purpose
    primary_language: str = ""
    stars: int = 0
    forks: int = 0
    contributors_count: int = 0
    last_pushed_at: str = ""
    repo_size_kb: int = 0
    last_surveyed_at: str = ""
    is_published: bool = False


@router.get("/{slug}/scouting-overview", response_model=ScoutingOverview)
async def get_scouting_overview(slug: str) -> ScoutingOverview:
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    stats = registry.get_latest_project_stats(project.slug) or {}
    return ScoutingOverview(
        slug=project.slug,
        display_name=project.display_name,
        github_url=project.github_url,
        description=project.description,
        primary_language=stats.get("primary_language") or "",
        stars=stats.get("stars") or 0,
        forks=stats.get("forks") or 0,
        contributors_count=stats.get("contributors_count") or 0,
        last_pushed_at=stats.get("last_pushed_at") or "",
        repo_size_kb=stats.get("repo_size_kb") or 0,
        last_surveyed_at=project.last_surveyed_at,
        is_published=bool(project.egeria_asset_guid),
    )


class ScoutingScanResult(BaseModel):
    status: str  # "ok" | "error"
    slug: str
    message: str = ""
    error: str | None = None


@router.post("/{slug}/scouting-scan", response_model=ScoutingScanResult)
async def run_scouting_scan(slug: str) -> ScoutingScanResult:
    """Fast, API-only coarse scan (repo stats + language classification) —
    runs the "Repo Coarse Scout" Survey Definition via the same executor
    Discovery's manual "Run" button uses. Local-only by default, no
    auto-publish, matching the existing convention that publish is always
    a separate, deliberate action."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        REPO_COARSE_SCOUT_SURVEY_DEFINITION_QN,
    )
    from resource_explorer.surveyors.survey_definition_executor import (
        SurveyDefinitionExecutorError,
        run_survey_definition,
    )
    from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReaderError

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    def _run():
        return run_survey_definition(
            "repo", slug, registry=registry,
            survey_definition_ref=REPO_COARSE_SCOUT_SURVEY_DEFINITION_QN,
        )

    try:
        result = await asyncio.to_thread(_run)
    except (SurveyDefinitionExecutorError, SurveyDefinitionReaderError) as exc:
        return ScoutingScanResult(status="error", slug=slug, error=str(exc))

    errors = result.get("errors") or []
    if errors:
        return ScoutingScanResult(status="error", slug=slug, error="; ".join(errors))
    return ScoutingScanResult(status="ok", slug=slug, message="Coarse scan complete.")


class AnalysisRunResult(BaseModel):
    status: str  # "ok" | "error"
    slug: str
    analysis_id: str
    message: str = ""
    error: str | None = None


@router.post("/{slug}/analyses/{analysis_id}/run", response_model=AnalysisRunResult)
async def run_single_analysis(slug: str, analysis_id: str) -> AnalysisRunResult:
    """Runs only the sub-surveyor step(s) for one named repo analysis, not
    the whole 10-surveyor survey — the per-card "Run" action in Analysis/
    Assessment. Reuses the same analysis_id -> step(s) map the scheduler's
    per-analysis-id dispatch uses (repo_survey_definition_adapter.py)."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_STEP_MAP
    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    steps = REPO_ANALYSIS_STEP_MAP.get(analysis_id)
    if not steps:
        raise HTTPException(
            status_code=400,
            detail=f"Analysis '{analysis_id}' has no mapped survey step(s) — "
                   "either it's a publish action (not a survey) or an unknown id.",
        )

    def _run():
        return SurveyOrchestrator(registry).run(slug, steps=steps)

    try:
        result = await asyncio.to_thread(_run)
    except Exception as exc:
        return AnalysisRunResult(status="error", slug=slug, analysis_id=analysis_id, error=str(exc))

    if result.errors:
        return AnalysisRunResult(
            status="error", slug=slug, analysis_id=analysis_id, error="; ".join(result.errors),
        )
    return AnalysisRunResult(
        status="ok", slug=slug, analysis_id=analysis_id,
        message=f"{len(result.annotations)} annotation(s).",
    )


@router.get("/{slug}/analyses/{analysis_id}/results")
async def get_analysis_results(slug: str, analysis_id: str) -> dict:
    """Latest structured results for one repo analysis — the real
    per-analysis results view (Phase B), replacing "check the full report
    for details." Raw dict, not a Pydantic model — shape genuinely differs
    per analysis_id (dependency ecosystems vs. security check list vs. ...),
    see REPO_ANALYSIS_RESULTS_MAP's individual reader functions."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_RESULTS_MAP

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    entry = REPO_ANALYSIS_RESULTS_MAP.get(analysis_id)
    if not entry:
        raise HTTPException(
            status_code=400,
            detail=f"Analysis '{analysis_id}' has no results view — "
                   "either it's scouting-tier (see Scouting instead) or an unknown id.",
        )
    results_reader, _ = entry
    return results_reader(registry, slug)


@router.get("/{slug}/analyses/{analysis_id}/trend")
async def get_analysis_trend(slug: str, analysis_id: str) -> dict:
    """Raw JSON trend data for one repo analysis — {runs: [{surveyed_at,
    value, ...}, ...]}, matching the existing survey_history endpoint's
    raw-JSON-not-Plotly-figure convention (D6) rather than building a new
    server-side Plotly figure per analysis type."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_RESULTS_MAP

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    entry = REPO_ANALYSIS_RESULTS_MAP.get(analysis_id)
    if not entry:
        raise HTTPException(
            status_code=400,
            detail=f"Analysis '{analysis_id}' has no trend view — "
                   "either it's scouting-tier (see Scouting instead) or an unknown id.",
        )
    _, trend_reader = entry
    return {"runs": trend_reader(registry, slug)}


class RefreshResult(BaseModel):
    status: str          # "ok" | "error"
    slug: str
    message: str = ""
    error: str | None = None


@router.post("/{slug}/refresh", response_model=RefreshResult)
async def refresh_project(slug: str) -> RefreshResult:
    """Incremental re-index + data profiling, runs synchronously in a thread."""
    from resource_explorer.registry import ProjectRegistry
    project = ProjectRegistry().get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    output_lines: list[str] = []

    def _do_refresh():
        import io, sys
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            from resource_explorer.ingestion.incremental import IncrementalIndexer
            from resource_explorer.query_cache import QueryCache
            IncrementalIndexer().refresh(project)
            QueryCache().invalidate_project(slug)
        finally:
            sys.stdout = old_stdout
            output_lines.extend(buf.getvalue().splitlines())

    try:
        await asyncio.to_thread(_do_refresh)
    except Exception as exc:
        return RefreshResult(status="error", slug=slug, error=str(exc))

    msg = "; ".join(output_lines) if output_lines else "Done"
    return RefreshResult(status="ok", slug=slug, message=msg)


@router.delete("/{slug}")
async def remove_project(slug: str) -> dict:
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.vector_store_pg import MultiCollectionStore
    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    store = MultiCollectionStore()
    for collection in project.collections:
        store.drop_collection(collection)
    registry.remove(slug)
    return {"removed": slug}
