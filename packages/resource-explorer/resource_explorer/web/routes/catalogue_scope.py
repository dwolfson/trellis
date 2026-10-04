"""Catalogue scope API: what gets catalogued for a database (slice A).

A declared, signed, dated choice stored in RE. Every write route resolves the
author from the session first and answers 401 when nobody is signed in (the
same posture as the Curate author routes); the request bodies have no author
field. Nothing here writes to Egeria and nothing here compiles a list for
Egeria's cataloguer: that is slice B. See `resource_explorer.catalogue_scope`.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from resource_explorer import catalogue_scope as scope
from resource_explorer.auth import get_current_user
from resource_explorer.registry import ProjectRegistry

router = APIRouter()


def _require_author(request: Request, action: str) -> str:
    user = get_current_user(request)
    author = (user or {}).get("user_id") or (user or {}).get("sub") or (user or {}).get("username") or ""
    if not author:
        raise HTTPException(
            status_code=401,
            detail=f"Sign in to {action}: a catalogue scope choice needs an author.",
        )
    return author


def _registry_for(slug: str) -> ProjectRegistry:
    registry = ProjectRegistry()
    if not registry.get_database(slug, allow_unreadable=True):
        raise HTTPException(status_code=404, detail=f"Database '{slug}' not found")
    return registry


class NodeBody(BaseModel):
    schema_name: str
    table_name: str = ""
    choice: str = ""


class DepthBody(BaseModel):
    depth: str


class ResolveBody(BaseModel):
    name: str
    choice: str


async def _run(fn, *args, **kwargs):
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except scope.ScopeError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.get("/{slug}")
async def read_scope(slug: str) -> dict:
    registry = _registry_for(slug)
    view = await asyncio.to_thread(scope.build_scope_view, registry, slug)
    entity = registry.get_database(slug, allow_unreadable=True)
    guid = getattr(entity, "egeria_asset_guid", "") or ""
    view["egeria_element"] = {"guid": guid, "short": guid[:8],
                              "text": guid[:8] if guid else "not catalogued in Egeria"}
    return view


@router.get("/{slug}/conflicts")
async def read_conflicts(slug: str) -> dict:
    registry = _registry_for(slug)
    return await asyncio.to_thread(scope.scope_conflicts, registry, slug)


@router.get("/{slug}/new-since")
async def read_new_since(slug: str) -> dict:
    registry = _registry_for(slug)
    return await asyncio.to_thread(scope.new_since_declared, registry, slug)


@router.get("/{slug}/history")
async def read_history(slug: str) -> dict:
    registry = _registry_for(slug)
    return {"events": registry.list_catalogue_scope_events(slug),
            "declarations": registry.list_catalogue_scope_baselines(slug)}


@router.put("/{slug}/depth")
async def put_depth(slug: str, body: DepthBody, request: Request) -> dict:
    author = _require_author(request, "choose a depth")
    registry = _registry_for(slug)
    return await _run(scope.set_depth, registry, slug, author, depth=body.depth)


@router.put("/{slug}/node")
async def put_node(slug: str, body: NodeBody, request: Request) -> dict:
    author = _require_author(request, "choose what gets catalogued")
    registry = _registry_for(slug)
    return await _run(scope.set_node_choice, registry, slug, author,
                      schema=body.schema_name, table=body.table_name, choice=body.choice)


@router.post("/{slug}/node/confirm")
async def post_confirm(slug: str, body: NodeBody, request: Request) -> dict:
    author = _require_author(request, "confirm a proposal")
    registry = _registry_for(slug)
    return await _run(scope.confirm_proposal, registry, slug, author,
                      schema=body.schema_name, table=body.table_name)


@router.post("/{slug}/node/override")
async def post_override(slug: str, body: NodeBody, request: Request) -> dict:
    author = _require_author(request, "override a proposal")
    registry = _registry_for(slug)
    return await _run(scope.override_proposal, registry, slug, author,
                      schema=body.schema_name, table=body.table_name)


@router.post("/{slug}/node/clear")
async def post_clear(slug: str, body: NodeBody, request: Request) -> dict:
    author = _require_author(request, "clear a choice")
    registry = _registry_for(slug)
    return await _run(scope.clear_node_choice, registry, slug, author,
                      schema=body.schema_name, table=body.table_name)


@router.post("/{slug}/redeclare")
async def post_redeclare(slug: str, request: Request) -> dict:
    author = _require_author(request, "declare the scope")
    registry = _registry_for(slug)
    return await _run(scope.redeclare, registry, slug, author)


@router.post("/{slug}/resolve")
async def post_resolve(slug: str, body: ResolveBody, request: Request) -> dict:
    author = _require_author(request, "resolve a name conflict")
    registry = _registry_for(slug)
    return await _run(scope.resolve_conflict, registry, slug, author,
                      name=body.name, choice=body.choice)
