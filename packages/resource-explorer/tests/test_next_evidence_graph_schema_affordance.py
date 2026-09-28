"""The Relationship Graph Evidence-rail block's "open one schema" zoom level
(`data-act="evidence-graphviz-schema"`, added in `re/relationship-graph-rendering`,
merged as PR #339) rendered as a bare `<select>` with no visual affordance that
it's interactive -- no border/hover/focus distinct from surrounding text, no
icon suggesting "this opens a menu". It read as inert text next to its sibling
"Schema map"/"Whole database" buttons, which ARE styled as buttons (bordered,
accent-colored, with an icon). The project owner tried it live and flagged
this.

Fix is pure CSS/markup: give the select the same button-like treatment as its
siblings (`border-accent`/`text-accent-on-dark`/hover state) plus a chevron
icon, wrapped in a relative container so the icon can sit inside the control.
`data-act` and the `<option>` list are untouched, so existing/future behavior
wiring (the `change` listener in `renderEvidenceRail`) and any option-content
assertions are unaffected.

These are source-text assertions, matching this repo's established pattern
for pure front-end JS behaviour (see test_next_sidebar_group_collapse.py,
test_next_component_review.py, test_next_rail_states.py) -- there is no
jsdom/browser harness here, so live rendering was verified manually in a
browser instead; see
docs/design-notes/RELATIONSHIP-GRAPH-SCHEMA-SELECT-AFFORDANCE-IMPLEMENTED.md."""
from __future__ import annotations

from pathlib import Path

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"


def _app():
    return (NEXT / "app.js").read_text(encoding="utf-8")


def _schema_select_block():
    app = _app()
    marker = 'data-act="evidence-graphviz-schema"'
    assert marker in app, "the schema-select control moved or was removed"
    start = app.rindex("schemaNames.length", 0, app.index(marker))
    end = app.index("</div>` : ''}", app.index(marker)) + len("</div>` : ''}")
    return app[start:end]


class TestSchemaSelectVisualAffordance:
    def test_data_act_and_options_unchanged(self):
        block = _schema_select_block()
        assert 'data-act="evidence-graphviz-schema"' in block
        assert '<option value="">Open a schema…</option>' in block
        assert "schemaNames.map((s) =>" in block

    def test_select_carries_button_like_classes(self):
        """Same visual vocabulary as the sibling `data-act="evidence-graphviz"`
        buttons above it in the same block (border-accent / text-accent-on-dark),
        not the plain `border-rule-strong` / `text-ink` it had before."""
        block = _schema_select_block()
        assert "border-accent" in block
        assert "text-accent-on-dark" in block
        assert "hover:bg-accent-tint" in block
        assert "border-rule-strong" not in block

    def test_select_has_a_chevron_indicating_a_menu(self):
        block = _schema_select_block()
        assert "chevron-down" in block
        assert "appearance-none" in block

    def test_select_is_wrapped_so_the_icon_can_be_positioned_over_it(self):
        block = _schema_select_block()
        assert '<div class="relative">' in block
        assert "pointer-events-none absolute" in block
