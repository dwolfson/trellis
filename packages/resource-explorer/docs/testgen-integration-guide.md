# Data quality checks, and what Resource Explorer takes from DataOps TestGen

**Status:** live guide, written 2026-10-28 against `origin/main` (`a1cf1925`). Sections marked
**(arriving)** describe work on a branch in today's gate, not yet merged; each names its branch.

This guide is for people who use Resource Explorer (RE) to check the quality of a PostgreSQL
database. It covers:

- profiling the database's values;
- reviewing the quality checks RE proposes;
- running the checks you accept;
- reading the results in Egeria;
- what comes next: publishing checks as Egeria rules, and running them across a work list on a schedule.

---

## What RE takes from TestGen, and what it does not

DataKitchen's **DataOps TestGen** (Apache-2.0) is an open-source data-quality tool. Its catalogue of
test types sets out, for each kind of check:

- what to measure;
- when the check is worth proposing;
- what threshold to start from;
- the SQL that evaluates it.

**RE uses that catalogue as data. It does not run TestGen.**

- **RE vendors the catalogue.** It copies TestGen's test-type definitions (release 5.134.0) into its
  own configuration, and runs them with its own survey steps against your database.
- **RE does not run, call or connect to TestGen.** TestGen's engine, metadata database, scheduler and
  UI play no part, and RE has no TestGen connection setting.
- **RE uses its own names.** In RE and in Egeria the features are called **Value Profile** and
  **Quality Checks**. The name "TestGen" appears only in one CLI command and in the `origin` of
  imported proposals.
- **Every result comes from one engine: RE's.** You can still bring in the checks a TestGen
  installation already has, as proposals for review. See "Importing checks from a TestGen
  installation" below.

**What is ported so far.** TestGen has 89 test types. Main runs 15 of them:

| group | test types | merged in |
|---|---|---|
| profile-driven checks | Missing_Pct, Required, Required_No_Placeholder, Unique, Future_Date, Min_Date | slice 1 (#809) |
| RE's own proposal | Row_Ct_Pct (TestGen has no selection rule for it; RE proposes it with a 10 % default) | slice 1 (#809) |
| recency | Recency, Future_Date_1Y | Q6 (#880) |
| baseline match ("Table Comparison"), opt-in per table | Match_Row_Ct, Match_Distinct_Ct, Match_Null_Ct, Match_Zero_Length_Ct, Match_Min_Date, Match_Max_Date | B1a (#887) |

**(arriving)** Branch `claude/re-quality-profile-1b-on-q5` adds 12 more types (see "Profile 1b"
below).

These are not proposed at all:

- cross-table checks;
- custom-SQL checks;
- TestGen's manual-only types;
- hash comparisons;
- trend monitors;
- duplicate-row detection;
- checks that need sampled text shapes.

**Before you start, you need:**

- **A registered PostgreSQL database** with a stored credential that can read it. RE's quality
  checks are written for PostgreSQL only.
- **A stored schema inventory**, from any earlier database survey.
- **To be signed in**, to accept or reject a check or to watch a table: a decision needs a person to
  record it.
- **The database's schema committed to Egeria (Curate's catalogue commit)**, if you want results
  linked to the columns and tables in Egeria. RE never creates those elements itself.

---

## 1. Run the quality survey (Q2)

Everything starts from one Survey Definition, the **DatabaseQualitySurvey** ("Database Quality
Survey"). It has three steps, run in order:

| step | what it does |
|---|---|
| **Postgres Value Profile** | measures every column, across the whole table: counts, distinct values, nulls, empty strings, and date bounds. These are measured counts, not estimates |
| **Propose Quality Checks** | reads the profile it just took and proposes the checks whose selection rules fit. It reads nothing from your database |
| **Run Quality Checks** | runs the checks a person has **accepted** against your database |

To run it:

- **In the UI:** open the database, go to **Survey & analyses**, and press Survey on
  **DatabaseQualitySurvey**. The same steps appear as two analyses, **Value Profile** and
  **Quality Checks**.
- **From the CLI:**
  ```bash
  uv run resource-explorer database survey-definition <slug> --survey-definition DatabaseQualitySurvey
  ```
- **From Egeria:** with RE's engine host enabled (`RE_ENGINE_HOST_ENABLED`) and the definition
  committed in Egeria, Egeria can start the same survey.

The **first run** profiles the database and proposes checks. Its Run step ends with "no accepted
checks: accept proposals in Curate first; nothing was run". That is expected: no check runs until a
person has accepted it.

---

## 2. Profiling

The **Value Profile** reads each table with one aggregate query, inside a read-only transaction.
It reads the whole table, with no sampling and no row-count ceiling.

- **Each table gets 5 minutes.** A table that takes longer is recorded as **"profile incomplete ·
  exceeded 5 min · counts not measured"**, with every measure blank, and gets no proposals.
  The limit is `VALUE_PROFILE_TABLE_BUDGET_SECONDS`, 300 by default.
- **An absence is never written as zero.**
  - A view, materialized view or foreign table is *not applicable*.
  - A table RE may not read is *not permitted*.
  - A table that ran out of time is *not measured*.
- **On main, the profile measures** record, value, distinct, null, zero-length and filled counts,
  the earliest and latest date, future-dated values, values more than 20 years old (added by Q6),
  and a general type for each column.
- **The profile is published to Egeria** with the survey report, one profile annotation per column.
  An unchanged measure is re-linked to the new report, not written again. The Curate publish card
  says whether counts or shape changed. If counts moved on more than a quarter of the tables, the run
  card adds "this database is written live · see change rates".
- **The settings are read-only** under **⚙ Admin → Value profile settings**. Each shows its value,
  whether it came from the environment, and what it means.

**Note:** the Value Profile card's own description and an early design note still mention a row
ceiling. No such ceiling exists. The 5-minute budget is the only bound.

### (arriving) Profile 1b

Branch `claude/re-quality-profile-1b-on-q5` (`DESIGN-QUALITY-PROFILE-1B.md`, on that branch) adds 13
whole-table measures:

- **text:** shortest, longest and average length;
- **numbers:** zero count, minimum, maximum, average, standard deviation, fractional sum and sum;
- **booleans:** true count;
- **dates:** values more than 5 years old, and distinct days present.

With them come **12 more checks**:

- 11 baseline matches on those measures, opt-in per table like the six above;
- **Daily_Record_Ct**, which is proposed for every table.

Profile reads and check runs also run in UTC. On that branch, the 1b measures are profiled and
checked but not yet published to Egeria.

---

## 3. Review the proposed checks: Accept | Reject

Open the database's **Curate** page and the **Structure** tab. The **Quality checks** section lists
what was proposed:

- **The head line** gives counts (proposed, accepted, rejected, retired, not established), the
  number of tables, and "proposed <time> from the value profile of <time>".
- **Three filters** narrow the list: **Test type**, **Dimension** and **State**.
- **Each table is a collapsible group.** Open one to see its checks. The columns are Decision,
  Column ("whole table" for a table check), Test type, Dimension, Parameters, and Profile of.

**The Decision cell is a two-part selector, Accept | Reject, one check at a time.** There is no bulk
verdict, by design.

- **"accepted · <you> · <date>" appears only once RE has read your verdict back.** While it is being
  saved the cell says "recording…". If it cannot be read back, the cell says so.
- **You can change your mind.** A decided check can be decided again. Verdicts are kept as a history,
  and the latest one wins.
- **Accept stores the check's parameters as they are now.** Those parameters become the check's
  baseline, so a later profile does not quietly move the goalposts.
- **Accept is disabled when the profile could not evaluate the check.** The row then reads "this
  profile could not evaluate the check, so there are no parameters to accept; accept after a profile
  that measures it". Reject still works.
- **A rejected check is not proposed again** in later batches.
- **A verdict is local.** Its tooltip says so: "recorded in Resource Explorer · Egeria changes when
  you press Publish".

**Not built yet:**

- editing a check's parameters before you accept it (the Admin text mentions it, but the grid has
  Accept | Reject only);
- a way to **retire** an accepted check. "retired" is a state RE can display, but nothing records it
  yet.

From the API, the proposals are at `GET /api/quality-checks/{slug}/proposals`, and a verdict goes to
`POST /api/quality-checks/{slug}/verdict` with `{check_key, verdict, note}`. The author comes from
your session, never from the request body.

### Watch a table for drift: the baseline match (B1a)

The six **baseline-match** checks fail when a table **moves away from the profile it was accepted
against**. They compare:

- the row count;
- per column, the distinct, null and empty-string counts, and the earliest and latest date.

**They are opt-in per table** (owner decision, 2026-10-26). Each table group in the Quality checks
section has a **Watch for drift** button, which becomes **Stop watching** once the table is watched.
The cue reads "not watched for drift" or "watched for drift · <who> · <date>". From the CLI:

```bash
uv run resource-explorer database quality-watch <slug> <schema.table> [--off] [--note "why"]
```

- **The checks are proposed at the next propose run.** Re-run the DatabaseQualitySurvey, then accept
  them like any other.
- **Stopping only stops new proposals.** An already-accepted match keeps running until it is retired.
- **An emptied table fails these checks.** Here an unmeasurable value **fails** instead of reading
  "not established", because an emptied table *has* moved from its baseline.
- **The opt-in is recorded only in RE.** Nothing goes to Egeria.

### Recency (Q6)

**Recency** proposes on a date column that looks like it is being kept up to date. All four of these
must hold:

- its latest value is not in the future;
- its latest value is within about two months of the profile;
- its name is not a file date;
- TestGen's inferred functional type for it is neither "Future Date" nor "Schedule Date". RE ports
  the part of that inference that labels date columns.

The default threshold follows TestGen's rule for how stale the column already is. **Future_Date_1Y**
("Future Year") proposes where future-dated values exist. Both report under the dimension
*timeliness*.

A column profiled before Q6 lacks the "more than 20 years old" count. Its Recency is
**not established**, and the result names the missing input. It is never read as "not a future date".

### Importing checks from a TestGen installation

If your organisation already runs TestGen, you can bring its test definitions in as **proposals**,
never as verdicts. The import is CLI only, and reads a JSON export file:

```bash
uv run resource-explorer database quality-import-testgen <slug> --export testgen-export.json --dry-run
uv run resource-explorer database quality-import-testgen <slug> --export testgen-export.json
```

- **The export file** comes from `scripts/export_testgen.py` in the `egeria-workspaces-fs` repository,
  part of that repo's optional TestGen calibration harness. RE matches the export's project to your
  database by its slug.
- **What is imported:** only **active** tests of a type RE has ported, with their parameters checked
  like RE's own. An invalid one becomes a *not established* row that quotes it.
- **What is skipped, and counted:**
  - tests of a type RE has not ported, listed by type;
  - inactive tests;
  - checks RE already proposes;
  - checks you have already accepted or rejected.
- **What you see afterwards:** imported rows carry the origin `testgen`, and their reason names the
  TestGen suite, test run and profile run. They appear in the Quality checks section, where you
  accept or reject them as usual.
- **Results are not imported.** RE runs the checks you accept itself.

Today's export omits TestGen's test-definition id, so the reason says "(id not in the export)".

---

## 4. Run the accepted checks, and read the results

**Run the DatabaseQualitySurvey again**, from the UI, the CLI or Egeria. Its Run step evaluates
every accepted check:

- **Each check runs against its accepted baseline**, never the latest profile. A run of the Run step
  on its own is therefore meaningful.
- **Each statement has 60 seconds** (`VALUE_PROFILE_STATEMENT_TIMEOUT_SECONDS`).
- **Each result has a state:**
  - *pass*, *warning*, *fail* or *logged* when the check reached a conclusion;
  - *not established* when the measure is undefined, for example on an empty table. RE does
    **not** copy TestGen's "an undefined measure passes";
  - *error* when the query failed or timed out;
  - *not permitted*, *not measured* or *not applicable* when it could not run;
  - "column or table gone from the inventory" when the target has disappeared.

**In Egeria, each check the run evaluated becomes one `QualityAnnotation`** in the survey report,
whatever its outcome:

- `annotationType` is "Database Quality Check".
- `qualityDimension` is the dimension word (see §7).
- `qualityDescription` reads like "failed: …; the check fails when …".
- **`qualityScore` is 100 for a pass and 0 for a fail**, and is set only when the check reached a
  conclusion. A check that could not conclude has no score, so it never reads as a failure.
- `additionalProperties` carries the check key, state and reason, test type, column, severity,
  measure, threshold and baseline date.
- The annotation is linked to its column or table in Egeria, if that element exists there. Elements
  that do not exist are counted, not treated as errors.

On main, each annotation's `ruleSource` is `unpublished`, because no rule exists in Egeria yet.

---

## 5. (arriving) Publish accepted checks as Egeria DataQualityRules (Q5)

**On main** there is only Q5's design and a read-only probe (#889). Branch
`claude/re-quality-q5-dqrule-publish` builds the publish. The rules below are the project owner's
decisions of 2026-10-28, and that branch builds them:

- **One accepted check becomes one `DataQualityRule`.** It is named
  `<database asset qualifiedName>::Quality::<check key>`, and displayed as, for example,
  "Unique Values: sales.orders.order_id".
- **Each rule is its own anchor**, a reusable governance rule. It is not anchored to the database.
  Rules tied to a data contract are a later piece.
- **A rule is linked by `GovernedBy`** from the column (or the table, for a table check) **and** from
  the database asset, once each.
  - A check whose column or table is not in Egeria gets **no** rule: "not added to Egeria · its
    schema is not committed". It never falls back to the database.
- **No zones.** RE writes no zone membership on a rule, so rules are visible to everyone who can see
  governance definitions.
- **One press publishes every pending accepted check.** Accept stays local; the publish writes the
  rules. On the branch this press is the API call `POST /api/quality-checks/{slug}/publish-rules`.
  **The branch has no button yet.** Folding it into the page's Publish waits for other work.
- **Rejecting after publish deprecates and unlinks.** The rule is set to DEPRECATED and its
  `GovernedBy` links are removed. **It is never deleted.** Changing a check's threshold or severity
  updates the same rule in place.
- **Egeria wins.** If someone edits a rule's operator, threshold or severity in Egeria, RE does not
  overwrite the edit. The next run uses Egeria's values and says so: "edited in Egeria · Egeria's
  threshold is used".
- **Each write is read back.** A mismatch is reported as "unverified" and left unlinked.
- **What a run records.** A run reads the published rule. Each new QualityAnnotation names its
  `ruleSource` and `ruleGuid`, and is linked to the rule it was evaluated under. Annotations from
  before the rule existed are not back-linked.

`GET /api/quality-checks/{slug}/rules` reports each check's state in Egeria. The wording includes:

- "in Egeria · DataQualityRule · read back"
- "edited in Egeria · Egeria's threshold is used"
- "retired in Egeria"
- "not added to Egeria · its schema is not committed"

No rule has been written to a shared Egeria yet. The first live write is that branch's gate.

---

## 6. (arriving) Batch and schedule over a work list (Q3)

Branch `claude/re-quality-q3-batch-schedule` lets you run the quality survey across a **work list of
databases**, or put the list on a schedule:

- **Where to start:** on a database work list's bench, the **quality checks across this list…**
  button opens the dialog **Quality checks across this list**.
- **What it shows first:** a price per database. The columns are Database, Tables, Size, Time and
  Since its last quality run:
  - **Size** says "size unknown · never analysed", never 0, when RE does not know it.
  - **Time** uses earlier runs' measured wall time, or says "not measured yet".
  - "Nothing runs until you confirm."
- **Run on N** queues one DatabaseQualitySurvey run per database, through the same queue and
  credential checks as a single press. It reports each member's outcome: queued, skipped, not
  permitted, cannot run, or has its own schedule.
- **Schedule** puts the list on a schedule, following its membership at each firing.
  - **"A scheduled run skips each database whose inventory did not change since its last quality
    run, and says so."** A press by a person never skips.
  - A member that has its own schedule keeps it.
  - A scheduled run runs as the person who created the schedule, with publish rights checked for each
    member at each firing.

That branch's note marks several of these rules "assumed, owner to confirm". One example is what
counts as an unchanged inventory. **A failed scheduled run does not yet reach a person.**

---

## 7. Dimension words: what Egeria is told

Each check carries TestGen's quality **dimension**. Egeria's `qualityDimension` takes the data
contract standard's words: accuracy, completeness, conformity, consistency, coverage, timeliness and
uniqueness.

| checks | TestGen dimension | Egeria word |
|---|---|---|
| Missing_Pct, Required, Required_No_Placeholder, Row_Ct_Pct | Completeness | `completeness` |
| Unique | Uniqueness | `uniqueness` |
| Future_Date, Future_Date_1Y, Recency | Timeliness | `timeliness` |
| the Match_* baseline checks | Consistency | `consistency` |
| Min_Date | **Validity** | **main: `conformity` · arriving: `accuracy`, with `originalDimension: Validity`** |

**Validity has no exact Egeria word.** The project owner's ruling of 2026-10-20 is that conformity
is not equivalent and accuracy is closer. So validity is published as **`accuracy`**, with
`additionalProperties.originalDimension: "Validity"`, until Egeria gains a validity value.

- **Main still writes `conformity`.** The ruling is implemented on branch
  `claude/re-quality-q5-dqrule-publish`, which applies it to both the DataQualityRule and every
  QualityAnnotation.
- **Once that merges, Min_Date shows `accuracy`** in Curate's Dimension column and filter.
- **No other dimension needs translating**, so no other check carries `originalDimension`.

---

## Quick path

1. Survey the database once, so it has a schema inventory, and commit its schema to Egeria if you
   want linked results.
2. Run **DatabaseQualitySurvey** from Survey & analyses.
3. Open **Curate → Structure → Quality checks**. Accept or reject each proposal. Press **Watch for
   drift** on the tables whose shape should hold still.
4. If you already run TestGen, import its checks with `quality-import-testgen`, then review them too.
5. Run **DatabaseQualitySurvey** again. Watched tables get their baseline checks proposed, and your
   accepted checks run. The results reach Egeria as QualityAnnotations on the columns.
6. **(arriving)** Publish the accepted checks as DataQualityRules, and put a work list of databases
   on a quality schedule.

## Where this comes from

The design notes, indexed in [design-notes/README.md](design-notes/README.md):

- `DESIGN-VALUE-PROFILE-AND-QUALITY-CHECKS.md` (slice 1 and decisions D1–D6)
- `DESIGN-QUALITY-AT-SCALE-AND-TESTGEN.md` (Q2–Q6)
- `DESIGN-QUALITY-Q4-PORT-PLAN-AND-CALIBRATION.md` (the port order)
- `DESIGN-QUALITY-Q6-RECENCY.md`
- `DESIGN-QUALITY-B1A-BASELINE-MATCH.md`
- `DESIGN-QUALITY-Q5-DATA-QUALITY-RULE.md`
- `INVENTORY-TESTGEN-TEST-TYPES-MAPPED.md` (all 89 types)
- `INTEGRATION-TESTGEN-RE-EGERIA.md` (diagrams, dated 2026-10-20)

The vendored catalogue's provenance is
`resource_explorer/configdata/quality/testgen/PROVENANCE.md`.
