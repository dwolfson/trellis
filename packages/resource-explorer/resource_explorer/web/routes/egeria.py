"""Egeria integration endpoints — asset registration, survey history, publish."""
from __future__ import annotations

import asyncio
import json
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from resource_explorer.registry import ProjectRegistry

router = APIRouter()


# ── identity ───────────────────────────────────────────────────────────────────
# RE has no per-user auth today (see resource_explorer/config.py::EgeriaConfig) —
# every request connects to Egeria as the same fixed service-account identity
# from config/.env, not a logged-in individual. This endpoint just surfaces
# that configured identity read-only for the header indicator; it is
# deliberately NOT a login mechanism. Real per-user login was raised and
# explicitly deferred as its own, larger piece of scope — see the Trellis
# design docs before building an actual auth flow against this.
@router.get("/whoami")
def whoami() -> dict:
    from resource_explorer.config import get_config
    cfg = get_config().egeria
    return {
        "user_id": cfg.user_id,
        "view_server": cfg.view_server,
        "platform_url": cfg.platform_url,
    }


# ── response models ───────────────────────────────────────────────────────────

class SurveyRow(BaseModel):
    surveyed_at: str
    egeria_report_guid: str
    published_at: str
    annotation_count: int | None


class EgeriaStatus(BaseModel):
    slug: str
    asset_guid: str | None
    is_registered: bool
    platform_url: str
    surveys: list[SurveyRow]


class PublishResult(BaseModel):
    status: str                    # "ok" | "error"
    report_guid: str | None = None
    annotation_count: int | None = None
    surveyed_at: str | None = None
    error: str | None = None
    stage: str | None = None       # "survey" | "publish"


class AnnotationItem(BaseModel):
    guid: str
    annotation_type: str
    summary: str
    confidence: int | None
    analysis_step: str
    explanation: str
    expression: str
    json_properties: dict
    subtype_data: dict


class AnnotationsResult(BaseModel):
    slug: str
    surveyed_at: str
    report_guid: str
    annotations: list[AnnotationItem]


class EgeriaSurveyReportRow(BaseModel):
    """A SurveyReport as it actually exists in Egeria right now (live read via
    the real ReportSubject relationship) — regardless of which engine (RE or
    Egeria's own native survey) produced it. See databases.py's identical
    model and resource_explorer/surveyors/egeria_survey_reader.py."""
    guid: str
    qualified_name: str
    display_name: str
    surveyed_at: str
    annotation_count: int
    schema_count: int
    table_count: int
    column_count: int
    description: str


class EgeriaAnnotationItem(BaseModel):
    guid: str
    annotation_type: str
    summary: str
    confidence: int | None
    analysis_step: str
    explanation: str
    expression: str
    json_properties: dict


class FileTypeSummary(BaseModel):
    label: str
    count: int
    source: str
    extensions: dict = {}     # details_json for the "Other" bucket


class DependencySummary(BaseModel):
    ecosystem: str
    count: int
    direct: int


class DataProfileSummary(BaseModel):
    file_path: str
    format: str
    row_count: int | None = None
    col_count: int | None = None
    columns: list[dict] = []      # [{name, dtype, null_pct}]
    null_summary: str = ""
    file_size_bytes: int = 0
    profiled_at: str | None = None


class SurveyReportData(BaseModel):
    slug: str
    display_name: str
    github_url: str
    latest_survey: SurveyRow | None
    file_types: list[FileTypeSummary]
    total_files: int
    health: dict
    primary_language: str
    dependencies: list[DependencySummary]
    has_egeria_annotations: bool
    data_profiles: list[DataProfileSummary] = []
    local_surveyed_at: str = ""   # timestamp of the most recent local survey run


class CatalogElement(BaseModel):
    label: str
    file_count: int
    extensions: list[str] = []


class CatalogRequest(BaseModel):
    elements: list[CatalogElement]


class CatalogItemResult(BaseModel):
    label: str
    guid: str | None = None
    status: str          # "created" | "error"
    error: str | None = None


class CatalogResult(BaseModel):
    status: str          # "ok" | "partial" | "error"
    cataloged: list[CatalogItemResult]


# ── helpers ───────────────────────────────────────────────────────────────────

def _platform_url() -> str:
    return os.getenv("EGERIA_PLATFORM_URL", "https://localhost:9443")


def _get_project_or_404(slug: str):
    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return project, registry


# ── routes ────────────────────────────────────────────────────────────────────

class DataClassRule(BaseModel):
    name: str
    display_name: str
    description: str
    keywords: list[str]
    source: str


