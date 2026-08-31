# Open stack — working checklist

**Purpose:** the live list of what is outstanding right now, across repos, so it
survives a context reset. Short entries with a pointer; the reasoning lives in
the design docs. Delete an entry when it is done — this is not a history.

**Last updated:** 2026-08-31

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
- [x] **Remaining 48 done 2026-08-27** — 96 orchestrator invocations, zero
      failures. ~17 min for step 1, under a minute for step 2.
- [x] **Whole-catalogue coverage:**

      | analysis | before | after |
      |---|---|---|
      | `supply_chain` | 0/60 | **50/60** |
      | `foss_scorecard` | 5/60 | **60/60** |
      | `chaoss_metrics` | 8/60 | **60/60** |
      | `cii_badge` | 8/60 | **60/60** |

      The 10 without `supply_chain` genuinely have no `.github/workflows` —
      confirmed per repo by the presence of `repo_conventions` findings, which
      proves the parse ran.

      Catalogue-wide label spread: `dangerous_workflow` 43 pass / 8 fail;
      `pinned_dependencies` 1 pass / 14 partial / 36 fail; `token_permissions`
      8 pass / 36 partial / 7 fail. Exactly **one** repo in sixty pins every
      GitHub Action to a commit SHA.

- [ ] **Verify the 8 `dangerous_workflow` failures.** Four were hand-checked
      (`data_prep_kit`, `genaieval`). The other four are `docs`, `genaiinfra`,
      `haystack_opea`, `langchain_opea` — and note they share one workflow,
      `pr-path-detection.yml` / `pr-link-path-scan.yaml`, the same OPEA-project
      file copied between repos. So it is likely **one upstream pattern**, not
      four independent findings, and worth reporting upstream once rather than
      four times.

**Verified by hand, not taken on trust:** `data_prep_kit`'s 7 checkout hits were
confirmed earlier from a local clone. `genaieval`'s hit is the *script-injection*
path, which had only synthetic coverage until now — checked against the real
file: `pr-path-detection.yml` interpolates
`${{ github.event.pull_request.head.ref }}`, an attacker-controlled fork branch
name, straight into a shell `run:` block. True positive.

**Also open:** a repo with no `.github/workflows` gets no `supply_chain`
findings at all, by the parser's documented convention (three "fail" rows for a
repo with no CI would be findings about a thing that does not exist). That is
still right — but the card then renders an absence, where "this repo has no
GitHub Actions workflows" is a measured, useful fact. Distinct from the
kedro_kubeflow case just fixed: there we never looked; here we looked and found
none. Worth a stated finding rather than silence.

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

## 3. RE as an engine host — BLOCKED, and a design already exists

**Correction 2026-08-27.** This section previously said "unblocked, not
started". That was wrong on both halves.

**A complete design already exists:** `docs/re-as-engine-host-plan.md`
(2026-08-17), grounded in a direct read of Egeria's Java source — the four
execution permutations, the reachability dimension, and case 2 ("RE as a
claiming engine") as the real investment. It is marked **ON HOLD**. Anything
starting here should begin by reading it, not by re-deriving it.

**Two hard gaps, confirmed by reading pyegeria 6.1.5 and by probing the live
platform:**

1. **Nothing can create a `GovernanceEngine` or `GovernanceService` element.**
   pyegeria has no create method and no properties class for either — only
   link/update/detach for the `SupportedGovernanceService` *relationship*,
   which presupposes both elements exist. This is **server-side**:
   `GovernanceConfigurationResource` is read-only, and Egeria itself populates
   engines and services through content-pack archive writers. Not a wrapping
   gap; an Egeria change or archive-based registration is required.
2. **No way to list claimable work — and it is NOT a wrapper gap.**
   *Corrected 2026-08-27 after `egeria-python-07` checked the Java source and
   pushed back.* I had recorded this as "only a wrapper gap; the route exists",
   taking `re-as-engine-host-plan.md` at its word that
   `.../active-engine-actions` was "the per-engine claimable-actions listing,
   distinct from the requester-side general listing". It is not distinct.

   Verified in `egeria-v6/egeria`: that route is declared in
   `GovernanceContextResource.java:89` and its handler is literally named
   **`getActiveClaimedEngineActions`**, with the Javadoc "engine actions that
   are still in process and that have been **claimed by this caller's userId**.
   This call is used when the caller restarts." It is the same restart-recovery
   operation as `.../engine-actions/active-claimed`, under a misleading URL.
   Live, it 404s on the View Service, which registers only `initiate` and
   `active-claimed` under `governance-engines/{guid}`.

   Enumerating **every** per-engine route in Egeria gives four: two config
   reads, the attach, and those two restart-recovery listings. **There is no
   claimable/unclaimed listing anywhere.** So this is a server-side gap — a
   missing Java endpoint — not a missing Python wrapper.

   The workable approach is the one live probing had already pointed at before
   the brief contradicted it: whole-server `get_active_engine_actions()`,
   filtered client-side by `governanceEngineGUID` and unclaimed status. Costs a
   wider fetch; correctness still rests on `claim` refusing a second claimant.

**The blocker the plan cites is not in any live tracker.** It cites
`ISSUE-51` for a template-created-asset bug where native surveys fail with
"connector is null". `PYEGERIA_ISSUES.md` was renumbered on 2026-08-15 and its
ISSUE-51 is now an unrelated, fixed `fetch_element()` issue. Searching the
canonical tracker for the blocker's own content — "connector is null",
`create_*_element_from_template` — returns nothing. The nearest match is `E1`
in RE's superseded local tracker, which is a *different* failure (a Postgres
repository connector 500 on classification save).

