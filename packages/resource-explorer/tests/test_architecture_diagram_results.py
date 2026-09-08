"""architecture_diagram (repo_survey_definition_adapter.py) — new 2026-09-08.

The Mermaid diagram + caption arch_recovery/persist.py's `_persist_diagram`
computes and writes at survey time (alongside repo_arch_detect/coupling's
own findings) was never read back by anything before this — see
BACKLOG.md's "how do components relate" investigation. This pins the read
path: a persisted `architecture_diagram` finding round-trips through
`_architecture_diagram_results`/`_architecture_diagram_headline` into the
shape `_renderEnvelopeMarkdown` (index.html) actually consumes — `mermaid`,
`caption`/headline, and the too-large flag.
"""
from __future__ import annotations

from resource_explorer.surveyors.repo_survey_definition_adapter import (
    ANALYSIS_KINDS,
    _architecture_diagram_headline,
    _architecture_diagram_results,
)


class _Reg:
    """`query_findings_all_runs`, not `query_findings` — the reader switched
    2026-09-08 to see both perspectives' rows even when they were surveyed at
    different times, which `query_findings`'s "only the single latest
    surveyed_at across the whole kind" would silently drop one of.

    Also stubs the calls `_architecture_verdict_coverage` makes (same day's
    follow-on, docs/curated-architecture-answers-design.md §6 item 1) —
    every diagram read now also checks curator-verdict coverage to append to
    its caption. Empty by default (no verdicts, nothing clustered), so
    existing caption assertions in this file are unaffected unless a test
    opts in via `verdicts=`/`blueprint_rows=`."""

    def __init__(self, rows, verdicts=None, blueprint_rows=(), component_scopes=()):
        self._rows = rows
        self._verdicts = verdicts or {}
        self._blueprint_rows = list(blueprint_rows)
        self._component_scopes = list(component_scopes)

    def query_findings_all_runs(self, slug, kind, scope_locator):
        assert scope_locator == ""
        if kind == "architecture_blueprints":
            return self._blueprint_rows
        assert kind == "architecture_diagram"
        return self._rows

    def get_component_verdicts(self, entity_type, entity_slug):
        return self._verdicts

    def query_finding_scopes(self, slug, kind, check_name=None):
        if kind == "architecture_recovery" and check_name == "component":
            return self._component_scopes
        return []


def _row(caption="3 component(s) shown at depth 2.", mermaid="graph TD\n  a --> b",
         char_count=None, exceeds=False, surveyed_at="2026-09-08T00:00:00",
         check_name="coupling"):
    return {
        "check_name": check_name,
        "summary": caption,
        "surveyed_at": surveyed_at,
        "detail_json": {
            "mermaid": mermaid,
            "char_count": char_count if char_count is not None else len(mermaid),
            "exceeds_renderer_limit": exceeds,
            "projection_depth": 2,
        },
    }


class TestResultsReadBack:
    def test_never_run_reports_its_own_empty_state(self):
        r = _architecture_diagram_results(_Reg([]), "acme-widget")
        assert r["_status"]["state"] == "never_run"

    def test_never_run_is_not_content(self):
        """Regression: the first version of this reader put `state`/`message`
        at the top level, which facts.py's `_has_content` does NOT recognise
        as envelope-only metadata -- combined with `live_read=True`, that made
        a genuinely-absent diagram report MEASURED with a fake headline
        instead of falling through to the real never-run gate. Caught live
        2026-09-08 by TestAgainstRealCatalog (test_facts.py) against a
        nonexistent repo, across every catalogued question at once."""
        from resource_explorer.facts import _has_content

        r = _architecture_diagram_results(_Reg([]), "acme-widget")
        assert _has_content(r) is False

    def test_a_persisted_diagram_round_trips(self):
        r = _architecture_diagram_results(_Reg([_row()]), "acme-widget")
        assert r["mermaid"] == "graph TD\n  a --> b"
        assert r["caption"] == "3 component(s) shown at depth 2."
        assert r["exceeds_renderer_limit"] is False
        assert r["char_count"] == len("graph TD\n  a --> b")

    def test_the_latest_run_wins(self):
        rows = [
            _row(caption="old", mermaid="graph TD\n  x", surveyed_at="2026-09-01T00:00:00"),
            _row(caption="new", mermaid="graph TD\n  y", surveyed_at="2026-09-08T00:00:00"),
        ]
        r = _architecture_diagram_results(_Reg(rows), "acme-widget")
        assert r["caption"] == "new"

    def test_a_json_string_detail_column_is_parsed(self):
        """Postgres hands back JSONB as a dict; a string-backed store (or a
        row read a different way) hands back the same content as text --
        the same backend split _architecture_summary_results already
        guards against."""
        import json
        row = _row()
        row["detail_json"] = json.dumps(row["detail_json"])
        r = _architecture_diagram_results(_Reg([row]), "acme-widget")
        assert r["mermaid"] == "graph TD\n  a --> b"