@router.get("/rules/dataclasses", response_model=list[DataClassRule])
async def get_dataclass_rules() -> list[DataClassRule]:
    """Fetch the active PII Data Classes and their corresponding keyword matching rules.

    Queries Egeria's Valid Value sets if online; falls back to local rules if offline.
    """
    fallback_rules = [
        {"name": "EmailAddress", "display_name": "Email Address", "description": "Electronic mail address identifier.", "keywords": ["email", "email_address", "mail_addr", "emailaddr"], "source": "Local Fallback"},
        {"name": "PhoneNumber", "display_name": "Phone Number", "description": "Telephone contact number.", "keywords": ["phone", "phone_number", "telephone", "mobile", "tel_num"], "source": "Local Fallback"},
        {"name": "SocialSecurityNumber", "display_name": "Social Security Number", "description": "Government issued social security identification number.", "keywords": ["ssn", "socialsec", "social_security", "ssn_num"], "source": "Local Fallback"},
        {"name": "CreditCardNumber", "display_name": "Credit Card Number", "description": "Financial credit or debit card identifier.", "keywords": ["creditcard", "credit_card", "cc_num", "card_number"], "source": "Local Fallback"},
        {"name": "Password", "display_name": "Password", "description": "Credential or secret authentication passkey.", "keywords": ["password", "passkey", "passwd", "pwd"], "source": "Local Fallback"},
        {"name": "DateOfBirth", "display_name": "Date of Birth", "description": "Individual date or anniversary of birth.", "keywords": ["dob", "dateofbirth", "birth_date", "birthdate"], "source": "Local Fallback"},
    ]

    platform_url = os.getenv("EGERIA_PLATFORM_URL")
    if not platform_url:
        return [DataClassRule(**r) for r in fallback_rules]

    try:
        from pyegeria.omvs.reference_data import ReferenceDataManager
        from pyegeria.omvs.data_designer import DataDesigner

        view_server = os.getenv("EGERIA_VIEW_SERVER", "view-server")
        user_id = os.getenv("EGERIA_USER", "steward")
        user_pwd = os.getenv("EGERIA_USER_PASSWORD", "steward")

        def _fetch():
            ref_manager = ReferenceDataManager(view_server, platform_url, user_id, user_pwd)
            ref_manager.create_egeria_bearer_token(user_id, user_pwd)
            designer = DataDesigner(view_server, platform_url, user_id, user_pwd)
            designer.create_egeria_bearer_token(user_id, user_pwd)

            rules = []
            for dc in fallback_rules:
                name = dc["name"]
                qname = f"DataClass::{name}"
                keywords = []
                try:
                    guid = designer.get_guid_for_name(qname)
                    if guid:
                        results = ref_manager.find_valid_value_definitions(
                            search_string=f"ValidValueDefinition::{name}Keyword::",
                            starts_with=True,
                            output_format="JSON"
                        )
                        if isinstance(results, list):
                            for item in results:
                                if isinstance(item, dict):
                                    props = item.get("properties", {})
                                    val = props.get("preferredValue") or props.get("displayName")
                                    if val:
                                        keywords.append(val.strip().lower())
                except Exception:
                    pass

                rules.append(
                    DataClassRule(
                        name=name,
                        display_name=dc["display_name"],
                        description=dc["description"],
                        keywords=list(set(keywords)) if keywords else dc["keywords"],
                        source="Egeria (Active)" if keywords else "Local Fallback"
                    )
                )
            return rules

        return await asyncio.to_thread(_fetch)
    except Exception:
        return [DataClassRule(**r) for r in fallback_rules]


@router.get("/{slug}/status", response_model=EgeriaStatus)
async def egeria_status(slug: str) -> EgeriaStatus:
    """Return Egeria registration status and local survey history for a project.

    Reads from the local SQLite registry only — no Egeria connection needed.
    """
    project, registry = _get_project_or_404(slug)
    asset_guid = registry.get_egeria_asset_guid(slug)
    surveys_raw = registry.get_egeria_surveys(slug)
    surveys = [
        SurveyRow(
            surveyed_at=r["surveyed_at"],
            egeria_report_guid=r["egeria_report_guid"],
            published_at=r["published_at"],
            annotation_count=r.get("annotation_count"),
        )
        for r in surveys_raw
    ]
    return EgeriaStatus(
        slug=slug,
        asset_guid=asset_guid,
        is_registered=asset_guid is not None,
        platform_url=_platform_url(),
        surveys=surveys,
    )


