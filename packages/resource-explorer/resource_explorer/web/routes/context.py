"""Resource context API — store and retrieve human-provided metadata."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from resource_explorer.auth import get_current_user

from resource_explorer.activity_logger import log_rfa
from resource_explorer import retention_basis
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
    # ENRICHMENT-E0-ROW-ANATOMY (REPLY-DESIGNER-ENRICHMENT-STAGE-IA.md §0.3):
    # this used to be the one store in the resource-context "three stores,
    # three rules" table with no author field at all — the Questions tab
    # showed "answered 2d ago", breaking the reply's own stated rule that
    # "a human-supplied answer carries who and when." Server-stamped from
    # the signed-in identity in `save_answer` below, never taken from the
    # client, same reasoning as `EnrichmentField.author` below. Blank on any
    # answer recorded before this field existed — that is a real, honest
    # gap (nobody was ever asked who), not something to backfill with a
    # guess.
    answered_by: str = ""


class EnrichmentField(BaseModel):
    """One enrichment field as testimony, not paperwork.

    Two kinds, and the kind is not configuration — a field is a JUDGEMENT if
    a person's opinion is the value (sensitivity, criticality, intended use,
    actual use, owner, notes) and an OBSERVATION if a person is supplying a
    fact about the world (license, environment, retention). Judgements are
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
    # ENRICHMENT-E3, observations with a proposing analysis only (licence):
    # what the survey measured when this row was written, stamped by the
    # SERVER from its own fact layer -- never taken from the client. The row's
    # observation state (proposed / confirmed / overridden / survey-now-
    # disagrees) is derived by comparing a LATER measurement with this one,
    # never with the person's own value. Empty when nothing was measured.
    measured_value: str = ""
    measured_at: str = ""
    # Free text beside a value. Retention: `value` is the basis enum name and the old
    # "how long, and under whose rule?" text lives here. Absent on older rows (reads as "").
    note: str = ""


class FieldWrite(BaseModel):
    key: str
    value: str = ""
    kind: str = "judgement"
    source: str = ""
    evidence: dict[str, str] = Field(default_factory=dict)
    interim: bool = False
    note: str = ""


class AnswerWrite(BaseModel):
    question: str
    answer: str = ""


def question_key(text: str) -> str:
    """Slug for one catalog question — the SAME rule as the client's
    `questionKey()` in `re-api.js` (lowercase, non-alphanumerics collapsed
    to `-`, trimmed, capped at 80 chars), so a key computed here for a
    server-stamped write matches a key the client already computed for a
    read. Duplicated rather than shared because the two run in different
    languages; see `QuestionAnswer`'s own docstring for why the key is a
    slug of the wording rather than a stable catalog id."""
    key = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return key[:80]


# The flat keys `/`'s form reads, mirrored from the enrichment record so the
# two UIs keep agreeing on the fields they share.
_MIRROR = {"sensitivity": "sensitivity", "environment": "environment",
           "owner": "org_owner", "intended_use": "purpose", "notes": "notes",
           # PI-098: the Next Context tab's steward, location and backup status share Classic's flat keys.
           "steward": "responsible_steward", "location": "geographic_location",
           "backup_status": "backup_status"}

#: Classic's backup-status select, enforced here too so a Next write cannot store a value Classic cannot show.
BACKUP_STATUSES = ("yes", "no", "partial", "unknown")


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


