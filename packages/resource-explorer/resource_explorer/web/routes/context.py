"""Resource context API — store and retrieve human-provided metadata."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from resource_explorer.activity_logger import log_rfa
from resource_explorer.registry import ProjectRegistry

router = APIRouter()

# Fields that are considered critical; blank value → auto-generate an RFA
_CRITICAL_FIELDS: dict[str, str] = {
    "environment":           "What environment is this resource used in? (production / staging / dev / research / archive)",
    "sensitivity":           "What is the sensitivity classification of this resource?",
    "responsible_steward":   "Who is the responsible data steward for this resource?",
    "org_owner":             "Which team or department owns this resource?",
}


class ContextData(BaseModel):
    environment:           str = ""   # production | staging | dev | research | archive | unknown
    org_owner:             str = ""
    geographic_location:   str = ""
    responsible_steward:   str = ""
    backup_status:         str = ""   # yes | no | partial | unknown
    sensitivity:           str = ""   # public | internal | confidential | restricted | unknown
    purpose:               str = ""   # free text — what is this resource for?
    notes:                 str = ""   # free text — anything else


@router.get("/{entity_type}/{slug}")
def get_context(entity_type: str, slug: str) -> dict:
    """Return stored context for a resource. Returns {} if none saved yet."""
    return ProjectRegistry().get_context(entity_type, slug) or {}


@router.post("/{entity_type}/{slug}")
def save_context(entity_type: str, slug: str, data: ContextData) -> dict:
    """Save context for a resource.

    Any critical field left blank generates an enrichment RFA in the activity log
    so it shows up in the RFA panel as an open question.
    """
    registry = ProjectRegistry()
    context = data.model_dump()
    context["updated_at"] = datetime.now(timezone.utc).isoformat()
    registry.save_context(entity_type, slug, context)

    # Auto-generate RFAs for blank critical fields
    rfa_fields: list[str] = []
    for field_name, question in _CRITICAL_FIELDS.items():
        if not context.get(field_name):
            rfa_fields.append(field_name)
            try:
                log_rfa(
                    registry=registry,
                    entity_type=entity_type,
                    entity_slug=slug,
                    entity_name=slug,
                    rfa_operation="context_form",
                    status="pending",
                    summary=question,
                    detail=f"Context field '{field_name}' was not provided.",
                )
            except Exception:
                pass  # never block save on log failure

    return {
        "status": "ok",
        "context": context,
        "rfa_fields": rfa_fields,
    }
