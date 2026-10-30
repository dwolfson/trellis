# DESIGN — Quality B1d: the monitors, as simple stated rules over RE's own series (2026-10-29)

**Status:** design only. No code, no DDL, no write to Egeria, to the shared registry or to a surveyed database. Nothing
here was run; every statement about TestGen comes from reading its source (clone `~/localGit/egeria-v6/dataops-testgen`,
HEAD `e8a5a906`, whose `testgen/` tree is identical to the vendored commit **`3606859c`**, release 5.134.0) and every
statement about RE from reading its code. Where a claim needs a run to be true, it says so.

This is B1d of `DESIGN-QUALITY-Q4-PORT-PLAN-AND-CALIBRATION.md` (§4 table, §5 row 8, §7 question 4): the monitors that
step 8 deliberately left out.

**Decision (project owner, 2026-10-26):** the Q4 note's seven §7 recommendations were accepted. Question 4 is the one that
bears here: "defer B1d past step 8, and when it comes, use a simple rule over RE's result series (the last N results,
min/max with a stated margin), recorded as the rule on the result, not called a prediction. Adding statsmodels to RE for
three types is not worth it now."

**Decision (project owner, 2026-10-29):** "we need the monitors planned too" (relayed by the coordinating session).

## 1. What TestGen has, from its source

TestGen's **Monitor** generation set is three types. A fourth is its Table Comparison cousin and a fifth needs a person's
SQL. Read from `testgen/template/dbsetup_test_types/`:

| Type | `run_type` | Set | Severity | What it measures | Upstream's rule | Upstream's minimum history |
|---|---|---|---|---|---|---|
| `Volume_Trend` | CAT | Monitor | Fail | `COUNT(CASE WHEN {SUBSET_CONDITION} THEN 1 END)`, one per non-dropped table (`gen_Volume_Trend.sql`) | fails when the count is `NOT BETWEEN` a lower and upper tolerance. Tolerances come from a SARIMAX forecast (`statsmodels`) with a t- or z-multiple of the forecast's standard error by sensitivity (low 3.0, medium 2.5, high 2.0), or, when a person sets one, from `history_calculation` over the last `history_lookback` results (`Value`, `Minimum`, `Maximum`, `Sum`, `Average`, or `EXPR:[...]`) | `predict_min_lookback`, default **30** results; SARIMAX itself refuses under **8** points (`MIN_TRAIN_VALUES`) |
| `Freshness_Trend` | QUERY | Monitor | Fail | a table **fingerprint**: `MD5` of `COUNT(*)` plus, for up to five columns chosen by `gen_Freshness_Trend.sql` (two IDs, one process date, one transactional date, one numeric measure), `MIN`, `MAX`, `COUNT(DISTINCT)`, sums. The result signal is `0` when the fingerprint changed since the last run and otherwise the minutes since it last did | the **gaps** between consecutive changes: upper = the larger of the 95th percentile of the gaps and 1.25 × the longest gap; lower = the 10th percentile (medium sensitivity; high is 80/1.0/20, low 99/1.5/5), over the newest 40 gaps (`MAX_FRESHNESS_GAPS`). Late when no change has arrived and the wait passes the upper bound (or, once a schedule is inferred, 0.85 × the median gap); unexpected when a change arrives before the lower bound or after the upper | **5** completed gaps (`MIN_FRESHNESS_GAPS`); fewer and the test is in "training mode" (result code -1, no verdict) |
| `Table_Freshness` | QUERY | none (it has a generation template, `gen_Table_Freshness.sql`, but no set) | Log | the same kind of fingerprint | fails (at Log) when the fingerprint equals the previous one: `lower_tolerance` holds "the most recent prior table fingerprint" | one prior result |
| `Schema_Drift` | METADATA | Monitor | | the table's columns against the previous test run | already ported as step 5 (`DESIGN-QUALITY-STEPS-4-5-DUPE-ROWS-AND-DRIFT.md`), reading two stored surveys | n/a here |
| `Metric_Trend` | CAT | none | Fail | a **person's** SQL expression | the same SARIMAX band as Volume_Trend | as Volume_Trend |

Two facts the inventory did not state, and that shape everything below:

1. **Freshness_Trend's rule is not SARIMAX.** `get_freshness_gap_threshold` is percentiles and a multiple of the longest gap
   over a sliding window: a stated rule already. Only its *schedule inference* (`infer_schedule`), weekend and holiday
   exclusion, and the staleness factor are elaborate, and they are optional (they apply only when the suite has a
   timezone, or when exclusions are set). So Freshness can be ported **near-exactly**, without a statistical library.
2. **Only Volume_Trend (and Metric_Trend, which is out) needs a stand-in for SARIMAX.** Freshness-gating (Volume's
   SARIMAX is first fitted on only the runs where Freshness_Trend saw a change, to stop stair-step tables from raising
   false alarms) is upstream's answer to the same problem §2.1 meets with a "restart the series" action.

`Metric_Trend` is out of this note: it is custom SQL, which the Q4 plan (family F) keeps out until a check editor and an
execution boundary exist.

None of these four is vendored yet. The first slice (§7) vendors `Volume_Trend`, `Freshness_Trend` and `Table_Freshness`
byte-identical with their three `gen_*` templates, pinned and checked by `scripts/sync_quality_catalog.py` the way every
earlier slice was. `Schema_Drift` is already vendored.

## 2. The rules, in plain words

Every rule is a stated rule over a series RE already stores. Each is recorded **as the rule** on the result (its words,
its window, its margin), never called a prediction. A result states the band it applied; the rule's words live in one
module (`monitor_rules.WORDS`, proposed) so a ruling is one edit.

### 2.1 Volume_Trend: "the row count is within the range of its recent runs"

- **Series.** The table's row count at each past run of this check (§3.1).
- **Window.** The last **20** usable results of this check for this table. The result being judged is not in its own window.
- **Minimum history.** **8** usable results (the floor SARIMAX itself imposes upstream). Upstream's default of 30 was
  chosen for a monitor that runs on its own frequent cron; at RE's cadence (§4.5) 30 results can be months. See question 1.
- **Band.** Lower = the smallest count in the window minus `m`; upper = the largest plus `m`; `m` = **10 %** of the window's
  median count (so a flat series tolerates a 10 % move, a noisy one is as wide as it has been). The lower bound is never
  below 0.
