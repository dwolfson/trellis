"""Resource schedule API — store and retrieve analysis schedules per resource."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from resource_explorer.registry import ProjectRegistry, TARGET_ANALYSIS, TARGET_SURVEY

router = APIRouter()


def _cost_hint(entity_type: str, analysis_id: str) -> dict:
    """Cost tiers and the cadence they warrant, for one analysis.

    Repo-only: cost tiers live on repo StepInfo entries, and database/filesystem
    analyses have no equivalent yet. Returning empty rather than guessing keeps
    that absence visible instead of showing every database analysis as "daily,
    costs nothing".
    """
    if entity_type != "repo":
        return {}
    # A Survey Definition has no cost tier: cost lives on individual repo
    # StepInfo entries, and a survey is a graph of them whose total depends on
    # which branches run. Returning empty says "not established" rather than
    # inventing a tier for a bundle — the same reason database analyses get
    # nothing here.
    if analysis_id.startswith("GovActionProcess::"):
        return {}
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        REPO_ANALYSIS_STEP_MAP, analysis_cost, recommended_schedule,
    )
    if analysis_id not in REPO_ANALYSIS_STEP_MAP:
        return {}
    fetch, compute = analysis_cost(analysis_id)
    return {"fetch_cost": fetch, "compute_cost": compute,
            "recommended_schedule": recommended_schedule(analysis_id)}

_VALID_SCHEDULES = {"manual", "daily", "weekly", "monthly"}


class ScheduleEntry(BaseModel):
    #: The target reference. An analysis id, or a Survey Definition's
    #: qualified name when target_kind is "survey". Named for its original
    #: meaning; see ProjectRegistry.save_schedule for why it was not renamed.
    analysis_id: str
    schedule: str = "manual"    # manual | daily | weekly | monthly
    enabled: bool = True
    #: "analysis" (default, unchanged behaviour) or "survey". The registry and
    #: scheduler have understood both since 2026-08-28; this route did not
    #: expose it, so a survey could be authored, listed and run by hand but
    #: never actually put on a cadence.
    target_kind: str = TARGET_ANALYSIS


#: How to find a resource of each schedulable kind. A schedule names a
#: resource that must still exist when the cadence fires, and nothing checked
#: that at the point the schedule was created.
_RESOURCE_LOOKUP = {
    "repo": lambda reg, slug: reg.get(slug),
    "database": lambda reg, slug: reg.get_database(slug),
    "filesystem": lambda reg, slug: reg.get_filesystem(slug),
}


def _require_resource(registry, entity_type: str, slug: str) -> None:
    """404 unless this resource exists.

    Measured 2026-08-28: POST /api/schedules/repo/egeria was accepted and
    stored, though no repo has that slug — the real one is `egeria_git`. The
    typo surfaced nowhere. It would have sat as a valid-looking weekly
    schedule and failed on its first run, a week later, with "schedule may be
    stale" written into a row nobody was watching.

    The scheduler already reports it correctly; the cost was entirely in WHEN.
    A mistake a caller can fix in the second it is made becomes, untouched, a
    silent gap in coverage the user believes they have.

    An unknown entity_type passes through deliberately rather than 422-ing:
    this route has never constrained the vocabulary, and inventing a whitelist
    here would reject a resource kind added elsewhere in the codebase before
    anyone thought to update this dict. What it must not do is claim a
    resource is missing when it simply cannot look it up.
    """
    from fastapi import HTTPException

    lookup = _RESOURCE_LOOKUP.get(entity_type)
    if lookup is None:
        return
    if lookup(registry, slug) is None:
        raise HTTPException(
            status_code=404,
            detail=f"No {entity_type} '{slug}' — a schedule against it could "
                   f"never run. Check the slug.",
        )


@router.get("/")
def list_all_schedules() -> list[dict]:
    """Every scheduled analysis across every resource — backs the Admin
    Schedules overview. Errors surface first; see
    ProjectRegistry.list_all_schedules()'s docstring."""
    return [{**r, **_cost_hint(r.get("entity_type", ""), r.get("analysis_id", ""))}
            for r in ProjectRegistry().list_all_schedules()]


@router.get("/{entity_type}/{slug}")
def get_schedules(entity_type: str, slug: str) -> list[dict]:
    """Return all schedules configured for a resource."""
    return [{**r, **_cost_hint(entity_type, r.get("analysis_id", ""))}
            for r in ProjectRegistry().get_schedules(entity_type, slug)]


@router.delete("/{entity_type}/{slug}/{analysis_id}")
def delete_schedule(entity_type: str, slug: str, analysis_id: str) -> dict:
    """Remove a schedule entirely (vs. disabling it) — useful for cleaning up
    stale schedules pointing at a resource that no longer exists."""
    from fastapi import HTTPException
    if not ProjectRegistry().delete_schedule(entity_type, slug, analysis_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "success"}


@router.post("/{entity_type}/{slug}")
def save_schedule(entity_type: str, slug: str, entry: ScheduleEntry) -> dict:
    """Create or update a schedule for a specific analysis on a resource."""
    from fastapi import HTTPException
    if entry.schedule not in _VALID_SCHEDULES:
        raise HTTPException(status_code=422, detail=f"Invalid schedule '{entry.schedule}'; must be one of {sorted(_VALID_SCHEDULES)}")
    if entry.target_kind not in (TARGET_ANALYSIS, TARGET_SURVEY):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid target_kind '{entry.target_kind}'; must be "
                   f"'{TARGET_ANALYSIS}' or '{TARGET_SURVEY}'")
    registry = ProjectRegistry()
    _require_resource(registry, entity_type, slug)
    registry.save_schedule(
        entity_type=entity_type,
        entity_slug=slug,
        analysis_id=entry.analysis_id,
        schedule=entry.schedule,
        enabled=entry.enabled,
        target_kind=entry.target_kind,
    )
    hint = _cost_hint(entity_type, entry.analysis_id)
    out = {"status": "ok", "entity_type": entity_type, "entity_slug": slug,
           "analysis_id": entry.analysis_id, "schedule": entry.schedule,
           "enabled": entry.enabled, "target_kind": entry.target_kind, **hint}

    # Advisory only — the schedule above is already saved. A ceiling that
    # refused would be wrong: wanting an expensive analysis more often than its
    # cost suggests is a legitimate choice, and the reasons for it are invisible
    # from here. Doing it unknowingly is the case worth catching.
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        schedule_is_more_frequent_than_recommended,
    )
    if hint and schedule_is_more_frequent_than_recommended(entry.analysis_id, entry.schedule):
        out["note"] = (
            f"This analysis is {hint['fetch_cost']}-fetch/{hint['compute_cost']}-compute; "
            f"{hint['recommended_schedule']} is usually often enough. "
            f"Running it {entry.schedule} is fine if you mean to."
        )
    return out
