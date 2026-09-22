"""DB/FS gate removal in /next (re/next-db-fs-gate-removal, 2026-09-22).

The project owner reversed the earlier "DB and FS stay out of /next" ruling
(docs/design-notes/COORDINATOR-BRIEF-MULTI-RESOURCE.md, 2026-09-20) — see
docs/Backlog.md's reversal entry. This slice:

  - relaxes `paneNeedsRepo()` so Survey no longer blocks db/filesystem (its
    backend, `/api/survey-definitions/{entity_type}/...`, is genuinely
    resource-type-generic);
  - replaces the old blanket "Repos only, in /next" message on By analysis,
    Disposition and the Questions checklist with `paneNeedsRepoBackend()`,
    which is honest about WHY those three stay repo-only today — a verified
    backend gap (repo-keyed routes/tables), not an unbuilt /next UI;
  - fixes two silent-wrong-data hardcodes: `automate.js`'s subscription
    filter and `worklist.js`'s analysis-menu lookup both ignored the actual
    selected/work-list resource type and always asked for 'repo'.

No browser verification with a signed-in session is asserted by these tests
-- see test_next_discovery_import_search.py's identical rationale. These
tests grep/slice the concatenated source, the established pattern for
/next JS modules without a browser.
"""
from __future__ import annotations

from pathlib import Path

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"


def _app():
    return (NEXT / "app.js").read_text(encoding="utf-8")


def _worklist_src():
    return (NEXT / "worklist.js").read_text(encoding="utf-8")


def _automate_src():
    return (NEXT / "stages" / "automate.js").read_text(encoding="utf-8")


class TestPaneNeedsRepoNoLongerBlanketBlocksNonRepo:
    """`paneNeedsRepo()` used to return the "Repos only, in /next" message
    for ANY non-repo resourceType, unconditionally -- including Survey,
    whose backend (getSurveyCandidates/runSurveyDefinition, both
    /api/survey-definitions/{entity_type}/...) never needed repo at all."""

    def test_pane_needs_repo_no_longer_gates_on_resource_type(self):
        # It may still use state.resourceType for the "pick a ..." wording,
        # but must no longer branch on `!== 'repo'` to block the pane.
        src = _app()
        start = src.index("function paneNeedsRepo() {")
        end = src.index("\n}", start)
        body = src[start:end]
        assert "resourceType !== 'repo'" not in body
        assert "Repos only" not in body

    def test_survey_pane_calls_the_relaxed_helper_not_the_backend_gate(self):
        src = _app()
        start = src.index("async function loadSurveyPane() {")
        end = src.index("\n}", start)
        body = src[start:end]
        assert "paneNeedsRepo()" in body
        assert "paneNeedsRepoBackend" not in body

    def test_survey_candidates_call_threads_the_real_resource_type(self):
        src = _app()
        assert "getSurveyCandidates(slug, { entityType: state.resourceType" in src
        assert "getSurveyCandidates(slug, { phase: state.stage })" not in src

    def test_run_survey_definition_call_threads_the_real_resource_type(self):
        src = _app()
        assert "runSurveyDefinition(slug, ref, { entityType: state.resourceType })" in src


class TestPaneNeedsRepoBackendIsHonestNotBlanket:
    """By analysis, Disposition and the Questions checklist stay repo-only,
    but the message must say a real, verified backend reason -- never the
    old undifferentiated 'Repos only, in /next' wording, which reads as an
    arbitrary /next limitation rather than the real one."""

    def test_backend_gate_helper_exists_and_still_gates_non_repo(self):
        src = _app()
        assert "function paneNeedsRepoBackend(" in src
        start = src.index("function paneNeedsRepoBackend(")
        end = src.index("\n}", start)
        body = src[start:end]
        assert "state.resourceType !== 'repo'" in body

    def test_old_undifferentiated_message_is_gone(self):
        src = _app()
        assert "Repos only, in /next" not in src

    def test_disposition_pane_uses_the_backend_gate(self):
        src = _app()
        start = src.index("async function loadDispositionPane() {")
        end = src.index("\n}", src.index("await renderRecords(slug);", start))
        body = src[start:end]
        assert "paneNeedsRepoBackend('Disposition'" in body

    def test_by_analysis_pane_uses_the_backend_gate(self):
        src = _app()
        start = src.index("async function loadByAnalysisPane() {")
        end = src.index("\n}", start + 2000)
        body = src[start:end]
        assert "paneNeedsRepoBackend('By analysis'" in body

    def test_questions_pane_no_longer_has_its_own_separate_guard(self):
        # The duplicate inline "Repos only, in /next" guard this pane used to
        # carry independently of paneNeedsRepo() is gone, replaced by a call
        # to the same shared helper everything else uses.
        src = _app()
        assert "paneNeedsRepoBackend('Questions checklist'" in src


class TestAutomateNoLongerHardcodesRepo:
    def test_subscription_filter_threads_state_resource_type(self):
        src = _automate_src()
        assert "entityType: state.resourceType" in src
        assert "entityType: 'repo'" not in src


class TestWorklistNoLongerHardcodesRepo:
    def test_analysis_menu_reads_the_work_lists_own_entity_type(self):
        src = _worklist_src()
        assert "listAnalyses(wl.entity_type || 'repo'" in src
        assert "listAnalyses('repo'" not in src
