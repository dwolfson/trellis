"""Conditional execution: a step that cannot say anything is skipped, loudly.

Before this, every selected step ran. `cve_scan` on a repo with no parsed
dependencies read `project_dependencies`, found nothing, and correctly declined
rather than claiming "no CVEs" — but it was dispatched, timed, published as an
analysis, and counted by `security_summary` among its eight inputs as *never
ran*, pushing the verdict below its floor. A step with nothing to work on still
consumed a slot in every downstream picture.

The whole risk of fixing that is trading one silence for another. These tests
pin the difference: a skip is **emitted with a reason**, never an omission, and
it is kept apart from both "ran" and "failed" because it is neither.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from resource_explorer.surveyors import result_status, step_preconditions as sp


class _Reg:
    def __init__(self, counts, broken=False):
        self._counts, self._broken = counts, broken

    def _conn(self):
        counts, broken = self._counts, self._broken

        class _Conn:
            def execute(self, sql, params):
                if broken:
                    raise RuntimeError("no such table")
                import re
                t = re.search(r"FROM (\w+)", sql).group(1)
                return SimpleNamespace(fetchone=lambda: {"n": counts.get(t, 0)})
            def __enter__(self): return self
            def __exit__(self, *a): return False

        return _Conn()


_P = SimpleNamespace(slug="p")
_CTX = {"has_versioned_dependencies": "cve_scan needs versioned dependencies"}


def test_a_step_with_its_input_present_runs():
    may, name, why = sp.evaluate(_Reg({"project_dependencies": 12}), _P, _CTX)
    assert may is True
    assert name == "" and why == ""


def test_a_step_with_no_input_is_skipped_and_says_why():
    may, name, why = sp.evaluate(_Reg({"project_dependencies": 0}), _P, _CTX)
    assert may is False
    assert name == "has_versioned_dependencies"
    # Three things a reader needs: this step's reason, what was measured, and
    # what to run to fix it.
    assert "cve_scan needs versioned dependencies" in why
    assert "resolved version" in why
    assert "repo_manifest_parse" in why, (
        "the skip does not say which step would satisfy it — that is the reader's "
        "next question and the reason exists to answer it"
    )


def test_an_unreadable_table_runs_the_step_rather_than_skipping_it():
    """Refusing on our own failure would turn "we could not check" into a claim
    about the repository. The step's own absence handling is better than a guess
    made here."""
    may, name, why = sp.evaluate(_Reg({}, broken=True), _P, _CTX)
    assert may is True, "a broken precondition check silently suppressed a step"


def test_an_unknown_precondition_name_runs_the_step(caplog):
    """A typo must not silently disable a step forever. That would be the worst
    outcome available: a step that never runs, for a reason nobody can look up,
    indistinguishable from one with nothing to say."""
    import logging
    with caplog.at_level(logging.ERROR):
        may, name, why = sp.evaluate(
            _Reg({"project_dependencies": 0}), _P, {"has_dependancies": "typo"})
    assert may is True
    assert any("unknown precondition" in r.message for r in caplog.records), (
        "an unknown precondition name was ignored without complaint"
    )


def test_the_skip_status_carries_the_reason_and_the_right_state():
    st = sp.skip_status("has_dependencies", "because there are none")
    assert st["state"] == result_status.SKIPPED_BY_DESIGN
    assert st["hint"] == "because there are none"
    assert st["cause"] == "has_dependencies"
    assert st["known_positive"] is False


def test_every_declared_precondition_exists():
    """A step declaring a name no checker implements would run unconditionally
    while appearing guarded — the guard reading as present is worse than none."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
    declared = {n for info in STEP_REGISTRY.values()
                for n in (getattr(info, "requires_context", None) or {})}
    assert declared, "no step declares a precondition — this test is vacuous"
    unknown = declared - set(sp.PRECONDITIONS)
    assert not unknown, f"declared but not implemented: {sorted(unknown)}"


