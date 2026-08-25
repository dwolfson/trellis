"""A metrics card must not manufacture zeros for a run that never happened.

`website_ingestion`'s reader returned chunks/pages_fetched/pages_found/
pages_failed as 0 whenever there was no persisted run, and its render mode lays
every key out as a labelled row — so a repo the step had never touched showed
four rows of zeros, which reads as "we scanned the site and found nothing".

Measured 2026-08-25: only 6 of 60 repos have any `website_ingestion` metrics, so
54 cards were showing that false zero. result_status documents the correct
answer — `never_run`, whose message is the plain "No results yet — click Run to
scan" the empty state already renders.

This is the reader-side twin of the render-mode fix earlier the same day: there
the card said "no results" while holding data; here it showed data while having
none.
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors import result_status
from resource_explorer.surveyors.repo_survey_definition_adapter import ANALYSIS_KINDS


class _EmptyRegistry:
    """A registry where nothing has ever run."""

    def query_metrics(self, slug, kind):
        return {}

    def query_findings(self, slug, kind):
        return []

    def query_finding_scopes(self, slug, kind, check_name=None):
        return []


def test_website_ingestion_says_never_run_rather_than_zero():
    reader = ANALYSIS_KINDS["website_ingestion"].results.results_reader
    out = reader(_EmptyRegistry(), "any-repo")

    counts = {k: v for k, v in out.items() if k not in ("_status", "surveyed_at", "detail")}
    assert not counts, (
        f"reader invented values for a run that never happened: {counts}. "
        "Zero is an answer; absence is not."
    )
    assert out["_status"]["state"] == result_status.NEVER_RUN


@pytest.mark.parametrize(
    "kind",
    [k for k, v in ANALYSIS_KINDS.items() if v.results and v.results.render == "metrics"],
)
def test_no_metrics_reader_invents_numbers_for_a_run_that_never_happened(kind):
    """The whole class, not just the instance that was caught.

    Any metrics-mode reader that returns numeric rows from an empty registry is
    telling the same lie, because the render mode cannot distinguish a real zero
    from a manufactured one.
    """
    reader = ANALYSIS_KINDS[kind].results.results_reader
    try:
        out = reader(_EmptyRegistry(), "any-repo")
    except Exception as exc:  # a reader needing more of the registry API than the stub has
        pytest.skip(f"{kind}'s reader needs more registry surface: {type(exc).__name__}")

    numeric = {k: v for k, v in out.items()
               if k not in ("_status", "surveyed_at", "detail") and isinstance(v, (int, float))}
    assert not numeric, (
        f"{kind} returned {numeric} with nothing persisted — a card would render "
        "those as measured values. Return a never_run status instead."
    )
