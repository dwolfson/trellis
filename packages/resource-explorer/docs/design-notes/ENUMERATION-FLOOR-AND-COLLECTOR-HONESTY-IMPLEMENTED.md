# Enumeration floor + collector honesty — implemented

**Coordinator brief:** Phase 1b, next after slice 17c
(`re/coordinator-brief-phase-1b`).
**Replying to:** the Decision recorded in
`docs/design-notes/SLICE-17B-RENDER-BOUND-LEVEL-GATE-IMPLEMENTED.md` (design
session, 2026-09-26, citing security-model.md §2.1/§3.4), and the
collector-honesty ruling recorded in
`docs/design-notes/SLICE-17C-RENDERABLE-ANSWER-GATE-IMPLEMENTED.md`'s "Live
gate follow-ups" section (same date).
**PR:** #TBD (`re/enumeration-floor-and-collector-honesty`).

## Part 1: the enumeration floor

### What was wrong

`coco_pharma`'s credential banner and its size answer disagreed on totals
(61 vs. 56 tables) because `get_schema_info()` enumerated schemas from
`information_schema.schemata` — privilege-filtered by Postgres to schemas
the connected role owns or holds *any* grant on. A schema with zero
privilege at all (not even `USAGE`) never appears there, so its tables
were never even attempted, not merely under-counted. `get_credential_capability()`'s
own docstring already documents hitting and fixing the identical gap for
itself (an 8-vs-6 schema undercount) by reading `pg_namespace` directly
instead — a fix that was never carried back to `get_schema_info()`'s own
enumeration.

### The fix

1. **`PostgreSQLConnection._enumerate_relations()`** (new) — the single
   unprivileged floor read (`pg_namespace`/`pg_class`, exactly the queries
   `get_credential_capability()` already used), now shared by both
   consumers. `get_credential_capability()` was refactored to call it
   rather than duplicating the same two queries.
2. **`get_schema_info()`** now runs a second pass after its existing
   privileged enumeration: any schema the floor sees that the privileged
   list missed entirely gets its tables read via the SAME machinery
   `_catalog_only_fallback()` already uses to recover a table
   `information_schema` couldn't see *within* an already-known schema
   (`_catalog_table_summary()` + `_catalog_columns_for_table()` — both
   pure `pg_class`/`pg_attribute` catalog-metadata reads, not
   privilege-filtered). Each such table is tagged `source:
   "catalog_fallback"`, the marker `database_rows_from_survey_data()`
   (`result_materializer.py`) already recognizes and stores as
   `STATE_CATALOG_ESTIMATE` — no downstream change needed for per-table
   honesty. The schema itself is tagged `access: "no_usage"` — not yet
   rendered anywhere (no per-schema view exists until slice 22), but
   present so that view can tell the two cases apart without re-deriving
   it.
3. **`_schema_inventory_results`** (`survey_definition_adapter.py`) now
   reports `base_table_count`/`view_count`/`materialized_view_count`/
   `foreign_table_count` alongside the unchanged `table_count` — relation
   kinds named separately, never blended into one count.
   `base_table_count` is the field kept stable for whatever already reads
   `table_count` as if it meant "ordinary tables only"; `table_count`
   itself keeps its original meaning (every relation kind combined), so
   neither meaning silently changed under an existing caller.

### Live verification (`coco_pharma`, `localhost_docker_coco_pharma`)

Before: `get_schema_info()` → 6 schemas, 56 tables (missing `demo`,
`demo_auth` entirely). `get_credential_capability()` → 8 schemas, 61
tables.

After: `get_schema_info()` → 8 schemas, 61 tables — `demo` (1 table) and
`demo_auth` (4 tables) present with `access: "no_usage"` and their real
table names/kinds. Totals now agree with `get_credential_capability()`'s
by construction (both read the same floor).

### Explicitly NOT done here

- **No per-schema UI** renders the `access: "no_usage"` marker yet — that
  is slice 22's own scope (the schema/table listing view). This PR only
  ensures the data reaches storage rather than vanishing; how it's
  presented is deliberately out of scope.
