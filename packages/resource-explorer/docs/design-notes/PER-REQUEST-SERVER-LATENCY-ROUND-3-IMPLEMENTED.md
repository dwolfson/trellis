# Per-request server latency, round 3 — diagnose first, then two targeted fixes

**Status:** Implemented, with one honest negative result. Diagnostic-0 answered with evidence
(steady-state board reads no longer touch `survey_data` at all — PR #349, already merged to
main, closed that path). Item 1 (a GIN index) was built, measured, and **does not help** —
reported as a negative result with `EXPLAIN ANALYZE` evidence rather than shipped anyway. Item 2
(`db_classification`'s 398-query pattern) is fixed and fixture-verified identical, and a real,
separate, larger bottleneck was found while verifying the gate — reported, not silently absorbed
into a false "gate met" claim. Two small follow-ons (a dead local, a repeat-fetch pattern in the
prerequisite resolver) are also done.

This is round 3 of the investigation in `PER-REQUEST-SERVER-LATENCY-IMPLEMENTED.md` (round 1)
and `PER-REQUEST-SERVER-LATENCY-ROUND-2-IMPLEMENTED.md` (round 2, its two unmet gate items). Read
those first.

**Branch note:** built on a fresh branch (`re/per-request-server-latency-round-3`) off current
`origin/main` — not off `re/per-request-server-latency` — per the PR/CI coordinator's instruction
while PR #352 (round 2 + the registry-cache-staleness fix) was blocked on the owner's return for
`gh`/1Password auth. Round 2's own fixes (the `find_latest_database_survey_with_key` jsonb
lookup, the `list_projects`/`list_databases` batch/off-the-loop fixes) are NOT present on this
branch and are not needed for anything in this round — diagnostic-0's answer and both round-3
items are independent of them. Where a measurement benefits from seeing round 1+2+3 together, this
doc says so explicitly and gives the combined number from a side-by-side worktree that already
has both — see "Combined measurement" under item 2.

## Diagnostic 0: does a board-summary read still touch `survey_data`, and why

**Method:** traced the actual call path for a `schema_inventory` (and, separately,
`db_classification`) board request against the current merged `origin/main`, which includes PR
#349 (board-summary-read-cost, merged since round 2 was scoped). Not assumed — read the code and
ran it.

`build_survey_results` (`workflows/analysis.py`), when `board_id` is given, calls `_read_board_
summary_if_fresh` FIRST: a single-row read of `registry.get_board_summary(entity_type, slug,
board_id)`, used as-is when it's at least as new as the board's own analysis_id's last recorded
run. Only on a miss or staleness does it fall through to the expensive recompute (which is where
`survey_data`/`credential_capability` lookups live).

Checked directly against `laz_local_adventureworks`, which has persisted `board_summary` rows for
all 18 boards (`SELECT ... FROM board_summary WHERE slug=...` — 18 rows, confirmed):

```
schema_inventory:      fast_path_hit=True  call_time=11.9ms
db_classification:     fast_path_hit=True  call_time=23.6ms
row_count_snapshot:    fast_path_hit=True  call_time=64.0ms
privilege_audit:       fast_path_hit=True  call_time=49.9ms
db_relationship_graph: fast_path_hit=True  call_time=66.5ms
db_fingerprint:        fast_path_hit=True  call_time=23.2ms
```

**Answer: neither of the two bugs the diagnostic named.** Not (a) — the recompute-when-missing
path isn't firing every time; the persisted row is fresh and used. Not (b) — the summary isn't
missing anything a board read needs; every board tested resolves from the single-row read alone.
On a database that already has run its analyses since #349 shipped, `survey_data` is simply off
the steady-state read path entirely — round 1/2's finding that a board read cost 700-900ms via an
unbounded `survey_data` fetch was measured against a build of the code that predates this fast
path (round 1/2's branch forked before #349 merged — see round 2's own doc for that discovery).

