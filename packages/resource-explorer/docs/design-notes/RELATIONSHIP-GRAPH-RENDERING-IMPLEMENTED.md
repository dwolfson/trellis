# Relationship graph rendering — implemented

Wires the wireframe-only design note "Design: the relationship graph, drawn from the real
AdventureWorks edges" (`1051e4d4`, merged into `main` 2026-09-28 as part of
`re/design-batch-0928`) into the running `/next` app. Before this change,
`docs/design-notes/wireframes/RelationshipGraph.dc.html` and the three example `.dot` files under
`docs/design-notes/wireframes/relationship-graph/` were a design canvas only — the "Is there a data
model here?" question in the Questions tab rendered text/stats from `db_relationship_graph` and no
graph image anywhere. It now does.

## What was built

- **`resource_explorer/surveyors/database/relationship_dot.py`** (new) — pure Graphviz DOT
  generation, no I/O. Three zoom levels:
  - `schema_map_dot` — one box per schema, always renders regardless of database size.
  - `full_database_dot` — the whole database: schema clusters, hub nodes sized/emphasised by
    in-degree (`HUB_MIN_IN_DEGREE = 5`, matching the wireframe's own examples), cross-schema edges
    drawn darker than intra-schema ones, `dot` layout (not `fdp`, per the design note's own
    finding). Returns `(None, reason)` above `FULL_GRAPH_TABLE_LIMIT = 100` tables — the design
    note's own threshold — with the reason worded as a named state
    (`"graph not drawn: N tables; per-schema views available"`), never a blank panel.
  - `schema_detail_dot` — one schema opened, with its OUTGOING keys also drawn (as edges to
    plaintext "ghost" nodes for the external target). This is what fixes the design note's own
    finding: `sales.salestaxrate` and `sales.shoppingcartitem` have keys LEAVING the schema and
    must never be drawn/captioned as "isolated" — they are captioned "no keys inside sales — joined
    across", and only a table with NO key in either direction is captioned "isolated".
  - Honesty extension beyond the wireframe: a table whose own keys were never captured
    (`DerivedInputs.keys_captured_for_table` is False — a native-survey read-back, or a
    catalog-only-fallback table) is drawn dashed and labelled "keys not captured" in both the
    whole-database and per-schema views — never as "no relationships", which would assert a
    measurement that was never taken. `full_database_dot`/`schema_detail_dot` both take an optional
    `not_captured_by_schema`/`not_captured` parameter for this. A credential-scoped survey can also
    carry a `credential_scope` (`connected_as`/`measured`/`total`) into the whole-database drawing's
    title, in the same vocabulary the existing 21b coverage headline uses.
  - `build_relationship_diagrams` — the single entry point, assembling all three levels from data
    `db_derived.py` already computed (no second query path).

- **`resource_explorer/surveyors/database/db_derived.py`** — `relationship_graph_by_container`
  (the function that already computes the correct per-schema counting, withholding crossing
  columns from each schema's internal graph and reporting them separately as
  `cross_container_references`) now also builds `tables_by_schema`/`not_captured_by_schema` from
  the same `inputs`/`containment` it already has, calls `build_relationship_diagrams`, and attaches
  the result as a new `"graphviz"` key on its return dict. Via `apply_container_grain`'s existing
  `.update()`, this lands at `derived["db_relationship_graph"]["graphviz"]` — the exact dict every
  other reader of this analysis already reads (`_db_derived_field_reader`), so it reaches the
  frontend through the existing fact-reading path with no new plumbing.

- **`resource_explorer/web/routes/diagrams.py`** — new `POST /api/diagrams/graphviz`, mirroring the
  existing `/api/diagrams/mermaid` route exactly (same shared Kroki container, same raw-SVG
  response, same "no fallback, a clear 502" failure behaviour), but posting to Kroki's
  `/graphviz/svg` endpoint. Graphviz is emitted rather than Mermaid because `dot`'s cluster layout
  has no Mermaid equivalent — the design note's own instruction.

- **Frontend** (`envelope.js`, `app.js`):
  - `envelope.js`'s new `factGraphviz(env)` mirrors the existing `factMermaid(env)` (used by
    `architecture_diagram`) — reads `f.value.graphviz` off the envelope's facts.
  - The Evidence rail (`showEvidence`) now renders a "Relationship graph" block when a question's
    envelope carries one: a "Schema map" button (always present), a "Whole database" button (or,
    above the 100-table threshold, the named fallback state as text instead of a broken/blank
    button), and a schema-name `<select>` for "Open a schema…" covering every schema the question's
    containment scope names.
  - `promoteToPane` (the pane that actually renders a diagram, reused unchanged from the Mermaid
    path for pan/zoom/theming) now branches on `turn.graphviz` vs `turn.mermaid` — DOT skips the
    Mermaid-specific `mermaidForKroki` escaping and hits `/api/diagrams/graphviz` instead.
  - **Kroki-down handling**: both a network-level fetch failure and a 502 from the backend (Kroki
    itself unreachable or erroring) render a "renderer unavailable" panel with the DOT/Mermaid
    SOURCE shown as copyable text (`renderRendererUnavailable`/`bindCopyTargets`) — never a blank
    or broken image. The source is real evidence independent of whether Kroki is up.

