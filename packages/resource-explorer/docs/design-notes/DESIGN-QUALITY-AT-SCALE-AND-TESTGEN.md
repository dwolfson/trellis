# DESIGN — Quality checks beyond one database: RE's quality slice, TestGen's runtime, batches and Egeria (2026-10-21)

From the design session, at the owner's request through the RE
coordinator ("yes, send testgen to design"). The owner's question: "Do
we need to be able to kick off work to effectively use it for more than
a single project/database?" Short answer: yes, and RE already has the
three mechanisms; what is missing is one definition that uses them, a
price, and the rule that keeps TestGen's live runtime a calibration
harness rather than a second engine. Facts on TestGen's interfaces below
come from the coordinator's summary of the 10-21 live run and are marked
where the evaluation session should confirm them.

## 1. State today

| Piece | State |
|---|---|
| RE quality slice 1 (#809, main 885053a5) | per-card Value Profile and Quality Checks on one Postgres database; four registry tables (`database_value_profiles`, `database_quality_proposals`, `database_quality_results`, `database_quality_verdicts`), created at the next 8813 restart after a peer round; three linear steps `postgres_value_profile` → `propose_quality_checks` → `run_quality_checks`; seven vendored TestGen test types; verdicts in Curate |
| #791 | superseded verdicts retired; works with pyegeria 6.2.7 (#806) |
| Engine-host declarations for propose and run | held (`HELD_FROM_DECLARATION`) because they would complete with empty survey reports until results publish |
| TestGen runtime (egeria-workspaces #663) | ran live 10-21: `seed_examples.py` creates one TestGen project and connection per target database, reading as `surveyor`, then profile, generate, test; five example projects took about three hours; SUBSCRIPTION_STAGING failed on TestGen's 50-character schema-name column; `export_testgen.py` and `compare/compare_re_testgen.py` diff TestGen's profile and tests against RE's slice-1 tables |
| Egeria | `DataQualityRule` (0450) exists on the platform; no pyegeria wrapper (`SPEC-PYEGERIA-DATA-QUALITY-RULE.md`, #755 spec only); results to Egeria are a mapping document |

The owner's decisions of 2026-10-19 stand and bound this note: D1, TestGen's
catalogue is vendored as data and RE executes it, TestGen's engine,
metadata database, scheduler and UI are not run as a service; D2, RE is
not the coordinator, Egeria coordinates through a Survey Definition or
RE's executor runs the steps; D3, checks are proposed in RE and accepted
into Egeria as `DataQualityRule`s.

## 2. Rulings

### 2.1 Engine of record: RE's slice, with TestGen's runtime as a calibration harness

RE's vendored checks propose and run (D1). TestGen's live runtime is
kept for one purpose: calibration. Its generated tests and profile are
compared against RE's proposals and profile for the same database, and
every disagreement is a finding about RE's port (a selection rule RE
applies differently, a measure that differs, a test type RE lacks). It
is not a second engine of record, it does not run on a schedule, and
nothing publishes from it. "Both side by side" in production would mean
two sets of verdicts on one column and two sentences for one fact.

Consequence: no adapter that drives TestGen from RE (question 3). The
seed script stays a hand-run harness on a few databases, run when RE's
port changes or a new test type is vendored. If TestGen's inference
(`functional_data_type`, which Recency needs) is wanted, slice 2 ports
the inference as data, as D1 did for the catalogue; it does not call
TestGen for it.

### 2.2 Batch: one Survey Definition, run across a work list, scheduled by Automate

The three mechanisms are one path, not three options:

1. **The definition.** `DatabaseQualitySurvey`, a Survey Definition
   authored in Dr.Egeria with the three steps in order (value profile,
   propose, run) and the guards they already declare. It runs on one
   database the way every definition does, from the Survey press or the
   "coordinated by Egeria" control once the engine-host declarations are
   unheld.
2. **The batch.** A work list of databases plus "run this definition
   across the list" (the work-list batch run RE has, `enqueueBatch`),
   one run per database, each its own row with its own price, through
   the same queue and the same credential gate. The batch is a list of
   runs, never a run of its own, so every result, verdict and proof row
   stays per database.
3. **The schedule.** Automate schedules the batch (the work list and the
   definition) with the existing change-detection rule: a database whose
   inventory did not change since its last quality run is skipped and
   says so.

Nothing new is invented; the slice is the definition plus the two
existing controls pointed at it, with the per-run price shown before
the batch starts.

### 2.3 The price

TestGen's three hours for five projects is TestGen's cost (its own
profiling plus test generation plus a metadata database), not RE's. RE's
steps price themselves from what the launcher already knows: value
profile is one aggregate `SELECT` per table over the whole table
(`fetch_cost` api_heavy; the estimate is bytes read per table from the
catalog's size, with the never-analysed case shown as "size unknown",
the gate-review rule); propose is zero-fetch; run is one statement per
accepted check. The batch dialog therefore shows a per-database line
("coco_pharma · 266 tables · ~4.1 GB read · ~12 min") and a total, from
the same cost vector the single-run dialog uses, before anyone presses.
A database over a configured size runs value profile on a sample with
the sample stated, or is skipped and listed, never silently truncated.
The measured wall time of each run becomes the next estimate.

### 2.4 Results flowing back from TestGen

Only through the compare bridge, and only as proposals. A TestGen test
that RE did not propose for the same column becomes a proposal row with
`origin=testgen`, the TestGen test id and the run it came from, never a
verdict; a person accepts it in Curate like any other. A TestGen test RE
also proposed is a match, recorded on the compare report. A proposal RE
made that TestGen did not is a note for the calibration log, not a
demotion. TestGen's test results (pass or fail) are not imported;
RE runs accepted checks itself, so one engine produces every result.

### 2.5 Credentials, identity and TestGen's limits

For RE's own steps: the database's stored credential as today, the
capability gate as today (`requires_capability`), and the run under the
initiating user with the service account only for scheduled, unattended
batches, the owner's identity rule. For the calibration harness:
TestGen keeps its `surveyor` read credential in its own runtime, outside
RE, and the harness is run by a person, so no RE identity question
arises. TestGen's 50-character schema-name limit is TestGen's; the
compare report lists the schemas it could not take, and RE's steps are
unaffected.

### 2.6 Egeria: what publishes, when

- **Now (slice 1 as built):** nothing, which is why the engine-host
  declarations are held.
- **Next:** results as `QualityAnnotation`s on the column or table
  elements, one per evaluated check, with `rule_source = unpublished`
  until the rule exists in Egeria, the dimension, the measure, the
  threshold and the outcome; this is the survey channel and follows
  Egeria's lead on the annotation type. The engine-host declarations are
  unheld when a run publishes at least its results, so a
  `survey-completed` carries a report with annotations.
- **Then:** accepted proposals as `DataQualityRule`s linked by
  `GovernedBy` (D3), which needs the pyegeria wrapper in
  `SPEC-PYEGERIA-DATA-QUALITY-RULE.md`; a pyegeria item on the owner's
  word, or a Mandy item if the type's request body misbehaves. Until
  then, results publish with `rule_source = unpublished` and the Publish
  control says "rules stay in RE until Egeria can hold them".

## 3. Slices and gates

| # | Slice | Gate, by use |
|---|---|---|
| Q2 | `DatabaseQualitySurvey` definition (three steps, authored, reconciled); results published as `QualityAnnotation`s; the two engine-host declarations unheld with a committed test that a run with zero accepted checks completes `survey-invalid` ("no accepted checks"), never an empty completed report | the owner runs it on coco_pharma from the Survey press, accepts three proposals, re-runs, reads three annotations back in Egeria by GUID |
| Q3 | Batch and schedule: the work-list batch run and Automate pointed at the definition, with the per-database price line and the skip-unchanged rule | a work list of coco_pharma and adventureworks run as one batch with two priced rows; a second scheduled run skips the unchanged one and says so |
| Q4 | Compare bridge as a documented harness: `seed_examples.py` and `compare_re_testgen.py` with a calibration report (matches, TestGen-only, RE-only, schemas TestGen could not take) and the import of TestGen-only tests as `origin=testgen` proposals | one calibration report on coco_pharma; one TestGen-only proposal accepted in Curate and run by RE |
| Q5 | `DataQualityRule` publish once the pyegeria wrapper exists | one accepted check read back as a rule linked `GovernedBy` to its column |
| Q6 | Slice 2 of the checks: Recency with the inference ported as data | the eighth check proposes on a dated column and nowhere else |

## 4. Open for the owner

- [ ] Agree that TestGen's runtime is a calibration harness only, with no
      RE adapter and no schedule (2.1).
- [ ] The size cap above which value profile samples or skips (2.3).
- [ ] The pyegeria `DataQualityRule` wrapper: your word to build it from
      the spec, or a Mandy item first.
- [ ] Whether Q3's batch is the Alpha demo's "many databases" story.
