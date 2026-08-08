# Resource Explorer — Architecture

**Last revised:** 2026-06-10

---

## Overview

Resource Explorer is an Egeria-first tool for discovering, assessing, and cataloging information resources. Its primary data model is Egeria's open metadata — every survey result that can be written to Egeria should be. Local SQLite is a cache and queue for offline work and fast reads.

The system has two layers:
1. **Survey layer** — ingests structure and metadata from resources (repos, databases, file systems) and writes to SQLite + Egeria
2. **Query layer** — answers natural-language questions using survey metadata, RAG (pgvector), and specialized agents

---

## Module Map

```
resource_explorer/
├── config.py                  # Pydantic settings (ExplorerConfig)
├── registry.py                # Registry — all tables, all read/write methods (Postgres by default, SQLite fallback)
├── activity_logger.py         # Thin helpers for writing activity log entries
├── analysis_catalog.py        # Local analysis registry (intent/persona/source tags)
├── scheduler.py               # Background daemon thread — executes due analyses
│
├── rag_system.py              # Main query orchestrator
├── query_processor.py         # Intent classifier (routing.yaml) + agent router
├── collection_router.py       # Selects relevant pgvector collections per query
├── query_cache.py             # LRU cache with optional Redis backend
├── llm_client.py              # LLMBackend protocol + Ollama/OpenAI/Anthropic impls
├── embeddings.py              # SentenceTransformer wrapper (MPS-aware)
├── vector_store_base.py       # BaseVectorStore ABC
├── vector_store_pg.py         # PgVectorStore + MultiCollectionStore (pgvector multi-tenant operations)
├── prompt_templates.py        # Per-agent prompt templates
├── agentstack_server.py       # AgentStack A2A server
│
├── github/                    # GitHub API client + stats fetcher
│
├── ingestion/                 # Ingestion pipeline (GitHub repos → pgvector)
│   ├── pipeline.py            # IngestionPipeline — downloads, chunks, indexes
│   └── incremental.py        # IncrementalIndexer — commit-diff based re-index
│
├── agents/                    # BeeAI RequirementAgent implementations
│   ├── base.py                # BaseExplorerAgent
│   ├── tools.py               # @tool decorated functions
│   └── *.py                   # stats, code, doc, health, compare, examples agents
│
├── cli/main.py                # Typer CLI entry point
│
├── web/
│   ├── app.py                 # FastAPI application + lifespan (starts scheduler)
│   ├── static/index.html      # Single-page UI
│   └── routes/
│       ├── activity.py        # GET /api/activity/ — activity log + RFAs
│       ├── analyses.py        # GET /api/analyses/{resource_type}
│       ├── context.py         # GET/POST /api/context/{entity_type}/{slug}
│       ├── databases.py       # CRUD + survey + diff for databases
│       ├── db_servers.py      # DB server management
│       ├── egeria.py          # Egeria survey, catalog, annotation, diff routes
│       ├── projects.py        # CRUD + refresh for repos
│       ├── query.py           # POST /api/query/
│       ├── schedules.py       # GET/POST /api/schedules/{entity_type}/{slug}
│       ├── stats.py           # Charts and survey history endpoints
│       └── webhook.py         # GitHub webhook handler
│
├── tui/app.py                 # Textual TUI
├── dashboard/graphs.py        # Plotly figure builders
│
├── surveyors/
│   ├── survey_report.py       # SurveyReport, Annotation dataclasses
│   ├── base_surveyor.py       # BaseSurveyor protocol
│   ├── survey_orchestrator.py # Runs all sub-surveyors; writes activity log
│   ├── egeria_publisher.py    # Writes survey results to Egeria
│   ├── egeria_reader.py       # Reads survey results back from Egeria
│   ├── file_classifier/       # File type classification
│   ├── sub_surveyors/         # Language, health, security, dependency, …
│   └── database/
│       ├── connection.py               # psycopg2 connection helpers
│       ├── database_surveyor.py        # Local PostgreSQL introspection
│       ├── egeria_database_surveyor.py # Triggers Egeria native survey
│       └── hybrid_database_surveyor.py # Runs both; local scan for immediate data
│
└── observability/             # MLflow, Phoenix, metrics
```

