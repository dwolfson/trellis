"""The component review in the Curate column (designer's ports round,
2026-09-14). Verified in a browser on kafka: 641 components as 69 branches,
the ⚠ count on the row, 116 leaves under clients/, the preview dialog."""
from __future__ import annotations

from pathlib import Path

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"


def _app():
    return (NEXT / "app.js").read_text(encoding="utf-8")


class TestReviewHappensAtTheBranch:
    def test_rows_are_branches_and_verdicts_say_where_they_came_from(self):
        app = _app()
        body = app[app.index("function verdictBadge("):app.index("function rowKey(i)")]
        assert "data-branch-open" in body and "accept all ${b.components}" in body
        assert "· with <span class=\"font-mono\">${esc(v.inherited_from)}/</span>" in body   # inherited says so
        assert "grouping only — a directory that holds components, not a component itself" in body
        assert "⚠ <span class=\"tnum\">${b.low_confidence}</span> at or below 50%" in body   # confidence routes, never hides

    def test_ports_are_a_column_and_the_foot_says_what_it_looked_in(self):
        app = _app()
        body = app[app.index("function verdictBadge("):app.index("function rowKey(i)")]
        assert "function portsWords(" in body
        assert "tree.topology" in body
        assert "read from the deployment artifacts" in body and "derived from" not in body

    def test_bulk_accept_goes_through_the_preview_and_nothing_runs_until_confirmed(self):
        app = _app()
        body = app[app.index("function recordVerdicts("):app.index("function rowKey(i)")]
        assert "openDialog('Accept at the branch'" in body
        assert "Nothing runs until you confirm." in body
        assert "will be created as Egeria SolutionComponents" in body
        assert "not yet measured" in body, "an unmeasured price is said, not invented"
        assert "if (verdict !== 'accepted' || count <= 1) { go(); return; }" in body   # rejecting creates nothing; one leaf needs no preview

    def test_no_undo_and_the_word_is_change(self):
        app = _app()
        body = app[app.index("function leafRowHtml("):app.index("async function renderComponentTree(")]
        assert "'change' : 'accept'" in body and "undo" not in body.lower()
