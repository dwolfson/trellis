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

- [x] **Slice of 12 done 2026-08-27** — one repo per language, 2→65k stars,
      5→423 contributors. `supply_chain` 11/12 (the 12th, `awesome_kedro`, is an
      awesome-list with no `.github/workflows` — a real result, not a failure);
      `foss_scorecard`/`chaoss_metrics`/`cii_badge` 12/12. ~18 min, no errors,
      though `openmetadata`'s zipball alone took ~11.
- [x] **Slice judged representative.** All three supply-chain checks
      discriminate (dangerous_workflow 7 pass/4 fail; pinned_dependencies 6
      partial/5 fail; token_permissions 9 partial/2 pass), every language is
      covered, and nothing failed systematically. Scorecard coverage rose from
      5–8 to **10–11 of 16 checks evaluated**, and scores *fell* as it rose
      (openmetadata 8.6→7.0, deep_causality 7.5→7.3) — correct, since fewer
      flattering unknowns are being excluded.
- [ ] **Run the remaining ~48 repos.** For coverage, not validation — the
      checks are proven. Budget for it: one large repo took 11 minutes.
- [ ] Re-check the whole-catalogue coverage table afterwards.

**Verified by hand, not taken on trust:** `data_prep_kit`'s 7 checkout hits were
confirmed earlier from a local clone. `genaieval`'s hit is the *script-injection*
path, which had only synthetic coverage until now — checked against the real
file: `pr-path-detection.yml` interpolates
`${{ github.event.pull_request.head.ref }}`, an attacker-controlled fork branch
name, straight into a shell `run:` block. True positive.

**Refinement worth logging:** the injection check does not distinguish
`pull_request` from `pull_request_target`. Both are genuine injection, but only
the latter runs with the base repo's secrets, so blast radius differs and the
finding currently reads the same for both.

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

**Two live findings, 2026-08-27 — both change the design, neither is in the
design note yet:**

1. **`get_active_claimed_engine_actions` cannot be used to FIND work.** Called
   with the `EgeriaWatchdog` engine's GUID it returns `'No elements found'`
   while three actions are `IN_PROGRESS` on that very engine — at every
   page_size, so it is not paging. Those three are claimed by
   `egeriawatchdogengine`, and the call was made as `erinoverview`. So it is
   caller-scoped: it answers "what have *I* claimed", not "what is available".
   Useful for **recovery after a restart** — reclaiming what we already hold —
   and useless for discovery. Finding claimable work needs
   `get_active_engine_actions` filtered on unclaimed status instead.

2. **RE needs its own engine-host user identity.** It talks to Egeria as one
   fixed service account (`erinoverview`). The watchdog claims as
   `egeriawatchdogengine`. Claims are attributed to the caller, so without a
   distinct identity RE's claims are indistinguishable from any other use of
   that account — and finding (1) means RE could not even list its own claimed
   work apart from anyone else's. This is a deployment prerequisite, not a
   coding detail.

3. **`EgeriaConfig.engine_host` is vestigial.** Declared in `config.py:147`
   with alias `EGERIA_ENGINE_HOST` and read nowhere in the package. It reads
   like engine-host support exists when none does — a deployment engineer
   setting it would reasonably expect an effect. Either wire it during this
   work or delete it; leaving it is a false affordance.

Also noted: `actionStatus` is the field on `get_active_engine_actions`'
payload, while `egeria_delegated_step` found the real key was `activityStatus`
when reading the same concept through `get_metadata_element_by_guid`. The name
differs by endpoint — worth pinning wherever the loop reads status, since that
exact mismatch already caused one false-terminal bug.

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