@router.get("/{slug}/annotations", response_model=AnnotationsResult)
async def get_annotations(slug: str, surveyed_at: str, report_guid: str = "") -> AnnotationsResult:
    """Fetch all annotations for a specific survey run from Egeria.

    Requires a live Egeria connection (EGERIA_PLATFORM_URL env var).
    `surveyed_at` is the ISO timestamp used as part of the annotation qualifiedName.
    """
    project, registry = _get_project_or_404(slug)

    from resource_explorer.surveyors.egeria_reader import EgeriaReader, EgeriaReaderError
    reader = EgeriaReader(registry=registry)
    try:
        # EgeriaReader calls pyegeria sync wrappers — run in thread to avoid event loop conflict
        raw_annotations = await asyncio.to_thread(reader.get_annotations, slug, surveyed_at)
    except EgeriaReaderError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Egeria query failed: {exc}")

    annotations = [
        AnnotationItem(
            guid=a.get("guid", ""),
            annotation_type=a.get("annotation_type", ""),
            summary=a.get("summary", ""),
            confidence=a.get("confidence"),
            analysis_step=a.get("analysis_step", ""),
            explanation=a.get("explanation", ""),
            expression=a.get("expression", ""),
            json_properties=a.get("json_properties", {}),
            subtype_data=a.get("subtype_data", {}),
        )
        for a in raw_annotations
    ]

    return AnnotationsResult(
        slug=slug,
        surveyed_at=surveyed_at,
        report_guid=report_guid,
        annotations=annotations,
    )


@router.get("/{slug}/egeria-surveys", response_model=list[EgeriaSurveyReportRow])
async def get_repo_egeria_surveys(slug: str) -> list[EgeriaSurveyReportRow]:
    """List SurveyReports that actually exist in Egeria right now for this repo
    (a live read via the real ReportSubject relationship, not the older
    qualifiedName-guessing /annotations path above)."""
    from resource_explorer.surveyors.egeria_publisher import EgeriaConnectionError, EgeriaPublisher

    project, registry = _get_project_or_404(slug)
    if not project.egeria_asset_guid:
        return []  # not yet cataloged in Egeria — nothing to walk from

    publisher = EgeriaPublisher(registry=registry)
    try:
        reports = await asyncio.to_thread(publisher.get_survey_reports_by_guid, project.egeria_asset_guid)
    except EgeriaConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [EgeriaSurveyReportRow(**r) for r in reports]


@router.get("/{slug}/egeria-surveys/{report_guid}/annotations", response_model=list[EgeriaAnnotationItem])
async def get_repo_egeria_annotations(slug: str, report_guid: str) -> list[EgeriaAnnotationItem]:
    """Fetch all annotations for a specific live Egeria SurveyReport, by the
    report's own GUID — works regardless of which engine produced the report."""
    from resource_explorer.surveyors.egeria_publisher import EgeriaConnectionError, EgeriaPublisher

    _project, registry = _get_project_or_404(slug)

    publisher = EgeriaPublisher(registry=registry)
    try:
        annotations = await asyncio.to_thread(publisher.get_annotations_by_report_guid, report_guid)
    except EgeriaConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [EgeriaAnnotationItem(**a) for a in annotations]


class ResetResult(BaseModel):
    status: str                  # "ok"
    slug: str
    asset_guid_cleared: bool
    surveys_deleted: int


class SurveyOnlyResult(BaseModel):
    status: str                      # "ok" | "error"
    annotation_count: int | None = None
    surveyed_at: str | None = None
    errors: list[str] = []
    error: str | None = None


# ── Egeria linkage divergence (docs/Backlog.md; egeria_linkage.py) ───────────
# Surfaced as its own routes rather than folded into /{slug}/reset because reset
# is repo-only and, crucially, undiscoverable: it is the right action but nothing
# ever tells you to take it. These make the condition visible and name the
# choices. The /{slug}/reset route stays as-is — same clearing, still valid.

class StaleLinkage(BaseModel):
    entity_type: str
    entity_slug: str
    stale_guid: str = ""
    detected_at: str = ""
    detail: str = ""


class LinkageResolveRequest(BaseModel):
    # republish — re-publish what RE already holds locally (fast; right when only
    #             Egeria was reset and the resource itself has not changed)
    # resurvey  — re-survey from scratch, then publish (right when the resource
    #             may have changed too, or the local data is old enough to doubt)
    # discard   — clear the broken link and stop; RE's local survey data is kept
    action: str


class LinkageResolveResult(BaseModel):
    status: str
    entity_type: str
    entity_slug: str
    action: str
    asset_guid_cleared: bool = False
    surveys_deleted: int = 0
    next_step: str = ""


@router.get("/linkage/stale", response_model=list[StaleLinkage])
def list_stale_linkages() -> list[StaleLinkage]:
    """Entities whose cached Egeria GUID was found not to exist.

    A row appears only after a real failure — nothing here probes Egeria. The
    reactive-only choice is deliberate for now: a proactive sweep would have to
    decide how often to re-check every cataloged entity, and the failure it
    guards against is rare and already loud once this exists.
    """
    return [StaleLinkage(**{k: v for k, v in row.items() if k != "status"})
            for row in ProjectRegistry().list_stale_egeria_linkages()]