class TestTwoPerspectives:
    """Regression for the live bug found 2026-09-08 against
    egeria-workspaces_git: repo_arch_detect and repo_arch_coupling each
    persist their own diagram, and before this fix both wrote under the
    identical check_name -- a reader taking "the latest" got whichever step
    happened to run last, and the chat-typed answer (RAG, reading something
    else entirely) disagreed with it: 85 components vs. 12."""

    def test_coupling_is_preferred_when_both_are_present(self):
        rows = [
            _row(check_name="detect", caption="detect view", mermaid="graph TD\n  d"),
            _row(check_name="coupling", caption="coupling view", mermaid="graph TD\n  c"),
        ]
        r = _architecture_diagram_results(_Reg(rows), "acme-widget")
        assert r["caption"] == "coupling view"
        assert r["perspective"] == "coupling"
        assert r["other_perspectives_available"] == ["detect"]

    def test_detect_answers_alone_when_coupling_has_not_run(self):
        rows = [_row(check_name="detect", caption="detect view")]
        r = _architecture_diagram_results(_Reg(rows), "acme-widget")
        assert r["perspective"] == "detect"
        assert r["other_perspectives_available"] == []

    def test_pre_fix_legacy_rows_still_answer(self):
        """Data surveyed before 2026-09-08 was written under the literal
        check_name "architecture_diagram" (no run_label). It must not go
        never-run just because the vocabulary changed under it."""
        rows = [_row(check_name="architecture_diagram", caption="legacy view")]
        r = _architecture_diagram_results(_Reg(rows), "acme-widget")
        assert r["caption"] == "legacy view"
        assert r["perspective"] == "architecture_diagram"

    def test_each_perspective_keeps_its_own_latest_run(self):
        """Two independent steps need not share a surveyed_at (the exact
        reason query_findings_all_runs exists, per its own docstring) --
        picking "coupling" must not accidentally pick an OLD coupling row
        over a newer detect one; each perspective's own latest wins before
        the preference order chooses between perspectives."""
        rows = [
            _row(check_name="coupling", caption="old coupling", surveyed_at="2026-08-01T00:00:00"),
            _row(check_name="coupling", caption="new coupling", surveyed_at="2026-09-08T00:00:00"),
            _row(check_name="detect", caption="newer detect", surveyed_at="2026-09-08T12:00:00"),
        ]
        r = _architecture_diagram_results(_Reg(rows), "acme-widget")
        assert r["caption"] == "new coupling"  # coupling still preferred over detect
        assert r["perspective"] == "coupling"


class TestHeadline:
    def test_never_run_has_no_headline(self):
        assert _architecture_diagram_headline(_Reg([]), "acme-widget") is None

    def test_the_caption_becomes_the_headline_label(self):
        h = _architecture_diagram_headline(_Reg([_row(caption="4 component(s) shown.")]), "acme-widget")
        assert h == {"label": "4 component(s) shown.", "status": "info"}

    def test_an_oversized_diagram_warns_instead_of_info(self):
        """caption() (mermaid.py) already appends "NOT RENDERABLE: ..." to
        its own text when this is true -- the badge must agree with the
        words rather than a reader having to notice only in the sentence."""
        h = _architecture_diagram_headline(
            _Reg([_row(caption="200 component(s) shown. NOT RENDERABLE: too large.", exceeds=True)]),
            "acme-widget",
        )
        assert h["status"] == "warn"

    def test_a_missing_caption_falls_back_to_a_generic_label(self):
        row = _row(caption="")
        h = _architecture_diagram_headline(_Reg([row]), "acme-widget")
        assert h["label"] == "Architecture diagram"


class TestLiveRead:
    """Regression for a real bug found live 2026-09-08 against
    egeria-workspaces_git: two persisted architecture_diagram rows existed
    and _architecture_diagram_results read them fine directly, but the
    question-catalog click path still said "I can't answer that yet ...
    Run: repo_arch_detect, repo_arch_coupling."

    Cause: repo_arch_detect/repo_arch_coupling running gets recorded under
    analysis_id "architecture_recovery" (that AnalysisKind's own id), never
    under "architecture_diagram" -- so FactLayer.fact()'s run-attribution
    gate (`facts.py`, keyed by analysis_id) never sees this id as having
    run, and reports NEVER_RUN even with real rows sitting in the table.
    `live_read=True` is the documented escape hatch for exactly this shape
    (see AnalysisKindResults.live_read's own docstring, and api_structure's
    2026-09-02 precedent) -- it tells FactLayer.fact() to read the table
    first and only fall through to the run-attribution gate if genuinely
    empty. Losing this flag on a future edit reintroduces the exact bug a
    live registry query caught, silently, since query_findings still
    returns data either way -- this test is what would have caught it."""

    def test_architecture_diagram_is_declared_live_read(self):
        kind = ANALYSIS_KINDS["architecture_diagram"]
        assert kind.results.live_read is True
