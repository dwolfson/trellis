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
    confidence: int = 100                   # 0–100
    expression: str = ""                    # relationship detail to the asset
    explanation: str = ""
    json_properties: dict[str, Any] = field(default_factory=dict)
    additional_properties: dict[str, Any] = field(default_factory=dict)
    source: str = "local"                   # 'local' | 'egeria' | 'pending'


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
    project_slug: str
    project_display_name: str
    github_url: str
    surveyed_at: datetime = field(default_factory=datetime.utcnow)
    annotations: list[Annotation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)   # non-fatal issues during survey
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
