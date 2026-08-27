"""Project management endpoints — list, get, remove, refresh."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger(__name__)
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
    # Set when this repo's cached Egeria GUID was found not to exist
    # (resource_explorer/egeria_linkage.py). Carried here because this card is
    # where the "Published to Egeria" badge is shown, and that badge is actively
    # misleading while the link is broken — it reports a catalog entry RE can no
    # longer reach.
    egeria_link_stale: bool = False
    egeria_link_stale_guid: str = ""


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

    linkage = registry.get_egeria_linkage("repo", project.slug) or {}

    return ScoutingOverview(
        egeria_link_stale=linkage.get("status") == "stale",
        egeria_link_stale_guid=linkage.get("stale_guid", ""),
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
        # Prefer the surveyed answer over GitHub's raw field. HomepageSurveyor
        # writes projects.homepage_url having tried GitHub's homepage first, then
        # the packaging manifests, then the README, then the repo URL — so it is
        # either the same value or a better one. stats.homepage remains the
        # fallback for repos surveyed before that step existed.
        homepage=(project.homepage_url or stats.get("homepage") or ""),
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


class ScoutingScanStarted(BaseModel):
    status: str = "started"
    slug: str
    activity_id: str


def _run_scouting_scan_sync(slug: str, registry) -> ScoutingScanResult:
    """The actual scan work, shared by the background-thread path below and
    kept as a plain sync function (no FastAPI/asyncio coupling) so it's
    trivially callable from a daemon thread with its own fresh registry
    connection — same convention as org_importer.py's _run_import_batch."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        REPO_COARSE_SCOUT_SURVEY_DEFINITION_QN,
    )
    from resource_explorer.surveyors.survey_definition_executor import (
        SurveyDefinitionExecutorError,
        run_survey_definition,
    )
    from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReaderError

    try:
        # fast=True — Coarse Scout's whole premise is being the cheap, fast
        # tier; without this, HealthSurveyor's stats refresh makes one
        # GitHub API call per commit in the last 90 days (a confirmed real
        # slowness bug for active repos, easily several minutes). See
        # StepInfo.accepts_fast / HealthSurveyor.__init__'s own docstrings.
        result = run_survey_definition(
            "repo", slug, registry=registry,
            survey_definition_ref=REPO_COARSE_SCOUT_SURVEY_DEFINITION_QN,
            fast=True,
        )
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
        try:
            from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator
            survey_result = SurveyOrchestrator(registry).run(
                slug, steps=["repo_health", "repo_language"], fast=True,
            )
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


def _run_scouting_scan_background(slug: str, activity_id: str) -> None:
    """Runs in a daemon thread — nothing here returns to an HTTP response.
    Mirrors org_importer.py's _run_import_batch background-thread pattern:
    its own fresh ProjectRegistry() (SQLite connections aren't shared
    across threads), terminal status written back onto the same activity_id
    the route created up front via registry.update_activity_status()."""
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    try:
        result = _run_scouting_scan_sync(slug, registry)
    except Exception as exc:  # pragma: no cover — genuinely unexpected, not a survey-step error
        log.exception("Scouting Scan background thread crashed for %s", slug)
        registry.update_activity_status(activity_id, "error", summary=f"Scouting Scan crashed: {exc}")
        return
    registry.update_activity_status(
        activity_id, result.status, summary=result.message or result.error or "",
    )


@router.post("/{slug}/scouting-scan", response_model=ScoutingScanStarted)
async def run_scouting_scan(slug: str) -> ScoutingScanStarted:
    """Fast, API-only coarse scan (repo stats + language classification) —
    runs the "Repo Coarse Scout" Survey Definition via the same executor
    Discovery's manual "Run" button uses. Local-only by default, no
    auto-publish, matching the existing convention that publish is always
    a separate, deliberate action.

    Fire-and-forget (background thread), not synchronous — a real, observed
    problem: for an active repo, the pre-fast-flag version of this route
    could block for 10+ minutes with zero visibility (see
    _run_scouting_scan_sync's own fast=True comment for the actual root
    cause). The route now returns immediately once the scan is queued; the
    frontend polls GET /api/activity/{activity_id} for status, same
    Activity Log every other operation in this codebase already writes to —
    matches org_importer.py's _run_import_batch precedent exactly, just for
    a single-repo scan instead of a batch."""
    import threading

    from resource_explorer.activity_logger import log_survey
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    activity_id = log_survey(
        registry, entity_type="repo", entity_slug=slug,
        entity_name=project.display_name, entity_location=project.github_url,
        intent="scouting", status="running",
        summary=f"Scouting Scan running for {project.display_name}…",
    )

    t = threading.Thread(
        target=_run_scouting_scan_background,
        args=(slug, activity_id),
        daemon=True, name="resource-explorer-scouting-scan",
    )
    t.start()

    return ScoutingScanStarted(slug=slug, activity_id=activity_id)


