# Declared extensibility, slice 1 PR 2 (the Curate publish table): what was built, choices, gaps (2026-10-27)

Companion to `DESIGN-DECLARED-EXTENSIBILITY-RENDERING-CHAT-CONFIDENCE.md` (§5 the publish table, §7 the gate) and to
PR 1's `DECLARED-EXTENSIBILITY-SLICE1-PR1-GAPS.md`. Records what the design note leaves open and what this PR chose,
rather than guessing.

## 1. What was built

- **The table** (`resource_explorer/publish_table.py`, `web/routes/publish_table.py`,
  `web/static/next/stages/publish-table.js`): on a database's Curate "Describe and publish" tab, between What people
  say and the Publish band. A row per declared measure of every database analysis with a declaration, except
  `proposal` kinds. Columns: analysis, measure with unit, value with unit, as-of, confidence form with its basis or
  method, scope, writes as (the declared type, or "generic measure · no native type declared"), Publish | Keep in RE,
  and the publish state from proof rows ("local · not published", "published · read back <time>", "changed since
  published", "sent · not read back"). An absent value shows the declared absence sentence, never a zero.
- **The choice**: saved at once, signed and dated, append-only, newest wins.
- **The press** is the database's one press, the Catalogue commit on Contents. Its manifest gains a line naming how
  many chosen measures go (`declared_measures`, from the same function the press sends from). Its step 3 (RE's own
  survey report) carries the chosen measures as annotations after the stored verdicts, reads the report back, and
  records one proof row per measure; the step's words gain "N declared measures read back".
- **The two routes**: generic (ResourceMeasureAnnotation, value in `resourceProperties` under the measure's name,
  `additionalProperties.declaredRoute: generic` and the label, unit, as-of, confidence basis, scope) and native
  (the declared type with the declared property map; `declaredRoute: native`).
- **The as-of seam** (PR 1 gap §2.1): `_db_derived_field_reader` now carries the run beside the payload as
  `_run: {read_snapshot, surveyed_at}`; `Fact.as_of` is `_run.read_snapshot` when present, else the run time, and is
  in `as_dict()`. `_run` is envelope, not content, in both `_has_content` and `results_have_data`. On screen, an
  answer whose facts have no run time but an as-of says "as of <time>" rather than "run time not recorded".

## 2. Choices this PR made, beyond the note

1. **No new table.** The choice is a row in `resource_scope_events` (kind `measure`, locator `<analysis>/<measure>`,
   choice `publish` | `keep`); `current_resource_scope` reads scope kinds only, so these never count as scope. Proof
   rows go in `catalogue_commit_proofs` (node_kind `measure`, schema_name = analysis id, table_name = measure,
   proofs `measure_read_back` / `measure_not_read_back`); every existing reader of that table filters by node kind or
   proof kind. No DDL.
2. **Not chosen is Keep in RE.** No row is ever published by default.
3. **Measures ride in RE's own survey report**, keyed `declared_measure.<analysis>.<measure>` under the report's
   prefix, so they need a measured survey of RE's own (the manifest says so when there is none) and a later survey's
   publish writes a new annotation rather than updating the old one, as every annotation in that report does.
4. **Only the commit asks for them.** `publish_local_survey(declared_measures=False)` is the default, so the retired
   publish route and the hybrid surveyor never send chosen measures without recording proofs.
5. **Native writing is ResourceMeasureAnnotation only.** Any other declared type (SchemaAnalysis, DataClass,
   ResourceProfile, Classification, ...) is shown as what the row writes as, with Publish disabled and the reason:
   "Resource Explorer does not write <type> from a declaration yet". Building those types from a declaration needs a
   per-type construction (a profile's value counts, a classification's name) that PR 1 says no declaration carries
   yet (PR 1 gaps §2.4).
6. **A row cannot publish** without a value, with a non-scalar value, or without an as-of ("a number never travels
   without its as-of"); nor when the confidence form is `generated` (the declaration already forbids it an
   annotation).
7. **Changed since published** compares the proof row's value and as-of with the current ones. It is a word on the
   row; nothing is re-sent until the next press.

## 3. Not built

- **File systems.** Their rows are listed by the route but not offered on screen, and cannot publish
  ("publishing from this table is built for databases only so far"): a file system's Publish attaches its root folder
  only and has no survey report of RE's for the measures to ride in.
- **Native types other than ResourceMeasureAnnotation** (§2.5).
- **The engine-host and native-survey paths.** A library step's results already publish through the engine host when
  Egeria runs it, and some built-in measures (schema inventory, row counts) are already in RE's survey report under
  their own annotations. The table does not know that, so publishing such a row writes the same number a second time
  under the declared name. See owner question 1.
- **Cost on open.** The table reads every declared analysis through the fact layer; the seven `db_derived` analyses
  each recompute `run_db_derived` (it is not memoized across facts). Fine at coco_pharma's size; worth a memo if a
  large database makes Curate slow to open.
- **Library steps' value paths** use the record property names ("Writes Per Day"); the table reads those as whole keys
  first. Whether the results reader returns records in that shape was not checked against a live run.

## 4. Owner questions

Answered and built 2026-10-28, each **assumed: owner to confirm** (no recorded answer was found): see
`DECLARED-EXTENSIBILITY-PUBLISH-TABLE-ANSWERS.md`.

1. **Rows whose analysis already publishes another way.** Should a row say "already in Egeria via <the survey report /
   the engine host>" and offer no Publish, rather than offering a second, declared copy of the same number?
2. **Native types next.** Which declared types should the publisher learn first? The PR 1 declarations name
   SchemaAnalysisAnnotation and ResourcePhysicalStatusAnnotation most often after ResourceMeasureAnnotation.
3. **File systems.** Should their chosen measures wait for a file-system survey report of RE's own, or ride on the
   root-folder publish?
4. **Choice lifetime.** A choice is kept across surveys, so a measure chosen once is sent by every later commit until
   someone chooses Keep in RE. Is that the intent, or should a choice be per survey?
