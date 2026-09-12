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


class TestLiveReadRequiresAnAbsenceGate:
    """`live_read=True` bypasses the run gate: facts.py reads the results and
    reports MEASURED whenever `_has_content()` says there is something there.
    That is only correct if the reader can say "nothing here" — and these
    readers cannot say it by returning an empty-ish dict, because every one of
    them stamps `slug` into the payload unconditionally, and a non-empty string
    IS content.

    Measured 2026-09-09 before the gate went in: `_architecture_recovery_results`
    on a slug that does not exist returned `_has_content() == True` with a
    headline of None — so live_read would have reported "measured" with no
    label, for every unknown repo. The fix is the `_status` envelope, which is
    the one shape `_has_content` exempts.
    """

    def _live_read_kinds(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import ANALYSIS_KINDS
        return {
            aid: kind for aid, kind in ANALYSIS_KINDS.items()
            if getattr(getattr(kind, "results", None), "live_read", False)
        }

    def test_there_is_at_least_one_live_read_kind_to_check(self):
        assert self._live_read_kinds(), (
            "no AnalysisKind sets live_read — this whole class is passing "
            "vacuously; the derivation broke, not the code"
        )

    def test_every_live_read_reader_reports_absence_as_absence(self):
        """The property that matters, checked by calling the readers rather than
        by reading their source: on a slug nothing has ever touched, a live_read
        reader must produce something `_has_content()` calls empty."""
        from resource_explorer.facts import _has_content
        from resource_explorer.registry import ProjectRegistry

        registry = ProjectRegistry()
        absent = "definitely_not_a_repo_" + "x" * 12
        offenders = []
        for aid, kind in self._live_read_kinds().items():
            reader = kind.results.results_reader
            try:
                value = reader(registry, absent)
            except Exception:
                continue  # a reader that refuses outright cannot claim measured
            if _has_content(value):
                keys = sorted(
                    k for k, v in (value or {}).items()
                    if k not in {"_status", "surveyed_at", "detail", "scoped_to",
                                 "run_outcomes"} and _has_content(v)
                )
                offenders.append((aid, keys))
        assert not offenders, (
            f"these live_read analyses report content for a repo that does not "
            f"exist, so facts.py will call them MEASURED with no headline: "
            f"{offenders}. Return a bare {{'_status': ...}} when there is "
            f"genuinely nothing, the way _architecture_diagram_results does."
        )

    @pytest.mark.corpus
    def test_the_gate_keys_on_the_timestamp_not_on_having_components(self):
        """The gate must not swallow the real answers it sits in front of.

        Marked `corpus`: it asserts over whatever the live registry holds,
        and on CI's empty Postgres it failed on its own vacuity guard --
        the one failure left after #43 let the suite run to the end.

        The tempting wrong fix is `if not all_components` — it looks equivalent
        and is not. Measured 2026-09-09: 8 of 61 repos have ZERO
        architecture_recovery findings and still carry a surveyed_at, because
        their steps ran and recorded a run_outcome saying the repo could not be
        read. "Unverified — coupling, detect could not read this repo" is a real
        answer (README finding 57: an unverified run and a genuine zero are
        indistinguishable as a bare count), and a component-count gate reports
        it as never-run. Only a repo nothing has ever touched has no timestamp.
        """
        from resource_explorer.facts import _has_content
        from resource_explorer.registry import ProjectRegistry
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _architecture_recovery_results)

        registry = ProjectRegistry()
        surveyed_but_empty = []
        for project in registry.list_all():
            value = _architecture_recovery_results(registry, project.slug)
            if value.get("surveyed_at") and not value.get("component_count"):
                surveyed_but_empty.append((project.slug, _has_content(value)))

        assert surveyed_but_empty, (
            "no repo in the registry is surveyed-but-componentless, so this test "
            "cannot distinguish a timestamp gate from a component gate — it is "
            "passing vacuously and the corpus, not the code, changed"
        )
        silenced = [slug for slug, answered in surveyed_but_empty if not answered]
        assert not silenced, (
            f"{len(silenced)} of {len(surveyed_but_empty)} repos that were "
            f"surveyed but recovered no components now report nothing: "
            f"{silenced[:5]}. The absence gate is keying on component count "
            f"rather than surveyed_at, which discards the 'ran but could not "
            f"read the repo' outcome."
        )
