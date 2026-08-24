"""Every intent with analyses must have a control that runs them.

Dan tried to run `repo_classification` from the UI and nothing happened —
there was no control for it. All five discovery-intent analyses
(repo_classification, architecture_recovery, license_classification, maturity,
repo_conventions) were catalogued, step-mapped, and runnable through
POST /{slug}/analyses/{id}/run. Nothing in the UI called it for them:
_loadAnalysisCatalogPanel was invoked for 'assessment' and 'analysis' only, and
the Discovery pane rendered Survey Definitions instead.

It presented as the shape this codebase keeps producing — the pane loaded, threw
nothing, and rendered successfully; it just rendered something else. "I clicked
and nothing ran" was indistinguishable from "there was nothing to run".

Scouting is the near-miss that made it easy to overlook: its analyses are also
card-less, but the Scouting scan button reaches them, so the pattern looked
handled.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

_HTML = pathlib.Path(__file__).parent.parent / "resource_explorer" / "web" / "static" / "index.html"

#: Intents whose analyses are reachable by something other than a catalog card.
#: Each needs a named reason — an exemption without one is how the Discovery
#: gap would have been "documented" rather than fixed.
_REACHED_ANOTHER_WAY = {
    "scouting": "the Scouting scan button runs repo_health/repo_language directly",
    "curate": "egeria_publish is a publish action, not a survey step — it has no step map",
    "enrichment": "served by context.py's form, not by the analysis catalog",
    "automate": "served by notification_subscriptions, not by the analysis catalog",
    "understanding": "charts, not runnable analyses",
}


@pytest.fixture(scope="module")
def panel_intents() -> set[str]:
    src = _HTML.read_text()
    return set(re.findall(r"_loadAnalysisCatalogPanel\('([a-z_]+)'", src))


def test_every_intent_with_analyses_has_a_way_to_run_them(panel_intents):
    by_intent: dict[str, list[str]] = {}
    for a in get_analyses("repo"):
        by_intent.setdefault(a.get("intent") or "", []).append(a["id"])

    unreachable = {
        intent: ids for intent, ids in by_intent.items()
        if intent not in panel_intents and intent not in _REACHED_ANOTHER_WAY
    }
    assert not unreachable, (
        "these intents have catalogued analyses and no control that runs them — "
        "the pane will render successfully and simply not offer them: "
        f"{ {k: sorted(v) for k, v in unreachable.items()} }"
    )


def test_discovery_specifically_has_a_panel(panel_intents):
    """The regression this file was written for."""
    assert "discovery" in panel_intents


def test_an_exemption_must_say_why(panel_intents):
    """A bare exemption list would let the next intent go quiet the same way."""
    for intent, reason in _REACHED_ANOTHER_WAY.items():
        assert reason and len(reason) > 20, intent


def test_the_discovery_tab_routes_to_a_real_view():
    """A sub-tab that routes nowhere is the same silence with extra steps."""
    src = _HTML.read_text()
    assert "showMainView('discovery-analyses')" in src
    assert "tab === 'discovery-analyses'" in src
    assert 'id="discovery-analyses-view"' in src
