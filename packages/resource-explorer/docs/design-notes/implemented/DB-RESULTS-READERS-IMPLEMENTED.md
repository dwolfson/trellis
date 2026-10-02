# DB-RESULTS-READERS — implemented (slice D1)

Slice D1 of `PLAN-ANALYSIS-GAPS-REPOS-AND-DATABASES.md`: results readers for the three database
analyses that were built and ran but had no reader, `data_class_match`, `reference_data_match` and
`nested_column_profile`. Branch `re/db-results-readers`, off `origin/main` `2d44c2f9`. No Egeria
write, nothing reads back from Egeria, no live database was run.

## What was wrong

Their verdicts only ever became Egeria annotations. There was no local table a reader could query
(`docs/Backlog.md`, "Database per-column match results have no local store"), so none of the three
was in `DATABASE_ANALYSIS_RESULTS_MAP`, By analysis could not draw a card with a sentence, and the
Survey & analyses pane had nothing to say for them. The `/next` string the owner saw,
`ran; no summary reader yet.`, is produced by `byAnalysisCardHtml` in
`resource_explorer/web/static/next/app.js` for a board that has results and no headline sentence.
The fact layer's matching note is `This ran; no summary reader exists yet for its results.`
(`facts.py`, `_check_level`).

## The shape copied

`schema_inventory` over `database_tables`, and the `database_column_profiles` /
`database_table_activity` writes in `DatabaseSurveyor._store_results`: a generic detail table
keyed `(database_slug, surveyed_at, source, ...)`, written with `registry.write_detail_rows`
(delete-then-insert per run key), one coverage row per attempted section, a results reader and a
headline reader registered in the two maps, `live_read=True` through `DATABASE_ANALYSIS_KINDS`. No
new pattern. The tables are picked up by `_DETAIL_TABLE_SPECS`, so `delete_database` and the
generic reader/writer cover them with no further edit.

## Per analysis

### data_class_match -> `database_data_class_matches`

