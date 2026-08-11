"""Project management endpoints — list, get, remove, refresh."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


# Disposition values that hide a repo from the sidebar by default — matches
# the frontend's _HIDDEN_DISPOSITIONS set exactly (index.html). "ignored" =
# passed on it early; "abandoned" = went further, then decided against it
# ("Scouting workflow redesign" plan, D3).
_HIDDEN_DISPOSITIONS = {"ignored", "abandoned"}


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
    disposition: str = "undecided"  # undecided | tracking | investigating | abandoned | ignored — see registry.py's repo_dispositions
    working_set_hidden: bool = False  # personal view filter, separate axis from disposition — see registry.py's resource_working_set


def _to_summary(p, registry=None) -> ProjectSummary:
    disposition = "undecided"
    working_set_hidden = False
    if registry is not None:
        disp = registry.get_disposition(p.github_url)
        if disp:
            disposition = disp["disposition"]
        working_set_hidden = registry.is_working_set_hidden("repo", p.slug)
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
        disposition=disposition,
        working_set_hidden=working_set_hidden,
    )


@router.get("/", response_model=list[ProjectSummary])
async def list_projects(include_ignored: bool = False, include_working_set_hidden: bool = False) -> list[ProjectSummary]:
    """Excludes `ignored`/`abandoned`-disposition repos and working-set-hidden
    repos by default — the sidebar's "Show hidden (N)" toggle passes both
    params to reveal everything. Reversible, not a hard delete either way
    (registry.py's repo_dispositions/resource_working_set rows are
    untouched) ("Discover repos to scout" plan, D10; "Scouting workflow
    redesign" plan, D3/D4)."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    summaries = [_to_summary(p, registry) for p in registry.list_all()]
    if not include_ignored:
        summaries = [s for s in summaries if s.disposition not in _HIDDEN_DISPOSITIONS]
    if not include_working_set_hidden:
        summaries = [s for s in summaries if not s.working_set_hidden]
    return summaries


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


class GroupSuggestion(BaseModel):
    org: str
    repo_slugs: list[str]
    repo_count: int
    suggested_display_name: str


@router.get("/groups/suggestions", response_model=list[GroupSuggestion])
async def suggest_groups() -> list[GroupSuggestion]:
    """Suggests — never auto-applies — groupings for currently-ungrouped
    repos that share a GitHub org. Importing multiple repos from the same
    org-scoped search at once (e.g. unitycatalog/unitycatalog,
    unitycatalog/unitycatalog-python, unitycatalog/unitycatalog-rs) is a
    strong signal they're the same logical project, but nothing at import
    time assigns a group automatically — grouping stays a deliberate,
    explicit action (matches how `set_project_group()` is only ever called
    from a real user click, never from `add()`/import code paths). Only
    orgs with 2+ ungrouped repos are surfaced; already-grouped repos are
    excluded so an accepted suggestion never gets re-suggested."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.github.client import GitHubClient

    registry = ProjectRegistry()
    by_org: dict[str, list[str]] = {}
    for p in registry.list_all():
        if getattr(p, "group_slug", ""):
            continue
        slug = GitHubClient._url_to_slug(p.github_url)
        if "/" not in slug:
            continue
        org = slug.split("/")[0]
        by_org.setdefault(org, []).append(p.slug)

    suggestions = [
        GroupSuggestion(org=org, repo_slugs=slugs, repo_count=len(slugs), suggested_display_name=org)
        for org, slugs in by_org.items()
        if len(slugs) >= 2
    ]
    suggestions.sort(key=lambda s: -s.repo_count)
    return suggestions


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


@router.get("/{slug}", response_model=ProjectSummary)
async def get_project(slug: str) -> ProjectSummary:
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return _to_summary(project, registry)


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
    # Last successful Coarse Profile refresh (IngestionPipeline.refresh_profile())
    # — the one Scouting-tier action that had no staleness signal at all
    # before this existed.
    last_profiled_at: str = ""
    is_published: bool = False
    # When egeria_publish last actually wrote to the catalog — distinct from
    # is_published (a point-in-time boolean derived from whether a GUID is
    # currently set). The data already existed (project_egeria_surveys.
    # published_at, one row per publish) but was never surfaced here before;
    # only the bare yes/no was shown.
    last_published_at: str = ""
    disposition: str = "undecided"
    disposition_reason: str = ""
    # Computed from archived/disabled/is_fork/is_template — "archived" >
    # "disabled" > "fork" > "template" > "active", first match wins.
    lifecycle_state: str = "active"
    homepage: str = ""
    security_and_analysis: dict = {}
    deployments_count: int = 0
    latest_deployment_at: str = ""
    latest_deployment_environment: str = ""
    latest_deployment_ref: str = ""


@router.get("/{slug}/scouting-overview", response_model=ScoutingOverview)
async def get_scouting_overview(slug: str) -> ScoutingOverview:
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    stats = registry.get_latest_project_stats(project.slug) or {}
    disp = registry.get_disposition(project.github_url) or {}
    latest_survey = registry.get_latest_egeria_survey(project.slug)

    lifecycle_state = "active"
    if stats.get("archived"):
        lifecycle_state = "archived"
    elif stats.get("disabled"):
        lifecycle_state = "disabled"
    elif stats.get("is_fork"):
        lifecycle_state = "fork"
    elif stats.get("is_template"):
        lifecycle_state = "template"

    try:
        security_and_analysis = json.loads(stats.get("security_and_analysis_json") or "{}")
    except (TypeError, ValueError):
        security_and_analysis = {}

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
        last_profiled_at=project.last_profiled_at,
        is_published=bool(project.egeria_asset_guid),
        last_published_at=(latest_survey or {}).get("published_at") or "",
        disposition=disp.get("disposition", "undecided"),
        disposition_reason=disp.get("reason", ""),
        lifecycle_state=lifecycle_state,
        homepage=stats.get("homepage") or "",
        security_and_analysis=security_and_analysis,
        deployments_count=stats.get("deployments_count") or 0,
        latest_deployment_at=stats.get("latest_deployment_at") or "",
        latest_deployment_environment=stats.get("latest_deployment_environment") or "",
        latest_deployment_ref=stats.get("latest_deployment_ref") or "",
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
        # Egeria-side Survey Definitions don't survive an Egeria database
        # reset — a real, recurring event in development, not a one-off
        # mistake. Without a fallback, that silently breaks Scouting Scan
        # entirely (including the git-stats refresh HealthSurveyor does at
        # scan time — the reason stale stats and a failed scan are usually
        # the same underlying problem, not two bugs) until someone notices
        # and manually re-authors the definition in Egeria. Scouting Scan
        # never actually needed Egeria to know *what* the two steps are,
        # only to name/bundle them — so fall back to running them directly.
        def _run_fallback():
            from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator
            return SurveyOrchestrator(registry).run(slug, steps=["repo_health", "repo_language"])

        try:
            survey_result = await asyncio.to_thread(_run_fallback)
        except Exception as fallback_exc:
            return ScoutingScanResult(
                status="error", slug=slug,
                error=f"{exc} (local fallback also failed: {fallback_exc})",
            )
        if survey_result.errors:
            return ScoutingScanResult(status="error", slug=slug, error="; ".join(survey_result.errors))
        return ScoutingScanResult(
            status="ok", slug=slug,
            message=(
                "Coarse scan complete — ran locally. Egeria's 'Repo Coarse Scout' "
                "Survey Definition wasn't found (likely an Egeria database reset); "
                "re-author it if you want scans to route through Egeria again."
            ),
        )

    errors = result.get("errors") or []
    if errors:
        return ScoutingScanResult(status="error", slug=slug, error="; ".join(errors))
    return ScoutingScanResult(status="ok", slug=slug, message="Coarse scan complete.")


class ProfileScanRequest(BaseModel):
    include_symbols: bool = False


class ProfileScanResult(BaseModel):
    status: str  # "ok" | "error"
    slug: str
    file_count: int = 0
    symbol_count: int = 0
    classified: bool = False
    classification_error: str | None = None
    message: str = ""
    error: str | None = None


@router.post("/{slug}/profile-scan", response_model=ProfileScanResult)
async def run_profile_scan(slug: str, req: ProfileScanRequest | None = None) -> ProfileScanResult:
    """Scouting's 'Profile' tab: download the zipball once and refresh
    project_file_inventory (+ project_data_profiles), optionally also
    project_code_symbols — decoupled from full pgvector re-ingestion.
    See IngestionPipeline.refresh_profile().

    Auto-chains the language_file_classification survey (repo_language +
    repo_file_classification + repo_file_structure) against the freshly
    refreshed file inventory, so "Refresh profile" actually shows a
    breakdown — previously the data was refreshed but nothing ever read it
    into a displayed result. Classification is best-effort: a failure here
    doesn't undo a successful refresh, it's just surfaced separately.
    """
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    include_symbols = bool(req.include_symbols) if req else False

    def _run():
        from resource_explorer.ingestion.pipeline import IngestionPipeline
        return IngestionPipeline().refresh_profile(
            project.slug,
            project.github_url,
            project.collections or [],
            subproject_path=project.subproject_path or None,
            include_symbols=include_symbols,
        )

    try:
        result = await asyncio.to_thread(_run)
    except Exception as exc:
        return ProfileScanResult(status="error", slug=slug, error=str(exc))

    registry.update_project_profiled_at(slug)

    message = f"{result.file_count} file(s) profiled"
    if include_symbols:
        message += f", {result.symbol_count} symbol(s) extracted"

    classified = False
    classification_error = None

    def _classify():
        from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_STEP_MAP
        from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator
        steps = REPO_ANALYSIS_STEP_MAP["language_file_classification"]
        return SurveyOrchestrator(registry).run(slug, steps=steps)

    try:
        survey_result = await asyncio.to_thread(_classify)
        if survey_result.errors:
            classification_error = "; ".join(survey_result.errors)
        else:
            classified = True
            message += " Classification updated."
    except Exception as exc:
        classification_error = str(exc)

    return ProfileScanResult(
        status="ok", slug=slug,
        file_count=result.file_count, symbol_count=result.symbol_count,
        classified=classified, classification_error=classification_error,
        message=message + ("" if message.endswith(".") else "."),
    )


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
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
    from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_STEP_MAP
    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    # action:"ingest" (currently just rag_ingestion) isn't a SurveyOrchestrator
    # step at all — it re-embeds content into pgvector via IncrementalIndexer,
    # not a survey. Checked before the step-map lookup below, same as
    # scheduler.py's own action:"publish" special-case.
    catalog_entry = next(
        (a for a in get_analyses("repo", include_egeria_live=False) if a["id"] == analysis_id), None,
    )
    if catalog_entry and catalog_entry.get("action") == "ingest":
        def _run_ingest():
            from resource_explorer.ingestion.incremental import IncrementalIndexer
            from resource_explorer.query_cache import QueryCache
            IncrementalIndexer().refresh(project)
            QueryCache().invalidate_project(slug)

        try:
            await asyncio.to_thread(_run_ingest)
        except Exception as exc:
            return AnalysisRunResult(status="error", slug=slug, analysis_id=analysis_id, error=str(exc))
        return AnalysisRunResult(status="ok", slug=slug, analysis_id=analysis_id, message="Re-ingested into pgvector.")

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

    def _do_remove():
        store = MultiCollectionStore()
        for collection in project.collections:
            try:
                store.drop_collection(collection)
            except Exception:
                # A stale/never-created collection (e.g. a broken registration
                # that errored before ingestion completed) shouldn't block
                # removing the registry row itself — best-effort, matching
                # OrgImporter's stats-fetch-failure precedent elsewhere.
                pass
        registry.remove(slug)

    # Blocking pgvector work — every other route in this file already runs
    # its blocking work via asyncio.to_thread; this one didn't, and a slow/
    # unreachable pgvector call here blocked the whole event loop (found
    # live: a delete on a broken registration hung indefinitely).
    await asyncio.to_thread(_do_remove)
    return {"removed": slug}


# ── sub-resources — the "Select"/"Catalog" stages of the repo scope-
# narrowing funnel (docs/repo-scope-narrowing-funnel.md, D2/D3/D4). Repo
# only for Phase 1; the underlying registry table is already generic
# across resource types (resource_type='repo' here) for when database/
# filesystem catch up. ───────────────────────────────────────────────────

class SubResourceRow(BaseModel):
    locator: str
    kind: str
    cataloged_at: str
    egeria_guid: str = ""


@router.get("/{slug}/sub-resources", response_model=list[SubResourceRow])
async def list_sub_resources(slug: str) -> list[SubResourceRow]:
    """What's currently tracked locally for this repo — backs the selection
    UI's "already cataloged" state so re-opening the panel later shows
    prior selections (D4 — catalog is repeatable, not a one-time gate)."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if not registry.get(slug):
        raise HTTPException(status_code=404, detail=f"Repository '{slug}' not found")
    rows = registry.list_sub_resources("repo", slug)
    return [
        SubResourceRow(
            locator=r["locator"], kind=r["kind"],
            cataloged_at=r["cataloged_at"], egeria_guid=r.get("egeria_guid") or "",
        )
        for r in rows
    ]


class SubResourceCatalogItem(BaseModel):
    locator: str
    kind: str  # 'file' | 'folder'


class SubResourceCatalogRequest(BaseModel):
    items: list[SubResourceCatalogItem]
    publish_to_egeria: bool = True  # default both (local + Egeria); False = sandbox-mode escape hatch


class SubResourceCatalogResult(BaseModel):
    cataloged: list[str]              # locators tracked locally (incl. auto-included ancestors)
    published: dict[str, str] = {}    # locator -> Egeria guid; empty unless publish_to_egeria


@router.post("/{slug}/sub-resources/catalog", response_model=SubResourceCatalogResult)
async def catalog_sub_resources(slug: str, body: SubResourceCatalogRequest) -> SubResourceCatalogResult:
    """Track the selected sub-resources locally (always), and optionally
    publish them to Egeria as real FileFolder/DataFile assets in the same
    action (D3 — default both; unchecking publish_to_egeria is the
    sandbox-mode escape hatch). Repeatable (D4): re-cataloging an
    already-tracked locator is a no-op that never disturbs its
    egeria_guid. Every selected file's ancestor folders are auto-included
    even if not explicitly selected, mirroring SubResourceSurveyor's own
    ancestor-folder guarantee — NestedFile strictly requires a FileFolder
    parent, so an inconsistent selection would otherwise silently fail to
    publish."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.egeria_publisher import EgeriaConnectionError, EgeriaPublisher
    from resource_explorer.surveyors.sub_surveyors import ancestor_folder_paths

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Repository '{slug}' not found")
    if not body.items:
        raise HTTPException(status_code=400, detail="No items given to catalog")

    # Snapshot each item's owners/dates from the current findings into the
    # local row (denormalized — publish_sub_resources() shouldn't need to
    # re-join back to findings that a later survey run might supersede).
    findings_by_path: dict[str, dict] = {}
    for f in registry.query_findings(slug, "repo_sub_resource_survey"):
        detail = {}
        if f.get("detail_json"):
            try:
                detail = json.loads(f["detail_json"])
            except (TypeError, ValueError):
                detail = {}
        findings_by_path[detail.get("path", "")] = detail

    selected_kind_by_locator: dict[str, str] = {item.locator: item.kind for item in body.items}
    for item in body.items:
        if item.kind != "file":
            continue
        for ancestor in ancestor_folder_paths(item.locator):
            selected_kind_by_locator.setdefault(ancestor, "folder")

    cataloged: list[str] = []
    for locator in sorted(selected_kind_by_locator):
        registry.catalog_sub_resource(
            "repo", slug, locator, selected_kind_by_locator[locator],
            source_finding="repo_sub_resource_survey",
            detail=findings_by_path.get(locator),
        )
        cataloged.append(locator)

    published: dict[str, str] = {}
    if body.publish_to_egeria:
        if not project.egeria_asset_guid:
            raise HTTPException(
                status_code=409,
                detail="Repo has no Egeria asset yet — publish the repo itself first before publishing sub-resources.",
            )
        publisher = EgeriaPublisher(registry=registry)
        try:
            published = await asyncio.to_thread(
                publisher.publish_sub_resources,
                slug, project.github_url, project.egeria_asset_guid, cataloged,
            )
        except EgeriaConnectionError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

    return SubResourceCatalogResult(cataloged=cataloged, published=published)


@router.delete("/{slug}/sub-resources")
async def uncatalog_sub_resource(slug: str, locator: str = "") -> dict:
    """Reversible (D4) — removes RE's local tracking record only; does not
    touch anything already published to Egeria. locator is a query param
    (not a path segment) so the root locator ("") is representable."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if not registry.get(slug):
        raise HTTPException(status_code=404, detail=f"Repository '{slug}' not found")
    registry.uncatalog_sub_resource("repo", slug, locator)
    return {"slug": slug, "locator": locator, "uncataloged": True}


# ── scoped analysis — the "Narrow" stage of the repo scope-narrowing funnel
# (docs/repo-scope-narrowing-funnel.md, D5/D6). Runs a corpus-shaped analysis
# against one cataloged sub-resource instead of the whole repo; gated by
# is_shape_compatible() so a whole_resource_only (or shape-mismatched)
# analysis can never be requested scoped. ──────────────────────────────────

class ScopedAnalysisRequest(BaseModel):
    locator: str  # must already be tracked via /sub-resources/catalog


@router.post("/{slug}/sub-resources/analyses/{analysis_id}/run", response_model=AnalysisRunResult)
async def run_scoped_analysis(slug: str, analysis_id: str, body: ScopedAnalysisRequest) -> AnalysisRunResult:
    """Runs one analysis's step(s) scoped to a single cataloged sub-resource
    (SurveyOrchestrator.run(steps=..., scope_locator=...)) rather than the
    whole repo. Only reachable for analyses whose target_shape is compatible
    with the sub-resource's kind (D6) — mirrors run_single_analysis above,
    plus the scope gate and scope_locator passthrough."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses, is_shape_compatible
    from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_STEP_MAP
    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    sub_resource = next(
        (r for r in registry.list_sub_resources("repo", slug) if r["locator"] == body.locator), None,
    )
    if not sub_resource:
        raise HTTPException(
            status_code=404,
            detail=f"'{body.locator}' is not a cataloged sub-resource of '{slug}' — "
                   "catalog it first via POST /sub-resources/catalog.",
        )

    catalog_entry = next(
        (a for a in get_analyses("repo", include_egeria_live=False) if a["id"] == analysis_id), None,
    )
    if not catalog_entry:
        raise HTTPException(status_code=400, detail=f"Unknown analysis '{analysis_id}'")

    target_shape = catalog_entry.get("target_shape", "whole_resource_only")
    if not is_shape_compatible(target_shape, sub_resource["kind"]):
        raise HTTPException(
            status_code=400,
            detail=f"Analysis '{analysis_id}' (target_shape={target_shape}) cannot be scoped "
                   f"to a '{sub_resource['kind']}' sub-resource.",
        )

    steps = REPO_ANALYSIS_STEP_MAP.get(analysis_id)
    if not steps:
        raise HTTPException(
            status_code=400,
            detail=f"Analysis '{analysis_id}' has no mapped survey step(s).",
        )

    def _run():
        return SurveyOrchestrator(registry).run(slug, steps=steps, scope_locator=body.locator)

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
        message=f"{len(result.annotations)} annotation(s), scoped to '{body.locator}'.",
    )


@router.get("/{slug}/sub-resources/analyses/{analysis_id}/results")
async def get_scoped_analysis_results(slug: str, analysis_id: str, locator: str) -> dict:
    """Latest structured results for one analysis, scoped to a single
    cataloged sub-resource — reads the generic project_analysis_metrics
    table filtered by scope_locator. Only meaningful for the corpus-shaped
    kinds that persist scoped metrics today (api_structure, data_file_
    profiling — see repo_survey_definition_adapter.STEP_REGISTRY's
    accepts_scope_locator flag); other analysis_ids return an empty dict
    since nothing was ever persisted under a non-empty scope_locator for
    them (they're whole_resource_only and D6-gated out of this route by
    run_scoped_analysis above)."""
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    # analysis_id (analysis_catalog.yaml) -> project_analysis_metrics `kind`
    # discriminator — same mapping used to write these rows in the
    # surveyors themselves (upsert_metric(slug, kind, ...)).
    metrics_kind_by_analysis_id = {
        "api_structure": "api_structure",
        "data_file_profiling": "data_profile",
    }
    kind = metrics_kind_by_analysis_id.get(analysis_id)
    if not kind:
        return {}
    return registry.query_metrics(slug, kind, scope_locator=locator)