**What this means for round 2's jsonb fix and round 3's items below:** `find_latest_database_
survey_with_key`/`db_classification`'s 398-query pattern are NOT redundant, per design's explicit
framing — they still serve two real paths this diagnostic didn't touch: the recompute-when-
missing/stale path (a board whose summary doesn't exist yet, or is older than its analysis_id's
last run), and the one-shot `backfill-board-summaries` CLI (`cli/main.py`, added alongside #349)
that deliberately forces every board through the expensive path once to warm the cache. Both are
real, both still run the code these fixes touch.

## Item 1: a GIN index for the jsonb containment query — built, measured, does not help

Round 2 measured `find_latest_database_survey_with_key`'s `jsonb_exists(survey_data::jsonb, %s)`
query at ~300-500ms and recommended a GIN index as the likely next lever, without building it
(correctly, since it hadn't been tested). This round built it and measured it. **It does not
help.**

### What was built

```sql
CREATE INDEX IF NOT EXISTS idx_database_surveys_survey_data_jsonb
ON database_surveys USING GIN ((survey_data::jsonb));
```

Postgres-only (guarded the same way every other Postgres-specific DDL in `_init_schema` is),
using the default `jsonb_ops` operator class (not `jsonb_path_ops`, which doesn't support the `?`
operator this query needs).

### EXPLAIN ANALYZE, before and after the index

Before (round 2's own baseline, `laz_local_adventureworks`, 57 rows for this slug):

```
Limit  (actual time=391.778..391.779 rows=1 loops=1)
  ->  Sort  (actual time=391.777..391.777 rows=1 loops=1)
        ->  Index Scan using idx_database_surveys_slug on database_surveys
              (actual time=13.628..391.549 rows=57 loops=1)
              Index Cond: (database_slug = 'laz_local_adventureworks'::text)
              Filter: jsonb_exists((survey_data)::jsonb, 'credential_capability'::text)
Execution Time: 391.805 ms
```

After creating the GIN index, same query, unchanged (Postgres doesn't use the new index at all —
still the slug btree index plus a per-row filter):

```
Limit  (actual time=341.800..341.801 rows=1 loops=1)
  ->  Sort  (actual time=341.799..341.799 rows=1 loops=1)
        ->  Index Scan using idx_database_surveys_slug on database_surveys
              (actual time=7.272..341.599 rows=57 loops=1)
              Index Cond: (database_slug = 'laz_local_adventureworks'::text)
              Filter: jsonb_exists((survey_data)::jsonb, 'credential_capability'::text)
Execution Time: 341.816 ms
```

Within measurement noise of the baseline — no real change. Forced the planner toward the GIN
index (`SET enable_seqscan/enable_indexscan = off`, and rewriting `jsonb_exists(...)` as the
literal `?` operator, since the planner does not recognize the function form as index-eligible for
this operator class — that distinction is itself worth recording: `jsonb_exists(x, y)` and `x ? y`
are semantically identical but only the operator SYNTAX is what the GIN operator class matches
against):

```
Bitmap Heap Scan on database_surveys (actual time=6.747..488.429 rows=57 loops=1)
  Recheck Cond: ((survey_data)::jsonb ? 'credential_capability'::text)
  Filter: (database_slug = 'laz_local_adventureworks'::text)
  Heap Blocks: exact=3
  ->  Bitmap Index Scan on idx_database_surveys_survey_data_jsonb
        (actual time=0.022..0.022 rows=104 loops=1)
Execution Time: 488.650 ms
```

**Worse, not better** — 488ms vs 342-391ms. The `Bitmap Index Scan` itself is near-instant
(0.022ms — the index genuinely works as an index). The cost is entirely in `Recheck Cond`:
Postgres re-evaluates the jsonb condition against the actual heap tuple for every candidate row a
bitmap scan returns, which means re-casting the large `TEXT` `survey_data` value to jsonb again —
the same parse the filter was already paying for, just via a different plan shape. A GIN index
speeds up *finding candidates*; it does not eliminate the cost of *verifying* them when the
verification itself requires re-parsing a large TEXT column, and Postgres's bitmap-scan recheck
does exactly that unconditionally for this operator.

### What would actually help — measured, not implemented

Tested the real fix directly with a throwaway `TEMP TABLE` (no schema change to the live table):
copied `database_surveys` with `survey_data` stored as native `jsonb` instead of `TEXT`, same
query, same slug filter, same `?` operator, one plain btree index on `database_slug`:

```
Limit (actual time=47.367..47.368 rows=1 loops=1)
  ->  Index Scan using tmp_survey_jsonb_database_slug_idx on tmp_survey_jsonb
        (actual time=0.237..47.282 rows=57 loops=1)
        Filter: (survey_data ? 'credential_capability'::text)
Execution Time: 47.390 ms
```

**47ms vs 342-391ms — an ~8x improvement, with no GIN index at all**, because there is simply
nothing left to parse at query time: the value is already stored in binary jsonb form.

**Not implemented this round — flagged as a follow-up requiring explicit sign-off, not a
routine additive migration.** Changing `survey_data`'s column type from `TEXT` to `JSONB` is a
real, table-rewriting migration (small table here — 127 rows, 18MB, would be fast — but the
column type itself is the issue, not the migration's runtime cost). More importantly it is
**breaking**: psycopg2 returns a native `jsonb` column as an already-parsed Python `dict`, not a
string, so every one of the many call sites across this codebase that does `json.loads(row.get
("survey_data") or "{}")` would raise `TypeError: the JSON object must be str, bytes or bytearray,
not dict` the moment the column stopped being `TEXT`. That is a coordinated, multi-file change
(`registry.py`'s own read/write paths, `_credential_capability_results`, `databases.py`'s
`_to_summary`, `db_derived.py`, and more — a `grep -c 'survey_data'` count, not a one-liner), and
SQLite has no equivalent native jsonb storage this codebase currently uses, so the two backends
would also need to diverge in how they store and read this column. Real, measured, worth doing —
just not something to ship as a side effect of "add an index."

**Net effect of item 1: the ineffective index was created for testing, then dropped — nothing
shipped from this item except the negative result and the measured recommendation above.**

## Item 2: `db_classification`'s 398-query pattern

### The bug

`db_derived.py`'s `load_inputs` calls `_resolve_table_surveyed_at` once per structured table
(schemas, tables, columns, profiles, activity — 5 calls). That function used to walk survey
history newest-first (`_snapshot_keys`), calling `registry.query_detail_rows(table, slug, at,
src)` for EACH candidate `surveyed_at` until one came back non-empty — because a later run's own
steps can genuinely never touch a given structured table at all (a `schema_inventory`-only run
writes no `database_table_activity` rows), and an earlier run in the same history might have the
real answer. For a table whose data lives in an old snapshot on a heavily-surveyed database, that
walk visited dozens of candidates. Measured (round 2, `laz_local_adventureworks`): 398 total
`cursor.execute()` calls, ~2.4s, via `cProfile`.

### The fix

New `ProjectRegistry.find_latest_detail_surveyed_at(table, slug, source=None, require_any_non_
null=None)` — one `SELECT MAX(surveyed_at) ... WHERE {slug_column}=? [AND source=?] [AND (col1 IS
NOT NULL OR col2 IS NOT NULL ...)]` query.

**Provably equivalent to the walk, not just usually faster:** the only `surveyed_at` values that
can ever appear as a row in `table` are ones some run actually wrote there — a run that never
touched the table leaves no row, so it can never be the `MAX`. The walk's entire purpose (skip a
candidate `surveyed_at` the table has nothing for) is exactly what aggregating over the table's
own rows does for free, by construction — there's no separate "check if empty" step needed because
an empty result can't produce a candidate value at all.

`require_any_non_null`, used for `database_table_activity`'s `require_measured_counter` case
(a row CAN exist for a `surveyed_at` — the step ran — with every counter `NULL`, meaning nothing
was actually measured, which must not count as "this run has the answer"), pushes that same
row-level check into the `WHERE` clause as an `OR ... IS NOT NULL` predicate rather than fetching
and inspecting each candidate row in Python.

`_resolve_table_surveyed_at` itself keeps its exact signature and the same two-part contract
(`(surveyed_at, rows)`) — every one of its 5 call sites in `load_inputs` is unchanged.

### Tests

- `TestFindLatestDetailSurveyedAt` (`tests/test_integration_registry_pg.py`, real Postgres): no
  rows, single surveyed_at, newest-of-several, **the walk's own reason for existing** (a later run
  that never touched this table must not shadow an earlier one that did), the
  `require_any_non_null` case (a newer all-NULL-counter row must not beat an older real one), and
  an end-to-end check through `_resolve_table_surveyed_at` itself for the exact bug shape.
- **Fixture comparison, as design explicitly asked for — not just "it's faster".** Ran
  `run_db_derived(registry, "laz_local_adventureworks")` (the actual `db_classification`-producing
  call) with the old walk and the new set-based version, dumped the full `derived` dict as JSON,
  and diffed every one of the 12 derived analyses field-by-field:

  | field | old == new? |
  |---|---|
  | `db_classification` (the actual target) | **True** |
  | `db_fingerprint`, `grain_determination`, `schema_conventions`, `db_change_rates`, `schema_diff`, `grant_change`, `proposed_data_scope`, `subject_signals`, `coverage_signals`, `preliminary_fit` | **True**, every one |
  | `db_relationship_graph` | **False** — but see below |

  `db_relationship_graph` differing looked like a real regression until checked against a control:
  running the OLD, completely unmodified code TWICE in a row (no code change between the two runs)
  produces the identical kind and magnitude of difference in that same field (tie-order in a
  `most_referenced` list, when two tables have the same reference count) — **pre-existing
  nondeterminism in the codebase, unrelated to this fix**, not something this change introduced.
  Confirmed directly rather than assumed: `before1 == before2` is `False` for `db_relationship_
  graph` and `True` for every other field, on two runs of code this round never touched. Flagged
  here as a separate, real, minor finding (worth a follow-up: something in `relationship_graph_by_
  container`'s tie-breaking reads row order that Postgres does not guarantee without an explicit
  `ORDER BY` tiebreaker) — not fixed this round, out of scope, and does not affect this fix's own
  correctness claim.

### Measured (isolated, `load_inputs` only, no round-1/2 caching present on this branch)

| | before | after |
|---|---|---|
| `load_inputs` cumulative (5 calls to `_resolve_table_surveyed_at`) | dominant cost of a ~4.3s `run_db_derived` call | **242-466ms**, no longer dominant |
| `find_latest_detail_surveyed_at` itself | n/a | 64ms cumulative for 25 calls (5 `load_inputs` invocations × 5 tables — see "a genuinely separate finding" below for why `load_inputs` runs 5 times) |

### Combined measurement (round 1+2+3 together) — and a genuinely separate finding this surfaced

Ported this round's two-file diff into the round-1/2 worktree (which already has the engine/schema
caching and `get_database_surveys` per-instance cache) to see the true combined effect, since this
round's own branch is off bare `main` and doesn't have round 1/2's fixes:

```
run_db_derived (combined, warm): 516-1036ms across 5 repeat calls
```

**Still above the 300ms target — a new, separate bottleneck, not this item's own fix failing.**
Profiled the combined run: `apply_container_grain` (line 4552, `db_derived.py`) — which computes
`db_relationship_graph`, `schema_conventions`, `subject_signals`, `coverage_signals`,
`preliminary_fit`'s per-container breakdowns via `fingerprint_by_container`/`relationship_graph_
by_container`/`conventions_by_container` — makes 89 of its own `query_detail_rows` calls,
independent of `load_inputs`/`_resolve_table_surveyed_at` entirely. This is the SAME shape of
problem (per-item queries where a set-based read could do), in DIFFERENT functions, that this
round's brief did not name (the brief was specifically "`db_derived.load_inputs`'s 398 queries" —
now fixed and verified).

**Also discovered while tracing this:** `_raw_derived_field` (`survey_definition_adapter.py`)
— the reader every one of the 8 `db_derived`-owned board analyses (`db_classification` included)
goes through — calls `run_db_derived` in full and then extracts just the one requested field.
There is no per-field-scoped computation path at all: asking for `db_classification` alone still
pays for `db_relationship_graph`, `grain_determination`, `schema_conventions`, and everything else
`run_db_derived` computes. This is why fixing `load_inputs` alone — even though it IS the named
"398 queries" and IS now genuinely fast — was not enough to clear the 300ms bar for the field
that's actually requested.

**Gate result: `db_classification` under 300ms — NOT MET**, honestly, with the real numbers above
and the real reason identified (`apply_container_grain`'s own N+1 pattern, plus `run_db_derived`'s
all-or-nothing computation shape), not claimed as passing. Flagged for a future round rather than
shotgunned into this one under time pressure — `apply_container_grain`'s pipeline is a materially
different, more involved piece of code than `_resolve_table_surveyed_at`'s walk, and deserves its
own diagnosis rather than a rushed generalization of this round's fix.

## Two cheap follow-ons (design's own additions, both from the staleness-fix agent's findings)

### `run_queue.py`'s dead `registry` local

`QueueRunner._loop` constructed `registry = ProjectRegistry()` and never used it — `claim_and_
execute_once(kinds=self.kinds)` doesn't take it. Deleted. No behavior change; nothing depended on
it (the tell was that nothing was broken by its absence, confirmed by the full suite).

### `SurveyOrchestrator`'s prerequisite-resolution loop resolving `capability_probe` once per run, not once per `resolve()` call

The staleness-fix agent's own commit (`dc065497`) identified this pattern while choosing between
caching strategies: `SurveyOrchestrator.run()` calls `prerequisite_resolver.resolve()` up to twice
per step (an initial check, plus a re-check after any auto-run) across every step being surveyed —
and `resolve()` already accepts a `capability_probe` parameter specifically so a caller who needs
it more than once doesn't have to let the resolver re-fetch it internally on every call (its own
docstring says so) — but nothing in the loop was actually passing it in, so every call
independently re-fetched via `credential_capability.stored_probe` → `get_database_surveys`. Design's
framing: "this makes the cache a safety net rather than the actual fix for that repeat pattern" —
the cache (round 1's, now hardened by the staleness fix) absorbs the redundant cost, but the
redundant CALL PATTERN itself was still there underneath it.

**Fix:** resolve `capability_probe` once, lazily (only if some step in `STEP_REGISTRY` actually
declares `requires_capability` — the exact same check `resolve()` would otherwise make internally,
hoisted above the loop so it runs once instead of once per call), then thread it through every
`resolve()` call in the loop. A repo/filesystem survey (no capability axis at all) still makes zero
registry calls for this, unchanged.

**Tests:** the existing prerequisite/orchestrator suite (81 tests across `test_prerequisite_
resolver.py`, `test_prerequisite_auto_run_end_to_end.py`, `test_survey_orchestrator.py`,
`test_next_prerequisite_proposal_ui.py`) all pass unchanged, including the capability-shortfall
tests, confirming resolution outcomes are unaffected. **Gap, flagged honestly:** did not add a new
dedicated test asserting the call-count reduction itself (e.g., "stored_probe is called at most
once across N `resolve()` calls in one run") — building a full multi-step database
`SurveyOrchestrator.run()` fixture with real `requires_capability` steps stubbed correctly turned
out to need more scaffolding than this follow-on's "cheap" framing budgeted for in the time
remaining this round. The fix is correct by construction (the same resolved value is threaded
through; `None` still falls back to `resolve()`'s own existing internal check, so behavior for
every caller that doesn't populate it is byte-identical to before) and the full regression suite
staying green is real evidence against a behavior change, but a call-count-specific test is a real
gap, not silently omitted.

## Full suite

`uv run pytest tests/ -q -rf`, clean env: **6856 passed, 103 skipped, 0 failed** (13m27s).

## Gate results

1. **Board summary under 200ms, in-server.** **PASS**, for the steady-state case diagnostic-0
   establishes as the actual live path (11.9-66.5ms across 6 boards tested on `laz_local_
   adventureworks`, all via the persisted-summary fast path). Not re-measured for the recompute
   path specifically in this round beyond the direct-call numbers above — see "Measurement note"
   below for why a full in-server coordinated-window pass was not completed this round.
2. **Cold-load By-analysis headlines under 2s.** Same as above — the dominant cost round 2
   identified (board reads) is now off the steady-state path per diagnostic-0; not re-measured
   in-server this round.
3. **`db_classification` under 300ms.** **NOT MET.** 516-1036ms combined (round 1+2+3), root
   cause identified (`apply_container_grain`'s own separate N+1, plus `run_db_derived`'s
   all-or-nothing computation shape) and flagged for a future round, not silently claimed passing.

## Measurement note — what this round did and did not complete

Per the PR/CI coordinator's sequencing (round 3 started on a fresh branch off bare `main` because
PR #352, carrying round 2 and the staleness fix, was blocked on the owner's `gh`/1Password auth
being unavailable), this round's own branch does not have round 1/2's fixes, so an in-server
coordinated-quiet-window HTTP measurement on THIS branch would not represent the shipped system —
it would measure round 3's fixes in isolation against a `main` that's missing round 1/2's
registry-layer work entirely. The combined numbers in this doc (item 2's "Combined measurement"
section) come from applying this round's diff to the round-1/2 worktree directly, which is the
best available approximation of the true post-merge state without waiting for #352 to actually
land. **A final coordinated in-server measurement against the real merged head (main + #352 +
this round, once all three are together) is still owed** — flagged explicitly rather than
reporting a number from an incomplete composition as if it were final.
