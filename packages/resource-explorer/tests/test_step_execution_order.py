"""Producers must precede consumers in STEP_REGISTRY.

`SurveyOrchestrator.run()` executes `list(all_surveyors.items())` — plain
insertion order over `STEP_REGISTRY`. So a step that reads what another step
writes only works because of where it happens to sit in a dict literal. Nothing
declares the relationship and nothing checks it, which means a reorder, or a new
step inserted in the obvious-looking place, would break a chain with **no test
failing and no error raised** — the consumer would simply read the PREVIOUS
run's data and report a confident, stale answer.

That failure would be invisible in exactly the way the rest of this codebase's
worst bugs have been: `cve_scan` reading zero dependencies does not crash, it
declines to report, and a declining check looks identical to a clean one.

Written 2026-09-01 after the order was *wrongly reported as broken*. The
positions had been read off `ANALYSIS_KINDS` — which is keyed by analysis id and
is not the execution order — instead of `STEP_REGISTRY`. `repo_manifest_parse`
sits at 3, not 24, and the chain has been correct all along. This file exists so
that the next person does not have to re-derive that by hand, and so the answer
cannot quietly stop being true.

Verified live the same night: one full survey of `amundsen` produced 880
dependency rows AND 8 cve_scan findings in the same run.
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

#: (producer, consumer, what actually flows). Every entry was established by
#: reading the two steps' registry calls, not by assuming a name relationship.
#:
#: `repo_manifest_parse` calls upsert_dependencies(); `repo_cve_scan` and
#: `repo_dependency` both call query_dependencies(). A CVE scan that runs first
#: sees an empty table and correctly declines — so the cost of getting this
#: wrong is a security metric silently capped, not a crash.
DATA_DEPENDENCIES = [
    ("repo_manifest_parse", "repo_cve_scan", "project_dependencies"),
    ("repo_manifest_parse", "repo_dependency", "project_dependencies"),
]

#: security_summary's INPUT_KINDS, mapped to the step that writes each. It reads
#: them via query_findings() and treats an empty list as "never ran" rather than
#: "ran and found nothing" — a distinction its own docstring is explicit about —
#: so a producer running after it is not a wrong number but a missing input, and
#: below MIN_INPUTS_FOR_VERDICT it withholds a verdict entirely.
SUMMARY_INPUT_PRODUCERS = {
    "security_hygiene":       "repo_security",
    "security_features":      "repo_security_features",
    "ci_quality":             "repo_ci_quality",
    "license_classification": "repo_license_classification",
    "repo_conventions":       "repo_conventions",
    "foss_scorecard":         "repo_foss_scorecard",
    "cii_badge":              "repo_cii_badge",
    "cve_scan":               "repo_cve_scan",
}


def _position(step_key: str) -> int:
    keys = list(STEP_REGISTRY)
    assert step_key in keys, f"{step_key} is not in STEP_REGISTRY"
    return keys.index(step_key)


@pytest.mark.parametrize("producer,consumer,what", DATA_DEPENDENCIES)
def test_producer_runs_before_consumer(producer, consumer, what):
    assert _position(producer) < _position(consumer), (
        f"{consumer} reads {what}, which {producer} writes, but {producer} now runs "
        f"AFTER it. The consumer will read the previous run's data and report a "
        f"stale answer without failing.")


def test_security_summary_runs_after_every_input_it_declares():
    """`after all its inputs`, not `last`.

    Only the first is the real requirement, and the distinction is not
    academic: repo_security_summary is terminal in RepoAssessmentSurvey but NOT
    in RepoFullSurvey, where repo_rag_ingestion stays last because it is the
    most expensive step and nothing reads it. "Runs last" passed under two
    different WRONG arrangements on 2026-08-31.
    """
    summary = _position("repo_security_summary")
    late = {kind: p for kind, p in
            ((k, _position(s)) for k, s in SUMMARY_INPUT_PRODUCERS.items())
            if p > summary}
    assert not late, (
        f"security_summary runs at {summary} but these inputs are produced after "
        f"it: {late}. It reads an absent finding as 'never ran' and withholds a "
        f"verdict below MIN_INPUTS_FOR_VERDICT, so this silently degrades the "
        f"security picture rather than failing.")


def test_the_input_map_matches_the_step_it_claims_to_track():
    """Guards the map above against drifting from security_summary's own list.

    Without this, a kind added to INPUT_KINDS is simply not checked, and the
    ordering test keeps passing while covering less than it claims to — a check
    quietly narrowing is worse than one that fails.
    """
    from resource_explorer.surveyors.sub_surveyors.security_summary import INPUT_KINDS

    assert set(INPUT_KINDS) == set(SUMMARY_INPUT_PRODUCERS), (
        "INPUT_KINDS and SUMMARY_INPUT_PRODUCERS disagree — update the map, "
        "otherwise the ordering test silently stops covering the new kind.")


def test_the_check_can_actually_fail():
    """The known-negative: the assertion must reject a reversed order.

    Without this, every test above passes for a comparison that is never false.
    """
    keys = list(STEP_REGISTRY)
    a, b = keys.index("repo_cve_scan"), keys.index("repo_manifest_parse")
    with pytest.raises(AssertionError):
        assert a < b, "deliberately reversed"