---

## SQLite Tables

All persistent state lives in a single SQLite file (default `~/.resource-explorer/registry.db`).

| Table | Purpose |
|-------|---------|
| `projects` | Registered Git repositories |
| `databases` | Registered PostgreSQL databases |
| `db_servers` | Database server connection info |
| `activity_log` | Audit trail — every operation writes an entry |
| `project_stats` | GitHub API stats snapshots |
| `project_commits` | Commit history |
| `project_file_type_counts` | File type breakdown per survey run (multiple rows per slug, timestamped) |
| `project_file_inventory` | Full file path list |
| `project_data_profiles` | Data file column/row profiles |
| `project_code_symbols` | Extracted class/function symbols |
| `project_dependencies` | Parsed dependencies |
| `project_egeria_surveys` | Egeria survey job tracking |
| `database_surveys` | Database survey snapshots (multiple rows per slug, timestamped) |
| `resource_context` | Human-provided context (environment, owner, sensitivity, …) |
| `resource_schedules` | Per-resource analysis schedule configuration |

---

## Query Flow

```
User query (Web / CLI / A2A)
  → QueryCache                       cache hit → return immediately
  → QueryProcessor.classify()        intent classification via config/routing.yaml
      ├── survey_meta  → SurveyMetaAgent  (activity log, RFAs, schedules, context)
      ├── statistical  → StatsAgent
      ├── comparison   → CompareAgent
      ├── examples     → ExamplesAgent
      ├── code_search  → CodeAgent
      ├── conceptual   → DocAgent
      ├── health       → HealthAgent
      └── general      → RAG (CollectionRouter → pgvector → LLM)
  → LLM generation (Ollama / OpenAI / Anthropic)
  → Response
  → Async: MLflow + Phoenix tracing, cache store
```

`survey_meta` is evaluated first. It handles questions about when a resource was last surveyed, what analyses are scheduled, what RFAs are open, or what the resource context contains — all answered from the registry without hitting pgvector.

For database and file-system resources, RAG searches survey metadata stored in pgvector (schema, annotations) rather than raw content — unless content has been explicitly ingested.

---

## Survey Flow

A survey is a collection of analyses. Each analysis produces zero or more annotations. The survey report is all annotations produced during one survey execution instance.

```
SurveyOrchestrator.run(slug)
  → [repo]      FileClassifier, FileStructure, FileSizeSurveyor, DataProfiler,
                LanguageSurveyor, HealthSurveyor, DependencySurveyor,
                DocumentationSurveyor, SecuritySurveyor, ApiStructureSurveyor
  → [database]  DatabaseSurveyor (local) and/or EgeriaDatabaseSurveyor (native)
  → SurveyResult (plain dataclasses)
       ↳ annotations[]:   each annotation links to its analysis (analysis_step)
  → ActivityLog entry written (operation='survey', annotations=[{analysis_name, count, …}])
  → [--publish] EgeriaPublisher.publish(result, zone_names=[…])
                   ↳ Creates SourceControlLibrary asset (with optional zoneMembership)
                   ↳ Creates SurveyReport linked via ReportSubject
                   ↳ Creates one Annotation per SurveyResult.annotation
```

`HybridDatabaseSurveyor` runs the local scan immediately after triggering the Egeria native survey, because Egeria surveys are async and produce no immediate schema data.

---

## Activity Log Schema

Every operation (scout, survey, catalog, publish, RFA, refresh) writes one `ActivityEntry`:

