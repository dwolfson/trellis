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

    "Nobody has read the site" and "we could not tell" must not arrive as the
    same thing: rendering keys on state, so passing the second through as the
    first would produce a confident offer to ingest a site we know nothing
    about — absence dressed as a finding, again.

    They used to arrive as one state, and this told them apart by matching
    `ingestion_status`'s DETAIL STRING. That coupling is gone: `unknown` is a
    state of its own, and this asserts the BEHAVIOUR rather than the sentinel,
    so it survives however the distinction is implemented. It also must not take
    out the card it decorates — a missing offer is not a missing result.
    """
    assert _doc_ingestion_state(_Boom(), "any") == {"state": "", "detail": ""}


def test_the_unknown_state_is_what_the_wrapper_keys_on():
    """Named explicitly so the contract between these two modules is a value,
    not a phrase. If `ingestion_status` renames the state, this fails loudly;
    when it merely reworded the detail, the old sentinel failed silently."""
    import inspect

    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        _doc_ingestion_state as f,
    )
    from resource_explorer.surveyors.sub_surveyors.arch_lens import ING_STATES, ING_UNKNOWN

    assert ING_UNKNOWN in ING_STATES
    assert "ING_UNKNOWN" in inspect.getsource(f)
    assert "ingestion status unreadable" not in inspect.getsource(f), (
        "the detail-string sentinel is gone; the state is the contract"
    )


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


# The sentinel test that used to sit here is deleted, as its own docstring said
# it should be: it guarded a match on ingestion_status()'s DETAIL STRING, which
# was only ever a stand-in for a distinction the state could not express.
# `ING_UNKNOWN` now exists, the wrapper keys on it, and
# test_the_unknown_state_is_what_the_wrapper_keys_on asserts the contract as a
# VALUE — which fails loudly if renamed, where the wording failed silently when
# reworded. Keeping both would guard a dependency that no longer exists.
#
# It earned its keep first: it went red on the very commit that changed the
# wording, in the same run, before the behaviour drifted.


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


def test_every_live_skip_reason_has_an_explanation():
    """A skip reason with no branch renders as a bare label.

    The website-ingestion card leads with the REASON when nothing was stored,
    because a zero there is usually the system being right — measured
    2026-08-25, 20 of 60 repos are in that state. A reason the UI cannot explain
    reduces to the raw enum value, which is better than a bare 0 but still makes
    the reader guess whether it is a fault.

    Checked against the reasons actually occurring in the corpus rather than the
    constants, so a new one added upstream fails here rather than shipping as an
    unexplained label.
    """
    import re
    from pathlib import Path

    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.repo_survey_definition_adapter import ANALYSIS_KINDS

    reader = ANALYSIS_KINDS["website_ingestion"].results.results_reader
    reg = ProjectRegistry()
    live = set()
    for p in reg.list_all():
        res = reader(reg, p.slug)
        if not res.get("chunks") and res.get("reason"):
            live.add(res["reason"])
    if not live:
        pytest.skip("no skipped ingestions in this corpus")

    index = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "index.html"
    block = index.read_text().split("const _WEBSITE_SKIP_REASON = {")[1].split("};")[0]
    explained = set(re.findall(r"^\s*(\w+):", block, re.M))

    missing = live - explained
    assert not missing, (
        f"skip reason(s) with no explanation in the card: {sorted(missing)}. "
        "They render as the raw enum value, leaving the reader to guess whether "
        "a zero is a fault or the system being right."
    )
