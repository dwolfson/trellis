"""Alias management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class AliasRequest(BaseModel):
    alias: str
    project_slug: str


@router.post("/")
async def add_alias(request: AliasRequest) -> dict:
    """Store a confirmed alias → project_slug mapping."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if not registry.exists(request.project_slug):
        raise HTTPException(status_code=404, detail=f"Project '{request.project_slug}' not found")
    registry.add_alias(request.alias, request.project_slug, confirmed_by="user")
    return {"alias": request.alias, "project_slug": request.project_slug, "saved": True}


@router.get("/{slug}")
async def list_aliases(slug: str) -> dict:
    """List all aliases for a project."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if not registry.exists(slug):
        raise HTTPException(status_code=404, detail=f"Project '{slug}' not found")
    return {"project_slug": slug, "aliases": registry.list_aliases(slug)}


@router.delete("/{alias}")
async def remove_alias(alias: str) -> dict:
    """Remove an alias."""
    from resource_explorer.registry import ProjectRegistry
    removed = ProjectRegistry().remove_alias(alias)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Alias '{alias}' not found")
    return {"alias": alias, "removed": True}
