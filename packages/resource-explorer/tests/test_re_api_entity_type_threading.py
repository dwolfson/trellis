"""Source-level regression tests for re-api.js's entity-type threading fixes
(Tier 1 audit, 2026-09-23) -- no JS test runner is wired into this suite, so
these pin the fix at the source level, the same technique
test_fact_answer_rendering.py uses for index.html.

Covers:
  * saveEnrichmentField -- hardcoded `PATCH /api/context/repo/{slug}/field`
    even though the backend route is already generic. The highest-severity
    fix in this pass: a real silent wrong-bucket WRITE, not just a wrong read.
  * runAnalysis -- hardcoded `POST /api/projects/{slug}/analyses/{id}/run`
    even though databases.py exposes the equivalent generic route.
  * getResourceFacts/getBulkFacts/getBulkStates -- did not send `entity_type`
    at all, so the backend (fixed separately, see
    test_analyses_facts_resource_type_dispatch.py) always saw its "repo"
    default regardless of what the caller actually knew.
"""
from __future__ import annotations

from pathlib import Path

RE_API = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "re-api.js"


def _fn(js: str, name: str) -> str:
    """Extract one `export const NAME = (...) => ...;` or `export const NAME
    = (...) => { ... };` definition through its terminating `;` at paren/brace
    depth 0 -- mirrors test_fact_answer_rendering.py's brace-matching
    technique, adapted for an arrow-function const rather than a `function`
    declaration. Includes an immediately-preceding `/** ... */` doc comment,
    if there is one directly above the marker with only whitespace between --
    several of this pass's fixes document a found-but-deferred gap there
    rather than inside the arrow function body itself."""
    marker = f"export const {name} ="
    start = js.index(marker)
    doc_end = js.rfind("*/", 0, start)
    if doc_end != -1 and js[doc_end + 2:start].strip() == "":
        doc_start = js.rfind("/**", 0, doc_end)
        if doc_start != -1:
            start = doc_start
    i = js.index(marker) + len(f"export const {name} =")
    depth = 0
    started = False
    while True:
        ch = js[i]
        if ch in "([{":
            depth += 1
            started = True
        elif ch in ")]}":
            depth -= 1
        elif ch == ";" and depth == 0 and started:
            i += 1
            break
        i += 1
    return js[start:i]


def _source() -> str:
    return RE_API.read_text()


class TestSaveEnrichmentFieldIsEntityGeneric:
    def test_no_longer_hardcodes_the_repo_bucket(self):
        fn = _fn(_source(), "saveEnrichmentField")
        assert "/api/context/repo/" not in fn, (
            "saveEnrichmentField must not hardcode the repo context bucket -- "
            "a database/filesystem save must land in ITS OWN bucket"
        )

    def test_builds_the_path_from_an_entity_type_parameter(self):
        fn = _fn(_source(), "saveEnrichmentField")
        assert "entityType" in fn
        assert "/api/context/${encodeURIComponent(entityType)}/" in fn

    def test_entity_type_defaults_to_repo_for_existing_callers(self):
        fn = _fn(_source(), "saveEnrichmentField")
        assert "entityType = 'repo'" in fn


class TestRunAnalysisDispatchesByEntityType:
    def test_no_longer_always_posts_to_the_projects_path(self):
        fn = _fn(_source(), "runAnalysis")
        # The literal repo path must not be the ONLY path constructed --
        # it's still the fallback default, but a database entityType must
        # route elsewhere.
        assert "_runAnalysisPath" in fn

    def test_database_routes_to_the_databases_path(self):
        js = _source()
        path_fn_start = js.index("function _runAnalysisPath(")
        brace = js.index("{", path_fn_start)
        depth = 1
        i = brace + 1
        while depth:
            if js[i] == "{":
                depth += 1
            elif js[i] == "}":
                depth -= 1
            i += 1
        path_fn = js[path_fn_start:i]
        assert "/api/databases/" in path_fn
        assert "entityType === 'database'" in path_fn

    def test_entity_type_defaults_to_repo(self):
        fn = _fn(_source(), "runAnalysis")
        assert "entityType = 'repo'" in fn


class TestGetAnalysesIndexSendsEntityType:
    """Fixed upstream by re/measurements-feedback-fix (PR #237), merged ahead
    of this branch -- pinned here since this file otherwise only documents
    what this Tier 1 pass itself changed."""

    def test_sends_entity_type_as_a_query_param(self):
        fn = _fn(_source(), "getAnalysesIndex")
        assert "entity_type=${encodeURIComponent(entityType)}" in fn
        assert "entityType = 'repo'" in fn


class TestBulkAndPerResourceFactsSendEntityType:
    def test_get_resource_facts_sends_entity_type(self):
        fn = _fn(_source(), "getResourceFacts")
        assert "entity_type=" in fn
        assert "entityType = 'repo'" in fn

    def test_get_bulk_facts_sends_entity_type(self):
        fn = _fn(_source(), "getBulkFacts")
        assert "entity_type" in fn
        assert "entityType = 'repo'" in fn

    def test_get_bulk_states_sends_entity_type(self):
        fn = _fn(_source(), "getBulkStates")
        assert "entity_type" in fn
        assert "entityType = 'repo'" in fn


class TestFoundNotFixedGapsAreDocumented:
    """The Tier 1 audit found getAnalysesIndex/getAnalysisTrend/getMembers/
    getMemberChildren/promoteMembers had no database/filesystem backend
    route at all -- these must say so in-source (not be silently left as
    hardcoded 'repo' with no explanation), per the PR's own found-but-
    deferred accounting.

    getAnalysesIndex is no longer one of them: `re/measurements-feedback-fix`
    (PR #237) landed a real fix for it (entity_type dispatch built into
    `build_analyses_index()` itself) ahead of this branch, superseding the
    Tier 1 audit's finding for that one function -- see the comment left in
    its place in re-api.js. getAnalysisTrend/getMembers/getMemberChildren/
    promoteMembers remain unfixed as of this branch."""

    def test_get_analysis_trend_names_the_gap(self):
        fn = _fn(_source(), "getAnalysisTrend")
        assert "FOUND, NOT FIXED" in fn

    def test_get_members_names_the_gap(self):
        fn = _fn(_source(), "getMembers")
        assert "found, not fixed" in fn.lower()
