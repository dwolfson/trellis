# Brief — primary-path keys and the structured-table clobber (2026-09-27)

Hand-off for a fresh coordinator session. Two correctness defects found on
the first AdventureWorks pass (`laz_local_adventureworks`, native Postgres
on `localhost:5432`, loaded 2026-09-27) and verified with `psql` against the
database. Both feed Slice 22 (the per-schema inventory view) and every
derived database card, so they land **before** Slice 22 merges.

Companion small fixes (#1 activity-headline key, #4 scouting run status,
#5–#7 wording) are on `re/adventureworks-correctness` and are not repeated
here.

Rules that apply: one worktree, one PR, one `*-IMPLEMENTED.md`; DCO
sign-off on every commit; the serving checkout at
`~/localGit/egeria-v6/trellis` is only ever fast-forwarded; gate on **both**
`localhost_docker_coco_pharma` and `laz_local_adventureworks`.

---

## A. Primary-path PK/FK capture drops keys

### Evidence

Truth from `pg_constraint` on `adventureworks` versus rows stored in
`database_columns` for any of the eight runs on 2026-09-27:

| | truth | stored |
|---|---|---|
| FK columns `(table, column)` | 91 | 71 |
| PK columns | 181 | 99 |

Every one of the 20 missing FK columns points at a heavily referenced
table (`person.businessentity` ×5, `production.product` ×4,
`person.countryregion` ×2, `person.stateprovince`, `person.address` for
`billtoaddressid`/`shiptoaddressid`, …):

```
humanresources.employee.businessentityid
person.stateprovince.territoryid
production.document.owner
purchasing.productvendor.productid
purchasing.productvendor.unitmeasurecode
purchasing.purchaseorderdetail.productid
purchasing.purchaseorderheader.employeeid
purchasing.vendor.businessentityid
sales.countryregioncurrency.countryregioncode
sales.customer.personid
sales.personcreditcard.businessentityid
sales.salesorderheader.billtoaddressid
sales.salesorderheader.shipmethodid
sales.salesorderheader.shiptoaddressid
sales.salesperson.businessentityid
sales.salestaxrate.stateprovinceid
sales.salesterritory.countryregioncode
sales.shoppingcartitem.productid
sales.specialofferproduct.productid
sales.store.businessentityid
```

Downstream effects already visible on the Discovery tab: Relationship
Graph reports 71 edges / 8 components / largest 24 (undercounts); Table
Grain says keys captured 68 of 68, which is right only because every
AdventureWorks table happens to keep at least one PK column through the
loss.

### Where

`resource_explorer/surveyors/database/connection.py`:

- `_get_tables_for_schema()` ~lines 620–710 builds `pk_lookup` (keyed by
  `table_name`) and `fk_lookup` (keyed by `(table_name, column_name)`) from
  `information_schema` queries. The FK query joins
  `constraint_column_usage`, which is not keyed per column and multiplies
  or collapses rows when the referenced table has several referencing
  constraints. The PK query has the same shape.
- `_catalog_keys_for_schema()` ~lines 804–850 is the **catalog-only
  fallback** added in Slice 21b. It reads `pg_constraint` / `pg_index`
  directly under identity A and is correct. On coco_pharma it took PK
  coverage from 3 to 21 of 58 tables with no extra privilege.

### Fix

1. Promote the fallback's `pg_constraint`/`pg_index` queries to the
   primary path: `_get_tables_for_schema()` calls
   `_catalog_keys_for_schema()` (or a shared helper) instead of the
   `information_schema` queries. Key both lookups by
   `(schema, table, column)`; a composite FK contributes one entry per
   column; a column that carries two FKs (rare, legal) keeps a list.
2. Delete the `information_schema` PK/FK queries once nothing calls them.
3. Re-survey both databases; store nothing new for coco_pharma beyond the
   run itself.

### Tests

- Unit: a fake `execute_query` returning `pg_constraint` rows for a
  referenced table with three referencing constraints, one composite FK,
  and one column with two FKs; assert 91-style counts, not 71.
- Live check written into the IMPLEMENTED doc as numbers:

```bash
/Applications/Postgres.app/Contents/Versions/16/bin/psql -p 5432 -U dwolfson -d adventureworks -Atc "select count(distinct (conrelid, k)) from pg_constraint, unnest(conkey) k where contype='f'; select count(*) from pg_constraint, unnest(conkey) where contype='p';"
```

must equal the stored `database_columns` counts for the new run.

### Gate

Discovery on `laz_local_adventureworks`: Relationship Graph edge count ≥ 86
(distinct table pairs; 90 constraints) and components fewer than 8; the
per-schema line on the model card names no schema as "not established
(keys_not_captured)". coco_pharma unchanged or better.

---

## B. Per-step runs write structured rows they did not collect

### Evidence

`database_table_activity` for `laz_local_adventureworks`, eight runs, all
157 rows each:

| surveyed_at | step that ran | rows_inserted sum | reads sum | NULL counters |
|---|---|---|---|---|
| 19:20:22 | scouting step 1 (schema+stats) | 761,184 | 861 | 87 (views) |
| 19:20:31 | scouting step 2 | NULL | 0 | 157 |
| 19:20:32 | scouting step 3 | NULL | 0 | 157 |
| 19:23:52 | credential_capability | NULL | 0 | 157 |
| 19:23:55 | db_resilience | NULL | 0 | 157 |
| 19:23:57 | row_count_snapshot | NULL | 0 | 157 |
| 19:24:00 | db_activity_signals | 761,184 | 861 | 87 |
| 19:24:03 | schema_inventory | NULL | 0 | 157 |

`db_derived.load_inputs()` (`db_derived.py` ~line 290) reads every
structured table at the **latest** `surveyed_at`. After the owner's last
run (19:24:03, no activity collected) `db_classification` reported
"No data for: activity" on a database with 761k inserts, and
"Derived from 2 of 4 signal families".

This is the same class as the three `_store_results` incidents in
`survey_data` (row_count/size_bytes; operations/credential_capability;
Slice 12's empty operations section), now one layer down in the
structured tables. `docs/Backlog.md` already carries the generic
`_store_results` item; this brief makes it concrete.

### Where

- `resource_explorer/surveyors/database/result_materializer.py` (or
  wherever `database_table_activity` / `database_columns` /
  `database_column_profiles` rows are written per run — grep
  `database_table_activity` in `registry.py` and the surveyor) writes a
  row per table regardless of whether the run's steps produced the
  section.
- `db_derived.load_inputs()` picks one `surveyed_at` for every table.

### Fix

1. **Write only what was collected.** A run writes rows to a structured
   table only when one of its steps produced that section. No section →
   no rows for that `surveyed_at`. Apply the same rule to `survey_data`
   sections (closes the generic Backlog item): merge-in this run's
   sections over the prior row's, never replace with empties.
2. **Read per table, newest non-empty.** `load_inputs()` resolves
   `surveyed_at` per structured table: the newest run for the slug that
   has rows in that table (and, for activity, at least one non-NULL
   counter). Carry each table's `surveyed_at` on `DerivedInputs` so
   provenance can say "activity from 19:24:00, structure from 19:24:03".
3. Back-fill is not required; the old NULL rows become harmless once the
   reader skips them. Optionally delete NULL-only activity rows in a
   migration and say so.

### Tests

- `test_store_results_preserves_prior_stats.py` and
  `test_store_results_preserves_prior_operations.py` already cover the
  `survey_data` layer; add the structured-table twin: run a step that
  collects only `schema_info`, assert no `database_table_activity` rows
  for that `surveyed_at`, and assert `load_inputs()` still returns the
  earlier run's activity.
- A ratchet: after any single-analysis run on a fixture, `load_inputs()`
  must return the same activity totals as before the run.

### Gate

On `laz_local_adventureworks`: run `schema_inventory` alone, then
`db_classification`. The classification card must say "Derived from 4 of
4 signal families", name activity as measured (writes 761,184+), and the
evidence panel must show which run each family came from. Repeat on
coco_pharma; nothing regresses.

---

## Order and size

A first (it changes what B reads), then B. Both are Opus-sized. Neither
touches `app.js`. Expect two PRs; report each tip to the design session
for CI polling and merge.