@router.get("/{entity_type}/{slug}/enrichment-analyses")
def get_enrichment_analyses(entity_type: str, slug: str) -> dict:
    """The Enrichment stage's "Survey & analyses" map (ENRICHMENT-E1-
    CONTEXT-TAB, 2026-09-29 amendment): every catalog entry tagged
    `intent: enrichment` for this resource type, each with its current
    unlock state.

    "No analysis runs at the Enrichment stage from a survey read. What you
    supply here unlocks: ..." — the reply's own premise (§0.2) corrected by
    the project owner the same day: a class of analysis DOES run here, gated
    on a human input rather than a survey read. This route computes that
    state server-side, through the SAME prerequisite-resolver machinery
    (`step_preconditions.human_input_state`) every other precondition in
    this codebase goes through, rather than a parallel client-side guess.

    A resource type with no `intent: enrichment` entries (repo, filesystem,
    today) returns an empty list honestly — that is the map having nothing
    to say, not a failure to read one.
    """
    import types

    from resource_explorer.facts import FactLayer
    from resource_explorer.surveyors import analysis_catalog_reader as acr
    from resource_explorer.surveyors import step_preconditions

    entries = acr.get_analyses(entity_type, intent="enrichment", include_egeria_live=False)
    registry = ProjectRegistry()
    project = types.SimpleNamespace(slug=slug)
    fl = FactLayer(registry, resource_type=entity_type)
    rows = []
    for entry in entries:
        requires_input = entry.get("requires_input") or ""
        if requires_input:
            present, reason = step_preconditions.human_input_state(registry, project, requires_input)
        else:
            # Declared intent: enrichment with no requires_input is a catalog
            # authoring gap, not "always available" — the same conservative
            # default every check above takes.
            present, reason = False, "no requires_input declared for this analysis"
        # "locked" | "unlocked" | "measured" — the third only ever reachable
        # from "unlocked" (a locked prerequisite that somehow has a stored
        # result is a contradiction worth surfacing as unlocked+stale rather
        # than measured, so a card never reads as done while its own
        # unlock condition currently fails).
        card_state = "locked"
        if present:
            card_state = "unlocked"
            try:
                fact = fl.fact(slug, entry["id"])
                if getattr(fact, "state", "") in ("measured", "automatic", "answered"):
                    card_state = "measured"
            except Exception:
                pass  # no results reader for a stub id — stays "unlocked"
        # Whether the per-card Run route can dispatch this analysis. Computed
        # from the run maps themselves (the same predicate the run route
        # validates with), so a Run control is never offered for an analysis
        # with no runner (doc_source_ingestion: slice 2 was never built).
        if entity_type == "database":
            from resource_explorer.surveyors.database.database_surveyor import database_analysis_has_runner
            runnable = database_analysis_has_runner(entry["id"])
        else:
            runnable = False
        rows.append({
            "id": entry["id"],
            "name": entry["name"],
            "runnable": runnable,
            "requires_input": requires_input,
            "unlocked": present,
            "reason": reason,
            "state": card_state,
        })
    return {"analyses": rows}


@router.post("/{entity_type}/{slug}")
async def save_context(entity_type: str, slug: str, data: ContextData, request: Request) -> dict:
    """Save context for a resource.

    Any critical field left blank generates an enrichment RFA in the activity log
    so it shows up in the RFA panel as an open question.

    `enrichment` and `question_answers` are saved one-at-a-time elsewhere
    (PATCH .../field, and saveQuestionAnswer's own read-modify-write) and
    both default to `{}` on `ContextData` when a caller's body omits them —
    which the classic `/` Context form's `saveContextForm` always does, since
    it only ever sends the fixed fields it renders. Passing that request's
    `ContextData` straight to `model_dump()` would erase every enrichment
    judgement and human answer recorded through `/next` the next time someone
    saves the classic form. So: only replace either collection when the
    caller's raw body actually names it; otherwise keep what is already on
    record. A caller that DOES mean to clear one sends `{"enrichment": {}}`
    explicitly (still `{}`, but now present in the body), which this still
    honours.
    """
    registry = ProjectRegistry()
    raw = await request.json()
    context = data.model_dump()
    existing = registry.get_context(entity_type, slug) or {}
    if "enrichment" not in raw:
        context["enrichment"] = existing.get("enrichment", {})
    if "question_answers" not in raw:
        context["question_answers"] = existing.get("question_answers", {})
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


#: The only proposing pairs: observation key -> the analysis that measures the
#: same fact. Judgements (sensitivity, owner, ...) are never here -- a survey
#: can be material for a judgement, never a proposal for it.
PROPOSING_ANALYSES = {"licence": "license_classification"}


def licence_value_from_fact(fact) -> str:
    """The licence a `license_classification` fact measured, or "" -- the
    Python twin of enrichment.js `proposedFrom`. Gated on a CLASSIFIED licence:
    "none" is a measured finding too, and is not a licence name."""
    if getattr(fact, "state", "") != "measured":
        return ""
    value = getattr(fact, "value", None) or {}
    tier = next((x for x in (value.get("findings") or []) if x.get("check_name") == "license_risk_tier"), None)
    if not tier or not tier.get("label") or str(tier.get("label")) == "none":
        return ""
    raw = tier.get("summary") or getattr(fact, "headline", "") or ""
    if " \u2014 " not in raw:
        return ""
    return str(raw).split(" \u2014 ")[0].strip()


