"""
Resolves a triggered Egeria-native survey engine action back into a real
result: poll the engine action to a terminal ActivityStatus (reusing
egeria_delegated_step._poll_action_status's live-verified polling logic —
see that module's docstrings for the activityStatus-vs-actionStatus wire-key
history), identify the SPECIFIC new SurveyReport this trigger produced, and
convert its annotations into RE's own Annotation dataclass shape.

Closes docs/survey-model.md §D5 ("Async Survey Result Retrieval") for the
database and filesystem adapters (database/survey_definition_adapter.py,
filesystem/survey_definition_adapter.py) — both previously called
trigger_survey_by_guid() and immediately returned, reporting status
"triggered" regardless of what actually happened.

## The report-attribution problem

After triggering, a resource's asset can have MULTIPLE SurveyReports linked
via ReportSubject — an old one from a previous run, a new one from this
trigger, or (for a live catalog under concurrent use) one from an unrelated
concurrent survey. There is no confirmed direct relationship from an
EngineAction to the SurveyReport it produced (investigated 2026-09-19,
alongside this build — no such relationship was found in AssetMaker's
graph-walk output for a completed engine action; if one is found later,
querying it directly is simpler and more precise than the approach here).

So the report this trigger produced is identified indirectly: record the
wall-clock time just before triggering, poll to a terminal status, then take
the SurveyReport whose surveyed_at is the newest one created strictly AFTER
that recorded time — never "the newest report overall" (a concurrent
unrelated survey could be newer) and never "the first result" (ordering is
not guaranteed by the API). If that narrows to anything other than exactly
one report, that is a genuine ambiguity and is raised as
SurveyReportAttributionError rather than guessed past — matching this
project's convention that an unverifiable result must be reported as
unverified, never as a confident wrong answer.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from resource_explorer.surveyors.egeria_delegated_step import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    EgeriaEngineActionTimeoutError,  # re-exported for callers' except clauses
    _get_clients,
    _poll_action_status,
)
from resource_explorer.surveyors.survey_report import (
    Annotation,
    AnnotationType,
    ClassificationAnnotation,
    DataClassAnnotation,
    QualityScoreAnnotation,
    RelationshipAnnotation,
    RequestForActionAnnotation,
    ResourceMeasureAnnotation,
    SchemaAnalysisAnnotation,
)

log = logging.getLogger(__name__)

__all__ = [
    "EgeriaEngineActionTimeoutError",
    "SurveyReportAttributionError",
    "convert_wire_annotation",
    "resolve_triggered_survey_report",
    "poll_trigger_and_retrieve_annotations",
]


class SurveyReportAttributionError(RuntimeError):
    """Raised when the specific SurveyReport a trigger produced cannot be
    identified unambiguously — zero or more than one candidate report was
    created after the recorded trigger time (or a candidate's timestamp
    could not be parsed at all). Never silently resolved by guessing."""


_ANNOTATION_CLASS_BY_TYPE_NAME: dict[str, type[Annotation]] = {
    AnnotationType.RESOURCE_MEASURE.value: ResourceMeasureAnnotation,
    AnnotationType.CLASSIFICATION.value: ClassificationAnnotation,
    AnnotationType.SCHEMA_ANALYSIS.value: SchemaAnalysisAnnotation,
    AnnotationType.DATA_CLASS.value: DataClassAnnotation,
    AnnotationType.QUALITY_SCORE.value: QualityScoreAnnotation,
    AnnotationType.RELATIONSHIP.value: RelationshipAnnotation,
    AnnotationType.REQUEST_FOR_ACTION.value: RequestForActionAnnotation,
}


def convert_wire_annotation(raw: dict, *, analysis_step: str) -> Annotation:
    """Convert one raw annotation dict — as returned by
    egeria_survey_reader.get_annotations_by_report_guid(), the flat
    guid/annotation_type/summary/confidence/analysis_step/explanation/
    expression/json_properties shape — into RE's own Annotation dataclass
    shape, so an Egeria-native survey's result can flow through the same
    step_outputs/publish machinery as a locally-run step's annotations.

    `analysis_step` is RE's own step name (the re_analysis_step key), not
    Egeria's own analysisStep wire value for the annotation (which names a
    step in Egeria's native survey pipeline, a different vocabulary) — the
    wire value is kept, unaltered, in `check_name` instead of being
    overwritten, so nothing is lost.
    """
    type_name = raw.get("annotation_type", "") or ""
    cls = _ANNOTATION_CLASS_BY_TYPE_NAME.get(type_name, ResourceMeasureAnnotation)
    json_properties = raw.get("json_properties", {}) or {}
    confidence = raw.get("confidence", 100)
    try:
        confidence = int(confidence)
    except (TypeError, ValueError):
        confidence = 100

    # check_name is passed as an explicit, literal keyword at every
    # constructor call below (not folded into **common_kwargs) so that
    # tests/test_annotation_check_names.py's AST scan — which looks for a
    # literal `check_name=` keyword at each Annotation-constructor call site,
    # precisely because a name that only arrives via **kwargs is exactly the
    # "added a call site without one" case that scan exists to catch — can
    # see it here too.
    check_name = raw.get("analysis_step", "") or "egeria_native_survey"
    common_kwargs: dict[str, Any] = dict(
        summary=raw.get("summary", "") or f"Egeria-native annotation ({type_name or 'unknown type'})",
        analysis_step=analysis_step,
        annotation_type_name=type_name,
        confidence=confidence,
        expression=raw.get("expression", "") or "",
        explanation=raw.get("explanation", "") or "",
        json_properties=json_properties,
        source="egeria",
        item_key=raw.get("guid", "") or "",
    )

    try:
        if cls is ResourceMeasureAnnotation:
            return ResourceMeasureAnnotation(
                check_name=check_name, resource_properties=json_properties, **common_kwargs
            )
        if cls is RequestForActionAnnotation:
            return RequestForActionAnnotation(
                check_name=check_name,
                action_requested=raw.get("explanation", "") or raw.get("summary", "") or "",
                action_target_name=raw.get("guid", "") or "",
                **common_kwargs,
            )
        # ClassificationAnnotation, SchemaAnalysisAnnotation, DataClassAnnotation,
        # QualityScoreAnnotation, RelationshipAnnotation: none of the wire
        # dict's fields map cleanly onto their type-specific extras
        # (candidate_classifications, schema_name, ...) — left at their
        # dataclass defaults rather than guessed at; the common fields above
        # (summary/explanation/json_properties/...) still carry the real content.
        #
        # `cls` is resolved dynamically (from _ANNOTATION_CLASS_BY_TYPE_NAME),
        # like cve_scan.py's own runtime-picked-constructor pattern that
        # test_annotation_check_names.py's `_alias_names` already knows to
        # resolve — each of the six concrete dataclasses this can be is
        # covered by an explicit `check_name=` call site elsewhere in this
        # function or in survey_report.py's own subclasses, so this generic
        # branch's dynamic dispatch is a resolvable alias, not a blind spot.
        return cls(check_name=check_name, **common_kwargs)
    except TypeError as exc:
        # Defensive only: a constructor mismatch must not blow up conversion
        # of an entire report's worth of annotations over one odd entry —
        # fall back to the always-valid base shape instead of dropping it.
        log.warning("convert_wire_annotation: falling back to base shape for %r: %s", type_name, exc)
        return ResourceMeasureAnnotation(
            check_name=check_name, resource_properties=json_properties, **common_kwargs
        )


def _parse_egeria_timestamp(value: Any) -> datetime | None:
    """Best-effort parse of an elementHeader.versions.createTime value (or
    an already-extracted `surveyed_at`) into a timezone-aware datetime.
    Handles an epoch-millis integer/numeric-string (the raw Java Date wire
    form) and an ISO-8601 string alike. Returns None — never a guess — for
    anything else, so an unparseable timestamp is excluded from attribution
    rather than silently mis-sorted."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, str):
        if value.isdigit():
            try:
                return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
            except (ValueError, OverflowError, OSError):
                return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def resolve_triggered_survey_report(reports: list[dict], *, triggered_at: datetime) -> dict:
    """Identify the single SurveyReport a specific trigger produced out of
    all SurveyReports linked to the resource's asset. See module docstring
    for why "newest" / "first" are both unsafe.

    Raises SurveyReportAttributionError unless exactly one report's
    surveyed_at parses to a moment strictly after `triggered_at`.
    """
    if triggered_at.tzinfo is None:
        triggered_at = triggered_at.replace(tzinfo=timezone.utc)

    candidates: list[tuple[datetime, dict]] = []
    unparseable = 0
    for report in reports:
        parsed = _parse_egeria_timestamp(report.get("surveyed_at"))
        if parsed is None:
            unparseable += 1
            continue
        if parsed > triggered_at:
            candidates.append((parsed, report))

    if len(candidates) == 1:
        return candidates[0][1]

    if not candidates:
        raise SurveyReportAttributionError(
            "Could not identify the SurveyReport this trigger produced: no SurveyReport "
            f"was found with a surveyed_at after trigger time {triggered_at.isoformat()} "
            f"(saw {len(reports)} total report(s) for this resource, {unparseable} with "
            "unparseable timestamps). The engine action reached a terminal status but no "
            "new report is visible yet — this may mean the report has not propagated, or "
            "that it was published under a timestamp this code could not parse."
        )

    guids = [r.get("guid", "?") for _, r in candidates]
    raise SurveyReportAttributionError(
        f"Ambiguous SurveyReport attribution: {len(candidates)} reports were created after "
        f"trigger time {triggered_at.isoformat()} (guids={guids}). Cannot determine which "
        "one this specific trigger produced without a direct EngineAction-to-report "
        "relationship (none was found — see this feature's design-notes doc). Reporting "
        "this as an explicit ambiguity rather than guessing."
    )