- **`database_rows_from_survey_data`'s schema-level `state` field** stays
  `STATE_MEASURED` uniformly for every schema, including a new
  `no_usage` one — a pre-existing simplification (schema-level state was
  never differentiated before this PR either), not made worse by this
  change. The TABLE-level honesty (`STATE_CATALOG_ESTIMATE` via the
  existing `source: "catalog_fallback"` marker) is what actually carries
  the caveat through to `_schema_inventory_results`.
- **A real survey re-run** is needed before `coco_pharma`'s stored detail
  rows reflect the new totals — this PR fixes the collector, not the
  already-stored data from before the fix (same caveat slice 17c's
  `privilege_audit` fix carried).

## Part 2: collector honesty

### What was wrong, generalized

The design session's own framing: `get_privilege_audit()`'s roles bug
(slice 17c) was invisible for weeks not because it was a rare edge case,
but because the collector's own `try/except Exception: roles = []` turned
a genuine exception into an empty result, indistinguishable from a real
empty one. That specific field got a reader-side floor (an empty `roles`
list can never be a legitimate zero), but the same failure mode can
recur invisibly in any OTHER collector where the empty default IS
sometimes legitimate — the floor has nothing to grab onto there.

**Ruling:** a collector that catches an exception records it on its own
section (`_errors`), never only the empty default; a reader renders a
recorded error as "Collection failed (`<field>`): `<reason>` — re-run.",
never silently as if the empty/zero were measured.

### What was converted

