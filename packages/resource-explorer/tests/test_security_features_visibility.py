"""An empty security-features card has three causes; say which.

GitHub returns `security_and_analysis` ONLY to callers with admin access to the
repository. For a third-party repo it comes back empty however many times the
step runs — the analysis is not failing, it is **structurally impossible**,
which is a fact about GitHub's API rather than about the run or the repository.

Measured 2026-08-25 across the real 60-repo corpus: 2 repos have findings and
both are the operator's own. The other 58 rendered as an empty card
indistinguishable from a repository with security features switched off.

Three causes, three states:
    findings present          -> measured
    stats but nothing visible -> skipped_by_design, with the reason
    no stats at all           -> never_run
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors import result_status
from resource_explorer.surveyors.repo_survey_definition_adapter import ANALYSIS_KINDS

#: Asserts over whatever the LIVE shared registry HOLDS, not over fixtures.
#: That is the point — "58 of 60 real repos render an empty security-features
#: card" is a fact no fixture would have produced — and it is also why these are
#: opt-in: five sessions share one Postgres, and a peer running a survey can turn
#: them red in a file nobody touched (measured 2026-08-30, when a concurrent
#: survey of egeria_workspaces_git caught it mid-run).
#:
#: Run with `pytest --corpus` when the corpus is quiet, which is the only time
#: their answer means anything.
pytestmark = pytest.mark.corpus


READER = ANALYSIS_KINDS["security_features"].results.results_reader


class _Reg:
    def __init__(self, stats=None, findings=()):
        self._stats, self._findings = stats, list(findings)

    def query_findings(self, slug, kind):
        return self._findings

    def get_latest_project_stats(self, slug):
        return self._stats


def test_a_third_party_repo_says_why_it_can_see_nothing():
    out = READER(_Reg(stats={"security_and_analysis_json": "{}"}), "someone-elses-repo")
    assert out["findings"] == []
    st = out["_status"]
    assert st["state"] == result_status.SKIPPED_BY_DESIGN
    joined = " ".join(str(v) for v in st.values())
    assert "admin" in joined, "the reason must name the actual cause"
    assert "Not a gap in the repository" in joined, (
        "a skip that reads as a shortfall pushes someone to 'fix' a repository "
        "that has nothing wrong with it"
    )


def test_never_fetched_is_not_the_same_as_invisible():
    out = READER(_Reg(stats=None), "unsurveyed")
    assert out["_status"]["state"] == result_status.NEVER_RUN


def test_visible_but_nothing_enabled_is_a_real_answer():
    """Admin access and every feature off is a genuine finding of 'none', and
    must NOT be dressed up as a skip — that would hide a real security posture
    behind an excuse."""
    out = READER(_Reg(stats={"security_and_analysis_json": '{"advanced_security": null}'}), "mine")
    assert out["findings"] == []
    assert "_status" not in out or out.get("_status", {}).get("state") != result_status.SKIPPED_BY_DESIGN


def test_no_repo_in_the_corpus_renders_a_bare_empty_card():
    """The point of the change, asserted against real data: every empty card
    states a cause."""
    from resource_explorer.registry import ProjectRegistry

    reg = ProjectRegistry()
    projects = reg.list_all()
    if not projects:
        pytest.skip("no registered repos")
    bare = [
        p.slug for p in projects
        if not READER(reg, p.slug).get("findings") and not READER(reg, p.slug).get("_status")
    ]
    assert not bare, f"empty security-features card with no stated cause: {bare[:5]}"


def test_a_status_envelope_is_not_counted_as_data():
    """Regression: explaining an emptiness must not make it look non-empty.

    `_results_have_data` recursed into every value, so attaching a `_status`
    envelope to an empty payload made the card claim it held results. The card
    would then be shown as having data and render an explanation of nothing —
    the precise inversion of what that function exists to prevent.

    Latent before this change (no reader attached a status to a fully empty
    payload); adding one to security_features exposed it. It would have bitten
    the next reader to do the same, which is every reader that adopts the
    result_status vocabulary.
    """
    from resource_explorer.web.routes.projects import _results_have_data

    assert _results_have_data({"findings": [], "_status": {"state": "skipped_by_design",
                                                           "hint": "a long explanation"}}) is False
    assert _results_have_data({"findings": [], "surveyed_at": "2026-08-25T00:00:00"}) is False
    assert _results_have_data({"findings": [{"check_name": "x"}], "_status": {}}) is True


def test_a_bare_never_run_state_is_not_counted_as_data():
    """Regression, 2026-08-31: architecture_summary/architecture_doc_lens's
    never-run shape is `{"state": "never_run", "message": "..."}` -- a bare
    top-level `state`, not wrapped in `_status`. The explanatory `message` is
    non-empty text, so the general envelope exclusion above didn't catch it
    until wiring these three into a dashboard for the first time exposed it
    (docs/Backlog.md "Survey Results dashboards cover 14 of 29 analyses").

    `nothing_found` must NOT be excluded the same way -- result_status.py's
    own ladder calls it "a real, final answer", not an absence, and hiding it
    here would be the exact inversion this function exists to prevent."""
    from resource_explorer.web.routes.projects import _results_have_data

    assert _results_have_data(
        {"state": "never_run", "message": "No architecture summary yet — run the analysis."}
    ) is False
    assert _results_have_data(
        {"state": "nothing_found", "message": "The architecture documentation was consulted "
                                               "and named nothing."}
    ) is True


def test_architecture_recoverys_doc_ingestion_field_is_not_counted_as_data():
    """Regression, 2026-08-31: architecture_recovery decorates every response
    with `{"documentation": {"state": "not-attempted", "detail": ""}}` — the
    documentation-SITE ingestion status, carried for unrelated presentation
    reasons (_doc_ingestion_state), never the recovery analysis's own
    findings. A never-surveyed repo's otherwise-all-empty/zero payload read
    as "has data" purely because of this nested field."""
    from resource_explorer.web.routes.projects import _results_have_data

    assert _results_have_data({
        "components": [], "component_count": 0,
        "documentation": {"state": "not-attempted", "detail": ""},
    }) is False
