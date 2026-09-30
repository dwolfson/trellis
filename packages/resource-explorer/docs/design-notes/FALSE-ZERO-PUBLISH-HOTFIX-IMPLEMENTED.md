# False-zero publish hotfix — implemented

Branch `re/false-zero-publish-hotfix`, cut from main 46653b28.

## Environment evidence (before any test run)

`uv sync --all-packages --extra dev` was run in the worktree, then:

```
$ uv run python -c "import resource_explorer; print(resource_explorer.__file__)"
/Users/dwolfson/localGit/egeria-v6/trellis-re-false-zero-publish/packages/resource-explorer/resource_explorer/__init__.py
```

That path is INSIDE this worktree (`trellis-re-false-zero-publish`), not main's
checkout (`trellis`). Test numbers below are only evidence because of this line.

(Trigger analysis and implementation notes follow as the work lands.)

## What happened (trigger, from the activity_log)

Three rows at 12:17:19, 12:18:57, 12:21:32 UTC (2026-09-30), all
`localhost_docker_coco_pharma`, source `egeria-published`, 0/0/0. Each pair of
activity rows shows `POST /api/databases/{slug}/survey` with the Egeria option
ticked (the classic UI's Survey modal — /next has no caller of that route). It
ran a one-step synthetic `postgres_schema_and_stats` (`egeria-adaptive`); the
local survey failed on `password authentication failed for user
"erinoverview"`, the step still reported `ok`, and the executor's publish step
wrote an empty row. The stored credential was wrong because of an
accidental `update-credentials` (a separate, owner-side fix).

## Rules as implemented

1. **A publish step writes no survey row.** `publish_step_annotations` and
   `publish_local_survey` no longer call `record_database_survey`. The Survey
   Definition publish step (`survey_definition_adapter._publish`) records its own
   `step_runs` row (`step_key=egeria_publish`) and stamps `published_at` +
   `egeria_report_guid` on the measured row it published
   (`record_database_survey_published`). With no in-run schema inventory and no
   measured stored row it raises instead of publishing an empty inventory.
   Readers of `source='egeria-published'` / the survey-row report guid were
   grepped: for databases only the classic UI's source badge map and the
   `last_survey_source` comment read it; the repo-side `egeria_report_guid`
   readers use `project_egeria_surveys`, not this table. No reader needed more
   than the small adaptation above.
2. **One predicate**: `registry.is_measured_survey(row)` (not invalid, source not
   `egeria-published`, non-empty schema_info) and
   `ProjectRegistry.latest_measured_database_survey`. Used by the classic Publish
   route and the publish step.
3. **Mark, don't delete**: `database_surveys.invalid_at` / `invalid_reason`
   (pattern: `superseded_at` on findings). `get_database_surveys`,
   `get_latest_database_survey`, `find_latest_database_survey_with_key` and the
   cache freshness signature exclude invalid rows
   (`get_database_surveys(include_invalid=True)` still returns them). Marking
   re-syncs the `databases` summary counts / last_surveyed_at.
   CLI: `resource-explorer repair mark-false-zero-surveys` — **dry run by
   default**; `--apply` marks. Keyed on the damage (publish source AND empty
   schema_info), any slug.
4. **Swallowed error**: the `egeria-adaptive` handler returns status `failed`
   with the real errors when nothing was measured and errors exist; the executor
   appends those errors to the run, and does not pass a failed step's output to
   the publish step. The classic Survey route turns a failed step into an error
   response (auth failure shown on the run, no row written). The classic Survey
   modal confirms "runs postgres_schema_and_stats, which publishes to Egeria"
   before an Egeria-hybrid run. /next's `planSurveyRun` is untouched.

Not done here: `EgeriaFileSystemSurveyor` has the same publish-writes-a-row
pattern (`egeria_filesystem_surveyor.py`); out of scope for this hotfix.

## Dry run against the dev registry

See the report for the exact output. Note: constructing `ProjectRegistry` from
this branch runs its additive migration (three nullable columns on
`database_surveys`) against the shared dev Postgres.

## Test evidence (import path confirmed above, inside this worktree)

`uv run pytest packages/resource-explorer/tests`: 7158 passed, 103 skipped, 0 failed
(18 min). New file: `tests/test_false_zero_publish_hotfix.py` (27 tests: predicate
table incl. "newest empty, older measured returns the older row"; mark-not-delete
and reader exclusion; dry-run-by-default CLI and its output format; publish writes
no row, twice; publish route pushes 8/61/479; failing survey => status failed, real
auth text, no publish, no row; classic route shows the failure with no row; classic
modal confirm wording). No /next change, so no /next harness entry.
