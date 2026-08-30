"""Outcome data reaching a surface — the readers, and the cards that read them.

Across the corpus 67 persisted outcomes are not `recovered`. Wiring them into
readers is only half the job: a reader that computes a field no renderer reads
is the same failure as not computing it, which is exactly what
_architecture_recovery_results' own docstring says about the layer below it —
and then its renderer read none of run_outcomes/unverified/partial/
completeness_note. The same defect, one layer further along.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_HTML = pathlib.Path(__file__).parent.parent / "resource_explorer" / "web" / "static" / "index.html"
_ADAPTER = (pathlib.Path(__file__).parent.parent / "resource_explorer" / "surveyors"
            / "repo_survey_definition_adapter.py")


@pytest.fixture(scope="module")
def html() -> str:
    return _HTML.read_text()


class TestEveryCustomModeHasARenderer:
    """manifest_parse was declared 'custom' with no branch, so it rendered
    "No results view for this analysis" while holding 61 dependencies, 3 CI
    checks and 5 convention signals. Declaring a mode is not implementing it."""

    def test_no_custom_kind_falls_through(self, html):
        # _renderCustomAnalysisResults used to be one if/else chain, each
        # branch its own `analysisId === '...'` check — 2026-08-30's
        # kind-plugin extraction replaced that with a lookup into
        # _CUSTOM_RESULT_RENDERERS (kind -> renderer function), so a
        # declared-but-unimplemented kind now shows up as a key with no
        # matching function reference rather than a missing branch. Same
        # invariant, different shape: a 'custom' mode with nothing wired to
        # it still falls through to "No results view for this analysis"
        # however much data it holds.
        modes = re.search(r"_REPO_RESULTS_RENDER_MODE = \{(.*?)\n\};", html, re.S).group(1)
        custom = set(re.findall(r"^\s*([a-z_]+):\s*'custom'", modes, re.M))
        registry = re.search(r"const _CUSTOM_RESULT_RENDERERS = \{(.*?)\n\};",
                              html, re.S).group(1)
        handled = set(re.findall(r"^\s*([a-z_]+):\s*_render\w+,?\s*$", registry, re.M))
        missing = custom - handled
        assert not missing, (
            f"declared 'custom' with no entry in _CUSTOM_RESULT_RENDERERS, so these render "
            f"'No results view for this analysis' however much data they hold: {sorted(missing)}"
        )


class TestManifestParseShowsWhyNotJustHowMany:

    def test_each_sub_parse_reports_separately(self):
        """egeria_git parses its CI and conventions fine and cannot read its
        build.gradle at all. One card-level status would have to pick a winner
        and would be wrong two ways out of three."""
        src = _ADAPTER.read_text()
        reader = re.search(r"def _manifest_parse_results\(.*?\n\n\ndef ", src, re.S).group(0)
        for key in ("dependencies", "ci_quality", "conventions"):
            assert f'"{key}"' in reader, key

    def test_a_bare_count_is_not_shown_for_an_unestablished_parse(self, html):
        """"0 · unverified" reads as a broken parse with no way to tell whose
        fault it is — the explanation replaces the count."""
        fn = re.search(r"function _renderManifestParseSub\(label, sub\) \{.*?\n\}", html, re.S).group(0)
        assert "not established" in fn
        assert "st.hint" in fn, "the cause must be shown, not just the state"


class TestArchitectureCardReadsWhatItsReaderWrites:

    @pytest.mark.parametrize("field", ["partial", "unverified", "completeness_note"])
    def test_completeness_signals_reach_the_card(self, html, field):
        # Was `if (analysisId === 'architecture_recovery') { ... }` inside
        # _renderCustomAnalysisResults — pulled into its own top-level
        # function, _renderArchitectureRecoveryResults, by 2026-08-30's
        # kind-plugin extraction. Same function body, one indent level
        # shallower and closed at column 0 rather than column 2.
        branch = re.search(r"function _renderArchitectureRecoveryResults\(data\) \{.*?\n\}",
                           html, re.S).group(0)
        assert field in branch, (
            f"the reader computes {field} so a scoped or unverified run cannot be "
            "mistaken for a complete one; a renderer that ignores it recreates "
            "the exact failure that field was added to prevent"
        )

    def test_both_return_paths_carry_it(self, html):
        """A partial run with zero components is still partial — the banner
        cannot live on only the populated path."""
        # Was `if (analysisId === 'architecture_recovery') { ... }` inside
        # _renderCustomAnalysisResults — pulled into its own top-level
        # function, _renderArchitectureRecoveryResults, by 2026-08-30's
        # kind-plugin extraction. Same function body, one indent level
        # shallower and closed at column 0 rather than column 2.
        branch = re.search(r"function _renderArchitectureRecoveryResults\(data\) \{.*?\n\}",
                           html, re.S).group(0)
        real_returns = [l for l in branch.split("\n")
                        if l.strip().startswith("return ") and "bits" not in l and "''" not in l]
        assert real_returns, "no return statements found — the regex needs revisiting"
        for r in real_returns:
            assert "completeness" in r, f"return without the completeness banner: {r.strip()[:70]}"
