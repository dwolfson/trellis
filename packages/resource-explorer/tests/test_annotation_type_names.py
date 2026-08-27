"""Egeria's `annotationType` should name WHICH result an annotation is.

It named the entity subtype until 2026-08-26 — "ClassificationAnnotation" —
duplicating the `class` field written beside it. 14 repo analyses share that
subtype, so the field distinguished nothing, and the names RE actually holds
(chaoss_metrics, supply_chain, cve_scan) never reached the catalog at all.

That is why publish attribution needed a local side-table: "which analysis
produced this?" was unanswerable from Egeria, so `project_published_analyses`
was built instead (commit e915b1c, the same day).
"""
import pytest

from resource_explorer.surveyors import repo_survey_definition_adapter as A
from resource_explorer.surveyors.annotation_props import build_annotation_props
from resource_explorer.surveyors.survey_report import (
    ClassificationAnnotation,
    QualityScoreAnnotation,
)


def _props(**kw):
    ann = ClassificationAnnotation(
        summary="s", analysis_step=kw.pop("analysis_step", "ChaossMetrics"),
        candidate_classifications=[], confidence=50, **kw)
    return build_annotation_props(ann, "QN::1")


# ── the resolver ────────────────────────────────────────────────────────────
def test_every_registered_step_resolves_to_a_name():
    """Exhaustive on purpose. A step whose convention this file does not know
    about goes unmapped and silently falls back to the subtype name — the exact
    defect being removed, reintroduced one step at a time."""
    unmapped = [key for key, info in A.STEP_REGISTRY.items()
                if not A._step_constant(info.surveyor_cls)]
    assert unmapped == [], f"steps with no readable STEP constant: {unmapped}"
    assert len(A.annotation_type_names()) == len(A.STEP_REGISTRY)


def test_names_are_analysis_ids_where_an_analysis_exists():
    names = A.annotation_type_names()
    assert names["ChaossMetrics"] == "chaoss_metrics"
    assert names["CveScan"] == "cve_scan"
    # Not derivable by any snake_case rule — which is why the map is derived
    # from the registry rather than computed from the string.
    assert names["CiQualityCheck"] == "ci_quality"
    assert names["ApiStructureAnalysis"] == "api_structure"


def test_steps_sharing_an_analysis_share_its_name():
    names = A.annotation_type_names()
    assert names["ArchitectureDetect"] == names["ArchitectureCoupling"] == \
        "architecture_recovery"


def test_a_prerequisite_step_is_named_by_its_own_key():
    """The four refresh steps have no analysis by design — they belong to a
    survey type, not an analysis — so their key is the most specific true name
    they have. Better than falling back to the subtype."""
    names = A.annotation_type_names()
    assert names["FileInventory"] == "repo_file_inventory"
    assert names["GitStatistics"] == "repo_git_statistics"


def test_an_unknown_step_resolves_to_nothing_rather_than_a_guess():
    assert A.resolve_annotation_type("NoSuchStep") == ""
    assert A.resolve_annotation_type("") == ""


# ── the published body ──────────────────────────────────────────────────────
def test_annotation_type_no_longer_duplicates_the_class_field():
    """The whole defect in one assertion."""
    props = _props()
    assert props["annotationType"] == "chaoss_metrics"
    assert props["class"] == "ClassificationAnnotationProperties"
    assert props["annotationType"] not in props["class"]


def test_analysis_step_is_still_written_and_is_a_different_thing():
    """Egeria models both: analysisStep is WHICH step ran, annotationType is
    WHICH result it is. Collapsing them would lose one."""
    props = _props()
    assert props["analysisStep"] == "ChaossMetrics"
    assert props["annotationType"] == "chaoss_metrics"


def test_an_explicit_name_wins_over_the_derived_one():
    """For a step emitting several distinguishable results, where the derived
    per-step name would blur them together."""
    props = _props(annotation_type_name="chaoss_elephant_factor")
    assert props["annotationType"] == "chaoss_elephant_factor"


def test_an_unregistered_step_keeps_the_previous_behaviour():
    """Database and filesystem surveyors are not in the repo step registry.
    Falling back preserves exactly what they wrote before rather than
    inventing a name — wrong-as-before beats newly-fabricated."""
    props = _props(analysis_step="SomeDatabaseStep")
    assert props["annotationType"] == "ClassificationAnnotation"


def test_the_fallback_is_not_reached_for_any_repo_step():
    """Every repo step must take the derived path, or the defect survives for
    that step alone and nobody notices."""
    for constant, expected in A.annotation_type_names().items():
        ann = QualityScoreAnnotation(
            summary="s", analysis_step=constant, quality_scores={}, confidence=1)
        assert build_annotation_props(ann, "QN::x")["annotationType"] == expected


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_blank_explicit_name_falls_through_to_the_derived_one(blank):
    ann = ClassificationAnnotation(
        summary="s", analysis_step="ChaossMetrics", candidate_classifications=[],
        confidence=1)
    ann.annotation_type_name = blank
    assert build_annotation_props(ann, "QN::1")["annotationType"] == "chaoss_metrics"
