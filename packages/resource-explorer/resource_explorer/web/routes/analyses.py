"""Analysis catalog API routes."""
from __future__ import annotations

from fastapi import APIRouter, Query

from resource_explorer.surveyors.analysis_catalog_reader import (
    get_analyses,
    get_egeria_merge_status,
    list_perspectives,
)

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


@router.get("/question-catalog")
def list_question_catalog(resource_type: str = "repo") -> list[dict]:
    """Full, unscoped Question catalog (docs/dr-egeria/resource_questions.csv,
    via question_catalog_reader.py) — every authored question with its
    funnel stage, perspectives, and answering info, no project/has_data
    computation. Backs the read-only Admin > Question Catalog browser.
    Contrast with GET /api/projects/{slug}/scouting-questions, which is
    project-scoped and adds a per-question has_data flag; this route is for
    browsing the catalog itself, not answering it for a specific resource.
    NOTE: declared before /{resource_type} deliberately — see
    list_perspectives_route's note above."""
    from resource_explorer.surveyors.question_catalog_reader import get_questions

    return get_questions(resource_type)


@router.get("/facts/{slug}")
def resource_facts(slug: str, analysis_ids: list[str] | None = Query(None)) -> dict:
    """What is known about this resource, and how well it is known.

    Facts arrive already judged: each carries a state from result_status's
    vocabulary rather than a bare value, so a caller cannot turn "never ran"
    into "none found". Omit analysis_ids for every analysis that has a results
    reader.
    """
    from resource_explorer.facts import FactLayer
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        REPO_ANALYSIS_RESULTS_MAP,
    )

    ids = analysis_ids or sorted(REPO_ANALYSIS_RESULTS_MAP)
    layer = FactLayer()
    return {"subject": slug, "facts": [f.as_dict() for f in layer.facts(slug, ids)]}


@router.get("/facts/{slug}/answer")
def answer_question(slug: str, question: str = Query(...)) -> dict:
    """An answer envelope for one catalogued question.

    The question is matched by its text, which is what the catalog keys on and
    what the Questions tab already renders. An envelope whose `answerable` is
    false carries `blocked_reason` and MUST NOT be rendered as a negative
    answer about the resource — for 30 of the 41 catalogued questions that is
    the correct outcome, and inventing an answer for them is precisely what
    this layer exists to prevent.
    """
    from resource_explorer.facts import FactLayer
    from resource_explorer.surveyors.question_catalog_reader import get_questions

    match = next((q for q in get_questions() if q.get("question") == question), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Question not in the catalog: {question!r}")
    return FactLayer().answer(slug, match).as_dict()


@router.get("/{resource_type}")
def list_analyses(
    resource_type: str,
    intent: str | None = Query(None),
    perspective: str | None = Query(None),
) -> list[dict]:
    """Return available analyses for a resource type.

    resource_type: 'repo' | 'database' | 'filesystem'
    intent:       scouting | assessment | discovery | analysis | enrichment | understanding | curate
    perspective:  all | dba | data_scientist | steward | security
    """
    result = get_analyses(resource_type, intent=intent, perspective=perspective)
    return result


@router.get("/{resource_type}/egeria-status")
def get_analyses_egeria_status(resource_type: str) -> dict:
    """Outcome of the most recent live-Egeria merge attempt for this
    resource_type, so the UI can show a "live Egeria data unavailable"
    indicator only when a merge was actually attempted and failed — not for
    resource types that were never wired up to a Technology Type at all.
    Call GET /{resource_type} first; this reflects that call's outcome, it
    does not trigger a fresh one."""
    return {"resource_type": resource_type, "status": get_egeria_merge_status(resource_type)}