class QuestionChecklistEntry(BaseModel):
    question: str
    stage: str  # single Funnel Stage, may be slash-combined (e.g. "Analysis/Enrichment")
    perspectives: list[str] = []
    kind: str  # analysis | direct | registry | human | chart | gap | partial | mixed | unknown
    analysis_ids: list[str] = []
    note: str = ""
    answering_mechanism: str = ""
    # None = not applicable (direct/registry/human/chart/gap kinds — no RE
    # analysis backs these, so there's nothing to check); True/False only
    # for analysis/partial/mixed kinds, computed best-effort per resource.
    has_data: bool | None = None
    purposes: list[str] = []
    # Why this entry is in the result: which Perspectives/Purposes matched
    # and whether Purpose promoted it. See docs/context-compilation-design.md
    # §11 -- the derivation is the explanation with content, distinct from
    # "what got shown".
    derivation: dict = {}


class QuestionChecklist(BaseModel):
    phase: str
    perspectives: list[str] = []
    purposes: list[str] = []
    questions: list[QuestionChecklistEntry] = []


def _question_has_data(registry, slug: str, analysis_ids: list[str]) -> bool | None:
    """Best-effort "has RE actually run this for this resource" check —
    True as soon as ANY of the question's mapped analysis_ids has data,
    False if none do, None if the question has no analysis_ids at all
    (nothing to check). repository_health has no results_reader in
    REPO_ANALYSIS_RESULTS_MAP (repo_survey_definition_adapter.py) — it's
    checked via project_stats directly instead, the same signal
    scouting-overview itself reads. Every reader call is wrapped: a
    results_reader raising must never break the whole checklist."""
    if not analysis_ids:
        return None
    from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_RESULTS_MAP

    for analysis_id in analysis_ids:
        if analysis_id == "repository_health":
            if registry.get_latest_project_stats(slug):
                return True
            continue
        entry = REPO_ANALYSIS_RESULTS_MAP.get(analysis_id)
        if not entry:
            continue
        results_reader, _ = entry
        try:
            data = results_reader(registry, slug)
        except Exception:
            continue
        if data and (not isinstance(data, dict) or any(v for v in data.values())):
            return True
    return False