```
ActivityEntry {
  id            uuid (PRIMARY KEY)
  ts            ISO 8601 UTC
  operation     scout | survey | catalog | publish | discover | rfa | refresh
  intent        scouting | assessment | discovery | enrichment
  entity_type   repo | database | server | filesystem | file
  entity_slug
  entity_name
  entity_location
  status        running | ok | error | pending
  summary
  detail
  items[]       { kind, display_name, qualified_name, guid, location }
  annotations[] { analysis_name, annotation_type, count, status, summary }
}
```

Items and annotations are stored as JSON text columns in SQLite.

---

## Survey Source Badges

Section headers in the survey report carry source badges:

| Badge | Meaning |
|-------|---------|
| ☁ Egeria | Data from Egeria native survey |
| 🏠 Local | Data from local Python/SQL scan |
| ⏳ Pending | Analysis triggered but result not yet available |

---

## Scheduler

`scheduler.py` starts a daemon thread via FastAPI `lifespan`. It wakes every 15 minutes, queries `resource_schedules` for entries whose `next_run ≤ now()`, executes each due analysis (repo survey via `SurveyOrchestrator`, database survey via `run_database_survey`), then advances `next_run`. Supported intervals: `manual`, `daily`, `weekly`, `monthly`.

---

## Analysis Catalog

`analysis_catalog.py` defines all available analyses as plain Python dicts with fields:

| Field | Values |
|-------|--------|
| `id` | unique slug |
| `intent` | `scouting` \| `assessment` \| `discovery` \| `enrichment` |
| `perspectives` | `all`, `dba`, `data_scientist`, `steward`, `security` |
| `annotation_types` | Egeria annotation class names produced by this analysis |
| `source` | `local` \| `egeria` |
| `run_time` | `fast` \| `minutes` \| `async` |
| `action` | `survey` \| `publish` |
| `recommended` | bool |

`GET /api/analyses/{resource_type}?intent=…&perspective=…` filters and returns this catalog.

The field was renamed from `personas` to `perspectives` — filter accordingly.

---

## Egeria Configuration

`config.py` exposes `ExplorerConfig.egeria` (type `EgeriaConfig`) with:

| Field | Env var | Default |
|-------|---------|---------|
| `platform_url` | `EGERIA_PLATFORM_URL` | `https://localhost:9443` |
| `view_server` | `EGERIA_VIEW_SERVER` | `qs-view-server` |
| `user_id` | `EGERIA_USER_ID` | `erinoverview` |
| `user_password` | `EGERIA_USER_PASSWORD` | `secret` |
| `default_catalog_zones` | `EGERIA__DEFAULT_CATALOG_ZONES` | `[]` |
| `default_survey_zones` | `EGERIA__DEFAULT_SURVEY_ZONES` | `[]` |

`default_catalog_zones` sets the `zoneMembership` on new SourceControlLibrary assets created via `EgeriaPublisher`. Override per-request by passing `zone_names` to `EgeriaPublisher.__init__()` or `publish()`, or by sending `{ "zone_names": [...] }` in the POST body of `/api/egeria/{slug}/publish`. The web UI exposes a comma-separated text input in the Egeria panel.

---

## Key Design Rules

1. Classify intent before touching the vector store — statistical queries never hit pgvector.
2. Min retrieval score = 0.30 — below this, return "I don't have enough information."
3. Query cache is the highest-ROI latency win — implement before optimizing retrieval.
4. Observability runs in background threads — never block the query response.
5. Incremental indexing for repos — commit-diff based, not full re-index.
6. Four canonical intent labels: `scouting`, `assessment`, `discovery`, `enrichment`.
7. All operations must write activity log entries.
8. Egeria is the catalog of record; SQLite is a cache and queue.
9. `HybridDatabaseSurveyor` must run local scan immediately — Egeria surveys are async.
10. Analysis catalog field is `perspectives` (not `personas`) — filter with `?perspective=`.
11. `survey_meta` intent routes to `SurveyMetaAgent`; evaluated before all other intents.
