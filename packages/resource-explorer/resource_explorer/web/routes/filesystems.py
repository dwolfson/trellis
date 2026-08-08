"""Filesystem management endpoints — list, get, register, survey, remove."""
from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from resource_explorer.registry import FileSystemEntity, ProjectRegistry, ProjectStatus

log = logging.getLogger(__name__)
router = APIRouter()


class FileSystemSummary(BaseModel):
    """Summary information for a filesystem entity."""
    slug: str
    display_name: str
    local_mount_point: str
    canonical_mount_point: str
    description: str
    status: str
    last_surveyed_at: str
    egeria_asset_guid: str
    file_count: int
    data_file_count: int
    egeria_url: str = ""
    egeria_server: str = ""
    egeria_user: str = ""
    group_slug: str = ""


class FileSystemRegistration(BaseModel):
    """Request body for registering a new filesystem."""
    slug: str
    display_name: str
    local_mount_point: str
    canonical_mount_point: str = ""
    description: str = ""
    egeria_url: str = ""
    egeria_server: str = ""
    egeria_user: str = ""
    egeria_password: str = ""
    group_slug: str = ""


class FileSystemSurveyRequest(BaseModel):
    """Request body for running a filesystem survey."""
    mode: str = "hybrid"  # "local" | "hybrid" | "egeria"
    egeria_url: str | None = None
    egeria_server: str | None = None
    egeria_user: str | None = None
    egeria_password: str | None = None
    force_publish: bool = False


class EgeriaSurveyReportRow(BaseModel):
    """A SurveyReport as it actually exists in Egeria right now (live read via
    the real ReportSubject relationship). See databases.py's identical model
    and resource_explorer/surveyors/egeria_survey_reader.py."""
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


@router.get("/", response_model=list[FileSystemSummary])
def list_filesystems():
    """List all registered filesystems."""
    registry = ProjectRegistry()
    filesystems = registry.list_filesystems()
    
    result = []
    for fs in filesystems:
        latest = registry.get_latest_filesystem_survey(fs.slug)
        result.append(
            FileSystemSummary(
                slug=fs.slug,
                display_name=fs.display_name,
                local_mount_point=fs.local_mount_point,
                canonical_mount_point=fs.canonical_mount_point or "",
                description=fs.description,
                status=fs.status.value,
                last_surveyed_at=fs.last_surveyed_at or "",
                egeria_asset_guid=fs.egeria_asset_guid or "",
                file_count=fs.file_count,
                data_file_count=fs.data_file_count,
                egeria_url=fs.egeria_url or "",
                egeria_server=fs.egeria_server or "",
                egeria_user=fs.egeria_user or "",
                group_slug=getattr(fs, "group_slug", "") or "",
            )
        )
    return result


@router.post("/", response_model=FileSystemSummary)
def register_filesystem(registration: FileSystemRegistration):
    """Register a new filesystem connection."""
    registry = ProjectRegistry()
    
    if registry.filesystem_exists(registration.slug):
        raise HTTPException(
            status_code=400,
            detail=f"FileSystem '{registration.slug}' already registered."
        )

    # Create filesystem entity
    fs = FileSystemEntity(
        slug=registration.slug,
        display_name=registration.display_name,
        local_mount_point=registration.local_mount_point,
        canonical_mount_point=registration.canonical_mount_point,
        description=registration.description,
        egeria_url=registration.egeria_url,
        egeria_server=registration.egeria_server,
        egeria_user=registration.egeria_user,
        egeria_password=registration.egeria_password,
        group_slug=registration.group_slug,
    )
    
    try:
        registry.register_filesystem(fs)
    except Exception as exc:
        log.exception("Failed to register filesystem")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write to registry: {exc}"
        )
        
    return FileSystemSummary(
        slug=fs.slug,
        display_name=fs.display_name,
        local_mount_point=fs.local_mount_point,
        canonical_mount_point=fs.canonical_mount_point or "",
        description=fs.description,
        status=fs.status.value,
        last_surveyed_at="",
        egeria_asset_guid="",
        file_count=0,
        data_file_count=0,
        egeria_url=fs.egeria_url or "",
        egeria_server=fs.egeria_server or "",
        egeria_user=fs.egeria_user or "",
    )


