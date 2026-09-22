# Database Survey Definitions — implemented

Phase 1 slice 12 (`COORDINATOR-BRIEF-MULTI-RESOURCE.md`): "Database survey
definitions: `generate_database_survey_definition.py` cloned from the repo
generator; `scouting`, `analysis`, `assessment` documents; publish through
Dr.Egeria." Gate (streams 2 `question-catalog-multi-type` and 4
`db-questions-csv`) was already merged before this slice started.

## What was built

1. `packages/resource-explorer/scripts/generate_database_survey_definition.py`
   — the database analogue of `scripts/generate_repo_survey_definition.py`.
2. Three generated documents under
   `docs/dr-egeria/survey-definitions/database-survey-definition-{scouting,analysis,assessment}.md`,
   plus their entries in the shared `.generated.json` provenance sidecar
   (one file per directory, keyed by filename — **not** one `.generated.json`
   per document; that is also how the repo generator works, contrary to how
   the task brief phrased it).
3. `docs/dr-egeria/survey-definitions/_batch.json` updated to list the three
   new files, so a future platform-reset heal restores them alongside the
   repo documents.
4. `tests/test_generate_database_survey_definition.py`, mirroring
   `tests/test_generate_repo_survey_definition.py`'s coverage, adapted for
   this script's hardcoded `SPECS` (see below for why there is no
   `database_survey_types.csv`).

## Design section implemented

`docs/multi-resource-questions-design.md` §5.2–§5.6 (the authored database
questions) and §5.7 (the step list) — specifically the "publish the survey
definitions that reference the steps §5.7 lists as already real" part of
§5.7, not the step-building parts of §5.1/§5.3/§5.5/§5.8 themselves (those
are slices 7/9/10/11, out of scope here per the brief's "do not touch
slices 7/8/9/10/11's step-implementation files").

## Why three tiers, and why they are the ones they are

`resource_explorer/surveyors/database/survey_definition_adapter.py` registers
exactly three `re_analysis_step`s today: `postgres_schema_and_stats`,
`postgres_operations`, `sql_analysis`. Unlike repo (~20 steps, a
`STEP_REGISTRY` dataclass registry, and a CSV mapping many (survey, step)
pairs), there was nothing to build a CSV-driven spec loader out of for three
fixed tiers — `SPECS` is a plain hardcoded list of three `SurveyDefSpec`s in
the script, validated against the adapter's real `re_analysis_steps` dict by
`_validate_specs()` (raises if a spec names an unregistered step; warns if a
registered step is referenced by no spec — the same two guards repo's
CSV loader has, minus the CSV).

- **scouting** (`DatabaseScoutingScan`) — `postgres_schema_and_stats` alone.
  The fast pass: schema/table/column inventory, row-count/size statistics,
  `pg_stats` profiling, index usage. Answers the two real Scouting-stage
  database questions this step's data backs (`schema_inventory`,
  `row_count_snapshot`).
- **analysis** (`DatabaseAnalysisSurvey`) — all three steps chained:
  `postgres_schema_and_stats`, then `postgres_operations` (privileges,
  activity signals, resilience, external dependencies), then `sql_analysis`
  (view dependency/lineage). The comprehensive bundle, matching repo's
  Analysis Survey being "everything Analysis extracts."
- **assessment** (`DatabaseAssessmentSurvey`) — `postgres_schema_and_stats`
  then `postgres_operations`. `sql_analysis` is deliberately excluded: no
  Assessment-stage database question in the CSV resolves to it.

**No discovery/coarse-profile/full tier was added.** Repo's Discovery and
Architecture-Discovery tiers exist because repo already has zero-new-fetch
signals (license classification, maturity, conventions) to reason over data
Scouting already collected. No database analysis does that yet — every
Discovery-stage database question in `resource_questions.csv` is `direct`
(registry/human lookup) or `GAP:`. Adding a Discovery-tier Survey Definition
today would chain no real step at all — exactly the invented, unsupported
tier the slice-12 brief says not to build. A `full`/"run everything" tier
was also skipped: with only three real steps, `analysis` already *is* "run
everything," so a fourth identically-scoped tier would be a rename, not a
new capability.

## The stale-gap wrinkle (found, not fixed)

`docs/dr-egeria/resource_questions_guide.md` documents that a `GAP:` note's
generator regex-scans for an embedded analysis id, and that `kind` (not the
presence of an id) governs Questions-tab answerability — mentioning a real
id inside a `GAP:` note still links it. `_build_step_key_to_questions()`
here reproduces that join exactly, unfiltered by `kind`, matching repo's
`_build_step_key_to_questions()` line for line (see both scripts'
docstrings).