So a blocker that halted a workstream survives only as prose in a design doc,
under a number that now means something else. Before any build here:

- [ ] Re-verify whether the template/Connection failure still reproduces
- [ ] Re-file it in the canonical tracker with its own content, not a number
- [ ] Decide the registration route given gap 1 is server-side
- [x] ~~File the missing `active-engine-actions` wrapper~~ — there is nothing
      to wrap. Raise the missing *endpoint* with whoever owns the Java side, or
      accept whole-server-plus-client-side-filter.
- [x] **The blocker is real and current** — `egeria-python-07` reproduced it
      2026-08-27 and filed it as ISSUE-79 (odpi/egeria-python PR #314). A
      template-created FileFolder survives creation now (E1's 500 no longer
      reproduces) but its native survey fails server-side with a
      `NullPointerException` in `BasicFolderConnector.getFile()` because
      `assetConnector` is null. Two distinct bugs, as suspected — the design
      doc had conflated them. **So the ON HOLD stands, now for a documented,
      reproducible reason instead of a dangling number.**

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

**RE-side sketch (does not depend on the pyegeria registration answer):**

*One request type per step, not one generic one.* Egeria routes on
`requestType`, and a governance engine's whole purpose is to advertise what it
can do. 37 step keys today — 34 repo, 2 database, 1 filesystem. Collapsing them
into a single "run an RE step" request type with the step name as a parameter
would hide RE's capabilities from the catalog and put routing in a field Egeria
does not interpret, which defeats registering at all. Per-step is also what
makes `executes_at` collapse into catalog data (design note §4.4): the engine
holding a `SupportedGovernanceService` for `repo_manifest_parse` *is* where it
runs.

*But registering all 37 uniformly would be wrong.* Their infrastructure needs
differ — by `fetch_cost`: 19 need nothing but the RE database, 9 download a
zipball, 3 are api_heavy, 3 make one API call. A remote engine host running a
`download` step needs GitHub credentials and egress; a zero-fetch step needs
neither. So the registered set is a **per-deployment choice**, not a fixed list,
and the registration code should take the set as input rather than enumerating
STEP_REGISTRY.

Design: `docs/survey-model-and-engine-host-design.md` §4.

## 4a. Full Survey should live only in Automate — blocked on a surface

`RepoFullSurvey` (survey_kind `automate_full`) is appended to **every** stage
tab, so a 34-step deep survey sits one click away on Scouting, whose whole
purpose is the cheap look that gates it.

Attempted 2026-08-27 and reverted unshipped. The stage tabs filter correctly —
restricting the append to `intent === 'automate'` removes it from all four —
but **the Automate view has no survey list to move it to.** `showMainView('automate')`
renders `#automate-view`, which loads subscriptions and schedules and never
fetches Survey Definition candidates. So the change hides Full Survey
everywhere and gives it nowhere to appear, which is what the original
"appended to every stage" comment was avoiding.

- [x] **Automate has a survey list** — built 2026-08-30 (`fd63eed`). Third sub-tab beside 🔔 Subscriptions and
      ⏱ Schedules), then restrict the append to that intent. Both halves, or
      neither — the filter alone loses the feature.

## 4. The granularity collapse — deferred by decision

`analysis_id`'s bundling role duplicates the survey type: 25 of 27 repo analyses
are a single step. Its *results* role is real and stays.

Migration risk was the blocker; that is now moot — Egeria can be wiped and
rebuilt (export/import round-trips 62 resources, bulk republish works). So this
is about the model being right, not about data.

