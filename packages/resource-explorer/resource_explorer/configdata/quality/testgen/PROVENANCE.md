# Vendored catalogue: DataKitchen DataOps TestGen test types (Postgres, slice 1 and Q6)

Data only. No TestGen code is vendored and TestGen is never run: Resource Explorer reads these files
and executes the checks with its own steps (`surveyors/database/quality/`). The engine and analysis names
Resource Explorer shows are its own ("value profile", "quality checks"); Apache-2.0 grants no trademark,
so the upstream product name appears only here, in `NOTICE` and in the developer docs.

- **Upstream repository:** https://github.com/DataKitchen/dataops-testgen
- **Copied from:** the owner's fork, https://github.com/dwolfson/dataops-testgen (checkout
  `~/localGit/egeria-v6/dataops-testgen`). The fork's `testgen/` tree is identical to upstream at the
  commit below.
- **Commit:** `3606859cf8bb4f809d2b19acc51462420829c4ab` ("release: 5.92.2 -> 5.134.0", 2026-10-14),
  **release 5.134.0**.
- **Copied:** 2026-10-20 (slice 1); 2026-10-26 (Q6: Recency, Future_Date_1Y, `before_20yr_date_ct`, the
  templated functions and the date branch of the functional-type inference), from the same commit. The clone's
  HEAD was `e8a5a906`, one docs commit on top of `3606859c`; its `testgen/` tree is identical to `3606859c`.
- **License:** Apache-2.0 (`LICENSE`, verbatim). `NOTICE` is DataKitchen's, verbatim.

## Files

| Vendored file | Upstream path | How |
|---|---|---|
| `test_types/Missing_Pct.yaml` | `testgen/template/dbsetup_test_types/test_types_Missing_Pct.yaml` | unchanged |
| `test_types/Required.yaml` | `testgen/template/dbsetup_test_types/test_types_Required.yaml` | unchanged |
| `test_types/Required_No_Placeholder.yaml` | `testgen/template/dbsetup_test_types/test_types_Required_No_Placeholder.yaml` | unchanged |
| `test_types/Unique.yaml` | `testgen/template/dbsetup_test_types/test_types_Unique.yaml` | unchanged |
| `test_types/Future_Date.yaml` | `testgen/template/dbsetup_test_types/test_types_Future_Date.yaml` | unchanged |
| `test_types/Min_Date.yaml` | `testgen/template/dbsetup_test_types/test_types_Min_Date.yaml` | unchanged |
| `test_types/Row_Ct_Pct.yaml` | `testgen/template/dbsetup_test_types/test_types_Row_Ct_Pct.yaml` | unchanged |
| `test_types/Recency.yaml` | `testgen/template/dbsetup_test_types/test_types_Recency.yaml` | unchanged (Q6) |
| `test_types/Future_Date_1Y.yaml` | `testgen/template/dbsetup_test_types/test_types_Future_Date_1Y.yaml` | unchanged (Q6) |
| `postgresql/profile_measures.sql` | `testgen/template/flavors/postgresql/profiling/project_profiling_query.sql` | subset: the measure lines for `record_ct`, `value_ct`, `distinct_value_ct`, `null_value_ct`, `zero_length_ct`, `filled_value_ct`, `min_date`, `max_date`, `future_date_ct` and (Q6) `before_20yr_date_ct`, each verbatim, under upstream's `TG-IF` flag names; a header comment added |
| `postgresql/templated_functions.yaml` | `testgen/template/flavors/postgresql/profiling/templated_functions.yaml` | subset (Q6): `DATEDIFF_DAY` and `DATEDIFF_MONTH`, verbatim; a header comment added |
| `profiling/functional_datatype_date.sql` | `testgen/template/profiling/functional_datatype.sql` | subset (Q6): the eight statements that can label a date column (upstream lines 18-25, 28-36, 39-43, 45-49, 72-116, 136-142, 228-262, 356-366), verbatim and in upstream order, each headed by its line range; a header comment added |
| `postgresql/general_type.sql` | `testgen/template/flavors/postgresql/data_chars/get_schema_ddf.sql` | subset: the `general_type` CASE, verbatim; a header comment added |
| `LICENSE`, `NOTICE` | `LICENSE`, `NOTICE` | unchanged |

Slice 1 is seven test types (`docs/design-notes/DESIGN-VALUE-PROFILE-AND-QUALITY-CHECKS.md`). Q6 adds
Recency, whose selection rule reads `functional_data_type`, and Future_Date_1Y
(`docs/design-notes/DESIGN-QUALITY-Q6-RECENCY.md`).

## How the catalogue is used

- **Target-side SQL runs verbatim.** Each YAML's Postgres `cat_test_conditions` entry (`measure`,
  `test_operator`, `test_condition`) is what `run_quality_checks` executes against the surveyed database,
  with every parameter validated by type before it is substituted.
- **Selection rules run as Python.** `selection_criteria` is Postgres SQL over TestGen's own
  `profile_results`; Resource Explorer's registry may be SQLite. Each rule is ported to a Python
  predicate pinned to the SHA-256 of the fragment it came from (`quality/catalogue.py`), and a test fails
  when the vendored fragment no longer matches its pin. The `general_type` CASE is ported the same way, and
  so are the date statements of the functional-type inference (`quality/functional_type.py`) and
  Recency's default threshold, which is an expression rather than a value.

## Updating

`scripts/sync_quality_catalog.py --check --upstream <testgen checkout>` diffs this copy against an
upstream checkout (each YAML's `selection_criteria`, `default_parm_columns`, `default_parm_values` and
Postgres `cat_test_conditions`, the profile SQL subset, and new test types) and writes nothing.
Adopting an upstream change is a deliberate commit: copy the file, update the commit above, and re-port
any predicate whose pin the tests then report.