def measured_for(registry, entity_type: str, slug: str, key: str) -> tuple[str, str]:
    """(value, run time) the proposing analysis measures for `key` right now;
    ("", "") when there is no proposing pair, the analysis does not apply to
    this kind, or nothing classified has been measured."""
    analysis_id = PROPOSING_ANALYSES.get(key)
    if not analysis_id:
        return "", ""
    try:
        from resource_explorer.facts import FactLayer
        from resource_explorer.surveyors import analysis_catalog_reader as acr

        if analysis_id not in {a["id"] for a in acr.get_analyses(entity_type)}:
            return "", ""
        fact = FactLayer(registry, resource_type=entity_type).fact(slug, analysis_id)
        value = licence_value_from_fact(fact) if key == "licence" else ""
        return (value, getattr(fact, "last_run_at", "") or "") if value else ("", "")
    except Exception:
        return "", ""  # an unreadable measurement is absence, never a blocked save


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

    if key == "retention" and write.value.strip() and write.value.strip() not in retention_basis.ORDINALS:
        raise HTTPException(status_code=422, detail="retention must be one of: " + ", ".join(retention_basis.ORDINALS))

    if key == "backup_status" and write.value.strip() and write.value.strip() not in BACKUP_STATUSES:
        raise HTTPException(status_code=422, detail="backup_status must be one of: " + ", ".join(BACKUP_STATUSES))

    registry = ProjectRegistry()
    context = registry.get_context(entity_type, slug) or {}
    fields = dict(context.get("enrichment") or {})
    # Stamp what the survey measures NOW beside the person's value (only for
    # observations with a proposing analysis). Confirming, overriding and
    # re-choosing all pass through here, so every choice re-stamps -- which is
    # the only thing that clears a "survey now disagrees" flag.
    measured_value, measured_at = (
        measured_for(registry, entity_type, slug, key) if write.kind == "observation" else ("", "")
    )
    fields[key] = EnrichmentField(
        value=write.value.strip(), kind=write.kind, author=author,
        set_at=datetime.now(timezone.utc).isoformat(), source=write.source.strip(),
        evidence=dict(write.evidence), interim=bool(write.interim),
        measured_value=measured_value, measured_at=measured_at, note=write.note.strip(),
    ).model_dump()
    context["enrichment"] = fields
    if key in _MIRROR:
        context[_MIRROR[key]] = write.value.strip()
    context["updated_at"] = datetime.now(timezone.utc).isoformat()
    registry.save_context(entity_type, slug, context)
    return {"key": key, "field": fields[key]}


@router.patch("/{entity_type}/{slug}/answer")
def save_answer(entity_type: str, slug: str, write: AnswerWrite, request: Request) -> dict:
    """Save ONE answer to a catalog human question, author-stamped.

    Mirrors `save_field` above (ENRICHMENT-E0-ROW-ANATOMY, REPLY-DESIGNER-
    ENRICHMENT-STAGE-IA.md §0.3/§6 item 1): before this route existed, the
    client did its own read-modify-write of the whole context document
    (`getContext` then `saveContext` with the answer spliced in) and
    recorded only a timestamp — nothing established the answerer's
    identity, so none was stored. That broke the reply's own stated rule
    that "a human-supplied answer carries who and when," the same rule
    `save_field` already enforces for enrichment judgements/observations.

    The author is the signed-in user, stamped here — never taken from the
    client, same reasoning as `save_field`'s `author`. Anonymous writes are
    refused with 401: an answer with no author is not an answer, the same
    standard applied to a judgement.

    Read-modify-write on the server (not the whole document — just
    `question_answers`), so two people answering two different questions on
    the same resource do not clobber each other's answers, the same
    protection `save_field` gives independent enrichment fields.
    """
    user = get_current_user(request)
    author = (user or {}).get("user_id") or (user or {}).get("sub") or (user or {}).get("username") or ""
    if not author:
        raise HTTPException(status_code=401, detail="Sign in to answer — an answer needs an author.")
    question = write.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question is required")

    registry = ProjectRegistry()
    context = registry.get_context(entity_type, slug) or {}
    answers = dict(context.get("question_answers") or {})
    key = question_key(question)
    answers[key] = QuestionAnswer(
        question=question, answer=write.answer.strip(),
        answered_at=datetime.now(timezone.utc).isoformat(), answered_by=author,
    ).model_dump()
    context["question_answers"] = answers
    context["updated_at"] = datetime.now(timezone.utc).isoformat()
    registry.save_context(entity_type, slug, context)
    return {"key": key, "answer": answers[key]}
