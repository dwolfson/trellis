# Surveys, Analysis, and Curation — Current State (2026-08-19)

**Status:** findings document, not a work plan. Everything below is observed in the code as of
commit `a3facfc` plus the uncommitted `feature/egeria-valid-values` changes. Open decisions are
collected at the end rather than resolved here.

**Purpose:** hand-off. A thread picking this up cold should be able to work from this document
without re-deriving the map.

> ## ⚠ STALENESS WARNING — READ BEFORE USING THIS DOCUMENT
>
> **This document was derived from the pre-migration standalone `resource-explorer` repo
> (`/Users/dwolfson/localGit/egeria-v6/resource-explorer`, branch `analysis-exploration`), not from
> `trellis/packages/resource-explorer`, which is the live tree. The two have diverged materially.**
>
> Measured divergence at time of porting (2026-08-19):
>
> | File | Standalone (this doc's source) | Trellis (live) |
> |---|---|---|
> | `surveyors/survey_definition_executor.py` | 296 lines | **375 lines** — refactored dispatch, plus a new `run_batch` mechanism not described anywhere below |
> | `web/static/index.html` | 5,503 lines | **10,321 lines** |
>
> **Treat every line number in this document as wrong until re-checked.** Structural findings are more
> durable than citations, but both need verification.
>
> ### Spot-checked against trellis at porting time
>
> | Finding | Status in trellis |
> |---|---|
> | **F1** — filesystem publish reads undefined `ann.egeria_type_name` | **STILL LIVE.** Read at `egeria_filesystem_surveyor.py:540`; defined nowhere in the package. Not an artifact of the stale tree. |
> | Prefect **is** wired into the executor (backlog correction) | **HOLDS.** Now `survey_definition_executor.py:162-167` (`_use_prefect`). |
> | Global-flag Prefect coercion of `resource-explorer` steps | **HOLDS**, now at `:167`. |
> | Legacy per-type re-survey buttons still bypass Survey Definitions | **HOLDS** structurally — buttons now at `index.html:7351`, `:7377`, `:7389`. |
>
> ### Known NOT covered
>
> - **`run_batch`** (`survey_definition_executor.py:75`, dispatch at `:189`/`:208`) — batches consecutive
>   `resource-explorer` steps into one adapter call so shared resources (e.g. a repo zipball) aren't
>   re-acquired per step. Postdates this analysis entirely. It likely interacts with §1.2's divergence
>   analysis and §5's open decision on which survey path wins — **re-read the executor before planning
>   that work.**
> - The whole of §2 (analysis inventory) was derived from the stale tree; the UI-facing parts of §1.2
>   and §4 especially, given `index.html` has roughly doubled.
>
> **Recommendation:** use this as a map of *what to look for and what questions to ask*, not as a
> citation source. Re-verify against trellis as you plan.


---

## 0. Read this first — three findings that change the picture

1. **Filesystem annotations almost certainly never reach Egeria.** See [F1](#f1--filesystem-publish-is-broken).
   Suspected latent bug, static evidence only, not yet reproduced at runtime.
2. **There are three publishers, not one.** `egeria_publisher.py` handles *only* repos. Databases
   publish via `surveyors/database/egeria_database_surveyor.py`, filesystems via
   `surveyors/filesystem/egeria_filesystem_surveyor.py`. All three carry a near-duplicate
   `_build_annotation_props`, and the filesystem copy has diverged in shape as well as being broken.
3. **The two survey-launch paths diverge on five axes, not one.** The backlog frames this as a UI
   unification. It is deeper than that — see [§1.2](#12-the-two-launch-paths-and-how-they-diverge).

Two backlog entries are stale and should be corrected in place:

| Backlog claim | Reality |
|---|---|
| `Backlog.md:47` — "`executes_at: prefect` is not wired into the executor's dispatch loop" | It **is** wired: `survey_definition_executor.py:151-171`. But see [S5](#s5--prefect-coercion) for a different, real problem at `:154`. |
| Implied throughout — APScheduler is the scheduler | There is **no APScheduler**. `resource_explorer/scheduler.py` is a hand-rolled daemon thread on a 900s sleep (`_CHECK_INTERVAL_SECONDS = 900`, `:21`; loop `:42`). |

---

## 1. Surveys

### 1.1 Definition layer (Egeria-authored)

| File | Role |
|---|---|
| `surveyors/survey_definition_reader.py` | Reads an Egeria `GovernanceActionProcess` into `SurveyDefinition`/`SurveyStep` (`:81`, `:93`). `find_candidate_process_guids(technology_type)` `:152`; `fetch(guid)` `:250` → `_parse_graph` `:271` walks the real `nextProcessSteps` / `processStepLinks` shape. Raises `UnsupportedSurveyDefinitionError` `:75` on >1 outgoing edge — **no branching support**. RE-specific keys (`executes_at`, `supported_technology_type`, `re_analysis_step`) are read from each step's `additionalProperties` in `_parse_step` `:345`. |
| `surveyors/survey_definition_executor.py` | Generic dispatch loop. `ResourceTypeAdapter` `:35` is the plugin contract. `SurveyDefinitionExecutor.run` `:99` resolves the process GUID, validates tech type, loops steps `:147`, publishes once at `:227`. |
| `surveyors/database/survey_definition_adapter.py:90` | `technology_type="PostgreSQL Database"`; `egeria_technology_type_name="PostgreSQL Relational Database"` `:114`. The two strings differ **deliberately** — do not "fix" this without reading the Technology Type hierarchy note in §4. |
| `surveyors/filesystem/survey_definition_adapter.py:50` | `technology_type="File System Directory"`. The `"File Folder"` bug noted in the backlog is already fixed. Single step, `filesystem_inventory` `:51`. |
| `surveyors/repo_survey_definition_adapter.py:126` | `technology_type="Git Repository"` — still unconfirmed against a live server (`Backlog.md:102`). Steps built dynamically at `:29`. |
| `surveyors/technology_type_processes.py` + `config/technology_type_processes.yaml` | Static catalog of Egeria-*native* processes per tech type, with `KIND_DELETE` etc. so destructive processes are never offered. |
| `surveyors/egeria_tech_type_catalog.py` | `get_produced_annotation_types(tech_type_name)` — what Egeria's native engine documents it produces. |

### 1.2 The two launch paths, and how they diverge

**Path A — Survey Definitions panel** (newer, Egeria-driven).
Frontend: nav `index.html:294`, view `:338`, `loadSurveyDefinitionsPanel()` `:2836`, run modal `:2980`,
submit `:3006` → `POST .../run` `:3033`. Backend: `web/routes/survey_definitions.py:39` (candidates)
and `:140` (run). Entity/slug comes from `_surveyDefEntityAndSlug()` `index.html:2829` — bound to the
currently selected resource, and **not invocable from a resource detail panel**.

**Path B — legacy per-resource-type modals** (pre-dates A, bypasses it entirely).

| Resource | Button | JS | Endpoint |
|---|---|---|---|
| Repo | sidebar 📊 `index.html:1111` | `runSurveyFromSidebar()` `:1186` | `POST /api/egeria/{slug}/survey` (`web/routes/egeria.py:380`) |
| Repo publish | `:1741` | `publishSurvey()` `:1762` | `POST /api/egeria/{slug}/publish` (`egeria.py:411`) |
| Database | sidebar 📊 `:1353`, detail `:3856`/`:3868` | `showSurveyDbModal()` `:2314` → `submitSurveyDb()` `:2342` | `POST /api/databases/{slug}/survey` (`databases.py:206`) |
| Database (native) | `:3830`/`:3835` | `showPublishDbModal()` `:4214` | `POST /api/databases/{slug}/publish` (`databases.py:436`) |
| Filesystem | sidebar 📊 `:4618`, detail `:4938`/`:4961` | `showSurveyFsModal()` `:4742` | `POST /api/filesystems/{slug}/survey` (`filesystems.py:211`), publish `:378` |

`Backlog.md:80` (HIGH) names `index.html:3641-3675`; line numbers have drifted, the real buttons are
now `:3830` / `:3856`.

#### The five divergences

- **S1 — Step selection.** A executes exactly the steps Egeria's process graph declares. B hardcodes
  the pipeline in Python (`HybridDatabaseSurveyor`, `SurveyOrchestrator.run` `survey_orchestrator.py:50`,
  `LocalFileSystemSurveyor.run`). **Editing a Survey Definition in Egeria has zero effect on Path B.**
- **S2 — Egeria target.** B's modals collect per-call Egeria URL/server/user overrides
  (`index.html:670-690`, `:905-918`). A collects only user/password (`:780`, `:784`) and relies on env
  config. **The two paths can write to different Egeria servers within one session.**
- **S3 — Publish shape.** A always goes through `adapter.publish` → the narrow
  `publish_step_annotations`, which deliberately avoids auto-catalog side effects. B's DB/filesystem
  publish routes go through the full `EgeriaPublisher.publish` / native-survey trigger path *with*
  cataloging side effects. Same resource, two different Egeria write shapes.
- **S4 — Result storage.** B writes rows to `database_surveys` / `filesystem_surveys` /
  `project_egeria_surveys`, which drive the detail-panel history charts. A returns a dict
  (`executor.run` `:233`) shown only in the run modal — **no unified history**. `executes_at: egeria`
  steps return `status: "skipped_egeria"` `:213` or a triggered engine-action GUID, and **nothing polls
  for completion** (`Backlog.md:88`).
- **S5 — Scheduler only knows B.** `scheduler.py:84`/`:97` call `SurveyOrchestrator` and
  `run_database_survey` directly. Survey Definitions are unreachable from a schedule, and filesystems
  aren't scheduled at all (`_execute` `:73` handles only `repo`/`database`).

#### S5b — Prefect coercion {#s5--prefect-coercion}

`survey_definition_executor.py:154-158`: if `config.prefect.enabled` is true, **every** step marked
`executes_at: resource-explorer` is silently rerouted to Prefect. A global config flag overrides the
execution engine that a definition explicitly asked for. Whether this is intended is an open decision
(§5).

Prefect wiring otherwise: `resource_explorer/prefect/flows.py` (`run_surveyor_step_task` `:13`,
`run_soda_scan_task` `:65`, `run_gx_validation_task` `:107`, `re_survey_flow` `:150`),
`surveyors/prefect_adapter.py:64`, CLI `cli/main.py:1825`/`:1846`, config `config.py:142`.

### 1.3 `egeria-outbox/` — not a runtime path

Untracked, in neither git nor `.gitignore`. One file:
`egeria-outbox/dr-egeria-outbox/processed-2026-08-05 09:31-egeria-database-survey-definition.md`.
Zero source references anywhere in the repo (grepped for `outbox`).

It is the Dr.Egeria MCP round-trip receipt for `docs/egeria-database-survey-definition.md`: the doc
source uses `Create Governance Action Process Step` with `executes_at: resource-explorer` and
`re_analysis_step: postgres_schema_and_stats` / `sql_analysis`; the outbox copy is rewritten to
`Update ...` form with assigned GUIDs filled in, plus `Link First Process Step` / `Link Next Process
Step` and a `Provenance` block. An artifact directory, not a mechanism. **Decide whether it should be
tracked, ignored, or relocated.**

---

## 2. Analysis inventory — what RE computes, and what Egeria actually sees

### 2.1 Git repos

Orchestrated by `survey_orchestrator.py:63-79` (10 sub-surveyors); published by `EgeriaPublisher.publish`
→ `SourceControlLibrary` asset + `SurveyReport` + one Annotation per item.

| Analysis | Computed at | Egeria annotation |
|---|---|---|
| File-type classification vs Egeria `ValidMetadataValues` | `file_classifier/file_classifier_surveyor.py:57-104`, wrapper `:137-215` | `ClassificationAnnotationProperties` + `ResourceMeasureAnnotationProperties` |
| Extension histogram | `file_classifier_surveyor.py:186-196` | `ResourceMeasureAnnotationProperties` |
| File count / size / LOC / per-language counts / top-level dirs | `sub_surveyors/file_structure.py:46-97` | `ResourceMeasureAnnotationProperties` ×3 |
| Disk footprint, avg size, size-by-type, top-10 largest, >50MB flags | `sub_surveyors/file_size.py:92-149` | `ResourceMeasure…` ×2 + `RequestForActionProperties` ×N |
| Data-file format inventory | `sub_surveyors/data_profiler.py:204-244` | `ResourceMeasureAnnotationProperties` |
| Per-file schema profile (rows×cols, dtypes, null %) | ingest `ingestion/pipeline.py:295-357` → `project_data_profiles`; read back `data_profiler.py:248-279`; core `_summarize_df :427-456` | `SchemaAnalysisAnnotationProperties` |
| Primary/secondary language, inferred project type | `sub_surveyors/language.py:60-98`, `:106-121` | `ClassificationAnnotationProperties` ×3 |
| Health scores (activity/community/release cadence/freshness) | `sub_surveyors/health.py:86-125` | `QualityAnnotationProperties` |
| Dependencies per ecosystem | `ingestion/dependency_parser.py:24-205` → `project_dependencies`; `sub_surveyors/dependency.py:39-77` | `DataClassAnnotationProperties` + `ResourceMeasure…` |
| Doc presence, hygiene files, doc-quality label | `sub_surveyors/documentation.py:63-123` | `ClassificationAnnotationProperties` ×3 |
| SECURITY.md / CI / LICENSE presence & gaps | `sub_surveyors/security.py:65-145` | `Classification…` / `RequestForActionProperties` |
| Public API surface, symbol counts by kind | `ingestion/code_symbol_extractor.py:32-243` → `project_code_symbols`; `sub_surveyors/api_structure.py:52-85` | `SchemaAnalysisAnnotationProperties` |
| Sub-surveyor internal errors | `base_surveyor.py:38-52` | `RequestForActionProperties` |

**Not published (R-gaps):**

- **R1 — Contributor tiers / bus-factor.** `github/stats_fetcher.py:209-261` computes per-author
  commits/additions/deletions over 30/90/365d windows and classifies core/regular/occasional against
  the project's own p25/p75. Lands only in `project_contributor_stats`; consumed only by
  `agents/tools.py:432-434`.
- **R2 — Commit history, stars/forks time series, weekly-commit and language charts**
  (`web/routes/stats.py:88-186`, `dashboard/graphs.py`). `HealthSurveyor` publishes the four derived
  scores; the underlying series is never sent.
- **R3 — AST chunks / vector-store documents.** `ingestion/ast_chunker.py:64-93` (tree-sitter),
  `doc_parser.py`, `notebook_parser.py`, `api_parser.py:20-38`. Milvus-only; Egeria sees none of it.
  Note `api_parser` extracts REST endpoints and `ApiStructureSurveyor` never reads them — the "API
  endpoints" claim at `analysis_catalog.py:88` is **unbacked**.
- **R4 — Individual symbol records** (signature, line numbers, docstring, qualified name). Only
  aggregate counts and ≤15 top names per language reach Egeria (`api_structure.py:74`).
- **R5 — Per-file inventory rows** (`project_file_inventory`) — aggregates only.
- **R6 — All LLM agent output** (`agents/`). Conversational; no annotation path.
- **R7 — Incremental-change facts** (`ingestion/incremental.py:144-157`, changed-file list between
  SHAs) — never surfaced as an annotation.

### 2.2 Postgres / relational databases

Computed by `database_surveyor.py`. Output is a plain `dict` (**not** a `SurveyResult`), stored as a
JSON blob in `database_surveys.survey_data` via `_store_results :211-251`.

| Analysis | Computed at | Egeria annotation |
|---|---|---|
| Schema/table/column **counts** | `database_surveyor.py:103-158` | `SchemaAnalysisAnnotationProperties` (3 tiers) |
| DB on-disk size, top-5 largest tables | `:160-209` | `ResourceMeasureAnnotationProperties` ×2 |
| View dependency extraction (SQLGlot AST) | `_survey_views :253-328` + `sql_analyzer.py:32-48` | `SchemaAnalysisAnnotationProperties` (`:406-419`) |
| Table→view lineage edges | `:422-432` | `RelationshipAdviceAnnotationProperties` |
| Query complexity / portability / node-join-CTE-subquery counts | `sql_analyzer.py:97-165` | `QualityAnnotationProperties` (`:435-450`) |
| High-complexity (>40) / low-portability (<80) warnings | `:453-476` | `RequestForActionProperties` |
| Column-level lineage + PII propagation | `sql_analyzer.py:50-96` + `database_surveyor.py:344-377, 478-516` | `DataClassAnnotationProperties` |
| Column-level `LineageMapping` relationships | `egeria_database_surveyor.py:687-750` | **native relationship** (not an annotation — good) |

**Not published (D-gaps):**

- **D1 — SQL/lineage analysis is computed then discarded on the main paths.** `publish_local_survey`
  accepts `views=` (`egeria_database_surveyor.py:588`) but **neither caller passes it**:
  `hybrid_database_surveyor.py:154-165` and `web/routes/databases.py:481-492` both omit it. SQLGlot
  dependencies, complexity, portability RFAs and PII propagation are computed on *every* survey,
  stored in `survey_data["views"]`, and published **only** via the Survey Definition path
  (`database/survey_definition_adapter.py:84`, step `sql_analysis`). Column lineage relationships are
  gated identically (`:658`). This is [S3](#the-five-divergences) with teeth: which path you launch
  from determines whether lineage reaches Egeria at all.
- **D2 — Database schema depth is thrown away.** `connection.py:124-236` collects column names, types
  with precision/length, nullability, defaults, ordinal position, PK flags, FK targets, and
  `pg_description` table/column comments. Every annotation in `_create_schema_annotations` reports only
  a **count**. Egeria receives "table X has 12 columns" and nothing about the 12 columns. Same for
  schema descriptions (`_get_schema_descriptions :110-123`). **Largest single "RE knows something
  Egeria never sees" item.**
- **D3 — Row counts and table activity stats never annotated.** `_get_table_row_stats :304+`
  (`pg_stat_user_tables`) plus `last_analyzed`, `last_vacuumed`, `pending_changes`, merged into
  `survey_data` at `:216-227`. Contradicts `analysis_catalog.py:141-153`, which advertises a "Row Count
  Snapshot" → `ResourceMeasureAnnotation`.
- **D4 — Table sizes beyond top-5.** `_create_statistics_annotations:185` hard-slices `[:5]`.
- **D5 — `index_health` and `privilege_audit`** (`analysis_catalog.py:155-176`) are catalog entries with
  **no implementation at all** — no `pg_stat_user_indexes` / `pg_roles` queries exist anywhere.
- **D6 — Database inventory per server** (`connection.py:238-267`) is UI-only.

### 2.3 Filesystems

Computed by `local_filesystem_surveyor.py`; again a flat `dict` in `filesystem_surveys.survey_data`.

| Analysis | Computed at | Intended annotation |
|---|---|---|
| File counts, total size, per-format histogram | `local_filesystem_surveyor.py:212-226` | `ResourceMeasureAnnotationProperties` (`egeria_filesystem_surveyor.py:283-309`) |
| OS attributes (hidden/symlink/executable/writable, unique ext & filename counts, aggregate timestamps) | `:152-181, 228-236` | folded into the same `ResourceMeasureAnnotation` |
| Classification by `deployedImplementationType`/`fileType`/`assetTypeName` | `:210` → shared `classify_file_paths` | `ClassificationAnnotationProperties` (`:316-325`) |
| Raw extension histogram | `:243` | `ResourceMeasureAnnotationProperties` (`:329-336`) |
| Unclassified files | `:244-245` | `RequestForActionProperties` (`:341-349`) |
| Inaccessible files/dirs | `:141-149, 311-338` | `RequestForActionProperties` (`:354-362`) |
| Data-file schema profiles | `_profile_data_files :260-309` | `SchemaAnalysisAnnotationProperties` (`:383-400`) |
| Profiling failures | `:301` | `RequestForActionProperties` (`:368-376`) |
| Local-only RFA mirror for activity log | `:22-65` (`build_rfa_annotations`) | **not published, by design** |

"Intended" is doing real work in that table — see F1.

Also: `catalog_and_survey :75-240` creates `DataFolder` + per-data-file assets from **hardcoded
template GUIDs** (`_create_data_file_asset :458-498`) — the side effect the Survey Definition path
deliberately avoids.

#### F1 — Filesystem publish is broken {#f1--filesystem-publish-is-broken}

`egeria_filesystem_surveyor.py:540` reads `ann.egeria_type_name`. **No such attribute exists on any
class in `survey_report.py`**, and the name appears nowhere else in the repo. Every call to
`_build_annotation_props` therefore raises `AttributeError`.

- In `catalog_and_survey`, this is swallowed by the broad `except` at `:220` — but *after* the
  SurveyReport was already created. Result: an empty report in Egeria, no error surfaced.
- In `publish_step_annotations`, the call at `:426` is unguarded, so the entire Survey Definition
  publish fails.

Net effect: **every filesystem analysis in the table above is effectively unpublished.** Static
evidence only — not yet reproduced against a live server. Confirm before fixing.

#### F2 — Filesystem publisher's property mapping has diverged

Independently of F1, even once that is fixed:

- `valueProperties` where repo/DB publishers use `resourceProperties` (`:549` vs `egeria_publisher.py:392`)
- `confidenceLevel` instead of `confidence`
- omits `annotationType`, `jsonProperties`, and `expression` entirely
- **no branch** for CLASSIFICATION, QUALITY_SCORE, DATA_CLASS or REQUEST_FOR_ACTION payloads — so
  `candidate_classifications` and `actionRequested` are silently dropped even though the annotations
  are constructed with them (`:318-325`, `:341-349`)
- RELATIONSHIP missing from `_class_map` (`:529-536`)

---

## 3. Invented, mis-mapped, and duplicated Egeria shapes

- **`annotationType` string mismatch.** `survey_report.py:19` sets `SCHEMA_ANALYSIS = "SchemaAnalysis"`,
  so the string written to Egeria is `"SchemaAnalysis"` while `analysis_catalog.py` and the adapters
  advertise `"SchemaAnalysisAnnotation"`. Same for `REQUEST_FOR_ACTION = "RequestForAction"`.
- **Dependency names in a GUID field.** `egeria_publisher.py:407` writes PyPI/npm package names into
  `candidateDataClassGUIDs`. Not GUIDs — the field is being used as free text.
- **`QualityScoreAnnotation` is RE's own invention.** `egeria_publisher.py:399-402` maps to
  `QualityAnnotationProperties` but emits a `qualityScores` **map**. Egeria's QualityAnnotation is
  `qualityDimension` + a **single** `qualityScore`. Same misuse for SQL complexity metrics
  (`database_surveyor.py:440-447`).
- **No `ResourceProfileAnnotation` / `ResourceProfileLogAnnotation` in RE's enum at all.** Per
  `docs/filesystem-survey-analytics-plan.md:20-26`, Egeria's native filesystem survey emits histograms
  as `ResourceProfileAnnotation` (×4) plus a `ResourceProfileLogAnnotation`. RE re-expresses these as
  `ClassificationAnnotation` + `ResourceMeasureAnnotation` — deliberate and documented, but a genuine
  divergence from the native shape, and it means RE's output is not comparable with Egeria's own
  surveyor output for the same resource.
- **`jsonProperties` is the universal escape hatch.** Column lists, dependency detail,
  `pii_propagations`, sample paths, language breakdowns, GitHub stats — all serialized into a JSON
  string. **None of it is queryable as typed Egeria metadata.** This is the mechanism by which most of
  the D- and R-gaps are "technically published but not usable."
- **Four parallel annotation vocabularies.** (1) `AnnotationType` enum in `survey_report.py:19`;
  (2) `ANNOTATION_TYPES_REGISTRY` `survey_report.py:118-175`; (3) the `annotation_types` SQLite table
  `registry.py:848` (seeded `:857-867`, CRUD at `web/routes/analyses.py:35-105`); (4)
  `surveyors/annotation_registry.json`, which defines `SchemaAnalysis`, `RelationshipLineage`,
  `QualityComplexity`, `DataClassPII`… and which **nothing in the codebase reads** — dead.
- **RFAs are descriptive annotations, not assignable actions.** Nothing assigns or notifies. Open
  backlog item `Backlog.md:53`, with `ToDo`/`create_my_todo` research at `:57` and the unexplored
  `steward`/`stewardTypeName` property pattern at `:59`.

---

## 4. Curation

### 4.1 Existing surfaces

| Area | Location |
|---|---|
| RFA panel | `index.html:300` (nav), `:334` (view), renderer `:2624-2690`; detection at `:1904` |
| RFA generation from missing context | `index.html:3166` — `_CTX_CRITICAL = ['environment','sensitivity','responsible_steward','org_owner']`, field defs `:3185`, warnings `:3229`/`:3254`/`:3284`. Backed by `web/routes/context.py` + `resource_context` (`registry.py:816`). **The only place `steward` appears as a first-class concept — and it is a free-text context field, not an Egeria actor/role.** |
| Annotation-type registry (curatable) | `web/routes/analyses.py:35-105`, table `registry.py:848` |
| Analysis catalog | `resource_explorer/analysis_catalog.py`, exposed at `analyses.py:109` |
| Activity log | `registry.py:791`, `web/routes/activity.py`; `'rfa'` in the operation vocabulary at `registry.py:139` |

### 4.2 In-flight: `feature/egeria-valid-values` (uncommitted, +324/−42, 5 files)

**What it actually does:** moves the PII keyword list out of hardcoded Python *and* out of
`DataClass.dataPatterns`, into **Egeria ValidValue reference data**, and surfaces the active rule set
in the UI. This is a shift toward Egeria as system of record for analysis *configuration*, not just
analysis *results* — a notable direction change that the backlog does not record at all.

- **`surveyors/database/bootstrap_data_classes.py`** (+135/−26). Now a 4-stage bootstrap per data
  class, using `pyegeria.omvs.reference_data.ReferenceDataManager` alongside `DataDesigner`:
  (1) create `DataClass::{name}` if missing — previously `continue`d on existence, now falls through so
  linking still runs on re-bootstrap; (2) create a `ValidValuesSet::{name}Keywords` via
  `create_valid_value_definition` (`dataType: "string"`, `scope: "ResourceExplorer"`); (3) create one
  `ValidValueDefinition::{name}Keyword::{kw}` per keyword with `preferredValue`, and
  `link_valid_value_definition` it into the set; (4) `link_data_class_definition` to attach the set to
  the data class.
  - ⚠ Step 4 is wrapped in a **bare `except` that logs at INFO** ("relationship already exists"), which
    will equally swallow genuine failures — including the stale-GUID case that `Backlog.md:13` tracks.
  - ⚠ Keyword source is still `dc_spec["dataPatterns"]`, so the same list now exists **both** as
    `dataPatterns` on the DataClass **and** as individual ValidValues. Two representations coexist.
- **`surveyors/database/database_surveyor.py:345-379`** — consumer side. Swaps
  `get_data_class_by_guid` + `dataPatterns` parsing for
  `find_valid_value_definitions(search_string="ValidValueDefinition::{dc}Keyword::", starts_with=True)`,
  harvesting `preferredValue or displayName`.
  - Separate **real fix** at `:381-385`: `is_pii_column` now normalizes the *keyword* (stripping `_`/`-`)
    as well as the column name. Previously an Egeria-sourced keyword like `email_address` could never
    match. Latent before; becomes live the moment Egeria supplies underscored keywords — which is
    exactly what the new ValidValues do.
- **`web/routes/egeria.py:164-241`** — new `DataClassRule` model `:164`, `GET /api/egeria/rules/dataclasses`
  `:172`, returning a `source` of `"Egeria (Active)"` or `"Local Fallback"`. Registered *before*
  `/{slug}/status` `:244` so `rules` isn't swallowed by the slug wildcard — deliberate and correct.
- **`web/static/index.html`** — collapsible "🔍 Active Classification Rules (Data Classes)" block on
  the database survey report `:4135-4147`, `toggleActiveRulesBlock()` `:1842-1889`. **Read-only — no
  edit path from the UI back into Egeria's valid values.**
- **`tests/test_web.py`** — new `TestEgeriaRules`. The mock patches
  `pyegeria.omvs.reference_data.ReferenceDataManager`; the route imports the symbol *inside* the
  function body (`egeria.py:181`), so the patch works — but if that import ever moves to module scope,
  the test **silently starts passing against the fallback path instead**.

⚠ **Three copies of the keyword list, already divergent.** `bootstrap_data_classes.STANDARD_DATA_CLASSES`,
`database_surveyor.py:343` (fallback), and `egeria.py:176-183` (route fallback). The route's lists
include variants (`mail_addr`, `tel_num`, `cc_num`) the surveyor fallback lacks.

Also untracked: `tests/test_sql_analyzer.py`, covering the SQLGlot analyzer whose PII propagation feeds
the `DataClassAnnotation` at `database_surveyor.py:508`.

---

## 5. Open decisions (not resolved here)

1. **Which survey path wins?** Path A (Egeria-declared steps) is the stated direction, but Path B owns
   scheduling, history storage, and the credential/override UX. Retiring B means porting S4 and S5
   first. Retiring A means giving up Egeria-authored definitions. A third option — B becomes a thin
   caller of A — is not obviously wrong and has not been costed.
2. **Is the Prefect coercion (`survey_definition_executor.py:154`) a bug or intended?** A global flag
   currently overrides per-step `executes_at`.
3. **Fix F1, or rewrite the filesystem publisher onto the shared `_build_annotation_props`?** Three
   near-duplicate copies exist; F2 shows the copies have already drifted. A one-line F1 fix leaves F2
   standing.
4. **Do we adopt Egeria's native `ResourceProfileAnnotation` shape**, or keep RE's
   `ClassificationAnnotation` + `ResourceMeasureAnnotation` re-expression? Affects comparability with
   Egeria's own surveyor output for the same resource.
5. **What replaces `jsonProperties` as the carrier for D2-class detail?** Column-level schema is the
   biggest gap and the hardest to express in typed annotations.
6. **Collapse the four annotation vocabularies to one** — and decide whether the source of truth is the
   Python enum, the SQLite table, or Egeria itself. The valid-values work above suggests Egeria; that
   would be a consistent and much larger move.
7. **Where does the keyword list live** once the three-copy divergence is resolved — and is a UI edit
   path back into Egeria's valid values in scope?
8. **`egeria-outbox/`** — track, ignore, or relocate.
9. **Should the D5 catalog entries** (`index_health`, `privilege_audit`) and the unbacked
   `api_structure` endpoint claim be implemented, or removed from `analysis_catalog.py`?

---

## 6. Designed but not implemented (from docs)

- `filesystem-survey-analytics-plan.md:3, 73` — §4 item 4 (splitting `filesystem_structure` /
  `filesystem_data_profiling` into two `re_analysis_steps`) was superseded; the adapter still registers
  one step (`filesystem/survey_definition_adapter.py:51`). §5 within-step progress streaming: not done.
  "Profile File Names to External Log" (annotation #8): explicitly not implemented.
- `survey-definitions.md:195-199` — guard-based branching rejected and untested live; the step
  vocabulary is a hardcoded dict, not a catalogable registry.
- `surveyor-reference.md:389` — `RelationshipAnnotation` listed as "(reserved)" for repos; in fact only
  the DB view analyzer produces it.
- `Backlog.md:32` — advanced SQLGlot view analytics, the natural continuation of `sql_analyzer.py`.
- `Backlog.md:53` — RFAs → real Egeria actions; needs its own research pass into `actor_manager.py` /
  `community_matters_omvs.py`.
