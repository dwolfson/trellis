"""The analysis-run and stage-batch workflows.

Moved verbatim out of `web/routes/projects.py` (its `_run_single_analysis_sync`
at :632 and `_run_stage_batch_background` at :837) as part of step 2b. The
route's own docstring already said the run function had been written
FastAPI-free "so it's trivially callable from a daemon thread" — this is that
observation taken to its conclusion: the same property makes it callable from
the CLI and from the run queue, and the only thing keeping it out of both was
which file it sat in.

**This is a move, not a redesign.** The ingest-vs-survey branch, the
`has_assigned_egeria_project` auto-publish gate, the three-state `published`
value, and the summary text are unchanged. The comments explaining *why* each
of those is the way it is moved with the code, because they are the reason it
must not be "simplified" on the way past.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

#: The analysis_id a stage-batch run is logged under. Not a real catalog entry —
#: a batch runs many analyses and belongs to none of them.
STAGE_BATCH_ANALYSIS_ID = "__stage_batch__"


@dataclass
class AnalysisRunResult:
    """What one analysis run concluded.

    `published` is three-state, not a bool: None (never attempted — the
    resource has no assigned Egeria project, or the run produced no
    annotations), False (attempted and failed), True (published). Callers
    render the ☁ Publish button on False and None and hide it on True, so
    collapsing the first two would hide the recovery path for a failure.
    """

    status: str  # "ok" | "error"
    summary: str = ""
    error: str = ""
    published: bool | None = None
    annotations: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """The exact dict shape `_run_single_analysis_sync` used to return, so
        the route wrapper and its tests keep reading the same keys."""
        out: dict = {"status": self.status, "published": self.published}
        if self.summary:
            out["summary"] = self.summary
        if self.error:
            out["error"] = self.error
        if self.annotations:
            out["annotations"] = self.annotations
        return out


@dataclass
class StageBatchResult:
    status: str  # "ok" | "error"
    stage: str
    step_keys: list[str] = field(default_factory=list)
    summary: str = ""
    errors: list[str] = field(default_factory=list)
    annotations: list[dict] = field(default_factory=list)


def resolve_analysis_plan(analysis_id: str) -> tuple[bool, list[str] | None]:
    """(is_ingest, steps) for one analysis id.

    `action: "ingest"` (today only `rag_ingestion`) is not a SurveyOrchestrator
    step at all — it re-embeds content into pgvector via IncrementalIndexer.
    Resolved before the step-map lookup, the same way scheduler.py special-cases
    `action: "publish"`. Callers use the pair both to validate up front (an
    unknown id has neither) and to run.
    """
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        REPO_ANALYSIS_STEP_MAP,
    )

    catalog_entry = next(
        (a for a in get_analyses("repo", include_egeria_live=False) if a["id"] == analysis_id),
        None,
    )
    is_ingest = bool(catalog_entry and catalog_entry.get("action") == "ingest")
    steps = None if is_ingest else REPO_ANALYSIS_STEP_MAP.get(analysis_id)
    return is_ingest, steps


def resolve_stage_step_keys(stage: str) -> tuple[list[str], int]:
    """(step_keys, analysis_count) for a "Run all <Stage>" batch.

    Derived live from every local AnalysisKind catalog entry tagged this intent,
    deliberately NOT from the per-stage Egeria Survey Definitions: measured
    2026-09-03, those cover 3/3, 5/7, 8/14 and 7/10 of each stage's catalog
    entries, so pinning one under a "Run all" label would silently under-run the
    stage. Deriving it means the set stays correct as entries are added.
    """
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        REPO_ANALYSIS_STEP_MAP,
    )

    entries = [
        a for a in get_analyses("repo", intent=stage, include_egeria_live=False)
        if a.get("action") not in ("ingest", "publish", "profile")
    ]
    step_keys: list[str] = []
    for a in entries:
        for sk in REPO_ANALYSIS_STEP_MAP.get(a["id"], []):
            if sk not in step_keys:
                step_keys.append(sk)
    return step_keys, len(entries)


def run_analysis(
    slug: str,
    analysis_id: str,
    *,
    is_ingest: bool | None = None,
    steps: list[str] | None = None,
    registry=None,
) -> AnalysisRunResult:
    """Run one analysis's mapped survey step(s) and, where the resource is
    assigned to an Egeria project, auto-publish what it produced.

    Never raises for an analysis-level failure — that comes back as
    `status="error"` — only for something genuinely unexpected, which the caller
    catches and records. Same split `_run_survey_definition_background` makes.
    """
    from resource_explorer.registry import ProjectRegistry

    if is_ingest is None or (steps is None and not is_ingest):
        resolved_ingest, resolved_steps = resolve_analysis_plan(analysis_id)
        is_ingest = resolved_ingest if is_ingest is None else is_ingest
        steps = resolved_steps if steps is None else steps

    registry = registry or ProjectRegistry()
    project = registry.get(slug)
    if not project:
        # Can't happen when a route checked synchronously first — but this now
        # also runs from a queue worker minutes after the enqueue, so "the
        # world has not moved" is a weaker assumption than it was.
        return AnalysisRunResult(status="error", error=f"Project '{slug}' not found")

    if is_ingest:
        from resource_explorer.ingestion.incremental import IncrementalIndexer
        from resource_explorer.query_cache import QueryCache

        IncrementalIndexer().refresh(project)
        QueryCache().invalidate_project(slug)
        return AnalysisRunResult(
            status="ok", summary="Re-ingested into pgvector.", published=None,
        )

    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

    result = SurveyOrchestrator(registry).run(slug, steps=steps)
    if result.errors:
        return AnalysisRunResult(status="error", error="; ".join(result.errors))
    summary = f"{len(result.annotations)} annotation(s)."

    # Auto-publish, gated the same way survey_definition_executor.py's Survey
    # Definition path is (has_assigned_egeria_project): an Assessment/Analysis
    # "Run →" against an assigned resource reaches Egeria without a separate
    # manual Publish click. Scoped to exactly the steps that just ran (this
    # `result`, not a fresh full survey), same as the manual Publish button's
    # own `steps` scoping — so last-published attribution
    # (get_last_published_annotation_types) stays accurate to what actually ran.
    # Publish failure must not turn an otherwise-successful survey into a
    # reported error: the findings are real and stored either way.
    published = None
    if result.annotations and registry.has_assigned_egeria_project("repo", slug):
        try:
            from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher

            # Already off any FastAPI event loop here — this function runs in a
            # worker thread, never on the loop. No asyncio.to_thread: pyegeria's
            # synchronous methods drive their own event loop internally, which
            # is what made the OLD synchronous route (this call wrapped in
            # asyncio.to_thread from inside a running loop) raise "this event
            # loop is already running" and fail auto-publish on every
            # Egeria-bound project reached through this route, softly, into
            # `summary`, with the run still reporting ok.
            EgeriaPublisher(registry=registry).publish(result)
            published = True
        except Exception as exc:
            published = False
            summary += f" (⚠ auto-publish to Egeria failed: {exc})"
            log.warning("Auto-publish failed for %s/%s: %s", slug, analysis_id, exc)

    # Carried out of here so the caller can write them onto the activity entry.
    # Without this the RFA drawer never saw a single annotation from an
    # Analyses-card run — see registry.update_activity_status() for the
    # measurement.
    from resource_explorer.surveyors.survey_report import summarise_annotations

    # Belt and braces with summarise_annotations' own skip: a run that produced
    # and stored real findings must never be reported as failed because the
    # sentence describing it could not be built.
    try:
        ann_summary = summarise_annotations(result.annotations)
    except Exception as exc:
        log.warning("Could not summarise annotations for %s/%s: %s", slug, analysis_id, exc)
        ann_summary = []

    return AnalysisRunResult(
        status="ok", summary=summary, published=published, annotations=ann_summary,
    )


def run_stage_batch(
    slug: str, stage: str, step_keys: list[str], *, registry=None,
) -> StageBatchResult:
    """Run every step of one Funnel stage as a single orchestrator call.

    Uses the adapter's `_run_batch`, the same primitive
    survey_definition_executor.py uses to run a multi-step Survey Definition in
    one SurveyOrchestrator.run() — this just derives its step_keys from the
    catalog's intent tags instead of from an authored Survey Definition, so it
    cannot drift out of sync as analyses are added to a stage.
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.repo_survey_definition_adapter import _run_batch
    from resource_explorer.surveyors.survey_report import summarise_annotations

    registry = registry or ProjectRegistry()
    project = registry.get(slug)
    result = _run_batch(project, registry, step_keys)
    ann_summary = summarise_annotations(result["annotations"])
    errors = result.get("errors") or []
    # An error only makes the whole batch an error when NOTHING was produced —
    # a 12-step batch where one step failed still wrote 11 steps' findings.
    status = "error" if errors and not result["annotations"] else "ok"
    n = len(step_keys)
    summary = f"Ran all {n} {stage} step(s)" + (f" — {len(errors)} error(s)" if errors else "")
    return StageBatchResult(
        status=status, stage=stage, step_keys=list(step_keys), summary=summary,
        errors=errors, annotations=ann_summary,
    )