- [x] **Design pass done 2026-08-28** — `docs/granularity-pass.md`. It
      recommends a **smaller** change than the one it set out to design, and
      the checklist's own risk note was wrong: `resource_schedules` has **one**
      row, and the whole bundling role is **6 rows** across three tables. The
      74k rows are keyed by finding `kind`, which turns out to be its own
      vocabulary already — 5 kinds are not analysis ids, and 12 analyses have
      no kind at all — so the results half was never the same thing under
      another name and does not move.
- [x] **Widen the schedule target** — done 2026-08-28 (`aeec939`).
      `resource_schedules` gained `target_kind` (`analysis` | `survey`,
      defaulted by ALTER TABLE), `save_schedule` validates it, and
      `scheduler._execute` dispatches a survey target through
      `run_survey_definition`. §4a is no longer blocked on schema.
- [ ] Decide the §6 open question: should an analysis stay independently
      runnable once surveys are schedulable, or become view-only?

Design: `docs/survey-model-and-engine-host-design.md` §2.

## 5. Smaller / opportunistic

- [x] **Its one reader was fixed 2026-08-27.** `project_contributor_stats` has
      no *meaningful* reader since CHAOSS moved to `project_commits`, but it
      does have one: an agent tool reporting a contributor's tier. It ordered
      `period_start DESC LIMIT 1`, which — given nested trailing windows — is
      the *narrowest* (30-day) window, so it answered "tier over the last
      month" to a question about the contributor. Measured across the
      catalogue: **70 of 347** contributors got a different tier that way,
      every sampled case a core maintainer downgraded to "regular" (Apache
      Polaris, sqlglot), and **271 more** were absent from the 30-day slice, so
      the caller was told the tier was unknown and to "run refresh" about a
      tier already computed. Now `ASC` — widest window. Test pins the
      direction, since the two orderings differ by one keyword and the wrong
      one fails silently.
- [ ] The table itself still misleads by shape. Fix the writer to disjoint
      periods, or retire it and derive tier from `project_commits`. Not urgent
      now that its reader is honest — but the trap remains for the next
      consumer.
- [x] **Checked 2026-08-27, and the finding was wrong.** `needs_republish` billed
      all its members as "previously catalogued that Egeria no longer holds".
      Of the seven, only four were: `docling_eval`, `openlineage`,
      `openmetadata` and `unitycatalog` really were published on 24–25 Aug and
      lost their asset to the redeploy. The other three — `docs`,
      `enterprise_rag`, `genaicomps` — carry only a scout import from 21 Aug
      and were **never catalogued at all**. Telling someone they lost something
      they never had sends them hunting a fault that does not exist, and the
      two want different actions: restoring a known asset versus a first
      publish. The finding now states which is which, from whether a completed
      `catalog` operation exists in the activity log.
- [x] `unitycatalog` published 2026-08-28 — asset
      `8a9b783a-4871-4100-86df-9c705a13849e`, report
      `3c1aa491-8ea4-4110-a6d8-a6c3ca71aec0`.
- [x] **The three never-catalogued repos published 2026-08-28** — `docs`
      (`8e479ad8`), `enterprise_rag` (`92d9db93`), `genaicomps` (`5ab31495`),
      each a distinct asset. The finding is down to three, all of them the
      "lost an asset" kind and all blocked on a Project decision — so the
      remaining count is now exactly the blocked set, which is what the
      publish_ready field was added to make visible.
- [x] **Resolved 2026-08-30.** All three were assigned to the RE Test Project (contexts
      materialised from the investigation they already belonged to) and published:
      `docling_eval` `5eb02266`, `openlineage` `88a2a70e`, `openmetadata` `940abe1f`.
      `needs_republish` is now EMPTY — the whole finding went 7 → 0 on 2026-08-30.
      Originally measured
      2026-08-28: `docling_eval`, `openlineage` and `openmetadata` all carry
      an Egeria Project context of `unset`, and the publish route's Part 5
      gate returns 428 for `unset` unless an investigation supplies one by
      inheritance — none does. So the finding's own advice ("POST
      /api/egeria/{slug}/publish with steps ['repo_health']") is refused for
      exactly the repos it is offered for, and the panel does not say so.
      The three that CAN run it are the three never-catalogued ones (`docs`,
      `enterprise_rag`, `genaicomps`), which are `linked` — the inverse of
      what the wording implies. Either the finding names the gate, or the
      gate's 428 body carries the remedy; deciding which is the work.
- [x] Answered 2026-08-30 — RE Test Project, for all three. Originally: which Egeria Project each of
      the three belongs to. That names a real catalog object and stays a
      human call.
