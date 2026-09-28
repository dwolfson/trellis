# Relationship-graph schema `<select>` visual affordance — implemented

**Dispatch:** direct live feedback from the project owner, 2026-09-28, on the Relationship Graph
Evidence-rail block (`data-act="evidence-graphviz-schema"`) just merged as part of
`re/relationship-graph-rendering` (PR #339).
**Branch:** `re/relationship-graph-dropdown-affordance`, off `origin/main` `100e131a`, built in a
separate worktree (`/Users/dwolfson/localGit/egeria-v6/trellis-re-graph-dropdown-affordance`).
**Coordination:** confirmed no overlap with the "Resource Explorer expansion architecture" session
before editing — the relationship-graph block was already on main (not, as first reported, only on
the unmerged feature branch). That session also flagged that a By-analysis rebuild agent
(`re/by-analysis-progressive-and-graph`, not yet pushed as of this branch) will touch the same
`app.js` region later tonight and was told to land after this fix and adapt, not the reverse.

## The bug

The Relationship Graph card in the Evidence rail (`resource_explorer/web/static/next/app.js`,
`showEvidence`'s `graphvizBlock`) renders three zoom levels: "Schema map" and "Whole database" as
`<button>`s (bordered, accent-colored, with a `maximize-2` icon), and "open one schema" as a bare
`<select>` styled with only `border-rule-strong`/`text-ink` — the same visual weight as plain
prose elsewhere on the card. The project owner tried it live: selecting a schema genuinely worked
(the dropdown's `change` handler already renders that schema's graph correctly), but nothing about
its appearance suggested it was interactive. It read as inert text sitting under two buttons that
very much do look like buttons.

## The fix

Pure CSS/markup, no behavior change. The `<select>` now carries the same button vocabulary as its
siblings — `border-accent`, `text-accent-on-dark`, plus `hover:bg-accent-tint` (an existing
hover-state utility already used elsewhere in `/next`, e.g. line 925) and a `focus:ring-accent`
outline. No prior "select styled as an interactive control" convention existed anywhere else in
`app.js` (checked all four other `<select>` elements — `sel-disposition`, `investigation-select`,
`notify-schedule-cadence` — none use the accent/button treatment), so this establishes one rather
than reusing an existing pattern, per the design's own preference to look for a precedent first.

Native select arrows are inconsistent and easy to miss against a dark, borderless background, so
the select is set `appearance-none` and wrapped in a `relative` container with a `chevron-down`
icon absolutely positioned over it (`pointer-events-none`, so it doesn't intercept clicks meant for
the select underneath) — the same "this opens something" signal the buttons above it give with
`maximize-2`.

`data-act="evidence-graphviz-schema"` and the `<option>` list (including the `Open a schema…`
placeholder) are untouched, so the existing `change` listener
(`out.querySelector('[data-act="evidence-graphviz-schema"]')?.addEventListener('change', ...)`)
and anything else that queries this element by its `data-act` keep working unmodified.

## Before / after

**Before:** `<select>` with `border-rule-strong` (a faint, low-contrast border shared with plain
dividers elsewhere) and `text-ink` — visually indistinguishable from static text on the card.

**After:** `<select>` wrapped in a `relative` div, `border-accent` + `text-accent-on-dark` +
`hover:bg-accent-tint` + `focus:ring-accent`, with an absolutely-positioned `chevron-down` icon —
matching the "Schema map"/"Whole database" buttons directly above it. Live-verified in a browser
against `laz_local_adventureworks` (11 schemas, 157 relations): the control now visually reads as
a third action alongside the two buttons, its hover state tints the background exactly like the
buttons do, and selecting "production" from the dropdown correctly rendered that schema's
relationship graph in the content pane — the dropdown's own behavior is unchanged.

## Tests

Added `tests/test_next_evidence_graph_schema_affordance.py`, following this repo's established
source-text assertion pattern for pure front-end JS (`test_next_sidebar_group_collapse.py`,
`test_next_component_review.py`, `test_next_rail_states.py` — there is no jsdom/browser harness
here). It isolates the `<select>` block by locating `schemaNames.length ? ... : ''` in `app.js`'s
source and asserts:
- `data-act="evidence-graphviz-schema"` and the `<option>` list are unchanged (no accidental
  behavior regression)
- the button-like classes (`border-accent`, `text-accent-on-dark`, `hover:bg-accent-tint`) are
  present, and the old `border-rule-strong` is gone
- the chevron icon and `appearance-none` are present
- the wrapping `<div class="relative">` + `pointer-events-none absolute` icon positioning exist

Full suite: **run from `/Users/dwolfson/localGit/egeria-v6/trellis-re-graph-dropdown-affordance/packages/resource-explorer`,
`uv run pytest tests/ -q -rf`** — pass/fail counts recorded below once the run completes.

## Verification

Live-verified in a browser against the branch, served on port 8815 (8813 reserved for the project
owner's own gates per the coordinator's instruction), signed in as `erinoverview` via
`resource-explorer login`/`logout` (demo/test credentials for this purpose only; session cleared
afterward per `docs/Backlog.md`'s note on `test_cli_workflow_commands.py`'s cached-session
collision). Navigated to `/next`, filtered to DBs, opened `laz_local_adventureworks`, went to
Discovery → "Is there a data model here — do the tables relate through foreign keys, or is this a
bag of tables?" → evidence → scrolled to the Relationship graph card. Confirmed: the "Open a
schema…" control now has a visible accent border, a chevron, and a hover-tint background matching
"Schema map"/"Whole database"; selecting "production" from it correctly opened that schema's graph
in the content pane (dropdown's function unaffected by the styling change).
