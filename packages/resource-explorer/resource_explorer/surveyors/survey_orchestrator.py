"""Runs all sub-surveyors for a project and assembles a SurveyResult."""
from __future__ import annotations

import logging
from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime

from trellis_microflow import resolve_resources

from resource_explorer.activity_logger import log_survey
from resource_explorer.registry import ProjectRegistry
from resource_explorer.surveyors import step_cost_observer
from resource_explorer.surveyors import result_status, step_preconditions
from resource_explorer.surveyors.survey_report import summarise_annotations, ClassificationAnnotation, SurveyResult

log = logging.getLogger(__name__)

# Step-cost-tiers plan (docs/step-cost-tiers-plan.md, D2/D5) — ordinal
# position, not numeric value, is what run()'s max_fetch_cost/
# max_compute_cost filter compares against. Keep in sync with the values
# StepInfo.fetch_cost/compute_cost actually use.
# Imported, not redeclared — see repo_survey_definition_adapter's own comment
# on why one copy of the ordinal scale matters. Module-level import would be
# circular (the adapter imports this module's SurveyOrchestrator), so these are
# bound lazily at first use.
def _cost_orders() -> tuple[list[str], list[str]]:
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        COMPUTE_COST_ORDER, FETCH_COST_ORDER,
    )
    return FETCH_COST_ORDER, COMPUTE_COST_ORDER


