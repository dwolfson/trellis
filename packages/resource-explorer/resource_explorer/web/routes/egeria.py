"""Egeria integration endpoints — asset registration, survey history, publish."""
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException
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
    # the Profile tab, etc.) publish only what it actually knows, as its own
    # SurveyReport linked to the same asset, rather than one all-or-nothing
    # publish. Same step-key vocabulary as REPO_ANALYSIS_STEP_MAP.
    steps: list[str] | None = None


@router.post("/{slug}/publish", response_model=PublishResult)
async def publish_survey(slug: str, req: PublishRequest | None = None) -> PublishResult:
    """Run a survey (full, or scoped to req.steps) then publish the result to Egeria.

    The survey and publish steps both call blocking synchronous code (pyegeria's
    sync wrappers use loop.run_until_complete internally).  Running them inside
    FastAPI's async event loop would cause "Can't patch loop" errors, so both
    steps are offloaded to a thread pool via asyncio.to_thread().
    """
    project, registry = _get_project_or_404(slug)

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




