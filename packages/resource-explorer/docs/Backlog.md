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

### Egeria ↔ RE sync/divergence reconciliation — when one store is reset independently of the other

Today RE trusts cached Egeria GUIDs (`egeria_asset_guid`, per-file/report GUIDs) unconditionally on every survey/publish path (`egeria_filesystem_surveyor.py:262`, `egeria_database_surveyor.py:126`/`147`, likely the same pattern in the repo path too) — reported 2026-07-21: a filesystem resurvey failed with Egeria `SERVER_ERROR_500` / `InvalidParameterException` / `OMRS-REPOSITORY-404-007`/`OMRS-REPOSITORY-404-002` because the cached GUID no longer existed in Egeria's repository, after the user reset Egeria's database independently of RE's SQLite.

**Confirmed direction (2026-07-21): this is not a per-call self-healing/retry problem.** A stale root GUID means the whole Egeria-side lineage RE cached for that asset (report GUID, per-file GUIDs, annotation GUIDs) is unverifiable, not just recreatable in place — silently recreating risks duplicating Egeria elements and quietly discarding real catalog history that may still matter. **Detect, don't auto-resolve:** catch the specific "entity GUID not known to the repository" 404/`InvalidParameterException` pattern at the point of use (today it surfaces as an opaque `SERVER_ERROR_500` all the way to the UI) and mark the local entity's Egeria linkage as stale, then let a human choose the resolution.

**Salvage, not just discard (2026-07-21):** locally-cached survey results/annotations for an asset aren't automatically worthless just because Egeria's copy of the GUID mapping is gone — the underlying filesystem/database may not have changed at all, only Egeria's catalog was reset, so RE's existing local survey data may still be accurate and worth re-publishing rather than re-scanning from scratch. So the human-facing choice on detecting divergence should be three options, not two:
1. **Republish** — re-run only the Egeria-publish step against RE's existing locally-cached survey data, creating fresh Egeria elements from data RE already collected (fast, no re-scan).
2. **Re-survey** — treat as never-cataloged and re-run the full survey + publish (right call if the underlying resource may have changed too, or the local data is old enough to be suspect).
3. **Discard locally** — purge RE's cached data for that asset since it's no longer trustworthy either.

Likely UI shape: the same mechanism as the RFA/ToDo pattern (item below) — this is itself a kind of RFA ("Egeria record for X not found — reconcile?").

**Open questions:** (1) reactive-only detection (caught at point of use, as above) vs. also proactive — a lightweight guid-existence check before survey/publish operations, or a periodic reconciliation sweep; (2) how to distinguish "republish is safe" from "local data is too stale to trust" — probably needs a staleness heuristic (age of last local survey vs. some threshold) surfaced to the human rather than decided automatically, not a hard rule; (3) the reverse case — RE's SQLite reset, Egeria intact — is believed easier since a `_find_element_guid()`-by-name fallback already exists for the never-cached case, but this hasn't actually been verified against a genuinely-reset-RE-database scenario; (4) whether reconciliation is generic across all three resource types given each `egeria_*_surveyor.py` currently reimplements its own GUID-caching logic independently rather than sharing one — a fix probably shouldn't be filesystem-only.

Related: "RFAs should become real Egeria actions" below (likely the delivery mechanism for the reconcile prompt), "Unify survey launching" below (a unified launcher is a natural place to surface a "your last sync appears stale" warning before a run even starts).

---

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