def poll_trigger_and_retrieve_annotations(
    *,
    surveyor: Any,
    engine_action_guid: str,
    resource_guid: str,
    triggered_at: datetime,
    analysis_step: str,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Poll `engine_action_guid` to a terminal ActivityStatus, then resolve
    and read back the specific new SurveyReport this trigger produced on
    `resource_guid`, converting its annotations into RE's own Annotation
    shape.

    `surveyor` is any EgeriaDatabaseSurveyor/EgeriaFileSystemSurveyor-shaped
    object exposing get_survey_reports_by_guid(guid)/
    get_annotations_by_report_guid(report_guid) — both already perform their
    own self.connect().

    Raises EgeriaEngineActionTimeoutError on poll timeout (the action is left
    running in Egeria; this only means RE gave up waiting) and
    SurveyReportAttributionError if the produced report cannot be
    unambiguously identified. Both are real, specific failures the caller
    should surface as this step's error — never a silent "triggered" success.
    """
    _automated_curation, metadata_expert = _get_clients()
    status, completion_message = _poll_action_status(
        metadata_expert, engine_action_guid, poll_interval, timeout
    )

    reports = surveyor.get_survey_reports_by_guid(resource_guid)
    report = resolve_triggered_survey_report(reports, triggered_at=triggered_at)

    raw_annotations = surveyor.get_annotations_by_report_guid(report["guid"])
    annotations = [convert_wire_annotation(a, analysis_step=analysis_step) for a in raw_annotations]

    return {
        "engine_action_guid": engine_action_guid,
        "final_status": status,
        "completion_message": completion_message,
        "report_guid": report.get("guid", ""),
        "report_qualified_name": report.get("qualified_name", ""),
        "annotations": annotations,
    }