A shared, minimal convention: any collector method that returns a `dict`
now attaches `_errors: {field_name: str(exc)}` for each of its own
try/except blocks that actually caught something, omitting the key
entirely when nothing failed (the same "stay silent when there is nothing
to caveat" contract `_credential_scope_status` already follows elsewhere).

Converted (`connection.py`):

- `get_credential_capability()` (via `_enumerate_relations()`; also
  `connected_as`, `stats_role`)
- `get_schema_info()` (`schemas`, `enumeration_floor`, and
  per-zero-privilege-schema catalog reads)
- `get_privilege_audit()` (`roles`, `table_grants`, `default_acl`)
- `get_replication_status()` (`is_in_recovery`, `replicas`)
- `get_wal_archiving_status()` (`archive_mode`, `archiver_stats`)
- `get_backup_tool_signals()` (`detected_extensions`)
- `get_clustering_info()` (`citus_detected`)
- `get_external_dependencies()` (`extensions`, `foreign_servers`,
  `foreign_tables`, `publications`, `subscriptions`)

Two new helpers (`survey_definition_adapter.py`):

- `_merge_collector_errors(*sections)` — combines every `_errors` sub-dict
  several independently-collected sections carry into one dict, since
  `_db_resilience_headline` builds one sentence from four separately
  fetched sections.
- `_collection_failed_headline(errors)` — the shared "Collection failed
  (`<field>`): `<reason>` — re-run." renderer.

All four operations-family headline readers now check for a recorded
error before computing their normal sentence:

- `_db_resilience_headline` — checks all four of its sub-sections via
  `_merge_collector_errors`; ANY of the four failing fails the whole
  headline (deliberately coarse — see "Explicitly NOT done here").
- `_db_external_dependencies_headline`
- `_db_privilege_audit_headline` — a recorded `roles` error now wins over
  the pre-existing "empty roles → honest-absence `None`" floor, so a
  caller that CAN say why roles is empty says so, rather than falling
  back to the generic no-summary-reader state a plain empty list gets.

### Explicitly NOT done here

- **`get_table_activity()`/`get_stats_reset()`** (feeding
  `db_activity_signals`) were NOT converted. Their return types are
  `list[dict]`/`str`, not `dict` — there is no natural place to attach an
  `_errors` key without changing their contract, and their only two
  callers (`_survey_operations` in `database_surveyor.py`, and
  `get_statistics()` in this same file) combine them into a larger dict
  built at the CALL SITE, not inside these methods. Converting them
  properly means deciding, at the call site, whether a failure here
  should fail only the `activity_signals` section (current behavior,
  preserved) or something coarser — a design question, not a
  drop-in change, and lower priority than the four analyses above since
  `db_activity_signals` was never silently empty to begin with (it has
  two real scalar fields, `stats_reset`/`table_count`, so a failure there
  already surfaces as a thinner-than-ideal sentence, not a confident wrong
  one).
- **`_get_schema_descriptions`, `_catalog_columns_for_table`,
  `_catalog_only_fallback`, `get_column_stats`, `get_index_stats`,
  `_get_table_row_stats`** — the six remaining sites from the slice 17c
  inventory, all either best-effort enrichments where an empty result was
  always a legitimate degrade path (`_get_schema_descriptions`), or feed
  `get_statistics()`, which nothing in `DATABASE_ANALYSIS_RESULTS_MAP`
  currently reads (confirmed: `get_statistics()`'s only caller is
  `_survey_statistics`, itself unwired to any analysis). Left unconverted
  as lower-priority, not silently dropped — logged here for whoever picks
  this up next.
- **Per-field composition in `_db_resilience_headline`** — when one of
  its four sections fails, the WHOLE headline renders the failure rather
  than splicing a caveat onto the sections that did succeed. Simpler and
  correctly conservative (never shows a wrong number), but a future
  refinement could show the three good sections with a footnote on the
  fourth instead.
- **`privilege_audit`'s `default_acl` field** still has no honest-absence
  floor of its own (only `roles` does) — `default_acl` empty IS a
  legitimate real state (no default-ACL rows at all is common), so no
  floor was warranted there; recording its own `_errors` entry (done) is
  sufficient without also gating on emptiness.

## Tests

- `test_schema_enumeration_floor.py` (new, 8 tests): `_enumerate_relations()`
  returns the raw floor data and raises rather than defaulting;
  `get_credential_capability()` uses the shared floor and records
  `_errors` on failure; `get_schema_info()` fills in zero-privilege
  schemas with their real tables, never duplicates an already-visible
  schema, records `_errors` when the floor pass itself fails, and agrees
  with `get_credential_capability()` on `table_total` end-to-end.
- `test_postgres_catalog_fallback.py` (4 new tests, in a new
  `TestSchemaInventoryResultsNameRelationKindsSeparately` class):
  `base_table_count`/`view_count`/`materialized_view_count`/
  `foreign_table_count` are each counted correctly against a mixed-kind
  fixture and an all-base-tables fixture.
- `test_collector_honesty.py` (new, 16 tests): each converted collector
  records the right `_errors` entry on a forced failure and stays clean
  (no `_errors` key) when nothing fails; `_merge_collector_errors`/
  `_collection_failed_headline` unit-tested directly; each of the three
  updated headline readers renders "Collection failed" on a forced
  section failure and its normal sentence otherwise; the
  `privilege_audit` case specifically confirms a recorded error wins over
  the pre-existing empty-roles honest-absence floor.
- Confirmed directly against the real `coco_pharma` registry (not a
  fixture): every converted collector runs clean (`_errors` is `None`)
  against the live connection — the new error-recording paths are not
  spuriously firing on real, working queries.
- Full suite: [pending — recorded once the background run finishes].

## Live signed-in gate

**Not yet run.** Needs a real signed-in session, and a fresh survey run
against `coco_pharma` (the enumeration floor only affects a schema-survey
step's OUTPUT going forward, not already-stored rows) to confirm, on
screen:

- The credential banner and "How big is this database" agree on
  `coco_pharma`'s schema and table totals (8 schemas, 61 tables).
- `demo`/`demo_auth` appear as tables in a schema-level view once one
  exists (slice 22) — until then, confirm via `_schema_inventory_results`'s
  raw `tables` list that they're present with `state: catalog_estimate`
  rather than absent.
- A forced collector failure (e.g., temporarily revoking a permission
  `pg_stat_replication` needs, or disconnecting mid-survey) renders as
  "Collection failed (...): ... — re-run." on the resilience/external
  -dependencies/privilege-audit rows, not as an empty or zero-valued
  sentence.

Whoever runs this: append the outcome here, one sentence per screen, per
the coordinator brief's own gate convention.
