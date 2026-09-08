"""
Plan-template API routes for Egeria Advisor.

Extracted from `app.py` (TC-5, BACKLOG.md — router-per-domain refactor,
slice 3). Fully self-contained — no dependency on `advisor.web.shared`.

Endpoints:
  GET    /api/plan-templates        → list available plan templates
  DELETE /api/plan-templates/{name} → delete a plan template by name
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/plan-templates")
async def list_plan_templates() -> Dict[str, Any]:
    """Return available plan templates."""
    from advisor.plan_templates import get_template_manager
    return {"templates": get_template_manager().list_templates()}


@router.delete("/api/plan-templates/{name}")
async def delete_plan_template(name: str) -> Dict[str, str]:
    """Delete a plan template by name."""
    from urllib.parse import unquote
    from advisor.plan_templates import get_template_manager
    deleted = get_template_manager().delete(unquote(name))
    return {"status": "ok" if deleted else "not_found"}
