"""A live-read analysis must not report "cannot be determined" about data it
can see.

`FactLayer.fact()` gates on whether the analysis appears in a recorded survey
run. For most analyses that is right — their results were written BY a survey,
so an unattributable result is genuinely unattributable.

`api_structure` is different and says so in its own reader comment: it queries
`project_code_symbols`, which is repopulated at INGESTION, not survey time. It
is current whether or not a survey ever ran. Measured 2026-09-02 on
egeria_python_git before the fix: state `not_established` — "surveyed by runs
that predate per-step recording, so whether this analysis was among them
cannot be determined" — while the reader returned 8,654 symbols.

That is a claim about our run bookkeeping, dressed as a claim about the
resource.
"""
from __future__ import annotations

import pytest

from resource_explorer.facts import FactLayer
from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.result_status import MEASURED, NEVER_RUN, NOT_ESTABLISHED


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="p", display_name="P", github_url="u", description=""))
    return reg


def _seed_symbols(registry, n=3):
    from resource_explorer.ingestion.code_symbol_extractor import CodeSymbol
    registry.upsert_code_symbols("p", [
        CodeSymbol(resource_slug="p", file_path=f"m{i}.py", language="python",
                   kind="function", name=f"f{i}", qualified_name=f"f{i}",
                   signature="()", docstring="", start_line=1, end_line=2)
        for i in range(n)
    ])


class TestLiveRead:
    def test_no_recorded_run_still_reports_measured(self, registry):
        """The known-negative. Unset `live_read` on api_structure and this
        fails with not_established — the pre-fix behaviour, about a table
        with rows in it."""
        _seed_symbols(registry)
        f = FactLayer(registry).fact("p", "api_structure")

        assert f.state == MEASURED, (
            f"a live-read analysis with data must not be {f.state}: {f.note!r}"
        )
        assert f.value.get("symbol_count") == 3

    def test_it_says_where_the_currency_comes_from(self, registry):
        """A reader should not have to guess why this one is measured with no
        survey behind it."""
        _seed_symbols(registry)
        note = FactLayer(registry).fact("p", "api_structure").note.lower()
        assert "ingestion" in note and "survey" in note

    def test_an_empty_live_read_still_falls_through_to_the_run_gate(self, registry):
        """live_read must not manufacture a verdict from nothing. With no
        symbols at all there is no data to be current about, so the honest
        answer is still the run-gate's."""
        f = FactLayer(registry).fact("p", "api_structure")
        assert f.state != MEASURED
        assert f.state in (NOT_ESTABLISHED, NEVER_RUN)

    def test_a_non_live_read_analysis_is_unaffected(self, registry):
        """The gate still applies to everything that genuinely depends on a
        survey run having happened."""
        f = FactLayer(registry).fact("p", "security_scan")
        assert f.state != MEASURED
