# Resource Explorer — Backlog

**Purpose:** A running list of work items that are agreed as worth doing but are not yet scheduled into a phase of an active design document. When an item is picked up for real design/implementation, move its detail into (or link from) the relevant design doc and leave a one-line pointer here.

This is a list, not a design doc — keep entries short. Link to a full design doc/section when one exists.

**Egeria/pyegeria bugs (as opposed to RE's own bugs)** are tracked separately in `docs/egeria-pyegeria-issues.md`, not here — log new ones there as they're found.

**Current-state map (2026-08-19):** `docs/survey-and-analysis-current-state-2026-08-19.md` maps how surveys, analysis and curation work — the axes on which the two survey-launch paths diverge, an inventory of which analyses reach Egeria and which don't, and a suspected bug (filesystem annotations never publish). **It was derived from the pre-migration standalone repo and carries a staleness warning — line numbers need re-checking, and it predates `run_batch` in the executor.** Several items below are corrected there. Related: `docs/architecture-recovery-design.md` (deriving Solution Blueprints from repos).

---

## Open items

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
- **No UI for resolve.** The RFA now appears in the drawer (it did not until the
  `log_rfa` fix below); the three-way resolve action is still API-only.

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

**Shipped so far (uncommitted, prototype-stage):** `resource_explorer/prefect/flows.py` (`@flow`/`@task` wrappers) and `resource_explorer/surveyors/prefect_adapter.py` (dispatches a step to the Prefect REST API or runs it locally via `nest_asyncio`), plus `tests/test_prefect_integration.py`. `prefect` added to `pyproject.toml` dependencies. **Not yet done:** ~~`executes_at: prefect` is not wired into `survey_definition_executor.py`'s dispatch loop~~ **(CORRECTED 2026-08-19, verified against this tree: it IS wired — `_use_prefect` at `survey_definition_executor.py:162-167`. Note `:167` — when `config.prefect.enabled` is true, *every* step marked `executes_at: resource-explorer` is rerouted to Prefect, so a global flag overrides what a definition explicitly asked for. Open question whether that is intended.)**; no staged-candidate registry states in `registry.py`; no deployment/worker actually configured or run against. This needs review as a real design decision (own dependency on a flow engine is a significant infra commitment) before the prototype code is treated as a real feature — not yet reflected as its own line item, currently living only in these two design docs.

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