@router.get("/{slug}/scouting-questions", response_model=QuestionChecklist)
async def get_scouting_questions(
    slug: str,
    phase: str = "scouting",
    perspectives: str | None = None,
    purposes: str | None = None,
) -> QuestionChecklist:
    """Per-phase Question checklist — which of the authored Scouting
    questions (docs/dr-egeria/resource_questions.csv, via
    question_catalog_reader.py) this phase raises or can answer, filtered
    by the active Perspective set (comma-separated query param, matching
    the UI's activePerspectives multi-select — see index.html's
    togglePerspective()), with a computed has_data flag for
    analysis/partial/mixed-kind questions."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.question_catalog_reader import get_questions

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    persp_list = [p.strip() for p in (perspectives or "").split(",") if p.strip()]
    purp_list = [p.strip() for p in (purposes or "").split(",") if p.strip()]
    entries = get_questions(
        "repo", phase=phase,
        perspectives=persp_list or None,
        purposes=purp_list or None,
    )

    checklist = []
    for e in entries:
        answering = e["answering"]
        has_data = (
            _question_has_data(registry, slug, answering["analysis_ids"])
            if answering["kind"] in ("analysis", "partial", "mixed")
            else None
        )
        checklist.append(QuestionChecklistEntry(
            question=e["question"],
            stage=e["stage"],
            perspectives=e["perspectives"],
            kind=answering["kind"],
            analysis_ids=answering["analysis_ids"],
            note=answering["note"],
            answering_mechanism=e.get("answering_mechanism", ""),
            has_data=has_data,
            purposes=e.get("purposes", []),
            derivation=e.get("derivation", {}),
        ))

    return QuestionChecklist(
        phase=phase, perspectives=persp_list, purposes=purp_list, questions=checklist
    )


# POST /{slug}/profile-scan was retired 2026-08-20. It refreshed
# project_file_inventory/project_data_profiles from a zipball and auto-chained
# the language-classification survey — all of which is now done by the
# repo_file_inventory survey step and the "Coarse Profile Survey" Survey
# Definition, reachable from Scouting's Survey sub-tab like any other survey.
#
# It had no caller: no UI code invoked it, and the scheduler calls
# IngestionPipeline.refresh_profile() directly rather than going through HTTP.
# It was also the last thing referring to a "Profile tab" that was never built.
# refresh_profile() itself is untouched and still used by the scheduler and
# IncrementalIndexer — only this HTTP surface is gone.


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
        from resource_explorer.activity_logger import log_analysis_run

        def _run_ingest():
            from resource_explorer.ingestion.incremental import IncrementalIndexer
            from resource_explorer.query_cache import QueryCache
            IncrementalIndexer().refresh(project)
            QueryCache().invalidate_project(slug)

        try:
            await asyncio.to_thread(_run_ingest)
        except Exception as exc:
            log_analysis_run(registry, "repo", slug, project.display_name, "error", str(exc), analysis_id)
            return AnalysisRunResult(status="error", slug=slug, analysis_id=analysis_id, error=str(exc))
        log_analysis_run(registry, "repo", slug, project.display_name, "ok", "Re-ingested into pgvector.", analysis_id)
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

    # Real, live-reported gap (2026-08-24): this route never wrote to
    # activity_log at all, so Analyses cards had no last-run signal —
    # unlike Survey Definition cards, which do (survey_definitions.py's
    # run route). log_analysis_run below closes that; see
    # registry.get_analysis_last_run()'s docstring for the read side.
    from resource_explorer.activity_logger import log_analysis_run

    try:
        result = await asyncio.to_thread(_run)
    except Exception as exc:
        log_analysis_run(registry, "repo", slug, project.display_name, "error", str(exc), analysis_id)
        return AnalysisRunResult(status="error", slug=slug, analysis_id=analysis_id, error=str(exc))

    if result.errors:
        error = "; ".join(result.errors)
        log_analysis_run(registry, "repo", slug, project.display_name, "error", error, analysis_id)
        return AnalysisRunResult(status="error", slug=slug, analysis_id=analysis_id, error=error)
    summary = f"{len(result.annotations)} annotation(s)."

    # Auto-publish, gated the same way survey_definition_executor.py's Survey
    # Definition path is (has_assigned_egeria_project) — this is the "actual
    # ask" this gating pass exists for: an Assessment/Analysis "Run →" against
    # an assigned resource now reaches Egeria without a separate manual
    # Publish click, same as a Survey Definition run already does. Scoped to
    # exactly the steps that just ran (this `result`, not a fresh full
    # survey), same as the manual Publish button's own `steps` scoping — so
    # last-published attribution (get_last_published_annotation_types) stays
    # accurate to what actually ran. Publish failure must not turn an
    # otherwise-successful survey into a reported error: the findings are
    # real and stored either way.
    # Three-state, not a bool: None (never attempted — unassigned or no
    # annotations) and False (attempted, failed) both keep the card's ☁
    # Publish button visible as the only/recovery path; True hides it, since
    # the whole reason to hide it is "nothing left to do here."
    published = None
    if result.annotations and registry.has_assigned_egeria_project("repo", slug):
        try:
            from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
            EgeriaPublisher(registry=registry).publish(result)
            published = True
        except Exception as exc:
            published = False
            summary += f" (⚠ auto-publish to Egeria failed: {exc})"
            log.warning("Auto-publish failed for %s/%s: %s", slug, analysis_id, exc)

    log_analysis_run(registry, "repo", slug, project.display_name, "ok", summary, analysis_id, published=published)
    return AnalysisRunResult(
        status="ok", slug=slug, analysis_id=analysis_id,
        message=summary,
    )


@router.get("/{slug}/analyses/last-activity")
async def get_analyses_last_activity(slug: str) -> dict[str, dict]:
    """{analysis_id: {last_run_at, last_run_status, last_published_at}} for
    every local AnalysisKind — the Analyses cards' equivalent of Survey
    Definitions' /candidates endpoint already returning last_run_at/
    last_published_at inline. Kept as its own lightweight endpoint rather
    than folded into GET /api/analyses/{resource_type} (analyses.py):
    that route is resource-type-wide and shared/cached across every repo of
    the same type (see its own module docstring) — deliberately has no repo
    slug at all. The frontend fetches this alongside GET /api/schedules/...
    in _loadAnalysisCatalogPanel() and merges both client-side into each
    card, same pattern that route already used for per-card schedule state.

    last_published_at is real per-analysis-id data even though this route
    is new: get_last_published_annotation_types() (added earlier the same
    day for the Survey Results dashboards) already has everything needed —
    each analysis_id's own annotation_types (analysis_catalog.yaml) is the
    same join key used there, just applied per-analysis instead of
    per-dashboard-of-several-analyses."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

    registry = ProjectRegistry()
    if not registry.get(slug):
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    last_run = registry.get_analysis_last_run("repo", slug)
    # Surveys that ran but carry no step detail (older rows). Their analyses
    # cannot be credited, but they also cannot honestly be called never-run.
    unattributed = last_run.pop("__unattributed_surveys__", {}).get("count", 0)
    published_by_type = registry.get_last_published_annotation_types(slug)
    published_by_analysis = registry.get_last_published_analyses(slug)

    result: dict[str, dict] = {}
    for a in get_analyses("repo", include_egeria_live=False):
        run = last_run.get(a["id"], {})
        # Publish attribution, in two tiers. Annotation types are shared --
        # ResourceMeasureAnnotation has 15 producers, ClassificationAnnotation
        # 13 -- so "any of my annotation types was published" credited every
        # sibling analysis with a publish it had no part in. That is what put
        # "Published today" on cards that had never run.
        #
        # A type only ONE analysis can produce is real evidence THIS analysis
        # was published. A shared one only shows the repo was published while
        # this analysis's types were involved, which is weaker and is labelled
        # as such -- the same 'analysis' vs 'repo' distinction the Survey
        # Definition cards already draw.
        # Recorded attribution first: the publish itself said which analyses it
        # covered (project_published_analyses). Everything below is the older
        # inference, kept only for publishes that predate that record.
        recorded = published_by_analysis.get(a["id"])
        own_types = a.get("annotation_types") or []
        shared = [t for t in own_types if t in published_by_type]
        if recorded:
            pub_at, pub_scope = recorded, "analysis"
        elif shared:
            # The inference can no longer yield an 'analysis' scope for
            # anything: once two analyses shared a type, nothing was uniquely
            # owned. Historical rows therefore read as the hedged 'repo'
            # scope, which is the truth about them — we cannot say which
            # analysis a pre-record publish covered.
            pub_at, pub_scope = max(published_by_type[t] for t in shared), "repo"
        else:
            pub_at, pub_scope = "", ""
        result[a["id"]] = {
            "last_run_at": run.get("last_run_at", ""),
            "last_run_status": run.get("last_run_status", ""),
            # "measured" / "never_run" / "not_established" -- the third is a
            # repo that WAS surveyed by runs we cannot attribute to analyses.
            # Calling that "never run" beside an attributable publish is what
            # produced "Never run" and "Published today" on one card.
            "last_run_basis": ("measured" if run.get("last_run_at")
                               else "not_established" if unattributed else "never_run"),
            "unattributed_surveys": unattributed,
            "last_run_via": run.get("last_run_via", ""),
            "last_run_partial": run.get("last_run_partial", False),
            "last_published_at": pub_at,
            "last_published_scope": pub_scope,
        }
    return result


