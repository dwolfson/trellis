"""The security topic summary — a reducer, and the ways a summary lies.

A one-word verdict is the most quotable thing this system produces and the
easiest to produce wrongly. Each test here corresponds to a specific way the
summary could be confidently wrong rather than to a feature.

Two of them exist because the bug happened while writing this step, not in
theory: `INPUT_KINDS` and `PRECEDENCE` were both written with the *analysis id*
`security_scan` instead of the findings kind `security_hygiene`. The first
failure was visible — "security_scan never ran" for every repo. The second was
not: it silently produced zero supersessions, so the summary looked like it had
found no overlapping checks when it had been looking for a kind nobody writes.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from resource_explorer.surveyors.sub_surveyors import security_summary as ss

#: the `resource_explorer` package directory itself
PKG = Path(ss.__file__).resolve().parents[2]
DOC = (PKG.parent / "docs" / "dr-egeria" / "survey-definitions"
       / "repo-survey-definition-assessment.md")


def _rows(*specs):
    """(check_name, label, surveyed_at) → finding rows as the registry returns them."""
    return [{"check_name": c, "label": l, "summary": "", "confidence": 100,
             "detail_json": "{}", "surveyed_at": t, "scope_locator": ""}
            for c, l, t in specs]


# ── the typo class ───────────────────────────────────────────────────────────

def test_every_input_kind_is_a_declared_findings_kind():
    """A name nobody writes is indistinguishable from an analysis that never ran.

    Checked against `check_registry.yaml`, which is the project's own declared
    vocabulary for this — and which already warned about the exact mistake this
    step shipped with. Its header lists the three analyses whose findings kind
    differs from their catalog id, `security_scan -> security_hygiene` first
    among them, verified against the live registry on 2026-08-24. The hazard was
    documented; the step walked into it anyway, which is why the guard is a test
    rather than a comment.
    """
    import yaml
    reg = yaml.safe_load((PKG / "configdata" / "check_registry.yaml").read_text())
    declared = {a.get("findings_kind") for a in (reg.get("analyses") or {}).values()}
    declared |= set(reg.get("whole_analysis_only") or [])
    declared |= set(reg.get("instance_keyed_not_checks") or [])
    assert len(declared) > 10, (
        f"only {len(declared)} kinds parsed from check_registry.yaml — the "
        "shape changed and this test would pass vacuously"
    )
    for kind in ss.INPUT_KINDS:
        assert kind in declared, (
            f"INPUT_KINDS names {kind!r}, which is not a declared findings kind. "
            "It can never be present, so the summary reports it as 'never ran' "
            "forever — see check_registry.yaml's header on id-vs-kind drift"
        )


def test_precedence_uses_findings_kinds_not_analysis_ids():
    """The same mistake in PRECEDENCE fails silently: zero supersessions, which
    looks exactly like 'no two checks overlap'."""
    for (weak_kind, _), (strong_kind, _) in ss.PRECEDENCE:
        assert weak_kind in ss.INPUT_KINDS, (
            f"{weak_kind!r} is not an input kind, so this precedence rule can "
            "never fire and its absence is invisible"
        )
        assert strong_kind in ss.INPUT_KINDS, strong_kind


# ── absence ──────────────────────────────────────────────────────────────────

def test_never_ran_is_not_counted_as_clean():
    """The failure that makes a summary dangerous: four missing inputs reported
    as a clean bill of health."""
    got = ss.summarise({"present": {}, "missing": list(ss.INPUT_KINDS)})
    assert got["known"] is False
    assert got["label"] == ""
    assert "only 0 of" in got["summary"]
    assert got["counts"]["good"] == 0


def test_a_verdict_is_refused_below_the_floor():
    present = {k: _rows(("c", "pass", "2026-08-30T00:00:00"))
               for k in ss.INPUT_KINDS[:ss.MIN_INPUTS_FOR_VERDICT - 1]}
    got = ss.summarise({"present": present,
                        "missing": list(ss.INPUT_KINDS[ss.MIN_INPUTS_FOR_VERDICT - 1:])})
    assert got["known"] is False, "graded a repository on a minority of its inputs"
    assert "would be a verdict on absence" in got["summary"]


def test_a_verdict_names_what_did_not_run():
    present = {k: _rows(("c", "pass", "2026-08-30T00:00:00")) for k in ss.INPUT_KINDS[:7]}
    got = ss.summarise({"present": present, "missing": [ss.INPUT_KINDS[7]]})
    assert got["known"] is True
    assert ss.INPUT_KINDS[7] in got["summary"], (
        "a verdict was issued without saying which input is missing from it"
    )


def test_an_unrecognised_label_counts_as_neither_good_nor_bad():
    """Counting an unknown label as clean is how a new check silently improves
    every score it appears in."""
    present = {k: _rows(("c", "wat", "2026-08-30T00:00:00")) for k in ss.INPUT_KINDS[:5]}
    counts = ss.summarise({"present": present, "missing": []})["counts"]
    assert counts == {"good": 0, "bad": 0, "unknown": 5}, counts


# ── staleness ────────────────────────────────────────────────────────────────

def test_the_summary_carries_the_age_of_its_oldest_input_not_its_own():
    """It summarises the latest sighting of each input, and those can be days
    apart — so its own timestamp is newer than some of its evidence."""
    present = {
        ss.INPUT_KINDS[0]: _rows(("c", "pass", "2020-01-01T00:00:00")),
        ss.INPUT_KINDS[1]: _rows(("c", "pass", "2026-08-30T00:00:00")),
        ss.INPUT_KINDS[2]: _rows(("c", "pass", "2026-08-30T00:00:00")),
        ss.INPUT_KINDS[3]: _rows(("c", "pass", "2026-08-30T00:00:00")),
    }
    got = ss.summarise({"present": present, "missing": []})
    assert got["oldest_input_at"].startswith("2020"), (
        "reported the newest input's age, which hides exactly the stale evidence "
        "the field exists to surface"
    )
    assert got["oldest_input_age_days"] > 1000
    assert got["is_state_summary"] is True


# ── precedence ───────────────────────────────────────────────────────────────

def _precedence_fixture(weak_label, strong_label):
    (wk, wc), (sk, sc) = ss.PRECEDENCE[0]
    present = {
        wk: _rows((wc, weak_label, "2026-08-30T00:00:00")),
        sk: _rows((sc, strong_label, "2026-08-30T00:00:00")),
    }
    for k in ss.INPUT_KINDS:
        present.setdefault(k, _rows(("other", "pass", "2026-08-30T00:00:00")))
    return {"present": present, "missing": []}


def test_the_weaker_check_is_not_counted_when_a_stronger_one_ran():
    """Both counted would double-count one question, and the weaker would drag a
    correct answer toward 'concerns'."""
    got = ss.summarise(_precedence_fixture("gap", "pass"))
    assert got["supersessions"], "precedence did not fire"
    s = got["supersessions"][0]
    assert s["agree"] is False, "a gap and a pass were recorded as agreeing"
    # The weak 'gap' must not appear in the bad count.
    only_others = ss.summarise({
        "present": {k: _rows(("other", "pass", "2026-08-30T00:00:00")) for k in ss.INPUT_KINDS},
        "missing": [],
    })
    assert got["counts"]["bad"] == only_others["counts"]["bad"], (
        "the superseded weaker finding was still counted against the repository"
    )


def test_precedence_needs_both_sides_to_have_run():
    """A stronger check that never ran supersedes nothing — claiming otherwise
    credits the summary with evidence it does not have."""
    (wk, wc), _ = ss.PRECEDENCE[0]
    present = {k: _rows(("other", "pass", "2026-08-30T00:00:00")) for k in ss.INPUT_KINDS}
    present[wk] = _rows((wc, "gap", "2026-08-30T00:00:00"))
    del present[ss.PRECEDENCE[0][1][0]]
    got = ss.summarise({"present": present, "missing": [ss.PRECEDENCE[0][1][0]]})
    assert got["supersessions"] == []


# ── wiring ───────────────────────────────────────────────────────────────────

def test_the_reducer_runs_last_in_the_assessment_survey():
    """It reads what the other steps wrote. Anywhere but last and it summarises
    the previous run's data while reporting this one's."""
    if not DOC.exists():  # pragma: no cover
        pytest.skip(f"{DOC} not generated")
    steps = re.findall(r"\| re_analysis_step \| (\S+) \|", DOC.read_text())
    assert steps, "no steps parsed from the generated Assessment Survey"
    assert steps[-1] == "repo_security_summary", (
        f"the reducer is not the last step: {steps}"
    )
    # And nothing may follow it in the chain.
    assert "### Governance Action Process Step\nGovActionProcessStep::RepoAssessmentSurvey::repo_security_summary" \
        not in DOC.read_text(), "a step follows the reducer"


def test_it_is_registered_as_a_step_and_an_analysis():
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        ANALYSIS_KINDS, STEP_REGISTRY)
    assert "repo_security_summary" in STEP_REGISTRY
    assert "security_summary" in ANALYSIS_KINDS
    assert ANALYSIS_KINDS["security_summary"].step_keys == ["repo_security_summary"]
