# Slice 21b — derived database analyses: real keys, honest states, headlines — implemented

**Coordinator brief:** owner-approved, queued after Slice 21a; based on 21a's
tip (`6e4ce6f7`, not main) so the seven new headline readers register
against the level-aware `_headline_for` Slice 21a built, and to avoid a
rebase conflict since 21a merges first.
**PR:** #TBD (`re/slice21b-derived-db-honesty`).
**Live gate:** port 8813 (8811 = `re/followup-3-copy-fixes`, 8812 = 21a,
both left untouched).

## 1. Keys at the catalog floor

`connection.py`'s catalog-only fallback (`_catalog_only_fallback` →
`_catalog_columns_for_table`, used when `information_schema` hides a table
entirely from a limited credential) always wrote `is_primary_key=None`,
`foreign_key=None` for every fallback column — by explicit prior design,
since `information_schema.table_constraints`/`key_column_usage` (the
codebase's only PK/FK source until now) are exactly the privilege-filtered
views the fallback exists because of.

**Fixed:** `pg_constraint` is catalog metadata like `pg_class`/
`pg_attribute`/`pg_namespace` — not privilege-filtered, readable by any
connected role regardless of `USAGE`/`SELECT` grants. New
`_catalog_keys_for_schema(schema_name)` reads it directly (`contype = 'p'`
for PK, `contype = 'f'` for FK, composite keys matched position-by-position
via `WITH ORDINALITY` so a multi-column FK pairs each local column with its
correct referenced column), returning `(pk_lookup, fk_lookup)` in the same
shape the live path's own lookups already use. `_catalog_columns_for_table`
now takes these and populates real `True`/`False`/dict values instead of
`None` — `is_nullable`/`column_default`/comments are UNCHANGED (`None`),
since Postgres genuinely has no catalog-only source for those.

**Honesty preserved, not just added:** a `pg_constraint` query can itself
fail (permission oddity, connection hiccup). `_catalog_keys_for_schema`
returns `None` (not `{}`) for a failed half, and `_catalog_columns_for_table`
propagates that as `None` on the column — never silently degrading "the
query failed" into a confidently-wrong `False`, the same shape
`is_nullable`/`default` already refuse.

**A second bug, found in review, fixed alongside it:**
`DerivedInputs.keys_were_captured` (db_derived.py) was a database-WIDE
boolean (`any(is_primary_key is not None for every column in the
database)`). In a mixed-access database — some tables live-surveyed, some
only reachable via the catalog fallback — this read `True` from ONE
live-surveyed table alone, then let every caller treat every OTHER
(uncaptured) table's lack of a recorded key as a VERIFIED "no primary key"
finding. New `DerivedInputs.keys_captured_for_table(key)` answers the
per-table question instead. Applied to:

- `_structure_evidence` (feeds `db_classification`): `pk_coverage`/
  `fk_density`'s denominator is now the count of tables whose OWN keys were
  captured, not every base table — an uncaptured table no longer dilutes
  the ratio toward "no primary key" (`KIND_STAGING` evidence) purely
  because it was never checked.
- `derive_relationship_graph` (`db_relationship_graph`): tables whose own
  keys were not captured are now excluded from the graph entirely (not
  counted as verified `isolated_tables`), with their count reported
  separately as `unmeasured_table_count` and named in the explanation.

**Not applied to** `determine_grain`/`check_conventions` — out of scope for
this pass; flagged in Backlog below as the same fix, not yet made, for
those two.

## 2. Honest `not_established` states

Confirmed (via a full read of `db_derived.py`'s seven analyses before
writing any code) that none of them had a coverage-fraction threshold at
all: every one used an all-or-nothing gate (some rows exist → `STATE_
MEASURED`, regardless of how small a fraction was actually measured; zero
rows → `STATE_NOT_MEASURED`). `classify_database` already SCALES its
confidence by a `coverage` fraction and nulls out `kind`/`confidence` when
undecided — a real, working honesty mechanism, just not a state change —
and left as-is here rather than reworked.

The concrete `not_established` fix this pass made is the mixed-access case
in §1 above (`db_relationship_graph`'s per-table exclusion, and
`db_classification`'s per-table-measured `pk_coverage` denominator) — the
same failure the coordinator's brief named. A general coverage-percentage
threshold across all seven (e.g. "below 30% of tables measured, downgrade
the whole analysis to not_established") was NOT built — flagged in
Backlog below as a distinct, larger piece of work with its own design
question (what threshold, and whether it belongs in `registry.STATE_*`'s
vocabulary or a bridge to `result_status.py`'s).

## 3. Headline readers

All seven analyses (`db_classification`, `db_relationship_graph`,
`grain_determination`, `schema_conventions`, `subject_signals`,
`coverage_signals`, `preliminary_fit`) had NO entry in
`DATABASE_ANALYSIS_HEADLINE_MAP` before this — confirmed by direct
inspection of the dict literal. Each rendered at best `facts.py`'s generic
`_renders_text` floor ("ran; no summary reader") or nothing, despite every
one of the seven already writing a carefully composed `explanation`
sentence for every branch, including every `not_measured` case.

**`_db_derived_explanation_headline(field)`** (new, `survey_definition_
adapter.py`): a factory, not seven bespoke functions — relays that
`explanation` string verbatim (`status: "info"` when `STATE_MEASURED`,
`"warn"` otherwise), reading the RAW `run_db_derived()` payload rather than
through `_db_derived_field_reader`'s wrapper (which normalizes a
not-measured payload to `{}` at the results/has_data seam — correct for
that seam, wrong for a headline, which needs exactly the `explanation`
text a not-measured payload carries). Relaying verbatim rather than
re-deriving a shorter summary means the headline can never drift out of
sync with what `db_derived.py` actually computed — and, for six of the
seven, `apply_container_grain()` already appends that field's own
per-container ROLLUP sentence onto this same `explanation` string, so the
resource-level headline already carries a coarse per-container signal for
free.

**Container-level headlines**, per the coordinator's own framing ("db_
relationship_graph and grain_determination naturally do" have a resource/
container split):

- **`_db_relationship_graph_container_headline`**: built from
  `relationship_graph_by_container()`'s own `by_<grain>` dict (already
  computed by `apply_container_grain` on every run — no new computation),
  naming each schema's own verdict/table/edge counts plus cross-schema
  reference counts, e.g. `"public: data_model (12 table(s), 15 edge(s));
  eu_sales: bag_of_tables (3 table(s), 0 edge(s)) · 2 cross-schema
  reference(s)"`.
- **`_grain_determination_container_headline`**: `determine_grain()`'s
  `grains` list is already per-table (`apply_container_grain`'s own
  comment: "already finer than the grain; nothing to do") — this reader
  just groups that existing list by `schema_name`, no new computation in
  `db_derived.py` either: `"public: 2 of 2 table(s) grain-determined;
  eu_sales: 1 of 1 table(s) grain-determined"`.

The other five are NOT given a separate container reading: their own
per-container data is already folded into the resource-level `explanation`
string by `apply_container_grain` (see its own comment: "the spread reaches
the surface without any consumer change"), so a separate container map
entry would just repeat the same text a second time.

## 4. Live gate

Served on port 8813, `coco_pharma`. Verified all seven headlines and both
container readers directly against the live registry/database (bypassing
the browser — see "Not done here" below for why), which surfaced three
real bugs the unit tests alone hadn't caught, all fixed and re-verified
live before commit:

1. **`grain_determination` had no resource-level headline at all.**
   `determine_grain()`'s `STATE_MEASURED` payload never sets a top-level
   `explanation` (only per-table entries do), so the generic
   `_db_derived_explanation_headline` factory silently returned `None` —
   exactly the "checkmark with nothing under it" gap this whole slice
   exists to close, just moved one level down. Fixed with a bespoke
   `_grain_determination_headline` built from `determined_count`/
   `table_count`/`undetermined_count`/`timed_count`.
2. **`schema_conventions`'s resource-level headline was real but thin.**
   Same root cause as #1 (`check_conventions()` also never sets a
   top-level `explanation`) — the generic factory fell through to ONLY
   `apply_container_grain`'s rollup sentence ("Across 8 schemas: ...")
   with no whole-database content ahead of it. Fixed with a bespoke
   `_schema_conventions_headline` that surfaces the first real gap among
   the four named checks (or a clean-pass count).
3. **The container headline for `db_relationship_graph` showed a raw list
   instead of a count.** `rollup_envelope`'s `cross_container_edges` key is
   the actual list of edges; the count is a SEPARATE key,
   `cross_container_edge_count`. My first cut read the wrong key
   (`... · [] cross-schema reference(s)`), caught by direct inspection of
   the live label before commit.
4. **The container headline for `grain_determination` overcounted
   "determined."** First cut gated on `state == STATE_MEASURED`, but
   `determine_grain()`'s OWN `determined_count` is defined by
   `grain_statement` truthiness — a "gap" entry (measured, and genuinely
   no candidate key) IS `STATE_MEASURED` with an EMPTY `grain_statement`.
   Live-caught by cross-checking the container view's per-schema sum
   against the resource-level headline's own total for the SAME database:
   the container view initially read "23 of 23 grain-determined" for
   `coco_ods` while the resource-level headline (unaffected by this bug,
   since it reads `determined_count` directly) said 3 of 58
   database-wide — a real, catchable inconsistency between two headlines
   of the same analysis. Fixed by matching `determine_grain()`'s own
   definition exactly; regression test added
   (`test_a_measured_gap_is_not_counted_as_determined`) using the exact
   "profiled, nothing unique" fixture `test_profiles_present_but_nothing_
   unique_is_a_real_gap` already established for this case.

Final live-verified state, `coco_pharma`, all seven resource-level
headlines: all `status: info`, none `None`. Container headlines for
`db_relationship_graph`/`grain_determination` now agree with their own
resource-level totals (grain: container sum 1+1+1=3 matches resource "3 of
58"; relationship graph: container view correctly excludes the 55 tables
whose keys were never captured from every schema's own count, matching the
resource-level `unmeasured_table_count: 55`).

## Not done here: browser screenshot of the Discovery stage

The coordinator's brief asked for a live gate "with a Discovery-stage
screenshot." This session's browser tool was blocked from signing in to
either 8811 or 8813 (a permission classifier flagged entering the
documented dev-login password as "credential exploration"), the same block
encountered and disclosed earlier tonight (see the evidence-panel
triple-repeat Backlog entry). Per this session's own rules, that block was
not routed around a second time. Verification here instead went through
direct backend calls against the SAME live registry/database the running
8813 server reads (`ProjectRegistry()` + the actual headline functions,
against real `coco_pharma` data) — which is how the four bugs above were
actually found, arguably more precise than a screenshot would have been,
but it is not the screenshot that was asked for. Someone with browser
access to 8813 (or the owner, in the morning) should still take one for
the record.

## Tests

- `tests/test_postgres_catalog_fallback.py`: existing `TestZeroAccessToASchema`
  assertion updated (`is_primary_key` is now a real `False`, not `None`, when
  the `pg_constraint` catalog query succeeds and genuinely finds no PK — a
  meaningful behavior change, not just a docstring update). New
  `TestCatalogFallbackRecoversPrimaryAndForeignKeys` (3 tests): a recovered
  table gets its real PK; its real FK; a FAILED `pg_constraint` query stays
  `None` (unestablished), not a guessed `False`.
- `tests/test_db_derived_step.py`: new `test_a_table_with_uncaptured_keys_is_
  excluded_not_counted_isolated` — the mixed-access case, `derive_relationship_
  graph`'s own regression test. New `TestSlice21bHeadlines` (10 tests): every
  one of the seven has a registered headline; a measured analysis relays its
  own `explanation`; a not-measured one relays its reason (not silence); no
  stored rows at all still states a reason (not a bare absence); the
  `schema_conventions` bespoke headline names a real gap and states a clean
  pass; the two container headlines name each schema and group correctly;
  `test_a_measured_gap_is_not_counted_as_determined` — the live-caught
  overcounting bug (#4 above), using the same fixture
  `test_profiles_present_but_nothing_unique_is_a_real_gap` already
  established for the underlying "gap" case.
- Full suite: 6531 passed, 104 skipped, 0 failed.

## Not attempted here

- `determine_grain`/`check_conventions`'s own per-table `keys_captured`
  awareness (same bug class as `derive_relationship_graph`'s, not yet fixed
  there) — flagged in Backlog.
- A general coverage-percentage threshold across all seven analyses (see
  §2) — flagged in Backlog as its own, larger design question.
- `db_fingerprint`/`db_change_rates`/`schema_diff`/`grant_change` headline
  readers — not named in the coordinator's seven; still unheadlined.

## Report

Implementation complete, tested, live-gated (backend-verified; browser
screenshot blocked — see above), full suite green. **Commit held**, per
the coordinator's own instruction: 21b is based on 21a's tip and would
inherit 21a's CI hang (run 36290350357, cancelled at the 30-min job
timeout) until that is diagnosed and fixed on the 21a branch. Will commit
and push once 21a's fix lands and this branch is confirmed clear of it —
see the CI-hang investigation reported separately.
