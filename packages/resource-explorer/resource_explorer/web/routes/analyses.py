"""Analysis catalog API routes."""
from __future__ import annotations

from fastapi import APIRouter, Query

from resource_explorer.surveyors.analysis_catalog_reader import (
    get_analyses,
    get_egeria_merge_status,
    list_perspectives,
)

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger(__name__)
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


#: Most resources one bulk read will serve. Beyond this the request is
#: REFUSED with the cap named, rather than quietly truncated — a matrix that
#: silently drops rows past 200 is worse than one that says it cannot.
BULK_FACTS_MAX_SUBJECTS = 200


@router.get("/facts")
def bulk_resource_facts(
    slugs: str = Query(..., description="comma-separated resource slugs"),
    analysis_ids: str = Query("", description="comma-separated; omit for every analysis"),
    states_only: bool = Query(
        False,
        description="cheap projection: is there output and when was it measured, "
                    "without running the results readers",
    ),
) -> dict:
    """What is known about SEVERAL resources, in one call.

    Exists for the comparison matrix, which is rows x questions and was making
    one request per row. Twelve rows is twelve round trips; four hundred is
    four hundred.

    **Scope `analysis_ids` if you can.** The cost here is dominated by a
    couple of analyses whose results readers are genuinely expensive —
    measured on `egeria_git`, `architecture_recovery` takes 47s and
    `architecture_diagram` 22s, while the other 32 together take under a
    second. Reading all 34 for one resource is 70s; reading the 5 that
    Scouting's questions actually use is 0.5s. A caller that knows which
    analyses it will display should say so.

    A GET rather than a POST because it is a read, and this app has a
    read-only mode that a POST would put it out of reach of. The cost of that
    choice is the URL length, hence the cap.
    """
    from resource_explorer.facts import FactLayer
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        REPO_ANALYSIS_RESULTS_MAP,
    )

    subjects = [s.strip() for s in slugs.split(",") if s.strip()]
    # Deduped, order preserved: a repeated slug in the request should not mean
    # the work is done twice.
    subjects = list(dict.fromkeys(subjects))
    if not subjects:
        raise HTTPException(status_code=400, detail="slugs is required")
    if len(subjects) > BULK_FACTS_MAX_SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"{len(subjects)} resources requested; this endpoint serves at "
                   f"most {BULK_FACTS_MAX_SUBJECTS} at a time",
        )

    ids = [a.strip() for a in analysis_ids.split(",") if a.strip()]
    ids = ids or sorted(REPO_ANALYSIS_RESULTS_MAP)

    if states_only:
        # THE CHEAP PATH. Two grouped queries for the whole matrix instead of
        # one results reader per (resource, analysis). The readers are what
        # cost — `architecture_recovery` at 47s on a large repo — and they
        # build a value a grid cell never displays.
        #
        # DELIBERATELY LESS INFORMATIVE, and it says so in the response. This
        # separates "there is output" from "there is none"; it does NOT
        # separate `measured` from `partial`, because that lives in the
        # results dict's own `_status` and only the reader produces it. A
        # caller must render the difference as not-yet-read. Claiming a state
        # nobody established is the exact failure this layer exists to stop,
        # and doing it for speed would be a poor trade.
        from resource_explorer.registry import ProjectRegistry

        registry = ProjectRegistry()
        summary = registry.analysis_result_summary(subjects, ids)
        layer = FactLayer()
        states: dict[str, dict] = {}
        for slug in subjects:
            runs = layer._last_run(slug)
            per: dict[str, dict] = {}
            for aid in ids:
                hit = summary.get((slug, aid)) or {}
                run = runs.get(aid) or {}
                per[aid] = {
                    "has_results": bool(hit.get("rows")),
                    "rows": hit.get("rows", 0),
                    # How current this cell is — the question a matrix of
                    # stored results has to answer before anyone trusts it.
                    "measured_at": hit.get("measured_at") or run.get("last_run_at", ""),
                    "last_run_at": run.get("last_run_at", ""),
                    # CERTAIN, not inferred: nothing stored and nothing run.
                    "certain_never_run": not hit.get("rows") and not run.get("last_run_at"),
                }
            states[slug] = per
        return {
            "states": {s: states[s] for s in subjects if s in states},
            "analysis_ids": ids,
            "requested": len(subjects),
            "returned": len(states),
            "projection": True,
            "projection_note": (
                "has_results and measured_at only — `measured` vs `partial` is "
                "not established here. Read the full facts for that."
            ),
        }

    out: dict[str, list] = {}
    failed: dict[str, str] = {}

    def read_one(slug: str):
        # A FactLayer per thread rather than one shared: it holds a registry
        # handle, and a DB connection is not something to share across
        # threads on the strength of it probably being fine.
        return slug, [f.as_dict() for f in FactLayer().facts(slug, ids)]

    # Fanned out across resources, because the cost here is dominated by a
    # couple of readers that are slow rather than by many that are quick —
    # `architecture_recovery` is 47s on a large repo and `architecture_diagram`
    # 22s, and Discovery's questions route to BOTH. Twelve resources serially
    # is a quarter of an hour; the work is DB- and IO-bound, so threads
    # actually buy something here.
    #
    # Bounded deliberately: this shares a Postgres with two apps and several
    # sessions, and an unbounded pool would trade one slow page for everyone
    # else's connections.
    workers = min(8, len(subjects))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(read_one, slug): slug for slug in subjects}
        for fut in as_completed(futures):
            slug = futures[fut]
            try:
                slug, facts = fut.result()
                out[slug] = facts
            except Exception as exc:
                # One unreadable resource is one unreadable resource. Named,
                # and kept OUT of `subjects`, so a caller cannot mistake "we
                # could not read it" for "it has no results" — the distinction
                # this whole layer exists to preserve.
                log.warning("bulk facts failed for %s: %s", slug, exc)
                failed[slug] = f"{type(exc).__name__}: {exc}"

    return {
        # Requested order, not completion order — the grid renders rows in the
        # order it asked for them.
        "subjects": {s: out[s] for s in subjects if s in out},
        "analysis_ids": ids,
        "requested": len(subjects),
        "returned": len(out),
        "unreadable": failed,
    }


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