- [x] **Question catalog wired to the analyses that answer it** — 2026-08-28
      (`f0abe27`, `41b5c5f`, `b11536a`). The generator carried
      `KNOWN_ANALYSIS_IDS` as a hand-synced literal of 15 against a real
      catalog of 29, so 14 analyses were unrecognizable to it and a CSV row
      naming one was silently emptied and tagged `unknown` — the reason 18
      analyses had no question. Reads the catalog live now. Three stale GAP
      notes closed, three questions that shared `repository_health` given
      their own sources, eight questions added. 49 questions; 6 analyses
      unreferenced and correctly so (refresh actions, not questions).
- [ ] **9 questions still answer nothing** (6 `gap`, 3 `unknown`). Six need a
      content read nothing does yet — upgrade process, CLA/DCO provenance,
      telemetry detection, AI/ML model-card licensing, secret handling,
      similar-repo search. Three carry authorial uncertainty in the CSV
      ("repo_conventions - RAG read?") and want a decision, not a surveyor.
      This is the concrete shape of §5's agent-based post-ingestion work.
- [x] **Automate can schedule a whole survey** — 2026-08-28 (`fd63eed`). Third
      sub-tab, `GET /api/survey-definitions/definitions` (read from the
      authored documents, so it survives Egeria being down), `target_kind`
      exposed on the schedules route. §4a is done except moving
      `RepoFullSurvey` out of the four stage tabs.
- [ ] **`repo_profile_refresh` is schedulable but invisible to the step map.**
      `REPO_ANALYSIS_STEP_MAP.get("repo_profile_refresh")` is None, so a reader
      checking the map concludes it cannot be scheduled. It can: `scheduler.
      _run_repo_survey` intercepts it earlier on `action == "profile"` and
      chains `language_file_classification` afterwards. Same shape as
      `rag_ingestion`, which is intercepted on its id. Nothing is broken; the
      map simply is not the whole dispatch story and reads as though it were.
      Either the map carries these entries or its name stops implying
      completeness.
- [x] **The schedules route now checks the resource exists** — `a11ddc4`.
      404 per resource kind on POST; DELETE deliberately unguarded, since
      clearing a schedule that points at a deleted resource is what it is for.
      Two existing tests were passing on slugs that had never existed and now
      register their resources.
- [ ] Egeria-side: `_parse_graph` now reads branching definitions, but no
      definition uses a guard yet. Authoring one would exercise the whole chain
      end to end on real data.

---

## 6. Raised 2026-08-31 — the security/survey thread

Everything below came out of one session. Design reasoning lives in
`survey-composition-and-topic-summary-design.md` (98608f1); this is the do-list.

### Done, do not redo
- [x] `security_scan` renamed **Security Hygiene** with an honest description (98608f1). Id unchanged.
- [x] `cii_badge` SSH-remote false negative — `git@github.com:...` reported a silver badge as
      `not_registered` (3c71785).
- [x] `ephemeral_prefect` autouse + the import note (a8dd281, e44300e).

### Direct asks, not started

- [ ] **Results → Dashboard rename.** 5 label strings in `index.html`; the 24 internal ids
      (`'results'`, `stage-results`, `_resultsHost`) stay. The placement comment calls it "where a
      run's results naturally get looked for" — that is the conflation being fixed.
- [ ] **Admin has nowhere to see feedback.** `list_resource_feedback(entity_type, slug)` is
      per-resource only, surfaced in Curate. No cross-resource view exists.
- [ ] **Admin is 9 flat tabs.** Proposed grouping: *Config* (Annotation Types, Groups, Discovery
      Sources, Question Catalog) · *Resync & Repair* (Egeria Alignment, Repair, Publish Queue) ·
      *Observability* (Prefect, + Feedback and Logs when they exist). Scheduling already moved to
      Automate, so it is not a fourth group.
- [ ] **No logs viewer, and logging is not wired.** Root logger has no handlers and `uvicorn.run()`
      takes no `log_config` (`cli/main.py:327`), so INFO is discarded and WARNING/ERROR arrive bare.
      **Wire logging before building a viewer** or it will show nothing and read as broken.
### Refresh as a survey, not a button

Reframed 2026-08-31: refresh wants to be a **schedulable survey in Automate** that decides whether
a refresh is needed and whether delta or full is cheaper — not a button. Design in
`survey-composition-and-topic-summary-design.md` §2b (planner step).

Already built, and this is mostly assembly:
- Four refresh steps, all `queued` and independently schedulable: `repo_profile_refresh`
  (scouting), `manifest_parse`, `rag_ingestion`, `website_ingestion` (analysis).