class BulkTarget(BaseModel):
    entity_type: str = "repo"
    slug: str


class BulkRequest(BaseModel):
    """An explicit list of what to act on, never a server-side "everything stale".

    A sweep result and a work list are different things: `egeria-recheck` reports
    what it found at that moment, and deriving the target list here would act on
    something nobody read. The UI sends the rows it displayed, so what is acted on
    is always what was seen.
    """
    targets: list[BulkTarget]
    dry_run: bool = True   # defaults to the safe direction; the caller opts out


class BulkResolveRequest(BulkRequest):
    action: str = "republish"


@router.post("/linkage/resolve-all")
async def resolve_all_linkages(req: BulkResolveRequest) -> dict:
    """Apply one resolution to many diverged resources.

    Republish is the usual choice after an Egeria reset — it re-publishes what RE
    already holds rather than re-scanning. Runs in a thread: a republish is a
    survey plus a publish per resource, so twenty of them is minutes, not
    milliseconds.
    """
    from resource_explorer.bulk_ops import resolve_all

    registry = ProjectRegistry()
    targets = [t.model_dump() for t in req.targets]
    try:
        result = await asyncio.to_thread(
            resolve_all, registry, targets, req.action, dry_run=req.dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result.as_dict()


@router.post("/linkage/delete-local")
async def delete_resources_locally(req: BulkRequest) -> dict:
    """Remove resources from RE entirely — registry row and pgvector collections.

    Destructive, and the collections are the expensive part to reverse:
    re-registering means re-ingesting. Egeria is left alone. Defaults to a dry
    run; the caller has to ask for the real thing.
    """
    from resource_explorer.bulk_ops import delete_local

    result = await asyncio.to_thread(
        delete_local, ProjectRegistry(), [t.model_dump() for t in req.targets],
        dry_run=req.dry_run)
    return result.as_dict()


@router.post("/linkage/delete-in-egeria")
async def delete_resources_in_egeria(req: BulkRequest) -> dict:
    """Delete the Egeria asset RE recorded for each resource.

    Only ever the GUID RE itself stored — never resolved by name, never
    cascading, and a resource without a cached GUID is skipped rather than
    searched for. Egeria is the catalog of record and RE otherwise only adds to
    it; this is the one path that can remove governance history, so it is
    deliberately the narrowest of the three.

    RE's own data is untouched: registry rows, survey results and collections all
    survive.
    """
    from resource_explorer.bulk_ops import delete_in_egeria

    result = await asyncio.to_thread(
        delete_in_egeria, ProjectRegistry(), [t.model_dump() for t in req.targets],
        dry_run=req.dry_run)
    return result.as_dict()


@router.post("/linkage/{entity_type}/{slug}/resolve", response_model=LinkageResolveResult)
async def resolve_stale_linkage(
    entity_type: str, slug: str, req: LinkageResolveRequest,
) -> LinkageResolveResult:
    """Act on a detected divergence.

    All three actions clear the unusable GUID and the divergence record — that is
    what unblocks the resource, and it is common to every choice. They differ in
    what happens next, which is why the caller has to say which one they mean
    rather than this picking for them.

    Only `republish`/`resurvey` for a repo actually run the follow-up work here.
    For databases and filesystems the link is cleared and the caller is told which
    existing action to run: re-publishing those from cached local data needs
    per-type orchestration (a database publish reconstructs schema_info and fires
    Egeria's native survey), and there is no registered database or filesystem in
    this deployment to verify such a path against. Clearing is the part that is
    genuinely generic; pretending the rest was would be worse than saying so.
    """
    if entity_type not in ("repo", "database", "filesystem"):
        raise HTTPException(status_code=422, detail=f"Unknown entity type '{entity_type}'")
    if req.action not in ("republish", "resurvey", "discard"):
        raise HTTPException(
            status_code=422,
            detail=f"Unknown action '{req.action}'; expected republish, resurvey or discard")

    registry = ProjectRegistry()
    if not registry.get_egeria_linkage(entity_type, slug):
        raise HTTPException(
            status_code=404,
            detail=f"No stale Egeria linkage recorded for {entity_type} '{slug}'")

    cleared, deleted = False, 0
    if entity_type == "repo":
        result = registry.clear_egeria_registration(slug)
        cleared, deleted = result["asset_guid_cleared"], result["surveys_deleted"]
    elif entity_type == "database":
        registry.set_database_egeria_guid(slug, "")
        cleared = True
    else:
        registry.set_filesystem_egeria_guid(slug, "")
        cleared = True

    registry.clear_egeria_linkage_status(entity_type, slug)

    next_step = ""
    if req.action == "discard":
        # Say what was actually removed. For a repo, clearing the registration
        # also drops project_egeria_surveys — the record of past publishes and
        # their report GUIDs. Those GUIDs point into the same repository that no
        # longer has the asset, so keeping them would preserve nothing but stale
        # pointers; the publish history itself remains in the activity log. But
        # "untouched", which this said before, was not true of them, and the one
        # action a user might fear is the wrong place to be imprecise.
        removed = (f" {deleted} publish record(s) removed;" if deleted else "")
        next_step = (f"Link cleared.{removed} survey results and annotations are "
                     "untouched, and past publishes remain in the activity log. "
                     "Nothing will be written to Egeria until you publish again.")
    elif entity_type == "repo":
        from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
        from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

        try:
            if req.action == "resurvey":
                survey = await asyncio.to_thread(
                    lambda: SurveyOrchestrator(registry).run(slug))
            else:
                # republish: re-derive from what RE already holds locally. The
                # orchestrator reads the stored tables rather than re-fetching,
                # so this is the "fast, no re-scan" path the choice promises.
                survey = await asyncio.to_thread(
                    lambda: SurveyOrchestrator(registry).run(slug, max_fetch_cost="none"))
            guid = await asyncio.to_thread(lambda: EgeriaPublisher(registry=registry).publish(survey))
            next_step = f"Re-created in Egeria as SurveyReport {guid}."
        except Exception as exc:
            # The link is already cleared, so this is recoverable by retrying the
            # ordinary publish — say that rather than leaving a bare stack trace.
            raise HTTPException(
                status_code=502,
                detail=(f"Link cleared, but {req.action} failed: {exc}. The stale GUID is "
                        "gone, so an ordinary publish should now succeed.")) from exc
    else:
        verb = "publish" if req.action == "republish" else "survey and publish"
        next_step = (f"Link cleared. Run {verb} for this {entity_type} from its own panel "
                     "to re-create it in Egeria.")

    return LinkageResolveResult(
        status="ok", entity_type=entity_type, entity_slug=slug, action=req.action,
        asset_guid_cleared=cleared, surveys_deleted=deleted, next_step=next_step,
    )


class RecheckDetail(BaseModel):
    entity_type: str
    slug: str
    guid: str
    result: str    # "ok" | "stale" | "error"
    detail: str = ""


class RecheckResult(BaseModel):
    checked: int
    ok: int
    stale: int
    errors: int
    skipped: int
    details: list[RecheckDetail]


@router.post("/linkage/recheck", response_model=RecheckResult)
async def recheck_linkages(entity_type: list[str] | None = None) -> RecheckResult:
    """Proactively probe Egeria for every cached GUID instead of waiting for
    the reactive path (guard_linkage) to trip over one on next use.

    This is the sweep behind `resource-explorer egeria-recheck` — see
    egeria_linkage.recheck_all_linkages for why it both records new
    divergences and clears ones that have since resolved. Runs in a thread:
    it makes one network call per cataloged resource (~20 in a typical
    deployment) and pyegeria's sync wrappers are blocking.
    """
    from resource_explorer.egeria_linkage import recheck_all_linkages

    registry = ProjectRegistry()
    result = await asyncio.to_thread(
        recheck_all_linkages, registry, entity_types=entity_type)
    return RecheckResult(**result)


@router.post("/{slug}/reset", response_model=ResetResult)
async def reset_egeria(slug: str) -> ResetResult:
    """Clear the cached Egeria asset GUID and all published survey records for a project.

    Use this after resetting the Egeria database so the next --publish re-registers
    the project from scratch instead of referencing stale GUIDs.
    """
    project, registry = _get_project_or_404(slug)
    result = registry.clear_egeria_registration(slug)
    return ResetResult(
        status="ok",
        slug=slug,
        asset_guid_cleared=result["asset_guid_cleared"],
        surveys_deleted=result["surveys_deleted"],
    )


@router.post("/{slug}/survey", response_model=SurveyOnlyResult)
async def run_survey(slug: str) -> SurveyOnlyResult:
    """Run a survey for a project and persist results to SQLite.

    Does not publish to Egeria. Updates project_file_type_counts so the
    Survey Report tab refreshes automatically after this call completes.
    """
    project, registry = _get_project_or_404(slug)

    try:
        from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

        def _run():
            return SurveyOrchestrator(registry=registry).run(slug)

        result = await asyncio.to_thread(_run)
    except Exception as exc:
        return SurveyOnlyResult(status="error", error=str(exc))

    return SurveyOnlyResult(
        status="ok",
        annotation_count=len(result.annotations),
        surveyed_at=result.surveyed_at.isoformat(),
        errors=result.errors,
    )


class PublishRequest(BaseModel):
    zone_names: list[str] = []
    # None (default) = full survey, byte-for-byte the existing behavior.
    # A list scopes the survey (and therefore the published SurveyReport) to
    # just those SurveyOrchestrator step keys — lets each phase (Scouting,
    # coarse profiling, etc.) publish only what it actually knows, as its own
    # SurveyReport linked to the same asset, rather than one all-or-nothing
    # publish. Same step-key vocabulary as REPO_ANALYSIS_STEP_MAP.
    steps: list[str] | None = None
    # Optional — set when this publish was triggered from a Survey Definition
    # candidate's own "☁ Publish" button (renderSurveyPanel), so the resulting
    # activity_log entry can be attributed back to that candidate for the
    # last-published badge (registry.get_survey_definition_last_activity).
    # Blank for every other publish surface (Curate, Profile, etc.) — those
    # just don't get a last-published badge anywhere, which is correct: they
    # aren't tied to one Survey Definition.
    survey_definition_ref: str = ""


@router.post("/{slug}/publish", response_model=PublishResult)
async def publish_survey(slug: str, req: PublishRequest | None = None) -> PublishResult:
    """Run a survey (full, or scoped to req.steps) then publish the result to Egeria.

    The survey and publish steps both call blocking synchronous code (pyegeria's
    sync wrappers use loop.run_until_complete internally).  Running them inside
    FastAPI's async event loop would cause "Can't patch loop" errors, so both
    steps are offloaded to a thread pool via asyncio.to_thread().
    """
    project, registry = _get_project_or_404(slug)

    # ── Egeria Project context gate (Part 5) ──────────────────────────────────
    # The first real Egeria write for a resource is exactly this route — every
    # repo publish surface (Scouting's registration-only publish, Assessment/
    # Analysis per-card publish, Profile publish, Curate's full publish) funnels
    # through here with different `steps`. Gating here once, rather than in
    # each frontend button handler, means a future publish surface can't
    # forget the check. status "unset" (never decided, including no row at
    # all) blocks; every other status (personal/linked/deferred/declined —
    # all deliberate answers) proceeds.
    context = registry.get_project_context("repo", slug)
    if not context or context.get("status") == "unset":
        return JSONResponse(
            status_code=428,
            content={
                "detail": "egeria_project_context_required",
                "entity_type": "repo",
                "entity_slug": slug,
            },
        )

    steps = req.steps if req else None

    # ── Step 1: survey (blocking — run in thread) ─────────────────────────────
    try:
        from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

        def _run_survey():
            return SurveyOrchestrator(registry=registry).run(slug, steps=steps)

        result = await asyncio.to_thread(_run_survey)
    except Exception as exc:
        return PublishResult(
            status="error",
            error=f"Survey failed: {exc}",
            stage="survey",
        )

    # ── Step 2: publish (blocking — run in thread) ────────────────────────────
    try:
        from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher, EgeriaConnectionError

        zone_names = (req.zone_names if req else None) or None

        def _run_publish():
            # pyegeria sync wrappers call asyncio.get_event_loop() — set one for this thread
            import asyncio as _aio
            loop = _aio.new_event_loop()
            _aio.set_event_loop(loop)
            try:
                return EgeriaPublisher(registry=registry, zone_names=zone_names).publish(result)
            finally:
                loop.close()
                _aio.set_event_loop(None)

        report_guid = await asyncio.to_thread(_run_publish)
    except Exception as exc:
        return PublishResult(
            status="error",
            error=str(exc),
            stage="publish",
            surveyed_at=result.surveyed_at.isoformat(),
        )

    # Separate, minimal activity_log entry (not a change to EgeriaPublisher.
    # publish()'s own log_catalog call above, which every publish surface
    # shares) — only written when this publish came from a Survey Definition
    # candidate's own "☁ Publish" button, so its last-published badge
    # (registry.get_survey_definition_last_activity) has something to find.
    if req and req.survey_definition_ref:
        from resource_explorer.activity_logger import log_catalog

        log_catalog(
            registry, entity_type="repo", entity_slug=slug,
            entity_name=project.display_name, entity_location=project.github_url,
            status="ok",
            summary=f"Published '{req.survey_definition_ref}' findings ({len(result.annotations)} annotations)",
            detail=json.dumps({"survey_definition_ref": req.survey_definition_ref}),
        )

    return PublishResult(
        status="ok",
        report_guid=report_guid,
        annotation_count=len(result.annotations),
        surveyed_at=result.surveyed_at.isoformat(),
    )


@router.get("/{slug}/survey-report", response_model=SurveyReportData)
async def get_survey_report(slug: str) -> SurveyReportData:
    """Assemble survey report data entirely from SQLite — no Egeria connection needed.

    Returns file type counts, health stats, dependency summary, and the latest
    survey record.  Egeria annotation details are fetched separately via the
    /annotations endpoint when the user requests them.
    """
    import json as _json

    project, registry = _get_project_or_404(slug)

    # File types from latest survey run
    file_type_rows = registry.query_file_type_counts(slug)
    local_surveyed_at = file_type_rows[0].get("surveyed_at", "") if file_type_rows else ""
    file_types: list[FileTypeSummary] = []
    for r in file_type_rows:
        exts: dict = {}
        if r.get("details_json"):
            try:
                exts = _json.loads(r["details_json"])
            except Exception:
                pass
        file_types.append(FileTypeSummary(
            label=r["type_label"],
            count=r["file_count"],
            source=r.get("source", "extension"),
            extensions=exts,
        ))
    total_files = sum(f.count for f in file_types)

    # Project stats (stars, forks, language, license…)
    stats = registry.get_latest_project_stats(slug) or {}
    health = {
        "stars":            stats.get("stars", 0),
        "forks":            stats.get("forks", 0),
        "open_issues":      stats.get("open_issues", 0),
        "contributors":     stats.get("contributors", 0),
        "last_push":        stats.get("last_push", ""),
        "primary_language": stats.get("primary_language", ""),
        "license":          stats.get("license", ""),
        "topics":           stats.get("topics", ""),
    }

    # Dependencies grouped by ecosystem
    deps = registry.query_dependencies(slug)
    dep_map: dict[str, dict] = {}
    for d in deps:
        eco = d.get("ecosystem") or "unknown"
        if eco not in dep_map:
            dep_map[eco] = {"ecosystem": eco, "count": 0, "direct": 0}
        dep_map[eco]["count"] += 1
        if d.get("dep_type") == "direct":
            dep_map[eco]["direct"] += 1
    dep_summary = [
        DependencySummary(**v)
        for v in sorted(dep_map.values(), key=lambda x: -x["count"])
    ]

    # Data profiles from project_data_profiles
    raw_profiles = registry.get_data_profiles(slug)
    data_profiles: list[DataProfileSummary] = []
    for p in raw_profiles:
        cols: list[dict] = []
        if p.get("schema_json"):
            try:
                cols = _json.loads(p["schema_json"])
            except Exception:
                pass
        data_profiles.append(DataProfileSummary(
            file_path=p["file_path"],
            format=p["format"],
            row_count=p.get("row_count"),
            col_count=p.get("col_count"),
            columns=cols,
            null_summary=p.get("null_summary") or "",
            file_size_bytes=p.get("file_size_bytes") or 0,
            profiled_at=p.get("profiled_at"),
        ))

    # Latest Egeria survey (may be None if never published)
    latest_raw = registry.get_latest_egeria_survey(slug)
    latest_survey: SurveyRow | None = None
    if latest_raw:
        latest_survey = SurveyRow(
            surveyed_at=latest_raw["surveyed_at"],
            egeria_report_guid=latest_raw["egeria_report_guid"],
            published_at=latest_raw["published_at"],
            annotation_count=latest_raw.get("annotation_count"),
        )

    return SurveyReportData(
        slug=slug,
        display_name=project.display_name,
        github_url=project.github_url,
        latest_survey=latest_survey,
        file_types=file_types,
        total_files=total_files,
        health=health,
        primary_language=stats.get("primary_language", ""),
        dependencies=dep_summary,
        has_egeria_annotations=latest_survey is not None,
        data_profiles=data_profiles,
        local_surveyed_at=local_surveyed_at,
    )


@router.post("/{slug}/catalog-elements", response_model=CatalogResult)
async def catalog_elements(slug: str, request: CatalogRequest) -> CatalogResult:
    """Create Egeria DataSet assets for selected file type categories.

    Each selected category becomes a DataSet asset linked to the project's
    SourceControlLibrary via a CapabilityAssetUse relationship.  The project
    must have been published to Egeria first (egeria_asset_guid must be cached).

    Runs in a thread to avoid event loop conflict with pyegeria sync wrappers.
    """
    project, registry = _get_project_or_404(slug)

    if not request.elements:
        return CatalogResult(status="ok", cataloged=[])

    def _do_catalog() -> list[CatalogItemResult]:
        import asyncio as _aio
        from pyegeria import AssetMaker
        # pyegeria sync wrappers call asyncio.get_event_loop() — set one for this thread
        loop = _aio.new_event_loop()
        _aio.set_event_loop(loop)

        view_server  = os.getenv("EGERIA_VIEW_SERVER", "qs-view-server")
        user_id      = os.getenv("EGERIA_USER", "erinoverview")
        user_pwd     = os.getenv("EGERIA_USER_PASSWORD", "secret")

        asset_guid = registry.get_egeria_asset_guid(slug)
        if not asset_guid:
            raise ValueError(
                "Project not yet registered in Egeria — publish a survey first."
            )

        am = AssetMaker(view_server, _platform_url(), user_id, user_pwd)
        am.create_egeria_bearer_token(user_id, user_pwd)

        results: list[CatalogItemResult] = []
        for elem in request.elements:
            try:
                dataset_body = {
                    "class": "NewElementRequestBody",
                    "properties": {
                        "class": "DataSetProperties",
                        "typeName": "DataSet",
                        "qualifiedName": f"DataSet::{slug}::{elem.label}",
                        "displayName": f"{elem.label} — {project.display_name}",
                        "description": (
                            f"{elem.file_count} {elem.label} file(s) in "
                            f"{project.github_url}. "
                            + (f"Extensions: {', '.join(elem.extensions)}." if elem.extensions else "")
                        ),
                        "additionalProperties": {
                            "project_slug":     slug,
                            "file_type_label":  elem.label,
                            "file_count":       str(elem.file_count),
                            "extensions":       ", ".join(elem.extensions),
                            "github_url":       project.github_url,
                        },
                    },
                }
                dataset_guid = am.create_asset(body=dataset_body)

                link_body = {
                    "class": "NewRelationshipRequestBody",
                    "properties": {
                        "class": "CapabilityAssetUseProperties",
                        "useType": "GOVERNS",
                        "description": f"{elem.label} files managed by this repository",
                    },
                }
                am.add_capability_asset_use(
                    software_capability_guid=asset_guid,
                    asset_guid=dataset_guid,
                    body=link_body,
                )
                results.append(CatalogItemResult(label=elem.label, guid=dataset_guid, status="created"))
            except Exception as exc:
                results.append(CatalogItemResult(label=elem.label, status="error", error=str(exc)[:140]))

        am.close_session()
        loop.close()
        _aio.set_event_loop(None)
        return results

    try:
        cataloged = await asyncio.to_thread(_do_catalog)
    except Exception as exc:
        return CatalogResult(
            status="error",
            cataloged=[CatalogItemResult(label="(all)", status="error", error=str(exc)[:200])],
        )

    errors = [c for c in cataloged if c.status == "error"]
    overall = "ok" if not errors else ("partial" if len(errors) < len(cataloged) else "error")

    try:
        from resource_explorer.activity_logger import log_catalog
        ok_items = [c for c in cataloged if c.status == "created"]
        log_catalog(
            ProjectRegistry(),
            entity_type="repo",
            entity_slug=slug,
            entity_name=project.display_name,
            entity_location=project.github_url,
            status=overall,
            summary=f"Cataloged {len(ok_items)}/{len(cataloged)} element(s) in Egeria",
            items=[
                {"kind": "DataSet", "display_name": c.label,
                 "qualified_name": f"DataSet::{slug}::{c.label}",
                 "guid": c.guid or "", "location": ""}
                for c in ok_items
            ],
        )
    except Exception:
        pass

    return CatalogResult(status=overall, cataloged=cataloged)


@router.get("/{slug}/diff")
async def get_survey_diff(slug: str) -> dict:
    """Compare the two most recent local survey runs for a repo.

    Returns None (empty dict) when fewer than two runs exist.
    """
    project, registry = _get_project_or_404(slug)
    history = registry.query_file_type_history(slug)
    if len(history) < 2:
        return {}

    curr_ts = history[-1]["surveyed_at"]
    prev_ts = history[-2]["surveyed_at"]

    def _counts_at(ts: str) -> dict[str, int]:
        with registry._conn() as conn:
            rows = conn.execute(
                "SELECT type_label, file_count FROM project_file_type_counts "
                "WHERE project_slug = ? AND surveyed_at = ?",
                (registry._normalize_slug(slug), ts),
            ).fetchall()
        return {r["type_label"]: r["file_count"] for r in rows}

    curr_counts = _counts_at(curr_ts)
    prev_counts = _counts_at(prev_ts)

    all_types = set(curr_counts) | set(prev_counts)
    changes = []
    for t in all_types:
        prev_v = prev_counts.get(t, 0)
        curr_v = curr_counts.get(t, 0)
        if curr_v != prev_v:
            pct = round((curr_v - prev_v) / prev_v * 100) if prev_v > 0 else None
            changes.append({"label": t, "prev": prev_v, "curr": curr_v,
                            "delta": curr_v - prev_v, "pct": pct})
    changes.sort(key=lambda c: abs(c["delta"]), reverse=True)

    total_curr = sum(curr_counts.values())
    total_prev = sum(prev_counts.values())

    return {
        "prev_date": prev_ts,
        "curr_date": curr_ts,
        "total_prev": total_prev,
        "total_curr": total_curr,
        "total_delta": total_curr - total_prev,
        "changes": changes[:10],
    }




