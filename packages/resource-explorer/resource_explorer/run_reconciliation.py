"""Declared versus received: one completed run held against its own declaration.

A Survey Definition's steps declare what they produce — `annotation_types` on
each RE step, from the analysis catalog. A run records which steps ran and how
they ended. Publishing records which annotation types actually went into the
run's SurveyReport, keyed by that report's GUID. Nothing has ever put the
three side by side, so "six declared, four received" was invisible: the two
missing were either *ran and found nothing* (an answer) or *the step did not
finish* (a defect), and a reader could not tell which.

This module tells which, from local data only. No Egeria call: the definition
comes from its authored document, the step statuses from the activity row,
and the received types from the publish bookkeeping — all keyed to the run,
never correlated by timestamp. Timestamp correlation is the thing
docs/annotation-identity-check.md rules out, because the two clocks disagree.

Two things it is careful NOT to claim:

* **Declared is not promised.** A declaration says what to expect and
  therefore what an absence *means*. It never says what happened. Every
  verdict below is derived from the run record, not from the declaration.
* **Unpublished is not empty.** An unpublished run has no report GUID, so
  nothing can be listed under it from here. That is "cannot be listed", and
  it is reported as such — not as zero received.
* **Unrecorded is not empty either.** The publish bookkeeping began on
  2026-09-07. A run published before that has a report GUID and no rows,
  and reading "no rows" as "nothing of this type" would have called 105 of
  130 published runs clean-and-empty on the day this was written. Absence
  means something only when the report has rows at all.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from resource_explorer.registry import ProjectRegistry

# Verdicts, in the order a reader should worry about them.
RECEIVED = "received"                    # published under this run's report
NOTHING_OF_THIS_TYPE = "nothing-of-this-type"   # steps ran clean, type absent — an answer
STEP_DID_NOT_FINISH = "step-did-not-finish"     # a declaring step failed — a defect
STEP_NOT_IN_RUN = "step-not-in-run"      # definition declares it, run never reached that step
NOT_PUBLISHED = "not-published"          # no report GUID: cannot be listed from here
NOT_RECORDED = "not-recorded"            # published, but before bookkeeping existed


@dataclass
class TypeVerdict:
    annotation_type: str
    declared_by: list[str]               # step keys that declare this type
    step_statuses: dict[str, str]        # step key -> status as the run recorded it
    verdict: str
    received: bool | None                # None when the run is unpublished

    def to_dict(self) -> dict:
        return {
            "annotation_type": self.annotation_type,
            "declared_by": self.declared_by,
            "step_statuses": self.step_statuses,
            "verdict": self.verdict,
            "received": self.received,
        }


@dataclass
class Reconciliation:
    run_id: str
    definition: str                      # bare document name, e.g. RepoAnalysisSurvey
    definition_ref: str                  # what the run recorded
    egeria_report_guid: str
    published: bool
    recorded: bool                       # bookkeeping holds rows for this report
    steps: list[dict] = field(default_factory=list)
    types: list[TypeVerdict] = field(default_factory=list)
    unresolved_steps: list[str] = field(default_factory=list)   # run steps with no declaration

    def to_dict(self) -> dict:
        counts: dict[str, int] = {}
        for t in self.types:
            counts[t.verdict] = counts.get(t.verdict, 0) + 1
        return {
            "run_id": self.run_id,
            "definition": self.definition,
            "definition_ref": self.definition_ref,
            "egeria_report_guid": self.egeria_report_guid,
            "published": self.published,
            "recorded": self.recorded,
            "steps": self.steps,
            "types": [t.to_dict() for t in self.types],
            "unresolved_steps": self.unresolved_steps,
            "summary": {
                "declared": len(self.types),
                **counts,
            },
        }


def step_key_of(qualified_name: str) -> str:
    """`GovActionProcessStep::RepoAnalysisSurvey::repo_git_statistics` ->
    `repo_git_statistics`. The last segment is the RE step key; the prefix is
    Egeria's. Verified against real activity rows, not assumed."""
    return str(qualified_name or "").split("::")[-1]


def definition_name_of(ref: str) -> str:
    """`GovActionProcess::RepoAnalysisSurvey` -> `RepoAnalysisSurvey`."""
    return str(ref or "").split("::")[-1]


