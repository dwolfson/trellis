# Resync heal keyed on flagged rows — implemented

## Environment confirmation (before any test run)

`uv sync --all-packages --extra dev` in this worktree, then from
`packages/resource-explorer`:

    resource_explorer.__file__ =
    /Users/dwolfson/localGit/egeria-v6/trellis-re-resync-heal/packages/resource-explorer/resource_explorer/__init__.py

Signing verified with a real `git commit -s -S` (`%G?` = G), then dropped.

## The bug

`_do_flag_vanished_publishes` healed only when the current scan's
`vanished_publishes` finding was non-empty, and `scan()` drops empty findings
(`res.findings = [f for f in res.findings if f.count]`). Once a republish
resolved, the finding became empty, the step was never scheduled/offered
(`scan_and_clear` applies a step only if its finding is present), and the old
flag never cleared. Live: egeria-python republished 5 times since 2026-09-29,
still showing "no longer in the store". Second defect: the heal iterated
`get_latest_egeria_surveys_all_projects()`, which only returns projects WITH a
report guid, so a flagged slug with no report (amundsen, sqlglot) could never
clear.

## The fix

- Heal is keyed on the flagged rows: `registry.list_egeria_linkages('repo_publish')`
  (status stale or uncatalogued), each re-verified against that slug's CURRENT
  latest report.
  - resolves: flag cleared (time logged and returned as `healed_at`/`healed_slugs`;
    the row is deleted, since absence means healthy, so the clear time lives in the
    log and the pass result, not on a row)
  - still absent: flag kept, `last_checked_at` advanced (`detected_at` preserved)
  - lookup failed: left alone, counted as undetermined
  - no report at all: status becomes `uncatalogued`, wording "not catalogued,
    publish needed"
- New finding `flagged_publish_rows` ("Publish flags awaiting re-check", same
  repair step) so the heal is reachable by both the scheduler and the manual
  Apply UI even when `vanished_publishes` is empty. Uncatalogued rows appear in
  it only once a report exists to re-read.
- New registry methods `mark_egeria_linkage_uncatalogued`, `list_egeria_linkages`.
- Surfaces: `publish_uncatalogued` added beside `publish_stale` in the analysis
  payloads, survey-definition candidates and ScoutingOverview; classic cards and
  /next show "not catalogued, publish needed". Every existing consumer tests
  `status == "stale"`, so the new status simply stops showing the stale warning.
- Slug note: linkage rows for repos key on the normalized slug (underscores, e.g.
  `egeria_python`), because they are written from `project_egeria_surveys`.

## Tests (`tests/test_egeria_resync.py::TestHealKeyedOnFlaggedRows`)

Real registry, real `scan_and_clear` pass (so the gating is under test):
republish clears the flag in one pass (the docstring's promise); still-vanished
keeps the flag and advances `last_checked_at`; no-report flagged slug becomes
`uncatalogued` and renders the new note; uncatalogued heals once a resolvable
report exists. Red proof: with `egeria_resync.py` reverted (git stash push by
path), the republish, no-report and uncatalogued-heal tests fail; restored, all
14 pass.

## Lesson to watch for elsewhere (documented, NOT fixed elsewhere)

**A scan step that drops empty findings made a downstream heal step unreachable
once the thing it was healing resolved on its own.** Shape: step B is gated on
"step A's finding is present", but B's job is to clean up state that A's
finding used to describe. When the underlying problem fixes itself, A's finding
goes empty, B never runs, and the stale record outlives its cause. Check any
"apply only if the finding is present" gate (`scan_and_clear`, the Admin
Egeria Alignment ticking logic) and any heal that iterates a scan result rather
than the persisted rows it is meant to clear. Heals should key on the persisted
marker, not on the detector's current output.
