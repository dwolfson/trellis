"""Survey Definition endpoints — list candidate Survey Definitions for a resource's
Technology Type (with full step/scope detail), and run one.

Thin web wrapper around resource_explorer.surveyors.survey_definition_reader /
survey_definition_executor — those modules already do all the real work (Egeria
reads, local execution, publishing); this file only adapts them to HTTP.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter()

# D3 (docs/survey-question-context-plan.md): module-level singleton, not
# constructed fresh per request — EgeriaTechTypeCatalog's own docstring
# already says "callers should share one instance rather than refetch per
# request" (workspace-wide catalog metadata, doesn't change often); the
# route just wasn't following that until now, so its internal cache never
# actually persisted across requests.
_tech_type_catalog = None


def _get_tech_type_catalog():
    global _tech_type_catalog
    if _tech_type_catalog is None:
        from resource_explorer.surveyors.egeria_tech_type_catalog import EgeriaTechTypeCatalog

        _tech_type_catalog = EgeriaTechTypeCatalog()
    return _tech_type_catalog


class SurveyDefinitionRunRequest(BaseModel):
    """Request body for running a specific Survey Definition against a resource."""
    survey_definition_ref: str  # a candidate's qualified_name, from the candidates list
    refresh_definition: bool = False
    db_user: str = ""
    db_pwd: str = ""
    egeria_url: str = ""
    egeria_server: str = ""


def _map_reader_executor_errors(exc: Exception) -> HTTPException:
    from resource_explorer.surveyors.survey_definition_executor import SurveyDefinitionExecutorError
    from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReaderError

    if isinstance(exc, (SurveyDefinitionExecutorError, SurveyDefinitionReaderError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _execution_split(steps: list[dict]) -> dict:
    """How many of this survey's steps run where.

    `publishes_itself` is true only when EVERY step runs natively in Egeria:
    one resource-explorer step means there are local findings that nobody will
    publish unless asked. Saying "already published" then would be the exact
    failure this vocabulary exists to prevent -- a status that reads as an
    answer while local annotations sit unpublished.
    """
    # Classified by WHO OWNS THE ANNOTATIONS, not by where the code runs.
    #
    # "prefect" is a dispatch mechanism for Resource Explorer's OWN surveyors
    # (resource_explorer/prefect/flows.py) — the findings come back here and
    # still need publishing. Treating it as native was safe only while "egeria"
    # was the sole alternative to "resource-explorer"; a peer session began
    # routing repo_arch_coupling through Prefect on 2026-08-26, which is what
    # exposed it. A survey whose steps were all Prefect-routed would otherwise
    # report "Publishes itself" and hide the only button that publishes them.
    local_engines = {None, "", "resource-explorer", "prefect"}
    native = sum(1 for s in steps if s.get("executes_at") not in local_engines)
    local = sum(1 for s in steps if s.get("executes_at") in local_engines)
    return {
        "steps_native": native,
        "steps_local": local,
        "publishes_itself": bool(steps) and local == 0,
    }


def _narrow_by_perspective(candidates: list[dict], wanted: list | None) -> list[dict]:
    """Post-filter, so a candidate is judged on its OWN perspectives.

    A candidate with none is kept: an errored one has no steps and no scoping
    to be judged from, and hiding it behind a test it cannot take would make a
    broken Survey Definition silently disappear -- the opposite of what a
    filter should do to something that needs attention.
    """
    if not wanted:
        return candidates
    want = set(wanted)
    return [
        c for c in candidates
        if not (c.get("perspectives") or [])
        or "all" in (c.get("perspectives") or [])
        or want & set(c.get("perspectives") or [])
    ]


def _scoped_perspectives(matched_questions: list, question_rows: list[dict]) -> list:
    """A Survey Definition's perspectives, read off the ScopedBy graph.

    Survey --ScopedBy--> Question --> Perspective. This is the natural
    association and the one D7 (docs/unified-survey-execution-model-plan.md)
    already called for: Questions carry both Funnel Stage and Perspectives, so
    scoping a Survey to the Questions it answers says which lenses it serves
    without a second, separately-maintained tag.

    Attribution comes from the same get_scoped_elements() calls that FOUND the
    candidate -- the query already knows which Question matched, it was simply
    being discarded by the union.
    """
    if not matched_questions:
        return []
    by_text = {q["question"]: q for q in question_rows}
    out: list = []
    for text in matched_questions:
        for persp in (by_text.get(text, {}).get("perspectives") or []):
            if persp not in out:
                out.append(persp)
    return out


def _derived_from_steps(steps: list[dict], declared: list | None = None) -> dict:
    """`analysis_ids` and `perspectives` for a candidate, from its own steps.

    Both are unions over the analysis_catalog entries whose step keys this
    survey runs. `analysis_ids` is what lets a survey card offer the same
    Results view its local counterparts have; `perspectives` is what lets one
    perspective filter apply to both card kinds instead of silently half.

    Order is preserved rather than sorted -- for perspectives it follows step
    order, which is run order, so the reading matches the survey's own shape.
    """
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

    step_keys = [s.get("re_analysis_step") for s in steps if s.get("re_analysis_step")]
    if not step_keys:
        return {"analysis_ids": [], "perspectives": list(declared or []),
                "perspectives_source": "scoped" if declared else ""}

    analysis_ids: list[str] = []
    perspectives: list[str] = []
    for entry in get_analyses("repo", include_egeria_live=False):
        owned = entry.get("re_analysis_steps") or []
        if not owned or not any(k in step_keys for k in owned):
            continue
        if entry["id"] not in analysis_ids:
            analysis_ids.append(entry["id"])
        for persp in entry.get("perspectives") or []:
            # "all" is deliberately NOT unioned in. On a single analysis it
            # means "not specific to any lens"; carried into a survey's union it
            # means one generic step makes the WHOLE survey match every filter.
            # A ten-step survey where nine are Security and one is untagged is
            # still a Security survey. When the union ends up empty the survey
            # really is unspecific, and an empty list already says so — callers
            # keep a candidate they cannot judge rather than hiding it.
            if persp != "all" and persp not in perspectives:
                perspectives.append(persp)
    # An author's declaration beats our inference and REPLACES it: a survey
    # tagged "Security" by its author is a Security survey even if its steps
    # also serve Steward. Merging the two would quietly re-add what the author
    # left out, making the declaration unable to narrow anything.
    if declared:
        return {"analysis_ids": analysis_ids, "perspectives": list(declared),
                "perspectives_source": "scoped"}
    return {"analysis_ids": analysis_ids, "perspectives": perspectives,
            "perspectives_source": "derived" if perspectives else ""}


@router.get("/{entity_type}/{slug}/candidates")
async def list_candidates(
    entity_type: str, slug: str,
    survey_kind: str | None = Query(
        None,
        description="Filter to Survey Definitions tagged with this survey_kind "
                    "(e.g. 'discovery') — omit to see every Survey Definition for "
                    "the resource's Technology Type regardless of kind, matching "
                    "the pre-survey_kind behavior.",
    ),
    phase: str | None = Query(
        None,
        description="D2 (docs/survey-question-context-plan.md) + D7 "
                    "(docs/unified-survey-execution-model-plan.md): scope the "
                    "candidate lookup to Questions tagged with this funnel-stage "
                    "(the CSV's single 'Funnel Stage' field, collapsed from the "
                    "earlier separate Asked At/Answered At columns 2026-08-14). "
                    "Per D7, each intent's own UI should pass its own stage here "
                    "as the primary filter — omitting it falls back to using every "
                    "cataloged repo Question regardless of stage, still scoped "
                    "over the full scan otherwise.",
    ),
    perspectives: list[str] | None = Query(
        None,
        description="Narrow to Survey Definitions serving any of these perspectives "
                    "(OR semantics). Applied to each candidate's own perspectives — "
                    "read off the Survey->ScopedBy->Question->Perspective graph — "
                    "AFTER discovery, never to the Question set used to discover "
                    "them: narrowing that first would make every candidate report "
                    "exactly the perspective asked for.",
    ),
) -> dict:
    """List Survey Definitions Egeria has for this resource's Technology Type,
    each with full step detail (not just a name) so a human can judge scope
    before running one."""

    def _do() -> dict:
        from resource_explorer.surveyors.question_catalog_reader import get_questions
        from resource_explorer.surveyors.survey_definition_executor import get_adapter
        from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader

        adapter = get_adapter(entity_type)
        reader = SurveyDefinitionReader()

        # D2: try the scoped ScopedBy lookup by default — phase/perspectives
        # only narrow which cataloged Questions get considered, they aren't
        # required to attempt scoping at all (fixed live, see the phase=
        # param docstring above for the incident this closes).
        # Deliberately NOT narrowed by `perspectives`: these rows are what a
        # matched candidate reads its own perspectives from, and filtering them
        # first would make every survey report exactly the filter that was
        # applied -- a circular answer that always agrees with the question.
        # Perspective narrowing of the candidate list happens client-side, over
        # the perspectives derived here.
        question_rows = get_questions(resource_type=entity_type, phase=phase)
        questions = [q["question"] for q in question_rows]
        thin_candidates: list = []
        if questions:
            thin_candidates = reader.find_candidate_process_guids_by_questions(
                questions, adapter.technology_type, survey_kind=survey_kind,
            )
        if not thin_candidates:
            # No cataloged Questions for this resource type, none resolved to
            # a real Egeria GUID yet, or none are scoped to any matching
            # Survey Definition — fall back to the full scan rather than
            # silently show an empty list (D2's own decision: the full-scan
            # path stays an explicit fallback, not removed).
            thin_candidates = reader.find_candidate_process_guids(adapter.technology_type, survey_kind=survey_kind)

        # Real Egeria-documented "what does a native step actually produce" info,
        # keyed by Egeria's own Technology Type name (deliberately not the same
        # string as adapter.technology_type — see ResourceTypeAdapter docstring).
        # Best-effort: if Egeria is unreachable or the tech type isn't found, this
        # is just an empty list and non-RE steps fall back to the static text.
        produced_annotation_types: list[dict] = []
        if adapter.egeria_technology_type_name:
            try:
                produced_annotation_types = _get_tech_type_catalog().get_produced_annotation_types(
                    adapter.egeria_technology_type_name
                )
            except Exception as exc:
                log.debug("get_produced_annotation_types(%r) failed: %s", adapter.egeria_technology_type_name, exc)

        # Deliberately serial. Parallelising this looks like the obvious next
        # perf win (it is ~1.3s of the endpoint's ~2.5s cold) and was measured
        # against a real server on 2026-08-19 — it does not pay off either way:
        #
        #   serial                       1.39s   all 4 correct
        #   ThreadPool, shared reader    0.34s   CORRUPTED — one candidate came
        #                                        back CLIENT_ERROR_400 that
        #                                        fetches fine serially
        #   ThreadPool, reader-per-thread 1.25-1.56s over 3 trials, all correct
        #
        # The shared-client speedup is not real: pyegeria's sync wrappers drive
        # an event loop (nest_asyncio) per client, so concurrent calls on one
        # client corrupt each other — intermittently, which is the worst way for
        # this to fail. Giving each thread its own reader is correct but buys
        # nothing, because the per-reader connect/token handshake costs about
        # what the concurrency saves.
        #
        # So: leave it serial until pyegeria exposes an async client that can be
        # driven from one loop (then gather() the fetches properly). If the real
        # problem is a slow/hanging definition rather than throughput, the fix is
        # a per-fetch deadline here, not threads.
        from resource_explorer.registry import ProjectRegistry
        from resource_explorer.surveyors.repo_survey_definition_adapter import get_survey_definition_speed_tag

        last_activity_by_ref = ProjectRegistry().get_survey_definition_last_activity(entity_type, slug)

        detailed = []
        for c in thin_candidates:
            try:
                survey_def = reader.fetch(c["guid"])
            except Exception as exc:
                # Don't let one malformed/unsupported (e.g. branching) Survey
                # Definition hide the rest of the list — surface it as an
                # errored candidate instead.
                detailed.append({**c, "description": "", "error": str(exc), "steps": []})
                continue

            steps = []
            for s in survey_def.steps:
                step_info: dict = {
                    "qualified_name": s.qualified_name,
                    "display_name": s.display_name,
                    "description": s.description,
                    "executes_at": s.executes_at,
                    "re_analysis_step": s.re_analysis_step,
                }
                if s.executes_at == "resource-explorer":
                    info = adapter.re_analysis_step_info.get(s.re_analysis_step, {})
                    step_info["annotation_types"] = info.get("annotation_types", [])
                    if not step_info["description"] and info.get("description"):
                        step_info["description"] = info["description"]
                elif produced_annotation_types:
                    # Technology-Type-level info, not verified to be scoped to this
                    # exact step — Egeria's catalog doesn't link a specific
                    # GovernanceActionProcessStep to a specific producedAnnotationType
                    # entry, so this shows everything the native engine for this
                    # Technology Type is documented to produce.
                    step_info["egeria_produced_annotation_types"] = produced_annotation_types
                steps.append(step_info)

            last_activity = last_activity_by_ref.get(c["qualified_name"], {})
            detailed.append({
                **c, "description": survey_def.description, "error": None, "steps": steps,
                "survey_kind": survey_def.survey_kind,
                "last_run_at": last_activity.get("last_run_at", ""),
                "last_run_status": last_activity.get("last_run_status", ""),
                "last_published_at": last_activity.get("last_published_at", ""),
                # 'candidate' = a real per-Survey-Definition publish (the ☁
                # Publish button on this exact card); 'repo' = inferred from
                # a whole-repo "Publish survey →" that happened after this
                # candidate's last run — see get_survey_definition_last_
                # activity's docstring for why that's still honest, not a
                # precise per-candidate claim. Blank when last_published_at
                # is blank too.
                "last_published_scope": last_activity.get("last_published_scope", ""),
                # Matches the local Analyses catalog's own run_time field —
                # see get_survey_definition_speed_tag's docstring for how
                # it's derived (Survey Definitions have no such field of
                # their own to read).
                "run_time": get_survey_definition_speed_tag(steps),
                # A Survey Definition has no perspectives of its own in Egeria,
                # so the Survey tab's perspective filter could only ever filter
                # the local half of the list -- a live-looking control acting on
                # half the cards. A survey IS its steps, so its perspectives are
                # the union of what those steps serve. Derived, not invented:
                # every value traces to an analysis_catalog entry.
                **_derived_from_steps(
                    steps,
                    # The ScopedBy graph is the declaration; the step union is
                    # an inference used only where no Question scopes this
                    # survey yet (notably the full-scan fallback, which finds
                    # candidates without going through Questions at all).
                    declared=(_scoped_perspectives(c.get("matched_questions") or [], question_rows)
                              or survey_def.perspectives),
                ),
                # Where this survey's steps actually run. An Egeria-native step
                # writes its annotations into Egeria as it runs -- published by
                # construction, with nothing local to publish and no "publish
                # this" to offer. A resource-explorer step produces annotations
                # here and needs an explicit publish. A survey can be a mix, so
                # this is a count, not a flag.
                **_execution_split(steps),
            })

        # Composite-survey propagation (2026-08-24 — direct feedback: "if a
        # Survey includes all the steps of other surveys and we run it, does
        # it also mean that the smaller size survey ran?" e.g. Scouting
        # Survey's own description says it's literally "the union of Git
        # Statistics Survey and Coarse Profile Survey"). A candidate whose
        # own re_analysis_step set is a non-empty SUBSET of another
        # candidate's set inherits that superset's last-run info when it has
        # none of its own — the smaller survey's steps genuinely did execute
        # as part of the bigger run, so its badge should say so. Marked via
        # `last_run_via` (the superset's own ref) so the UI can render this
        # honestly ("via Scouting Survey") rather than implying a direct run;
        # a candidate that HAS its own last_run_at is never overwritten, even
        # if a later superset run exists — its own history takes precedence.
        # When multiple supersets qualify, the one with the most recent
        # last_run_at wins (most relevant to "did this run recently").
        def _step_set(cand: dict) -> set[str]:
            return {s["re_analysis_step"] for s in cand.get("steps", []) if s.get("re_analysis_step")}

        step_sets = {c["qualified_name"]: _step_set(c) for c in detailed}
        for cand in detailed:
            if cand.get("last_run_at"):
                continue
            own_steps = step_sets.get(cand["qualified_name"])
            if not own_steps:
                continue
            best = None
            for other in detailed:
                if other["qualified_name"] == cand["qualified_name"] or not other.get("last_run_at"):
                    continue
                other_steps = step_sets.get(other["qualified_name"])
                if not other_steps or other_steps == own_steps or not own_steps.issubset(other_steps):
                    continue
                if best is None or other["last_run_at"] > best["last_run_at"]:
                    best = other
            if best is not None:
                cand["last_run_at"] = best["last_run_at"]
                cand["last_run_status"] = best.get("last_run_status", "")
                cand["last_run_via"] = best["qualified_name"]

        # Extends the registry's own repo-wide-publish fallback (see
        # get_survey_definition_last_activity's docstring) to candidates that
        # only got a last_run_at just above, via composite propagation, not a
        # real activity_log row of their own — e.g. Coarse Profile Survey,
        # covered by a Scouting Survey run, genuinely had its data included
        # in a later whole-repo publish too, same as Scouting Survey itself
        # was. Without this, only the composite *superset* showed the
        # repo-wide publish badge and every subset it covered stayed blank,
        # which is exactly the same "we published but it says never" gap
        # this whole mechanism exists to close. repo_wide_publish_at is
        # recovered from whichever candidate(s) the registry call already
        # tagged 'repo' (all share the same timestamp — the most recent
        # untagged publish for this entity), not recomputed independently.
        repo_wide_publish_at = next(
            (c["last_published_at"] for c in detailed if c.get("last_published_scope") == "repo"), "",
        )
        if repo_wide_publish_at:
            for cand in detailed:
                if cand.get("last_published_at") or not cand.get("last_run_at"):
                    continue
                if cand["last_run_at"] <= repo_wide_publish_at:
                    cand["last_published_at"] = repo_wide_publish_at
                    cand["last_published_scope"] = "repo"

        # Native Egeria processes for this Technology Type (config/technology_
        # type_processes.yaml), shown as informational only — NOT merged into
        # `detailed`/candidates, since only "survey_existing" processes are
        # currently safe/wired to run from RE (via other_engine_handlers);
        # "catalog_and_survey" needs template placeholder params RE doesn't
        # collect yet, and "delete" processes must never be offered as
        # runnable at all. See technology_type_processes.py's KIND_* constants.
        native_processes: list[dict] = []
        if adapter.egeria_technology_type_name:
            from resource_explorer.surveyors.technology_type_processes import (
                KIND_DELETE,
                get_native_processes,
            )
            native_processes = [
                {
                    "qualified_name": p.qualified_name,
                    "display_name": p.display_name,
                    "kind": p.kind,
                    "description": p.description,
                }
                for p in get_native_processes(entity_type, adapter.egeria_technology_type_name)
                if p.kind != KIND_DELETE
            ]

        return {
            "technology_type": adapter.technology_type,
            "candidates": _narrow_by_perspective(detailed, perspectives),
            "egeria_native_processes": native_processes,
        }

    try:
        return await asyncio.to_thread(_do)
    except Exception as exc:
        raise _map_reader_executor_errors(exc)


def _execute_survey_definition_sync(entity_type: str, slug: str, body: SurveyDefinitionRunRequest) -> dict:
    """The actual run — plain sync function (no FastAPI/asyncio coupling) so
    it's trivially callable from a daemon thread with its own fresh registry
    connection, matching projects.py's _run_scouting_scan_sync precedent.
    Raises SurveyDefinitionExecutorError/SurveyDefinitionReaderError on a
    reader/executor-level failure — the caller decides how to surface that
    (an HTTPException for the old synchronous path; an errored activity
    entry for the background path below)."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.survey_definition_executor import run_survey_definition

    registry = ProjectRegistry()
    result = run_survey_definition(
        entity_type,
        slug,
        registry=registry,
        survey_definition_ref=body.survey_definition_ref,
        refresh_definition=body.refresh_definition,
        db_user=body.db_user,
        db_pwd=body.db_pwd,
    )

    report_guid = result.get("egeria_report_guid", "")
    if report_guid:
        from resource_explorer.config import get_config
        portal_url = get_config().egeria.portal_url.rstrip("/")
        result["egeria_portal_report_url"] = f"{portal_url}/tech-catalog?guid={report_guid}"

    return result


