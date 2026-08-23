# Resource Explorer — Backlog

**Purpose:** A running list of work items that are agreed as worth doing but are not yet scheduled into a phase of an active design document. When an item is picked up for real design/implementation, move its detail into (or link from) the relevant design doc and leave a one-line pointer here.

This is a list, not a design doc — keep entries short. Link to a full design doc/section when one exists.

**Egeria/pyegeria bugs (as opposed to RE's own bugs)** are tracked separately in `docs/egeria-pyegeria-issues.md`, not here — log new ones there as they're found.

**Current-state map (2026-08-19):** `docs/survey-and-analysis-current-state-2026-08-19.md` maps how surveys, analysis and curation work — the axes on which the two survey-launch paths diverge, an inventory of which analyses reach Egeria and which don't, and a suspected bug (filesystem annotations never publish). **It was derived from the pre-migration standalone repo and carries a staleness warning — line numbers need re-checking, and it predates `run_batch` in the executor.** Several items below are corrected there. Related: `docs/architecture-recovery-design.md` (deriving Solution Blueprints from repos).

---

## Open items

### Step outcomes and the Egeria governance model — what landed 2026-08-21, and what was deferred

**Landed:** `resource_explorer/step_outcome.py` — the five-label vocabulary from
`docs/approach-portfolio-model.md` §3 (`recovered` / `partial` / `no_signal` / `unverified` /
`regression`), with §3's rule enforced in the constructor: an approach with no known-positive
check cannot report `no_signal`, only `unverified`. `repo_website_ingestion` is the first
adopter. Recording only — nothing routes on these labels.

**Established while investigating, all verified against the live server rather than read:**

- Guards already round-trip in RE today. `scripts/generate_repo_survey_definition.py` emits
  `### Guard / Any` on every `Link Next Process Step`; Dr.Egeria's command accepts `Guard` and
  `Mandatory Guard`; a live read of Analysis Survey returns `guard: 'Any'`, `mandatoryGuard:
  False` on all 9 links. The reader receives them and discards them.
- `NextGovernanceActionProcessStepProperties` carries exactly `guard: Optional[str]` and
  `mandatory_guard: Optional[bool]`. A flat token, no structured payload — which is *why*
  outcome and cause are separate fields, not a stylistic choice.
- RE consults no Egeria specification at all. `STEP_REGISTRY` is a specification living in
  Python. `SpecificationProperties` is the pyegeria client for the real thing.

**Deferred, with the reason:**

1. **Guard-based branching.** Deferred by decision 2026-08-21 — recorded outcomes are useful
   without routing, and branching is real work in `survey_definition_reader` (a documented v1
   boundary, see `docs/survey-definitions.md`). Authored links stay `guard: Any` until wanted.
2. **Whether a locally-produced guard can be recorded against the process at all**, given RE
   acts as its own engine host. Untested. If it turns out to be engine-action-only, then for
   RE-executed surveys this vocabulary is a *recording* mechanism and only a *routing* one
   under Egeria coordination — a real difference, worth knowing before building on it.
3. **Generating the Egeria specification from the enforced local contract.** Direction agreed
   (master in Egeria, cached locally), and the shape agreed with the arch-recovery session:
   keep `ResourceProvider.provides` / `requires_views` / `validate_resource_views()` as the
   *enforced* contract and generate the published spec from it, so the two cannot drift. One
   property to honour: generation must fail loudly if the enforced contract has no expressible
   form in the spec, rather than emitting a lossy one — otherwise the drift returns through the
   generator.
4. **`Produced Request Parameters` as the carrier if a cause ever needs to reach a *later*
   step** rather than only be recorded. Read in the docs, **not exercised** — do not build on
   it as verified.
5. ~~**Adopting the vocabulary in the other 23 steps.**~~ **PARTLY RESOLVED 2026-08-22 — the
   file-inventory readers are done.** `step_outcome.from_upstream_table()` is the shared
   three-way derivation for a step that reads a table an earlier step was meant to fill:
   empty table → `unverified`, rows present but nothing matched → `no_signal` (**the non-empty
   table is the known-positive**), otherwise `recovered`. It never returns `partial` — whether
   a non-zero result is *complete* is knowledge only the calling step has.

   Adopted in `repo_file_size`, `repo_data_profiling`, `repo_documentation`,
   `repo_sub_resource_survey`, `repo_file_classification`, `repo_file_structure` and
   `repo_security`. Three things fell out of doing it that were not visible beforehand:

   - **`SecurityHygieneSurveyor` was reading the wrong table entirely.** It looked for
     SECURITY.md / CI config / LICENSE in `project_code_symbols`, which by construction holds
     only `.py/.js/.java/.go` files — so the first two checks failed for *every repo, always*,
     and raised RFAs at confidence 90/85 telling people to add files they already had.
     Confirmed against live data before changing (docling: SECURITY.md + 13 workflow files in
     the inventory, zero of either in code symbols). `documentation.py` had already been moved
     to the inventory for this exact reason and left a comment saying why; this step was missed.
     Now reads the inventory, and emits **no** gap RFAs when the inventory is empty.
   - **`DocumentationSurveyor` was issuing a verdict on unread repos.** Half its score comes
     from the inventory, so an empty one produced "Documentation quality: Minimal" — and
     persisted `label="Minimal"` into the trend, which outlives the run. Now `Unverified` in
     both places.
   - **Three `StepInfo` comments named the wrong source table.** `repo_file_structure` and
     `repo_language` do not read the inventory at all (project_stats / project_code_symbols),
     and `repo_security` did not until this change. Corrected — the comments encode ordering
     prerequisites, so a wrong one is a wrong dependency.

   Two contracts were deliberately reversed and their tests rewritten rather than patched:
   `test_no_inventory_persists_nothing` (a run that found nothing now leaves a labelled zero —
   a gap in a trend is unreadable) and `test_no_signals_yields_minimal_quality`. Both carry a
   note saying what changed and why. New coverage: `tests/test_inventory_reader_outcomes.py`.

   **`repo_api_structure` followed on the same day.** It reads `project_code_symbols` rather
   than the inventory, but the shape is identical and the live case was the strongest of the
   set: measured across the registry, **13 of 20 repos had a populated file inventory and zero
   symbols** (docling 1,653 files/0 symbols, trellis 1,078/0). For all thirteen the step
   returned an empty annotation list — the one output indistinguishable from never having run.
   It now emits a labelled annotation and a zero metric, and distinguishes an empty table
   (`unverified`) from a scope that excluded every symbol (`no_signal`, via an unscoped
   `COUNT(*)`). `test_no_symbols_persists_nothing` reversed with a note, same as
   `test_no_inventory_persists_nothing`.

   **Still open:** the remaining ~15 steps.
6. **Converging with arch-recovery's `run_scope`/`partial`.** That session already emits
   `partial` on scoped runs (`ca34edf`) and offered a walkthrough of where `StepInfo` /
   `requires_resources` / `resolve_resources` would need to change. Not started; deliberately
   not touching their plumbing.
7. **pyegeria ISSUE-70** — `ActionAuthor.update_next_action_process_step()` always raises
   `AttributeError` (calls a method that does not exist). Logged in
   `/Users/dwolfson/localGit/egeria-python/PYEGERIA_ISSUES.md`, **not fixed**, per the standing
   rule. Not blocking: guards are authored through Dr.Egeria. It blocks amending a guard in
   place, which would be tidier than re-authoring a document and re-running the reconciler.
8. ~~`repo_arch_detect` / `repo_arch_coupling` are not assigned to a stage`~~ **RESOLVED
   2026-08-22.** Assigned to Discovery — `analysis_catalog.yaml`'s `architecture_recovery`
   entry retagged `intent: discovery`, and a new `RepoArchitectureDiscovery` survey_group
   (`docs/dr-egeria/repo_survey_types.csv`, `repo-survey-definition-architecture-discovery.md`)
   authored live in Egeria and reconciled. `tests/test_reachability_audit.py`'s
   `STEPS_NOT_IN_A_STAGE_SURVEY` exemption for both steps is removed;
   `test_analysis_catalog_reader.py::test_discovery_is_the_zero_fetch_derivation_tier` now
   carries a named, single exception (`DISCOVERY_FETCHES_ANYWAY = {"architecture_recovery"}`)
   since — unlike every other Discovery-tier analysis — both steps DO fetch (zipball, and a git
   clone for co-change), a real tension with CLAUDE.md rule 17 recorded rather than papered
   over. Egeria's RepoFullSurvey now holds all 24 of `STEP_REGISTRY`'s steps reachable from a
   stage-specific survey.


### Testing strategy — four silent-failure classes, one built, three open

Eight faults found on 2026-08-20 shared one shape: **the code ran, reported success, and did
nothing.** None threw. Each was found by hand, late, after the capability had been "done" for
a while, and every one of them passed its own module's tests. What they had in common was a
gap *between* two components, invisible from inside either.

**BUILT — `tests/test_reachability_audit.py`.** Structural comparison of every registry
against the surface meant to expose it: steps vs. survey types, analysis kinds vs. catalog
entries vs. dispatch, generated documents vs. the batch manifest, intents vs. rule 17's
canonical eight. Verified against the real historical faults rather than assumed — replaying
`repo_website_ingestion`'s orphan state, the 4-of-7 batch manifest, and a typo'd intent each
fails it. Deliberately asserts only that things are wired together, never that they work;
behaviour is each capability's own job, and these bugs all passed those tests.

Note it excludes the `*` (Full Survey) sentinel on purpose. That bundle is generated *from*
STEP_REGISTRY, so it can never be missing anything, and counting it would have declared
`repo_website_ingestion` reachable on the day it was reachable from nothing.

### BUILT 2026-08-20 — a "no silent success" ratchet (`tests/test_no_silent_success.py`)

`resource_explorer` has 197 broad `except` handlers whose body only logs. Most are legitimate
best-effort writes; the problem is that nothing distinguishes those from the ones that hide a
defect. Two did exactly that this session: `EgeriaDatabaseSurveyor.catalog_and_survey`
returned success while swallowing a stale-GUID 404, and `run_prefect_step` reported "API
dispatch failed" for an `UnboundLocalError` that made the whole Prefect API path unreachable.

**Built as a ratchet, not a sweep.** 112 existing sites (the earlier figure of 115 double-counted
handlers in nested functions) are recorded in `tests/no_silent_success_baseline.json` keyed by
`path::function` with a count — not line numbers, which churn on unrelated edits. A new site
fails the test; a baseline entry that no longer exists also fails, so the number can go down
but never up and the baseline cannot rot. Verified in both directions, and the detector is
proven against the two real bug shapes plus four near-miss controls (narrow except, re-raise,
handler that returns, log-only handler in a void function).

Still open, deliberately: fixing the 112. The rule is that a handler that swallows *and whose
function still reports success* must record something observable — a metric, an error field, a divergence row. That
is precisely the fix applied to both sites above. Invasive across 197 call sites, so it wants
a design pass and probably a staged rollout (new code first, then per-module), rather than a
sweep.

### BUILT 2026-08-20 — live smoke tier (`tests/test_egeria_live_smoke.py`) + pinned error payloads

Several of these were findable *only* against live Egeria: which paths actually consume a
cached GUID, a divergence swallowed by a non-fatal handler, and the real error codes. The
live probe corrected two things this backlog had recorded from the original report — the
outer code is `OMAG-REPOSITORY-HANDLER-404-007`, not `OMRS-REPOSITORY-404-007`, and the
response self-labels `CLIENT_ERROR_400` while `relatedHTTPCode` is 404.

Two pieces: capture real error payloads verbatim as fixtures (started —
`tests/test_egeria_linkage_divergence.py`'s `LIVE_ERROR`) rather than paraphrasing them; and
add a marked live smoke tier that skips when Egeria is unreachable, in the shape of the
existing `requires_pgvector` tier. No mock would have found the three faults above, so this
is not a substitute for unit tests but the only cover for that class.

### Open — grow the repo corpus substantially, as a bug-finding strategy

37 repos registered, 9 with a derived homepage, 5 groups. That small corpus has already been
the single most productive source of real defects: of the handful of repos with homepages,
three exhibited distinct, unanticipated shapes — `sqlglot.com` is a 138-byte pdoc
meta-refresh stub (ingest reported success having embedded nothing), `kedro_plugins` declares
its own GitHub URL as its homepage (would have ingested forge chrome as documentation), and
`docs.unitycatalog.com` no longer resolves. Versioned-vs-unversioned sitemaps and
site-built-from-an-ingested-repo came from the same handful.

That is a very high defect rate per repo, and it argues the corpus is the limiting factor on
finding the next class of bug rather than the test suite is. RE already has the machinery to
act on this — org import and the Discovery search/list sources — so this is a matter of
deliberately importing breadth (several foundations, several languages, monorepos, archived
and fork-heavy orgs, repos with no docs at all) and then running the full survey set across
it looking for steps that report success having done nothing. Worth planning as its own
exercise, including what "success having done nothing" looks like per step, since that is the
shape none of these tests catch on their own.


### Architecture recovery — the PORTED implementation has never been scored

Phase 1's declared numbers (13 of 13 components, 97% coverage, ARI 0.969 —
`docs/architecture-recovery-phase1-findings.md`) were measured on the **throwaway spike** in
`scripts/arch-spike/`. What shipped into `resource_explorer/surveyors/arch_recovery/` is a *port*,
and it has at least one known behavioural difference: the spike merged agreeing proposals at IR
level and boosted confidence on agreement, while the port discovers agreement at read time by
grouping on `scope_locator` and does not boost. There may be others; nobody has checked.

**Do not assume the port reproduces the spike's numbers.** Run `score.py` against the ported
pipeline's output and the pre-registered fixtures, and record the result. If it differs, that is a
finding either way — the port is wrong, or the merge mattered less than assumed.

This is the same class of error the spike hit three times (README findings 15, 30, 37): assuming a
property of the code when it was actually a property of how the code was being measured. A port
that passes its unit tests can still partition differently.

Cheap: `score.py` and the fixtures already exist; only the plumbing from the ported pipeline's
output to the scorer is new.

### Architecture recovery — re-check the Phase 1 measurements once there are more samples

**Not a doubt about the current numbers; a limit on what two repos can establish.** Phase 1's
measurement goals were declared met on 2026-08-20 (`docs/architecture-recovery-phase1-findings.md`)
— 13 of 13 components, 97% file coverage, ARI 0.969 on trellis, T1 recall held at 18/27, 5.3s per
repo. Every criterion in the plan's §5 was cleared, several by a wide margin.

Re-run the whole evaluation, and expect to revise, when there is materially more experience:
**roughly 8–10 surveyed repos of varied shape**, or the first time a real user disagrees with a
partition RE published.

What only more samples can settle:

- **n=2, and they are not independent.** trellis is a well-factored Python monorepo — close to the
  best case for import cohesion — and `egeria-workspaces` is a flat app. Both are ours, both are
  Python, both were partly written by the people writing the detectors.
- **`COHESIVE_BAR` and `DISPERSION_BAR` are unvalidated.** They were set by inspection on one
  repo. The Phase 1 plan's own preferred answer (Newman modularity as a null-model threshold) was
  tried and failed — `Q > 0` admitted 15 of 16 candidates (README finding 33) — so the current
  bars are a placeholder, not a result.
- **The residue rule is a known trade, not a solution.** Adopting unproposed subtrees took
  `Utility scripts` to exact and `Core` from exact to 0.51, because the two ground-truth entries
  disagree about residue ownership *deliberately* (finding 44). More repos will show which reading
  is the common one — or that it is genuinely per-repo and belongs to a human.
- **T2's ground truth is not a clean pre-registration.** The trellis component count was reported
  to the maintainer before the fixture was written. Contamination runs the safe way — the fixture
  contradicts the detector rather than echoing it — but it is a caveat on T2's numbers that a
  fresh repo would not carry.
- **T1 precision is 0.31 and is not really understood.** It is dominated by add-on granularity
  (finding 12), where the maintainer names a 9-container bundle as one component. Whether that is
  a fixture inconsistency or the normal way people think about add-ons needs more than one
  example.
- **Python only.** `imports.py` extracts Python; `egeria` has zero tracked `.py` files, so the
  obvious adversarial target cannot be scored at all and "does this generalise beyond Python?"
  is currently unanswerable.

**Cheap to redo, which is the point.** `score.py`, `coupling.py` and the pre-registered fixtures
already exist, so re-running is hours, not a phase — provided new targets get **pre-registered
ground truth written before the detectors run on them** (`tests/fixtures/architecture-ground-truth/README.md`).
Writing that fixture is the actual cost, and it is what makes the re-check meaningful rather than
a re-confirmation.

Related: `docs/approach-portfolio-model.md` §4 proposes recording approach outcomes against repo
characteristics — if that is built, this re-check becomes a query rather than an exercise.


### ~~HIGH — Suspected bug: filesystem annotations never reach Egeria~~ — FIXED 2026-08-20

Confirmed real and fixed. `egeria_filesystem_surveyor.py` read `ann.egeria_type_name`,
which exists on no class in `survey_report.py`, so `_build_annotation_props` raised
`AttributeError` on every call — swallowed by the broad `except` in `catalog_and_survey`
(empty SurveyReport, no error surfaced) and fatal in `publish_step_annotations`.

Fixed by consolidating rather than by a one-line attribute rename, because the item
itself flagged that the real defect was three near-duplicate `_build_annotation_props`
implementations that had drifted apart (`valueProperties` vs `resourceProperties`,
`confidenceLevel` vs `confidence`, four missing annotation-type branches, RELATIONSHIP
absent from `_class_map`). A rename would have left the drift standing and the next
divergence free to happen. `surveyors/annotation_props.py` is now the single
implementation; all three surveyors delegate to it, keeping their method names since
tests and call sites reach for them by name.

**Verified:** all seven annotation classes in `survey_report.py` pass through all three
publishers without raising. **Not verified:** an end-to-end filesystem publish against a
live Egeria — no filesystem entity is registered in this deployment, so there was
nothing to survey. Worth re-running once one exists, since the original failure was
invisible precisely because it was swallowed.

### Egeria ↔ RE sync/divergence reconciliation — DETECTION BUILT 2026-08-20, resolution partly open

**Built:** `resource_explorer/egeria_linkage.py` detects "that GUID does not exist here"
at the point of use and, instead of the opaque `SERVER_ERROR_500` that reached the UI
verbatim, records the divergence in the new `egeria_linkage_status` table, raises an RFA,
and throws a named error that says what happened and what the three choices are.

**Corrected 2026-08-20 by testing against live Egeria with a deliberately bad GUID** — the
first version guarded five paths on the assumption all five consume a cached GUID. Only
three do:

| path | cached GUID | by-name fallback | guarded |
|---|---|---|---|
| repo publish | yes | **none** — a stale GUID is fatal | yes |
| filesystem `publish_step_annotations` | yes (`guid or _find_element_guid(...)`) | yes | yes |
| database `catalog_and_survey` | yes (as the *server* element) | yes | yes |
| filesystem `catalog_and_survey` | no | yes | no |
| database `publish_step_annotations` | no | yes | no |

The two unguarded ones resolve their element by name every time, so a stale cached GUID
cannot break them — and a guard there could only misattribute an unrelated lookup failure
to a GUID that was never used. Tests assert the placement in *both* directions, plus that
the classification still matches what the code does, so the table above cannot quietly rot.

**The real defect that live testing exposed:** in database `catalog_and_survey`, the stale
GUID does produce exactly the error the detector recognises — at
`_initiate_survey("PostgreSQL Server", server_guid)` — but the surrounding
`except Exception: log.warning(...non-fatal...)` swallowed it, and the method returned
success with `server_survey_guid=''`. The wrapping guard never saw it because the exception
never escaped. Since the cataloging work genuinely does succeed there, this stays non-fatal,
but it now records the divergence and raises the RFA: "non-fatal" must not mean "invisible",
or every later run skips the server survey the same silent way.

The detector was validated against this deployment's live Egeria rather than against a
paraphrase — asking for a GUID that cannot exist returns `OMAG-REPOSITORY-HANDLER-404-007`
wrapping `OMRS-REPOSITORY-404-002`, and that verbatim message is now a test fixture. Two
things that probe corrected: the outer code is `OMAG-REPOSITORY-HANDLER-404-007`, not the
`OMRS-REPOSITORY-404-007` recorded here from the original report; and the response labels
itself `CLIENT_ERROR_400` while `relatedHTTPCode` is 404, which is why detection keys on
Egeria's message codes and not on HTTP status.

**Held to "detect, don't auto-resolve" as decided:** the cached GUID is deliberately *not*
cleared on detection. It is kept so a human can see what RE had and so republish can report
what it is replacing.

`GET /api/egeria/linkage/stale` lists divergences; `POST /api/egeria/linkage/{type}/{slug}/resolve`
takes `republish` | `resurvey` | `discard`. All three clear the unusable GUID and the
divergence record — that is what unblocks the resource, and is common to every choice.

**Still open:**
- **republish/resurvey run the follow-up work for repos only.** For databases and
  filesystems the link is cleared and the caller is told which existing action to run.
  Re-publishing those from cached local data needs per-type orchestration — a database
  publish reconstructs `schema_info` and fires Egeria's native survey — which is the real
  reason it is not built here.

  **Correction (2026-08-20):** the commit that added this said there was "no registered
  database or filesystem in this deployment". That was wrong and was never checked — only
  filesystems were. There are two registered databases, `localhost_docker_coco_ods` and
  `localhost_docker_coco_pharma`; filesystems are genuinely zero. Neither database carries
  an `egeria_asset_guid`, so neither can exhibit this divergence today — a stale link needs
  a cached GUID first. So the path is testable in principle, but only after cataloging one
  of them in Egeria, which is a real write to the live catalog and a deliberate choice
  rather than a side effect of verification.
- **`discard` clears the Egeria linkage; it does not purge RE's local survey data**, which
  is the stronger reading in the original note above. Deleting a user's survey history is
  hard to reverse and should not happen behind a single API call — it needs its own
  confirmation path before being built.
- **Detection is reactive only** (open question 1). A proactive GUID-existence sweep would
  have to decide how often to re-check every cataloged entity; the failure is rare and now
  loud, so this was not worth paying for yet.
- **Open question 3, partly answered 2026-08-20.** The by-name fallback works: with
  `coco_ods` cataloged, `_find_element_guid("coco_ods")` returns the same GUID as the cache
  (`c2e8bb6c-…`), so a registry that has lost its GUID can recover it. Two of the five paths
  above rely on that route exclusively and are therefore immune to the forward case. Still
  unverified end to end against a genuinely reset RE database.
- ~~**No UI for resolve.**~~ **BUILT 2026-08-20.** Admin ▸ 🔗 Egeria Links lists every
  divergence with Republish / Re-survey / Discard, and an affected repo shows the same three
  actions as a banner on its Scouting card — placed directly above the "☁ Published to
  Egeria" badge, which is actively misleading while the link is broken since it reports a
  catalog entry RE can no longer reach. Both call one shared button-builder so the wording of
  a destructive-sounding choice cannot differ between them.

  Found while verifying: `discard` reported "RE's local survey results are untouched" while
  also deleting `project_egeria_surveys` — the record of past publishes. Those GUIDs point
  into the repository that no longer has the asset, and the publish history itself remains in
  the activity log, so nothing of value was preserved by keeping them; but the sentence was
  not true, and the one action a user might fear is the wrong place to be imprecise. It now
  names the count it removes and what survives.

### Automate: had never notified anyone — two independent faults, both fixed 2026-08-20

Its whole value is the notification, and nothing errored while it delivered none.

1. **Delivery** — every RFA it wrote was invisible in the RFA drawer (see the item below).
2. **Prerequisite** — detection only runs off a *scheduled* completion, so a subscription
   with no recurring schedule for the same analysis can never fire. The live state was
   exactly that: an active `maturity` subscription on `sqlglot`, `last_checked_at` empty,
   and the only schedule in the deployment belonging to a different entity *and* a
   different analysis. The warning existed only as a toast at create time and a tooltip on
   the Notify button — nothing on the subscription row, so one made weeks earlier sat there
   looking healthy and inert.

`SubscriptionData` now carries `has_schedule`, computed against enabled, non-`manual`
schedules for the same (entity_type, entity_slug, analysis_id), and the row renders
"active — but never fires (no schedule)" with a pointer to where to set one. A `manual`
cadence deliberately does not count: it never recurs, so nothing ever completes for
detection to compare against.

`tests/test_automate_end_to_end.py` follows the whole chain — scheduled run → detection →
RFA a human can see — rather than a unit of it, because the two failure modes are
indistinguishable from outside: a subscription that never fires and one with nothing to
report both show "never notified".

**Not a fault, found alongside:** the one schedule in this deployment
(`localhost_docker_coco_ods` / `index_health`) errors on every run with "No Survey
Definition found matching 'index_health'". `index_health` is not in the database analysis
catalog (`schema_inventory`, `row_count_snapshot`, `privilege_audit`, `egeria_db_survey`) —
a stale schedule pointing at an analysis that no longer exists. The scheduler is behaving
as designed here (D5: report a stale schedule, never silently fall back), and the Schedules
tab shows the error. It just needs deleting.

### ~~RFAs written by `log_rfa()` never reached the RFA drawer~~ — FIXED 2026-08-20

`GET /api/activity/rfas`, the feed behind the drawer, keeps only *annotations* whose
`annotation_type` contains "RequestForAction" — it never looks at `operation="rfa"`.
`log_rfa()` wrote its entry with an empty annotations list, so every RFA it produced was
invisible there: the entry existed in the activity log, and the one surface built to act on
it showed nothing.

All three producers were affected — Automate's change notifications (`scheduler.py`),
Enrichment's context requests (`web/routes/context.py`), and Egeria linkage divergences.
Each is by definition a request for a human action, and no human was shown one. **Automate
is the one that mattered most**: its entire delivery mechanism is "notify via RFA", so
subscriptions could fire correctly and still appear to do nothing.

Nothing failed, which is why it lasted: the writes succeeded, the entries were real, and
only a reader looking for a different shape came up empty. Found while checking whether the
divergence RFA above actually reached a user. `tests/test_rfa_visibility.py` asserts each
producer reaches the drawer feed, at its own call site rather than through a mock of
`log_rfa` — a stubbed test would pass even with the fix reverted.

### Advanced SQLGlot view analytics
We can extend our SQL View static analyzer (`sql_analyzer.py`) with further advanced metadata analytics:
1. **Dialect Compatibility Matrix**: Check query compatibility across target warehouses (e.g. Snowflake, BigQuery, Athena, Redshift) by transpiling view SQL and report compatibility scores.
2. **Nesting Depth & Cycles**: Warn stewards about excessively nested views (e.g. view on top of view, on top of view) that degrade database query performance, and detect circular dependency loops.
3. **Query Optimization Advice**: Use `sqlglot.optimizer` to analyze query syntax in views and suggest simplified rewrites (e.g. redundant joins, dead subqueries, qualifying column expressions).
4. **Access & Join Heatmaps**: Parse views and query logs to discover which tables/columns are most frequently joined or filtered, recommending candidates for indexing or physical layout updates.

---

### Distributed survey orchestration via a flow tool (Prefect) — early prototype, not yet integrated

RE's only execution model today is either synchronous in-process (`SurveyOrchestrator`) or the `scheduler.py` daemon-thread poller (see the "Periodic / triggered survey scheduling" item below). Neither can run survey work *near* a protected asset (a database inside a VPC, a filesystem edge agent) without deploying RE itself there, and neither gives retries/backoff/task-level telemetry for free.

**Design notes (2026-07-14):** `docs/distributed-survey-orchestration.md` proposes Prefect (over Dagster/Airflow — see its §3 comparison table) as a task runner slotted in via the existing `executes_at` routing convention already used by Survey Definitions (`executes_at: prefect`, alongside today's `egeria`/`resource-explorer`), so this is additive to the local-executor work above, not a replacement. `docs/distributed-survey-best-practices.md` grounds this against how DataHub/OpenMetadata handle distributed estate-wide ingestion, and proposes a broader progressive intake funnel (Scouting → Staging Registry → Enrichment Gate/ToDo → Deep Assessment → Egeria Certified Catalog) that reframes "coherent selective-cataloging model" (item below) in terms of Prefect-driven phases.

**Shipped so far (uncommitted, prototype-stage):** `resource_explorer/prefect/flows.py` (`@flow`/`@task` wrappers) and `resource_explorer/surveyors/prefect_adapter.py` (dispatches a step to the Prefect REST API or runs it locally via `nest_asyncio`), plus `tests/test_prefect_integration.py`. `prefect` added to `pyproject.toml` dependencies. **CRITICAL FINDING 2026-08-20 — the Prefect API path had never executed.**
`run_prefect_step` opened with `asyncio.get_running_loop()`, while a redundant
`import asyncio` further down the same function made `asyncio` a closure cell (the lambda
captures it). That first line therefore did a LOAD_DEREF on a cell nothing had stored and
raised `UnboundLocalError`; the broad `except` read it as "API unreachable", logged
"Prefect API dispatch failed", and ran the flow in-process. So every Prefect step has always
run locally, `_run_prefect_step_api` was dead code, and the log line was indistinguishable
from a genuinely unreachable server. Fixed (inner import removed), and the fallback now logs
the exception type and traceback so a bug here can no longer masquerade as a connection
problem. **This matters for the design decision below: whatever the flow-engine dependency
has been bought so far, distributed execution is not it — nothing has ever been dispatched.**

**Routing fixed at the same time.** `prefect.enabled` re-routed every step declaring
`executes_at: resource-explorer`, overriding what a definition explicitly asked for —
`executes_at` is documented as naming the execution engine and as open-ended precisely so
engines can be chosen per step, so a global override removed the only way to say "run this
one here" and made `executes_at: prefect` redundant. Now gated on a separate, off-by-default
`PREFECT_ROUTE_LOCAL_STEPS`: routing RE's own steps through Prefect for retries/telemetry is
a legitimate deployment choice, it just has to be asked for by name.

**Not yet done:** ~~`executes_at: prefect` is not wired into `survey_definition_executor.py`'s dispatch loop~~ **(CORRECTED 2026-08-19, verified against this tree: it IS wired — `_use_prefect` at `survey_definition_executor.py:162-167`. Note `:167` — when `config.prefect.enabled` is true, *every* step marked `executes_at: resource-explorer` is rerouted to Prefect, so a global flag overrides what a definition explicitly asked for. Open question whether that is intended.)**; no staged-candidate registry states in `registry.py`; no deployment/worker actually configured or run against. This needs review as a real design decision (own dependency on a flow engine is a significant infra commitment) before the prototype code is treated as a real feature — not yet reflected as its own line item, currently living only in these two design docs.

Related/overlapping: "Periodic / triggered survey scheduling" below (this may be the eventual replacement for the daemon thread it says is only a short-term fix), "Coherent selective-cataloging model" below (the staging-registry funnel is a concrete proposal for it), and "Unify survey launching" above once a launcher needs to route to a third execution engine, not just two.

---

### RFAs should become real Egeria actions, not just descriptive annotations — needs a deeper dive

Every `RequestForActionAnnotation` RE produces today (repo security/doc gaps, the new filesystem inaccessible/unclassified/profiling-failure RFAs added 2026-07-13 — see the filesystem analytics item below) is purely descriptive: it's an `Annotation` attached to a `SurveyReport`, published via `EgeriaPublisher`'s `RequestForActionProperties` mapping (`egeria_publisher.py`). Nobody is notified, nothing is assigned, there's no due date or lifecycle status. A human has to know to go look at the survey report to ever see it.

**Confirmed so far (2026-07-13, quick pass through pyegeria, not yet a full design):** Egeria has a separate, genuinely actionable mechanism — a `ToDo`/"person action" element, distinct from a survey Annotation. `pyegeria/omvs/my_profile.py::create_my_todo`/`_async_create_my_todo`, backed by the general-purpose `pyegeria/omvs/asset_maker.py::_async_create_action` (`ActionRequestBody`), supports: `assignToActorGUID` (assign to any actor, not just the calling user — the `my_profile.py` wrapper is just a "my" convenience, the underlying call is not actor-scoped), `actionSponsorGUID`, `originatorGUID`, `newActionTargets` (linking the action to specific elements — e.g. the actual offending file/table, not just prose), and a full lifecycle (`activityStatus`: REQUESTED/APPROVED/WAITING/IN_PROGRESS/COMPLETED/FAILED/CANCELLED/etc. — see `pyegeria/core/_globals.py::ACTIVITY_STATUS`, `dueTime`, `priority`, `lastReviewTime`). The docstring itself notes a `ToDo` is one of several "person action" kinds — "Meeting, ToDo, Notification, Review" — so there's a whole small taxonomy here, not just one element type.

Also spotted, not yet chased down: a distinct `steward`/`stewardTypeName`/`stewardPropertyName` property pattern that shows up on collection-membership and classification relationships (`pyegeria/omvs/collection_manager.py`, `classification_explorer.py`) — "who validated this" rather than "who needs to act on this." These look related but are probably not the same concept as ToDo assignment, and it's not yet clear how (or whether) they're meant to compose — e.g. does a steward get auto-assigned the ToDo for things in their stewardship scope?

**Deliberately not designed yet — this needs its own research pass, not a bolt-on:** two unexplored pyegeria OMVS modules that are very likely load-bearing for this — `actor_manager.py` (actor/role model — who can be assigned, how roles relate to stewardship) and `community_matters_omvs.py` (ties into the existing, also-unresolved "journaling discoveries as blog-style entries visible to particular communities" open question in the A2A item below — notification/audience may be a community concept, not just a 1:1 assignment). Also needs: which RFAs should actually become assignable `ToDo`s vs. staying descriptive-only (probably not every annotation warrants interrupting a human), who the default assignee/sponsor is when RE has no obvious human to name (survey run by an unattended schedule vs. a logged-in user), and whether this should be built as a generic `EgeriaPublisher`/executor-level capability (any `RequestForActionAnnotation` optionally promotable to a `ToDo`) rather than something each resource type's publish path reimplements.

Related/overlapping open items: the A2A item's "Rendezvous for results" open point (notification mechanism, journaling, comments as candidates alongside the activity log) and the "unify survey launching" item's unified-dashboard goal — a real ToDo/action queue could end up being part of that unified view rather than a separate concept.

---

### MEDIUM (was HIGH) — Filesystem local survey: silent-failure causes fixed, true "hang" UX still open

Originally: filling out the local filesystem survey pop-up and clicking Run appeared to hang — no progress, no response to further clicks — while the server was actually alive and grinding through a very long synchronous scan, dumping a wall of `Could not profile schema for ...` warnings and pandas/openpyxl noise to the server console that the user never saw (2026-07-13 report, full console dump captured in chat).

**Implemented (2026-07-13), per `docs/filesystem-survey-analytics-plan.md`:**
- `IGNORE_DIRS` now skips bare `venv` as well as `.venv` — this was the concrete cause of the multi-minute scan across dozens of stray venvs (`tzdata`/`pytz` zoneinfo files) in the original report.
- `LocalFileSystemSurveyor` (`resource_explorer/surveyors/filesystem/local_filesystem_surveyor.py`) is now split internally into a metadata-only structure pass and a separate profiling pass. Per-file profiling failures and inaccessible files/directories are collected into `survey_data["profiling_errors"]`/`["inaccessible_files"]` instead of only `log.warning`, and — for the Survey Definitions run path — surfaced as real `RequestForActionAnnotation`s (`egeria_filesystem_surveyor.py::publish_step_annotations`) so a run that hits malformed CSVs/legacy `.xls` files reads as "completed with warnings," not silence. Verified against reproductions of the exact original error strings; covered by `tests/test_filesystem_survey_definition_adapter.py`.
- Kept as **one** Survey Definition step rather than two, per follow-up direction (if you're already asking the OS for one file's `stat()`, there's no benefit to walking the tree twice for the rest of it) — also matches Egeria's own native survey, which turns out to be a single un-decomposed step itself.

**Still open — this is why the item isn't fully closed:** the pre-existing `/api/filesystems/{slug}/survey` route (`web/routes/filesystems.py::survey_filesystem`, the original "📊 Run Survey" button in the Filesystem tab, distinct from the newer Survey Definitions tab — see the "unify survey launching" item below) still calls `LocalFileSystemSurveyor.run()` synchronously with no progress reporting, streaming, timeout, or cancellation. It benefits from the `IGNORE_DIRS` fix and no longer silently drops errors internally, but the browser's `fetch()` still just waits on the full run with nothing to show in the meantime on a large/broad root — the "feels like a hang" UX itself is unfixed there. No file-count/size cap or confirmation step before scanning a large/broad root path either. Likely resolves naturally once "unify survey launching" retires this route in favor of the Survey Definitions path, rather than needing its own fix.

---

### HIGH — Unify survey launching (retire old Re-survey buttons, no unified dashboard yet)

Two uncoordinated ways to start a survey on the same resource exist side by side today:
1. The new Survey Definitions panel (`docs/Backlog.md`'s "RE locally executing Survey Definitions" item below) — Egeria-authored, browses real candidates with step detail.
2. Old per-resource-type buttons still in `resource_explorer/web/static/index.html` (e.g. the database detail panel's "📊 Re-survey" → `showSurveyDbModal()` and "☁ Re-survey in Egeria" → `showPublishDbModal()`, ~~around index.html:3641-3675~~ **now `index.html:7351` / `:7377` / `:7389`, verified against this tree**) that predate the Survey Definitions work and don't go through it at all.

**CORRECTED 2026-08-19 — this is not just a UI unification.** The two paths diverge on five axes: step selection (editing a Survey Definition in Egeria has *zero* effect on the legacy path), Egeria target (the legacy modals collect per-call URL/server/user overrides, so the two paths can write to *different Egeria servers in one session*), publish shape (narrow `publish_step_annotations` vs. full `EgeriaPublisher.publish` with cataloging side effects), result storage (only the legacy path writes history rows and drives the charts), and scheduling (`scheduler.py` calls the orchestrators directly — Survey Definitions are unreachable from a schedule). Retiring the legacy path means porting history storage and scheduling first. Detail, and a third option (legacy becomes a thin caller of the new path), in `docs/survey-and-analysis-current-state-2026-08-19.md` §1.2 and §5.1 — **but re-verify the specifics against this tree; `run_batch` postdates that analysis and likely bears on it.**

Neither the old buttons nor the Survey Definitions panel is quite right as the long-term answer — Survey Definitions is Egeria-authored/candidate-driven, which is correct for "what can run here," but launching a survey is a cross-cutting action needed from multiple places (resource detail panel, discovery results, scheduled/recurring runs), not just one tab. Likely direction: a generic survey-launcher component/modal that any view can invoke (given entity_type + slug), backed by the Survey Definitions candidates API, replacing the old per-type modals rather than living alongside them.

Related, not yet built: polling Egeria for survey results so completed native (`executes_at: egeria`) runs surface somewhere unified instead of only showing an engine-action GUID with "check Egeria's Asset Catalog" (see `resource_explorer/web/routes/survey_definitions.py` run endpoint and its frontend handling in index.html around line 2881). Today there is no unified "survey results dashboard" — results are scattered across the Survey Definitions run modal, the database/filesystem detail panels' own survey history, and Egeria's own catalog for anything async. A poller (or the A2A rendezvous from the item below) is the likely fix, feeding one dashboard view regardless of which launcher/engine started the run.

Full context for the Survey Definitions side: `docs/egeria-collaboration-and-survey-model.md` section 6; the A2A item below covers the async-notification half of "unified dashboard."

---

### RE locally executing Survey Definitions — IMPLEMENTED (2026-07-07)

Was flagged as the single biggest open design/implementation item, ahead of the A2A work below — now built. RE does not wait for Egeria→RE A2A dispatch to execute a Survey Definition's own `executes_at: resource-explorer` steps; it reads the definition and runs its own steps entirely on its own initiative. A2A remains needed only for the opposite case: Egeria's own automation deciding, unprompted, to trigger an RE step.

**Usage:** `docs/survey-definitions.md`. **Shipped shape:** generic across all three resource types (database, repo, filesystem), not just PostgreSQL as originally scoped — `survey_definition_reader.py` (generic GAP graph fetch/parse) + `survey_definition_executor.py` (generic dispatch loop + `ResourceTypeAdapter` plugin interface) + one adapter per resource type. Publishing uses a new narrow `publish_step_annotations` method for database/filesystem (their existing publish paths had unwanted auto-cataloging/native-survey side effects) and the existing `EgeriaPublisher.publish` unmodified for repos. Three new CLI commands (`survey-definition`, `database survey-definition`, `filesystem survey-definition`). Unit-tested (`tests/test_survey_definition_reader.py`, `tests/test_survey_definition_executor.py`, 219 total tests passing).

**Scope actually shipped, still restricted as planned**: linear step sequences only (branching raises `UnsupportedSurveyDefinitionError`), a small hardcoded `re_analysis_step` → surveyor mapping per resource type (depends on the analysis-step inventory/registration item below for anything beyond the fixed list already wired up).

**Validated live (2026-07-07/08)** for both single-step and two-step chained PostgreSQL Survey Definitions — `PostgreSQL Database` discovery, graph fetch/parse/execute/publish, and correctly skipping an `executes_at: egeria` step, all confirmed end-to-end. The graph-parsing code needed two real fixes once tested against actual data: (1) the response shape is `governanceActionProcess`/`firstProcessStep` top-level keys with step properties under `processStepProperties`, not the originally-guessed `relationshipHeader`-wrapped shape; (2) chaining is a genuine node+edge graph (`nextProcessSteps` flat node list + a separate `processStepLinks` edge list keyed by GUID), not a nested per-step structure — the reader now builds a node/edge index and walks it, rejecting >1 outgoing edge as unsupported branching. **Still outstanding:** `Git Repository` Technology Type string (repo, unconfirmed). **Filesystem confirmed wrong (2026-07-13):** `filesystem/survey_definition_adapter.py` currently guesses `"File Folder"` — the real Egeria Technology Type, confirmed live via `EgeriaTechTypeCatalog`, is `"File System Directory"` (`FileFolder` is the underlying open-metadata type name, not the Technology Type display name). This is likely why no Survey Definition candidates were showing up for filesystems. Fix tracked in `docs/filesystem-survey-analytics-plan.md` §4. Also still outstanding: branching (guard-based) Survey Definitions — the rejection path is unit-tested but not yet exercised against a real branching definition.

Full context: `docs/egeria-collaboration-and-survey-model.md`, section 6.6 and open question A8.

---

### Analysis-step inventory and registration

Authoring a Survey Definition (item above, and the Dr.Egeria item below) requires knowing which analysis steps already exist to compose from — a real, unsolved gap with two halves: (1) finding Egeria's existing analysis steps (discoverable via the same technology-type/governance-definition search referenced in `docs/survey-activity-design.md` D4/D6, not yet exercised for this purpose), and (2) publishing RE's own sub-surveyors as catalogable `GovernanceActionType` elements — nothing does this today, so an author can't reference `re_analysis_step: schema_inventory` until something has created that catalogable element in the first place. Likely shape: a one-time/per-addition publish step (an extension of `EgeriaPublisher`, or its own Dr.Egeria plan) plus a local inventory RE itself can consult.

The local-executor item above is now implemented and gives this a concrete, real dispatch point to extend or replace: each resource type's adapter module (`*/survey_definition_adapter.py`) has a `re_analysis_steps` dict — today a small hardcoded Python mapping, not yet a catalogable/extensible registry. This item is about making that mapping itself discoverable/extensible in Egeria terms, rather than requiring a code change to add a recognized step.

Full context: `docs/egeria-collaboration-and-survey-model.md`, section 6.1 and open question A12.

---

### Egeria ↔ Resource Explorer A2A collaboration (bidirectional)

RE currently only calls *into* Egeria (triggering native surveys via `AutomatedCuration`/`initiate_postgres_*_survey`, publishing annotations via `EgeriaPublisher`). There is no path for Egeria's own automation (governance action processes, engine actions) to call *into* RE — e.g. to dispatch one of RE's Python surveyors as part of an Egeria-orchestrated workflow.

Direction agreed: RE should expose itself as an **A2A-callable surface** (extending the existing `agentstack_server.py` per-agent pattern) that Egeria can invoke as if it were any other governance/survey action service. Two reasons A2A over a bespoke REST contract: (1) A2A's task-state model (`input_required`, streaming, polling) already matches the async-survey-result problem RE works around manually today in `HybridDatabaseSurveyor`; (2) it's protocol RE already speaks, so other orchestrators (not just Egeria) get the same capability for free.

**Deferred pending:** input from Mandy (owner of Egeria's core Java / connector frameworks) on what the Egeria-side connector shape should be — likely does not require a new OCF connector *type*, but the specifics should follow her judgment on precedent in the existing wide range of Egeria connectors.

**Known open design points once picked up:**
- New per-capability A2A agent (own port, per the one-agent-per-`Server` rule) using structured `DataPart` payloads (asset GUID, resource type, surveyor/analysis name, options) rather than the natural-language `TextPart` pattern the existing chat agents use.
- Auth: `agentstack_server.py` currently has no caller authentication — fine for an internal chat agent, not sufficient for a surface Egeria automation is meant to trust. **Resolved:** use Egeria's existing bearer-token approach and security services directly; no separate RE auth namespace/scheme needed.
- Rendezvous for results: the existing `activity_log`/RFA schema (see `docs/survey-activity-design.md` D3, D8) is RE's own operational record, but it's not the only channel results should flow through — Egeria's notification mechanism, journaling discoveries as blog-style entries visible to particular communities, comments, and formal reports are all candidates depending on audience, and these aren't mutually exclusive with the activity log.

Full context: `docs/egeria-collaboration-and-survey-model.md`, section 2.

---

### Survey/Analysis model conformance to Egeria Area 6

RE's survey model (fixed pipeline of sub-surveyors, one `SurveyResult` per run) doesn't yet reflect Egeria's actual Area 6 mechanics — composable `AnalysisStep` phases within a survey, embeddable survey-pipeline connectors, declarative annotation-type catalogs, standard completion guards, and (critically) no existing built-in notion of different survey "kinds" (shallow sweep vs. deep focused, persona-tailored presentation). RE will likely need to grow more variety of survey/analysis "kinds" faster than Egeria's own connector catalog does — that's fine as long as Egeria stays the system of record — but RE's internal model should still speak Egeria's vocabulary where a precedent exists.

Full context, grounded in the actual Egeria Java source: `docs/egeria-collaboration-and-survey-model.md`, section 3.

---

### Coherent selective-cataloging model

No coherent model today for *what* to catalog and how to catalog things in groups (e.g. repo file-type checkboxes exist, but nothing like "file type AND touched in the last N months"; no selectivity at all for database or filesystem surveys). Need a general flow: Discover → Survey (broad) → Analyze/Question/Select → Survey (deep, often on the selected subset) → Catalog (side effect of deep survey or an explicit action) — with surveys triggerable by a human, on a schedule, or by Egeria automation.

Egeria has no direct precedent for "survey broadly across not-yet-cataloged resources, then selectively catalog a subset" — current Area 6 surveys always run against an asset that's already cataloged. This is genuinely new territory for RE to define, composed from existing Egeria primitives (`RequestForAction` annotations + completion guards + `GovernanceActionProcess` chaining), and possibly worth proposing back into Egeria core once proven.

Full context: `docs/egeria-collaboration-and-survey-model.md`, section 4.

---

### Periodic / triggered survey scheduling

Egeria has no native cron/interval scheduling for survey action services (the only interval-based mechanism found anywhere in the framework, `IntegrationConnectorProvider.refreshTimeInterval`, belongs to a different framework — integration connectors, not surveys). RE already has rudimentary scheduling of its own (`resource_explorer/scheduler.py` — a daemon thread polling the `resource_schedules` table every 15 minutes, per D9 in `docs/survey-activity-design.md`), so this is easily fixed short-term if a gap shows up. The longer-term expectation, though, is that recurring scheduling lands in Egeria core, or is reached via a connector to a dedicated scheduling service, rather than RE's daemon-thread approach becoming permanent infrastructure. Revisit once the selective-cataloging flow above has a shape, since "survey on a schedule" and "survey a previously-selected subset again" are closely related.

---

### Dr.Egeria as the authoring format for Survey Definitions

Direction agreed and now grounded: Dr.Egeria (RE's markdown DSL, already used via MCP and in Egeria Advisor) is the authoring format for Survey Definitions — not as a runtime trigger mechanism (MCP/Dr.Egeria command round-trips are likely too inefficient for that; A2A stays the trigger path, see the item above), but as a design-time spec format, authored in Egeria Advisor's existing plan editor. **Grounded finding: no new Dr.Egeria commands needed.** Egeria has no dedicated "SurveyActionType" open-metadata type — the closest real, catalogable element is `GovernanceActionType`, and Dr.Egeria's existing "Action Author" family already covers authoring a Survey Definition's composition end to end: each step is a `Create Governance Action Process Step` (not the more generic `Create Governance Action Type`, which is for standalone action templates never chained into a process), the survey as a whole is a `Create Governance Action Process`, and `Link First/Next Process Step` sequences them. RE-specific info (execution location, target technology type, which RE sub-surveyor a step maps to) is proposed to live in the `Additional Properties` dictionary attribute that already exists on every element in this chain — a documented key convention (`executes_at`, `supported_technology_type`, `re_analysis_step`), not a schema change.

**Conditional execution, partially resolved:** `Link Next Process Step`'s existing `Guard`/`Mandatory Guard` attributes already give real step-to-step branching (a step produces a guard, different `Link Next Process Step` commands route to different next steps based on it) — no new syntax needed for that. Still open: whether conditional logic is ever needed *within* one step's own parameters (not just branching between steps) — needs a requirements pass with concrete example Survey Definitions to answer.

`executes_at` is deliberately an open, extensible value (not a two-value enum) — `egeria` and `resource-explorer` are the first two, but other execution engines (Airflow, most obviously) should be nameable here too without a schema change, since it's a free-text dictionary value.

**RE's read/execute side is now implemented** (see the "RE locally executing Survey Definitions" item above) — the reader/executor have been exercised structurally (graph parsing, branching/cycle rejection, dispatch logic all unit-tested against canned fixtures), though authoring a real Survey Definition via Dr.Egeria and running it against a live server hasn't been validated yet.

**Not yet solved:** an `executes_at: resource-explorer` tag on a step is just catalogable metadata — nothing makes Egeria's engine host dispatch to RE *without RE itself initiating the run*. That specific case depends on the A2A item landing first. RE executing its own steps on its own initiative does not have this dependency — see the "RE locally executing Survey Definitions" item above, now implemented.

Full context: `docs/egeria-collaboration-and-survey-model.md`, section 6, and open questions A6–A9, A12.

---

### LOW — Orphaned temp-dir cleanup on hard crash

Every repo download (full ingest, incremental refresh, Coarse Profile's `refresh_profile()`, symbol-only extraction, single-collection re-embed — confirmed all 5 call sites 2026-08-10) already downloads into a `tempfile.TemporaryDirectory()`, self-cleaning on the `with` block's exit — success, error, or exception. No local clone persists anywhere by design; disk usage from a repo download is transient, existing only for the duration of that one run. The one non-`TemporaryDirectory` temp file (notebook parsing, `NamedTemporaryFile(delete=False)`) is explicitly `os.unlink()`'d in a `finally` block.

The one real gap: a hard process kill (`kill -9`, crash, power loss) mid-download skips the `with` block's cleanup entirely, potentially leaving an orphaned temp dir (partial zipball) in the OS temp directory. Rare, self-limiting (each leftover is at most one repo's zip; the OS's own temp-dir conventions eventually reclaim it), and not actively guarded against today. A small startup sweep clearing stale resource-explorer-tagged temp dirs from a previous crash would close it — not worth building unless actual `/tmp` bloat shows up in practice.
---

### Documentation as source, as dated source, and as signal (design §5.5a)

Three implementable items came out of the Milvus ground-truth exercise (spike README findings 65–67).
All three are Discovery-tier by rule 17's test — cheap, and they gate the expensive tiers.

**1. Step 0 needs an outward hop to the project's doc site.** §5.2 step 0 reads in-repo docs only, and
Milvus proves that insufficient: the authoritative logical architecture is at `milvus.io`, while
`milvus-io/milvus`'s own `docs/` has a README, `design-docs/`, `agent_guides/` and `archive/` but not
the front-door architecture page. Resolve the doc site from README links, repository metadata, or the
package manifest homepage, and treat a published architecture page as a first-class distillation
input. One fetch, once. Open question: how to recognise *which* published page is the architecture
page without hand-curation — a per-project hint in the fixture is fine to start.

**2. Path-dating, to put a vintage on any prose architecture.** `GET
/repos/{o}/{r}/commits?path={p}&per_page=1` dates any path; for a path that no longer exists that is
effectively its removal date. Vintage is bounded above by the newest dead path a description cites;
blind spot is bounded below by the churn of live paths it omits. Verified on Milvus — four calls
dated a stale description at ~17 months old without reading any Go. Should run on **any** prose
architecture we consume *and on our own recovered blueprints*, with the dates carried in §5.4
evidence. Cheap to build; the only real design choice is where unresolvable paths surface, and the
answer is probably "as their own outcome", never silently as detector misses.

**2a. Resolving where the docs live is a PREREQUISITE for item 3, not a sibling of it.** Measured
over twelve repos (spike finding 68), five of five checked keep documentation in a *separate,
actively-maintained repo*. `kubernetes/kubernetes/docs/` holds only `.gitignore` and `OWNERS` — a
tombstone — so the naive doc-lag metric scores Kubernetes at 1412 days of abandoned documentation
while `kubernetes/website` was pushed the same day. Resolve the docs location first (item 1), then
measure (item 3). Detect the tombstone pattern explicitly: a docs directory holding only
`OWNERS`/`.gitignore`/README stubs means deliberate relocation, which is a *positive* curation signal
of the same class as Milvus's maintained `docs/archive/` and Egeria's `saved/`.

Useful consequence: because the docs repo is a git repo, item 2's path-dating applies to the document
itself as well as to the paths it cites — two independent dates that cross-check, no heuristics.

**3. Doc-health as a reported signal.** Not what the docs say — whether they exist and are kept
current. Compare commit recency of doc paths against code paths; note whether stale docs are archived
(Milvus maintains `docs/archive/`, which is a stronger marker than merely having docs) or left in
place. Milvus's lag is one day. This is the measurable half of the triage judgement finding 58 needed
a human for. **Report as dated evidence, do not rank on it** — a maintained doc site can coexist with
rotting in-repo docs, and a small stable library may document lightly on purpose. A naive `docs/` mtime
is also too coarse on its own (one typo fix moves it); prefer a distribution over doc paths, and
per-component lag where §6.0 scope locators make that possible.

**4. Ground-truth candidates the scan surfaced**, in the order they should be attempted — this feeds
the pending 8–10 repo measurement re-check:

| candidate | why | caveat |
|---|---|---|
| `prometheus/prometheus` | `documentation/internal_architecture.md` is **in-repo**; 281 MB | **DONE** — pre-registered `9039f9a`, scored **0/11**, see below |
| `milvus-io/milvus` | 8 architecture pages in `milvus-io/milvus-docs`, current within a day | Go/C++ — **blocked on Go support**, see below |
| `kubernetes/kubernetes` | canonical component names map cleanly onto `cmd/` | large; doubles as a scale test |
| `odpi/egeria` (T3) | — | **negative result:** of 15 architecture hits in `odpi/egeria-docs`, most are under `saved/` (archived) or are dojo-tutorial SVGs. No current authoritative logical-architecture page. Our flagship target is the corpus's *weakest* ground-truth source — worth knowing before a poor T3 score is read as a detector failure. |

---

### DONE (spike only) — Go support: the component-proposing stack is Python/Java/npm-only

**Resolved in the spike, finding 70: Prometheus 0/11 → 11/11, ARI 0.9936.** Four changes —
`rules-imports/import-go.yml`, Go resolution in `imports.py`, a `go_subsystems()` proposer in
`detectors.py`, and a name-collision fix in `score.py` that had been silently discarding 30 of 173
components. Regression-checked: `trellis` 8/11 and `egeria-workspaces` 18/27 both unchanged.

**Still open, and now the binding constraints:**

* ~~**Port it.**~~ **DONE (finding 71).** Applied as edits, not file copies, so the package's own
  divergence survived. The ported implementation was then scored for the first time — 173 components,
  **11/11**, ARI 0.9936, identical to the spike on every measure. Nine regression tests added; full
  suite 1678 passed. The `score.py` name-collision bug was scorer-only: `arch_recovery/` already keys
  by slug throughout.
* **Precision, not recall — now the only thing that matters.** Recall across three owner-published
  fixtures is 11/11 (Prometheus), 3/5 plus two at 99.8% (Milvus) and 6/6 (Kubernetes). Against that,
  the proposer emits **173, 608 and 3270 components** for **11, 5 and 6** declared ones — the
  coupling proposer contributing 146, 409 and 2482 untyped entries. Detection is solved; **nothing
  about "3270 components" is usable by a human.** Distillation (§5.2, Phase 5) is the only remaining
  obstacle to an answer. Scale is *not* the problem: Kubernetes' 31300 files and 93046 imports run in
  ~16s end to end.
* **Go type inference.** `has_main` types `promql`, `util` and `documentation` as `Console Command`
  because some `main.go` sits beneath them.
* **Go cohesion needs recursive rollup subtrees.** Files in one Go package never import each other,
  so `coupling.py`'s `import_cohesion` is structurally ~0 at package granularity.

### (superseded) HIGH — Go support: the component-proposing stack is Python/Java/npm-only

**Correction to the row above.** It previously said Go repos would be fine except that "coupling
correctly reports `unverified`". Scoring Prometheus disproved that (spike finding 69): **three of the
four proposers produce nothing on Go.** ast-grep rules are Python/Java, `imports.py` reports
`0 python files, 0 java files`, and manifest identity is structurally blind on a single-module repo —
Prometheus's six `go.mod` files include a root module spanning the entire architecture and five
peripheral ones, none matching a component. Only co-change crossed the seam (18219 pairs), and
co-change is a *validator*, not a proposer. Result: 4 detected components against 11 declared, all
four npm packages under `web/ui/`, score 0/11.

The owners' eleven components map essentially 1:1 onto **Go package directories**. So the missing
capability is not "add a Go ast-grep rule" — it is reading Go package structure at all, which would
serve identity, imports and code markers together. Blocks Milvus and Kubernetes as well as Prometheus,
i.e. three of the four ranked ground-truth candidates.

### DONE (finding 73) — the scorer can now express a partial component match

Implemented as a **reported** measure: the strict-containment headline is unchanged and stays the
number of record, with partial cover printed beneath it as *REPORTED, not counted above*. No
threshold — "partial" is simply `0 < coverage < 1`, since a reported fraction beats an invented
cut-off. Overclaiming nodes are named separately so "we found less than the component" and "we found
a blob that merged it with something else" are no longer indistinguishable.

First run surfaced a real defect nobody could previously see: **`trellis.md`'s `Web front-end` is
unmatchable by construction** — its three missing files are `web/static/vendor/*.min.js`, which
`exclusion.py` removes as vendored, so no detector can ever claim them. Needs a note in a revision
file (rule 3 forbids editing the fixture; `trellis-revised.md` already exists as the mechanism).
`Web backend` likewise misses exactly one real file, `web/app.py` — a chaseable detector gap rather
than a component-wide failure.

### (superseded) HIGH (was doubly evidenced) — the scorer cannot express a partial component match

**Milvus makes this urgent.** Two of its five components were recovered at **575/576** and
**259/260** files — 99.8% — each missing exactly one `OWNERS` file, and both score **0**, identical
to recovering nothing (finding 72). Combined with Prometheus's `Web UI and API` at 325/380, that is
three near-misses across two independent repos, from two unrelated causes: an unsupported language
and an orphaned container-level metadata file. `step_outcome.py` has defined `partial` for this state
since the outcome vocabulary landed and the scorer has never emitted it. Strict containment itself is
correct and must NOT be loosened — 575 ≠ 576, and a measure that rounds is worse than one that is
strict. What is missing is the ability to *report* the near-miss alongside it.

### (original entry) HIGH — the scorer cannot express a partial component match

On Prometheus the detector recovered **325 of the 380 files** of the ground-truth component
`Web UI and API` — every one correctly contained, missing only the 38 Go files of the API server,
because that component is bilingual and only its TypeScript half is in a supported language. §2a's
union rule correctly declines (the union is not the full set), so it scores **0 — identical to
recovering nothing at all**.

§2a established that finding *more* structure must not score worse. This is the neighbouring defect:
finding *most* of a component must not score the same as finding none of it. `step_outcome.py`
already defines `partial` for exactly this state and the scorer never emits it. **Fix before the 8–10
repo measurement re-check**, or that run reports a wall of zeros that conceals real near-misses —
which is the same class of mistake as the three metrics that silently contradicted design decisions
they predated.
