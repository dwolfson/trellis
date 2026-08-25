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

import inspect
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


def _js_object_pairs(name: str) -> dict[str, str]:
    """Same parse as _js_object_keys, but keeping the values.

    The key-only check above was written for a real bug and stopped one step
    short of it: `repository_health` and `repo_classification` both HAD entries,
    so every key assertion passed, while their values disagreed with the backend
    and their cards rendered wrongly. A present-but-wrong entry is invisible to
    a membership test.
    """
    html = INDEX.read_text()
    start = html.index(f"const {name} = {{")
    body = html[start:html.index("};", start)]
    return dict(re.findall(r"^\s*(\w+):\s*'([^']*)'", body, re.M))


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


def test_render_mode_values_agree_with_the_backend():
    """A render mode that exists but names the wrong branch is worse than a
    missing one: the card renders, so nothing looks broken, but it renders the
    wrong shape and falls through to the empty state.

    Both real instances behaved that way. `repository_health` declared
    'findings_list' against a payload with no `findings` key, so a repo with
    genuine scores displayed "No results yet — click Run to scan."
    `repo_classification` declared 'custom' where the backend said
    'findings_list'; there the frontend was right and the backend entry was
    stale. Hence comparing values, not asserting one side is authoritative.
    """
    frontend = _js_object_pairs("_REPO_RESULTS_RENDER_MODE")
    backend = {k: v.results.render for k, v in ANALYSIS_KINDS.items() if v.results}

    mismatched = {
        k: (frontend[k], backend[k])
        for k in frontend.keys() & backend.keys()
        if frontend[k] != backend[k]
    }
    assert not mismatched, (
        "render mode disagrees between index.html and ANALYSIS_KINDS "
        f"(analysis_id: (frontend, backend)): {mismatched}. "
        "Decide which side is right — a stale backend declaration and a wrong "
        "frontend branch both present as an empty results card."
    )


def test_metrics_mode_readers_return_metrics_at_the_top_level():
    """The 'metrics' branch iterates the payload's own entries and filters out
    only detail/surveyed_at/_status, so a reader that nests its numbers under
    an envelope key renders one row named after the envelope.

    _health_results did exactly that. This pins the contract that made the
    render-mode fix real rather than merely consistent.
    """
    from resource_explorer.surveyors import repo_survey_definition_adapter as A

    reserved = {"detail", "surveyed_at", "_status"}
    for kind, spec in ANALYSIS_KINDS.items():
        if not spec.results or spec.results.render != "metrics":
            continue
        src = inspect.getsource(spec.results.results_reader)
        assert '"metrics":' not in src and "'metrics':" not in src, (
            f"{kind}'s reader ({spec.results.results_reader.__name__}) appears to "
            "nest its numbers under a 'metrics' key, but its render mode is "
            "'metrics', which reads them from the top level. Flatten the payload "
            f"(reserved top-level keys: {sorted(reserved)})."
        )