def test_cve_scan_declares_the_dependency_precondition():
    """The worked example, and the one the backlog entry names."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
    ctx = STEP_REGISTRY["repo_cve_scan"].requires_context
    # `has_versioned_dependencies`, NOT `has_dependencies` — the two come apart,
    # and the difference is the point. Measured 2026-09-01: egeria_git has 216
    # dependency rows and 0 with a version, because Gradle resolves versions
    # through a BOM. `has_dependencies` would pass there and cve_scan would still
    # decline, which is a guard firing on the wrong property — worse than none,
    # because it reads as coverage.
    assert "has_versioned_dependencies" in ctx
    assert "has_dependencies" not in ctx, (
        "gating on dependencies rather than VERSIONED dependencies passes on a "
        "Gradle/BOM repo where cve_scan still cannot query OSV"
    )
    assert ctx["has_versioned_dependencies"].strip(), "a precondition with no reason"


def test_a_skip_is_neither_run_nor_failed():
    """`skipped_steps` is deliberately separate from `steps_run` and
    `step_errors`. A skipped step did not run, so it is not the first; it did not
    fail, so it is not the second. Folding it into either recreates the ambiguity
    SKIPPED_BY_DESIGN exists to remove."""
    from resource_explorer.surveyors.survey_report import SurveyResult
    f = SurveyResult.__dataclass_fields__
    assert "skipped_steps" in f
    assert "steps_run" in f and "step_errors" in f


def test_the_orchestrator_emits_the_skip_rather_than_omitting_it():
    """Asserted against the dispatch site: the skip must add an annotation and
    continue, not merely `continue`."""
    from pathlib import Path
    import resource_explorer.surveyors.survey_orchestrator as mod
    src = Path(mod.__file__).read_text()
    block = src[src.index("_ctx = getattr(_info"):]
    block = block[:block.index("log.info(\"Running")]
    assert "result.add(" in block, "the skip does not emit an annotation"
    assert "skip_status" in block, "the skip does not carry a status"
    assert "result.skipped_steps[" in block, "the skip is not recorded on the result"
    assert "continue" in block

def test_a_skip_actually_executes_end_to_end_through_the_orchestrator(monkeypatch, tmp_path):
    """Forces the branch to RUN, rather than reading the source for it.

    The source-reading test below passed while `ClassificationAnnotation` was not
    imported in that module — a NameError that fires only when a step is actually
    skipped. A survey where nothing is skipped is green; the first real
    precondition miss raises mid-run. The feature works until the moment it does
    something, which is the least useful failure timing available, so the branch
    has to be executed to be checked at all.
    """
    from resource_explorer.registry import Project, ProjectRegistry
    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="skiptest", display_name="Skip Test",
                    github_url="https://github.com/o/r", description=""))

    # cve_scan only: the one step that declares a precondition, on a registry
    # where project_dependencies is genuinely empty.
    result = SurveyOrchestrator(reg).run("skiptest", steps=["repo_cve_scan"])

    assert "repo_cve_scan" in result.skipped_steps, (
        f"the step was not skipped; skipped={result.skipped_steps}, "
        f"errors={result.errors}"
    )
    reason = result.skipped_steps["repo_cve_scan"]
    assert "repo_manifest_parse" in reason

    skips = [a for a in result.annotations
             if result_status.SKIPPED_BY_DESIGN in (getattr(a, "candidate_classifications", []) or [])]
    assert skips, "the skip produced no annotation — it is an omission, not a result"
    ann = skips[0]
    assert ann.confidence == 0
    assert ann.json_properties.get("state") == result_status.SKIPPED_BY_DESIGN
    assert ann.json_properties.get("hint"), "the annotation carries no reason"
    assert "repo_cve_scan" not in (result.steps_run or []), (
        "a skipped step was recorded as run"
    )
    assert "repo_cve_scan" not in (result.step_errors or {}), (
        "a skipped step was recorded as an error"
    )