def _declared_types_by_step(definition_name: str) -> dict[str, list[str]]:
    """Step key -> declared annotation types, from the authored document and
    the adapter's step info. A step with no entry declares nothing, which is
    recorded as an empty list rather than skipped, so the run's step list and
    the declaration can be compared step for step."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import _RE_ANALYSIS_STEP_INFO
    from resource_explorer.surveyors.survey_definition_docs import documented_definitions

    doc = documented_definitions().get(definition_name)
    if doc is None:
        return {}
    out: dict[str, list[str]] = {}
    for key in doc.steps:
        info = _RE_ANALYSIS_STEP_INFO.get(key) or {}
        out[key] = list(info.get("annotation_types") or [])
    return out


def reconcile_run(entry: dict, registry: ProjectRegistry | None = None) -> Reconciliation | None:
    """One activity row -> its declared-vs-received. None if the row is not a
    survey run with a step list (nothing to reconcile against)."""
    detail = entry.get("detail")
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except ValueError:
            detail = {}
    detail = detail or {}
    run_steps = detail.get("steps") or []
    ref = detail.get("survey_definition_ref") or ""
    if not run_steps or not ref:
        return None

    registry = registry or ProjectRegistry()
    slug = entry.get("entity_slug") or ""
    report_guid = str(detail.get("egeria_report_guid") or "")
    published = bool(report_guid)
    definition = definition_name_of(ref)
    declared = _declared_types_by_step(definition)

    status_by_key: dict[str, str] = {}
    steps_out: list[dict] = []
    unresolved: list[str] = []
    for s in run_steps:
        key = step_key_of(s.get("step"))
        status = str(s.get("status") or "")
        status_by_key[key] = status
        steps_out.append({
            "step": key,
            "status": status,
            "declared": declared.get(key, []),
            "detail": s.get("detail"),
        })
        if key not in declared:
            unresolved.append(key)

    received: set[str] = registry.get_published_annotation_types_for_report(slug, report_guid) if published else set()
    # Published, but nothing recorded under this report at all: the
    # bookkeeping did not exist yet. Absence is meaningless here.
    recorded = published and bool(received)

    # Types, each traced back to the steps that declare it.
    by_type: dict[str, list[str]] = {}
    for key, types in declared.items():
        for t in types:
            by_type.setdefault(t, []).append(key)

    verdicts: list[TypeVerdict] = []
    for t, keys in by_type.items():
        statuses = {k: status_by_key.get(k, "") for k in keys}
        # The run record first, the bookkeeping second. A step that never ran
        # or did not finish is a defect whether or not anything was recorded
        # afterwards; only the received / nothing-of-this-type distinction
        # needs the bookkeeping, and only the bookkeeping can make it.
        got: bool | None
        if published and t in received:
            v = RECEIVED
            got = True
        elif all(k not in status_by_key for k in keys):
            v = STEP_NOT_IN_RUN
            got = False
        elif any(status_by_key.get(k) and status_by_key.get(k) != "ok" for k in keys):
            v = STEP_DID_NOT_FINISH
            got = False
        elif not published:
            v = NOT_PUBLISHED
            got = None
        elif not recorded:
            v = NOT_RECORDED
            got = None
        else:
            v = NOTHING_OF_THIS_TYPE
            got = False
        verdicts.append(TypeVerdict(t, keys, statuses, v, got))

    # Received but never declared — the other direction of the same diff.
    # An analysis added later, whose types nothing in the definition names.
    for t in sorted(received - set(by_type)):
        verdicts.append(TypeVerdict(t, [], {}, RECEIVED, True))

    order = {RECEIVED: 3, NOTHING_OF_THIS_TYPE: 1, STEP_DID_NOT_FINISH: 0, STEP_NOT_IN_RUN: 2, NOT_PUBLISHED: 4, NOT_RECORDED: 5}
    verdicts.sort(key=lambda x: (order.get(x.verdict, 9), x.annotation_type))

    return Reconciliation(
        run_id=str(entry.get("id") or ""),
        definition=definition,
        definition_ref=ref,
        egeria_report_guid=report_guid,
        published=published,
        recorded=recorded,
        steps=steps_out,
        types=verdicts,
        unresolved_steps=unresolved,
    )