One row per column per run: `verdict` (column_matching's own vocabulary, not collapsed),
`confidence`, `evidence`, the matched class (display name, qualified name, guid, draft flag),
`sampled_conformance`, `privacy_relevant`, `proposed_specification`, `detected_patterns_json`,
`not_established_reason`, the sample basis (`sample_strategy`, `sample_rows`, `sample_total_rows`,
`sample_seed`), the rendered `statement`, and `state` (measured for an established verdict,
not_applicable, otherwise not_collected). Coverage section `data_class_matches`.

Summary shows (reader value): `column_count`, `established_count`, `not_established_count`,
`not_applicable_count`, `matched_count`, `no_match_count`, `proposed_count`,
`privacy_relevant_count`, `verdict_counts`, `sample_strategies`, and a `columns` list.
Headline, for example: `1 of 2 columns tested matched a known Data Class — 1 had no match`.

### reference_data_match -> `database_reference_data_matches`

Same key and shared columns, plus `value_coverage`, `unmatched_values_json`, `proposed_values_json`
in place of the Data Class specific ones. Coverage section `reference_data_matches`. Summary adds
`partial_count`. Headline, for example: `0 of 3 low-cardinality columns tested matched a known
Valid Value Set — 3 had no match`. Columns outside the low-cardinality gate are `not_applicable`
and counted as such, never as "no match".

### nested_column_profile -> `database_nested_columns`

One row per JSON/JSONB/XML column: `column_family`, `label` (structured, scalar_only, mixed,
unparseable, empty), `key_count`, `max_depth`, `schema_json` (the whole inferred schema),
`not_established_reason`, the sample basis, and `state` (measured or empty when a value was read;
not_collected or not_supported when none was). Coverage section `nested_columns`. The step output
now also carries `schema_name`, `table_name`, `column_name` and `sample` per column (additive), so
the store never re-splits a dotted path. Summary: `column_count`, `structured_count`,
`scalar_only_count`, `mixed_count`, `unparseable_count`, `empty_count`, `not_established_count`,
`label_counts`, `columns`. Headline, for example: `3 JSON, JSONB or XML columns — 1 structured,
1 scalar-only, 1 mixed`.

## Status words come from stored rows

The reader reads the newest coverage row for its section (`registry.get_latest_section_coverage`,
new, read-only, across runs and sources, because each step is run as its own `survey()` call with
its own `surveyed_at`) and the detail rows of that run. The outcomes, none a branch the code
happened to take:

| stored fact | what the reader returns | fact state |
|---|---|---|
| no coverage row for the section | an envelope-only dict (`_status` not_established, reason `no_stored_result`); `results_have_data`, `_has_content` and `question_has_data` all read it as "nothing here" | `never_run` when no run is attributed (the run gate answers first); `not_established` when a run is attributed but predates storage, never `nothing_found` |
| coverage `not_collected` / `not_supported`, or rows whose every verdict established nothing | `state: not_established` with the reason text; match counts are omitted so nothing is drawn as 0 | `not_established` |
| rows, all established, no finding | real zero (`matched_count: 0` printed, `_status` nothing_found) | `nothing_found` |
| rows, some columns could not be tested | counts plus `partial: true`, the headline says `N could not be tested` | `partial` |
| a credential-scope shortfall from the `credential_capability` probe | `_status` measured_within_credential_scope, taking precedence over a bare zero | `measured_within_credential_scope` |

A step that raised is recorded (`column_profile_failed` / `nested_columns_failed` on the survey
results) as coverage `not_collected` with the message, so "tried and could not" is stored rather
than being an absence. A survey that never requested the step writes no coverage row (the two `{}`
defaults in `survey()` mean "did not run").

One neighbouring change: `workflows/scouting.question_has_data` counted any truthy value, so an
envelope-only reader result (`{"_status": {...}}`) ticked the question for a database that never
ran the analysis. It now skips `_status` like `results_have_data` and `facts._has_content` do.

Idempotence: re-materialising one run replaces its own rows (`write_detail_rows`); a later run has
its own `surveyed_at`, so two runs are two row sets and the older one stays. Both are tested.

## Migration (additive, new tables only, no existing table touched)

**The first start of any process on this code migrates whatever registry it opens. The shared
registry at localhost:5442 is that registry; it needs a peer check before the first start.**
Created by `CREATE TABLE IF NOT EXISTS` in `_DB_FS_DETAIL_TABLE_DDL` (the same block that created
the other detail tables), so a re-run is a no-op and no `ALTER` is involved
(`_DB_FS_DETAIL_TABLE_MIGRATIONS` lists the three with `()`). Nothing is back-filled: a database
that ran these analyses before this change has no stored result and reads `not_established`, "ran
before its results were stored", until it is run again.

SQLite (as written):

```sql
CREATE TABLE IF NOT EXISTS database_data_class_matches (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    database_slug            TEXT NOT NULL,
    surveyed_at              TEXT NOT NULL,
    source                   TEXT NOT NULL DEFAULT 'local',
    schema_name              TEXT NOT NULL,
    table_name               TEXT NOT NULL,
    column_name              TEXT NOT NULL,
    verdict                  TEXT NOT NULL,
    confidence               INTEGER DEFAULT NULL,
    evidence                 TEXT DEFAULT '',
    matched_display_name     TEXT DEFAULT '',
    matched_qualified_name   TEXT DEFAULT '',
    matched_guid             TEXT DEFAULT '',
    matched_element_is_draft INTEGER DEFAULT NULL,
    sampled_conformance      REAL DEFAULT NULL,
    privacy_relevant         INTEGER DEFAULT NULL,
    proposed_specification   TEXT DEFAULT '',
    detected_patterns_json   TEXT DEFAULT NULL,
    not_established_reason   TEXT DEFAULT '',
    sample_strategy          TEXT DEFAULT '',
    sample_rows              INTEGER DEFAULT NULL,
    sample_total_rows        INTEGER DEFAULT NULL,
    sample_seed              INTEGER DEFAULT NULL,
    statement                TEXT DEFAULT '',
    state                    TEXT NOT NULL DEFAULT 'measured',
    UNIQUE(database_slug, surveyed_at, source, schema_name, table_name, column_name),
    FOREIGN KEY (database_slug) REFERENCES databases(slug)
);
CREATE TABLE IF NOT EXISTS database_reference_data_matches (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    database_slug            TEXT NOT NULL,
    surveyed_at              TEXT NOT NULL,
    source                   TEXT NOT NULL DEFAULT 'local',
    schema_name              TEXT NOT NULL,
    table_name               TEXT NOT NULL,
    column_name              TEXT NOT NULL,
    verdict                  TEXT NOT NULL,
    confidence               INTEGER DEFAULT NULL,
    evidence                 TEXT DEFAULT '',
    matched_display_name     TEXT DEFAULT '',
    matched_qualified_name   TEXT DEFAULT '',
    matched_guid             TEXT DEFAULT '',
    matched_element_is_draft INTEGER DEFAULT NULL,
    value_coverage           REAL DEFAULT NULL,
    unmatched_values_json    TEXT DEFAULT NULL,
    proposed_values_json     TEXT DEFAULT NULL,
    not_established_reason   TEXT DEFAULT '',
    sample_strategy          TEXT DEFAULT '',
    sample_rows              INTEGER DEFAULT NULL,
    sample_total_rows        INTEGER DEFAULT NULL,
    sample_seed              INTEGER DEFAULT NULL,
    statement                TEXT DEFAULT '',
    state                    TEXT NOT NULL DEFAULT 'measured',
    UNIQUE(database_slug, surveyed_at, source, schema_name, table_name, column_name),
    FOREIGN KEY (database_slug) REFERENCES databases(slug)
);
CREATE TABLE IF NOT EXISTS database_nested_columns (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    database_slug          TEXT NOT NULL,
    surveyed_at            TEXT NOT NULL,
    source                 TEXT NOT NULL DEFAULT 'local',
    schema_name            TEXT NOT NULL,
    table_name             TEXT NOT NULL,
    column_name            TEXT NOT NULL,
    column_family          TEXT DEFAULT '',
    label                  TEXT NOT NULL,
    key_count              INTEGER DEFAULT NULL,
    max_depth              INTEGER DEFAULT NULL,
    schema_json            TEXT DEFAULT NULL,
    not_established_reason TEXT DEFAULT '',
    sample_strategy        TEXT DEFAULT '',
    sample_rows            INTEGER DEFAULT NULL,
    sample_total_rows      INTEGER DEFAULT NULL,
    sample_seed            INTEGER DEFAULT NULL,
    state                  TEXT NOT NULL DEFAULT 'measured',
    UNIQUE(database_slug, surveyed_at, source, schema_name, table_name, column_name),
    FOREIGN KEY (database_slug) REFERENCES databases(slug)
);
CREATE INDEX IF NOT EXISTS idx_db_dc_matches_slug ON database_data_class_matches(database_slug, surveyed_at);
CREATE INDEX IF NOT EXISTS idx_db_rd_matches_slug ON database_reference_data_matches(database_slug, surveyed_at);
CREATE INDEX IF NOT EXISTS idx_db_nested_cols_slug ON database_nested_columns(database_slug, surveyed_at);
```

Postgres: the identical statements, with `PostgresCursorWrapper._translate_sql` rewriting
`id INTEGER PRIMARY KEY AUTOINCREMENT` to `id SERIAL PRIMARY KEY` and `?` to `%s`. Nothing else
differs (this was printed from the wrapper, not hand-written). It is checked against a fake raw
cursor in `test_postgres_migration_sql_without_a_connection` (every statement is
`CREATE TABLE/INDEX IF NOT EXISTS`, no `ALTER`/`DROP`/`DELETE`, `SERIAL` present, no
`AUTOINCREMENT`), the same approach as `tests/test_curate_authors.py`. It was never run against a
server.

## Files

- `resource_explorer/registry.py`: three section constants, three DDL statements, three indexes,
  three `()` migration entries, order map entries, `get_latest_section_coverage`.
- `resource_explorer/surveyors/database/column_match_store.py` (new): row builders and
  `store_column_match_results`.
- `resource_explorer/surveyors/database/database_surveyor.py`: records a failed step and calls the
  store from `_store_results`.
- `resource_explorer/surveyors/database/nested_columns_step.py`: per-column schema/table/column
  names, sample basis and reason (additive keys).
- `resource_explorer/surveyors/database/survey_definition_adapter.py`: three results readers, three
  headline readers, entries in `DATABASE_ANALYSIS_RESULTS_MAP` and `DATABASE_ANALYSIS_HEADLINE_MAP`.
- `resource_explorer/workflows/scouting.py`: `question_has_data` skips the `_status` envelope.
- `tests/test_db_value_analyses_results_readers.py` (new, 28 tests),
  `tests/test_db_fs_results_and_questions.py` (map count 19 to 22, the expected-absent set shrinks to
  `egeria_db_survey`), `frontend-build/test-harness/db-value-analyses-summary.test.mjs` (new, 5).

No UI source changed: the pane renders the headline, the COUNTS table and `boardStateKey` for any
analysis, and that is all these use. No Tailwind class was added.

## Verification

- Environment: `uv run python -c "import resource_explorer; print(resource_explorer.__file__)"` printed
  `/Users/dwolfson/localGit/egeria-v6/trellis-re-db-results-readers/packages/resource-explorer/resource_explorer/__init__.py`
  (this worktree). Every test ran with `PGVECTOR_PORT=1` and `REGISTRY_DATABASE_URL` pointing at a
  temp SQLite file; nothing touched localhost:5442.
- Red on main, green here: with the source reverted (tests kept) the new test module fails to
  import (`cannot import name 'SECTION_DATA_CLASS_MATCHES'`), the two pinned counts fail
  (`DATABASE_ANALYSIS_RESULTS_MAP` 19 vs 22 and `_DETAIL_TABLE_SPECS` 10 vs 13), and with only the
  `question_has_data` change reverted the three never-run tests fail (the envelope ticked the
  question). With the change: 28 new tests pass, plus the two updated pins.
- Full run over the files touched, every test mentioning `DATABASE_ANALYSIS_RESULTS_MAP` or the
  three ids, `test_next_*`, `test_tailwind*`, `test_static_js_syntax`, `test_registry*` and the
  nested/column tests (90 files): 1735 passed, 104 skipped (real-Postgres tier, skipped by
  `PGVECTOR_PORT=1`), 1 failed (`test_every_declared_table_exists_and_round_trips`, the pinned
  count of 10, since updated to 13 and re-run green with the new module, 82 passed).
- jsdom harness (Node 20.11.0): `npm run test:harness` 266 passed, 0 failed. The 5 new tests pin
  how the existing generic mechanism renders these payloads; they pass on main too, because no UI
  source changed, so they are not a red-to-green test.

## Not verified

- No live run: `data_class_match`, `reference_data_match` and `nested_column_profile` were not
  run against coco_pharma or any database, so no real stored result was read. The owner's gate
  ("coco_pharma shows a result for each, or an honest not run") is not done: coco_pharma ran these
  before this change and has no stored rows, so until it is run again it reads `not_established`
  ("ran before its results were stored") on the question and the fact, and `Not run yet.` on the
  By analysis card (that card only sees `has_results`, and cannot tell a never-run database from
  one whose run predates storage).
- No real Postgres: the Postgres SQL is a wrapper translation checked against a fake cursor. Not
  checked on a server: `INTEGER` for `sample_total_rows` / `sample_seed` (the same width as the
  existing `database_column_profiles` columns, so a table with more than 2^31 rows overflows there
  too) and the `FOREIGN KEY ... REFERENCES databases(slug)` on the live schema.
- The credential-scope state is read from the latest `credential_capability` probe, not from the
  run itself, the same as `schema_inventory`; a probe older than the run could mislabel it.
- The reference catalogue read (Egeria's Data Classes and Valid Value Sets) is unchanged: when the
  platform cannot be read every column is `no_candidates` and the reader says `not_established`.
  Whether that happens on a live run was not observed.
- The per-column `columns` list is returned whole (as `schema_inventory` returns `tables`); a
  database with thousands of columns makes a large payload that was not measured.