@router.get("/{slug}/analyses/{analysis_id}/results")
async def get_analysis_results(slug: str, analysis_id: str, depth: str | None = None) -> dict:
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

    # `depth` is honoured only by readers that declare a max_depth parameter
    # (today: architecture_recovery). It was already supported end-to-end in
    # arch_recovery/projection.py — DEFAULT_PROJECTION_DEPTH, and a
    # STAGE_PROJECTION_DEPTH table naming the level each stage wants — but no
    # caller ever passed it, so every consumer silently got depth 1 and had no
    # way to ask for anything else. Passing it to a reader that does not accept
    # it would be a TypeError, hence the signature check rather than a blanket
    # kwarg.
    if depth is not None:
        import inspect

        if "max_depth" in inspect.signature(results_reader).parameters:
            if depth in ("all", "full", "none"):
                return results_reader(registry, slug, max_depth=None)
            try:
                parsed = int(depth)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"depth must be an integer or 'all', got {depth!r}",
                )
            if parsed < 0:
                raise HTTPException(status_code=400, detail="depth must be >= 0")
            return results_reader(registry, slug, max_depth=parsed)

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
    if trend_reader is None:
        # e.g. license_classification — a single current-state classification,
        # not a repeated-check story (license rarely changes), so it was
        # registered with trend_reader=None rather than a reader that would
        # always return a flat, near-meaningless one-point-per-run line.
        raise HTTPException(
            status_code=400,
            detail=f"Analysis '{analysis_id}' has no trend view — it's a current-state "
                   "classification, not tracked over time.",
        )
    return {"runs": trend_reader(registry, slug)}