@router.get("/{slug}/", response_model=FileSystemSummary)
def get_filesystem(slug: str):
    """Retrieve details for a specific registered filesystem."""
    registry = ProjectRegistry()
    fs = registry.get_filesystem(slug)
    if not fs:
        raise HTTPException(
            status_code=404,
            detail=f"FileSystem '{slug}' not found."
        )
        
    return FileSystemSummary(
        slug=fs.slug,
        display_name=fs.display_name,
        local_mount_point=fs.local_mount_point,
        canonical_mount_point=fs.canonical_mount_point or "",
        description=fs.description,
        status=fs.status.value,
        last_surveyed_at=fs.last_surveyed_at or "",
        egeria_asset_guid=fs.egeria_asset_guid or "",
        file_count=fs.file_count,
        data_file_count=fs.data_file_count,
        egeria_url=fs.egeria_url or "",
        egeria_server=fs.egeria_server or "",
        egeria_user=fs.egeria_user or "",
    )


@router.delete("/{slug}/")
def delete_filesystem(slug: str):
    """Remove a filesystem registration and all its surveys from the registry."""
    registry = ProjectRegistry()
    if not registry.filesystem_exists(slug):
        raise HTTPException(
            status_code=404,
            detail=f"FileSystem '{slug}' not found."
        )
    try:
        registry.remove_filesystem(slug)
        return {"status": "ok", "message": f"FileSystem '{slug}' removed."}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete filesystem '{slug}': {exc}"
        )


@router.post("/{slug}/survey")
def survey_filesystem(slug: str, req: FileSystemSurveyRequest):
    """Run a local or hybrid survey on the filesystem, optionally publishing to Egeria."""
    registry = ProjectRegistry()
    fs_entity = registry.get_filesystem(slug)
    if not fs_entity:
        raise HTTPException(
            status_code=404,
            detail=f"FileSystem '{slug}' not found."
        )

    # 1. Update status to active/surveying
    registry.update_filesystem_status(slug, ProjectStatus.ACTIVE)

    # 2. Run local or hybrid walk
    try:
        if req.mode == "local":
            from resource_explorer.surveyors.filesystem.local_filesystem_surveyor import (
                LocalFileSystemSurveyor,
                build_rfa_annotations,
            )
            local_surveyor = LocalFileSystemSurveyor(fs_entity, registry)
            res = local_surveyor.run()

            # Save local-only survey
            registry.add_filesystem_survey(
                fs_slug=slug,
                surveyed_at=res["surveyed_at"],
                survey_data=res,
                egeria_report_guid="local-only",
                source="local",
            )

            annotations = build_rfa_annotations(res)
            try:
                from resource_explorer.activity_logger import log_survey
                log_survey(
                    registry,
                    entity_type="filesystem",
                    entity_slug=slug,
                    entity_name=fs_entity.display_name,
                    entity_location=fs_entity.local_mount_point,
                    intent="assessment",
                    status="error" if annotations else "ok",
                    summary=f"FileSystem survey: {res['total_files']} files ({res['total_data_files']} data files)",
                    detail=f"Walked {fs_entity.local_mount_point}. Total size {res['total_size']}.",
                    annotations=annotations,
                )
            except Exception:
                log.exception(f"Failed to write activity log entry for filesystem survey {slug}")

            return {
                "status": "ok",
                "mode": "local",
                "total_files": res["total_files"],
                "total_data_files": res["total_data_files"],
                "total_size": res["total_size"],
            }
            
        elif req.mode in ("hybrid", "egeria"):
            from resource_explorer.surveyors.filesystem.hybrid_filesystem_surveyor import run_hybrid_filesystem_survey
            res = run_hybrid_filesystem_survey(
                filesystem_slug=slug,
                registry=registry,
                egeria_url=req.egeria_url,
                egeria_server=req.egeria_server,
                egeria_user=req.egeria_user,
                egeria_password=req.egeria_password,
                force_egeria_publish=req.force_publish or (req.mode == "egeria"),
            )
            
            publish_info = res.get("egeria_publish") or {}
            
            return {
                "status": "ok",
                "mode": req.mode,
                "total_files": res["total_files"],
                "total_data_files": res["total_data_files"],
                "total_size": res["total_size"],
                "egeria_asset_guid": publish_info.get("filesystem_guid", ""),
                "egeria_report_guid": publish_info.get("report_guid", ""),
                "annotation_count": publish_info.get("annotation_count", 0),
            }
            
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported survey mode '{req.mode}'")
            
    except Exception as exc:
        log.exception(f"Filesystem survey failed for {slug}")
        registry.update_filesystem_status(slug, ProjectStatus.ERROR, str(exc))
        raise HTTPException(
            status_code=500,
            detail=f"Survey execution failed: {exc}"
        )