def _run_survey_definition_background(
    entity_type: str, slug: str, body: SurveyDefinitionRunRequest, activity_id: str,
) -> None:
    """Runs in a daemon thread — nothing here returns to an HTTP response.
    Mirrors projects.py's _run_scouting_scan_background precedent, generalized
    to any Survey Definition: the ONE activity entry the route created up
    front (status='running') gets its terminal status/summary written back
    via registry.update_activity_status(), with the full structured result
    (steps report, egeria_report_guid, portal URL, errors — everything the
    run modal renders) JSON-encoded into that same entry's `detail` field.
    No separate result-store needed, and — unlike an in-memory dict — this
    survives a server restart same as any other activity entry; the frontend
    just needs to json.parse() `detail` once the poll sees a terminal status."""
    import json

    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.survey_definition_executor import SurveyDefinitionExecutorError
    from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReaderError

    # Embedded in `detail` on every terminal path (success, reader/executor
    # error, and unexpected crash) — see registry.get_survey_definition_last_
    # activity(), which scans activity_log for exactly this key to compute
    # each candidate's last-run badge. summary alone isn't reliable for this:
    # it does contain the ref for the *initial* 'running' row (see the route
    # below), but this call always overwrites summary on the terminal row, so
    # by the time anything queries a completed run, the ref only survives if
    # it's also in detail.
    ref = body.survey_definition_ref

    registry = ProjectRegistry()
    try:
        result = _execute_survey_definition_sync(entity_type, slug, body)
    except (SurveyDefinitionExecutorError, SurveyDefinitionReaderError) as exc:
        registry.update_activity_status(
            activity_id, "error", summary=str(exc),
            detail=json.dumps({"errors": [str(exc)], "survey_definition_ref": ref}),
        )
        return
    except Exception as exc:  # pragma: no cover — genuinely unexpected, not a survey-step error
        log.exception("Survey Definition run background thread crashed for %s/%s", entity_type, slug)
        registry.update_activity_status(
            activity_id, "error", summary=f"Survey Definition run crashed: {exc}",
            detail=json.dumps({"errors": [str(exc)], "survey_definition_ref": ref}),
        )
        return

    errors = result.get("errors") or []
    summary = f"Completed with {len(errors)} error(s)" if errors else "Survey Definition run complete"
    result["survey_definition_ref"] = ref
    registry.update_activity_status(activity_id, "error" if errors else "ok", summary=summary, detail=json.dumps(result))


