"""
Egeria-aligned survey result dataclasses.

All types are plain Python — no pyegeria dependency here.
EgeriaPublisher (egeria_publisher.py) converts these to API calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AnnotationType(str, Enum):
    RESOURCE_MEASURE = "ResourceMeasureAnnotation"
    CLASSIFICATION = "ClassificationAnnotation"
    SCHEMA_ANALYSIS = "SchemaAnalysis"
    DATA_CLASS = "DataClassAnnotation"
    QUALITY_SCORE = "QualityScoreAnnotation"
    RELATIONSHIP = "RelationshipAnnotation"
    REQUEST_FOR_ACTION = "RequestForAction"


@dataclass
class Annotation:
    """Base annotation — mirrors Egeria Area 6 base Annotation entity."""
    annotation_type: AnnotationType
    summary: str
    analysis_step: str
    #: Optional override for Egeria's `annotationType` — the NAME of the result,
    #: not its shape. Left empty, it is derived from analysis_step via the step
    #: registry. Set it only where one step emits several distinguishable kinds
    #: of result and the derived, per-step name would blur them together.
    annotation_type_name: str = ""
    confidence: int = 100                   # 0–100
    expression: str = ""                    # relationship detail to the asset
    explanation: str = ""
    json_properties: dict[str, Any] = field(default_factory=dict)
    additional_properties: dict[str, Any] = field(default_factory=dict)
    source: str = "local"                   # 'local' | 'egeria' | 'pending'
    #: Index, within this same run()'s returned annotations list, of the
    #: annotation this one is evidence *for* — e.g. a per-file
    #: SchemaAnalysisAnnotation's evidence_of points at the index of its
    #: sub-surveyor's aggregate ResourceMeasureAnnotation. `None` (default)
    #: means "not evidence of anything in this run" — every existing
    #: annotation, unchanged. A same-run, list-index signal, not a GUID: the
    #: GUID does not exist until after publish, and append order is NOT safe
    #: to reconstruct blind, cross-run, after the fact (see
    #: docs/annotation-linking-plan.md Q3) — this field is safe only because
    #: the sub-surveyor sets it deliberately, about its own list, in the same
    #: run that produces it. Consumed by Phase 2 (not implemented yet); Phase 1
    #: only adds the field so sub-surveyors can start setting it.
    evidence_of: int | None = None


@dataclass
class ResourceMeasureAnnotation(Annotation):
    """File/size/language counts for a project or sub-scope."""
    annotation_type: AnnotationType = field(default=AnnotationType.RESOURCE_MEASURE, init=False)
    resource_properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClassificationAnnotation(Annotation):
    """Category or label assignments (language, project type, doc presence, etc.)."""
    annotation_type: AnnotationType = field(default=AnnotationType.CLASSIFICATION, init=False)
    candidate_classifications: list[str] = field(default_factory=list)


@dataclass
class SchemaAnalysisAnnotation(Annotation):
    """Module/API structure — public functions, classes, endpoints."""
    annotation_type: AnnotationType = field(default=AnnotationType.SCHEMA_ANALYSIS, init=False)
    schema_name: str = ""
    schema_type: str = ""


@dataclass
class DataClassAnnotation(Annotation):
    """Dependency classification — package name, version, ecosystem."""
    annotation_type: AnnotationType = field(default=AnnotationType.DATA_CLASS, init=False)
    candidate_data_class_names: list[str] = field(default_factory=list)


@dataclass
class QualityScoreAnnotation(Annotation):
    """Health and quality scores derived from GitHub stats."""
    annotation_type: AnnotationType = field(default=AnnotationType.QUALITY_SCORE, init=False)
    quality_scores: dict[str, float] = field(default_factory=dict)


@dataclass
class RelationshipAnnotation(Annotation):
    """Discovered relationship between two components."""
    annotation_type: AnnotationType = field(default=AnnotationType.RELATIONSHIP, init=False)
    related_entity_name: str = ""
    relationship_type_name: str = ""


@dataclass
class RequestForActionAnnotation(Annotation):
    """Flag for human review — missing artifact, security gap, stale dep, etc."""
    annotation_type: AnnotationType = field(default=AnnotationType.REQUEST_FOR_ACTION, init=False)
    action_requested: str = ""
    action_target_name: str = ""


@dataclass
class SurveyResult:
    """
    Complete output of one survey run against a project.

    Consumed by:
      - SurveyOrchestrator (assembles it from sub-surveyor outputs)
      - EgeriaPublisher    (converts to pyegeria API calls)
      - CLI survey command (renders as markdown without Egeria)
    """
    resource_slug: str
    project_display_name: str
    github_url: str
    surveyed_at: datetime = field(default_factory=datetime.utcnow)
    annotations: list[Annotation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)   # non-fatal issues during survey
    #: The re_analysis_step keys this run actually executed, set by
    #: SurveyOrchestrator, which is the one place that knows exactly.
    #:
    #: Recorded so a publish can say WHICH analyses it published rather than
    #: inferring it from annotation types afterwards. That inference held only
    #: while every type had a single producer, and stopped being true the
    #: moment a second analysis produced a QualityScoreAnnotation — after which
    #: no analysis could earn an attributable publish at all.
    steps_run: list[str] = field(default_factory=list)
    #: {step_key: reason} for steps a precondition declined to dispatch, kept
    #: SEPARATE from `steps_run` and from `step_errors` because a skip is neither.
    #: A skipped step did not run, so it is not in steps_run; it did not fail, so
    #: it is not an error. Folding it into either would recreate the ambiguity
    #: `result_status.SKIPPED_BY_DESIGN` exists to remove — and the reason travels
    #: with it, because a skip without one is indistinguishable from a failure on
    #: a screen. See surveyors/step_preconditions.py.
    skipped_steps: dict[str, str] = field(default_factory=dict)
    # Same failures as `errors`, keyed by the step that raised. Needed because a
    # single run can now carry steps belonging to several different scheduled
    # analyses (scheduler.py coalesces same-repo due schedules into one run so
    # the zipball downloads once), and each of those schedules records its own
    # pass/fail. Without per-step attribution the batch would have to mark every
    # analysis in it failed because one step raised, which turns one real
    # failure into several false ones. `errors` stays the flat list every
    # existing caller reads.
    step_errors: dict[str, str] = field(default_factory=dict)

    def add(self, annotation: Annotation) -> None:
        self.annotations.append(annotation)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def by_type(self, annotation_type: AnnotationType) -> list[Annotation]:
        return [a for a in self.annotations if a.annotation_type == annotation_type]


ANNOTATION_TYPES_REGISTRY = [
    {
        "type": "ResourceMeasureAnnotation",
        "display_name": "Resource Measure",
        "description": "Represents quantitative physical measurements of a resource (e.g. file count, size, language breakdown, row count, etc.).",
        "properties": ["resource_properties (dict)"],
        "egeria_type": "ResourceMeasureAnnotationProperties",
        "python_class": "ResourceMeasureAnnotation",
    },
    {
        "type": "ClassificationAnnotation",
        "display_name": "Classification",
        "description": "Represents categorization or labels assigned to a resource (e.g. language name, framework/technology detected, project type, file format, etc.).",
        "properties": ["candidate_classifications (list[str])"],
        "egeria_type": "ClassificationAnnotationProperties",
        "python_class": "ClassificationAnnotation",
    },
    {
        "type": "SchemaAnalysis",
        "display_name": "Schema Analysis",
        "description": "Represents structural metadata discovered within a resource (e.g. modules, API symbols, classes, functions, database schemas, tables, columns, etc.).",
        "properties": ["schema_name (str)", "schema_type (str)"],
        "egeria_type": "SchemaAnalysisAnnotationProperties",
        "python_class": "SchemaAnalysisAnnotation",
    },
    {
        "type": "DataClassAnnotation",
        "display_name": "Data Class",
        "description": "Represents classification of data patterns or formats (e.g. dependency package ecosystems, email addresses, credit cards, custom formats).",
        "properties": ["candidate_data_class_names (list[str])"],
        "egeria_type": "DataClassAnnotationProperties",
        "python_class": "DataClassAnnotation",
    },
    {
        "type": "QualityScoreAnnotation",
        "display_name": "Quality Score",
        "description": "Represents calculated health/quality scores or metrics for a resource (e.g. repository bus factor, documentation coverage, test coverage, code quality).",
        "properties": ["quality_scores (dict[str, float])"],
        "egeria_type": "QualityAnnotationProperties",
        "python_class": "QualityScoreAnnotation",
    },
    {
        "type": "RelationshipAnnotation",
        "display_name": "Relationship Advice",
        "description": "Represents discovered dependencies or links between different resources (e.g. database foreign key relationships, imports, API consumers).",
        "properties": ["related_entity_name (str)", "relationship_type_name (str)"],
        "egeria_type": "RelationshipAdviceAnnotationProperties",
        "python_class": "RelationshipAnnotation",
    },
    {
        "type": "RequestForAction",
        "display_name": "Request For Action",
        "description": "Represents a flagged issue requiring human attention or stewardship action (e.g. missing SECURITY.md, inaccessible folder, profiling error, stale dependency).",
        "properties": ["action_requested (str)", "action_target_name (str)"],
        "egeria_type": "RequestForActionProperties",
        "python_class": "RequestForActionAnnotation",
    }
]


_MAX_GROUP_ITEMS = 25


def summarise_annotations(annotations, limit: int = 20) -> list[dict]:
    """Group a run's annotations for the activity log, by (step, type).

    Extracted 2026-09-02 so there is ONE grouping rule rather than two. It
    lived inline in SurveyOrchestrator.run(); the Analyses-card path
    (projects.py::run_single_analysis) needed the same shape, and copying it
    is how the original defect would have been reintroduced in a second
    place.

    Keying on (step, annotation_type) rather than step alone: a sub-surveyor
    emitting several annotation kinds in one run — a passing
    ClassificationAnnotation beside a failing RequestForActionAnnotation —
    used to collapse into one dict where `summary` kept the FIRST seen and
    `annotation_type` kept overwriting to the LAST, so a passing check's
    words wore a RequestForAction label in the drawer.

    `explanation`/`action_requested`/`action_target_name` are taken from the
    SAME annotation that donated the summary, never a different member of the
    group — two independent first/last-wins fields on one group is precisely
    the shape that broke this once.
    """
    from collections import defaultdict

    by_step: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "summary": "", "explanation": "",
                 "action_requested": "", "action_target_name": "", "items": []})
    for a in annotations:
        # Skip anything that is not shaped like an annotation rather than
        # raising. This function builds a DISPLAY summary; letting it throw
        # took down the whole analysis run — the background thread crashed
        # and a survey whose findings were computed and stored reported
        # "crashed" to the user, because a summary of it could not be built.
        ann_type = getattr(a, "annotation_type", None)
        value = getattr(ann_type, "value", None)
        if not value:
            continue
        step = getattr(a, "analysis_step", None) or value
        group = by_step[(step, value)]
        group["count"] += 1
        # Every member kept, not just the first (2026-09-02).
        #
        # The group is a compact preview for the activity log, and that is
        # what it was built for. But GET /api/activity/rfas uses it as the
        # ACTIONABLE list, and a request for action that was summarised away
        # cannot be acted on. Measured on `workshops`: SecurityHygieneCheck
        # emits three RequestForActions — no SECURITY.md, no CI config, no
        # licence — which share a step and a type, so the group carried
        # count=3 and the text of the first. The drawer rendered
        # "SecurityHygieneCheck 3 / No SECURITY.md found", which is exactly
        # Dan's original report: "they all seem to be SecurityHygieneCheck 3
        # - there is little description". The other two were not hidden.
        # They were never written.
        #
        # Capped: a group is a preview, and an unbounded list here would put
        # a whole survey's annotations into every activity row.
        if len(group["items"]) < _MAX_GROUP_ITEMS:
            group["items"].append({
                "summary": (getattr(a, "summary", "") or "")[:200],
                "explanation": getattr(a, "explanation", "") or "",
                "action_requested": getattr(a, "action_requested", "") or "",
                "action_target_name": getattr(a, "action_target_name", "") or "",
            })
        if not group["summary"]:
            group["summary"] = (getattr(a, "summary", "") or "")[:200]
            group["explanation"] = getattr(a, "explanation", "") or ""
            group["action_requested"] = getattr(a, "action_requested", "") or ""
            group["action_target_name"] = getattr(a, "action_target_name", "") or ""
    return [
        {"analysis_name": step, "annotation_type": ann_type,
         "count": v["count"], "status": "local", "summary": v["summary"],
         "explanation": v["explanation"],
         "action_requested": v["action_requested"],
         "action_target_name": v["action_target_name"],
         "items": v["items"]}
        for (step, ann_type), v in list(by_step.items())[:limit]
    ]