- The Automate surface to hang it off — survey list beside Subscriptions and Schedules
  (`fd63eed`, 2026-08-30). This was §4a's blocker; it is gone.
- `POST /api/projects/{slug}/refresh` — delta RAG ingestion + query-cache invalidation. Nothing in
  the UI calls it (the `/refresh` hits in `index.html` are Discovery Sources).

Missing:
- [ ] A **Refresh Survey Definition** bundling the four.
- [ ] The **planner step** at the front of it: last SHA vs live head, which tables are populated,
      how stale each is → decide per-step what runs.
- [ ] A **per-step "still current?" check.** Only `IncrementalIndexer.refresh` SHA-gates today; the
      other three redo their work regardless.

Two traps, both already visible in the code:
- **The gate cannot be survey-wide.** `IncrementalIndexer.refresh`'s no-change path still profiles
  data files if that was never run. Unchanged ≠ complete; a survey-level skip would skip work never
  done.
- **Cheap acquisition ≠ cheap compute.** `SourceCache` is keyed on (repo, SHA), so an ungated step
  costs 1.28s warm rather than 22.6s cold — which *hides* a missing gate instead of replacing it.
  The parse/profile/embed work still repeats in full. (Not clearing `SourceCache` on refresh remains
  correct: a stale hit is impossible.)

### The ~30s stage load — diagnosed, not fixed

`/api/survey-definitions/{type}/{slug}/candidates` measured **24.2s cold, 0.12s warm**, and
`index.html` calls it **twice sequentially** (once for the stage, once for `automate_full`).
The other two stage calls are 0.37s and 0.50s.

- [ ] Fix. The two calls are independent, so concurrency halves it immediately; the real fix is one
      round trip or a warm cache. It is a live Egeria call.
- Caution: an earlier measurement of 14.7s was taken under load 65 caused by two orphaned `gh`
  processes. Re-measure before and after, not against that number.

### Catalog honesty — one instance fixed, the class open

- [ ] **`documentation_coverage` overclaims.** Says it assesses "README completeness… inline comment
      coverage"; actually checks which doc collections got indexed plus a filename hygiene list.
      Same defect as `security_scan`, no mitigating history.
- [ ] **~12 terse descriptions unaudited.** 15 of 29 repo entries are under 200 chars; the
      discursive ones state their limits and are the ones that turned out honest. Length is a
      fingerprint of having been reconciled against the code, not a virtue.
- [ ] **Consider a ratchet** — an allowlist of audited entries that fails when a new one appears,
      in the shape of the orphaned-slug fix. Claim-verb detection is probably too fuzzy.

### From the design note — nothing built

- [ ] Discovery **Security Survey**: `security_scan`, `security_features`, `ci_quality`,
      `license_classification`, `repo_conventions`, `foss_scorecard`, `cii_badge` — all fast/inline.
- [ ] **`Security_Assessment`** survey: the above + `cve_scan` (minutes/queued, excluded from
      Discovery by rule 17) + the GAP steps below.
- [ ] **Reducer steps and a topic-summary annotation.** `foss_scorecard` is already a reducer;
      it needs naming as one. Optional and possibly several per survey.
- [ ] **Four GAP questions with no analysis at all**: secret handling, telemetry/phone-home
      detection, CLA/DCO provenance, SLA/availability content. Secret scanning is what
      "Security Scan" claimed to do all along.
- [ ] **Per-stage summary dashboards** — deferred by decision, 2026-08-31. Stage *filtering* already
      works (`get_dashboard_stages`, membership not equality); summarising across stages does not.
      Open when defining it: derived membership double-counts, since `security_overview` belongs to
      both Discovery and Assessment.
- [ ] **Do findings need a run identifier?** `project_analysis_findings` has no run column. A run is
      identifiable only by a shared `surveyed_at`, by convention, and `query_findings` does not use
      it that way. Blocks "summarise this run" being a real query. See open question 5.

### Carried, not from today
- [ ] `UNVERIFIED` is computed and never persisted, so query time cannot reach it.
- [ ] `test_local_flow_execution_fallback` failed once on 2026-08-31 and did not reproduce — see
      Backlog "Test reliability" for what is ruled out. Do not treat Prefect teardown noise as a
      reproduction signature.


## Done 2026-08-26/27 — do not redo

Three Survey Definition hazards (generator overwrite, reconciler deleting
branches, drift scan conflating recovery with coverage); annotation types
published by name; whole-survey sequencing handed to Prefect; the reader
reading branching definitions; four new analyses (FOSS scorecard extension,
CVE scan, CHAOSS, CII badge); pyegeria 6.1.5 upgrade.
