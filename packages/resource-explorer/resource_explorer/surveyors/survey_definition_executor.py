"""
Generic dispatch loop for executing a Survey Definition's RE-side steps.

Fetches a Survey Definition from Egeria (via SurveyDefinitionReader), walks its
ordered steps, and for each step tagged executes_at="resource-explorer" dispatches
to the matching local surveyor via a per-resource-type ResourceTypeAdapter. Steps
tagged for another engine (e.g. "egeria", "airflow") are skipped — that's someone
else's responsibility to run.

This module has no resource-type-specific logic itself; each resource type
(database, repo, filesystem) registers its own small adapter — see
resource_explorer/surveyors/database/survey_definition_adapter.py,
resource_explorer/surveyors/repo_survey_definition_adapter.py, and
resource_explorer/surveyors/filesystem/survey_definition_adapter.py.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from resource_explorer.surveyors import result_status
from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader

log = logging.getLogger(__name__)

from resource_explorer.activity_logger import log_survey


class SurveyDefinitionExecutorError(RuntimeError):
    """Raised for executor-level errors (unknown entity type, ambiguous/missing
    Survey Definition, technology-type mismatch) — distinct from per-step failures,
    which are accumulated in the result's "errors" list instead of raised."""


@dataclass
class ResourceTypeAdapter:
    entity_type: str
    technology_type: str
    re_analysis_steps: dict  # re_analysis_step -> Callable(entity, registry, **kwargs) -> dict
    get_entity: Callable  # (registry, slug) -> entity | None
    publish: Callable  # (entity, step_outputs: list[dict], surveyed_at: str, registry) -> str (report_guid)
    # re_analysis_step -> {"description": str, "annotation_types": list[str]} — lets
    # UI/API callers explain what a step actually does/produces before running it,
    # without needing a live Egeria round-trip (RE already knows this about its own
    # steps). Optional: steps that exist in re_analysis_steps but have no entry
    # here just won't get a description/annotation-type hint shown.
    re_analysis_step_info: dict = field(default_factory=dict)
    # executes_at value (e.g. "egeria") -> Callable(entity, registry, step, **kwargs)
    # -> dict. For steps NOT tagged "resource-explorer" that this resource type can
    # still actively do something about — e.g. triggering Egeria's own native
    # survey engine for an "egeria"-tagged step, rather than only ever skipping it.
    # Optional: engines with no handler here are still just skipped/logged, same
    # as before this existed.
    other_engine_handlers: dict = field(default_factory=dict)
    # Egeria's own real Technology Type display name (e.g. "PostgreSQL Relational
    # Database") — deliberately separate from `technology_type` above, which is
    # only the free-text string RE's own authored Survey Definitions happen to be
    # tagged with via additionalProperties.supported_technology_type. The two are
    # NOT guaranteed to match (confirmed live 2026-07-08: our own authored
    # "SimplePostgresSurvey" uses "PostgreSQL Database", which isn't a real
    # registered Technology Type at all). This field is used to query Egeria's
    # real Technology Type catalog (EgeriaTechTypeCatalog) for what a native
    # survey step actually produces. Optional: leave blank if unknown.
    egeria_technology_type_name: str = ""
    # Optional: (entity, registry, re_analysis_step_keys: list[str], **kwargs) ->
    # {"annotations": [...], "errors": [...]}. When set, the dispatch loop below
    # groups consecutive "resource-explorer" steps into ONE call here instead of
    # calling re_analysis_steps[key] once per step — real fix, not a
    # micro-optimization: per-step dispatch means any step declaring a shared
    # D6 resource (e.g. repo's zipball_root) re-acquires it independently every
    # time, since trellis_microflow.resolve_resources only dedupes *within* a
    # single SurveyOrchestrator.run() call. A Survey Definition whose steps all
    # need the same zipball (e.g. a "Coarse Profile" survey) would otherwise
    # download it once per step. None (default, every adapter before this
    # existed) keeps the exact prior one-call-per-step behavior.
    run_batch: Callable | None = None


_ADAPTERS: dict = {}


def register_adapter(adapter: ResourceTypeAdapter) -> None:
    """Register a ResourceTypeAdapter for its entity_type. Called once at import
    time by each resource type's survey_definition_adapter module."""
    _ADAPTERS[adapter.entity_type] = adapter


