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


# ── the architecture diagram's second half ───────────────────────────────────
#
# `architecture_diagram` is the first kind whose results view cannot be built
# from its payload alone: the payload holds Mermaid SOURCE, and the picture is
# drawn by the Kroki proxy (POST /api/diagrams/mermaid). A `(data) => html`
# renderer cannot await that, so _renderArchitectureDiagramResults emits a
# placeholder and renderPendingArchDiagrams() fills it in after the caller has
# inserted the HTML.
#
# That split has an invariant no other kind has: a site that inserts results
# HTML and never runs the sweep shows an empty bordered box — a card that looks
# built and is blank, which is worse than the missing Results button this file's
# other tests were written for. Four sites insert results HTML today; the point
# of deriving them below rather than listing them is that a fifth is caught.


def _top_level_functions(html: str) -> dict[str, str]:
    """Split index.html's script into its top-level `function`/`async function`
    bodies. Column-0 anchored — every function these tests care about is
    top-level, and a nested one would belong to its parent's body anyway."""
    # Line comments stripped first: this file discusses its own function names
    # constantly, and a comment naming _renderAnalysisResultsContent() would
    # otherwise classify a function by what it talks about rather than what it
    # calls. (Harmless today — _loadDashboardTrendCharts was picked up that way
    # and could not affect the result — but a derivation that reads prose as
    # code is one edit away from being wrong in a direction that matters.)
    html = re.sub(r"^\s*//.*$", "", html, flags=re.M)
    starts = [(m.start(), m.group(1))
              for m in re.finditer(r"^(?:async )?function (\w+)\s*\(", html, re.M)]
    out = {}
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(html)
        out[name] = html[pos:end]
    return out


def test_every_site_that_inserts_results_html_draws_pending_diagrams():
    html = INDEX.read_text()
    fns = _top_level_functions(html)

    # A function that builds results HTML but never assigns innerHTML hands it
    # upward — its caller is the insertion site, not it. _renderGroupedCards
    # Dashboard is the one such today.
    producers = {"_renderAnalysisResultsContent"}
    producers |= {n for n, b in fns.items()
                  if "_renderAnalysisResultsContent(" in b and ".innerHTML" not in b}

    inserters = {
        n for n, b in fns.items()
        if ".innerHTML" in b and any(f"{p}(" in b for p in producers)
        and n not in producers
    }
    assert inserters, "found no results-insertion sites at all — the derivation broke, not the code"

    missing = {n for n in inserters if "renderPendingArchDiagrams(" not in fns[n]}
    assert not missing, (
        f"these insert analysis results HTML and never draw the pending "
        f"architecture diagram, so an architecture_diagram card renders as an "
        f"empty bordered box: {sorted(missing)}. Call renderPendingArchDiagrams() "
        f"after the innerHTML assignment."
    )


def test_the_placeholder_is_claimed_before_the_diagram_is_fetched():
    """Two sweeps can overlap — a dashboard rendering while a chat card is still
    fetching. Measured with the claim moved after the await: three POSTs for two
    placeholders, the second overwriting the first's SVG."""
    html = INDEX.read_text()
    body = _top_level_functions(html)["renderPendingArchDiagrams"]
    claim = body.index("container.dataset.rendered = 'true'")
    fetched = body.index("await fetch(")
    assert claim < fetched, (
        "renderPendingArchDiagrams marks a placeholder rendered only after "
        "awaiting the diagram server, leaving a window in which a second sweep "
        "posts the same source again."
    )


def test_every_path_that_can_show_a_diagram_also_offers_its_source():
    """The Mermaid source is the take-away form of this card (pastes into a PR
    or an ADR and stays live, and is diffable between runs where two pictures
    are not). All three exits of the renderer have a `mermaid` string in hand
    — drawn, too-large-to-draw, and the empty case — so the two that have a
    diagram to talk about must both offer it, not just the happy one."""
    html = INDEX.read_text()
    body = _top_level_functions(html)["_renderArchitectureDiagramResults"]

    # The early return for "no data at all" legitimately has no source to show.
    returns = [seg for seg in body.split("return ")[1:]
               if "_renderEmptyResultState" not in seg]
    assert len(returns) >= 2, (
        "expected at least the drawn and the too-large returns to inspect; the "
        "derivation broke, not the code"
    )
    missing = [i for i, seg in enumerate(returns) if "_renderMermaidSource(" not in seg]
    assert not missing, (
        f"{len(missing)} of {len(returns)} returns in "
        f"_renderArchitectureDiagramResults show a diagram (or say why it "
        f"cannot be drawn) without offering its Mermaid source. Add "
        f"_renderMermaidSource(data.mermaid)."
    )


def test_a_diagram_that_cannot_be_drawn_still_shows_its_source():
    """The failure path is the one that most needs the source: the diagram
    server being unreachable is exactly when a reader has no other route to
    the answer, and the source is already sitting in the placeholder's
    dataset. Guards against it regressing to an error message alone."""
    html = INDEX.read_text()
    body = _top_level_functions(html)["renderPendingArchDiagrams"]
    catch = body[body.index("} catch ("):]
    assert "dataset.mcode" in catch, (
        "renderPendingArchDiagrams' failure path no longer renders the Mermaid "
        "source it already holds in container.dataset.mcode — a reader whose "
        "diagram server is down now gets an error and nothing else."
    )


def test_the_source_block_is_escaped_exactly_once():
    """_esc() on an already-escaped string double-escapes: the reader copies
    `A --&gt; B` and pastes something no Mermaid renderer accepts. The
    placeholder's data-mcode is escaped at emit time and decoded by reading
    .dataset, so the failure path escapes once; the <details> block escapes the
    raw payload once. Neither may escape a value that _esc already touched."""
    html = INDEX.read_text()
    fns = _top_level_functions(html)
    src = fns["_renderMermaidSource"]
    assert "_esc(mermaid)" in src, "_renderMermaidSource no longer escapes its input"
    assert src.count("_esc(") == 1, (
        f"_renderMermaidSource escapes {src.count('_esc(')} times; the source "
        f"is displayed once and must be escaped once."
    )
    # The renderer must hand it the RAW payload, never the escaped copy.
    body = fns["_renderArchitectureDiagramResults"]
    assert "_renderMermaidSource(_esc(" not in body, (
        "_renderArchitectureDiagramResults passes an already-escaped string to "
        "_renderMermaidSource, so the copy button yields &gt; instead of >."
    )
