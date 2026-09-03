"""_gap_analysis_results — the shared reader for the four GAP analyses
(secret_scan, telemetry_scan, contribution_provenance, sla_content) —
dropped every finding's `detail` down to check_name/label/summary/confidence.
secret_scan.py's per-match `excerpt` (the actual matched text, computed and
persisted, never reproduced in the finding's own `summary`) was silently
unreachable through this reader for all four kinds it serves.

Backlog.md item 3's 31-reader sweep.
"""
from __future__ import annotations

from resource_explorer.surveyors.repo_survey_definition_adapter import (
    _contribution_provenance_results,
    _secret_scan_results,
    _sla_content_results,
    _telemetry_scan_results,
)


class _Reg:
    def __init__(self, rows):
        self._rows = rows

    def query_findings(self, slug, kind):
        return self._rows


class TestDetailPassesThroughEveryFinding:
    def test_secret_scan_excerpt_reaches_the_reader(self):
        rows = [
            {"check_name": "scan_summary", "label": "recovered", "summary": "1 match",
             "confidence": 100, "detail_json": '{"outcome": "recovered"}'},
            {"check_name": "secret-rule-1", "label": "secret-rule-1",
             "summary": "possible secret at src/config.py:42", "confidence": 80,
             "detail_json": '{"path": "src/config.py", "line": 42, '
                            '"rule_id": "secret-rule-1", "excerpt": "sk_live_****MASKED"}'},
        ]
        out = _secret_scan_results(_Reg(rows), "acme/widget")
        match = next(f for f in out["findings"] if f["check_name"] == "secret-rule-1")
        assert match["detail"]["excerpt"] == "sk_live_****MASKED", \
            "excerpt was computed and persisted but never reached the results reader"

    def test_status_envelope_is_unaffected_by_the_passthrough(self):
        """The fix must not disturb the existing scan_summary -> _status wiring.
        detail_json here matches StepOutcome.as_row()'s real shape
        (outcome/outcome_cause/outcome_known_positive) — status_from_detail
        derives _status.state from `outcome`, not from a pre-built `state`
        key, so the fixture has to speak that vocabulary to exercise the
        real code path."""
        rows = [
            {"check_name": "scan_summary", "label": "no_signal",
             "summary": "clean scan", "confidence": 100,
             "detail_json": '{"outcome": "no_signal", "outcome_cause": "",'
                            ' "outcome_known_positive": true}'},
        ]
        out = _secret_scan_results(_Reg(rows), "acme/widget")
        assert out["_status"]["state"] == "nothing_found"
        assert out["_status"]["outcome"] == "no_signal"

    def test_other_three_gap_readers_also_carry_detail_through(self):
        """Confirms the fix is structural (in _gap_analysis_results itself),
        not something patched only into the secret_scan call site."""
        rows = [
            {"check_name": "some_check", "label": "gap", "summary": "x", "confidence": 50,
             "detail_json": '{"marker": "present"}'},
        ]
        for reader in (_telemetry_scan_results, _contribution_provenance_results, _sla_content_results):
            out = reader(_Reg(rows), "acme/widget")
            assert out["findings"][0]["detail"] == {"marker": "present"}, reader.__name__

    def test_missing_detail_json_is_an_empty_dict_not_a_crash(self):
        rows = [
            {"check_name": "x", "label": "gap", "summary": "s", "confidence": 0,
             "detail_json": None},
        ]
        out = _secret_scan_results(_Reg(rows), "acme/widget")
        assert out["findings"][0]["detail"] == {}
