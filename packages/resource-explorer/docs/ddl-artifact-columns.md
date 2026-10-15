# DDL record: artifacts slice-1 columns (re/artifact-columns)

**Status:** branch, not deployed. This is the deployment record for three additive columns in RE's shared
registry. **Decision (project owner, 2026-10-15):** go on the artifacts slice-1 DDL columns, which are
`survey_commit_sha` per run and `file_role` per symbol and marker row from one shared classifier
(DESIGN-ARTIFACTS-VIEW-AND-DOC-LINKS.md §3, §7.1).

Nothing in this branch has run against the shared registry (localhost:5442). The columns are added only by
RE's own schema init, the first time a process running this code opens the shared registry, and only after the
owner's word for that restart. Merging is not enough.

## The exact Postgres DDL

`ProjectRegistry._add_nullable_text_column` in `resource_explorer/registry.py` runs these from
`_init_schema`. Each one runs only when `_get_table_columns` says the column is missing, inside the init
transaction:

```sql
SET LOCAL lock_timeout = '10s';
ALTER TABLE project_code_symbols ADD COLUMN IF NOT EXISTS file_role TEXT;
SET LOCAL lock_timeout = '10s';
ALTER TABLE project_code_markers ADD COLUMN IF NOT EXISTS file_role TEXT;
SET LOCAL lock_timeout = '10s';
ALTER TABLE step_runs ADD COLUMN IF NOT EXISTS survey_commit_sha TEXT;
```

The three run in the order `_init_schema` reaches them: symbols right after that table's existing column
migrations, markers right after its CREATE TABLE, and step_runs after its `engine_action_*` migrations. On
SQLite the same statements run without `IF NOT EXISTS`.

The columns are nullable with no default. On Postgres 11 and later that is a catalog-only change, with no table
rewrite, and needs only a brief ACCESS EXCLUSIVE lock on each table. If another process holds that lock, the
ALTER fails after 10 s with RuntimeError "Could not add <table>.<column>: another process holds a lock …; stop
other Resource Explorer processes and restart.", rather than queueing every reader behind it. This is the same
shape as `resource_schedules.created_by` (2026-10-11) and `step_runs.engine_action_requested_at`.

Older rows read NULL, and no data is migrated.

| Column | Holds | NULL means |
|---|---|---|
| `project_code_symbols.file_role` | `core`, `test`, `generated`, `vendored` or `docs` | extracted before the column existed |
| `project_code_markers.file_role` | the same | the same |
| `step_runs.survey_commit_sha` | the commit a repo step run surveyed | not a repo run, no commit known for the repo (`last_commit_sha` empty), or the row predates the column |

## Which code writes and reads them

**Writes.**
- `ingestion/file_role.py` `classify_file_role(path)` is the one classifier. It calls
  `ingestion/vendored.provenance` for vendored and generated paths, `ingestion/test_paths.is_test_path` for tests,
  and checks for a `docs/`, `doc/` or `documentation/` directory outside a `src/` root.
- `CodeSymbolExtractor.extract` and `extract_markers` (`ingestion/code_symbol_extractor.py`) stamp `file_role` on
  every row they return. Every extraction path goes through them: the survey step `repo_symbol_extraction`
  (`SymbolExtractionSurveyor`), RAG ingestion and `refresh_profile` (`ingestion/pipeline.py`).
- `ProjectRegistry.upsert_code_symbols` writes the role, and a re-extraction overwrites it.
  `upsert_code_markers` also writes the role.
- `ProjectRegistry.record_step_run` copies `projects.last_commit_sha` into `step_runs.survey_commit_sha` for
  `entity_type='repo'`, in the same transaction as the insert. The local, Prefect and observer paths all go
  through it (`step_cost_observer.record`). The value is copied rather than joined, so a later fetch does not
  rewrite an earlier run.

**Reads.**
- `artifact_provenance.py` provides `role_label`, `commit_label` and `extraction_commit` (the latest
  `repo_symbol_extraction` step run's `survey_commit_sha`). NULL reads "not recorded".
- `members._symbols_in_file` shows each symbol's role. `members._symbol_members` adds "Symbols extracted at
  commit <sha12>", or "Extraction commit not recorded".

**Known limit.** The survey reads a zipball of the default branch at download time
(`GitHubClient.zipball_root`, which knows that SHA). `projects.last_commit_sha` is set only by
`IncrementalIndexer` and the CLI wizard, so a repo surveyed without a re-index records the last indexed commit,
which may be older than the surveyed tree. The slice-1 brief chose `last_commit_sha`. Making the zipball's own
SHA the source would change only `record_step_run`'s single read.

## Which processes would create it

These columns are added by the first process running this code that constructs a `ProjectRegistry` against the
shared registry. The creators are the same five as for `step_annotations` (`docs/ddl-step-annotations.md`):

1. 8813, the gate server, on its restart. This is the intended creator.
2. 8810, `--reload` on the main checkout. Do not fast-forward the main checkout before the owner's word.
3. The Prefect worker, on its next start.
4. Any CLI or `re-py.sh` probe run from a checkout that carries the change.
5. Test runs, but only in their own throwaway schema.

No script or SQL file outside `registry.py` alters these three tables.

## BEFORE snapshot: `~/.re-gate/scripts/ddl_artifact_columns_snapshot.py before`

The snapshot is read-only: one psycopg2 session with `readonly=True`, running SELECTs only. It never imports
`resource_explorer`. It records:

- the server time;
- the column lists of the three tables;
- the row counts of `project_code_symbols`, `project_code_markers` and `step_runs`, plus `projects` and
  `activity_log`;
- the granted advisory locks.

It exits 1 if any of the three columns already exists.

```
REGISTRY_SNAPSHOT_URL=postgresql://<user>:<pwd>@localhost:5442/egeria_advisor \
    python ~/.re-gate/scripts/ddl_artifact_columns_snapshot.py before > before.txt
```

## AFTER check: the same script, `after`

It checks the following, and exits 1 if any check fails:

- Each column exists once, in `resource_explorer`, as `text`, nullable, with no default.
- Every other column of each table is unchanged and in its old order. The new one is appended last.
- The non-NULL counts are reported: 0 right after the restart, and they rise only as surveys run. A non-NULL
  `file_role` must be one of the five roles.

Then run `diff before.txt after.txt`. The row counts should be unchanged apart from ordinary traffic.

## Creator honesty

Postgres keeps no timestamp for an ADD COLUMN. The record therefore names which process ran first after the
owner's word. Later `_init_schema` runs are no-ops, because each column is checked first and the ALTER uses
`IF NOT EXISTS`.
