"""Declared versus received: one run held against its own declaration.

Every verdict is exercised with a fake registry, so nothing here reads the
live database. The distinctions under test are the ones that were invisible
before this existed: "ran and found nothing" versus "the step did not finish",
and both of those versus "cannot be known from here".
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.run_reconciliation import (
    NOT_PUBLISHED, NOT_RECORDED, NOTHING_OF_THIS_TYPE, RECEIVED,
    STEP_DID_NOT_FINISH, STEP_NOT_IN_RUN, definition_name_of, reconcile_run,
    step_key_of,
)


class FakeRegistry:
    def __init__(self, published: dict[str, set[str]] | None = None):
        self.published = published or {}

    def get_published_annotation_types_for_report(self, slug, report_guid):
        return set(self.published.get(report_guid, set()))


@pytest.fixture(autouse=True)
def stub_declarations(monkeypatch):
    """A two-step definition: A declares X and Y, B declares Y and Z."""
    class Doc:
        steps = ["step_a", "step_b"]

    monkeypatch.setattr(
        "resource_explorer.surveyors.survey_definition_docs.documented_definitions",
        lambda: {"TestSurvey": Doc()},
    )
    monkeypatch.setattr(
        "resource_explorer.surveyors.repo_survey_definition_adapter._RE_ANALYSIS_STEP_INFO",
        {
            "step_a": {"annotation_types": ["X", "Y"]},
            "step_b": {"annotation_types": ["Y", "Z"]},
        },
    )


def run(steps, report_guid="rep-1", ref="GovActionProcess::TestSurvey"):
    return {
        "id": "run-1", "entity_slug": "repo-1",
        "detail": json.dumps({
            "survey_definition_ref": ref,
            "egeria_report_guid": report_guid,
            "steps": [{"step": f"GovActionProcessStep::TestSurvey::{k}", "status": s} for k, s in steps],
        }),
    }


def verdicts(rec):
    return {t.annotation_type: t.verdict for t in rec.types}


class TestKeys:
    def test_step_key_is_the_last_segment(self):
        assert step_key_of("GovActionProcessStep::RepoAnalysisSurvey::repo_git_statistics") == "repo_git_statistics"

    def test_definition_name_is_the_last_segment(self):
        assert definition_name_of("GovActionProcess::RepoAnalysisSurvey") == "RepoAnalysisSurvey"


class TestVerdicts:
    def test_all_received(self):
        rec = reconcile_run(run([("step_a", "ok"), ("step_b", "ok")]),
                            FakeRegistry({"rep-1": {"X", "Y", "Z"}}))
        assert verdicts(rec) == {"X": RECEIVED, "Y": RECEIVED, "Z": RECEIVED}
        assert rec.published and rec.recorded

    def test_ran_clean_and_produced_nothing_is_an_answer(self):
        """Steps ok, bookkeeping has rows for this report, Z absent: Z was
        genuinely not produced. Distinct from the defect below."""
        rec = reconcile_run(run([("step_a", "ok"), ("step_b", "ok")]),
                            FakeRegistry({"rep-1": {"X", "Y"}}))
        assert verdicts(rec)["Z"] == NOTHING_OF_THIS_TYPE
        assert [t for t in rec.types if t.annotation_type == "Z"][0].received is False

    def test_a_failed_step_is_a_defect_not_an_absence(self):
        rec = reconcile_run(run([("step_a", "ok"), ("step_b", "error")]),
                            FakeRegistry({"rep-1": {"X", "Y"}}))
        v = verdicts(rec)
        assert v["Z"] == STEP_DID_NOT_FINISH
        # Y is declared by both steps and WAS received — received wins over
        # the failed step, because the type did arrive.
        assert v["Y"] == RECEIVED

    def test_a_step_the_run_never_reached(self):
        rec = reconcile_run(run([("step_a", "ok")]), FakeRegistry({"rep-1": {"X", "Y"}}))
        assert verdicts(rec)["Z"] == STEP_NOT_IN_RUN

    def test_unpublished_is_unknown_not_zero(self):
        rec = reconcile_run(run([("step_a", "ok"), ("step_b", "ok")], report_guid=""),
                            FakeRegistry())
        assert not rec.published
        assert set(verdicts(rec).values()) == {NOT_PUBLISHED}
        assert all(t.received is None for t in rec.types)

    def test_published_before_bookkeeping_is_unknown_not_zero(self):
        """The one that would have called 105 of 130 real runs clean-and-
        empty: a report GUID with no rows under it. Absence means nothing."""
        rec = reconcile_run(run([("step_a", "ok"), ("step_b", "ok")]), FakeRegistry({}))
        assert rec.published and not rec.recorded
        assert set(verdicts(rec).values()) == {NOT_RECORDED}
        assert all(t.received is None for t in rec.types)

    def test_a_defect_is_reported_even_when_bookkeeping_is_missing(self):
        """The run record is consulted before the bookkeeping. A failed step
        is a defect whether or not anything was recorded afterwards."""
        rec = reconcile_run(run([("step_a", "error"), ("step_b", "ok")]), FakeRegistry({}))
        v = verdicts(rec)
        assert v["X"] == STEP_DID_NOT_FINISH
        assert v["Z"] == NOT_RECORDED

    def test_received_but_never_declared_is_listed_too(self):
        """The other direction of the diff: an analysis added later whose
        type nothing in the definition names."""
        rec = reconcile_run(run([("step_a", "ok"), ("step_b", "ok")]),
                            FakeRegistry({"rep-1": {"X", "Y", "Z", "W"}}))
        w = [t for t in rec.types if t.annotation_type == "W"][0]
        assert w.verdict == RECEIVED and w.declared_by == []

    def test_worst_first_ordering(self):
        rec = reconcile_run(run([("step_a", "ok"), ("step_b", "error")]),
                            FakeRegistry({"rep-1": {"X"}}))
        assert rec.types[0].verdict == STEP_DID_NOT_FINISH

    def test_summary_counts_by_verdict(self):
        rec = reconcile_run(run([("step_a", "ok"), ("step_b", "error")]),
                            FakeRegistry({"rep-1": {"X"}}))
        s = rec.to_dict()["summary"]
        assert s["declared"] == 3
        assert s[RECEIVED] == 1


class TestNotARun:
    def test_no_step_list_means_nothing_to_reconcile(self):
        assert reconcile_run({"id": "x", "detail": json.dumps({"survey_definition_ref": "r"})}, FakeRegistry()) is None

    def test_no_definition_ref_means_nothing_to_reconcile(self):
        assert reconcile_run({"id": "x", "detail": json.dumps({"steps": [{"step": "s", "status": "ok"}]})}, FakeRegistry()) is None

    def test_unknown_definition_declares_nothing(self):
        rec = reconcile_run(run([("step_a", "ok")], ref="GovActionProcess::NoSuchSurvey"), FakeRegistry({"rep-1": {"X"}}))
        assert rec.unresolved_steps == ["step_a"]
        # X arrived but nothing declared it: listed as received-undeclared
        assert verdicts(rec) == {"X": RECEIVED}
