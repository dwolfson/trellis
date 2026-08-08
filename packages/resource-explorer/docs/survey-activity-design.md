# Survey, Activity, and Annotation Architecture — Design Document

**Status:** In revision — second round of comments incorporated  
**Authors:** Dan Wolfson, Claude  
**Date:** 2026-06-09  
**Scope:** Unified activity log, survey source clarity, tiered annotation framework, Egeria technology-type integration, project scope and naming

---

## Strategic Decision: Project Split

The work described in this document has grown beyond the original Project Explorer scope. Project Explorer was designed as a general-purpose, multi-agent RAG system for exploring GitHub repositories — useful to technical users who may have no interest in Egeria.

The Egeria-focused survey and annotation capabilities being designed here represent a distinct product with a different target user, different primary data model, and different design constraints. Continuing to build both inside the same repository risks constraining the new work to design decisions that were correct for the old use case but are wrong for the new one.

**Proposal:** Keep Project Explorer as-is (it has independent value for non-Egeria users) and create a new repository for the Egeria-focused tool. The working name is **Egeria Resource Explorer** — reflecting the focus on exploring and understanding information resources through the lens of Egeria's metadata catalog. Code that is clearly general-purpose (embeddings, LLM client, RAG infrastructure) can be shared or extracted into a common library over time.

**This document is written as a design foundation for the new Egeria Resource Explorer project.**

**Working name:** "Resource Explorer" — a shorter form that implies the broader scope (databases, file systems, Git repos) without tying the name to a single platform. Can be changed before launch if a better name emerges.

**Migration approach:** Resource Explorer is a superset, not a fork. The underlying surveying code, Egeria integration modules, FastAPI routes, and RAG infrastructure all transfer with little or no change. The main new work is the UI shell — the activity log, analysis menu, and survey source display require a rethink of the frontend information architecture. Incremental porting: move modules one at a time, replace the UI shell last, and keep Project Explorer functional throughout.

---

## Background and Motivation

### What the tool is trying to do