## Coverage of the design note's three zoom levels + the coordination session's five requirements

1. Schema map — always renders, any database size. ✅ (live-verified, see below)
2. Whole database — schema clusters, hub weighting, darker cross-schema edges, `dot` layout,
   >100-table fallback as a named state. ✅ (live-verified for the render path; fallback path is
   unit-tested — `laz_local_adventureworks` has 68 key-captured tables, under the threshold, so the
   live database could not exercise the fallback itself)
3. Per-schema — outgoing keys drawn, "no keys inside X" never "isolated" for a table with only
   outgoing keys. ✅ (live-verified — see below)
4. Absence honesty (not-captured tables drawn dashed, credential-scope title) — built and
   unit/integration-tested; not live-exercised on `coco_pharma` in this pass (time-boxed; the code
   path threading `not_captured_by_schema` through from real `DerivedInputs` is exercised by
   `TestWiredIntoDbRelationshipGraph::test_never_key_captured_table_is_dashed_not_measured_absent`,
   an integration test through `run_db_derived` itself, not just the pure DOT function). Real
   credential-scope threading from `survey_definition_adapter.py`'s `_attach_container_credential_
   scope` into the drawing's title is NOT wired — `build_relationship_diagrams`/`full_database_dot`
   accept `credential_scope` and use it correctly (unit-tested), but nothing yet calls them with a
   real scoped value; that attachment happens in a different module/layer (post-hoc, after
   `run_db_derived` returns) and connecting it is left as a follow-up (see below).
5. Named fallback state, not a blank panel. ✅ (`full_fallback_reason` string, unit-tested with the
   exact wording; rail renders it as text when `full` is absent).
6. Kroki-down reporting with "copy as evidence" text fallback. ✅ (built; not live-exercised against
   a real down Kroki in this pass — covered by `TestRenderGraphvizRoute` at the route level, which
   is what actually determines the 502 path the frontend branches on).
7. Fold the whole-database headline before the per-schema list. Already true before this change —
   `apply_container_grain` appends the per-schema rollup sentence AFTER the whole-database
   `explanation` (`"{payload['explanation']} {rollup_sentence}"`), so the numbers already lead. No
   change needed; left as-is.
8. Tests: DOT generation determinism, not-captured/scoped cases, fallback threshold, Kroki-down
   route test. ✅ — see below.

## Live verification — `laz_local_adventureworks`

Ran the app from this worktree on a scratch port (8891, separate from the shared checkout's 8810 —
per this repo's CLAUDE.md, the shared checkout at `~/localGit/egeria-v6/trellis` must stay on `main`
and nobody else's server runs from it) and drove it through the actual `/next` UI, signed in as
`erinoverview` (logged out again afterward).

**Counts, as measured by the ALREADY-EXISTING `db_relationship_graph` analysis** (this change reads
that analysis's own output; it does not recompute anything):

- Evidence rail for "Is there a data model here...": **edge count 91 · component count 2 · largest
  component 67 · connected tables 67 · isolated tables 1 (`production.transactionhistoryarchive`) ·
  dangling references 0**.
- Schema map view: **person 13 tables/13 keys · humanresources 6 tables/5 keys · production 25
  tables/27 keys · purchasing 5 tables/4 keys · sales 19 tables/22 keys**, with cross-schema edge
  counts drawn between them.
- 68 of 68 key-captured tables total (5 real schemas + 5 empty abbreviation-named duplicate schemas
  — `hr`/`pe`/`pr`/`pu`/`sa` — that this survey run reports `not_established (no_schema_rows)` for,
  which is why the database's raw sidebar count reads "11 schemas · 157 tables" while the
  relationship-graph analysis's own key-captured population is 68, exactly matching the design
  note).

**These numbers match the design note's own recorded counts exactly** (68 tables, 91 keys, 2
components, 1 isolated table — the design note's "20 cross-schema" isn't a field this analysis
reports as one number, but the schema-map view's edge labels sum to the same cross-schema edges the
note counted). Nothing in `docs/Backlog.md` or recent commits shows `db_relationship_graph`'s
counting changed since the note was written 2026-09-28 — Section A/PR #316's PK/FK undercount fix
predates the note (the note's own commit message says its counts were fetched *after* that fix), so
no drift to explain here.

**Zoom level 1 — schema map**: rendered via Kroki, showing all 5 real schemas as boxes with their
table/key counts and cross-schema edges labelled with counts — visually matches
`schema_map.dot`'s shape.

**Zoom level 2 — whole database**: rendered via Kroki, showing schema clusters (person, sales,
purchasing, humanresources, production) with hub nodes in bold (`person`, `businessentity`,
`employee`, `product`, `salesterritory`) — matches `full_dot.dot`'s shape. (68 tables is under the
100-table threshold, so this is the render path, not the fallback path — the fallback is covered
by unit tests instead, per item 2 above.)

**Zoom level 3 — schema detail (`sales`)**: rendered via Kroki. Verified by reading the actual
rendered SVG's text nodes (not just eyeballing a screenshot):

```
"salestaxrate", "no keys inside sales — joined across",
"shoppingcartitem", "no keys inside sales — joined across"
```

This is the design note's own finding, confirmed fixed end-to-end against real data: both tables
have a key leaving `sales` and are captioned accordingly — never "isolated".

Screenshots of all three views were reviewed live in the session (schema map, whole-database, and
the `sales` detail view showing the salestaxrate/shoppingcartitem captions) but are not attached to
this doc as files; the SVG-text-content evidence above is the more precise record of the same
verification.

## Tests

`tests/test_relationship_dot.py` (new, 23 cases):
- `TestSchemaMapDot` — deterministic output, cluster-free per-schema boxes with counts, cross-schema
  edge labelling, width scales with table count.
- `TestFullDatabaseDot` — schema clusters present, cross-schema edges styled differently from
  internal ones (colour check), hub nodes sized/labelled by in-degree (built via a fixture crossing
  `HUB_MIN_IN_DEGREE`, not hardcoded to the wireframe's own numbers), not-captured tables drawn
  dashed and never claim "no keys", credential-scope title uses the 21b vocabulary, determinism,
  the >100-table fallback returns `None` with a named reason, and the boundary case (exactly at the
  threshold still draws).
- `TestSchemaDetailDot` — the core fix: a table with only outgoing keys says "no keys inside X",
  never "isolated"; the outgoing edge is actually drawn; a table with no keys at all IS labelled
  isolated (the one case allowed to say so); not-captured takes priority over the isolated label;
  determinism.
- `TestBuildRelationshipDiagrams` — assembles all three levels; fallback reason present with schema
  map still rendering at 100+ tables; not-captured threads through to both `full` and `by_schema`.
- `TestWiredIntoDbRelationshipGraph` (integration, same fixture pattern as
  `test_schema_containment_grain.py`) — `run_db_derived` over a real registry produces a
  `db_relationship_graph` result carrying `graphviz` with all three levels, and a table whose keys
  were never captured is dashed in the real wired-up output, not just in the pure function.

`tests/test_diagrams_route.py` — added `TestRenderGraphvizRoute` (5 cases), mirroring
`TestRenderMermaidRoute` exactly: success returns raw SVG, Kroki-unreachable and Kroki-error-response
both surface as 502 (not 500 — this is what the frontend's "renderer unavailable" branch depends
on), missing `source` is a 422, and the route posts to Kroki's `/graphviz/svg` with the right
content-type.

## Full test suite

```
uv run pytest tests/ -q -rf
6710 passed, 103 skipped, 0 failed, 4898 warnings in 697.95s (0:11:37)
```

No `-k`, no deselects, full run. Zero failures.

## Follow-ups (not done in this pass)

- Real `credential_scope` threading from `survey_definition_adapter.py`'s post-hoc credential-scope
  attachment into the drawing's title — the DOT-generation side is built and tested, but nothing
  calls it with a live scoped value yet. `coco_pharma`'s scoped/not-captured rendering was verified
  only through the `run_db_derived`-level integration test, not live in the browser.
- No PR opened, per instructions — this is a pushed branch only; the "Resource-explorer PR/CI
  merge" session batches PRs and was sent the tip.
