"""The refresh planner — a reducer pointed forwards, and the states it must keep apart.

`security_summary` sits at the end of a survey and reads what the other steps
wrote. This sits at the front and reads stored *state* to say what the run needs.
Same mechanism, opposite direction.

Every test here corresponds to a way a plan could be confidently wrong, not to a
feature. The two that matter most are the ones a simpler design would have got
wrong for free: a survey-wide SHA gate collapses `never_run` into `current`, and
an unreachable GitHub collapses `unknown` into `current`.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from resource_explorer.surveyors.sub_surveyors import refresh_plan as rp

PKG = Path(rp.__file__).resolve().parents[2]
DOC = (PKG.parent / "docs" / "dr-egeria" / "survey-definitions"
       / "repo-survey-definition-refresh.md")


class _Reg:
    """A registry whose row counts are dictated by the test."""

    def __init__(self, counts):
        self._counts = counts

    def _conn(self):
        counts = self._counts

        class _Cur:
            def __init__(self, n): self._n = n
            def fetchone(self): return {"n": self._n}

        class _Conn:
            def execute(self, sql, params):
                m = re.search(r"FROM (\w+)", sql)
                return _Cur(counts.get(m.group(1), 0))
            def __enter__(self): return self
            def __exit__(self, *a): return False

        return _Conn()


def _project(sha="aaaaaaaa"):
    return SimpleNamespace(slug="p", github_url="https://github.com/o/r",
                           last_commit_sha=sha)


ALL_POPULATED = {"project_file_inventory": 10, "project_dependencies": 10}


def _by_check(findings):
    return {f["check_name"]: f for f in findings}


def test_unchanged_head_reports_current():
    got = _by_check(rp.plan(_Reg(ALL_POPULATED), _project("abc123"), "abc123", ""))
    assert got["repo_file_inventory"]["label"] == "current"
    assert got["refresh_needed"]["label"] == "no"


def test_moved_head_reports_stale():
    got = _by_check(rp.plan(_Reg(ALL_POPULATED), _project("abc123"), "def456", ""))
    assert got["repo_file_inventory"]["label"] == "stale"
    assert got["refresh_needed"]["label"] == "yes"
    assert "abc123"[:8] in got["repo_file_inventory"]["summary"]


def test_never_run_is_not_current_even_when_the_head_has_not_moved():
    """The trap a survey-wide SHA gate falls into.

    `IncrementalIndexer.refresh` already knows this — on its no-change path it
    still profiles data files if that was never done. "Unchanged" and "complete"
    are different questions, so the gate has to be per target.
    """
    reg = _Reg({"project_file_inventory": 10, "project_dependencies": 0})
    got = _by_check(rp.plan(reg, _project("abc123"), "abc123", ""))

    assert got["repo_file_inventory"]["label"] == "current"
    assert got["repo_manifest_parse"]["label"] == "never_run", (
        "an empty table with an unchanged head was reported as current — "
        "that is work never done, being skipped forever"
    )
    assert got["refresh_needed"]["label"] == "yes"


def test_an_unreadable_head_is_unknown_not_current():
    """"Could not ask GitHub" and "nothing changed" are different facts, and only
    one of them is about the repository. Reporting the second would be a claim
    about someone's repo derived from our own connectivity."""
    got = _by_check(rp.plan(_Reg(ALL_POPULATED), _project("abc123"), "", "HTTPError: 503"))
    assert got["repo_file_inventory"]["label"] == "unknown"
    assert got["repo_file_inventory"]["confidence"] == 0
    assert got["repo_file_inventory"]["detail"]["known"] is False
    assert got["refresh_needed"]["label"] == "unknown"
    assert "503" in got["refresh_needed"]["summary"]


def test_a_repo_never_indexed_against_any_commit_is_stale_not_current():
    """Empty `last_commit_sha` must not compare equal to a real head."""
    got = _by_check(rp.plan(_Reg(ALL_POPULATED), _project(""), "abc123", ""))
    assert got["repo_file_inventory"]["label"] == "stale"


def test_the_verdict_says_it_is_advisory():
    """The whole risk of a plan is being read as an action. "Nothing to refresh"
    must not be mistaken for "nothing ran" — the executor runs every step in the
    graph regardless of what this says."""
    got = _by_check(rp.plan(_Reg(ALL_POPULATED), _project("abc123"), "abc123", ""))
    assert "ADVISORY" in got["refresh_needed"]["summary"]
    assert got["refresh_needed"]["detail"]["advisory_only"] is True


def test_head_sha_never_raises():
    """A planner that raises takes the whole survey down before any step runs."""
    class _Boom:
        def get_repo(self, url): raise RuntimeError("network gone")
    sha, err = rp.head_sha(_project(), client=_Boom())
    assert sha == ""
    assert "RuntimeError" in err


# ── wiring ───────────────────────────────────────────────────────────────────

def test_the_planner_runs_first_in_the_refresh_survey():
    """A plan produced after the run it was meant to plan is useless. This is the
    mirror of `security_summary`, which must run last."""
    if not DOC.exists():  # pragma: no cover
        pytest.skip(f"{DOC} not generated")
    steps = re.findall(r"\| re_analysis_step \| (\S+) \|", DOC.read_text())
    assert steps, "no steps parsed"
    assert steps[0] == "repo_refresh_plan", f"planner is not first: {steps}"


def test_the_planner_runs_first_in_the_full_survey_too():
    """"Repo Full Survey" is generated from the `*` sentinel — STEP_REGISTRY's own
    order — so the entry's position in that dict IS its chain position. Placed
    beside the other reducer it landed at index 34 of 36, planning a run that had
    already happened."""
    doc = DOC.parent / "repo-survey-definition-full.md"
    if not doc.exists():  # pragma: no cover
        pytest.skip("full survey not generated")
    steps = re.findall(r"\| re_analysis_step \| (\S+) \|", doc.read_text())
    assert steps[0] == "repo_refresh_plan", f"planner is at index {steps.index('repo_refresh_plan')}"
    assert steps[-1] == "repo_rag_ingestion", "rag_ingestion must stay last"


def test_it_is_registered_as_a_step_and_an_analysis():
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        ANALYSIS_KINDS, STEP_REGISTRY)
    assert "repo_refresh_plan" in STEP_REGISTRY
    assert list(STEP_REGISTRY)[0] == "repo_refresh_plan", (
        "position in STEP_REGISTRY is position in Full Survey's chain"
    )
    assert ANALYSIS_KINDS["refresh_plan"].step_keys == ["repo_refresh_plan"]


def test_the_refresh_survey_covers_the_four_targets():
    if not DOC.exists():  # pragma: no cover
        pytest.skip("not generated")
    steps = set(re.findall(r"\| re_analysis_step \| (\S+) \|", DOC.read_text()))
    for t in rp.TARGETS:
        assert t["step"] in steps, (
            f"{t['step']} is planned for but not in the survey — the plan would "
            "report on a target the survey never runs"
        )