Egeria Resource Explorer is a tool for discovering, understanding, and cataloging information resources — databases, file systems, Git repositories, and other data assets — using Egeria as the central metadata catalog and governance platform. It is not primarily an AI chat interface (that is Project Explorer's identity); it is a scouting, surveying, and context-gathering tool that produces structured metadata.

Four distinct user intents drive the design. The names below are the canonical intent labels used throughout this document for routing, filtering, and analysis tagging — modeled after the intent classification pattern in egeria-advisor (where `LIVE_DATA`, `CODE_HELP`, `CONCEPT`, `WRITE_COMMAND` route queries to different handlers).

> **Update (intent-shell rewrite):** the web UI now implements **seven** intents, not four — Scouting/Assessment/Discovery/Enrichment below plus **Analysis** (structural/quantitative work split out of Assessment — dependency scans, data profiling, API extraction: real work, but not a *scored evaluation* the way Assessment is), **Understanding** (chart-based trend visualization, previously a sidebar fixture with no intent of its own), and **Curate** (catalog maintenance — annotation type registry, resource groups, analysis schedules). The four intents' original rationale below is still valid for what it covers; treat this as an addition, not a correction. See `CLAUDE.md`'s "Seven User Intents" table for the canonical current list, and `resource_explorer/configdata/analysis_catalog.yaml`'s header comment for the reclassification this drove in the analysis catalog.

**Scouting** is about breadth. Given a newly-discovered server or file system, a data engineer or DevOps practitioner wants to quickly understand what's there: how many databases, how many rows, who manages it, when it was last updated, is it actively used or a candidate for decommissioning? Scouting works across many resources at once and delivers results fast. The output is a broad inventory, not deep analysis.

**Assessment** is about depth, applied selectively. After scouting identifies something worth understanding, a data steward, data scientist, AI engineer, or security specialist runs assessments to understand the risks, quality, completeness, and lineage of a specific resource. Assessments can be shallow or deep, broad or focused (security-only, quality-only, lineage-only), and are often run incrementally — first a quick Egeria native survey to see what annotations it produces, then targeted custom analyses to answer specific questions. Assessments are also temporal: running the same analysis repeatedly and tracking how things change over time is as valuable as the initial result.

**Discovery** is about retrieval. Business users, data scientists, and AI engineers want to find data relevant to their needs. They search and filter by what assessments have revealed: "find all databases with a SecurityRFA," "find all tables with >1M rows and a data quality annotation." Discovery is the payoff for all the scouting and assessment work — the catalog becomes useful only when it can be searched by what it knows.

**Enrichment** is not automated at all. Many critical facts about a resource cannot be derived from scanning: Is this database in a production system or a research sandbox? Who is the responsible DBA? What organization owns it? Where is it geographically located? Is it backed up? Egeria's `RequestForAction` annotation is the right primitive here — a structured prompt for a human to supply a specific piece of information, tracked until answered and then promoted into the catalog as permanent metadata. This requires a UI for managing open RFAs, assigning them to people, recording answers, and closing them.

Intent and persona are cross-cutting in the analysis menu (D4): a DBA performing an Assessment sees different recommended analyses than a data scientist performing Discovery. Persona is distinct from intent — a persona (DBA, data scientist, steward, security engineer) represents who the user is; intent represents what they are trying to accomplish right now. In the current UI, persona ("perspective") is multi-select/concurrent (you can hold more than one at once) while intent is exclusive-select — see `resource_explorer/surveyors/analysis_catalog_reader.py`'s `list_perspectives()`.


### What we are currently doing (and the problems)

Project Explorer currently supports Git repository surveys and PostgreSQL database surveys. Three structural problems have emerged:

1. **The activity log is shallow and ephemeral.** In-memory only, lost on page reload, coarse summaries rather than structured Egeria output.

2. **Survey panels do not distinguish data sources.** Local Python/SQL scan results and Egeria native annotation results look identical in the UI.

3. **"Survey" conflates two different activities.** Structural inventory (fast, always available, tells you what exists) and governance assessment (slower, on-demand, tells you what it means) are treated as one operation.

---

## Core Design Decisions

### D1 — Organize by Analysis and Intent, Not by Source [Revised]

The original framing split annotations by *who runs them* (our code vs. Egeria vs. third-party tools). This is the wrong axis. The same row count result means the same thing regardless of whether it came from a local `pg_stat_user_tables` query or an Egeria native survey. Results from multiple sources should be merged, not kept in separate silos.

The right axes are **what analysis was done** and **what intent drove it**.

**Analysis** is the unit of work: a specific examination of a specific resource that produces a specific set of annotations. An analysis has a name, a description, a list of annotation types it produces, and optionally a source (Egeria governance action, local SQL, external tool). The same analysis may be available from multiple sources — when that happens, we prefer Egeria's result but show the local result when Egeria is unavailable.

**Intent** is the reason the analysis was run. Seven intents in the current implementation (see the Background section's update note) — the original four, plus Analysis/Understanding/Curate:
- **Scouting** — broad, fast, run across many resources at once; produces a summary view
- **Discovery** — produces annotations structured to support search and retrieval; launches Egeria Survey Definitions
- **Assessment** — deep, targeted, run on specific resources; scored evaluation against criteria; produces detailed annotations
- **Analysis** — structural/quantitative work on a specific resource (dependencies, data profiling, API extraction) — not a scored evaluation, so kept distinct from Assessment
- **Enrichment** — captures human-provided context via the Context form; writes it to Egeria as structured properties
- **Understanding** — chart-based visualization of trends over time (stars, commits, schema, table sizes, etc.)
- **Curate** — catalog maintenance: annotation type registry, resource groups, analysis schedules

RFA (RequestForAction) response handling — assigning, deferring, completing — is **not** one of the seven; it's a persistent drawer independent of the active intent (see D5-equivalent in the current UI, `#rfa-drawer` in `index.html`).

**In almost all cases, analysis results should be stored in Egeria**, even when the analysis itself was run locally. Egeria is the catalog of record. Local SQLite is a cache and queue — useful for offline work and fast reads, but not the authoritative store.

**Change over time is a first-class concern.** The same analysis run at regular intervals produces a time series. Row count trends, schema drift, security posture changes — these are as important as the initial snapshot. Design the annotation store and activity log from the start to support temporal queries. A scheduler (likely Airflow in production deployments) is a future component that will drive regular-cadence runs.

---

### D2 — Activity Log Persistence [Proposed]

Persist the activity log to a database so history survives page reloads and sessions. All operations — scouting runs, survey triggers, catalog operations, RFA creation — write to this log.

SQLite is acceptable for the initial implementation. The long-term home is PostgreSQL: the primary data sources being surveyed are often Postgres instances, and consolidating app storage there as well simplifies deployment. Migration path: SQLite → Postgres via Alembic or a direct schema port; keep the API layer stable so the frontend doesn't change.

Retention policy: configurable via `.env` (default: keep indefinitely up to a row limit, e.g., 10,000 entries).

---

### D3 — Unified Activity Item Schema [Revised]

Every operation that touches a resource produces one or more activity items. The schema covers all resource types uniformly:

```
ActivityEntry {
  id:              uuid
  ts:              ISO timestamp
  operation:       'scout' | 'survey' | 'catalog' | 'publish' | 'discover' | 'rfa' | 'refresh'
  intent:          'scouting' | 'discovery' | 'assessment' | 'analysis' | 'enrichment' | 'understanding' | 'curate'
  entity_type:     'repo' | 'database' | 'server' | 'filesystem' | 'file'
  entity_slug:     internal slug
  entity_name:     display name
  entity_location: URL, server:port, file path, etc.
  status:          'running' | 'ok' | 'error' | 'pending'
  summary:         one-line result
  detail:          longer text, error message, etc.

  items: [          # cataloged Egeria objects created/updated
    {
      kind:           Egeria open type name (e.g. "PostgreSQLServer", "SurveyReport")
      display_name:   human-readable name
      qualified_name: Egeria qualifiedName
      guid:           Egeria element GUID
      location:       URL / connection string / path
    }
  ]

  annotations: [    # analysis results produced
    {
      analysis_name:    name of the analysis that was run
      annotation_type:  Egeria annotation subtype
      count:            number of annotations of this type
      status:           'local' | 'in-egeria' | 'pending-egeria'
      summary:          brief description of findings
    }
  ]
}
```

---

### D4 — Survey and Analysis Menu [Revised]

Both Egeria-provided surveys and our own local analyses should be organized and presented in the same way. The user sees a unified menu of "available analyses" for a given resource, regardless of where the analysis logic lives. Each entry shows:

- Name and description
- What annotation types it produces
- Typical run time (fast / minutes / async)
- Last run date and result count (if previously run)
- Recommended badge for high-value analyses by persona

Egeria's `AutomatedCuration.find_technology_types()` and `get_tech_type_detail()` are the source for Egeria-provided analyses. Our own analyses are registered in a local catalog using the same schema. When Egeria and our own tool can both run the same analysis (e.g., row counts), we show one entry with a note about the source preference.

The menu should support:
- **Filtering by intent** — scouting / discovery / assessment / analysis / enrichment / understanding / curate
- **Filtering by persona** — DBA (performance, security, index health), data scientist (quality, profiling, growth), steward (lineage, classification, RFA status), security (privilege audit, sensitive data)
- **Search** across analysis names and descriptions
- **"Run all scouting analyses"** as a single action — the primary entry point for new resources

Separate catalog and survey actions: cataloging (registering an asset in Egeria) happens once; surveys can be run many times with different intents. These should be distinct UI actions.

**Resolved:** `get_tech_type_detail()`'s real shape was prototyped and is now wrapped by `EgeriaTechTypeCatalog.get_produced_annotation_types()` (`resource_explorer/surveyors/egeria_tech_type_catalog.py`), which deduplicates `producedAnnotationType` entries out of `resourceList`/`governanceActionProcesses`. It's consumed by both `survey_definitions.py` (Discovery) and `analysis_catalog_reader.py`'s live-Egeria merge (Assessment/Analysis) — fail-soft, so Egeria being unreachable falls back to the local catalog rather than blocking the menu.

---

### D5 — Async Survey Result Retrieval [Proposed]

Egeria native surveys are asynchronous. We receive a `survey_action_guid` when the survey is triggered; annotations appear later. Egeria has a notification framework but no webhook capability today.

**Approach for now:** Polling. Each pending activity log entry shows a "Check for results" button; the UI also polls automatically every 30 seconds for any entries with `status='pending'` when the Activity panel is open.

**To investigate:** Egeria's notification/event framework and whether it can be used to push completion events to us without polling.

---

### D6 — Analysis Catalog and Context Gathering [Revised]

The set of analyses available for a resource type is organized at two levels:

**Level 1 — Analysis catalog:** A registry of all analyses available for a given resource type, each with a name, description, intent tags, persona tags, annotation types produced, and implementation (Egeria governance action name, or local Python/SQL module). Generic analyses work across all RDBMS; database-specific analyses (e.g., PostgreSQL system table queries) are tagged to their technology type.

Example analyses for PostgreSQL databases:

| Analysis | Intent | Persona | Source | Annotations produced |
|----------|--------|---------|--------|----------------------|
| Schema inventory | Scouting | All | Local / Egeria | SchemaAnalysis, ResourceMeasure |
| Row count snapshot | Scouting | All | Local / Egeria | ResourceMeasure |
| Index health | Assessment | DBA | Local SQL | RequestForAction, DataClass |
| Table growth rate | Assessment | DBA, data scientist | Local SQL | ResourceMeasure (time series) |
| Privilege audit | Assessment | Security | Local SQL | DataClass, RequestForAction |
| Data profiling | Assessment | Data scientist | Egeria | SchemaAnalysis, DataClass |
| Sensitive data classification | Discovery | Steward, security | Egeria | Classification, RequestForAction |
| Constraint coverage | Assessment | DBA, steward | Local SQL | RequestForAction |
| Environment / ownership form | Enrichment | Steward | UI form | (writes to Egeria asset properties) |

**Level 2 — Questions and perspectives:** Different personas have different questions they want answered. Egeria supports the concept of perspectives and associated questions. We should align our analysis catalog with these so that "run all DBA assessment analyses" maps to a specific, documented set of analyses with a known set of output annotation types.

**Context gathering — forms and questionnaires:** Some critical metadata cannot be derived by scanning. Environment (production vs. sandbox), organizational ownership, geographic location, responsible steward, backup status, sensitivity classification — these require human input. We need:
- Structured forms for common context questions, tailored by resource type
- Free-form fields for notes
- Integration with Egeria's `RequestForAction` annotations as the tracking mechanism
- A UI panel for open RFAs: view all open questions across all resources, assign to people, record answers, close when resolved

**Advanced Egeria concepts to leverage:**
- **DataScope** — bounds the data in space (geographic bounding box) and time (collection start/end). Relevant for assets that represent subsets of a larger dataset.
- **DataLens** — defines the scope of data for a project, team, or business capability. DataScope on an asset can be matched against a DataLens to determine relevance.
- **DataGrain** — captures the granularity of data (e.g., daily snapshots, per-transaction). Important for time-series data and for understanding how to aggregate or join datasets.

These should be surfaceable in the context-gathering forms and in the survey report display.

References:
- egeria-advisor intent/routing patterns: `/Users/dwolfson/localGit/egeria-v6/egeria-advisor/advisor/llm_intent_classifier.py`, `query_processor.py`
- https://egeria-project.org/concepts/data-lens
- https://egeria-project.org/types/6/0626-Data-Grain-Discovery

---

### D7 — Resource Types: Scope and Priority [Decided]

The framework must be generic across resource types from the start. Resource-type-specific logic lives in pluggable modules; the activity log, analysis catalog, and UI shell are shared.

**Priority order:**
1. PostgreSQL databases *(current, partially implemented)*
2. File systems and files *(next — structurally similar to Git repo surveys)*
3. Git repositories *(current, to be brought into the new architecture)*
4. Other RDBMS (MySQL, SQLite, DuckDB) *(medium term)*
5. Object storage (S3, GCS, Azure Blob) *(medium term)*
6. Streaming (Kafka topics) *(longer term)*
7. REST APIs, GraphQL endpoints *(longer term)*

---

### D8 — RequestForAction Lifecycle [New]

RFAs are currently created by surveyors but have no management UI. They represent open questions that require human answers to complete the catalog. A complete RFA workflow:

1. **Creation** — any analysis or context-gathering form can create an RFA with a specific question, the resource it relates to, and the persona best suited to answer it
2. **Assignment** — RFAs can be assigned to a named person or role
3. **Response** — the assignee provides an answer through the UI; the answer is written back to Egeria as a structured metadata property on the asset
4. **Closure** — the RFA is marked resolved; the answer becomes part of the permanent catalog record
5. **Escalation** — overdue RFAs are surfaced in a "pending context" view

The RFA panel is a cross-resource view: all open questions across all surveyed resources, filterable by persona, resource type, age, and assignee.

---

### D9 — Temporal Analysis and Scheduling [New]

Running the same analysis repeatedly and comparing results over time is as important as the initial snapshot. The activity log and annotation store must support this from the start.

**Near-term:** Each survey run is stored with a timestamp; the UI can show a history of runs and highlight changes (schema columns added/removed, row count change, new RFAs opened). A simple "changes since last run" diff view is the minimum.

**Medium-term:** User-configurable schedules for specific analyses on specific resources (e.g., "run row count snapshot on this database daily"). Stored as schedule records in the database, executed by a background thread or task queue.

**Long-term:** Integration with Airflow or another scheduler for production-grade cadence management. Survey results fed into a time-series store for trending and anomaly detection.

---

### D10 — App Storage Migration Path [New]

Current app storage: SQLite (`registry.db`). This is appropriate for a single-developer tool but will become a constraint as the tool is used by teams.

Migration path: SQLite → PostgreSQL. The registry, activity log, analysis results, and RFA store all move. Key considerations:
- Keep the registry abstraction layer (`ProjectRegistry` class) as the migration boundary — no direct SQLite calls outside the registry
- Alembic for schema migrations
- Connection pooling (asyncpg or psycopg3) for the async FastAPI routes
- SQLite remains available for local/offline deployments via a config flag

---

## Implementation Phases

### Phase 0 — Project Foundation

**Scope:** Establish the new Egeria Resource Explorer project.

**Tasks:**
- Create new GitHub repository under the LF AI org (or personal for now)
- Define the project structure, tech stack, and packaging (`pyproject.toml`, `uv`)
- Port the database surveying code (the most mature new capability) as the first module
- Port the web UI shell (FastAPI + index.html) with a clean separation from the RAG/chat infrastructure
- Set up the shared resource type abstraction so PostgreSQL is the first implementation of a generic interface
- Decide on SQLite vs. PostgreSQL for the new project's own storage

**Deferred to the new project:** All phases below. Project Explorer continues to receive maintenance but new Egeria-focused features go into the new repo.

**Open for discussion:** Timing — should we finish the current iteration of Project Explorer's database surveying (activity log, source clarity) before splitting, or split now and carry the work forward in the new repo?

---

### Phase 1 — Survey Source Clarity

**Goal:** Users always know where data in a survey panel came from.

**What this means in practice:**
- Every value in the survey panel carries a source indicator: `☁` for Egeria annotations, `🏠` for local scan, `⏳` for pending async result
- Section headers clearly label the analysis that produced them (e.g., "Schema inventory — local scan, 2026-06-09 14:32")
- Egeria annotations and local scan results are shown in separate sections, not intermixed
- Pending Egeria results show a placeholder with the survey action GUID and a "Check for results" button

**Effort:** Small — primarily frontend

---

### Phase 2 — Persistent Unified Activity Log

**Goal:** All operations across all resource types are recorded in a persistent, structured log accessible after page reload and filterable by intent, resource type, and status.

**Schema:** As defined in D3 above.

**Key behaviors:**
- Every scout/survey/catalog/publish/RFA operation writes an entry
- Pending Egeria surveys show in the log with status `pending`; polling updates them
- Repo publishes and database catalogs use the same entry structure
- Filter by entity type (All / Repos / Databases / Files), intent (Scouting / Discovery / Assessment / Analysis / Enrichment / Understanding / Curate), and status
- Retroactively populate from `project_egeria_surveys` and `database_surveys` on first run

**Effort:** Medium

---

### Phase 3 — Annotation Detail and RFA Panel

**Goal:** The activity log and survey panels show full annotation detail; open RFAs are manageable.

**Activity log:** Each entry expands to show the items table (D3 schema) and a per-annotation-type breakdown with counts, summaries, and GUIDs. For Egeria surveys, this is fetched from Egeria once available. For local scans, this is populated immediately from the survey result.

**RFA panel:** A cross-resource view of all open RequestForAction annotations. Sortable by resource, age, persona, and assigned person. Inline form to record an answer; answer written back to Egeria on submit.

> **Status:** built as a persistent `#rfa-drawer` (reachable from anywhere, not a per-resource tab) with real defer/reassign/complete/reopen response actions — see `rfa_actions` table and `PATCH /api/activity/rfas/{rfa_id}`. **Not yet accurate to this doc's original phrasing:** response actions and the free-text "record answer" form are both local-only right now (SQLite `rfa_actions` table / activity log), not written back to Egeria as `RequestForActionProperties` updates or native `ToDo` actions — that write-back is a real, tracked follow-up, not this doc's original design realized. Don't assume "answered" or "completed" here means Egeria's own record changed.

**Effort:** Medium

---

### Phase 4 — Analysis Catalog and Survey Menu

**Goal:** Users see a unified, organized menu of available analyses for any resource, drawn from both Egeria and our own analysis catalog.

**Prerequisites:**
- ~~Prototype `find_technology_types` and `get_tech_type_detail` against the live Egeria instance and document what they return~~ — done, see D1's "Resolved" note above and `egeria_tech_type_catalog.py`
- ~~Define the local analysis catalog schema (mirrors the Egeria output format)~~ — done, `configdata/analysis_catalog.yaml` + `analysis_catalog_reader.py`

**What ships:**
- Analysis menu per resource with intent and persona filters
- "Run all scouting analyses" as a one-click entry point
- Catalog and survey as separate actions (catalog once; survey many times)
- Survey history with change highlights vs. prior run

**Effort:** Medium-large

---

### Phase 5 — Context Gathering and Forms

**Goal:** Structured collection of human-provided metadata; RFA creation from forms; answers written to Egeria.

**What ships:**
- Per-resource context forms: environment, owner, location, steward, sensitivity, DataScope fields, DataGrain fields
- Free-form notes field
- Auto-creation of RFAs for unanswered fields
- Form answers written to Egeria as asset properties
- DataLens matching: show which DataLenses this resource's DataScope overlaps

**Effort:** Large

---

### Phase 6 — Temporal Analysis and Scheduling

**Goal:** Track how resources change over time; schedule recurring analyses.

**What ships:**
- Change summary in survey panel: "vs. last run — 3 new columns, row count +12%"
- Per-resource analysis schedule configuration
- Background scheduler (thread-based initially, Airflow integration later)
- Time-series chart for key metrics (row counts, schema changes, annotation counts) in the survey panel

**Effort:** Large

---

## Open Questions

| # | Question | Status |
|---|----------|--------|
| Q1 | What does `get_tech_type_detail("PostgreSQL Server")` return from our Egeria instance? | Open — needs live API call |
| Q2 | Typical completion time for an Egeria PostgreSQL database survey? | Open — needs observation |
| Q3 | Does Egeria's notification framework support survey completion events? | Open — needs investigation |
| Q4 | Are qualified names returned by `create_postgres_*_element_from_template()` or fetched separately? | Open — needs pyegeria test |
| Q5 | What annotation types does the Egeria PostgreSQL survey produce for our schema? | Open — needs live test |
| Q6 | New repo: personal or LF AI org? Separate package or monorepo with Project Explorer? | Open — strategic decision |
| Q7 | Should the new project's own storage be SQLite (simpler) or PostgreSQL from day one? | Open |
| Q8 | Which Egeria DataLens, DataScope, DataGrain APIs are available in current pyegeria? | Open — needs pyegeria review |

---

## Explicitly Out of Scope (for this document)

- Changes to Project Explorer's RAG pipeline, pgvector store, or chat interface
- Multi-user authentication and per-user access control
- Real-time collaborative annotation
- TUI for the new tool (web UI first)
- Non-PostgreSQL RDBMS support in the initial implementation
- Airflow integration (scheduled analyses use a simpler background thread initially)

---

*Last revised: 2026-06-09. Update status field when moving from design to implementation.*
