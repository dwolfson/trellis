# Open stack — working checklist

**Purpose:** the live list of what is outstanding right now, across repos, so it
survives a context reset. Short entries with a pointer; the reasoning lives in
the design docs. Delete an entry when it is done — this is not a history.

**Last updated:** 2026-08-27

---

## 1. Backfill — the analyses that answer nothing yet

**The headline problem.** Code merged, tested, and inert.

| analysis | repos with findings (of 60) | notes |
|---|---|---|
| `supply_chain` | **0** | so all three supply-chain checks on the FOSS scorecard report `unknown` for every repo |
| `foss_scorecard` | 5 | only repos touched during verification |
| `chaoss_metrics` | 8 | " |
| `cii_badge` | 8 | " |

- [ ] Run `repo_manifest_parse` across a **representative slice**, confirm the
      slice is representative, widen if not. 60 zipball downloads if run whole,
      so volume and timing are a deliberate choice, not a default.
- [ ] Then `foss_scorecard`, `chaoss_metrics`, `cii_badge` — all zero-fetch, so
      cheap once their inputs exist.
- [ ] Re-check the coverage table above afterwards.

## 2. ~~Retire the ISSUE-50 workaround~~ — DONE 2026-08-27

`EgeriaDelegatedStepSurveyor` routes through `initiate_gov_action_type()`,
which needs a **pre-authored `GovernanceActionType` per delegated step**. The
pyegeria bug that forced it is fixed: `initiate_engine_action` now takes
`governance_engine_name`. `initiate_and_wait()` already exists in the module.

- [x] Switch the primary trigger path to `initiate_and_wait()`
- [x] Live-verify against a real delegated step
- [x] Drop the per-step `GovernanceActionType` *requirement* — the direct path
      needs no pre-authored element. The probe doc is kept: it documents the
      action-type path, which is still valid and still preferable when a
      `GovernanceActionType` already exists.
- [x] Remove the stale comment saying the direct path is "kept for when
      ISSUE-50 is fixed"

Live-verified: a real engine action on the Stewardship engine reached `COMPLETED` through the
direct path. Also fixed en route: the Prefect tests were not hermetic — they honoured a
configured `PREFECT_API_URL` from `.env`, so they passed in one checkout and failed in another on
ambient environment alone. Shared `ephemeral_prefect` fixture in `tests/conftest.py`.

## 3. RE as an engine host — unblocked, not started

Server arbitration confirmed (`OMAG-GENERIC-HANDLERS-403-003`, first-claim-wins),
client methods available since the pyegeria 6.1.5 upgrade, and the refusal
arrives as a typed `PyegeriaUnauthorizedException`. Nothing external is gating
this any more.

- [ ] Register RE's steps as request types via `link_supported_governance_service`
- [ ] Implement find → claim → execute → report
- [ ] Decide polling cadence (Kafka is an optimisation only — correctness rests
      on `claim`, not delivery)

Design: `docs/survey-model-and-engine-host-design.md` §4.

## 4. The granularity collapse — deferred by decision

`analysis_id`'s bundling role duplicates the survey type: 25 of 27 repo analyses
are a single step. Its *results* role is real and stays.

Migration risk was the blocker; that is now moot — Egeria can be wiped and
rebuilt (export/import round-trips 62 resources, bulk republish works). So this
is about the model being right, not about data.

- [ ] Own design pass. Touches `resource_schedules` (keyed by `analysis_id`) and
      27 render payloads.

Design: `docs/survey-model-and-engine-host-design.md` §2.

## 5. Smaller / opportunistic

- [ ] `project_contributor_stats` has no real reader since CHAOSS moved to
      `project_commits`. Either fix the writer to produce disjoint periods or
      retire the table — a table that looks like a time series and is not is
      exactly the trap it caused.
- [ ] `needs_republish: 7` in the Egeria Alignment scan — no automatic repair by
      design (needs a decision per resource). Worth checking whether the count
      should be growing.
- [ ] Egeria-side: `_parse_graph` now reads branching definitions, but no
      definition uses a guard yet. Authoring one would exercise the whole chain
      end to end on real data.

---

## Done 2026-08-26/27 — do not redo

Three Survey Definition hazards (generator overwrite, reconciler deleting
branches, drift scan conflating recovery with coverage); annotation types
published by name; whole-survey sequencing handed to Prefect; the reader
reading branching definitions; four new analyses (FOSS scorecard extension,
CVE scan, CHAOSS, CII badge); pyegeria 6.1.5 upgrade.
