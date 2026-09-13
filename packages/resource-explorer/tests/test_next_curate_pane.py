"""The Curate pane in /next: what a Python suite can hold it to without a
browser. The screen itself was verified on a branch server (2026-09-12)."""
from __future__ import annotations

import re
from pathlib import Path

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"


def _app():
    return (NEXT / "app.js").read_text(encoding="utf-8")


class TestTheScreenHoldsTheDesignRules:
    def test_it_renders_whether_or_not_the_catalog_has_rows_for_the_stage(self):
        app = _app()
        i = app.index("if (state.stage === 'curate') renderCurate(slug);")
        j = app.index("if (!state.questions.length) {", i)
        assert i < j, "Curate must render before the empty-question early return"

    def test_only_what_it_is_is_confirmed_row_by_row(self):
        app = _app()
        cols = app[app.index("const CURATE_COLUMNS = ["):app.index("];", app.index("const CURATE_COLUMNS = ["))]
        assert cols.count("pick: true") == 1 and "key: 'what_it_is'" in cols.split("pick: true")[0].rsplit("{", 1)[-1]

    def test_the_population_rule_is_said_and_the_button_is_gated_not_hidden(self):
        app = _app()
        body = app[app.index("async function renderCurate("):app.index("function rowKey(i)")]
        assert "Only worthy things get curated" in body
        assert "data-curate-go ${plan.in_population && me ? '' : 'disabled'}" in body
        assert "sign in to catalogue" in body

    def test_every_count_opens_its_members_and_the_manifest_names_the_three_rules(self):
        app = _app()
        body = app[app.index("function curateRowHtml("):app.index("function rowKey(i)")]
        assert "data-curate-members" in body and "openMembers({ slug, analysisId: b.dataset.curateMembers" in body
        assert "testimony copied · measurements linked · unresolved things travel" in body
        assert "Reversing this needs a correction, which stays on the record." in body

    def test_the_commit_is_polled_and_the_record_redrawn_per_step(self):
        app = _app()
        body = app[app.index("async function renderCurate("):app.index("function rowKey(i)")]
        assert "await pollActivity(out.activity_id" in body and "getCuration(slug, out.curation.id)" in body
        assert "runs in the worker, not here" in app