def _results_have_data(results) -> bool:
    """Does a results payload actually contain anything?

    Truthiness is not enough and that is the whole point of this function: the
    readers return a shaped-but-empty dict when a step has never run for a repo
    — `{"findings": [], "gap_count": 0}` — which is truthy, so `any(results)`
    reported five-of-five analyses present for a repo that had never been
    surveyed for any of them.

    A payload counts as having data when it holds a non-empty collection or a
    non-zero number. An all-empty, all-zero payload is what "never ran" looks
    like. A genuinely all-zero result is therefore hidden too, which is the
    accepted trade: it reads as "nothing to show" either way, and
    include_empty=true returns everything for anyone who needs the distinction.
    """
    if not results:
        return False
    if isinstance(results, dict):
        # `_status` is an ENVELOPE, not content — it describes why a payload is
        # empty, so counting it as data makes every explained emptiness claim to
        # hold something. That is the opposite of what this function exists for:
        # a card saying "skipped, here is why" would be reported as having
        # results and then render as an explanation of nothing.
        #
        # `surveyed_at` and `detail` are excluded for the same reason — a
        # timestamp is evidence a step ran, not evidence it found anything, and
        # a reader that returns only a timestamp has nothing to show.
        # (_renderMetricsResults in index.html already filters exactly these
        # three for the same reason; this is the server-side half of it.)
        envelope = {"_status", "surveyed_at", "detail"}
        return any(_results_have_data(v) for k, v in results.items() if k not in envelope)
    if isinstance(results, (list, tuple, set)):
        return len(results) > 0
    if isinstance(results, bool):
        return results
    if isinstance(results, (int, float)):
        return results != 0
    if isinstance(results, str):
        return bool(results.strip())
    return True


