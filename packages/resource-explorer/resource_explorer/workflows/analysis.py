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
        REPO_ANALYSIS_SOURCE_STEPS,
    )

    catalog_entry = next(
        (a for a in get_analyses("repo", include_egeria_live=False) if a["id"] == analysis_id),
        None,
    )
    is_ingest = bool(catalog_entry and catalog_entry.get("action") == "ingest")
    # SOURCE steps: this resolves what to RUN. An analysis that owns no steps
    # (architecture_diagram) still runs its source's — off the ownership map it
    # would resolve to [] and the caller would report it undispatchable.
    steps = None if is_ingest else REPO_ANALYSIS_SOURCE_STEPS.get(analysis_id)
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
        REPO_ANALYSIS_SOURCE_STEPS,
    )

    entries = [
        a for a in get_analyses("repo", intent=stage, include_egeria_live=False)
        if a.get("action") not in ("ingest", "publish", "profile")
    ]
    step_keys: list[str] = []
    for a in entries:
        # SOURCE steps: "Run all <Stage>" must run what each entry needs, not
        # what it owns. Identical today only because architecture_diagram's
        # source is owned by architecture_recovery, which shares its intent —
        # a coincidence, not a guarantee.
        for sk in REPO_ANALYSIS_SOURCE_STEPS.get(a["id"], []):
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


def _humanise_age(seconds: float) -> str:
    """"3 minutes ago" / "2 hours ago" / "6 days ago" — coarse on purpose. The
    first version printed minutes at every scale and produced "1827 minutes
    ago", which is a number a reader has to do arithmetic on before it means
    anything."""
    if seconds < 60:
        return "less than a minute ago"
    if seconds < 3600:
        n, unit = int(seconds // 60), "minute"
    elif seconds < 86400:
        n, unit = int(seconds // 3600), "hour"
    else:
        n, unit = int(seconds // 86400), "day"
    return f"{n} {unit}{'s' if n != 1 else ''} ago"


@dataclass(frozen=True)
class Freshness:
    """Whether an analysis's data is recent enough that running it again would
    buy nothing.

    Deliberately a verdict PLUS its evidence, not a bare bool: a Run that
    declines to run has to be able to say why, and say it about the analysis
    that actually produced the data. `via` is the id whose run supplied the
    freshness — for a derived analysis that is its SOURCE, so
    `architecture_diagram` reports being fresh because `architecture_recovery`
    ran, rather than claiming a run of its own it never had.
    """

    fresh: bool
    #: "never-run" / "stale" / "fresh" — three states, because "we have no idea
    #: when this last ran" and "it ran, a while ago" are different reasons to
    #: proceed and only one of them is a measurement.
    state: str
    age_seconds: float | None
    last_run_at: str
    via: str

    def reason(self, analysis_id: str) -> str:
        """One sentence a caller can hand straight to a user."""
        if self.state == "never-run":
            return f"'{analysis_id}' has no recorded run, so it will run now."
        ago = _humanise_age(self.age_seconds or 0)
        source = "" if self.via == analysis_id else f" (via '{self.via}')"
        if self.fresh:
            return (f"'{analysis_id}' already has data from {ago}{source}; "
                    f"not running it again. Pass force=true to run anyway.")
        return f"'{analysis_id}' last produced data {ago}{source}."


def assess_freshness(registry, entity_type: str, slug: str, analysis_id: str,
                     max_age_seconds: int | None = None) -> Freshness:
    """Is `analysis_id`'s data newer than the freshness threshold?

    Reads `get_analysis_last_run`, which since 2026-09-09 credits a derived
    analysis's run to the source whose steps it actually ran — this function
    depends on that fix and would otherwise report the recovery stale moments
    after a diagram run had rewritten its data.

    Considers the analysis's SOURCES as well as itself, in the other direction:
    `architecture_diagram` derives from `architecture_recovery`'s steps, so a
    recent run of the recovery makes the diagram's data current even though the
    diagram itself has never been run. Takes the most recent of the two.

    A run recorded as `error` does NOT count as freshness — its data is the old
    data, and refusing to re-run after a failure is the one behaviour nobody
    would want.
    """
    from datetime import UTC, datetime

    from resource_explorer.config import get_config
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        repo_analysis_derived_sources,
    )

    if max_age_seconds is None:
        max_age_seconds = get_config().runs.freshness_seconds

    runs = registry.get_analysis_last_run(entity_type, slug)
    candidates = [analysis_id, *repo_analysis_derived_sources(analysis_id)]

    best_ts, best_via = None, analysis_id
    for aid in candidates:
        row = runs.get(aid) or {}
        if row.get("last_run_status") == "error":
            continue
        raw = row.get("last_run_at") or ""
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if best_ts is None or ts > best_ts:
            best_ts, best_via = ts, aid

    if best_ts is None:
        return Freshness(False, "never-run", None, "", analysis_id)

    age = (datetime.now(UTC) - best_ts).total_seconds()
    # A negative age means a clock skew or a future-dated row; treat it as stale
    # rather than as infinitely fresh, so a bad timestamp can never wedge an
    # analysis into never running again.
    fresh = 0 <= age < max_age_seconds
    return Freshness(fresh, "fresh" if fresh else "stale", age,
                     best_ts.isoformat(), best_via)