- **Verdict.** `fail` (at the check's severity, Fail) when the count is outside the band, as upstream's `NOT BETWEEN`.
  `pass` inside it.
- **Usable.** A prior result counts when it concluded (`CONCLUDED` in `run_checks`) with a numeric measure, for the same
  `check_key`, and with the same `subset_condition` as now. A result that could not measure (`not_measured`,
  `not_permitted`, error) is skipped and counted; a change of subset condition **restarts the series** (the older
  results are for a different population).
- **Too little history.** `not_established`, never a pass: "Not enough history: 3 of 8 runs." (words in §5).
- **A change that is meant.** A table that is reloaded or truncated fails once, then its new level enters the window,
  and the old level stays in it for up to 20 runs, so the next runs may sit inside a band that is too wide. The honest
  remedy is the one upstream reaches with freshness gating, done by a person: "this change is expected — restart the
  series" records `series_start` (a timestamp) in the verdict's `params_json`, and the window then holds only results at or
  after it. No DDL (the verdict already stores `params_json` as accepted). See question 6.
- **Parameters** (all in `params_json`, editable like any threshold): `window` (20), `min_history` (8), `margin_pct` (10),
  `series_start` (none), `subset_condition` (none).

### 2.2 Freshness_Trend: "the table is written to as often as it has been"

- **Series.** A run's *update events* (§3.2): the survey times at which the table was seen to have changed since the survey
  before. The values the rule reads are the **gaps** between consecutive update events, in minutes.
- **Window.** The newest **40** gaps (upstream's constant).
- **Minimum history.** **5** completed gaps, so 6 update events (upstream's constant). Fewer: `not_established`,
  "Not enough history: 3 of 5 gaps."
- **Band** (upstream's medium sensitivity, unchanged): upper = the larger of the 95th percentile of the gaps and 1.25 × the
  longest gap; lower = the 10th percentile, kept only if above 0. Percentile as `numpy.percentile` (linear interpolation),
  so a replay against upstream agrees to the float (§6).
- **Verdict at a run.**
  - The table changed since the survey before: the wait since the previous update event is compared with the band.
    Inside it, `pass` ("updated, on time"); below the lower bound, `fail` ("earlier than expected"); above the upper,
    `fail` ("later than expected").
  - The table did not change: if the wait since the last update event is beyond the upper bound, `fail` ("late");
    otherwise `pass` ("no update yet; still within the usual wait").
- **What v1 leaves out, on purpose.** Upstream's schedule inference (daily or weekly deadlines, active days, sub-daily
  windows), `exclude_weekends` and holiday codes. Without them a weekend gap on a weekday-only table is a long gap that
  widens the band, which makes the monitor late to fire, never early. That asymmetry is named on the result ("calendar
  time; weekends and holidays are not excluded").
- **Resolution.** The gap between two update events can be no finer than the time between two surveys. A table written
  to every five minutes, surveyed daily, has a one-day gap forever. The result says how often it looks (§4.5, §5).
- **Parameters:** `window` (40), `min_gaps` (5), `upper_percentile` (95), `floor_multiplier` (1.25), `lower_percentile` (10),
  `series_start`.

### 2.3 Table_Freshness: "the table has been written to since the last look"

- **Series.** The same signal as §2.2, reduced to the last two surveys.
- **Rule.** Upstream's: unchanged since the previous run fails at **Log**; changed passes. In RE's words the unchanged
  result is `logged`, the status the earlier slices already use for "did not hold, at severity Log".
- **Minimum history.** Two surveys. With one: `not_established`, "Only one survey is stored, so there is nothing to compare
  it with. This is not a finding that the table is unchanged." (the Schema_Drift sentence, reused).
- It is not in TestGen's Monitor set, so it is **opt-in per table**, with the Table Comparison watch (`table_comparison.set_watch`).

### 2.4 Schema_Drift

Unchanged. It already is a monitor in everything but name: two stored surveys, "not enough history" when there is one.

## 3. Where the series come from, and whether step 8 left anything to build

No monitor needs a new measurement taken for it. Each reads one of three stored series.

### 3.1 The row count (Volume)

`database_quality_results` has one row per (run, check): `UNIQUE(database_slug, surveyed_at, source, check_key)`, with
`measure`, `measure_text`, `record_ct`, `status`, `reason`, `threshold_values_json`, `params_json`. The per-table
statement in `run_checks.py` begins with `COUNT(*) AS record_ct` for every table that has at least one CAT check
(`run_checks.py:494`), so **every such run already holds the table's row count, for nothing**. `Volume_Trend` is a CAT
check whose measure is that count: a table that has any other accepted CAT check pays no extra read; a table that has only
this monitor pays one `COUNT(*)` inside the existing per-table budget (§4).

The detail tables are append-only per run. `write_detail_rows` replaces only the rows of the same `surveyed_at`; I found
nothing in `registry.py` that prunes older ones, so the history a window needs is there.

### 3.2 The update events (Freshness, Table_Freshness)

`database_table_activity` stores, per survey and table, the cumulative `pg_stat_user_tables` counters (`rows_inserted`,
`rows_updated`, `rows_deleted`), `live_tuples`, `dead_tuples`, the vacuum and analyze stamps, and **`stats_reset`**. An
*update event* is a survey at which `rows_inserted + rows_updated + rows_deleted` exceeds the previous survey's, provided
`stats_reset` is unchanged. That column was added for exactly this (its comment in `registry.py` is the reasoning): when
the reset stamp moves, the interval is *"counters reset, no rate available"*, not an event and not a "no change".

This is a **write-activity** signal, not a content comparison, and it must be worded as one: an update that sets a value
to itself counts as activity, and a table changed by a path the statistics do not count would not show. A table that is a
view, or one the survey could not read counters for, has no row, and the monitor says so (§5) instead of guessing.

### 3.3 The content fingerprint (Freshness, opt-in)

For a faithful port of upstream's signal, `gen_Freshness_Trend.sql`'s selection and fingerprint expression are Postgres SQL
over the profile's `functional_data_type` and measures. RE has had those since steps 6 and 7b, so selection ports as a
pinned predicate and the expression runs as a Postgres statement. It is the only part of B1d that **reads the table**,
which is why it is a later, opt-in slice (§7, B1d-4). The fingerprint's MD5 fits `database_quality_results.measure_text`.

Once value hashes are on (step 8, off by default), there is a second, zero-fetch content signal: a column's multiset hash
that is the same across two profile runs says its content is unchanged. That is a stronger statement than write activity
and costs nothing beyond the profile, but only for profiled columns and only when hashes were taken. Noted for question 3;
not designed further here.

### 3.4 What step 8 left, and what B1d still needs

Step 8 left what B1d needs untouched: the profile and result series exist and neither step 7 nor 8 changed their shape.
**B1d needs no DDL.** Retention is not a problem for a window of at most 40 (§3.1: nothing prunes). Two optional items:

- an index `database_quality_results (database_slug, check_key, surveyed_at)` so reading one check's newest 40 results does
  not walk the database's runs. Without it the existing `(database_slug, surveyed_at)` index bounds the read to the newest
  runs. Recommended only if measured slow. If wanted, it is a record for the owner like the step 7 and 8 DDL, applied at a
  restart, not by this change.
- a registry read `quality_result_series(slug, check_key, limit)` (code, not DDL). `query_detail_rows` offers only "latest
  run" and "one named run", so the series read is the one new storage function.

## 4. Cost at run time

| Monitor | Reads | Extra read of the surveyed database |
|---|---|---|
| Volume_Trend | up to 20 prior result rows from the registry | none for a table that has another accepted CAT check (the `COUNT(*)` is already in the per-table statement); one `COUNT(*)` for a table that has only this monitor, inside the per-table budget |
| Freshness_Trend (activity) | the table's last 41 activity snapshots from the registry | none: the counters were stored by the survey |
| Table_Freshness (activity) | the last two snapshots | none |
| Freshness_Trend (fingerprint, opt-in) | the profile's measures | one aggregate pass per table with `COUNT(DISTINCT)` on up to five columns: the profile's own cost class, under its own per-table budget (5 minutes, `not_measured · exceeded 5 min` when it runs out, as Dupe_Rows) |

**No timing number is claimed** — none exists. The static-restore timing run that step 6's note §11 describes is where the
fingerprint's cost and the single `COUNT(*)` on large tables are measured; the activity-based monitors have nothing to
time but registry reads of at most a few dozen rows per check.

### 4.5 Cadence is the limit, and it must be shown

A monitor sees the table only when something looks at it. TestGen's Monitor suite has its own cron. RE's monitors ride the
**DatabaseQualitySurvey** run (Q3: a work list, scheduled through `resource_schedules`), whose cadence is a person's
choice. Both Volume and Freshness say how often they look: "looked at 11 times in the last 20 days, median 41 h apart".
A table surveyed daily cannot be late by the hour. Question 5 asks whether a lighter run is wanted.

## 5. How results show, and publish

### 5.1 On screen

A monitor's result is a row in the table card's checks like any other, and its detail shows the measure with the band the
rule applied: the line chart upstream names (`result_visualization: line_chart`) with the band drawn, Volume's counts
against `[lower, upper]` per run. The states are RE's existing ones (`passed`, `failed`, `not_established`,
`not_measured`, `not_permitted`, and `logged` for Table_Freshness); no new vocabulary. **The words below are PROPOSED; the
project owner decides.** They live in `monitor_rules.WORDS`.

| Case | State | Words |
|---|---|---|
| Fewer usable results than the minimum | `not_established` | Not enough history: *n* of *m* runs. This is not a finding that the row count is normal. |
| Some earlier runs could not count rows | as the verdict | …*k* of the last *w* runs are used; *j* earlier runs could not count rows (timed out or not permitted). |
| Subset condition changed | `not_established` until the minimum | The condition on this check changed on *date*; only runs since then are compared. |
| Series restarted by a person | as the verdict | Compared with runs since *date*, when the project owner's role marked the earlier change as expected. |
| Inside the band | `passed` | 1,204 rows, within 1,050–1,300 (the range of the last 20 runs, ± 10 %). |
| Outside the band | `failed` | 2,410 rows, above 1,300 (the range of the last 20 runs, ± 10 %). Fails outside that range. |
| Freshness: fewer gaps than the minimum | `not_established` | Not enough history: 3 of 5 gaps between updates. This is not a finding that the table is fresh. |
| Freshness: on time | `passed` | Updated 2 h ago; the usual wait is 22–26 h (the last 12 updates). Looked at 11 times in 20 days. |
| Freshness: late | `failed` | No update seen for 31 h; the longest wait in the last 40 updates was 25 h (fails above 31 h). Calendar time; weekends and holidays are not excluded. |
| Freshness: earlier than usual | `failed` | Updated 20 min after the previous update; the shortest usual wait is 22 h. |
| Statistics reset since the previous survey | `not_established` | The database's statistics were reset after *date*, so the writes between those two surveys cannot be compared. This is not a finding that the table did not change. |
| No activity row (view, or not readable) | `not_measured` | Write activity is not measured for this table (a view, or the survey could not read its statistics). |
| Table_Freshness, unchanged | `logged` | No writes were seen between the surveys of *old* and *new*. |
| Table_Freshness, changed | `passed` | Writes were seen between the surveys of *old* and *new*. |
| Table_Freshness, one survey | `not_established` | Only one survey is stored, so there is nothing to compare it with. This is not a finding that the table is unchanged. |

### 5.2 To Egeria

Q5 publishes an accepted check as a `DataQualityRule` (`SPEC-PYEGERIA-DATA-QUALITY-RULE.md`; `GovernedBy` to the column or
table) and each run as a `QualityAnnotation` that carries the state word.

- **Volume_Trend publishes as a rule**, because it is CAT. Its threshold is a derived band, and Q5 already has the rule for
  that: `published_threshold` publishes, for a pinned expression condition, *the baseline the condition is built around*,
  never the computed limit. For Volume that is `margin_pct`; the rule's `method` and `expression` carry the sentence
  "row count within the range of the last *window* runs, ± *margin_pct* % of their median", and `comparisonOperator` is
  `mustBeBetween`. The run's annotation carries the band that run applied (`threshold_values_json`, already stored per
  result) and the measure.
- **Freshness_Trend and Table_Freshness are QUERY types.** `published_threshold` refuses a non-CAT type today with a
  sentence, and Q5 then skips the check as `unverified`. B1d does not change that: their runs publish as
  `QualityAnnotation`s (state, measure, the words) and no rule is written until the owner asks (question 7), the same
  position Dupe_Rows is in.
- **Absence words travel.** A `not_established` result is published as a `QualityAnnotation` in state `not_established`
  with the same sentence, never as a pass and never skipped silently, so "not enough history" is in Egeria as what it is.

## 6. Calibration against TestGen's monitors

The harness (`DESIGN-QUALITY-Q4-PORT-PLAN-AND-CALIBRATION.md` §6) lives in `egeria-workspaces-fs`, needs a TestGen runtime
and a static restore of coco_pharma or adventureworks (Q4 recommendation 5: evidence of record is never taken from a live
database), and has not been run for any family. For the monitors it is possible only in these ways:

| Monitor | Calibratable | How, and the expected asymmetry |
|---|---|---|
| Freshness_Trend, band | **yes, to the float** | Replay: take TestGen's `test_results.result_signal` history for a table (the gap series) and compute the band with RE's rule. Upstream's `get_freshness_gap_threshold` is the same percentiles; RE must agree when the suite has no timezone and no exclusions. With an inferred schedule upstream replaces the upper bound with a deadline: a **listed** asymmetry (v1 leaves schedule inference out), not counted as a miss |
| Freshness_Trend, verdict | partly | Needs the same update events. TestGen's events come from its fingerprint; RE's v1 from write activity. On a static copy with **scripted writes between runs** (insert, update, delete, and a no-op update) the two should agree except on the no-op update (activity says changed, fingerprint says not); that is the expected difference, listed. Not yet observed |
| Table_Freshness | yes, in fingerprint mode | The same MD5 expression gives the same fingerprint; the verdicts should agree exactly. In activity mode, as the row above |
| Volume_Trend | verdicts only | A SARIMAX band and a min/max band do not agree numerically and are not meant to. The comparison is **agreement on seeded anomalies** on a static copy: the same series of row counts with a known step, a known outlier and a known slow trend, run through both, and which runs each flags. Measures: seeded anomalies RE misses that TestGen catches (the number that matters), and false alarms RE raises on the quiet part. A disagreement on a slow trend is expected |
| Schema_Drift | no | Different windows (two surveys vs the previous test run), as step 5 recorded |

Two practical points. TestGen predicts only after `predict_min_lookback` results (default 30), so the throwaway suite must
set it to 8 or run at least 30 times; the calibration needs a **scripted, repeatable series of runs** on the restore with
mutations between them, not one run. And the run needs one peer round and the owner's go, as the timing run does.

## 7. Slices, DDL, and what is not claimed

| Slice | What | New data | DDL | Cost |
|---|---|---|---|---|
| B1d-0 | vendor `Volume_Trend`, `Freshness_Trend`, `Table_Freshness` and their three `gen_*` templates, byte-identical; pins and `sync_quality_catalog.py` checks; `Metric_Trend` recorded as not ported (custom SQL) | none | none | none |
| B1d-1 | `quality_result_series` read; the Volume rule and its words; selection (every profiled table, §2.1); tests | none | none (optional index, §3.4) | zero or one `COUNT(*)` |
| B1d-2 | Freshness_Trend and Table_Freshness over write activity; the `stats_reset` guard; tests | none | none | registry reads only |
| B1d-3 | the band on the screen; publish: Volume as a rule, the others as annotations | none | none | none |
| B1d-4 | opt-in **fingerprint** mode for Freshness_Trend and Table_Freshness (the selection and expression ported from `gen_Freshness_Trend.sql`), under its own budget | the MD5 in `measure_text` (column exists) | none | one aggregate pass per table |
| B1d-5 | calibration replay (§6): after the restart that applies steps 7 and 8, after the static-restore timing run, each through a peer round | none | none | owner-scheduled |

**DDL for B1d: none.** The optional index is a record, not part of any slice unless the owner wants it.

**Not claimed.** No timing or cost number. No statement that write activity equals "content changed". No equivalence of
Volume's band with SARIMAX's. Any figure in §5's words is an example.

## 8. Departures from TestGen, with the reason

1. **Volume's band is a stated min/max ± margin, not a SARIMAX forecast** (the owner's ruling, §7 Q4 of the Q4 note).
2. **Minimum history 8, not 30** for Volume, with upstream's own 8 as the floor and RE's slower cadence as the reason.
3. **Freshness over write activity in v1, not a content fingerprint**, to keep the monitors zero-fetch; the fingerprint is
   B1d-4, opt-in.
4. **No schedule inference, weekend or holiday exclusion in v1**; the asymmetry is named on every freshness result.
5. **Monitors ride the quality survey's cadence**, not a monitor cron of their own.
6. **Freshness-gating of the volume series is replaced by a person's "restart the series"**, not by a second model.
7. **A first look, or too little history, is `not_established`**, where TestGen's training mode is "result code -1".

## 9. Questions for the project owner

1. **Volume's constants.** Window 20, minimum history 8, margin 10 % of the window median. *Recommendation:* as stated; they
   are parameters on the check, so a table can be tuned. The alternative is upstream's 30 minimum.
2. **Freshness's constants.** Upstream's medium sensitivity unchanged: 5 gaps minimum, newest 40, 95th percentile, 1.25 ×
   longest gap, 10th percentile. *Recommendation:* yes, unchanged, no schedule inference in v1.
3. **Freshness signal.** Write activity (zero-fetch, said to be activity not content) as the default, with a content
   fingerprint later and opt-in; or the fingerprint as the default (a faithful port that reads each table). A third signal,
   the multiset hashes of step 8, needs hashes on. *Recommendation:* activity by default; the fingerprint as B1d-4.
4. **Which tables.** Volume_Trend and Freshness_Trend proposed for every profiled table (two rows per table, zero or one
   cheap read; TestGen's own default), `Table_Freshness` opt-in with the Table Comparison watch. *Recommendation:* as
   stated. The alternative is opt-in for all three, which keeps Curate quieter.
5. **Cadence.** Monitors ride the DatabaseQualitySurvey run and show how often they look. A lighter "monitor run" that
   takes only counts and counters on a faster schedule is a later slice if a table needs hour-level freshness.
   *Recommendation:* ride the survey now; confirm that daily-or-slower resolution is acceptable for v1.
6. **"This change is expected — restart the series."** A person's action that sets `series_start`.
   *Recommendation:* yes; without it a reload leaves a wide band for up to 20 runs.
7. **Publishing.** Volume as a `DataQualityRule` now; Freshness and Table_Freshness as annotations only until asked.
   *Recommendation:* yes.
8. **Severities.** Upstream's: Volume Fail, Freshness Fail, Table_Freshness Log. *Recommendation:* as upstream.
9. **Words.** §5.1's sentences, and `logged` for an unchanged Table_Freshness.
10. **Metric_Trend** (custom SQL): confirm it stays out with family F.
11. **Order of the calibration and timing runs.** The restore, the timing run (step 6 note §11) and the calibration run
    (plan §6) can share one static restore; the monitors' replay needs a scripted series of runs on it.
    *Recommendation:* one restore, one scripted series, the timing run first.
