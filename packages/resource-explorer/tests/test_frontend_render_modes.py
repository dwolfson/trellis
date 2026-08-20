"""The frontend's analysis-kind mirrors must not fall behind the backend.

index.html hand-maintains two objects keyed by analysis_id — _REPO_RESULTS_RENDER_MODE
(which render branch a kind's results use) and _REPO_TREND_LABEL (the trend
chart's Y-axis unit). Both are documented as mirroring ANALYSIS_KINDS, and both
silently fell behind it: repository_health, code_symbol_extraction,
rag_ingestion and website_ingestion each had a working backend results reader
and no entry here, so their cards rendered with no Results button at all — the
button is gated on membership of the render-mode object.

Nothing failed, which is what made it survive: a missing entry looks exactly
like an analysis that was never meant to have results. These tests are the
check that was missing, not a restatement of the fix.

Parsed with a regex rather than a JS engine on purpose — the SPA has no build
step and no JS test runner, and adding either to guard two object literals
would cost more than it protects.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from resource_explorer.surveyors.repo_survey_definition_adapter import ANALYSIS_KINDS

INDEX = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "index.html"


def _js_object_keys(name: str) -> set[str]:
    html = INDEX.read_text()
    start = html.index(f"const {name} = {{")
    body = html[start:html.index("};", start)]
    return set(re.findall(r"^\s*(\w+):\s*'", body, re.M))


@pytest.fixture(scope="module")
def kinds_with_results() -> set[str]:
    return {k for k, v in ANALYSIS_KINDS.items() if v.results}


def test_every_kind_with_results_has_a_render_mode(kinds_with_results):
    """Without an entry the card renders no Results button, so a working
    backend reader is unreachable from the UI."""
    missing = kinds_with_results - _js_object_keys("_REPO_RESULTS_RENDER_MODE")
    assert not missing, (
        f"analysis kinds with backend results but no frontend render mode: {sorted(missing)}. "
        "Add them to _REPO_RESULTS_RENDER_MODE in index.html."
    )


def test_no_render_mode_for_a_kind_that_no_longer_exists(kinds_with_results):
    """The other direction: an entry for a removed kind is dead code that reads
    as coverage."""
    stale = _js_object_keys("_REPO_RESULTS_RENDER_MODE") - kinds_with_results
    assert not stale, f"frontend render modes for unknown analysis kinds: {sorted(stale)}"


def test_render_modes_are_ones_the_frontend_can_dispatch():
    """_renderAnalysisResultsContent dispatches on exactly these three; anything
    else falls through to the custom branch and renders by accident."""
    html = INDEX.read_text()
    start = html.index("const _REPO_RESULTS_RENDER_MODE = {")
    body = html[start:html.index("};", start)]
    used = set(re.findall(r":\s*'(\w+)'", body))
    assert used <= {"findings_list", "metrics", "custom"}


def test_every_kind_with_a_trend_has_a_y_axis_label():
    """The trend chart is generic, so without a label the plotted number has no
    stated unit — a chart that looks authoritative and says nothing."""
    with_trend = {k for k, v in ANALYSIS_KINDS.items()
                  if v.results and v.results.trend_reader}
    missing = with_trend - _js_object_keys("_REPO_TREND_LABEL")
    assert not missing, (
        f"analysis kinds with a trend reader but no Y-axis label: {sorted(missing)}. "
        "Add them to _REPO_TREND_LABEL in index.html."
    )
