"""The API reference of a repository: read it, and register / re-check / clear a running instance's OpenAPI URL.

GET    /api/api-reference/{slug}                    every known source (committed spec, running instance,
                                                    derived from code), which is best, how they differ, and what
                                                    is missing and why
PUT    /api/api-reference/{slug}/instance           {url}: fetch read-only, keep only a real OpenAPI document
POST   /api/api-reference/{slug}/instance/refetch   re-check the registered URL
DELETE /api/api-reference/{slug}/instance           forget the URL and the stored copy

A rejected URL is an ANSWER (HTTP 200, `ok: false`, `reason`: "not an OpenAPI document: got text/html"), not a
fault, so the control can show the sentence beside the field.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from resource_explorer.api_reference import live, service
from resource_explorer.auth import get_current_user
from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)
router = APIRouter()


def _registry() -> ProjectRegistry:
    return ProjectRegistry()


def _transport():
    """None in production (a real network client); tests substitute an httpx transport."""
    return None


class InstanceBody(BaseModel):
    url: str


def _repo(registry: ProjectRegistry, slug: str) -> None:
    if registry.get(slug) is None:
        raise HTTPException(status_code=404, detail=f"repository '{slug}' not found")


@router.get("/{slug}")
def get_reference(slug: str) -> dict:
    registry = _registry()
    _repo(registry, slug)
    return service.build_reference(registry, slug)


@router.put("/{slug}/instance")
def register_instance(slug: str, body: InstanceBody, request: Request) -> dict:
    registry = _registry()
    _repo(registry, slug)
    user = get_current_user(request) or {}
    by = user.get("user_id") or user.get("sub") or user.get("username") or ""
    return live.register_instance(registry, slug, body.url, by=by, transport=_transport())


@router.post("/{slug}/instance/refetch")
def refetch_instance(slug: str) -> dict:
    registry = _registry()
    _repo(registry, slug)
    return live.refetch_instance(registry, slug, transport=_transport())


@router.delete("/{slug}/instance")
def clear_instance(slug: str) -> dict:
    registry = _registry()
    _repo(registry, slug)
    return {"cleared": live.clear_instance(registry, slug)}