That surfaced something worth flagging, not fixing (question-catalog CSV
content is stream 4's territory, off-limits here): three question rows still
carry `kind: gap` while naming a `(proposed)` analysis id that Phase 1
slices 7/8 have *since actually built* —

| Question (abbreviated) | Proposed id named in the GAP note | Real now? |
|---|---|---|
| "Is this database alive..." | `db_activity_signals` | Yes — `postgres_operations` |
| "...primary or a replica..." | `db_resilience` | Yes — `postgres_operations` |
| "What does this database depend on..." | `db_external_dependencies` | Yes — `postgres_operations` |

`_build_step_key_to_questions()` links all three correctly regardless (the
join never consulted `kind`), so the generated documents are not affected —
but the question catalog's own `kind: gap` label on these three rows is now
stale relative to `analysis_catalog.yaml`, and the Questions-tab checklist
will still show them as "no mechanism exists for this" even though one now
does. Logged to `docs/Backlog.md` (see below) rather than edited here,
per the CLAUDE.md convention that `resource_questions.csv` content is
stream 4's, not this slice's, to change.

## GAP questions that remain genuinely unbuilt, and what unblocks each

Every other `GAP:`-marked database question's proposed id has no registered
step behind it today. By proposed id, and which slice (per the coordinator
brief's Phase 1 table) would build it:

| Proposed id (from the CSV's `GAP:` note) | Question (abbreviated) | Blocked on |
|---|---|---|
| (unnamed — column profiling) | Scope of data in time / date-range extraction | Slice 10 (`postgres_column_profile`) |
| `db_documentation_coverage` (name withheld in the CSV note itself, substring-guard) | "Is this database documented..." (Scouting) and "How complete/consistent is documentation" (Assessment) | Not in any current slice 7–11 — needs a new comment-coverage step, undesigned |
| `db_server_profile` | "What engine and version..." | Not in any current slice 7–11 — server-level, undesigned |
| `db_classification` | "What kind of database is this..." | Not in any current slice 7–11 (adjacent to slice 9's `db_derived` but not named in its design §5.3 scope as read) |
| `db_relationship_graph` | "Is there a data model here..." | Slice 9 (`db_derived`, design §5.3) |
| `grain_determination` | "What is the grain of each table..." | Slice 9 (`db_derived`) |
| `db_fingerprint` | "Does this look like a copy..." | Slice 9 (`db_derived`) |
| `db_hub_tables` | "Which tables would a consumer start with..." | Not in any current slice 7–11 — adjacent to slice 9 but not named in its scope |
| (unnamed — semi-structured column detection) | "Which columns hold semi-structured data..." | Overlaps slice 11 (`postgres_nested_columns`) at the detection edge; the ranking/rollup itself is undesigned |
| `column_profile` | "What do columns actually contain..." | Slice 10 (`postgres_column_profile`) |
| `data_class_match` | "Which columns conform to a Data Class..." | Slice 10 (`postgres_column_profile`, design §5.8) |
| `reference_data_match` | "Which low-cardinality columns conform to reference data..." (Analysis and Assessment "well-governed reference data") | Slice 10 |
| `nested_column_profile` | "What is inside JSON/JSONB/XML columns..." | Slice 11 (`postgres_nested_columns`) |
| `schema_conventions` | "Which tables have no PK/FK/comment/unused index..." (Analysis) and "How well-modelled..." (Assessment) | Slice 9 (`db_derived`, "conventions checks") |
| `db_change_rates` | "How is this database changing..." | Slice 9 (`db_derived`, "change rates") |
| `semantic_suggestions` | "Which glossary terms do these columns probably mean..." | Not in any current slice 7–11 — depends on slice 10's Data Class/reference-data matches as inputs, plus its own agent-based step; undesigned |

None of these appear as steps in any generated document — they cannot,
since `_build_step_key_to_questions()` only links a question to a step that
is actually in `STEP_REGISTRY`, and the survey-definition markdown format
itself has no field for an aspirational note (confirmed against
`dr_egeria_survey_publisher.py` — there is no such field, matching repo's
convention that an unmapped question is silently un-scoped, "the next
resync un-authors it from Egeria" rather than annotated in place).

## Publishing through Dr.Egeria — deferred

The established mechanism for publishing repo's survey definitions is
`resource_explorer/bootstrap.py`'s `check_and_heal()`, driven by
`docs/dr-egeria/survey-definitions/_batch.json`'s manifest: it re-executes
every document in a batch when the batch's canary element
(`GovActionProcess::RepoFullSurvey`) is missing from Egeria. That mechanism
is reused here (the three new files were added to the SAME manifest/folder,
not a new batch — see `_batch.json`'s updated `$comment`), but it does
**not** by itself publish anything new: the canary is almost certainly
already present on the running dev platform (repo's definitions are already
live), so an ordinary heal will not fire for these three new files. The
existing `repo-survey-definition-compliance.md` precedent in the same
manifest establishes that a newly-added file needs one manual, one-time
execution at authoring time, independent of any future heal — the same is
true here.

**That one-time execution was NOT done from this session.** Reasons:

- This is an isolated worktree agent, not the checkout the coordinator brief
  ties Egeria writes to being "ordinary" for (that framing assumes the
  session doing the write can also verify the live platform's current state
  — e.g. confirm the canary really is present, confirm no other session is
  mid-heal — which this session could not do beyond checking
  `list_sessions` for `isRunning: true` peers, none found).
- `docs/dr-egeria/survey-definitions/_batch.json`'s own `$comment` calls out
  that "Link First/Next Process Step" commands are NOT idempotent and warns
  against running this batch's documents "just in case." The three new
  documents are brand new (first-time creation, not a re-run of an
  already-linked process), which is the safe case — but verifying that
  assumption against the live platform (that
  `GovActionProcess::DatabaseScoutingScan`/`DatabaseAnalysisSurvey`/
  `DatabaseAssessmentSurvey` don't already exist under those qualified
  names) requires a live read this session did not perform.
- No live Trellis session was found running (`list_sessions`, no
  `isRunning: true` entries) at the time this was written, so peer
  coordination has nothing to wait on — but "nobody is currently running"
  is not the same as "safe to write," and per `coordinate-shared-writes`,
  a live Egeria write from an isolated agent context with no way to
  independently verify the result afterward is exactly the case to defer.

**Follow-up (exact command):** from the main checkout
(`/Users/dwolfson/localGit/egeria-v6/trellis`, after fast-forwarding to this
PR's merge), execute the three new documents once, in tier order
(cheapest first, matching repo's convention), via the `mcp__egeria`
Dr.Egeria tooling already used for every prior survey-definition
authoring pass:

```
# Confirm the three qualified names do not already exist first:
#   GovActionProcess::DatabaseScoutingScan
#   GovActionProcess::DatabaseAnalysisSurvey
#   GovActionProcess::DatabaseAssessmentSurvey
# Then run each document's Dr.Egeria markdown against the dev platform
# (mcp__egeria__dr_egeria_run_block, one document at a time):
docs/dr-egeria/survey-definitions/database-survey-definition-scouting.md
docs/dr-egeria/survey-definitions/database-survey-definition-analysis.md
docs/dr-egeria/survey-definitions/database-survey-definition-assessment.md

# Then, since this batch's post_heal step applies to any execution of it:
uv run python scripts/reconcile_survey_definition_links.py
uv run python scripts/reconcile_survey_definition_scopes.py   # report-only check
```

Message any running Trellis session first (per `coordinate-shared-writes`
and this project's "ask peers before commits" rule), even though none was
found running when this was written.

## What could not be tested

- **Live publish** — deferred, see above; nothing here was run against a
  live Egeria platform.
- **`SurveyDefinitionReader` actually parsing the three new documents once
  live** (branching/guard walk, ScopedBy resolution) — only exercised
  against repo's real, live-published documents in the existing test suite;
  the database ones are new and untested end-to-end until published.
- **The `egeria-adaptive`/`egeria` `other_engine_handlers` paths** —
  irrelevant to this slice (those are triggered by a different mechanism,
  not by the Survey Definition's own step chain), not exercised.
- **Whether `DatabaseAnalysisSurvey`'s `sql_analysis` step actually needs
  Egeria's real SQL-view catalog populated first** — untested; out of scope
  for a document-generation slice.

## Backlog items logged

Logged to `docs/Backlog.md` (not fixed, per the slice-12 instruction to log
only):

- The three stale `kind: gap` question-catalog rows (`db_activity_signals`,
  `db_resilience`, `db_external_dependencies`) that name a proposed id
  slices 7/8 have since actually built — the question catalog's `kind`
  should probably flip to `analysis` for these three, but that CSV is
  stream 4's territory.
