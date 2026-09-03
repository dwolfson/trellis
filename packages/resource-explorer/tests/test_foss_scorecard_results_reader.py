"""_foss_scorecard_results/_headline must surface everything score() computes.

Filed under docs/Backlog.md item 3, "the silent field-allowlist pattern" — the
sweep finding 118 asked for across other sites. `_foss_scorecard_results`
(repo_survey_definition_adapter.py) read three named metric keys and stopped,
while `score()` (foss_scorecard.py) computes and persists five, three as named
metrics and two — `checks_total`, `comparable_to_openssf` — only in `detail`.
`checks_total` is exactly the denominator this reader's OWN docstring exists
to preserve ("8.0 over five checks and 8.0 over twelve are different claims"),
and `_foss_scorecard_headline`'s label rendered "N checks" with no way to tell
which. Both were silently unreachable from the results API.

The regression guard here is structural, not enumerated: it calls the real
`score()` and asserts every key it returns reaches the reader's output. A
future key added to `score()` fails this test rather than becoming a fifth
silently-dropped field — the same shape of guard
`test_site_ingestion_guards.py::TestTheDetailAllowlistCoversEveryCaller`
already built for `_note`'s allowlist, applied here.
"""
from __future__ import annotations

from resource_explorer.surveyors.repo_survey_definition_adapter import (
    _foss_scorecard_headline,
    _foss_scorecard_results,
)
from resource_explorer.surveyors.sub_surveyors.foss_scorecard import FAIL, PASS, PARTIAL, score


class _Reg:
    """Shapes query_metrics() exactly as registry.py's real implementation
    does: {metric_name: value, ..., "surveyed_at": ..., "detail": {...}} —
    the named metrics flattened at the top level, everything else nested
    under "detail". Getting this nesting wrong would make the test pass for
    the wrong reason."""

    def __init__(self, findings, agg):
        self._findings = findings
        self._agg = agg

    def query_findings(self, slug, kind):
        return self._findings

    def query_metrics(self, slug, kind):
        if not self._agg:
            return {}
        return {
            "score": self._agg["score"],
            "checks_evaluated": float(self._agg["checks_evaluated"]),
            "checks_unknown": float(self._agg["checks_unknown"]),
            "surveyed_at": "2026-09-03T00:00:00",
            "detail": dict(self._agg),
        }


def _finding(label: str) -> dict:
    return {"check_name": f"check-{label}", "label": label, "summary": "", "confidence": 100}


class TestEveryScoreKeyReachesTheResultsReader:
    def test_a_partial_coverage_scorecard_surfaces_its_denominator(self):
        """5 evaluated of 12 total — the exact ambiguity this analysis exists
        to avoid, per its own docstring."""
        results = ([_finding(PASS)] * 3 + [_finding(PARTIAL)] * 2
                   + [{"check_name": "c", "label": "unknown", "summary": "", "confidence": 0}] * 7)
        agg = score(results)
        assert agg["checks_evaluated"] == 5 and agg["checks_total"] == 12

        out = _foss_scorecard_results(_Reg(results, agg), "acme/widget")

        assert out["checks_total"] == 12
        assert out["comparable_to_openssf"] is False

    def test_the_reader_is_a_superset_of_whatever_score_computes(self):
        """Structural guard, not an enumerated one: every key score() returns
        must reach the reader's output. Fails on a future key exactly the way
        checks_total's omission should have failed before this fix."""
        results = [_finding(PASS)] * 4 + [_finding(FAIL)] * 2
        agg = score(results)

        out = _foss_scorecard_results(_Reg(results, agg), "acme/widget")

        missing = set(agg.keys()) - set(out.keys())
        assert not missing, f"score() computes {missing} but the reader drops it"

    def test_no_metrics_yet_returns_only_findings(self):
        """Never run: query_metrics() returns {} per its own contract, and
        the reader must not invent zeros for a run that never happened."""
        out = _foss_scorecard_results(_Reg([], None), "acme/widget")
        assert out == {"findings": []}


class TestTheHeadlineLabelSaysTheDenominatorWhenItMatters:
    def test_partial_coverage_names_both_numbers(self):
        results = ([_finding(PASS)] * 3 + [_finding(PARTIAL)] * 2
                   + [{"check_name": "c", "label": "unknown", "summary": "", "confidence": 0}] * 7)
        agg = score(results)

        headline = _foss_scorecard_headline(_Reg(results, agg), "acme/widget")

        assert "5 of 12 checks" in headline["label"], headline["label"]

    def test_full_coverage_does_not_say_5_of_5(self):
        """Spelling out an equal denominator is noise the docstring's own
        example doesn't ask for — only a genuine gap should surface it."""
        results = [_finding(PASS)] * 5
        agg = score(results)

        headline = _foss_scorecard_headline(_Reg(results, agg), "acme/widget")

        assert "of 5" not in headline["label"], headline["label"]
        assert "5 checks" in headline["label"], headline["label"]
