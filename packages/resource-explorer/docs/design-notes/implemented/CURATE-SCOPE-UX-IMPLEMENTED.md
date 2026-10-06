# Curate scope UX slice, implemented (2026-10-06)

Branch `re/curate-scope-conflicts-layout-selection`. Parts: (1) name conflicts removed, (2) layout,
(3) filter and multi-select, (4) one read per write and a render error banner, (5) the repository
plan's non-blocking loading state, (6) toggle pins, commit button, choice feedback.

## Part 5: the repository Curate plan (perf row for the backlog)

`GET /api/projects/<slug>/curate/plan` took 25,127 ms on `egeria_git`. The stage used to show
"Assembling what the catalogue would learn…" with no clock; it now draws at once with
`plan loading · n s` (seconds from a clock, a fake one in the tests), the other bands load on their
own and the rest of the page stays usable, the plan fills in when it arrives, and a failure shows
its cause and the elapsed time.

Cause, measured on a temp-SQLite fixture (no Egeria, no shared registry), `build_plan` under cProfile:

- **One number: 6 of the 6 fact reads each call `record_gaps_for`, and that is 36 of 40 ms (90%) of
  `build_plan` on a small fixture.** One plan issues 669 SQL statements and 1,294 connection
  checkouts (about 111 statements per gap pass: `collect_gaps` -> `_disagreement_gaps` ->
  `_r_changed_since_survey` -> 37 `detect_change` calls per pass). `layer.facts()` is called once per
  analysis id (`_fact`), so the gap pass runs 6 times; passing the six ids to one `facts()` call
  would run it once.
- The size-dependent part is the sub-resource survey: 20,000 findings moved the same plan from 41 ms
  to 466 ms, dominated by reading that analysis twice (`_sub_resource_survey_results` and its headline;
  145 `query_findings` calls, 40,465 row objects).
- No Egeria call is made by `build_plan` (nothing in `curate_plan.py` reaches Egeria).
- NOT reproducible here: the 25 s. On SQLite the statements are microseconds; 669 statements over 25 s
  is about 37 ms each, which fits a Postgres round trip plus pool checkout under load, but that is an
  inference from the arithmetic, not a measurement. The next measurement belongs on the gate server:
  time `record_gaps_for` once inside `_fact`.
