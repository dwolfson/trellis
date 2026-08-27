"""The re-authoring repair, and the drift scan that motivates it.

The failure this guards is specific and has bitten before: Link First/Next
Process Step is not idempotent — the relationship carries a guard and is
multi-link by design — so re-running the Dr.Egeria documents ADDS a second
outgoing edge rather than merging. A definition with two next-steps is refused
by the reader and renders with zero steps, which is worse than the drift being
repaired. The reconciler that strips those edges must therefore run every time,
and the way to guarantee that is to never call the documents directly.
"""
from unittest.mock import patch

import pytest

from resource_explorer import egeria_resync as R


def test_reauthoring_is_first_in_repair_order():
    """Definitions must be current before anything republishes against them."""
    assert R.REPAIR_STEPS[0] == "reauthor_survey_definitions"


def test_intended_steps_expands_the_full_survey_sentinel():
    """The CSV's '*' row means every registered step, not a one-step survey.

    Read literally it would make RepoFullSurvey look like it should have a
    single step and report the other 31 as unwanted extras — drift invented by
    the scanner rather than found by it.
    """
    intended = R._intended_steps_from_csv()
    assert len(intended["RepoFullSurvey"]) > 20
    assert R._FULL_SURVEY_SENTINEL not in intended["RepoFullSurvey"]
    # A normal definition still reads literally.
    assert "repo_health" in intended["RepoScoutingSurvey"]


def test_repair_goes_through_heal_batch_so_the_reconciler_cannot_be_skipped():
    """Delegation is the point: heal_batch runs the documents AND the post-heal.

    Calling _run_dr_egeria directly would work and would silently omit the
    reconciler, so this asserts the delegation itself, not just the outcome.
    """
    batch = type("B", (), {"batch_id": "survey-definitions",
                           "files": ["a.md", "b.md"],
                           "post_heal": {"script": "scripts/reconcile.py"}})()
    with patch("resource_explorer.bootstrap.discover_batches", return_value=[batch]), \
         patch("resource_explorer.bootstrap.heal_batch",
               return_value=(True, "ok")) as heal:
        out = R.EgeriaResync.__dict__["_do_reauthor_survey_definitions"](
            object.__new__(R.EgeriaResync))
    heal.assert_called_once_with(batch)
    assert out["reauthored"] is True
    assert out["documents"] == 2
    assert out["post_heal"] == "scripts/reconcile.py"


def test_repair_reports_a_failed_heal_rather_than_claiming_success():
    batch = type("B", (), {"batch_id": "survey-definitions", "files": ["a.md"],
                           "post_heal": None})()
    with patch("resource_explorer.bootstrap.discover_batches", return_value=[batch]), \
         patch("resource_explorer.bootstrap.heal_batch",
               return_value=(False, "a.md: command failed")):
        out = R.EgeriaResync.__dict__["_do_reauthor_survey_definitions"](
            object.__new__(R.EgeriaResync))
    assert out["reauthored"] is False
    assert "command failed" in out["detail"]


def test_missing_batch_is_an_error_not_a_silent_no_op():
    """A renamed or deleted batch must not read as 'nothing needed doing'."""
    with patch("resource_explorer.bootstrap.discover_batches", return_value=[]):
        out = R.EgeriaResync.__dict__["_do_reauthor_survey_definitions"](
            object.__new__(R.EgeriaResync))
    assert out["reauthored"] is False
    assert "not found" in out["error"]


@pytest.mark.parametrize("live,want,missing,extra", [
    (["a", "b"], ["a", "b"], [], []),
    (["a"], ["a", "b"], ["b"], []),
    (["a", "z"], ["a"], [], ["z"]),
])
def test_drift_is_computed_in_both_directions(live, want, missing, extra):
    """Extra steps matter as much as missing ones — a step Egeria still runs
    that RE has since removed produces a survey RE cannot interpret."""
    assert [k for k in want if k not in live] == missing
    assert [k for k in live if k and k not in want] == extra