@router.post("/{entity_type}/{slug}/run")
async def run_survey_definition_route(entity_type: str, slug: str, body: SurveyDefinitionRunRequest) -> dict:
    """Fire-and-forget (background thread), not synchronous — a real,
    live-reported gap: this used to block the whole HTTP request for the
    entire survey duration, with only a spinner and no way to tell whether a
    multi-step/multi-minute survey (e.g. Coarse Profile Survey's zipball
    download+profile, or a 17-step Repo Full Survey) was still running or
    had hung. Mirrors projects.py's run_scouting_scan precedent exactly,
    generalized to any Survey Definition/resource type: returns an
    activity_id immediately; the frontend polls GET /api/activity/{id}
    until it's terminal, then reads the full run result back out of that
    entry's own `detail` field (see _run_survey_definition_background)."""
    import threading

    from resource_explorer.activity_logger import log_survey
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    activity_id = log_survey(
        registry, entity_type=entity_type, entity_slug=slug, entity_name=slug,
        entity_location="", intent="assessment", status="running",
        summary=f"Running Survey Definition '{body.survey_definition_ref}' on {slug}…",
    )

    t = threading.Thread(
        target=_run_survey_definition_background,
        args=(entity_type, slug, body, activity_id),
        daemon=True, name="resource-explorer-survey-def-run",
    )
    t.start()

    return {"status": "started", "activity_id": activity_id}
