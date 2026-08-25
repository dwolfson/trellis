"""The documentation-site offer: four states, one of which is an offer.

A repo whose architecture sources are all unreadable sites has nothing to show
on the architecture card and a concrete, answerable thing to put in that space.
But only one of the four states is an offer, and getting that wrong is worse
than showing nothing:

  not-attempted  nobody has read the site   -> offer
  declined       refused ON PURPOSE         -> explain, never offer
  ingested       already read               -> say so
  attempted      read, nothing usable       -> a finding

`declined` is the one that matters. The ingestion step refuses when the site is
self-published — the repo builds it, so its source is already indexed in better
form — so offering there re-opens a decision the system made correctly. Measured
2026-08-25: 14 of 60 repos are `declined`, so a naive two-state rule would nag
about a quarter of the corpus.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import ProjectRegistry
from resource_explorer.surveyors.repo_survey_definition_adapter import (
    _architecture_recovery_results,
    _doc_ingestion_state,
)


class _Boom:
    """A registry whose metrics read explodes."""

    def query_metrics(self, *a, **kw):
        raise RuntimeError("metrics unavailable")


def test_an_unreadable_status_is_not_rendered_as_an_offer():
    """The subtle one, and the reason this wrapper exists.

    `ingestion_status()` absorbs its own read failure and returns
    `not-attempted` with detail "ingestion status unreadable" — so "nobody has
    read the site" and "we could not tell" arrive as the SAME state. Rendering
    keys on state, so passing it through would produce a confident offer to
    ingest a site we know nothing about: absence dressed as a finding, again.

    It also must not take out the card it decorates. A missing offer is not a
    missing result.
    """
    assert _doc_ingestion_state(_Boom(), "any") == {"state": "", "detail": ""}


def test_the_state_is_carried_on_the_architecture_results():
    """The renderer reads it from here, so its presence is a contract."""
    reg = ProjectRegistry()
    slugs = [p.slug for p in reg.list_all()[:1]]
    if not slugs:
        pytest.skip("no registered repos")
    out = _architecture_recovery_results(reg, slugs[0])
    assert "documentation" in out
    assert set(out["documentation"]) == {"state", "detail"}


def test_every_live_state_is_one_the_renderer_handles():
    """A state the UI has no branch for renders as nothing, which is exactly the
    silent-absence failure this whole area keeps producing. Measured across the
    real corpus rather than assumed from the constants.
    """
    from resource_explorer.surveyors.sub_surveyors import arch_lens

    handled = {
        arch_lens.ING_NOT_ATTEMPTED,
        arch_lens.ING_DECLINED,
        arch_lens.ING_INGESTED,
        arch_lens.ING_ATTEMPTED_EMPTY,
    }
    reg = ProjectRegistry()
    seen = {arch_lens.ingestion_status(reg, p.slug)[0] for p in reg.list_all()}
    unhandled = seen - handled - {""}
    assert not unhandled, f"live states with no render branch: {unhandled}"


def test_the_unreadable_sentinel_still_exists_upstream():
    """A guard on someone else's wording, which is the fragile part.

    `_doc_ingestion_state` distinguishes "nobody read the site" from "we could
    not tell" by matching the detail string `ingestion_status()` returns on a
    read failure — because both arrive as `not-attempted`. If that wording
    changes, the match silently stops working and the card goes back to
    confidently offering to ingest sites whose status merely failed to load.

    Silently is the problem. This fails loudly instead, and should be deleted
    the day `ingestion_status()` returns a distinct state for the two — an offer
    already made to that effect.
    """
    import inspect

    from resource_explorer.surveyors.sub_surveyors import arch_lens

    src = inspect.getsource(arch_lens.ingestion_status)
    assert "ingestion status unreadable" in src, (
        "the sentinel _doc_ingestion_state matches on has changed. Either update "
        "that match, or better, switch to a distinct state if ingestion_status() "
        "now provides one."
    )


def test_an_unreadable_status_never_produces_an_offer():
    """The behaviour the sentinel exists to protect, asserted directly so it
    survives however the detection is implemented."""
    from resource_explorer.surveyors.sub_surveyors import arch_lens

    class _Unreadable:
        def query_metrics(self, *a, **kw):
            raise RuntimeError("boom")

    state, detail = arch_lens.ingestion_status(_Unreadable(), "x")
    rendered = _doc_ingestion_state(_Unreadable(), "x")
    assert rendered["state"] != arch_lens.ING_NOT_ATTEMPTED, (
        f"an unreadable status ({state}/{detail!r}) would render as an offer"
    )
