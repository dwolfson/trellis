# DESIGN — Quality port step 6: the rest of the functional-type inference, and the nineteen types that read it (2026-10-29)

**Status:** built on branch `claude/re-quality-6-functional-type`, pushed, not merged, not deployed. Step 6 of the port
order in `DESIGN-QUALITY-Q4-PORT-PLAN-AND-CALIBRATION.md` §5.

**Decision (project owner, 2026-10-29):** "Approve, start now" for quality step 6; the DDL is approved: a nullable
`functional_data_type`, and `functional_table_type` if stored per table, on `database_value_profiles`, applied at the next
8813 restart after merge. DDL record: `../ddl-value-profile-step6.md`.

No query was run against any database to build or test this slice, no Egeria write, no write to the shared registry
(`:5442`). Every test uses a tmp SQLite file and canned rows.

## 1. What was ported, and from where

Everything comes from the TestGen clone `~/localGit/egeria-v6/dataops-testgen` (HEAD `e8a5a906`, one docs commit on
`3606859c`; `git diff --stat 3606859c HEAD -- testgen/` is empty).

| Vendored file | Upstream file | What |
|---|---|---|
| `profiling/functional_datatype.sql` | `testgen/template/profiling/functional_datatype.sql` (629 lines) | **unchanged.** Ported statement for statement in `quality/functional_infer.py`, pinned by SHA-256 |
| `profiling/functional_tabletype_stage.sql` | `testgen/template/profiling/functional_tabletype_stage.sql` | **unchanged.** The table period (cumulative or window) and the table type, ported as `table_period` and `table_kind` |
| `test_types/{19 names}.yaml` | `testgen/template/dbsetup_test_types/test_types_<Name>.yaml` | unchanged |
| `postgresql/templated_functions.yaml` | `flavors/postgresql/profiling/templated_functions.yaml` | one more entry, `DATEDIFF_WEEK`, verbatim (Weekly_Rec_Ct's measure) |

`profiling/functional_datatype_date.sql` (Q6's subset) stays; `functional_type.py` still serves Recency. `scripts/sync_quality_catalog.py
--check` now also checks the two whole files byte for byte; against the clone it reports "in step with upstream".

## 2. The design: a label is the set of values it could still end with

Upstream's CASE statements read measures RE does not take yet. In SQL a NULL there falls through to the next arm, so
"not measured" reads as "no" — the collapse this repo's find-absence rule exists to prevent. Porting the file as ordered
UPDATEs over a single label would have either invented labels (treating NULL as no) or refused to label anything.

`functional_infer.py` instead tracks, per column, **the set of values `functional_data_type` could end with** (`None` in
the set is NULL, nothing has labelled it):

- a statement whose condition is false changes nothing; true sets its label; **unknown adds its possible results** to the
  set (`apply`, `case_set`). The IS NULL guards, the unguarded overwrites (Process prefix, the Period overrides, Process
  and System User by name) and the CASE arm order are the file's own;
- a set of one label is the column's label (`Inference.label`). A set of more is **no label**, and `Inference.why` says
  why: `type not inferred · a text column; needs min_text, avg_embedded_spaces, …, which the profile does not take yet
  (profile slice 2)`. There is no default type and no 'UNKNOWN' unless upstream's own last statement would have given it;
- a selection rule asks `label_in(possible, test)`: **true** (every label it could be passes), **false** (none does: the
  rule really says no, so a number is not flooded with `not_established` for a text rule) or **unknown**;
- a measure upstream takes only for text (`min_text`, `numeric_ct`, `avg_embedded_spaces`, `frequent_patterns`, …) is NULL
  by construction on any other column, as upstream's; it is unknown only on a text column.

What the stored measures settle: TBD, Constant, the ID masks, ID-Unique / ID-Unique-SK / ID-Secondary / ID-Group, ID-FK
(across the tables of one profile batch), every date label Q6 settled plus Date Stamp / DateTime Stamp, the Process
prefix, Process User, System User, Boolean for B and for a 0/1 number, Sequence, an ID or Attribute-Numeric by name,
Measurement Discrete, Measurement, Measurement Pct, Period Year / Quarter / Month / Week / DOW for a number.
What they cannot settle is **text**: Zip, Email, Phone, Address, State, City, the person and entity names, Code, Category,
Attribute, Description, Flag, ID by shape, Period Mon-NN and Year-Mon all read the text-shape measures (profile slice 2,
port step 7). They stay in the column's possible set, so a text column answers `not_established` for exactly the
rules that could be about its label.

**Measurement Spike** needs the 25th, 50th and 75th percentiles, which RE does not take. It is ruled out (so the column is
a Measurement or Measurement Discrete) when a spike cannot happen from what is stored: the values are mostly filled and
all on one side of zero, or the zeros are too few for the three percentiles to be 0 (`zero_value_ct < (value_ct - 1)/2 - 1`,
a bound, not an estimate). Otherwise the column stays "could be a spike" and the Measure rules say so. See §7.

**Table type.** `functional_tabletype_stage.sql` reads the table's record count over its profile history. RE stores that
(every batch), so the period is `table_period` over `registry.value_profile_record_counts`: 'window' if any count fell
between two measured runs, else 'cumulative'. A run that did not measure the table is skipped, never read as 0. The type
(summary, transaction, entity, bridge, domain) is `table_kind` over the labels, when every column has one label; else the
column holds the period alone (`'cumulative'`), which is all the rules read.

## 3. The nineteen types

All are CAT. "Selects now" means the rule can answer true on a column the stored measures settle; "waits" names what is
missing, as the `not_established` reason does.

| Type | Reads | Now |
|---|---|---|
| Min_Val | Measure% label, `min_value` | selects on a numeric Measurement |
| Avg_Shift, Incr_Avg_Shift | Measure% (not Spike), `distinct_value_ct`, not lat/long | selects; run measure and params ported (`baseline_avg` is new) |
| Outlier_Pct_Above, Outlier_Pct_Below | label `Measurement`, `stdev_value / avg_value` | selects; a zero mean is unknown (a division error upstream) |
| Variability_Increase, Variability_Decrease | Measure%, `stdev_value > 0`, `avg_value` | selects |
| Unique_Pct | label not Measurement% | selects on numbers and dates; a text column is `not_established` while it could be Measurement Pct |
| Dec_Trunc | `fractional_sum > 0`, table `cumulative` | selects once the table has two profile runs |
| Distinct_Date_Ct | Transactional Date%, `date_days_present`, table `cumulative` | selects when the date CASE settles; the Wk/Mo branches wait |
| Monthly_Rec_Ct, Weekly_Rec_Ct | + `date_months_present` / `date_weeks_present` | waits: those two measures are not taken |
| Valid_US_Zip, Valid_US_Zip3, Valid_Month | label `Zip`, `Zip3`, `Period Month` | a "no" wherever the label is ruled out (most columns); waits on text shape where it is not. Valid_Month's default reads `min_text` |
| Alpha_Trunc, Pattern_Match, Distinct_Value_Ct, LOV_Match | `numeric_ct`, `frequent_patterns`, `frequent_values` | waits: profile slice 2 and port step 8 |

A type that waits still has its selection rule ported and pinned, its vendored run measure, and a default-parameter port
that raises a `ParameterError` naming the measure it needs, so nothing is silently half-built.

## 4. Departures from the brief or from TestGen, with reasons

1. **A single profile run does not give a table a period.** Upstream's SUM over a NULL first difference makes every table
   'cumulative' after one run, so Dec_Trunc, Distinct_Date_Ct, Monthly_Rec_Ct and Weekly_Rec_Ct are proposed on run 1 there.
   One count is not a trend; RE reads fewer than two measured runs as "not inferred". `functional_infer.SINGLE_PROFILE_IS_CUMULATIVE`
   flips it to upstream's behaviour in one line. **Needs the owner's word** (open item 1).
2. **Text columns get no label.** Not a departure from TestGen, which labels them from measures RE does not take; but it
   means roughly half of family C's reach waits for profile slice 2 (step 7). Stated, not hidden.
3. **`Transactional Date (Qtr)` is never concluded.** Upstream's `datediff('QUARTER', ...)` uses `DATE_PART('qtr', ...)`, which
   Postgres rejects, so the arm cannot run as vendored; RE keeps it as a possibility. The Wk and Mo arms wait on
   `date_weeks_present` / `date_months_present`.
4. **Measurement Spike** is ruled out by a bound, not by percentiles (§2). A column the bound cannot rule out is not a
   Measurement for the Measure rules until a person or a later slice settles it. Adding the three percentiles would settle
   it exactly; that is more DDL (three columns) and needs the owner's word (open item 2).
5. **`numeric_scale` is read at profile time only.** The inference needs a number's scale (Measurement Discrete, ID by name),
   which the profile reads from the catalog. Propose has no catalog read, so a NULL row recomputed at propose time treats
   the scale as unknown; a stored label is used as it stands.
6. **City and ID-FK** are cross-row. ID-FK is ported across the tables of one batch; City is kept as a possibility for a text
   column (it reads neighbours' labels and text shape).
7. **A non-profiled column** (a view, a table over budget, no privilege) gets one `not_established` row per family C type,
   as every earlier type does. That is nineteen more per such column; it is the existing behaviour, not new.
8. **`Distinct_Value_Ct` is selected by its `selection_criteria`**, not by `gen_Distinct_Value_Ct.sql` (a different upstream
   generator, for constants whose value changes); the template is not vendored.
9. **Egeria:** the nineteen are not published as `DataQualityRule`s here; no publish path was added or exercised for them.

## 5. Cost

None measured. The inference is pure over the profile rows: it runs no query against the surveyed database and adds no
measure to the profile read. Its cost is Python over the batch (not timed) plus one aggregate query on `database_value_profiles`
for the record-count history (a GROUP BY over RE's own registry, not a surveyed database). There is no local static copy of coco_pharma or
adventureworks, and nothing was run against a live registered database.

## 6. Calibration against TestGen (Q4 §6)

Not run: the harness is in `egeria-workspaces-fs`, outside RE, and there is no static copy. Rows to add, per type, and what
can and cannot be calibrated:

- **Label agreement.** For every column of the static copy where RE gives one label, TestGen's `functional_data_type` must
  equal it; where RE gives a set, TestGen's label must be a member. Zero unexplained disagreements is the gate. Expected
  explained ones: a table's first profile (departure 1), text columns (set, not label), Spike (departure 4).
- **Selection agreement per type.** For each of the nineteen: RE true ⇒ TestGen generates it; TestGen generates it ⇒ RE true
  or `not_established` (never false). RE false and TestGen true is a defect. Cannot be calibrated yet: Alpha_Trunc,
  Pattern_Match, Distinct_Value_Ct, LOV_Match, Monthly_Rec_Ct, Weekly_Rec_Ct (always `not_established` here), and
  Valid_Month's baseline.
- **Run agreement.** The measure is TestGen's, verbatim; agreement is on the same baseline.

## 7. Open items for the owner

1. Single profile run: 'cumulative' as upstream does, or "not inferred" as built (departure 1)?
2. Add the three percentile columns so Measurement Spike is settled exactly (departure 4)? Or accept the bound?
3. Publish the nineteen as `DataQualityRule`s (the Q5 path), or leave them local for now?
4. Timing on the largest tables for the added aggregate query: needs the static restore.

## 8. Tests

`tests/test_quality_step_6_functional_type.py` (33 tests): the vendored files and every pin; the inference statement by
statement; a column the measures cannot settle says why and gets no default; the table period and type; both columns
exist on a fresh registry and are added to an old one; the profile stores the label and leaves what it cannot settle NULL;
each selection rule, including the three-valued cases; defaults and rendered measures, which parse as Postgres. Four
existing tests changed for expected reasons: the ported-set equality, the proposal count (12 → 14: Unique_Pct on two
columns), the statement-parse test (new parameters), and the b1a opt-in count.
