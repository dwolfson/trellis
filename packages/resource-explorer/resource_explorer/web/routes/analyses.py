"""Analysis catalog API routes."""
from __future__ import annotations

from fastapi import APIRouter, Query

from resource_explorer.analysis_catalog import get_analyses, list_perspectives

router = APIRouter()


from pydantic import BaseModel, Field
from fastapi import APIRouter, Query, HTTPException


class AnnotationTypeRegisterRequest(BaseModel):
    annotation_type: str = Field(..., alias="type")
    display_name: str
    description: str = ""
    properties: list[str] = []
    egeria_type: str = ""
    python_class: str = ""

    class Config:
        populate_by_name = True


class AnnotationTypeUpdateRequest(BaseModel):
    display_name: str
    description: str = ""
    properties: list[str] = []
    egeria_type: str = ""
    python_class: str = ""


@router.get("/annotation-types")
def list_annotation_types() -> list[dict]:
    """Return all known annotation types, their descriptions and properties."""
    from resource_explorer.registry import ProjectRegistry
    raw_list = ProjectRegistry().list_annotation_types()
    # Translate database column names to match the old frontend JSON interface:
    # "annotation_type" becomes "type"
    translated = []
    for item in raw_list:
        d = dict(item)
        d["type"] = d.pop("annotation_type")
        translated.append(d)
    return translated


@router.get("/annotation-types/{type_name}")
def get_annotation_type(type_name: str) -> dict:
    """Return details of a specific annotation type."""
    from resource_explorer.registry import ProjectRegistry
    item = ProjectRegistry().get_annotation_type(type_name)
    if not item:
        raise HTTPException(status_code=404, detail="Annotation type not found")
    d = dict(item)
    d["type"] = d.pop("annotation_type")
    return d


@router.post("/annotation-types")
def register_annotation_type(body: AnnotationTypeRegisterRequest) -> dict:
    """Register a new annotation type in the metadata catalog."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if registry.get_annotation_type(body.annotation_type):
        raise HTTPException(status_code=400, detail="Annotation type already registered")
    registry.register_annotation_type(
        annotation_type=body.annotation_type,
        display_name=body.display_name,
        description=body.description,
        properties=body.properties,
        egeria_type=body.egeria_type,
        python_class=body.python_class,
    )
    return {"status": "success"}


@router.put("/annotation-types/{type_name}")
def update_annotation_type(type_name: str, body: AnnotationTypeUpdateRequest) -> dict:
    """Update an existing annotation type details."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if not registry.get_annotation_type(type_name):
        raise HTTPException(status_code=404, detail="Annotation type not found")
    registry.update_annotation_type(
        annotation_type=type_name,
        display_name=body.display_name,
        description=body.description,
        properties=body.properties,
        egeria_type=body.egeria_type,
        python_class=body.python_class,
    )
    return {"status": "success"}


@router.delete("/annotation-types/{type_name}")
def delete_annotation_type(type_name: str) -> dict:
    """Remove an annotation type from the catalog."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if not registry.get_annotation_type(type_name):
        raise HTTPException(status_code=404, detail="Annotation type not found")
    registry.delete_annotation_type(type_name)
    return {"status": "success"}


@router.get("/perspectives")
def list_perspectives_route() -> list[str]:
    """Distinct perspective values actually in the catalog — backs the UI's
    perspective selector so it's never a hardcoded, silently-stale list.
    NOTE: declared before /{resource_type} deliberately — Starlette matches
    routes in declaration order, so a literal path after a path-param catch-all
    at the same position would never be reached."""
    return list_perspectives()


@router.get("/{resource_type}")
def list_analyses(
    resource_type: str,
    intent: str | None = Query(None),
    perspective: str | None = Query(None),
) -> list[dict]:
    """Return available analyses for a resource type.

    resource_type: 'repo' | 'database'
    intent:       scouting | assessment | discovery | enrichment
    perspective:  all | dba | data_scientist | steward | security
    """
    return get_analyses(resource_type, intent=intent, perspective=perspective)
