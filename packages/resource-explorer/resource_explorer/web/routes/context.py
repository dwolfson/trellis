"""Resource context API — store and retrieve human-provided metadata."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from resource_explorer.auth import get_current_user

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


class QuestionAnswer(BaseModel):
    """One human answer to one catalog question.

    The question TEXT is stored alongside the answer, not just used as the
    key. The catalog has no stable question id — `question_catalog.yaml`
    entries carry question/stage/perspectives/purposes/answering and nothing
    identifying — so the key here is a slug derived from the wording. Reword
    the CSV and the slug changes, which would orphan the answer.

    Storing the text makes that orphaning visible and recoverable rather than
    silent: the answer is still there, still readable, and still says which
    question it was given for. A stable id in the catalog would be the real
    fix; this records why it is wanted.
    """
    question: str = ""
    answer: str = ""
    answered_at: str = ""


class EnrichmentField(BaseModel):
    """One enrichment field as testimony, not paperwork.

    Two kinds, and the kind is not configuration — a field is a JUDGEMENT if
    a person's opinion is the value (sensitivity, criticality, intended use,
    actual use, owner, notes) and an OBSERVATION if a person is supplying a
    fact about the world (licence, environment, retention). Judgements are
    perishable: they carry an author, a date, and the measurements that were
    on screen when they were made, so that when those measurements move the
    judgement is not invalidated but FLAGGED for review, and the flag can say
    what moved. Observations carry a source instead.

    `author` and `set_at` are stamped by the server from the signed-in
    identity, never taken from the client: testimony without an author is
    not testimony, and an author the client asserts is not an author.
    """
    value: str = ""
    kind: str = "judgement"          # judgement | observation
    author: str = ""                 # server-stamped
    set_at: str = ""                 # server-stamped, ISO
    source: str = ""                 # observations: where the fact came from ("license_classification", "user")
    # analysis_id -> last_run_at, as shown when the judgement was made.
    evidence: dict[str, str] = Field(default_factory=dict)
    interim: bool = False            # owner only: the investigator standing in


class FieldWrite(BaseModel):
    key: str
    value: str = ""
    kind: str = "judgement"
    source: str = ""
    evidence: dict[str, str] = Field(default_factory=dict)
    interim: bool = False


# The flat keys `/`'s form reads, mirrored from the enrichment record so the
# two UIs keep agreeing on the fields they share.
_MIRROR = {"sensitivity": "sensitivity", "environment": "environment",
           "owner": "org_owner", "intended_use": "purpose", "notes": "notes"}


class ContextData(BaseModel):
    environment:           str = ""   # production | staging | dev | research | archive | unknown
    org_owner:             str = ""
    geographic_location:   str = ""
    responsible_steward:   str = ""
    backup_status:         str = ""   # yes | no | partial | unknown
    sensitivity:           str = ""   # public | internal | confidential | restricted | unknown
    purpose:               str = ""   # free text — what is this resource for?
    notes:                 str = ""   # free text — anything else
    # Answers to the catalog's Human-Supplied questions, keyed by a slug of
    # the question text (see QuestionAnswer). Deliberately separate from the
    # fixed fields above: those are the catalog-time asset record
    # (environment, sensitivity, backup status, location), and NONE of them
    # appears in the question catalog. These are the seven questions the
    # catalog actually asks a human — dependencies, cost, skills, monitoring,
    # security, governance, estate fit — which had nowhere to be stored.
    question_answers: dict[str, QuestionAnswer] = {}
    # Enrichment as testimony (2026-09-11): each field with its kind, its
    # author and date, and the evidence on screen when a judgement was made.
    # See EnrichmentField. Saved one field at a time through PATCH .../field.
    enrichment: dict[str, EnrichmentField] = {}


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


@router.patch("/{entity_type}/{slug}/field")
def save_field(entity_type: str, slug: str, write: FieldWrite, request: Request) -> dict:
    """Save ONE enrichment field. Eight independent facts should not share a
    Save: a person who knows the owner and not the sensitivity can say so
    and leave. Read-modify-write on the server, so two people setting two
    fields do not clobber each other the way two whole-document POSTs would.

    The author is the signed-in user, stamped here. Anonymous writes are
    refused with 401 rather than recorded as nobody's: a judgement with no
    author is the thing this model exists to prevent.
    """
    user = get_current_user(request)
    author = (user or {}).get("user_id") or (user or {}).get("sub") or (user or {}).get("username") or ""
    if not author:
        raise HTTPException(status_code=401, detail="Sign in to record enrichment — a judgement needs an author.")
    if write.kind not in ("judgement", "observation"):
        raise HTTPException(status_code=422, detail="kind must be judgement or observation")
    key = write.key.strip().lower().replace(" ", "_")
    if not key or len(key) > 64:
        raise HTTPException(status_code=422, detail="key is required")

    registry = ProjectRegistry()
    context = registry.get_context(entity_type, slug) or {}
    fields = dict(context.get("enrichment") or {})
    fields[key] = EnrichmentField(
        value=write.value.strip(), kind=write.kind, author=author,
        set_at=datetime.now(timezone.utc).isoformat(), source=write.source.strip(),
        evidence=dict(write.evidence), interim=bool(write.interim),
    ).model_dump()
    context["enrichment"] = fields
    if key in _MIRROR:
        context[_MIRROR[key]] = write.value.strip()
    context["updated_at"] = datetime.now(timezone.utc).isoformat()
    registry.save_context(entity_type, slug, context)
    return {"key": key, "field": fields[key]}
