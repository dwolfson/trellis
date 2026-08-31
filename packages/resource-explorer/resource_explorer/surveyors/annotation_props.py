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

2026-08-29: the CREATE loop itself (`_create_annotations`) was extracted the
same way, as `publish_annotations` below, for the same reason — three
near-identical copies, one of which had already drifted once. That loop also
gained an idempotency guard (design doc `outbox-publishing-design.md` D2):
before creating an annotation, look up its qualifiedName in Egeria and adopt
the existing GUID rather than creating a duplicate. Previously
`DataDiscovery.create_annotation` was called blind, so replaying a publish
(e.g. after a crash between Egeria recording the write and the caller
recording success) created a second annotation with the same qualifiedName.
The qualifiedName format/timestamp is unchanged — see the module docstring on
each caller's `_create_annotations` wrapper for why the run timestamp in it is
correct and must not be removed.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from resource_explorer.surveyors.survey_report import AnnotationType

log = logging.getLogger(__name__)


def to_string_map(d: dict) -> dict[str, str]:
    """Convert a dict to map<string, string> as required by Egeria typed map fields.

    Nested dicts/lists are JSON-serialised to a string value so no nested
    structures escape into the wire format.  All scalar values are str()-coerced.
    """
    result: dict[str, str] = {}
    for k, v in d.items():
        result[str(k)] = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
    return result


def _annotation_type_name(ann, atype) -> str:
    """What Egeria's `annotationType` should say: WHICH result this is.

    It named the entity subtype until 2026-08-26 — "ClassificationAnnotation",
    duplicating the `class` field beside it. 14 repo analyses share that
    subtype, so the field distinguished nothing, and the names RE actually
    holds (chaoss_metrics, supply_chain, cve_scan) never reached the catalog.
    That is why publish attribution needed a local side-table: the question
    "which analysis produced this?" was unanswerable from Egeria.

    Order of preference:

    1. an explicit `annotation_type_name` on the annotation — for a step that
       emits more than one kind of result and wants to say which is which;
    2. the name derived from `analysis_step` via the step registry;
    3. the entity subtype name, as before.

    Three is wrong, and kept deliberately: database and filesystem surveyors
    are not in the repo step registry, so falling back preserves exactly their
    current behaviour rather than inventing a name for them. Wrong-as-before
    beats newly-fabricated.
    """
    explicit = (getattr(ann, "annotation_type_name", "") or "").strip()
    if explicit:
        return explicit
    try:
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            resolve_annotation_type,
        )
    except ImportError as exc:  # pragma: no cover - import guard
        log.warning("annotation type registry unavailable (%s) — annotations will "
                    "name their entity subtype instead of their result", exc)
        return atype.value
    return resolve_annotation_type(getattr(ann, "analysis_step", "")) or atype.value


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
        "annotationType": _annotation_type_name(ann, atype),
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


def build_annotation_body(ann, qualified_name: str, report_guid: str) -> dict:
    """The exact body `DataDiscovery.create_annotation` expects.

    Extracted so the two paths that create an annotation — publishing it
    directly (`publish_annotations` below) and enqueueing it for the outbox
    (`egeria_outbox.enqueue_annotations`) — build the identical payload. If
    they diverged, a retried annotation would differ from the one the direct
    path would have written, which is exactly the class of drift the outbox
    exists to remove rather than introduce.
    """
    return {
        "class": "NewElementRequestBody",
        "parentGUID": report_guid,
        "parentRelationshipTypeName": "ReportedAnnotation",
        "properties": build_annotation_props(ann, qualified_name),
    }


def publish_annotations(
    discovery,
    find_element_guid,
    annotations: list,
    report_guid: str,
    qualified_name_prefix: str,
) -> None:
    """Create one Annotation element per item in `annotations`, idempotently.

    The shared CREATE loop for EgeriaPublisher (repo), EgeriaDatabaseSurveyor
    and EgeriaFileSystemSurveyor — previously three near-identical copies, all
    of which called `DataDiscovery.create_annotation` blind, with no check for
    an existing element of the same qualifiedName. Replaying a publish (e.g.
    after a crash between Egeria recording the write and the caller recording
    success) therefore created a duplicate annotation.

    `find_element_guid` is injected rather than this module calling
    `AutomatedCuration.get_guid_for_name` itself: all three callers already
    have a connected `_find_element_guid(name) -> str` method that does
    exactly this lookup for the identical purpose on sub-resources
    (`EgeriaPublisher.publish_sub_resources`, D8) and on ExternalReferences
    (`_publish_homepage_reference`) — reusing it means one fewer live call
    path to test and maintain, and it already returns "" (never raises) when
    nothing matches or the lookup itself fails.
    `DataDiscovery.find_annotations(search_string=qn, starts_with=False)`
    would also work, but it is a second, narrower search purely for
    Annotation-typed elements where the existing generic-name lookup is
    already proven correct here and cheap (unscoped, but qualifiedName
    embeds project slug + run timestamp + index, so a same-name collision
    with something else is not a realistic risk) — see get_guid_for_name's
    own docstring: it raises only when *more than one* element matches.

    qualified_name_prefix is everything before the trailing "::{i}" — the
    caller owns that format (and its run timestamp) entirely; this function
    only appends the per-annotation index.

    Error handling unchanged from the three pre-existing copies: a failure
    creating one annotation is logged and the loop continues rather than
    aborting the run.
    """
    for i, ann in enumerate(annotations):
        qualified_name = f"{qualified_name_prefix}::{i}"

        try:
            existing_guid = find_element_guid(qualified_name)
        except Exception as exc:  # defensive — real _find_element_guid never raises
            log.debug("Annotation lookup failed for %s (will attempt create): %s",
                      qualified_name, exc)
            existing_guid = ""
        if existing_guid:
            log.debug("Annotation %s already exists (GUID %s) — not re-creating",
                      qualified_name, existing_guid)
            continue

        body = build_annotation_body(ann, qualified_name, report_guid)
        try:
            discovery.create_annotation(body=body)
        except Exception as exc:
            log.warning(
                "Failed to create annotation %d (%s): %s",
                i, ann.annotation_type.value, exc,
            )
