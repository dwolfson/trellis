"""One place that maps an Annotation dataclass to an Egeria properties body.

Extracted 2026-08-19 from three near-identical private copies — EgeriaPublisher
(repo), EgeriaDatabaseSurveyor, EgeriaFileSystemSurveyor — after the filesystem
copy was found to be silently broken and materially drifted from the other two.

The drift was not cosmetic. The filesystem copy:
  * read `ann.egeria_type_name`, an attribute that exists on no class in
    survey_report.py and nowhere else in the package, so it raised
    AttributeError on the FIRST annotation of every run;
  * emitted `valueProperties` where the others emit `resourceProperties`, and
    `confidenceLevel` where the others emit `confidence`;
  * handled six of the seven AnnotationTypes, omitting RELATIONSHIP from both
    its dispatch and its class map.

Because the failing call sits outside `_create_annotations`' inner try (which
guards only the create_annotation request), the error escaped the whole loop
rather than costing one annotation. On the Survey-Definition path
(publish_step_annotations) nothing caught it and the run failed outright; on the
catalog_and_survey path a broad except logged "Failed to publish SurveyReport",
which was doubly misleading — the report had been created, and it was the
annotations that died. Net effect: no filesystem analysis ever reached Egeria.

The test suite could not have caught it: the filesystem adapter test patches
`_create_annotations` out entirely, so the broken code never ran under test.

Repo and database publishing were unaffected, and this module is their existing
behaviour verbatim, so extracting it is a no-op for them and a fix for
filesystems. The three callers keep their thin `_build_annotation_props`/
`_to_string_map` methods as delegating wrappers, since tests and subclasses
reach for them by name.
"""
from __future__ import annotations

import json
from typing import Any

from resource_explorer.surveyors.survey_report import AnnotationType


def to_string_map(d: dict) -> dict[str, str]:
    """Convert a dict to map<string, string> as required by Egeria typed map fields.

    Nested dicts/lists are JSON-serialised to a string value so no nested
    structures escape into the wire format.  All scalar values are str()-coerced.
    """
    result: dict[str, str] = {}
    for k, v in d.items():
        result[str(k)] = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
    return result


def build_annotation_props(ann, qualified_name: str) -> dict:
    """Map an Annotation dataclass to the correct Egeria subtype properties body."""
    """Map an Annotation dataclass to the correct Egeria subtype properties body."""
    atype = ann.annotation_type

    # Map our AnnotationType enum to the Egeria Jackson subtype class name.
    # Note: RequestForActionAnnotationProperties is NOT valid — use RequestForActionProperties.
    _class_map = {
        AnnotationType.RESOURCE_MEASURE:   "ResourceMeasureAnnotationProperties",
        AnnotationType.CLASSIFICATION:     "ClassificationAnnotationProperties",
        AnnotationType.QUALITY_SCORE:      "QualityAnnotationProperties",
        AnnotationType.DATA_CLASS:         "DataClassAnnotationProperties",
        AnnotationType.REQUEST_FOR_ACTION: "RequestForActionProperties",
        AnnotationType.SCHEMA_ANALYSIS:    "SchemaAnalysisAnnotationProperties",
        AnnotationType.RELATIONSHIP:       "RelationshipAdviceAnnotationProperties",
    }
    egeria_class = _class_map.get(atype, "AnnotationProperties")

    props: dict = {
        "class": egeria_class,
        "qualifiedName": qualified_name,
        "annotationType": atype.value,
        "summary": ann.summary,
        "analysisStep": ann.analysis_step,
        "confidence": ann.confidence,
    }
    if ann.explanation:
        props["explanation"] = ann.explanation
    if ann.expression:
        props["expression"] = ann.expression
    if ann.json_properties:
        props["jsonProperties"] = json.dumps(ann.json_properties)

    # Subtype-specific fields — native typed fields for registered subtypes;
    # additionalProperties (map<string,string>) for unregistered types.
    if atype == AnnotationType.RESOURCE_MEASURE:
        rp = getattr(ann, "resource_properties", {})
        if rp:
            props["resourceProperties"] = to_string_map(rp)

    elif atype == AnnotationType.CLASSIFICATION:
        cc = getattr(ann, "candidate_classifications", [])
        if cc:
            props["candidateClassifications"] = cc

    elif atype == AnnotationType.QUALITY_SCORE:
        qs = getattr(ann, "quality_scores", {})
        if qs:
            props["qualityScores"] = to_string_map(qs)

    elif atype == AnnotationType.DATA_CLASS:
        dc = getattr(ann, "candidate_data_class_names", [])
        if dc:
            props["candidateDataClassGUIDs"] = dc  # field name per Egeria type

    elif atype == AnnotationType.REQUEST_FOR_ACTION:
        action_req = getattr(ann, "action_requested", "")
        if action_req:
            props["actionRequested"] = action_req
        action_target = getattr(ann, "action_target_name", "")
        if action_target:
            props["actionProperties"] = {"actionTargetName": action_target}

    elif atype == AnnotationType.SCHEMA_ANALYSIS:
        sn = getattr(ann, "schema_name", "")
        st = getattr(ann, "schema_type", "")
        if sn:
            props["schemaName"] = sn
        if st:
            props["schemaType"] = st

    elif atype == AnnotationType.RELATIONSHIP:
        ren = getattr(ann, "related_entity_name", "")
        rtn = getattr(ann, "relationship_type_name", "")
        if ren:
            props["relatedEntityName"] = ren
        if rtn:
            props["relationshipTypeName"] = rtn

    return props
