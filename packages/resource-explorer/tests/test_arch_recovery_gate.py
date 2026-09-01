"""`repo_classification`'s architecture_recovery_gate is now honoured.

The gate was computed and stored and nothing read it. Measured 2026-08-31
across the corpus: 45 repos gated `run`, 8 gated `skip` — and `monocle`, gated
`skip` for "samples role present and no structural evidence", carried 405
architecture findings. The classification did its job; nothing acted on it.

Dan, 2026-08-31: "if the repo doesn't hold code artifacts we don't try to run
an architecture discovery on it" — and, separately, "we should let them
decide". Both are true at once, which is why the gate is advisory: it changes
the default, not the permission.
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors.sub_surveyors.arch_recovery_detect import ArchDetectSurveyor


class _Proj:
    slug = "course_material"
    github_url = "https://github.com/o/course-material"


class _Reg:
    def __init__(self, gate_label=None, gate_summary=""):
        self._label, self._summary = gate_label, gate_summary

    def query_findings(self, slug, kind, scope=""):
        if kind != "repo_classification" or self._label is None:
            return []
        return [{"check_name": "architecture_recovery_gate", "label": self._label,
                 "summary": self._summary, "surveyed_at": "2026-08-31T00:00:00"}]


def _run(reg, **kw):
    return ArchDetectSurveyor(_Proj(), reg, local_path=None, **kw).run()


class TestASkipIsADeliberateStateNotAnEmptyResult:
    def test_a_gated_repo_is_not_surveyed(self):
        anns = _run(_Reg("skip", "tutorial role present and no structural evidence"))
        assert len(anns) == 1
        props = anns[0].resource_properties
        assert props["gated"] is True
        assert props["component_count"] == 0
        assert "skipped" in anns[0].summary.lower()

    def test_the_reason_travels_with_the_skip(self):
        # "Skipped" without a reason is indistinguishable from a failure on the
        # screen — the same complaint result_status.skipped() exists to answer.
        reason = "tutorial role present and no structural evidence"
        anns = _run(_Reg("skip", reason))
        assert reason in anns[0].resource_properties["gate_reason"]
        assert reason in anns[0].summary

    def test_it_reports_skipped_by_design_not_nothing_found(self):
        # A gated repo did not look and find nothing; it did not look. Folding
        # those together is the confident-wrong-answer this codebase keeps
        # finding, in the one place with a vocabulary built to prevent it.
        from resource_explorer.surveyors import result_status

        anns = _run(_Reg("skip", "no structural evidence"))
        status = anns[0].json_properties
        assert status["state"] == result_status.SKIPPED_BY_DESIGN


class TestTheGateIsAdvisory:
    def test_an_explicit_run_overrides_it(self):
        # "We should let them decide" — a user who wants the answer for a
        # tutorial repo is entitled to it. Reaching the no-checkout branch
        # proves the gate did not short-circuit.
        anns = _run(_Reg("skip", "no structural evidence"), respect_gate=False)
        assert not any(a.resource_properties.get("gated") for a in anns
                       if hasattr(a, "resource_properties"))

    def test_a_run_verdict_does_not_skip(self):
        anns = _run(_Reg("run", "structural evidence found"))
        assert not any(getattr(a, "resource_properties", {}).get("gated") for a in anns)


class TestAbsenceIsNotAVerdict:
    def test_a_never_classified_repo_runs(self):
        # An unrun prerequisite must not look like a decision about the repo.
        anns = _run(_Reg(gate_label=None))
        assert not any(getattr(a, "resource_properties", {}).get("gated") for a in anns)

    def test_a_registry_that_raises_does_not_block_the_survey(self):
        class _Boom:
            def query_findings(self, *a, **k):
                raise RuntimeError("db down")

        anns = _run(_Boom())
        assert not any(getattr(a, "resource_properties", {}).get("gated") for a in anns)
