"""A check_name emitted by several analysis steps gets the step as item_key (trevor, 2026-09-04)."""
import pytest

from resource_explorer.surveyors.survey_report import (
    ClassificationAnnotation, annotation_qualified_name, assert_unique_qualified_names,
    disambiguate_shared_check_names,
)


def _ann(step, check="scan_summary", item_key=""):
    return ClassificationAnnotation(check_name=check, summary="s", analysis_step=step,
                                    candidate_classifications=["x"], confidence=100,
                                    explanation="e", json_properties={}, item_key=item_key)


def test_shared_check_name_gets_step_as_item_key():
    anns = [_ann("SecretScan"), _ann("ContributionProvenance"), _ann("SlaContent"), _ann("TelemetryScan")]
    assert disambiguate_shared_check_names(anns) == 4
    names = {annotation_qualified_name("P", i, a) for i, a in enumerate(anns)}
    assert len(names) == 4 and all(n.startswith("P::scan_summary::") for n in names)
    assert_unique_qualified_names("P", anns)  # must not raise


def test_single_step_check_name_is_not_renamed():
    anns = [_ann("SecretScan"), _ann("SecretScan", check="ruleset_freshness")]
    assert disambiguate_shared_check_names(anns) == 0
    assert annotation_qualified_name("P", 0, anns[0]) == "P::scan_summary"


def test_same_step_twice_still_raises():
    anns = [_ann("SecretScan"), _ann("SecretScan")]
    with pytest.raises(ValueError, match="same qualifiedName"):
        assert_unique_qualified_names("P", anns)


def test_existing_item_key_is_kept():
    anns = [_ann("SecretScan", item_key="gitleaks"), _ann("SlaContent")]
    disambiguate_shared_check_names(anns)
    assert anns[0].item_key == "gitleaks"
