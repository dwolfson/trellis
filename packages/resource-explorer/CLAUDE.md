# CLAUDE.md — Resource Explorer

This file provides guidance to Claude Code when working in this repository.

## What this project is

**Resource Explorer** is a tool for discovering, understanding, and cataloging information resources — Git repositories, PostgreSQL databases, file systems, and other data assets — using Egeria as the central metadata catalog and governance platform.

It is the successor to [Project Explorer](https://github.com/LF-AI/project-explorer), extended with:
- Egeria-first architecture: surveys write to Egeria as the catalog of record
- Unified activity log across all resource types
- Intent-based UI (Scouting / Discovery / Assessment / Analysis / Enrichment / Understanding / Curate)
- Persona-aware analysis menu (DBA, data scientist, steward, security)
- RequestForAction lifecycle management for human-provided context
- Temporal analysis: track how resources change over time

**Target users:** Data engineers, data stewards, DBAs, AI engineers, and security practitioners who need to understand and catalog information resources. Egeria is required for the core survey/catalog workflow; RAG-based querying works without it.

**Design reference:** `docs/survey-activity-design.md` — read this before making architectural changes.

## Package name

The Python package is `resource_explorer` (snake_case). The CLI entry point is `resource-explorer`.

All imports use `from resource_explorer.X import Y`. The package was ported from `explorer` in Project Explorer; there should be no remaining `from explorer.` imports anywhere.

## Tech Stack

| Component | Package | Notes |
|---|---|---|
| Agent framework | `beeai-framework[rag]` | `RequirementAgent` with `@tool`-decorated functions |
| Agent runtime | `agentstack-sdk` | A2A server |
| Vector store | `pymilvus` | Multi-tenant via collection namespacing |
| Document parsing | `docling` | PDF, web, DOCX, Markdown |
| Embeddings | `sentence-transformers` | `all-MiniLM-L6-v2`, 384-dim, MPS on Apple Silicon |
| LLM default | `ollama` | Metal GPU on Apple Silicon; pluggable |
| LLM tracing | `openinference-instrumentation-beeai` | → Arize Phoenix at localhost:6006 |
| Experiment tracking | `mlflow` | Background thread, non-blocking |
| CLI | `typer` + `rich` | |
| Web UI | `fastapi` + `uvicorn` + Tailwind + Plotly.js | Single-page HTML frontend |
| TUI | `textual` | Full-screen terminal UI |
| Egeria | `pyegeria` | Survey, catalog, RFA management |
| Database surveying | `psycopg2-binary` | PostgreSQL introspection |

## Setup

```bash
uv sync
uv sync --extra dev --extra phoenix

cp .env.example .env
# Edit .env: set GITHUB_TOKEN, MILVUS_URI, LLM_BACKEND, Egeria connection, etc.
```

External services:
- **Milvus** at `localhost:19530` (or Milvus Lite via `MILVUS__URI=./data/milvus.db`)
- **Ollama** at `localhost:11434` — `ollama pull llama3.1:8b`
- **Egeria** at `EGERIA_PLATFORM_URL` — required for survey/catalog; optional for RAG-only use
- **Arize Phoenix** (optional) — `python -m phoenix.server.main` → `localhost:6006`
- **MLflow** (optional) — `mlflow server --port 5025` → `localhost:5025`

## Seven User Intents

These are the canonical intent labels used throughout the codebase for routing, filtering, and analysis tagging. They appear in the UI's `#intent-nav` primary navigation, the activity log schema, the analysis catalog (`configdata/analysis_catalog.yaml`), and the query router.

Superseded the original four (Scouting/Assessment/Discovery/Enrichment) in the intent-based web UI rewrite — Analysis, Understanding, and Curate were added to give structural/quantitative work, data visualization, and discoverability/reuse-readiness work their own homes instead of being folded into Assessment or a sidebar.

| Intent | What the user is doing | Speed | Output |
|--------|----------------------|-------|--------|
| **Scouting** | Broad inventory across many resources | Fast | Summary view |
| **Discovery** | Find resources by what surveys revealed, launch Egeria Survey Definitions | Fast | Search results / survey launch |
| **Assessment** | Scored evaluation of a specific resource against criteria | Slow / async | Detailed annotations |
| **Analysis** | Structural/quantitative analysis (not scored) — dependencies, profiling, API extraction | Fast–minutes | Structured data |
| **Enrichment** | Provide human context (Context form) — facts about the resource: environment, ownership, sensitivity | Human-paced | Egeria asset properties |
| **Understanding** | Visualize trends over time — charts (stars, commits, schema, etc.) | Fast | Charts |
| **Curate** | Make a resource easier to find and more trustworthy to reuse — search tags, resource-level feedback, curator notes | Human-paced | `resource_tags`/`resource_feedback`/`resource_curator_notes` |

**Enrichment vs. Curate** — easy to conflate, deliberately distinct: Enrichment records *facts about* the resource (a one-time/periodic form); Curate is *ongoing curatorial work* to make the resource discoverable and reusable (tags, feedback, running commentary). Digital-product evaluation, sample-dataset creation, and a dedicated quality-remediation workflow were named as Curate capabilities but are NOT built — each needs its own design pass; see `docs/curate-followups.md`.

**System/catalog configuration is not an intent.** Annotation Types registry, resource Groups, and the Schedules overview are reachable from the header's **⚙ Admin** button (same pattern as 📋 Activity — decoupled from `#intent-nav`/`currentNavIntent`), not from one of the seven intents — they configure how the system behaves, not something a user does to curate a specific resource.

**Scheduling vs. monitoring schedules are two different surfaces on purpose.** Setting/changing a cadence for a specific analysis is per-resource and lives as a "⏱ Schedule" action directly on each analysis card in Assessment/Analysis/Discovery. Admin's Schedules pane is a *global, read-mostly overview* (`GET /api/schedules/`) across every resource — what's scheduled, whether the last run succeeded, drill into errors, remove stale schedules — not a duplicate editor. Both hit the same `schedules.py`/`resource_schedules` backend. The scheduler (`scheduler.py`) writes a real `ActivityEntry` for every run it executes, success or failure, and records the outcome on the schedule row itself (`last_run_status`/`last_run_activity_id`) — this was a real gap before (only logged to Python's own logger, invisible from the UI, violating rule 16 below), not a deliberate omission.

RFA (RequestForAction) is **not** one of the seven intents either — it's a persistent drawer (`#rfa-drawer`, reachable from `#intent-nav` alongside Chat) with local-only defer/reassign/complete response actions, independent of whichever intent tab is active. See `resource_explorer/registry.py`'s `rfa_actions` table docstring for why this is a stepping stone toward real Egeria ToDo actions, not that integration itself.

## Architecture

### Query Flow

```
User Query
  → Intent classification (Scouting / Discovery / Assessment / Analysis / Enrichment / Understanding / Curate)
  → Resource type context (repo / database / filesystem)
  → QueryCache                    ← cache hit → return immediately
  → QueryProcessor                ← classifies sub-intent
      ├── statistical  → StatsAgent (GitHub API + SQLite time-series)
      ├── comparison   → CompareAgent (multi-project RAG + structured diff)
      ├── examples     → ExamplesAgent (generates runnable Python code)
      ├── code_search  → CodeAgent (code collections in Milvus)
      ├── conceptual   → DocAgent (markdown + web docs)
      ├── health       → HealthAgent (community metrics)
      ├── schema       → survey metadata query (databases / file systems)
      └── general      → RAG (CollectionRouter → Milvus → LLM)
  → LLM generation (Ollama or API backend)
  → Response formatting
  → Async: MLflow + Phoenix tracing, metrics write, cache store
```

For **databases and file systems**, RAG searches the survey metadata (schema, annotations, activity log) rather than raw content — unless content has been explicitly ingested.

### Survey Flow

```
SurveyOrchestrator.run(slug, resource_type)
  → [repo]      FileClassifier, FileStructure, FileSizeSurveyor, DataProfiler,
                LanguageSurveyor, HealthSurveyor, DependencySurveyor,
                DocumentationSurveyor, SecuritySurveyor, ApiStructureSurveyor
  → [database]  DatabaseSurveyor (local) and/or EgeriaDatabaseSurveyor (native)
  → SurveyResult (plain dataclasses)
  → ActivityLog entry written (persistent SQLite table)
  → [--publish] EgeriaPublisher → Egeria catalog of record
```

### Activity Log

The activity log is the central audit trail for all operations. Every scout/survey/catalog/publish/RFA operation writes an entry. Schema (D3 in the design doc):

```
ActivityEntry {
  id, ts, operation, intent, entity_type, entity_slug,
  entity_name, entity_location, status, summary, detail,
  items[]:       { kind, display_name, qualified_name, guid, location }
  annotations[]: { analysis_name, annotation_type, count, status, summary }
}
```

The activity log lives in `activity_log` SQLite table. It is the NEW replacement for the in-memory `_activityLog` that existed in Project Explorer's web UI.

### Web UI

`resource_explorer/web/static/index.html` — single-page app, intent-based shell:
- `#intent-nav`: the 7-intent tab strip (Scouting / Discovery / Assessment / Analysis / Enrichment / Understanding / Curate) — the primary navigation axis, replacing the old resource-type-first sidebar tabs
- Left sidebar: a resource-type **facet** (Repos / Databases / File Systems) that filters within whichever intent is active — `resourceTypeFacet` + `setResourceTypeFacet()`, not the primary nav
- Perspective row: concurrent, multi-select persona filter (`dba` / `data_scientist` / `steward` / `security`, data-driven from the analysis catalog) — cross-cutting, not exclusive like intent/facet
- Main panel: content depends on the active intent (survey report, analysis catalog cards, Survey Definitions, context form, charts, or the Curate tags/feedback/notes pane)
- Persistent side surfaces, independent of the intent panel: `#chat-panel` (RAG-backed Q&A, scope-aware) and `#rfa-drawer` (RequestForAction response actions — defer/reassign/complete), both toggleable from `#intent-nav`, both stay open across intent switches
- Header-level, also decoupled from `#intent-nav`: 📋 Activity (persistent log) and ⚙ Admin (Annotation Types / Groups / Schedules — system config, not one of the 7 intents; see the Enrichment-vs-Curate note above)

### Egeria Integration

Egeria is the catalog of record. Survey results are written there via `EgeriaPublisher`. Local SQLite is a cache for fast reads and offline operation.

Key pyegeria patterns:
- `AutomatedCuration.create_postgres_server_element_from_template()` / `create_postgres_database_element_from_template()`
- `initiate_postgres_server_survey()` / `initiate_postgres_database_survey()` — both async
- `AssetMaker` (view_server, platform_url, user_id, user_password) — note arg order
- `find_technology_types()` / `get_tech_type_detail()` — source for the analysis menu

## Module Map

```
resource_explorer/
├── config.py              # Pydantic settings (ExplorerConfig)
├── registry.py            # SQLite registry: projects, databases, db_servers,
│                          # activity_log, project_stats, project_commits,
│                          # project_code_symbols, project_dependencies,
│                          # project_file_type_counts, project_file_inventory,
│                          # project_data_profiles, project_egeria_surveys,
│                          # database_surveys
├── rag_system.py          # Main orchestrator — entry point for all queries
├── query_processor.py     # Intent classifier + agent router
├── collection_router.py   # Selects relevant Milvus collections per query
├── query_cache.py         # LRU cache with optional Redis backend
├── llm_client.py          # LLMBackend protocol + Ollama/OpenAI/Anthropic impls
├── embeddings.py          # SentenceTransformer wrapper (MPS-aware)
├── multi_collection_store.py  # Milvus multi-tenant operations
├── prompt_templates.py    # Per-agent prompt templates
├── agentstack_server.py   # AgentStack A2A server
├── github/                # GitHub API client + stats fetcher
├── ingestion/             # Ingestion pipeline (GitHub repos → Milvus)
├── agents/                # BeeAI RequirementAgent implementations
│   ├── base.py            # BaseExplorerAgent
│   ├── tools.py           # @tool functions
│   └── *.py               # Specialist agents (stats, code, doc, health, compare, examples)
├── cli/
│   └── main.py            # Typer CLI
├── configdata/
│   ├── technology_type_processes.yaml  # Egeria Technology Type -> native process table
│   └── analysis_catalog.yaml           # Analysis menu, tagged by the 7 intents (see analysis_catalog_reader.py)
├── web/
│   ├── app.py             # FastAPI application
│   ├── static/index.html  # Single-page UI — intent-based shell (#intent-nav, 7 intents; see "Seven User Intents" above)
│   └── routes/
│       ├── query.py               # POST /api/query/
│       ├── projects.py            # GET/POST /api/projects/, groups CRUD
│       ├── stats.py                # GET /api/stats/{slug}/charts/{type} — backs Understanding
│       ├── egeria.py               # Egeria survey + annotation + catalog-elements + whoami routes
│       ├── databases.py            # Database management routes
│       ├── db_servers.py           # DB server management routes
│       ├── analyses.py             # GET /api/analyses/{resource_type} + /perspectives + /egeria-status — backs Assessment/Analysis
│       ├── activity.py             # Activity log + GET/PATCH /api/activity/rfas — backs the RFA drawer
│       ├── context.py              # GET/POST /api/context/{type}/{slug} — backs Enrichment
│       ├── curate.py               # Tags/feedback/curator-notes CRUD — backs Curate
│       ├── schedules.py            # Analysis schedule CRUD + GET /api/schedules/ (global) — backs the per-card ⏱ Schedule action and Admin's Schedules monitoring overview
│       └── survey_definitions.py   # Egeria Survey Definition candidates/run — backs Discovery
├── tui/app.py             # Textual TUI
├── dashboard/graphs.py    # Plotly figure builders
├── surveyors/             # Survey framework
│   ├── survey_report.py
│   ├── base_surveyor.py
│   ├── survey_orchestrator.py
│   ├── egeria_publisher.py
│   ├── egeria_reader.py
│   ├── egeria_tech_type_catalog.py    # EgeriaTechTypeCatalog — live Technology Type queries
│   ├── technology_type_processes.py   # Reader for configdata/technology_type_processes.yaml
│   ├── analysis_catalog_reader.py     # Reader for configdata/analysis_catalog.yaml + optional live-Egeria merge
│   ├── survey_definition_reader.py    # Generic Survey Definition (GovernanceActionProcess) reader
│   ├── survey_definition_executor.py  # Generic dispatch loop + ResourceTypeAdapter interface
│   ├── repo_survey_definition_adapter.py  # re_analysis_step -> repo sub-surveyor mapping
│   ├── file_classifier/   # File type classification
│   ├── sub_surveyors/     # Repo sub-surveyors (language, health, security, etc.)
│   ├── database/          # PostgreSQL surveying
│   │   ├── connection.py
│   │   ├── database_surveyor.py
│   │   ├── egeria_database_surveyor.py
│   │   ├── hybrid_database_surveyor.py
│   │   └── survey_definition_adapter.py
│   └── filesystem/        # Filesystem surveying
│       ├── local_filesystem_surveyor.py
│       ├── egeria_filesystem_surveyor.py
│       ├── hybrid_filesystem_surveyor.py
│       └── survey_definition_adapter.py
└── observability/         # MLflow, Phoenix, metrics
```

## What's New vs. Project Explorer

| Area | Project Explorer | Resource Explorer |
|------|-----------------|-------------------|
| Activity log | In-memory, lost on reload | Persistent SQLite `activity_log` table |
| Survey source display | Not differentiated | ☁ Egeria / 🏠 Local / ⏳ Pending per value |
| UI shell | Project-centric sidebar | Resource-type sidebar + intent tab strip |
| Analysis menu | Fixed survey actions | Unified menu (Egeria + local) with intent/persona filters |
| RFA management | Created but not tracked | Full lifecycle: create → assign → respond → close |
| Temporal tracking | Single snapshot | History of runs; "vs. last run" diffs |
| Package name | `explorer` | `resource_explorer` |
| CLI command | `project-explorer` | `resource-explorer` |

## Key Design Rules (inherited from Project Explorer + new)

1. Classify intent before touching the vector store — statistical queries never hit Milvus
2. Min retrieval score = 0.30 — below this, say "I don't have enough information"
3. Query cache is the highest-ROI latency win — implement before optimizing retrieval
4. Observability (MLflow, Phoenix) runs in background threads — never block the response
5. Incremental indexing for repos — commit-diff based
6. Chunk size is content-specific — code ≠ prose ≠ examples
7. Use single-quoted YAML strings for regex patterns containing backslashes
8. A2A `Server` supports exactly one agent per instance
9. Milvus `VARCHAR` `max_length` is a UTF-8 byte limit — truncate via `encoded[:max_bytes].decode('utf-8', errors='ignore')`
10. BeeAI `FunctionTool` objects have no `.func` attribute — use `_raw()` helpers for fallback calls
11. `AssetMaker` constructor: `(view_server, platform_url, user_id, user_password)` — view_server first
12. `EgeriaPublisher` annotation class names: `RequestForActionProperties` (no "Annotation" suffix), `QualityAnnotationProperties` (not "QualityScore")
13. `pg_description` requires schema-qualified `(schema.table)::regclass` form for `obj_description()` and `col_description()`
14. `server_connection()` in `connection.py` connects to the `postgres` system DB for listing databases
15. `HybridDatabaseSurveyor` must run the local scan immediately after triggering the Egeria native survey — Egeria surveys are async and produce no immediate schema data
16. Activity log entries must be written for ALL operations — scouting, survey, catalog, publish, RFA — not just for Egeria publishes
17. The seven intent labels are canonical: `scouting`, `discovery`, `assessment`, `analysis`, `enrichment`, `understanding`, `curate` — use these exact strings in the activity log schema, UI filters, and analysis catalog tags. `discovery` and `enrichment` intentionally have zero entries in the analysis catalog (Discovery is served by `survey_definitions.py`, Enrichment by `context.py`) — that's by design, not a gap.

## Testing

```bash
uv run pytest tests/ -v
uv run pytest --cov=resource_explorer --cov-report=html
```

## Code Style

```bash
uv run black resource_explorer/
uv run ruff check resource_explorer/
uv run mypy resource_explorer/
```