@router.get("/{slug}/surveys")
def list_filesystem_surveys(slug: str):
    """Retrieve history of surveys for a filesystem."""
    registry = ProjectRegistry()
    if not registry.filesystem_exists(slug):
        raise HTTPException(
            status_code=404,
            detail=f"FileSystem '{slug}' not found."
        )
    return registry.list_filesystem_surveys(slug)


@router.get("/{slug}/surveys/latest")
def get_latest_survey(slug: str):
    """Retrieve the latest complete survey for a filesystem."""
    registry = ProjectRegistry()
    survey = registry.get_latest_filesystem_survey(slug)
    if not survey:
        raise HTTPException(
            status_code=404,
            detail=f"No survey history found for filesystem '{slug}'."
        )
    return survey


@router.get("/{slug}/egeria-surveys", response_model=list[EgeriaSurveyReportRow])
def get_filesystem_egeria_surveys(slug: str) -> list[EgeriaSurveyReportRow]:
    """List SurveyReports that actually exist in Egeria right now for this
    filesystem (a live read via the real ReportSubject relationship)."""
    from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import (
        EgeriaFileSystemSurveyor,
        EgeriaFileSystemSurveyorError,
    )

    registry = ProjectRegistry()
    fs = registry.get_filesystem(slug)
    if not fs:
        raise HTTPException(status_code=404, detail=f"FileSystem '{slug}' not found.")
    if not fs.egeria_asset_guid:
        return []  # not yet cataloged in Egeria — nothing to walk from

    surveyor = EgeriaFileSystemSurveyor()
    try:
        reports = surveyor.get_survey_reports_by_guid(fs.egeria_asset_guid)
    except EgeriaFileSystemSurveyorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [EgeriaSurveyReportRow(**r) for r in reports]


@router.get("/{slug}/egeria-surveys/{report_guid}/annotations", response_model=list[EgeriaAnnotationItem])
def get_filesystem_egeria_annotations(slug: str, report_guid: str) -> list[EgeriaAnnotationItem]:
    """Fetch all annotations for a specific live Egeria SurveyReport, by the
    report's own GUID."""
    from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import (
        EgeriaFileSystemSurveyor,
        EgeriaFileSystemSurveyorError,
    )

    registry = ProjectRegistry()
    fs = registry.get_filesystem(slug)
    if not fs:
        raise HTTPException(status_code=404, detail=f"FileSystem '{slug}' not found.")

    surveyor = EgeriaFileSystemSurveyor()
    try:
        annotations = surveyor.get_annotations_by_report_guid(report_guid)
    except EgeriaFileSystemSurveyorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [EgeriaAnnotationItem(**a) for a in annotations]


@router.post("/{slug}/publish")
def publish_survey_to_egeria(slug: str, req: FileSystemSurveyRequest):
    """Manually publish the latest local filesystem survey details to Egeria."""
    registry = ProjectRegistry()
    fs_entity = registry.get_filesystem(slug)
    if not fs_entity:
        raise HTTPException(
            status_code=404,
            detail=f"FileSystem '{slug}' not found."
        )

    survey = registry.get_latest_filesystem_survey(slug)
    if not survey:
        raise HTTPException(
            status_code=400,
            detail="No local survey results available to publish. Run a survey first."
        )

    url = req.egeria_url or fs_entity.egeria_url or ""
    server = req.egeria_server or fs_entity.egeria_server or ""
    user = req.egeria_user or fs_entity.egeria_user or ""
    pwd = req.egeria_password or fs_entity.egeria_password or ""

    if not (url and server and user and pwd):
        raise HTTPException(
            status_code=400,
            detail="Missing Egeria credentials (url, server, user, password)."
        )

    try:
        from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import EgeriaFileSystemSurveyor
        egeria_surveyor = EgeriaFileSystemSurveyor(
            platform_url=url,
            view_server=server,
            user_id=user,
            user_password=pwd,
        )
        publish_res = egeria_surveyor.catalog_and_survey(fs_entity, survey["survey_data"], registry=registry)
        return {
            "status": "ok",
            "egeria_asset_guid": publish_res.get("filesystem_guid", ""),
            "egeria_report_guid": publish_res.get("report_guid", ""),
            "annotation_count": publish_res.get("annotation_count", 0),
        }
    except Exception as exc:
        log.exception(f"Manual filesystem publish failed for {slug}")
        raise HTTPException(
            status_code=500,
            detail=f"Publish failed: {exc}"
        )