@router.get("/{slug}/survey-results")
async def get_survey_results(slug: str, stage: str = "", include_empty: bool = False) -> dict:
    """Tier 2 — the Survey Results dashboards for this repo.

    stage (optional): restrict to cards belonging to that funnel stage, so each
    intent's own Results tab shows only what it is responsible for. Omitted =
    every stage, the original repo-wide view.

    include_empty (optional): return cards with no stored results too. Off by
    default — see the has_results comment below for why an empty card is worse
    than an absent one.

    Original docstring follows.

    Tier 2 — the repo-wide Survey Results dashboard
    (docs/survey-results-dashboard-plan.md). Every SURVEY_RESULT_DASHBOARDS
    entry, with its resolved analysis_ids' latest results attached (reusing
    the exact same results_reader()s the per-analysis_id Analysis/Assessment
    cards already call — no new persistence, this is a pure aggregation
    layer) and its derived Perspective tags. A dashboard entry whose reader
    raises (e.g. a step that's never been run for this repo) degrades to
    results=None for that one analysis_id rather than failing the whole
    dashboard list."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        REPO_ANALYSIS_RESULTS_MAP,
        SURVEY_RESULT_DASHBOARDS,
        get_dashboard_annotation_types,
        get_dashboard_perspectives,
        get_dashboard_stages,
    )

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    # {annotation_type: latest published_at} — one query for the whole repo,
    # joined per-dashboard below against each dashboard's own annotation_types
    # (get_dashboard_annotation_types). Real Egeria publish history, not a
    # guess — see EgeriaPublisher.publish()'s record_published_annotation_types call.
    published_by_type = registry.get_last_published_annotation_types(slug)

    dashboards = []
    for dashboard in SURVEY_RESULT_DASHBOARDS.values():
        stages = get_dashboard_stages(dashboard.analysis_ids)
        # Stage filter: a card can legitimately belong to several stages
        # (health_maturity reports repository_health/scouting *and*
        # maturity/assessment), so this is membership, not equality.
        if stage and stage not in stages:
            continue

        analyses = []
        for analysis_id in dashboard.analysis_ids:
            entry = REPO_ANALYSIS_RESULTS_MAP.get(analysis_id)
            results = None
            if entry:
                results_reader, _ = entry
                try:
                    results = results_reader(registry, slug)
                except Exception:
                    results = None
            analyses.append({"analysis_id": analysis_id, "results": results})

        # Only surface a card backed by something that actually ran. Previously
        # every dashboard was returned unconditionally and a card with no data
        # rendered as an empty shell, so the Results tab advertised analyses the
        # repo had never been surveyed for — 6 cards covering 13 analyses when
        # Scouting only ever runs a handful. `results=None` is what a reader
        # returns for a step with no stored rows, so it is the honest signal.
        has_results = any(_results_have_data(a["results"]) for a in analyses)
        if not has_results and not include_empty:
            continue

        # Real per-dashboard publish signal (2026-08-24), not a repo-wide
        # guess: the latest of this dashboard's own annotation_types' known
        # publish times. Blank when has_results is true but nothing in it
        # has ever actually been published — an honest, common state (ran
        # locally, never sent to Egeria), distinct from never-run.
        dashboard_types = get_dashboard_annotation_types(dashboard.analysis_ids)
        last_published_at = max(
            (published_by_type[t] for t in dashboard_types if t in published_by_type),
            default="",
        )

        dashboards.append({
            "id": dashboard.id,
            "title": dashboard.title,
            "description": dashboard.description,
            "render": dashboard.render,
            "custom_renderer": dashboard.custom_renderer,
            "perspectives": get_dashboard_perspectives(dashboard.analysis_ids),
            "stages": stages,
            "has_results": has_results,
            "analyses": analyses,
            "last_published_at": last_published_at,
            # Repo-wide, not per-dashboard — there's no per-analysis_id run
            # timestamp to draw on today (unlike last_published_at above,
            # which genuinely is per-dashboard). Still an honest "as of"
            # signal: every dashboard's data was current no later than this.
            "last_surveyed_at": project.last_surveyed_at or "",
        })
    return {"slug": slug, "stage": stage, "dashboards": dashboards}


@router.get("/{slug}/survey-results/summary")
async def get_survey_results_summary(slug: str, phase: str = "") -> dict:
    """Tier 1 — a phase-scoped 'is it worth proceeding' stat row
    (docs/survey-results-dashboard-plan.md D5). One stat tile per
    ANALYSIS_KINDS entry whose analysis_catalog.yaml intent matches `phase`
    and has a headline_reader — empty phase returns every tile with a
    headline_reader across all intents."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
    from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_HEADLINE_MAP

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")

    analyses = get_analyses(resource_type="repo", intent=phase or None)
    tiles = []
    for a in analyses:
        headline_reader = REPO_ANALYSIS_HEADLINE_MAP.get(a["id"])
        if not headline_reader:
            continue
        try:
            headline = headline_reader(registry, slug)
        except Exception:
            headline = None
        if headline:
            tiles.append({"analysis_id": a["id"], "analysis_name": a.get("name", a["id"]), **headline})
    return {"slug": slug, "phase": phase, "tiles": tiles}


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
