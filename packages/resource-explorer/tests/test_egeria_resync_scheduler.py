"""Tests for egeria_resync.py's scan_and_clear() — the scheduled,
unattended counterpart to a human clicking Apply in Admin > Egeria Alignment.

Built 2026-09-04 after a full Egeria repository-store wipe: the human-driven
recovery path (EgeriaResync.scan()/apply()) worked exactly as designed, but
nothing ran it until someone remembered to. scan_and_clear() automates only
SAFE_SCHEDULED_STEPS — the four clear_* repairs that verify live before
writing, cost no real time, and never need a human decision — leaving
anything expensive (archive downloads) or needs_decision (Egeria Project
bindings) untouched for a person to handle deliberately.

These tests are about the DECISION LOGIC (which steps get proposed to
apply()), not EgeriaResync's own scan/apply internals — those already have
their own coverage elsewhere.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from resource_explorer.egeria_resync import (
    EXPENSIVE_STEPS,
    SAFE_SCHEDULED_STEPS,
    Finding,
    ScanResult,
    scan_and_clear,
)


def _scan_result(*findings, reachable=True, unreachable_reason=""):
    return ScanResult(reachable=reachable, unreachable_reason=unreachable_reason, findings=list(findings))


class TestScanAndClear:
    def test_unreachable_egeria_applies_nothing(self):
        with patch("resource_explorer.egeria_resync.EgeriaResync") as MockResync:
            instance = MockResync.return_value
            instance.scan.return_value = _scan_result(reachable=False, unreachable_reason="platform down")
            result = scan_and_clear()

        assert result == {"reachable": False, "unreachable_reason": "platform down", "applied": {}}
        instance.apply.assert_not_called()

    def test_no_findings_applies_nothing(self):
        with patch("resource_explorer.egeria_resync.EgeriaResync") as MockResync:
            instance = MockResync.return_value
            instance.scan.return_value = _scan_result()
            result = scan_and_clear()

        assert result == {"reachable": True, "unreachable_reason": "", "applied": {}}
        instance.apply.assert_not_called()

    def test_a_safe_present_finding_gets_applied(self):
        finding = Finding(key="stale_assets", title="t", detail="d",
                           repair_step="clear_stale_assets")
        with patch("resource_explorer.egeria_resync.EgeriaResync") as MockResync:
            instance = MockResync.return_value
            instance.scan.return_value = _scan_result(finding)
            instance.apply.return_value = {"clear_stale_assets": {"cleared": 3}}
            result = scan_and_clear()

        instance.apply.assert_called_once_with(["clear_stale_assets"])
        assert result == {"clear_stale_assets": {"cleared": 3}}

    def test_only_present_safe_steps_are_proposed_not_the_whole_set(self):
        """Regression guard: must not blindly apply all of SAFE_SCHEDULED_STEPS
        regardless of what scan() actually found — only what's present."""
        finding = Finding(key="stale_contexts", title="t", detail="d",
                           repair_step="clear_stale_contexts")
        with patch("resource_explorer.egeria_resync.EgeriaResync") as MockResync:
            instance = MockResync.return_value
            instance.scan.return_value = _scan_result(finding)
            instance.apply.return_value = {}
            scan_and_clear()

        applied_steps = instance.apply.call_args[0][0]
        assert applied_steps == ["clear_stale_contexts"]

    def test_a_needs_decision_finding_is_never_applied_even_if_step_name_matches(self):
        """Defense in depth: even if a future finding reused one of
        SAFE_SCHEDULED_STEPS' step names but set needs_decision=True, this
        must refuse it rather than trust the step name alone."""
        finding = Finding(key="stale_assets", title="t", detail="d",
                           repair_step="clear_stale_assets", needs_decision=True)
        with patch("resource_explorer.egeria_resync.EgeriaResync") as MockResync:
            instance = MockResync.return_value
            instance.scan.return_value = _scan_result(finding)
            result = scan_and_clear()

        instance.apply.assert_not_called()
        assert result == {"reachable": True, "unreachable_reason": "", "applied": {}}

    def test_expensive_findings_are_never_proposed(self):
        """registration_only -> republish_survey_results is EXPENSIVE and
        must never be scheduled, even though it needs_decision=False."""
        finding = Finding(key="registration_only", title="t", detail="d",
                           repair_step="republish_survey_results")
        assert finding.repair_step in EXPENSIVE_STEPS  # sanity on the fixture itself
        with patch("resource_explorer.egeria_resync.EgeriaResync") as MockResync:
            instance = MockResync.return_value
            instance.scan.return_value = _scan_result(finding)
            result = scan_and_clear()

        instance.apply.assert_not_called()
        assert result["applied"] == {}

    def test_a_needs_decision_finding_alongside_a_safe_one_only_applies_the_safe_one(self):
        safe = Finding(key="stale_assets", title="t", detail="d",
                        repair_step="clear_stale_assets")
        blocked = Finding(key="registration_only", title="t", detail="d",
                           repair_step="republish_survey_results")
        with patch("resource_explorer.egeria_resync.EgeriaResync") as MockResync:
            instance = MockResync.return_value
            instance.scan.return_value = _scan_result(safe, blocked)
            instance.apply.return_value = {"clear_stale_assets": {"cleared": 1}}
            scan_and_clear()

        instance.apply.assert_called_once_with(["clear_stale_assets"])

    def test_safe_scheduled_steps_is_a_strict_subset_of_the_non_expensive_non_decision_repairs(self):
        """Guards SAFE_SCHEDULED_STEPS' own construction invariant directly,
        independent of any particular Finding fixture."""
        assert set(SAFE_SCHEDULED_STEPS).isdisjoint(EXPENSIVE_STEPS)


class TestScheduler:
    def test_start_and_stop_do_not_raise(self):
        from resource_explorer import egeria_resync

        with patch.object(egeria_resync, "scan_and_clear", return_value={"reachable": True, "applied": {}}):
            egeria_resync.start_scheduler(interval=3600)
            try:
                assert egeria_resync._thread is not None
                assert egeria_resync._thread.is_alive()
            finally:
                egeria_resync.stop_scheduler()
            assert egeria_resync._thread is None

    def test_a_failed_pass_does_not_kill_the_loop_or_raise(self):
        from resource_explorer import egeria_resync

        with patch.object(egeria_resync, "scan_and_clear", side_effect=RuntimeError("boom")):
            egeria_resync.start_scheduler(interval=3600)
            try:
                assert egeria_resync._thread.is_alive()
            finally:
                egeria_resync.stop_scheduler()

    def test_get_status_reflects_the_last_run(self):
        from resource_explorer import egeria_resync

        stop = MagicMock()
        stop.is_set.side_effect = [False, True]  # run exactly one pass then exit
        with patch.object(egeria_resync, "scan_and_clear",
                           return_value={"reachable": True, "unreachable_reason": "",
                                         "applied": {"clear_stale_assets": {"cleared": 5}}}):
            egeria_resync._loop(3600, stop)

        status = egeria_resync.get_status()
        assert status["last_reachable"] is True
        assert status["last_applied"] == {"clear_stale_assets": {"cleared": 5}}
        assert status["consecutive_failures"] == 0
