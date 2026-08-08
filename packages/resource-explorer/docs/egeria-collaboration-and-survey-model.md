# Resource Explorer as an Egeria Ecosystem Member — Collaboration Model, Survey/Analysis Conformance, and Selective Cataloging

**Status:** Discussion captured; §6.6 (RE's local Survey Definition executor) is implemented, unit-tested, and validated end-to-end against a live Egeria server for both a single-step and a two-step chained PostgreSQL Survey Definition — see `docs/survey-definitions.md` for usage. Still outstanding: repo/filesystem Technology Type strings, and branching (guard-based) Survey Definitions.
**Authors:** Dan Wolfson, Claude
**Date:** 2026-07-07
**Scope:** RE's relationship to Egeria as a peer specialized server; RE↔Egeria bidirectional triggering (A2A); conformance of RE's survey/analysis model to Egeria's Area 6 framework; a coherent selective-cataloging model; authoring Survey Definitions as Dr.Egeria plans
**Relationship to other docs:** Extends `docs/survey-activity-design.md` (which established the intent model, activity log schema, and local-cache/Egeria-catalog-of-record split). This document assumes that one as background and focuses on three follow-on questions it left open or under-specified: how RE and Egeria call each other, whether RE's survey mechanics actually match Egeria's own model, and how selective cataloging should work. Backlog pointers for all deferred items live in `docs/Backlog.md`.

---

## 1. Why this document exists

This captures a design conversation about where Resource Explorer sits relative to Egeria, prompted by two questions: (1) is RE a client of Egeria or a peer in the ecosystem, and how should the two call each other; (2) does RE's survey/analysis machinery actually conform to how Egeria itself models discovery and surveys (Area 6), and if not, where does it diverge and why.

Context for anyone reading this later: Dan created Resource Explorer, pyegeria, Egeria Advisor, and Workspaces, and is a committer on Egeria itself — so this is not an integration between two unrelated projects with fixed APIs; it's one person (plus collaborators, notably Mandy on Egeria's core Java) able to evolve any layer of the stack to make the seams right.

---

## 2. RE's role in the Egeria ecosystem

### 2.1 Why RE exists (as stated in this conversation)

1. **A human interface to drive surveying/cataloging/understanding.** Egeria's automation is good, but Dan wanted curiosity- and need-driven human interaction with it, accessible without programming.
2. **Question-asking, visualization, hypothesis testing.** Users should be able to ask questions, visualize surveys, change the analysis to test new hypotheses, explore further, and decide what to do about a resource — catalog it, add context, decide how to use it.
3. **Reach beyond what Egeria can see.** Egeria's visibility is bounded by what its connectors can reach. RE can run in more places with different visibility, and can lean on other tools (e.g. Airflow) to reach and analyze further away.
4. **Python.** A large, relevant library ecosystem, and easier for data scientists/data engineers to extend than Egeria's Java core.
5. **AI augmentation.** LLMs, tabular foundation models, ML, and other techniques all have roles to play across the above, in different situations.

### 2.2 RE is not standalone — it's a specialized server in the Egeria ecosystem

Correction to an earlier framing in this conversation: RE is **not** a prototyping ground whose successful experiments "graduate" into Java connectors and disappear from RE. Some capabilities may move from RE into Egeria core over time (or vice versa) when that's the right call, but the default relationship is **collaboration between peers**, not a maturity ladder. RE is its own specialized server that extends Egeria's reach and abilities and serves as a human interface to many of Egeria's capabilities. Concretely:

- **RE → Egeria** (exists today): RE triggers Egeria's native survey action services (`AutomatedCuration.initiate_postgres_database_survey`, etc. — see `resource_explorer/surveyors/database/egeria_database_surveyor.py`), publishes locally-computed results into Egeria as `SurveyReport`/`Annotation` graphs (`egeria_publisher.py`), and reads Egeria's catalog for display (`egeria_reader.py`).
- **Egeria → RE** (does not exist yet): Egeria's governance automation (a governance action process, an engine action, a watchdog-triggered response) has no way to invoke an RE surveyor as a step in an Egeria-orchestrated workflow. This is the gap this conversation focused on closing.

### 2.3 The inbound path: A2A

Decision: extend RE's existing A2A surface (`resource_explorer/agentstack_server.py`, currently `stats`/`code`/`docs`/`health`/`compare`/`integration` agents, each its own `Server` instance per the one-agent-per-server rule) rather than inventing a bespoke REST contract for Egeria to call. Reasoning discussed:

- **The async-survey problem RE already has gets solved for free in both directions.** A2A's task-state model (`TaskState.input_required`, streaming generators, polling) is a real protocol for "this may take a while, here's how to check back" — which is exactly the shape of the problem `HybridDatabaseSurveyor` currently works around manually (trigger Egeria's async native survey, then separately run and publish a synchronous local survey because Egeria's result isn't available yet, see `docs/survey-activity-design.md` D5). If Egeria calls RE via A2A and RE calls Egeria's own surveys asynchronously, the same polling/task-state machinery could serve both directions instead of two separate ad hoc mechanisms.
- **Other tools benefit for free.** Any A2A-aware orchestrator — not just Egeria — can call RE the same way. Airflow, another agent, a different governance tool.
- **Structural gaps to close before this is real, not blockers to the approach:**
  1. The existing agents are conversational (`_text(message)` pulls a plain string, `_project_scope` regexes a `project:<slug>` prefix). A survey-trigger call is a structured invocation (asset GUID, resource type, which surveyor/analysis, options) with a structured result, not a question. A2A's `Part` supports `DataPart` for this — it means a new agent (own port) built around structured payloads, not a rework of the framework.
  2. No caller authentication exists today (`agentstack_server.py` has none). Fine for an internal chat agent; not acceptable for a surface Egeria's automation is meant to trust to trigger surveys or cataloging actions. Needs whatever Egeria's own service-to-service credential pattern is — defer to Egeria's existing conventions rather than inventing an RE-specific scheme.
  3. Result rendezvous should reuse the existing `activity_log`/RFA schema (`docs/survey-activity-design.md` D3/D8) rather than a new reporting path — an Egeria-triggered run is just another activity-log entry with a different origin, though the rendezvous mechanism itself needn't be limited to that one schema (see the note at the end of this section).