class SurveyOrchestrator:
    """
    Runs all sub-surveyors in sequence and returns a SurveyResult.

    Parameters
    ----------
    registry        : open ProjectRegistry
    pyegeria_client : optional — passed to FileClassifierSurveyor for cache refresh
    force_refresh   : force FileTypeCache refresh even if not stale
    """

    def __init__(
        self,
        registry: ProjectRegistry,
        pyegeria_client=None,
        force_refresh: bool = False,
        data_path: str | None = None,
    ) -> None:
        self._registry = registry
        self._pyegeria_client = pyegeria_client
        self._force_refresh = force_refresh
        self._data_path = data_path  # local clone path for DataProfilerSurveyor Tier 2

    def run(
        self, resource_slug: str, steps: list[str] | None = None,
        scope_locator: str = "", fast: bool = False,
        max_fetch_cost: str | None = None, max_compute_cost: str | None = None,
    ) -> SurveyResult:
        """Survey a single project and return the assembled SurveyResult.

        steps : optional list of step keys (same vocabulary as
            repo_survey_definition_adapter.py's re_analysis_steps — e.g.
            "repo_health", "repo_api_structure") to run only those
            sub-surveyors instead of the full set. None (default) runs
            every sub-surveyor, exactly as before this parameter existed.
        scope_locator : D5/D6 repo scope-narrowing funnel plan — "" (default,
            unchanged) surveys the whole repo. A non-empty locator narrows
            corpus-shaped steps (StepInfo.accepts_scope_locator=True) to one
            cataloged sub-resource; steps that don't accept it ignore this
            entirely (they always run whole-repo, matching their
            target_shape). Only meaningful alongside steps=[...] — a scoped
            full survey isn't a supported combination and callers should
            gate on D6 target-shape compatibility before calling this with
            both set.
        fast : Scouting-tier "skip anything N+1/expensive" flag — forwarded
            only to steps whose StepInfo.accepts_fast is True (repo_health
            today, see HealthSurveyor.__init__). False (default) is every
            existing caller's exact prior behavior, unchanged.
        max_fetch_cost, max_compute_cost : step-cost-tiers plan
            (docs/step-cost-tiers-plan.md, D5) — optional ceilings on
            StepInfo.fetch_cost/compute_cost ("none"/"api"/"api_heavy"/
            "download" and "low"/"medium"/"high" respectively, compared by
            ordinal position). A step whose cost exceeds either ceiling is
            excluded from this run, same as if it had been left out of
            `steps`. Both None (default) applies no filter — every
            existing caller's exact prior behavior, unchanged. This is
            deliberately the only new surface this plan adds — no new
            survey types, no scheduler changes; see the plan's "Out of
            scope".
        """
        project = self._registry.get(resource_slug)
        if project is None:
            raise ValueError(f"Project '{resource_slug}' not found in registry.")

        surveyed_at_dt = datetime.utcnow()
        # Shared run-timestamp, passed into the surveyors that persist
        # structured findings at survey time (Phase B, D1) — lets one
        # orchestrator run's writes across those tables be correlated,
        # instead of each independently stamping datetime.utcnow() seconds
        # apart. Dependency/DataProfiler persistence isn't threaded here —
        # those write at ingest/refresh time via IngestionPipeline, a
        # separate code path this orchestrator doesn't touch.
        surveyed_at = surveyed_at_dt.isoformat()

        result = SurveyResult(
            resource_slug=project.slug,
            project_display_name=project.display_name,
            github_url=project.github_url,
            surveyed_at=surveyed_at_dt,
        )

        # Derived from STEP_REGISTRY (analysis-kind extensibility redesign) —
        # a plain (project, registry) construction is the default; the one
        # surveyor needing genuine per-instance orchestrator context that
        # isn't a D6 resource (FileClassifier's Egeria-refresh client) is
        # the only explicit special case left, kept small and commented
        # rather than forcing a fully generic instance-attr-injection
        # mechanism for just this one. StepInfo.accepts_surveyed_at marks
        # the surveyors that persist structured findings/metrics and need
        # the shared per-run timestamp threaded in.
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            STEP_REGISTRY,
            _resource_providers_for,
        )

        step_keys_to_run = (
            set(STEP_REGISTRY.keys()) if steps is None else set(steps) & STEP_REGISTRY.keys()
        )

        # D5 cost-tier filter — applied after the steps=[...] selection
        # above, same set-narrowing shape. Ordinal comparison via
        # _FETCH_COST_ORDER/_COMPUTE_COST_ORDER's index, not the string
        # values themselves.
        _FETCH_COST_ORDER, _COMPUTE_COST_ORDER = _cost_orders()
        if max_fetch_cost is not None:
            ceiling = _FETCH_COST_ORDER.index(max_fetch_cost)
            step_keys_to_run = {
                k for k in step_keys_to_run
                if _FETCH_COST_ORDER.index(STEP_REGISTRY[k].fetch_cost) <= ceiling
            }
        if max_compute_cost is not None:
            ceiling = _COMPUTE_COST_ORDER.index(max_compute_cost)
            step_keys_to_run = {
                k for k in step_keys_to_run
                if _COMPUTE_COST_ORDER.index(STEP_REGISTRY[k].compute_cost) <= ceiling
            }

        # Recorded AFTER the cost-tier narrowing, so it is what actually ran
        # rather than what was asked for — a publish attributing an analysis
        # that a cost ceiling excluded would be the same false claim in a new
        # place. Precondition skips are subtracted after the dispatch loop below,
        # for the same reason: they are not known until each step is reached.
        result.steps_run = sorted(step_keys_to_run)

        # D6 (docs/unified-survey-execution-model-plan.md): resolve every
        # shared resource any selected step needs, once, before
        # constructing any surveyor — resolve_resources dedupes across
        # however many steps asked for the same name. self._data_path is a
        # real, still-live explicit override (CLI `resource-explorer
        # refresh --data-path`) — when a caller already supplied a local
        # clone path, skip the D6 zipball download for that purpose
        # entirely rather than fetching one nothing will use.
        needed_resources: set[str] = set()
        for step_key in step_keys_to_run:
            for resource_name, kwarg_name in STEP_REGISTRY[step_key].requires_resources.items():
                if kwarg_name == "local_path" and self._data_path is not None:
                    continue
                needed_resources.add(resource_name)

        with ExitStack() as stack:
            resources = (
                resolve_resources(
                    stack, _resource_providers_for(project, self._registry), needed_resources
                )
                if needed_resources
                else {}
            )

            # Iterate STEP_REGISTRY's own insertion order, not
            # step_keys_to_run (a set — unordered) — a full run's step
            # order must stay deterministic and match the registry's
            # declared order, same as before this D6 change.
            all_surveyors = {}
            for step_key, info in STEP_REGISTRY.items():
                if step_key not in step_keys_to_run:
                    continue
                if step_key == "repo_file_classification":
                    kwargs = {
                        "pyegeria_client": self._pyegeria_client,
                        "force_refresh": self._force_refresh,
                    }
                else:
                    kwargs = {}
                if info.accepts_surveyed_at:
                    kwargs["surveyed_at"] = surveyed_at
                if info.accepts_scope_locator:
                    kwargs["scope_locator"] = scope_locator
                if info.accepts_fast:
                    kwargs["fast"] = fast
                for resource_name, kwarg_name in info.requires_resources.items():
                    if kwarg_name == "local_path" and self._data_path is not None:
                        kwargs[kwarg_name] = self._data_path
                    else:
                        kwargs[kwarg_name] = resources[resource_name]
                all_surveyors[step_key] = info.surveyor_cls(project, self._registry, **kwargs)

            if steps is None:
                selected = list(all_surveyors.items())
            else:
                selected = [(key, all_surveyors[key]) for key in steps if key in all_surveyors]

            for step_key, surveyor in selected:
                # Preconditions on stored data, before dispatch. A step whose
                # input another step produces is absent cannot say anything, and
                # running it anyway costs a slot in every downstream picture —
                # `security_summary` counts such a step among its inputs as
                # "never ran" and withholds a verdict below its floor.
                #
                # The skip is EMITTED, not omitted. `result_status.skipped()`
                # requires a reason for the same purpose it does everywhere else:
                # a step that simply disappears from a report is indistinguishable
                # from one that ran and found nothing.
                _info = STEP_REGISTRY.get(step_key)
                _ctx = getattr(_info, "requires_context", None)
                if _ctx:
                    may_run, precondition, why = step_preconditions.evaluate(
                        self._registry, project, _ctx)
                    if not may_run:
                        log.info("Skipping %s for %s — %s",
                                 surveyor.step_name, project.slug, why)
                        result.add(ClassificationAnnotation(
                            summary=f"Skipped: {why}",
                            analysis_step=surveyor.step_name,
                            candidate_classifications=[result_status.SKIPPED_BY_DESIGN],
                            confidence=0,
                            json_properties=step_preconditions.skip_status(precondition, why),
                        ))
                        result.skipped_steps[step_key] = why
                        continue

                log.info("Running %s for %s …", surveyor.step_name, project.slug)
                # Measure what the step actually costs, against what its
                # StepInfo declares. Three mis-declarations surfaced in one week
                # — a zero-fetch step calling the GitHub API, a `medium` step
                # measuring `low`, and a timing taken for the wrong function —
                # and none was catchable by a test, because each was a
                # declaration disagreeing with behaviour rather than code
                # disagreeing with itself. See step_cost_observer: it reports
                # and never corrects, deliberately.
                info = STEP_REGISTRY.get(step_key)
                with step_cost_observer.observe(
                    step_key,
                    getattr(info, "fetch_cost", ""),
                    getattr(info, "compute_cost", ""),
                ) as _observed:
                    try:
                        annotations = surveyor.run()
                        for ann in annotations:
                            result.add(ann)
                        log.info("  → %d annotation(s)", len(annotations))
                    except Exception as exc:
                        msg = f"{surveyor.step_name} raised unexpectedly: {exc}"
                        log.exception(msg)
                        result.add_error(msg)
                        # Also keyed by step, so a caller running steps on behalf
                        # of several analyses at once can tell which of them
                        # failed.
                        result.step_errors[step_key] = msg
                # Recorded outside the try so a step that RAISED is still
                # measured: a step that fails after 90 seconds of network calls
                # is exactly the case worth having a number for.
                if _observed:
                    # Attach what the step produced before judging its speed —
                    # a duration with no idea whether the step was exercised is
                    # the absence-looks-like-zero shape inside the instrument.
                    _observed[0].annotations, _observed[0].outcomes = (
                        step_cost_observer.describe_work(locals().get("annotations")))

                    _observed[0].disagreement = step_cost_observer._disagreement(_observed[0])
                    recorded = step_cost_observer.record(
                        self._registry, project.slug, _observed[0], surveyed_at)
                    if recorded == step_cost_observer.NOT_RECORDED:
                        # Branchable, not just logged: an unwritten observation
                        # is indistinguishable from a step that was never slow.
                        result.add_error(
                            f"step cost for {step_key} could not be recorded — "
                            "its cost observation is missing, not zero")

        # A skipped step did not run, so it must not stay in steps_run — which a
        # publish reads to say WHICH analyses it published. Leaving it there
        # would attribute an analysis to a step that produced nothing: the same
        # false claim the cost-ceiling comment above describes, arriving by a new
        # route. Subtracted here rather than up front because a precondition is
        # only evaluated when its step is reached.
        #
        # Caught by test_a_skip_actually_executes_end_to_end_through_the_orchestrator:
        # the annotation and skipped_steps were both already correct while
        # steps_run still said the step had run. Reading the dispatch site would
        # not have found it — only running the branch did.
        if result.skipped_steps:
            result.steps_run = sorted(
                set(result.steps_run) - set(result.skipped_steps))

        log.info(
            "Survey complete for %s: %d annotation(s), %d error(s)",
            project.slug,
            len(result.annotations),
            len(result.errors),
        )

        # Any survey counts as "surveyed" — coarse scan or deep, full or
        # step-filtered — so this is unconditional, unlike the self-logging
        # below which only applies to a full (steps=None) run.
        try:
            self._registry.update_project_surveyed_at(project.slug)
        except Exception as exc:
            log.warning("Could not update last_surveyed_at for %s: %s", project.slug, exc)

        # Self-logging only applies to a full survey. A step-filtered (partial)
        # run is always driven by a caller that writes its own, more specific
        # activity-log entry (e.g. scheduler.py's per-analysis-id dispatch, or
        # repo_survey_definition_adapter.py's Survey Definition executor) —
        # logging here too would double-log every such run.
        if steps is None:
            # Group annotations by (analysis_step, annotation_type) for a
            # compact activity log entry — NOT by step alone.
            #
            # Real bug, fixed 2026-09-01: the group key used to be just
            # `step`, so every annotation a single sub-surveyor produced in
            # one run — e.g. SecurityHygieneSurveyor's PASSING
            # ClassificationAnnotation("Security policy file present")
            # alongside its FAILING RequestForActionAnnotation("No CI
            # configuration detected") — collapsed into one dict. `summary`
            # kept the FIRST annotation seen (first-wins), but
            # `annotation_type` kept overwriting to the LAST one seen
            # (last-wins) — two different "which one won" rules on the same
            # group, which is how a passing check's summary ended up wearing
            # a RequestForAction label. GET /api/activity/rfas
            # (web/routes/activity.py) substring-matches on "RequestForAction"
            # in `annotation_type`, so every such mislabeled group surfaced
            # in the RFA drawer as a request for action nobody could act on,
            # because there was nothing to act on — the check had passed.
            #
            # Keying by (step, annotation_type) keeps a passing
            # ClassificationAnnotation and a failing RequestForActionAnnotation
            # from the same step in separate groups, so neither's summary or
            # type can leak into the other's row. Confirmed against live data
            # before this fix: two stored `docs` activity entries each carried
            # a RequestForAction-typed annotation summarised "Security policy
            # file present" — the passing check's own words, wearing the
            # failing check's label.
            # One grouping rule, shared with the Analyses-card path —
            # see summarise_annotations() for why keying on
            # (step, annotation_type) matters and what it fixed.
            ann_summary = summarise_annotations(result.annotations)

            try:
                log_survey(
                    self._registry,
                    entity_type="repo",
                    entity_slug=project.slug,
                    entity_name=project.display_name,
                    entity_location=project.github_url,
                    intent="assessment",
                    status="error" if result.errors else "ok",
                    summary=f"{len(result.annotations)} annotation(s), {len(result.errors)} error(s)",
                    detail="; ".join(result.errors) if result.errors else "",
                    annotations=ann_summary,
                )
            except Exception as exc:
                log.warning("Could not write activity log entry: %s", exc)

        return result
