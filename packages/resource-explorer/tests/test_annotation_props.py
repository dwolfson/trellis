"""Tests for the shared annotation->Egeria properties mapping.

These exist because the filesystem publisher shipped a copy of this logic that
raised AttributeError on the first annotation of every run, and the suite could
not see it: tests/test_filesystem_survey_definition_adapter.py patches
`_create_annotations` out entirely, so the broken code never executed under
test. A mock sat exactly where the bug was.

The guard against a repeat is not "test the filesystem copy" — it is that there
is only one copy, and that every publisher is asserted to produce byte-identical
output from it. A future divergence fails here rather than in production.
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors.annotation_props import build_annotation_props, to_string_map
from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor
from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import EgeriaFileSystemSurveyor
from resource_explorer.surveyors.survey_report import (
    AnnotationType,
    ClassificationAnnotation,
    DataClassAnnotation,
    QualityScoreAnnotation,
    RelationshipAnnotation,
    RequestForActionAnnotation,
    ResourceMeasureAnnotation,
    SchemaAnalysisAnnotation,
)

PUBLISHERS = [EgeriaPublisher, EgeriaDatabaseSurveyor, EgeriaFileSystemSurveyor]

ALL_ANNOTATIONS = [
    ResourceMeasureAnnotation(summary="1234 files", analysis_step="a", resource_properties={"n": 1}),
    ClassificationAnnotation(summary="s", analysis_step="a", candidate_classifications=["python"]),
    QualityScoreAnnotation(summary="s", analysis_step="a"),
    DataClassAnnotation(summary="s", analysis_step="a"),
    RequestForActionAnnotation(summary="s", analysis_step="a"),
    SchemaAnalysisAnnotation(summary="s", analysis_step="a"),
    RelationshipAnnotation(summary="s", analysis_step="a",
                           related_entity_name="E", relationship_type_name="T"),
]


def _call(cls, ann, qn="QN::test"):
    """Invoke a publisher's method without constructing one (no Egeria needed)."""
    return cls._build_annotation_props(cls.__new__(cls), ann, qn)


class TestNoPublisherDrift:
    @pytest.mark.parametrize("ann", ALL_ANNOTATIONS, ids=lambda a: type(a).__name__)
    def test_every_publisher_produces_identical_props(self, ann):
        """The actual regression guard. Three copies of this logic drifted far
        enough that one emitted valueProperties/confidenceLevel where the others
        emitted resourceProperties/confidence, and dropped a whole annotation
        type — all while the suite stayed green."""
        outputs = [_call(cls, ann) for cls in PUBLISHERS]
        assert outputs[0] == outputs[1] == outputs[2], (
            f"{type(ann).__name__} diverges: "
            + " vs ".join(f"{c.__name__}={o}" for c, o in zip(PUBLISHERS, outputs))
        )

    @pytest.mark.parametrize("cls", PUBLISHERS, ids=lambda c: c.__name__)
    @pytest.mark.parametrize("ann", ALL_ANNOTATIONS, ids=lambda a: type(a).__name__)
    def test_no_publisher_raises_on_any_annotation_type(self, cls, ann):
        """Direct repro of the shipped bug: the filesystem copy read
        `ann.egeria_type_name`, which exists on no annotation class, so this call
        raised AttributeError for every type."""
        props = _call(cls, ann)
        assert props["qualifiedName"] == "QN::test"
        assert props["class"].endswith("Properties")


class TestSharedMapping:
    def test_every_annotation_type_has_a_dedicated_egeria_class(self):
        """A type missing from the class map silently degrades to the generic
        AnnotationProperties — which is how RELATIONSHIP was being dropped."""
        for ann in ALL_ANNOTATIONS:
            assert build_annotation_props(ann, "QN")["class"] != "AnnotationProperties", (
                f"{ann.annotation_type} falls through to the generic class"
            )

    def test_relationship_annotation_is_mapped(self):
        """Regression: the filesystem copy omitted RELATIONSHIP from both its
        dispatch and its class map, so relationship advice was unpublishable."""
        props = build_annotation_props(ALL_ANNOTATIONS[-1], "QN")
        assert props["class"] == "RelationshipAdviceAnnotationProperties"
        assert props["relatedEntityName"] == "E"
        assert props["relationshipTypeName"] == "T"

    def test_resource_measure_uses_resourceProperties_not_valueProperties(self):
        """The filesystem copy emitted `valueProperties`, which is not the field
        Egeria's ResourceMeasureAnnotation declares."""
        props = build_annotation_props(
            ResourceMeasureAnnotation(summary="s", analysis_step="a", resource_properties={"n": 1}), "QN")
        assert "resourceProperties" in props and "valueProperties" not in props

    def test_confidence_not_confidenceLevel(self):
        """Likewise `confidenceLevel` vs the declared `confidence`."""
        props = build_annotation_props(ALL_ANNOTATIONS[0], "QN")
        assert "confidence" in props and "confidenceLevel" not in props

    def test_annotation_type_is_always_emitted(self):
        for ann in ALL_ANNOTATIONS:
            assert build_annotation_props(ann, "QN")["annotationType"] == ann.annotation_type.value

    def test_empty_optional_fields_are_omitted_not_sent_blank(self):
        ann = ResourceMeasureAnnotation(summary="s", analysis_step="a")  # no explanation/expression
        props = build_annotation_props(ann, "QN")
        assert "explanation" not in props and "expression" not in props


class TestToStringMap:
    def test_nested_structures_are_json_encoded(self):
        """Egeria typed map fields are map<string,string>; nested structures must
        not escape into the wire format."""
        out = to_string_map({"scalar": 1, "nested": {"a": 2}, "list": [1, 2]})
        assert out == {"scalar": "1", "nested": '{"a": 2}', "list": "[1, 2]"}
        assert all(isinstance(v, str) for v in out.values())

    @pytest.mark.parametrize("cls", PUBLISHERS, ids=lambda c: c.__name__)
    def test_publishers_share_one_to_string_map(self, cls):
        assert cls._to_string_map({"a": {"b": 1}}) == to_string_map({"a": {"b": 1}})