**Dr.Egeria was considered as a second inbound path and ruled out for that role — but not for authoring.** The original idea was that Dr.Egeria (RE's markdown DSL for driving Egeria, already exposed via MCP and used inside Egeria Advisor) could be extended with survey/analysis commands as an alternative to A2A for Egeria-triggered runs. On reflection, using MCP/Dr.Egeria commands as the actual *runtime* invocation path — Egeria's automation parsing/emitting markdown commands through MCP to trigger an RE survey — is likely inefficient for what is fundamentally a machine-to-machine governance-orchestration call: A2A's structured, typed request/response and native task-state polling (§2.3 above) fit that job better than round-tripping through a markdown command language and MCP tool-call layer. **A2A remains the answer for triggering.** Where Dr.Egeria clearly does earn its place is *authoring* — see §3.3, where Dr.Egeria is proposed as the format for defining Survey Definitions (design-time specs), which is a genuinely different job from runtime invocation and one Dr.Egeria is already well-suited to.

**On result rendezvous being broader than the activity log:** don't assume `activity_log`/RFA is the only channel. Several Egeria-native mechanisms are candidates for surfacing survey results and completions, depending on audience — Egeria's own notification mechanism, journaling discoveries as blog-style entries visible to particular communities, comments, formal reports. These aren't mutually exclusive with the activity log; the activity log is RE's own operational record, while these are ways the *result* gets surfaced to people and systems outside RE. Worth a dedicated pass through Egeria's existing communication/notification primitives before picking one.

### 2.4 What's deliberately deferred

The specific shape of the Egeria-side connector is deferred to Mandy (owner of Egeria's core Java / connector frameworks). Dan's expectation, subject to her judgment: this likely does **not** require a new OCF connector type — Egeria already has a wide range of connectors to use as precedent. Preparatory architecture, design, and possibly implementation work on the **RE side** (the new structured A2A agent, auth hook points, activity-log integration) can proceed ahead of the Egeria-side particulars. Tracked in `docs/Backlog.md`.

---

## 3. Survey/Analysis model conformance to Egeria Area 6

### 3.1 The concern

Dan's read: RE's survey model doesn't currently conform to Egeria's terminology and mechanics for *how* a survey is built out of parts, and separately, Egeria's own survey model hasn't yet been flexed to cover the variety of intents and users RE wants to support. Different users want RE for different purposes — understanding what's already known, extending that knowledge in specific directions (more detail, mappings, quality analysis), or exploring for new resources in new areas/endpoints/systems entirely. A large Hadoop cluster might warrant a broad shallow sweep first, then a later, narrower survey limited to resources touched in the last few months. RE will likely grow this variety faster than Egeria's own connector catalog — that's fine as long as Egeria remains the system of record — but RE should still follow Egeria's models to the extent reasonable, and right now RE doesn't have a way to define new surveys from common analysis/annotator building blocks, nor different result presentations for different personas (business analyst, steward, data engineer, data scientist).

### 3.2 What Egeria's Area 6 framework actually provides (grounded in source, not assumption)

Researched directly against the cloned Egeria repo (`/Users/dwolfson/localGit/egeria-v6/egeria`), current framework generation (**Open Survey Framework**, package `org.odpi.openmetadata.frameworks.opensurvey`) — note the older `survey-action-framework` package (`org.odpi.openmetadata.frameworks.surveyaction`) is vestigial: no `src/`, not registered in `settings.gradle`, kept only as stale compiled `build/` output. Same pattern applies to `governance-action-framework` → split into `open-governance-framework` + `open-watchdog-framework`.

**Composable analysis steps exist and are exactly what we're missing.** `controls/AnalysisStep` is a shared enum (`CHECK_ASSET`, `CHECK_ACTION_TARGETS`, `CHECK_REQUEST_PARAMETERS`, `MEASURE_RESOURCE`, `SCHEMA_EXTRACTION`, `PROFILE_DATA`, `PROFILING_ASSOCIATED_RESOURCES`, `PRODUCE_INVENTORY`, `PRODUCE_ACTIONS`, `SCHEMA_VALIDATION`, `DATA_VALIDATION`). A connector provider declares which subset/order it supports (e.g. Apache Kafka's survey declares `CHECK_ASSET → PROFILING_ASSOCIATED_RESOURCES → PRODUCE_INVENTORY`); a single `SurveyActionServiceConnector.start()` runs through its declared steps, calling `annotationStore.setAnalysisStep(...)` before each phase so both the `SurveyReport` and every `Annotation` produced in that phase are tagged with it. `FolderSurveyService` (`file-survey-connectors`) is the concrete worked example: it builds one internal list of candidate annotations, then makes three passes over it filtered by step (`PROFILING_ASSOCIATED_RESOURCES` → `PRODUCE_ACTIONS` → `PRODUCE_INVENTORY`).

**Execution model — RE already runs independently and pushes results; Egeria driving RE step-by-step is a future state, not today's.** RE today executes local surveys entirely on its own — `HybridDatabaseSurveyor` runs its local psycopg2 survey synchronously and pushes the result into Egeria via `EgeriaPublisher` afterward; Egeria never drives that local execution. Egeria driving RE (dispatching individual steps to RE mid-survey) only becomes real once the A2A inbound path (§2) exists. Given that gap, and for simplicity: **at least initially, a Survey Definition should run entirely in one place** — wholly local to RE, or wholly dispatched to Egeria's native survey engine — rather than mixing execution location step-by-step within a single run. This revises the mixed-step illustration in §6.3 (one step tagged `executes_at: resource-explorer`, the next `executes_at: egeria`, chained together) — that example still usefully demonstrates the guard-chaining mechanism, but a real first Survey Definition should probably keep `executes_at` uniform across all its steps rather than alternating; see the note added to §6.3.

Also worth documenting now as a real design point, even though it's explicitly **not to be implemented yet**: RE operating with intermittent or scheduled connectivity to Egeria — queuing local survey results locally and publishing them to Egeria in a batch whenever connectivity resumes, rather than assuming Egeria is always reachable at publish time. This would matter in highly secure or air-gapped environments where RE runs disconnected from Egeria for extended periods. Flagging it here so a future connectivity-queueing mechanism isn't a surprise architectural addition later — no design work on it now.

**There's a second, higher-level composition mechanism: true multi-connector pipelines.** `SurveyActionPipelineConnector` (a `VirtualConnectorExtension`) runs a list of independently embeddable `SurveyActionServiceConnector`s in sequence against one shared `SurveyContext` — `SequentialSurveyPipeline` is the (only) shipped implementation. This is genuinely composable "annotators" as separate connectors, distinct from the in-service "analysis step" phases above. **This maps directly onto what RE needs for building new surveys out of common building blocks** — RE's `BaseSurveyor` subclasses (`FileStructureSurveyor`, `HealthSurveyor`, `SecuritySurveyor`, etc., in `resource_explorer/surveyors/sub_surveyors/`) are already, structurally, embeddable annotator-producing units run in a fixed sequence by `SurveyOrchestrator` — the gap is that RE's sequence is hard-coded per resource type rather than declared/composed, and RE's units don't carry an `AnalysisStep`-equivalent tag.

**Shallow-vs-deep and scope-limiting already have precedent, just not for "recency."** `FolderSurveyService` is controlled by an `analysisLevel` request parameter (`TOP_LEVEL_ONLY` / `ALL_FOLDERS` / `TOP_LEVEL_AND_FILES` / `ALL_FOLDERS_AND_FILES`) — a real, shipped shallow/deep distinction. More generally, `controls/SurveyRequestParameter` defines framework-wide standard parameters `FINAL_ANALYSIS_STEP` ("run through step N and stop") and `IGNORE_ANALYSIS_STEPS` ("skip these specific steps"), and the Apache Atlas survey action service doc describes exactly this pattern in practice: "each analysis step builds on the work of its predecessor... you can choose to stop the processing after any step using the `finalAnalysisStep` property." **Gap confirmed by exhaustive search:** no existing survey connector filters *input* scope by recency (last-modified, last-accessed) — `FolderSurveyService` captures modification times as *output* measurements only. A "survey only resources touched in the last N months" parameter would be a genuinely new addition, but the idiomatic way to add it already exists (`SurveyRequestParameter`-style declarative request-parameter enum) — it isn't a new mechanism, just a new parameter. Recency is only one example, though — real scope-selection criteria are likely to be many, and combined with compound/logical expressions (e.g. "recency AND file type AND size threshold," or "size > X OR touched in last N days"), not just a single scalar filter. Whatever mechanism gets designed for this needs to support that compound case from the start rather than being built around a single-parameter example and needing rework later.

**Standard completion guards already distinguish "kinds" of outcome, and there's a second guard set for quality/certification-flavored surveys.** `controls/SurveyActionGuard` defines `SURVEY_COMPLETED`/`SURVEY_INVALID`/`SURVEY_FAILED` plus certification-oriented guards `DATA_CERTIFIED`/`DATA_NOT_CERTIFIED`/`MISSING_CERTIFICATION_TYPE`/`MISSING_SCHEMA_TYPE`, exposed as two named sets: `getSimpleSurveyGuardTypes()` and `getDataValidationSurveyGuardTypes()`. This is real precedent that Egeria already distinguishes a plain discovery survey from a quality/validation-flavored one at the guard level — relevant to the "different intents" question, though it doesn't yet extend to persona-based presentation (that's UI-layer, not something Egeria's framework addresses today). Confirmed as a real, deliberate extension point rather than a hard boundary: if persona-based presentation ever needs to be modeled in Egeria itself (not just RE's UI layer), that's something we can implement in Egeria if the need arises — not a limitation to design around permanently.

**Annotation taxonomy — corrected and expanded vs. what RE's `survey_report.py` currently models.** The real property classes (`open-metadata-framework/.../properties/surveyreports/`) are: `SchemaAnalysisAnnotationProperties`, `ClassificationAnnotationProperties`, `DataClassAnnotationProperties`, `QualityAnnotationProperties` (not `QualityScoreAnnotation`), `ResourceMeasureAnnotationProperties`, `RelationshipAdviceAnnotationProperties` (not `RelationshipAnnotation`), `RequestForActionProperties` (confirmed, matches RE's existing correction in `egeria_push_pull_design.md`) — plus several RE does not yet model at all: `DataFieldAnnotationProperties`, `DataGrainAnnotationProperties`, `FingerprintAnnotationProperties`, `ResourcePhysicalStatusAnnotationProperties`, `ResourceProfileAnnotationProperties`, `ResourceProfileLogAnnotationProperties` (used pervasively for CSV inventory/log-file annotations), `SemanticAnnotationProperties`. `SurveyReport` itself is not survey-specific at all — it's `SurveyReportProperties extends ReportProperties`, distinguished only by `analysisParameters` (the request parameters used) and `analysisStep` (current/last step).

**No first-class periodic/cron scheduling framework exists for survey/governance-action services — but Egeria does fake recurring execution today via Java code, not just the integration-connector refresh interval.** The only *declarative, framework-level* interval mechanism found is `IntegrationConnectorProvider.refreshTimeInterval` (default 60 min), which belongs to the Open Integration Framework (continuously-running integration connectors) and is architecturally unrelated to survey action services (one-shot engine actions with at most a single deferred `requestedStartDate`). However: per Dan, Egeria does achieve recurring/scheduled-feeling execution in practice by faking it with Java functions (e.g. a watchdog or governance action re-triggering itself, or an engine written to loop internally) rather than through a declared scheduling primitive — a concrete example to be tracked down separately. So the more precise finding is: there's no *clean, declarative* scheduling concept in the survey/governance-action frameworks to conform to, but there is existing precedent for achieving the effect procedurally, and it's a real gap worth formalizing (in Egeria core, or via a scheduling connector, per the direction already agreed in §4.3) rather than something entirely unprecedented. This still matches D9 in `docs/survey-activity-design.md` (medium/long-term: background thread → Airflow) as RE's own near-term stopgap.
### 3.3 Direction for RE (not yet designed in detail — for discussion)

Given the above, a plausible shape (to validate, not a final design):

- **Give RE's sub-surveyors an explicit step/phase tag**, mirroring `AnalysisStep`, so a survey's progress and a resource's known annotations can be organized the same way Egeria organizes them — this is largely a labeling exercise on `Annotation`/`SurveyResult` (`survey_report.py`), since the underlying sub-surveyors already run in a fixed, effectively-staged order.
- **Make the sub-surveyor sequence declarable per "survey kind" rather than hard-coded in `SurveyOrchestrator`**, so a "shallow sweep" survey definition and a "deep focused" survey definition for the same resource type can each declare which sub-surveyors (annotators) they include and in what order — directly analogous to `SequentialSurveyPipeline` composing embeddable connectors, and to `FINAL_ANALYSIS_STEP`/`IGNORE_ANALYSIS_STEPS` for stopping early or skipping steps. **Author these Survey Definitions in Dr.Egeria** (RE's markdown DSL, per §2.3 — as an authoring format, not a runtime trigger) rather than inventing a bespoke Python/JSON schema — a Survey Definition is naturally expressible as a markdown document declaring a resource type, a set of ordered analysis steps/sub-surveyors, and scope parameters, consistent with how the rest of the RE/Egeria stack is already authored and reviewed.
- **Many analysis steps are likely generic across resource shapes, not resource *types*.** Column profiling, for instance, is probably the same operation whether the underlying data is a CSV, a relational table, or a Parquet file — the shared structure is "tabular data," not "database" vs. "filesystem." A Survey Definition should be able to sequence these shared, reusable steps (with gates between them, echoing Egeria's `finalAnalysisStep`/guard-based stopping points) rather than each resource type reimplementing its own version of the same profiling logic.
- **Open requirements question, leaning toward "not needed": does authoring Survey Definitions in Dr.Egeria actually need conditional execution?** Dr.Egeria today has no construct for conditional/branching execution. Gated steps (the point above) or guard-based branching (mirroring Egeria's `SurveyActionGuard`/`GovernanceActionProcess` model, e.g. "if this annotation type/value is found, run this next step; otherwise skip to that one") are the kind of thing that *would* need it — but Dan's current sense is this doesn't seem needed at this point, and §6.4's finding (branching between steps already works today via `Link Next Process Step`'s `Guard`/`Mandatory Guard` attributes, no new syntax required) may already be sufficient for real cases. Still worth a requirements pass — concrete example Survey Definitions that would or wouldn't need conditional logic *within* a single step, not just branching between steps — before fully closing this out, but the working assumption going forward is that it's not a near-term requirement. Tracked in `docs/Backlog.md`.
- **Add scope-limiting request parameters (e.g. recency) as a new, RE-idiomatic parameter**, following the declarative-enum pattern Egeria uses (`SurveyRequestParameter`, `FolderRequestParameter`) rather than inventing an ad hoc kwarg per surveyor — this is confirmed new territory, not something to reconcile against an existing Egeria mechanism.
- **Persona-based presentation is UI/menu layer, not survey-mechanics layer** — this already has a home in `docs/survey-activity-design.md` D4/D6 (analysis catalog with persona/intent filters); the finding here is that Egeria's framework has no persona concept to conform to at all, so RE is free to define this without an Egeria precedent to track.

A broader framing volunteered in discussion, worth keeping in mind throughout this section: most of the underlying concepts should end up the same between RE and Egeria, since both are being designed together by the same people around shared principles. Where terminology or class names differ between RE's model and Egeria's actual code (as several do — see the annotation-taxonomy correction below), treat that as **drift from parallel evolution, not a mistake to hunt down and fix** — RE and Egeria will keep evolving somewhat independently, and periodic reconciliation passes like this one are the mechanism for catching drift, not a sign the two were ever meant to be byte-for-byte identical.

---

## 4. A coherent model for what to catalog, and cataloging in groups

### 4.1 The concern

There's no coherent model today for *what* to catalog and how to catalog things in groups. Repo surveys offer simple file-type checkboxes but nothing like "file type AND touched recently." Database and filesystem surveys currently have no selectivity over what gets cataloged or reported at all. The general shape wanted: **Discover → Survey (broad) → Analyze/Question/Select → Survey (deep, often on the selected subset, often requiring cataloging as a side effect) → repeat**, with surveys of any kind triggerable by a human, on a schedule, or by Egeria's own automation.

### 4.2 What Egeria provides today (grounded in source)

Cataloging and surveying are already architecturally separate in Egeria, but in a way that doesn't cover RE's use case:

- **Cataloging is done via Integration Connectors against `CatalogTarget`s** (`open-governance-framework/.../properties/CatalogTarget.java`) — each catalog target is an explicit, named thing to catalog (`catalogTargetName`, `metadataCollectionQualifiedName`, `connectionName`, `configurationProperties`, `templates`). Egeria's cataloging model already assumes a specific, selected target list, not "catalog everything found."
- **Surveys, conversely, always run against an asset that is already cataloged** — `SurveyContext.assetGUID` is always non-null. There is no existing Egeria governance action service that surveys an *uncataloged* filesystem/database/cluster and then decides what subset to catalog. `FolderSurveyService`, for example, surveys a folder that's already an asset and produces annotations/CSV inventories describing its files, and flags problems via `RequestForAction`, but never catalogs the individual files it finds as new assets itself.
- **The closest existing composable mechanism** is: a survey attaches `RequestForActionProperties` annotations (linked to specific elements via `linkRequestForActionTarget`) and sets a custom completion guard (e.g. `DATA_NOT_CERTIFIED`); a `GovernanceActionProcess` configured to catch that guard can route to a subsequent remediation/cataloging step scoped to just the flagged targets. This is a real, working "survey flags candidates → subsequent action processes only the flagged candidates" chain, but it's a pattern assembled from primitives (`Annotation` + `RequestForAction` + guard + `GovernanceActionProcess`), not a pre-built selective-onboarding service. No "onboarding governance action service" precedent exists in the codebase at all.

**Revised conclusion: this is less of a gap than first framed.** Egeria already implies a coarse-to-fine escalation pattern, just not automated end-to-end. You catalog a resource coarsely first (a database server, a filesystem root, a Kafka cluster, as a single asset), survey runs *within* that already-cataloged domain, and the natural next move is to selectively catalog a finer-grained subset of what the survey found (specific tables, specific files) so *that* subset can be surveyed more deeply in turn. That's exactly the same coarse/fine escalation Egeria's asset model already assumes for the first turn (catalog → survey) — what doesn't exist as a pre-built service is the *second* turn of the same crank (survey output → selective fine-grained catalog → deeper survey), repeated as needed. RE's job is to make that second (and third, and Nth) turn a first-class, repeatable operation, expressed with the same primitives as the first turn (`Annotation`, `RequestForAction`, guards, `GovernanceActionProcess`) so it stays interoperable and could plausibly be proposed back into Egeria core once proven.

### 4.3 Direction for RE (not yet designed in detail — for discussion)

A plausible shape, following the concern's own phrasing (Discover → Survey → Analyze/Select → Deep-Survey/Catalog):

- **Discover**: a broad, shallow sweep across an as-yet-uncataloged space (a Hadoop cluster, a file share, a set of endpoints) producing lightweight inventory annotations (`ResourceMeasureAnnotation`/`ResourceProfileLogAnnotation`-shaped, per §3) without creating Egeria assets for every item found — analogous to how `FolderSurveyService` writes CSV inventories rather than cataloging every file.
- **Analyze / Question / Select**: the human-curiosity-driven step from Dan's original motivation (§2.1, point 2) — a UI over the Discover output that lets a user filter/select a subset (file type + recency, size thresholds, naming patterns, whatever the resource type supports) rather than the current all-or-nothing repo checkboxes. This step also includes analysis *over time* — comparing results across multiple prior survey runs (schema drift, row-count trends, newly-appeared vs. disappeared resources), not just filtering a single snapshot. This is the same temporal concern as D9 in `docs/survey-activity-design.md`; Select criteria should be able to reference "changed since last run" alongside static properties like file type or size.
- **Survey (deep) on the selection**: the selected subset gets a focused, deeper survey (per §3's "deep survey kind"), and cataloging becomes an explicit side effect of that step (or a distinct follow-on action) rather than bundled into the broad sweep.
- **Expressed in Egeria terms**: the Discover step's output should be modeled as `RequestForAction`-flagged candidates with a completion guard (e.g. a new RE-defined guard analogous to `DATA_NOT_CERTIFIED`, something like "candidates ready for review"), so that if this pattern is later driven by Egeria automation (via the A2A path in §2) rather than a human in the RE UI, it composes with `GovernanceActionProcess` chaining the same way a human-driven select-then-catalog flow would.
- **Triggering**: all of Discover/Survey/deep-Survey/Catalog should be triggerable by a human (today's primary path), on a schedule, or by Egeria automation once the A2A inbound path (§2) exists — the same operations, three different initiators, landing in the same `activity_log` schema either way. On scheduling specifically: RE already has a rudimentary scheduler today (`resource_explorer/scheduler.py` — a daemon thread polling the `resource_schedules` table every 15 minutes, driving repo/database surveys), but the expectation going forward is that recurring scheduling lands in Egeria core, or is reached via a connector to a dedicated scheduling service, rather than becoming permanent RE-native infrastructure — RE's existing scheduler is a stopgap to revisit once that exists, not the long-term home (see also §3.2's note on Egeria having no native cron mechanism today). Completion notifications should likewise go through Egeria's own notification mechanism rather than a bespoke RE notification path, consistent with the broader point in §2.3 about result rendezvous not being limited to RE's own activity log.

---

## 6. Dr.Egeria design for authoring Survey Definitions

Follow-on to §2.3/§3.3's proposal to author Survey Definitions in Dr.Egeria. This section grounds that proposal in the actual Egeria type system and the actual Dr.Egeria compact command specs (`egeria-python/md_processing/data/compact_commands/`), rather than assuming a new command family is needed.

### 6.1 What a "Survey" maps to: no new type needed

Searched the current Egeria type archive (`open-metadata-resources/open-metadata-archives/open-metadata-types/`) for a dedicated survey-definition type. There isn't one. `SurveyReport` (model 0603) exists and is the *result* entity (§3.2), but nothing called `SurveyActionType` or similar exists as a catalogable, reusable "template for a survey" — confirming, from a different angle, the §3.2 finding that surveys and other governance actions share hosting infrastructure (`SurveyActionServiceHandler extends GovernanceServiceHandler`). The closest real, catalogable element is **`GovernanceActionType`** (defined in `OpenMetadataTypesArchive2_6.java`, entity `GOVERNANCE_ACTION_TYPE`, extends the generic `GovernanceAction` → `GovernanceControl` → `GovernanceDefinition` → `Referenceable` chain) — the same generic "reusable call template" entity used for any governed action, survey or otherwise.

Its own properties are minimal: `waitTime`, `producedGuards` (confirmed directly in `GovernanceActionTypeProperties.java` and in the `Governance Action Type Base` bundle in `commands_action_author.json`), plus everything inherited from `GovernanceControl`/`GovernanceDefinition`/`Referenceable` — `displayName`, `qualifiedName`, `description`, `additionalProperties`, `domainIdentifier`, `scope`, `importance`, `implications`, `outcomes`, `results`, `usage`, etc. Notably absent from the properties model entirely (checked directly, not assumed): any field binding a `GovernanceActionType` to the specific governance/survey engine or connector that executes it (no `governanceEngineName`/`governanceEngineGUID`/`connectorType` property anywhere in the open-metadata-framework governance properties package). That binding is resolved at the engine-host/request-type-configuration layer, outside the catalogable element itself — meaning a `GovernanceActionType` (or, by extension, a Survey Definition modeled on it) is a **description of what an action is and produces, not a wiring diagram for how it actually runs.** That distinction matters for what Dr.Egeria commands can and can't do here (§6.4).

**Dr.Egeria already has commands for exactly this entity family** — the "Action Author" family (`commands_action_author.json`) already defines `Create Governance Action Type`, `Create Governance Action Process`, `Create Governance Action Process Step`, `Link First Process Step`, `Link Next Process Step`. `GovernanceActionProcessStep` is itself a subtype of `GovernanceActionType` (confirmed in the same archive file), and `GovernanceActionProcess` + chained `GovernanceActionProcessStep`s via `NextGovernanceActionProcessStepLink` is precisely "an ordered sequence of steps" — the same composition Egeria's own `SequentialSurveyPipeline` and `AnalysisStep` phases need (§3.2).

**Conclusion: no new Dr.Egeria commands are needed to author a Survey Definition's composition.** A Survey Definition = one `Create Governance Action Process` (the survey as a whole) + one `Create Governance Action Process Step` per analysis step + `Link First Process Step`/`Link Next Process Step` to sequence them. This reuses the existing "Action Author" family exactly as-is. (`Create Governance Action Type` is the base command for a standalone action template that's never chained into a process — not what a Survey Definition's steps need, since every step here participates in the `Link First/Next Process Step` chain; those link commands' "Governance Action Process Step" reference is typed specifically to `GovernanceActionProcessStep` elements, confirmed against the real compact command spec.)

**Not yet solved by any of the above: an inventory of analysis steps to compose from.** Being able to *author* a chain of `GovernanceActionType`/`GovernanceActionProcessStep` elements says nothing about knowing which steps already exist to chain together. Two distinct halves to this, both real gaps:
- **Finding Egeria's existing analysis steps** — discoverable in principle via the same technology-type/governance-definition search already referenced in `docs/survey-activity-design.md` D4/D6 (`find_technology_types`/`get_tech_type_detail`, or a direct `GovernanceActionType` search), but not yet exercised for this purpose.
- **Publishing RE's own analysis steps (sub-surveyors) as catalogable elements** — RE's sub-surveyors (`FileStructureSurveyor`, `HealthSurveyor`, etc.) don't exist as `GovernanceActionType` elements in Egeria at all today; nothing publishes them. Before an author can reference `re_analysis_step: schema_inventory` in a Survey Definition (§6.2), something has to have created a catalogable element for `schema_inventory` in the first place — and a mechanism for registering a *new* RE analysis step (when someone adds a new sub-surveyor) so it becomes discoverable the same way, not just usable if you already know its name.

Practically, this likely means: a one-time (or per-addition) publish step — plausibly an extension of `EgeriaPublisher`, or its own small Dr.Egeria plan — that creates a `GovernanceActionType` per RE analysis step with `executes_at: resource-explorer` and the right `re_analysis_step`/`supported_technology_type` tags, plus some local inventory (a registry, possibly just RE's existing sub-surveyor registration, extended with these Egeria-facing identifiers) so RE itself always knows the mapping. Not designed in detail yet — flagged here as a real prerequisite to §6.3 actually working, not an afterthought. Tracked in `docs/Backlog.md`.

### 6.2 Where RE-specific information goes: Additional Properties, as proposed

`Additional Properties` (a generic `Dictionary`-style attribute) is present on every entity in this chain — confirmed directly in the rendered advanced templates (`Create_Governance_Action_Type.md`, `Create_Governance_Action_Process.md`). This is exactly the field Dan proposed starting with for recording execution location, and it needs no schema change, no new Tinderbox attribute, no regeneration pass — it's already there. Proposed convention (not a schema change, just a documented key convention within the existing dictionary):

| Key | Example value | Meaning |
|---|---|---|
| `survey_definition` | `PostgreSQLStandardSurvey` | Groups steps belonging to the same logical survey (redundant with the containing `GovernanceActionProcess`, but useful for a step viewed in isolation) |
| `executes_at` | `egeria` \| `resource-explorer` \| `airflow` \| ... | Where this step actually runs — the piece of information this whole exercise was about capturing. Deliberately an open, extensible identifier rather than a closed two-value enum: RE and Egeria are the first two, but other execution engines (Airflow, most obviously — per §2.1 point 3, reaching further via other tools was one of RE's founding reasons to exist) should be nameable here too without a schema change, since it's a free-text dictionary value, not a validated `Valid Values` list. |
| `supported_technology_type` | `PostgreSQL Database` | Which technology type this step/survey applies to — lets RE's "choose a survey for this resource" menu (§3.1) filter by matching the resource's own technology type |
| `re_analysis_step` | `schema_inventory` | For `executes_at: resource-explorer` steps only — which RE sub-surveyor/analysis-step key this corresponds to, so RE knows what to actually run when it reads this element |

This is deliberately a documented convention over a generic field, not a first-class validated attribute — consistent with the skill's own caution (Step 3: an attribute that "looks like" it changed doesn't mean anything reads it yet). If usage proves out and the convention needs real validation (valid-values enforcement, required-ness), *that's* the point to go back to Tinderbox and promote `executes_at`/`supported_technology_type` to real `custom_attributes` on `Create Governance Action Type` — not before.

### 6.3 Draft example: a Dr.Egeria plan authoring a Survey Definition

Illustrative only — attribute names/values follow the real rendered templates in `egeria-python/sample-data/templates/basic/Action Author/`, but this hasn't been run against a live server.

**Note on execution locality (per §3.2's revised finding):** the example below mixes `executes_at: resource-explorer` and `executes_at: egeria` across two chained steps to demonstrate that the guard-chaining mechanism works regardless of where each step runs. For an actual first Survey Definition, prefer keeping `executes_at` uniform across all steps in the survey — the mixed-step form shown here is a capability demonstration, not the recommended v1 shape. See §6.6 for an important, separate point: RE executing its own `executes_at: resource-explorer` steps does **not** need to wait on the A2A work at all.

**Implemented:** the `re_analysis_step` values recognized today are richer than this single-example sketch — `postgres_schema_and_stats` (database), `filesystem_inventory` (filesystem), and one key per repo sub-surveyor (`repo_file_structure`, `repo_file_size`, `repo_language`, `repo_health`, `repo_dependency`, `repo_documentation`, `repo_security`, `repo_api_structure`, `repo_data_profiling`, `repo_file_classification`). Full authoring reference: `docs/survey-definitions.md`.

```markdown
## Create Governance Action Process Step
> A description of a call to perform a step in a governance action process. This acts as a template when creating the appropriate engine action instance.

### Display Name
PostgreSQL Standard Survey — Schema Inventory

### Qualified Name
GovActionProcessStep::PostgreSQLStandardSurvey::SchemaInventory

### Description
Schema/table/column inventory step of the PostgreSQL Standard Survey Definition.

### Domain Identifier
DATA

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| survey_definition | PostgreSQLStandardSurvey |
| executes_at | resource-explorer |
| supported_technology_type | PostgreSQL Database |
| re_analysis_step | schema_inventory |

### Produced Guards
schema-inventory-complete, schema-inventory-failed

___

## Create Governance Action Process Step
### Display Name
PostgreSQL Standard Survey — Row Count Snapshot

### Qualified Name
GovActionProcessStep::PostgreSQLStandardSurvey::RowCountSnapshot

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| survey_definition | PostgreSQLStandardSurvey |
| executes_at | egeria |
| supported_technology_type | PostgreSQL Database |

### Produced Guards
survey-completed

___

## Create Governance Action Process
### Display Name
PostgreSQL Standard Survey

### Qualified Name
GovActionProcess::PostgreSQLStandardSurvey

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| supported_technology_type | PostgreSQL Database |
| survey_kind | shallow-sweep |

___

## Link First Process Step
### Governance Action Process
GovActionProcess::PostgreSQLStandardSurvey

### Governance Action Process Step
GovActionProcessStep::PostgreSQLStandardSurvey::SchemaInventory

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::PostgreSQLStandardSurvey::SchemaInventory

### Next Governance Action Process Step
GovActionProcessStep::PostgreSQLStandardSurvey::RowCountSnapshot

### Guard
schema-inventory-complete

### Mandatory Guard
true
```

### 6.4 Conditional execution, revisited — partially resolved

§3.3/A7 flagged "does Dr.Egeria need conditional execution" as an open, unresolved requirements question. Reading the actual `Link Next Process Step` template answers part of it: **branching by guard is already a real, existing mechanism**, not something to design from scratch. `Link Next Process Step` carries `Guard` and `Mandatory Guard` — a step's completion sets a guard (`Produced Guards`), and separate `Link Next Process Step` commands from the same step, each keyed to a different guard value, is how a `GovernanceActionProcess` branches (e.g. `schema-inventory-complete` → `RowCountSnapshot`, `schema-inventory-failed` → some remediation/RFA step instead). This is exactly the guard-chaining mechanism already documented in §3.2/§4.2 for `SurveyActionGuard`/`GovernanceActionProcess`, just confirmed here at the Dr.Egeria command level too.

What's still genuinely open: this gives branching *between* steps (which step runs next, based on the previous step's outcome), not conditional logic *within* a single step's own parameters (e.g. no inline "if request parameter X > threshold then Y" expression language inside one `Create Governance Action Type`/`Create Governance Action Process Step` command). Whether Survey Definitions need that finer-grained kind of conditional is still the open part of A7 — the coarser step-to-step branching this section confirms may well be sufficient for the concrete cases that matter, but that's exactly the requirements pass (concrete example Survey Definitions) A7 already called for.

### 6.5 What this doesn't solve: Egeria-side dispatch of RE-hosted steps

Authoring a `GovernanceActionType`/`GovernanceActionProcessStep` with `executes_at: resource-explorer` in its `Additional Properties` is just a catalogable declaration — nothing today makes Egeria's engine host actually *act* on that value by calling RE **without RE itself being the one to initiate the run**. That specific case — Egeria's own automation (a governance action process, an engine action, a watchdog) deciding on its own to trigger an RE step as part of an Egeria-orchestrated workflow — genuinely depends on the Egeria-side connector from the A2A backlog item (§2, `docs/Backlog.md`) existing first. That's the only thing still gated on A2A; see §6.6 for the much larger piece that isn't.

### 6.6 RE executing Survey Definitions locally, independent of Egeria and independent of A2A — the priority item

**Implemented (2026-07-07).** Code: `resource_explorer/surveyors/survey_definition_reader.py`, `survey_definition_executor.py`, and one adapter per resource type (`database/survey_definition_adapter.py`, `repo_survey_definition_adapter.py`, `filesystem/survey_definition_adapter.py`), plus three CLI commands. Unit-tested (`tests/test_survey_definition_reader.py`, `tests/test_survey_definition_executor.py`) and validated against a live Egeria server for a single-step PostgreSQL Survey Definition — including correcting the reader's graph-parsing to the real response shape (`governanceActionProcess`/`firstProcessStep` top-level keys, step properties under `processStepProperties`, no `relationshipHeader` wrapper at all, unlike the first guess). Usage: `docs/survey-definitions.md`. One correction vs. the proposal below: publishing does **not** go through the existing `EgeriaPublisher`/`publish_local_survey` path unmodified for every resource type — only the repo adapter reuses `EgeriaPublisher.publish` as-is. Database and filesystem needed new, narrower publish-only methods (`publish_step_annotations`) because their existing "publish" methods (`publish_local_survey`, `catalog_and_survey`) also auto-catalog the resource and/or trigger Egeria's own native survey as a side effect — not appropriate once a Survey Definition has already explicitly declared the step runs in RE. See `docs/survey-definitions.md`'s "What happens on a run" section.

Important correction to how §6.5 could be read: **RE does not need to wait for the A2A work to execute a Survey Definition's own `executes_at: resource-explorer` steps.** RE already reads Egeria's catalog directly (`egeria_reader.py` — precedent for exactly this kind of read), and RE already executes local surveys entirely independently of Egeria and publishes results back afterward (`HybridDatabaseSurveyor`/`EgeriaPublisher` — precedent for exactly this kind of local execution). Nothing about either of those depends on Egeria's engine host being able to dispatch to RE. The A2A work in §2 is only required for the *opposite* direction — Egeria's automation deciding, on its own, to trigger an RE step without a human or RE itself kicking things off. RE reading a Survey Definition it already knows about and running its own steps is a fundamentally different, much more tractable case that can be built now.

**This is flagged as the highest-priority open design item to actually build**, ahead of the A2A work: the concrete shape is RE (a) fetching a `GovernanceActionProcess` + its chained `GovernanceActionType`/`GovernanceActionProcessStep` elements for a given resource via pyegeria, (b) walking the step graph in order (respecting `Link Next Process Step` guards, §6.4), (c) for each step where `executes_at: resource-explorer`, dispatching to the matching RE sub-surveyor via its `re_analysis_step` key (which depends on the analysis-step inventory/registration gap in §6.1 being solved first — the two are directly linked), and (d) writing results back through the existing `EgeriaPublisher` path exactly as today. Steps tagged `executes_at: egeria` (or any other engine, per §6.2) are simply skipped by RE's local executor — those remain Egeria's (or that other engine's) problem to run, whenever that dispatch exists.

Deliberately scoped down for a first cut, not full generality: **execute for a restricted vocabulary and pattern set first** — e.g. only strictly linear step sequences (no guard branching yet), only steps whose `re_analysis_step` maps to an existing, already-registered RE sub-surveyor (no dynamic/unknown steps), one resource type at a time (PostgreSQL first, matching §4.3's D7 priority order). Widen the supported vocabulary once the restricted version works end-to-end, rather than building full generality up front.

---

## 7. Open questions carried forward

| # | Question | Where it matters | Answer / status |
|---|----------|-------------------|------------------|
| A1 | What should the Egeria-side connector for inbound RE calls actually look like? | §2.4 — deferred to Mandy | Open |
| A2 | What auth mechanism should gate Egeria→RE A2A calls? | §2.3 | Answered — use Egeria's existing bearer-token approach and security services directly; no need for a separate RE auth namespace/scheme. |
| A3 | Should RE's sub-surveyor `AnalysisStep`-equivalent tagging be added before or after the declarative "survey kind" composition work? | §3.3 | Reframed rather than directly answered — many analysis steps are likely generic/reusable across resource *shapes* (e.g. column profiling is probably the same for CSV, a relational table, or Parquet), so Survey Definitions should sequence shared reusable steps with gates between them, rather than tagging being a purely per-resource-type exercise. See §3.3. |
| A4 | What's the right RE-native guard vocabulary for "candidates ready for review" in the Discover→Select flow, and should it literally extend `SurveyActionGuard`-style naming for consistency? | §4.3 | Answered — as a starting principle, stay close to Egeria's own concepts and terminology, at least internally, rather than defining a parallel RE vocabulary. |
| A5 | Once selective cataloging has a working shape in RE, is it worth proposing back into Egeria core (a new governance action service category), given Dan's committer status? | §4.2 | Answered — yes; if RE arrives at a good model, the intent is to collaborate with the Egeria core team and push it in. |
| A6 | Should Dr.Egeria (RE's markdown DSL, already used via MCP and in Egeria Advisor) be extended to support survey/analysis commands, alongside or instead of the A2A inbound path? | §2.3, §3.3, §6 | Answered — not as a runtime trigger (MCP/Dr.Egeria command round-trips are likely too inefficient for machine-to-machine invocation; A2A stays the trigger path), but yes as the authoring format for Survey Definitions — and §6 confirms this needs no new Dr.Egeria commands at all, just reuse of the existing "Action Author" family. |
| A7 | Do Survey Definitions actually require conditional/branching execution, or do linear sequences plus stop/skip parameters cover the real cases? Dr.Egeria has no conditional-execution construct today. | §3.3, §6.4 | Mostly answered, leaning "not needed" — `Link Next Process Step`'s existing `Guard`/`Mandatory Guard` attributes already give step-to-step branching (confirmed in the real template, no new syntax needed), and Dan's current sense is that within-step conditional logic doesn't seem needed at this point. Still nominally open pending a concrete-example requirements pass, but not treated as a blocker going forward. |
| A8 | Once a real Survey Definition is authored this way, what does RE's own read side and local executor look like — does it parse `GovernanceActionType`/`GovernanceActionProcess` elements directly via pyegeria, and how does it run its own steps? | §3.1, §6.5, §6.6 | **Implemented** — see §6.6's "Implemented" note and `docs/survey-definitions.md`. Built generic across all three resource types (not just database), with the restricted-vocabulary scope (linear sequences only, hardcoded `re_analysis_step` mapping) as planned. Unit-tested and live-validated for both single-step and two-step chained PostgreSQL Survey Definitions (the graph-parsing was rewritten once against real data — it's a genuine node+edge graph via `processStepLinks`, not a nested chain). Remaining open: repo/filesystem Technology Type strings, and branching (guard-based) Survey Definitions, untested live. |
| A9 | Should a single Survey Definition ever mix execution locations across its steps (some `executes_at: egeria`, some `executes_at: resource-explorer`), or should v1 keep each Survey Definition wholly local or wholly Egeria-native? | §3.2, §6.3 | Answered for now — keep it simple initially: a Survey Definition should run entirely in one place. Mixed-location composition is deferred until there's a concrete need (and until Egeria-side dispatch to RE, per §6.5, exists to make the Egeria-hosted half actionable rather than just declarative). |
| A10 | What does RE's intermittent/scheduled-connectivity design (queue results locally, publish to Egeria when reconnected) actually look like? | §3.2 | Explicitly deferred — documented as a real future design point (useful for secure/air-gapped deployments), not to be designed or implemented now. |
| A11 | What's a concrete example of Egeria "faking" recurring/scheduled execution via Java functions today (referenced as an existing but undocumented precedent)? | §3.2 | Open — Dan to supply a concrete example; once available, revisit the "no native scheduling" framing in §3.2 and the scheduling Backlog item. |
| A12 | How does RE discover/register analysis steps as catalogable Egeria elements — both finding Egeria's existing ones and publishing RE's own sub-surveyors the first time they're used? | §6.1 | Still open. §6.6's local executor now has a concrete, real dispatch point (each adapter's `re_analysis_steps` dict) that this future work would extend or replace — today it's a small hardcoded Python mapping per resource type, not a catalogable/extensible registry. |

See `docs/Backlog.md` for tracked, not-yet-scheduled work items derived from this document.