def get_adapter(entity_type: str) -> ResourceTypeAdapter:
    # Import adapters lazily so this module doesn't force-import every resource
    # type's Egeria-coupled surveyor code just to construct an executor.
    if entity_type not in _ADAPTERS:
        if entity_type == "database":
            import resource_explorer.surveyors.database.survey_definition_adapter  # noqa: F401
        elif entity_type == "repo":
            import resource_explorer.surveyors.repo_survey_definition_adapter  # noqa: F401
        elif entity_type == "filesystem":
            import resource_explorer.surveyors.filesystem.survey_definition_adapter  # noqa: F401
    adapter = _ADAPTERS.get(entity_type)
    if adapter is None:
        raise SurveyDefinitionExecutorError(
            f"No Survey Definition adapter registered for entity_type={entity_type!r}. "
            f"Known types: {sorted(_ADAPTERS)}"
        )
    return adapter


class SurveyDefinitionExecutor:
    def __init__(self, registry, reader: SurveyDefinitionReader | None = None) -> None:
        self.registry = registry
        self.reader = reader or SurveyDefinitionReader()

    def run(
        self,
        entity_type: str,
        slug: str,
        technology_type: str | None = None,
        survey_definition_ref: str | None = None,
        refresh_definition: bool = False,
        **runner_kwargs: Any,
    ) -> dict:
        surveyed_at = datetime.utcnow().isoformat()
        adapter = get_adapter(entity_type)
        tech_type = technology_type or adapter.technology_type

        entity = adapter.get_entity(self.registry, slug)
        if entity is None:
            raise SurveyDefinitionExecutorError(
                f"{entity_type} '{slug}' not found in registry"
            )

        process_guid, process_qn = self._resolve_process_guid(
            entity_type, slug, tech_type, survey_definition_ref, refresh_definition
        )

        survey_def = self.reader.fetch(process_guid)
        if (
            survey_def.supported_technology_type
            and survey_def.supported_technology_type != tech_type
        ):
            raise SurveyDefinitionExecutorError(
                f"Survey Definition '{survey_def.qualified_name}' declares "
                f"supported_technology_type={survey_def.supported_technology_type!r}, "
                f"which does not match the requested {tech_type!r}"
            )

        if not survey_def.steps:
            raise SurveyDefinitionExecutorError(
                f"Survey Definition '{survey_def.qualified_name}' (guid={process_guid}) "
                "was fetched successfully but resolved to zero steps. Either it genuinely "
                "has no steps linked via Link First/Next Process Step, or the graph's "
                "first-step relationship wasn't recognized by SurveyDefinitionReader — "
                "this is the one part of the reader not yet validated against a live "
                "server (see docs/survey-definitions.md, Current Limitations)."
            )

        steps_report: list = []
        step_outputs: list = []
        errors: list = []

        def _stamp_definition_provenance(output) -> None:
            """Give every keyless annotation this call's `output` carries an
            item_key naming the Survey Definition being executed, so a step
            authored into more than one definition (e.g. `repo_secret_scan`,
            included by both repo-survey-definition-compliance.md and
            repo-survey-definition-full.md) cannot collide on publish —
            see survey_report.assert_unique_qualified_names, which raises
            exactly this collision rather than letting it silently drop an
            annotation.

            Stamped here, at the one place every RE-executed step's
            annotations pass through on their way into `step_outputs`
            (single-step, batched, and Prefect-routed alike), rather than in
            each sub-surveyor — so a step that has never anticipated running
            under more than one definition is covered automatically, and the
            fix does not have to be repeated for the next shared step.

            A step's own item_key (language, ecosystem, file_path,
            secret_pattern's path:line...) is left untouched: this only
            fills the gap for a check that is "one summary per run" and
            never set one, which is exactly the shape that collides.
            """
            if not isinstance(output, dict):
                return
            for ann in output.get("annotations", []) or []:
                # Defensive: a handful of dispatch-loop tests stand in
                # "annotations" with plain dicts/strings rather than real
                # Annotation instances — nothing to stamp on those, and
                # nothing this fix should need to care about.
                if not hasattr(ann, "item_key"):
                    continue
                if not ann.item_key:
                    ann.item_key = survey_def.qualified_name

        # Hand the WHOLE definition to Prefect when it is available, instead of
        # sequencing it here. RE should not be a workflow engine: Egeria
        # coordinates and RE executes leaves, or RE coordinates and delegates
        # the workflow to Prefect. The loop below is the third thing — RE as
        # sequencer, Prefect as task runner — which is the inversion of that.
        #
        # Gated on prefect.enabled, so a deployment without Prefect keeps the
        # local loop. That fallback is not temporary: an offline or
        # Prefect-less run has to keep working, which is the same argument that
        # made Automate local-first.
        # Whatever the local loop still has to do. Prefect having run the
        # definition leaves it empty; everything AFTER the loop — publishing,
        # the activity entry, the assembled result — is shared, so the two
        # paths differ only in who sequenced the steps.
        pending_steps = survey_def.steps
        if _prefect_orchestration_enabled():
            planned = self._run_via_prefect(entity_type, entity, survey_def, runner_kwargs)
            if planned is not None:
                steps_report, step_outputs, errors = planned
                for _output in step_outputs:
                    _stamp_definition_provenance(_output)
                pending_steps = []

        # Order + guard information for the local loop below. Only built when
        # the local loop is actually going to run something — Prefect having
        # taken the whole definition (pending_steps == []) already evaluated
        # guards itself, via prefect/flows.py::run_planned_step_task, and
        # walked `survey_execution_plan`'s own topological order.
        #
        # docs/survey-guard-evaluation-design.md §2.5/§5: before this, the
        # local loop walked `survey_def.steps` — the reader's flat,
        # topologically-ordered-but-unbranched list — with no reference to
        # `.links`/guards at all. Every step ran, always, regardless of what
        # any upstream produced. This is the fallback docs/survey-model-and-
        # engine-host-design.md §4.6 says must keep working indefinitely for
        # an offline/Prefect-less run, so it has to be correct on its own,
        # not merely "correct because every live definition today is
        # unbranched" (true, but an accident of what's authored, not a
        # property of this code).
        plan_by_key: dict = {}
        produced_guard: dict = {}
        if pending_steps:
            from resource_explorer.surveyors.survey_execution_plan import (
                CyclicPlanError,
                build_plan,
            )

            try:
                plan = build_plan(survey_def)
            except CyclicPlanError as exc:
                # Same treatment as _run_via_prefect's identical guard: never
                # run part of a survey whose steps cannot be ordered at all
                # and call it complete.
                raise SurveyDefinitionExecutorError(str(exc)) from exc

            plan_by_key = {ps.qualified_name: ps for ps in plan.steps}
            # Reorder pending_steps to the plan's topological order (a no-op
            # for every definition that runs today — 4.5's own verification
            # note: "every live definition plans to exactly its current
            # order"). A step the plan didn't resolve (defensive only; every
            # step in survey_def.steps came from the same survey_def the plan
            # was built from) is appended rather than dropped, in its
            # original position, so nothing silently vanishes from the run.
            by_qn = {s.qualified_name: s for s in pending_steps}
            ordered = [by_qn[ps.qualified_name] for ps in plan.steps if ps.qualified_name in by_qn]
            seen_qns = {s.qualified_name for s in ordered}
            ordered.extend(s for s in pending_steps if s.qualified_name not in seen_qns)
            pending_steps = ordered

        def _step_key(step) -> str:
            """The same key `survey_execution_plan.build_plan` uses (its own
            `key_of`, not exported): `re_analysis_step`, falling back to
            `qualified_name`. Kept in sync deliberately — `guarded_by` dicts
            are keyed by this, so a diverging key function here would make
            every guard silently never match."""
            return step.re_analysis_step or step.qualified_name or ""

        def _guard_check(step) -> tuple[bool, str]:
            """(may_run, reason). True with no reason when the step is
            unconditional (no PlannedStep found, or an empty `guarded_by`) —
            the overwhelmingly common case today, since authored guards are
            held at "Any" (step_outcome.py's 2026-08-21 decision) until a
            real branching definition exists.

            Egeria fires a step if ANY ONE of its guarded incoming links is
            satisfied (verified against EngineActionHandler.java — see
            docs/survey-guard-evaluation-design.md §1). This instead requires
            EVERY guarded incoming edge to match, the same simplification
            prefect/flows.py::run_planned_step_task already makes — kept
            consistent between the two paths rather than fixed in one and not
            the other; §2.3 of the design doc explains why it makes no
            observable difference to any definition that exists today.
            `mandatoryGuard`'s join semantics are not evaluated at all: the
            plan has nowhere to carry them (§2.2) — a gap, not a choice.
            """
            planned = plan_by_key.get(step.qualified_name)
            guarded_by = getattr(planned, "guarded_by", None) if planned else None
            if not guarded_by:
                return True, ""
            for upstream_key, required in guarded_by.items():
                produced = produced_guard.get(upstream_key)
                if produced != required:
                    return False, (
                        f"guard {required!r} required from {upstream_key!r} but it "
                        + (f"produced {produced!r}" if upstream_key in produced_guard
                           else "was never recorded — no step output in this run "
                                "carried a 'guard' key for it")
                    )
            return True, ""

        from resource_explorer.config import get_config
        from resource_explorer.surveyors.prefect_adapter import PrefectFlowRunCancelled, run_prefect_step

        # Steps that exist only as Prefect flows (resource_explorer/prefect/flows.py)
        # and have no STEP_REGISTRY entry, so there is nothing local to run them
        # with. Named here rather than inline so the list is findable from both
        # sides; they should carry executes_at="prefect" once authored.
        PREFECT_ONLY_STEPS = ("soda_data_quality", "great_expectations_validation")

        def _use_prefect(step) -> bool:
            """Which engine runs this step.

            executes_at is what the definition asked for, and it is honoured.
            `prefect.enabled` says Prefect is reachable — it does not re-route a
            step that named a different engine; `prefect.route_local_steps` is
            the explicit opt-in for that, because taking RE's own steps to
            Prefect is a real deployment choice but not one to make silently.
            """
            if step.executes_at == "prefect" or step.re_analysis_step in PREFECT_ONLY_STEPS:
                return True
            if step.executes_at == "resource-explorer":
                try:
                    cfg = get_config().prefect
                    return bool(cfg.enabled and getattr(cfg, "route_local_steps", False))
                except Exception:
                    return False
            return False

        i = 0
        n = len(pending_steps)
        while i < n:
            step = pending_steps[i]

            # Egeria's guard, evaluated — see docs/survey-guard-evaluation-design.md
            # §1/§5. A step whose guard is not satisfied by what its upstream(s)
            # produced did not happen, on this branch, in this run: emitted as
            # SKIPPED_BY_DESIGN via result_status's own vocabulary, not as
            # silence and not as an error (a branch not taken is not a failure).
            may_run, guard_reason = _guard_check(step)
            if not may_run:
                log.info("Skipping %s — %s", step.qualified_name, guard_reason)
                steps_report.append({
                    "step": step.qualified_name,
                    "status": result_status.SKIPPED_BY_DESIGN,
                    "detail": guard_reason,
                })
                i += 1
                continue

            use_prefect = _use_prefect(step)

            # D1 (docs/survey-tab-unification-plan.md) — batch a run of consecutive
            # plain "resource-explorer" steps into one adapter.run_batch()
            # call instead of dispatching each individually, when the
            # adapter supports it (repo does; database/filesystem don't yet
            # — run_batch=None there keeps their exact prior per-step path).
            # Only steps this adapter actually recognizes are eligible; an
            # unknown step_key breaks the group so it still gets the normal
            # "unknown_step" report below, not silently absorbed.
            if (
                not use_prefect
                and step.executes_at == "resource-explorer"
                and adapter.run_batch is not None
                and step.re_analysis_step in adapter.re_analysis_steps
            ):
                group = [step]
                j = i + 1
                while j < n:
                    nxt = pending_steps[j]
                    if (
                        _use_prefect(nxt)
                        or nxt.executes_at != "resource-explorer"
                        or nxt.re_analysis_step not in adapter.re_analysis_steps
                        or not _guard_check(nxt)[0]
                    ):
                        break
                    group.append(nxt)
                    j += 1

                if len(group) > 1:
                    step_keys = [s.re_analysis_step for s in group]
                    try:
                        output = adapter.run_batch(entity, self.registry, step_keys, **runner_kwargs)
                        _stamp_definition_provenance(output)
                        step_outputs.append(output)
                        batch_errors = output.get("errors") or []
                        # Batched steps share one status — real, minor cost
                        # of the fix: a partial failure within the group
                        # can't be pinpointed to the exact step_key without
                        # instantiating each surveyor just to read its
                        # step_name, which the batch call deliberately
                        # avoids. The combined error text is still fully
                        # visible in `errors` below and in each step's own
                        # "detail" here — not silently swallowed, just not
                        # individually attributed.
                        status = "error" if batch_errors else "ok"
                        # One output for the whole group (`run_batch`'s point —
                        # see its docstring), so one guard for the whole group:
                        # the same "shared status" limitation the comment above
                        # already names, not a new one.
                        batch_guard = output.get("guard") if isinstance(output, dict) else None
                        for s in group:
                            entry = {"step": s.qualified_name, "status": status}
                            if batch_errors:
                                entry["detail"] = "; ".join(batch_errors)
                            steps_report.append(entry)
                            produced_guard[_step_key(s)] = batch_guard
                        errors.extend(batch_errors)
                    except Exception as exc:
                        msg = f"RE batch steps {step_keys} failed: {exc}"
                        log.exception(msg)
                        errors.append(msg)
                        for s in group:
                            steps_report.append({"step": s.qualified_name, "status": "error", "detail": str(exc)})
                    i = j
                    continue
                # group of exactly 1 — fall through to the identical
                # single-step path below, unchanged from before batching.

            if use_prefect:
                try:
                    output = run_prefect_step(entity_type, entity.slug, step.re_analysis_step, runner_kwargs)
                    _stamp_definition_provenance(output)
                    step_outputs.append(output)
                    steps_report.append({"step": step.qualified_name, "status": "ok", "engine": "prefect"})
                    produced_guard[_step_key(step)] = output.get("guard") if isinstance(output, dict) else None
                except PrefectFlowRunCancelled as exc:
                    # Distinct from a generic failure — this is the user
                    # actually stopping the survey (via the Admin "⚡ Prefect"
                    # panel's Cancel button), not something breaking. Surfaced
                    # as its own status so the activity log reads "cancelled",
                    # not "error", for what was a deliberate action.
                    msg = f"Prefect step '{step.re_analysis_step}' was cancelled: {exc}"
                    log.info(msg)
                    errors.append(msg)
                    steps_report.append({"step": step.qualified_name, "status": "cancelled", "engine": "prefect"})
                except Exception as exc:
                    msg = f"Prefect step '{step.re_analysis_step}' failed: {exc}"
                    log.exception(msg)
                    errors.append(msg)
                    steps_report.append({"step": step.qualified_name, "status": "error", "engine": "prefect"})
            elif step.executes_at == "resource-explorer":
                runner = adapter.re_analysis_steps.get(step.re_analysis_step)
                if runner is None:
                    msg = (
                        f"Unknown re_analysis_step '{step.re_analysis_step}' in step "
                        f"{step.qualified_name} — {entity_type} adapter only knows: "
                        f"{sorted(adapter.re_analysis_steps)}"
                    )
                    log.error(msg)
                    errors.append(msg)
                    steps_report.append({"step": step.qualified_name, "status": "unknown_step"})
                    i += 1
                    continue
                try:
                    output = runner(entity, self.registry, **runner_kwargs)
                    _stamp_definition_provenance(output)
                    step_outputs.append(output)
                    steps_report.append({"step": step.qualified_name, "status": "ok"})
                    produced_guard[_step_key(step)] = output.get("guard") if isinstance(output, dict) else None
                except Exception as exc:
                    msg = f"RE step '{step.re_analysis_step}' failed: {exc}"
                    log.exception(msg)
                    errors.append(msg)
                    steps_report.append({"step": step.qualified_name, "status": "error"})
            elif step.executes_at in adapter.other_engine_handlers:
                handler = adapter.other_engine_handlers[step.executes_at]
                try:
                    outcome = handler(entity, self.registry, step, **runner_kwargs)
                    steps_report.append({
                        "step": step.qualified_name,
                        "status": "triggered",
                        **({"detail": outcome} if isinstance(outcome, dict) else {}),
                    })
                except Exception as exc:
                    msg = f"Failed to trigger {step.executes_at} for step '{step.qualified_name}': {exc}"
                    log.exception(msg)
                    errors.append(msg)
                    steps_report.append({"step": step.qualified_name, "status": "error"})
            elif step.executes_at == "egeria":
                # Real, live-reported gap (2026-08-24 — "closing the stub"):
                # this used to log.info and move on with no entry in `errors`
                # at all, so a mixed Survey whose Egeria-native step has no
                # registered other_engine_handlers reported "Survey
                # Definition run complete" — a silent lie, not a warning.
                # RE's own client-side step-walk is the only thing driving
                # execution today (per docs/unified-survey-execution-model-
                # plan.md's D1/D8 — Egeria's MAS doesn't independently create
                # Engine Actions for any step type yet), so a step that lands
                # here genuinely never runs anywhere, not "runs elsewhere
                # without RE watching." That's a real failure of this run's
                # completeness, not a benign no-op — now counted in `errors`
                # accordingly, distinct wording from an actual step
                # exception so it reads as "never executed," not "broke."
                msg = (
                    f"Step {step.qualified_name} was not executed: executes_at=egeria but no "
                    f"other_engine_handlers['egeria'] is registered for entity_type={entity_type!r} "
                    "(see database/survey_definition_adapter.py's _trigger_egeria_native_survey "
                    "for the pattern to add one)"
                )
                log.warning(msg)
                errors.append(msg)
                steps_report.append({"step": step.qualified_name, "status": "not_executed_no_egeria_handler"})
            else:
                msg = (
                    f"Skipping step {step.qualified_name}: unrecognized executes_at="
                    f"{step.executes_at!r} (only 'resource-explorer' and 'egeria' are "
                    "understood today)"
                )
                log.warning(msg)
                errors.append(msg)
                steps_report.append({"step": step.qualified_name, "status": "unrecognized_engine"})

            i += 1

        # Gated on the resource actually having an assigned Egeria Project — this
        # used to publish unconditionally for any repo a Survey Definition ran
        # against, decided-in-Egeria or not (confirmed live 2026-08-27, alongside
        # egeria.py's manual-publish route, which HAS always gated this). Findings
        # are stored locally either way; only the automatic Egeria write is
        # skipped for an unassigned resource. Manual publish is still available
        # to catalog an unassigned resource explicitly, or to re-publish.
        report_guid = ""
        published = False
        if step_outputs and self.registry.has_assigned_egeria_project(entity_type, slug):
            try:
                report_guid = adapter.publish(entity, step_outputs, surveyed_at, self.registry)
                published = True
            except Exception as exc:
                msg = f"Failed to publish results to Egeria: {exc}"
                log.exception(msg)
                errors.append(msg)

        # Record that this Survey Definition ran.
        #
        # It never did. The executor has carried zero log_survey calls since it
        # was written, so a Survey Definition could run any number of times and
        # its card still read "Never run" — get_survey_definition_last_activity
        # looks for an activity row of operation 'survey' keyed on
        # `survey_definition_ref`, and nothing wrote one. The card was reporting
        # the activity log accurately; the log was empty.
        #
        # The ref is what makes the row attributable to THIS definition rather
        # than to the repo generally.
        ran = sum(1 for r in steps_report if r.get("status") in ("ok", "triggered"))
        try:
            log_survey(
                self.registry, entity_type, slug,
                getattr(entity, "display_name", "") or slug,
                getattr(entity, "github_url", "") or "",
                intent="discovery",
                status="error" if errors else "ok",
                summary=(f"{survey_def.display_name}: {ran} of {len(steps_report)} step(s) ran"
                         + (f", {len(errors)} error(s)" if errors else "")),
                detail=json.dumps({
                    "survey_definition_ref": process_qn,
                    "process_guid": process_guid,
                    "steps": steps_report,
                    "errors": errors,
                    "published": published,
                    "egeria_report_guid": report_guid,
                }),
            )
            run_recorded = True
        except Exception as exc:
            # A survey that ran must not report failure because its bookkeeping
            # failed — but the caller has to be able to tell. Returned as a
            # field, not just logged: a silent miss here is precisely what
            # produced "Never run", and a second silent miss would look
            # identical to the first.
            run_recorded = False
            log.warning("could not record the survey run for %s: %s", process_qn, exc)

        return {
            "source": "survey-definition",
            "entity_type": entity_type,
            "slug": slug,
            "process_guid": process_guid,
            "process_qualified_name": process_qn,
            "surveyed_at": surveyed_at,
            "steps": steps_report,
            "errors": errors,
            "egeria_report_guid": report_guid,
            "published": published,
            # False when the run happened but could not be written to the
            # activity log — the card will say "Never run" and be wrong.
            "run_recorded": run_recorded,
        }

    def _run_via_prefect(self, entity_type, entity, survey_def, runner_kwargs):
        """(steps_report, step_outputs, errors) from one Prefect flow, or None.

        Returns None rather than raising when the plan cannot be built or
        Prefect cannot be reached, so an orchestration problem degrades to the
        local loop instead of failing a survey the loop could have run. The
        reason is logged — a silent fallback would make "Prefect ran this" and
        "Prefect was never reachable" look identical in the report.
        """
        from resource_explorer.surveyors.survey_execution_plan import (
            CyclicPlanError,
            build_plan,
            serialise,
        )

        try:
            plan = build_plan(survey_def)
        except CyclicPlanError as exc:
            # Not a fallback case: the local loop would run a cyclic definition
            # in list order and report success for a survey that cannot be
            # ordered at all.
            raise SurveyDefinitionExecutorError(str(exc)) from exc

        if not plan.steps:
            return None
        try:
            from resource_explorer.prefect.flows import re_survey_definition_flow

            report = re_survey_definition_flow(
                entity_type=entity_type, slug=entity.slug,
                plan=serialise(plan), runner_kwargs=runner_kwargs or {},
            )
        except Exception as exc:
            log.warning(
                "Prefect orchestration unavailable for %s (%s) — falling back to "
                "in-process sequencing", survey_def.qualified_name, exc)
            return None

        return (
            [{k: v for k, v in entry.items() if k != "output"} for entry in report],
            [entry["output"] for entry in report
             if entry.get("status") == "ok" and entry.get("output")],
            [f"{e['step_key']}: {e.get('detail', 'failed')}"
             for e in report if e.get("status") == "error"],
        )

    def _resolve_process_guid(
        self,
        entity_type: str,
        slug: str,
        technology_type: str,
        survey_definition_ref: str | None,
        refresh_definition: bool,
    ) -> tuple:
        if survey_definition_ref:
            guid = self.reader.find_process_guid_by_name(survey_definition_ref)
            if not guid:
                raise SurveyDefinitionExecutorError(
                    f"No Survey Definition found matching '{survey_definition_ref}'"
                )
            self.registry.set_survey_definition_guid(
                entity_type, slug, technology_type, guid, survey_definition_ref
            )
            return guid, survey_definition_ref

        if not refresh_definition:
            cached = self.registry.get_survey_definition_guid(entity_type, slug, technology_type)
            if cached:
                return cached["process_guid"], cached["process_qualified_name"]

        candidates = self.reader.find_candidate_process_guids(technology_type)
        if not candidates:
            raise SurveyDefinitionExecutorError(
                f"No Survey Definition found in Egeria for technology type "
                f"'{technology_type}'. Author one first (see "
                "docs/egeria-collaboration-and-survey-model.md section 6.3)."
            )
        if len(candidates) > 1:
            names = ", ".join(c["qualified_name"] for c in candidates)
            raise SurveyDefinitionExecutorError(
                f"Multiple Survey Definitions found for technology type "
                f"'{technology_type}': {names}. Disambiguate with --survey-definition."
            )

        chosen = candidates[0]
        self.registry.set_survey_definition_guid(
            entity_type, slug, technology_type, chosen["guid"], chosen["qualified_name"]
        )
        return chosen["guid"], chosen["qualified_name"]


def run_survey_definition(entity_type: str, slug: str, registry=None, **kwargs: Any) -> dict:
    """Convenience function mirroring run_hybrid_survey's shape."""
    if registry is None:
        from resource_explorer.registry import ProjectRegistry
        registry = ProjectRegistry()
    executor = SurveyDefinitionExecutor(registry)
    return executor.run(entity_type, slug, **kwargs)


def _prefect_orchestration_enabled() -> bool:
    """Whether Prefect should sequence a whole Survey Definition.

    Reads the same `prefect.enabled` switch the per-step dispatch already
    honours, so there is one answer to "is Prefect available here" rather than
    two that can disagree.
    """
    try:
        from resource_explorer.config import get_config

        return bool(get_config().prefect.enabled)
    except Exception as exc:  # pragma: no cover - config guard
        log.debug("could not read prefect config, assuming disabled: %s", exc)
        return False
