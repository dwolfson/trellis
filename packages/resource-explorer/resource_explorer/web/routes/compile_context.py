"""Compile a context for a question — the packer's HTTP surface.

NOT to be confused with routes/context.py, which is the Resource context API
(human-provided metadata and RFA generation, backing the Enrichment intent).
Different concern, and the similar names are a hazard: this file exists under
this name because `context.py` was already taken.

Returns the manifest and the derivation alongside the text, deliberately. A
caller that only gets text cannot say why a section is there, what was dropped,
or what is missing — and those are the three things a person actually asks.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class CompileRequest(BaseModel):
    resource_slug: str
    question: str
    purposes: list[str] = []
    perspectives: list[str] = []
    #: Characters, not tokens. The caller owns the conversion, because only it
    #: knows which model the context is for.
    budget: int = 8000
    target_model: str = ""


class CompileResponse(BaseModel):
    text: str
    manifest: dict
    derivation: list[dict]


@router.post("/compile", response_model=CompileResponse)
async def compile_endpoint(request: CompileRequest) -> CompileResponse:
    from resource_explorer.context_compile import compile_context
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    if registry.get(request.resource_slug) is None:
        raise HTTPException(
            status_code=404, detail=f"Resource '{request.resource_slug}' not found"
        )
    try:
        compiled = compile_context(
            registry, request.resource_slug, request.question,
            purposes=request.purposes, perspectives=request.perspectives,
            budget=request.budget, target_model=request.target_model,
        )
    except Exception as exc:
        # A compile that cannot satisfy its own spec is a 422, not a 500: the
        # request was well-formed and the answer is "not within this budget".
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CompileResponse(
        text=compiled.text, manifest=compiled.manifest, derivation=compiled.derivation,
    )