# ── recording onto the activity entry ────────────────────────────────────────
#
# The route used to do this inline in its background thread. It lives here so
# the queue worker records a run in EXACTLY the same shape a route-spawned
# thread did — the frontend polls GET /api/activity/{id} and reads the run's
# result out of that entry's `detail`, and that contract must not depend on
# which process ran the work.


def execute_and_record_analysis(slug: str, analysis_id: str, activity_id: str,
                                *, registry=None) -> AnalysisRunResult:
    """Run one analysis and write its terminal status onto `activity_id`."""
    from resource_explorer.registry import ProjectRegistry

    registry = registry or ProjectRegistry()
    is_ingest, steps = resolve_analysis_plan(analysis_id)
    try:
        result = run_analysis(
            slug, analysis_id, is_ingest=is_ingest, steps=steps, registry=None,
        )
    except Exception as exc:  # pragma: no cover — genuinely unexpected
        log.exception("Analysis run crashed for %s/%s", slug, analysis_id)
        registry.update_activity_status(
            activity_id, "error", summary=f"'{analysis_id}' run crashed: {exc}",
            detail=json.dumps({"analysis_id": analysis_id, "published": None,
                               "error": str(exc)}),
        )
        return AnalysisRunResult(status="error", error=str(exc))

    summary = result.summary or result.error or ""
    detail = {"analysis_id": analysis_id, "published": result.published}
    if result.status == "error":
        detail["error"] = result.error or summary
    else:
        detail["message"] = summary
    registry.update_activity_status(
        activity_id, result.status, summary=summary, detail=json.dumps(detail),
        annotations=result.annotations or None,
    )
    return result


def execute_and_record_stage_batch(slug: str, stage: str, step_keys: list[str],
                                   activity_id: str, *, registry=None) -> StageBatchResult:
    """Run a stage batch and write its terminal status onto `activity_id`."""
    from resource_explorer.registry import ProjectRegistry

    registry = registry or ProjectRegistry()
    try:
        result = run_stage_batch(slug, stage, step_keys, registry=registry)
    except Exception as exc:  # pragma: no cover — genuinely unexpected
        log.exception("Stage-batch run crashed for %s/%s", slug, stage)
        registry.update_activity_status(
            activity_id, "error", summary=f"Run all {stage} crashed: {exc}",
            detail=json.dumps({"stage": stage, "step_keys": step_keys, "error": str(exc)}),
        )
        return StageBatchResult(status="error", stage=stage, step_keys=list(step_keys),
                                errors=[str(exc)])

    registry.update_activity_status(
        activity_id, result.status, summary=result.summary,
        detail=json.dumps({"stage": stage, "step_keys": step_keys, "errors": result.errors}),
        annotations=result.annotations,
    )
    return result
