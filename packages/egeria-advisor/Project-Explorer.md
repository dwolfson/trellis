# Project Explorer — Strategy & Design Plan

## Vision

**Project Explorer** is a complete, production-quality reference implementation showing developers how to build a multi-agent RAG system from open-source components. It is designed to be studied, forked, and adapted — not a toy proof of concept, but a real working system that runs on a developer's laptop and can be hardened for production if needed.

Concretely, it is an intelligent, multi-project research assistant for GitHub repositories. Given one or more GitHub projects, it ingests code, documentation, and metadata, and provides a natural-language interface for technical users and product managers to explore, compare, and understand those projects — without requiring any AI/ML expertise.

*Inspired by egeria-advisor — a domain-specific RAG assistant for the Egeria open metadata platform — project-explorer generalizes the same architectural patterns for any GitHub project.*
---

## Goals

| Goal                       | Description                                                                       |
|----------------------------|-----------------------------------------------------------------------------------|
| **Universal**              | Works with any public (or private, with auth) GitHub project                      |
| **Multi-project**          | Manage a registry of projects; query across or within                             |
| **Adaptive ingestion**     | Analyze repos and auto-select the right collection types and parsers              |
| **Specialist agents**      | Route query types to the best agent: code, docs, stats, comparison                |
| **Non-expert UX**          | Terminal and web interface; no AI/ML knowledge required                           |
| **Observable**             | Track query quality, performance, satisfaction, and system health                 |
| **Incremental**            | Re-index only what changed since last run                                         |
| **Learnable & Extensible** | Complete, non-toy reference implementation designed to be studied, forked, and adapted |
| **Portable** | Runs on a laptop (Apple Silicon native acceleration) or server; containerized for easy deployment with a clear path to production hardening |

---



## What's Missing from the Initial Feature List

Beyond what you described, the following capabilities round out the system:

1. **Project comparison** — Side-by-side analysis of two or more projects (features, maturity, activity, community health)
2. **Dependency mapping** — What does each project depend on? What depends on it? Vulnerability exposure surface.
3. **License compliance** — Detect and summarize licenses; flag incompatibilities across a project's dependency tree
4. **Community health scoring** — Issue response time, PR merge rate, contributor diversity, bus factor estimate
5. **Changelog & release summarization** — "What changed in v2.0?" — parsed from CHANGELOG, release notes, and commit diffs
6. **Private repo support** — GitHub token-based auth for private or org-scoped repos
7. **Project similarity / discovery** — "Find me projects similar to X" using embedding-space clustering
8. **Scheduled re-indexing** — Cron-based incremental refresh so content stays current
9. **Export & reports** — Markdown summary, PDF report, or structured JSON export of any analysis
10. **REST API layer** — Expose query and management endpoints so other tools can integrate
11. **Alerting** — Notify (Slack, email, webhook) when a tracked project releases a new version or spikes in activity
12. **Multi-modal UI** — Beyond terminal: a Streamlit/FastAPI web UI and Jupyter notebook integration
13. **Project onboarding wizard** — Interactive flow to add a new project, detect content types, and confirm ingestion plan before running

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interface                            │
│   CLI (rich/typer) │ Web UI (FastAPI + HTMX) │ Jupyter plugin   │
├─────────────────────────────────────────────────────────────────┤
│                    Query Router / Intent Classifier              │
│   Factual │ Statistical │ Code │ Conceptual │ Compare │ Action   │
├─────────────────────────────────────────────────────────────────┤
│                    Agent Layer (BeeAI / AgentStack)              │
│  CodeAgent │ DocAgent │ StatsAgent │ CompareAgent │ HealthAgent  │
├─────────────────────────────────────────────────────────────────┤
│                    RAG Retrieval                                  │
│   CollectionRouter │ MultiCollectionStore │ Re-ranker (cross-enc)│
│                    Milvus (HNSW, 384-dim)                        │
├─────────────────────────────────────────────────────────────────┤
│                    Ingestion Pipeline                             │
│   RepoAnalyzer │ Docling │ CodeParser │ WebScraper │ PDFParser   │
│   IncrementalIndexer (commit-diff based)                         │
├─────────────────────────────────────────────────────────────────┤
│                    Project Registry & Metadata                    │
│   SQLite (project config, stats time-series, collection map)     │
│   GitHub API (PyGitHub / GraphQL)                                │
├─────────────────────────────────────────────────────────────────┤
│                    Observability & Feedback                       │
│   MLflow (experiments) │ Arize Phoenix (local LLM tracing) │ SQLite metrics │
│   FeedbackCollector │ Query Cache                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Query Flow

```
User Query
  → CLI / Web UI
  → QueryCache (cache hit → return immediately)
  → IntentClassifier
      ├── statistical   → StatsAgent (GitHub API + time-series SQLite)
      ├── comparison    → CompareAgent (multi-project RAG + structured diff)
      ├── code_search   → CodeAgent (code collections RAG)
      ├── conceptual    → DocAgent (markdown + web docs RAG)
      ├── health        → HealthAgent (community metrics + Arize data)
      └── general       → RAG (CollectionRouter → Milvus → LLM)
  → LLM generation (Ollama local or API-based)
  → Response formatting (terminal / web / notebook)
  → Async: MLflow tracking, Arize logging, metrics write, cache store
```

---

## Project Registry

Each registered project is a record in SQLite with:

```
projects
  id, slug, display_name, description
  github_url, homepage_url, docs_url
  github_token (encrypted, optional — private repos)
  last_indexed_at, last_stats_fetched_at
  collections: JSON list of active collection names
  status: active | paused | error
```

Projects are managed via CLI commands:
- `project-explorer add <github-url>` — triggers onboarding wizard
- `project-explorer remove <slug>` — drops collections and registry entry
- `project-explorer list` — shows all projects with status
- `project-explorer refresh <slug>` — incremental re-index
- `project-explorer status` — environment health dashboard

---

## Collection Design

Each project gets a namespace: `{project_slug}_{collection_type}`. Not every project gets every collection — the **RepoAnalyzer** inspects the repo structure and decides.

| Collection Type | Content | Chunk Strategy |
|---|---|---|
| `python_code` | .py source files | 512 tokens, overlap 64 |
| `javascript_code` | .js/.ts source | 512 tokens, overlap 64 |
| `java_code` | .java source | 512 tokens, overlap 64 |
| `go_code` | .go source | 512 tokens, overlap 64 |
| `markdown_docs` | READMEs, guides, wikis | 384 tokens, overlap 48 |
| `web_docs` | MkDocs, Sphinx, Docusaurus sites | 384 tokens, overlap 48 |
| `api_reference` | OpenAPI specs, docstrings | 256 tokens, overlap 32 |
| `examples` | Code samples, notebooks | 1024 tokens, overlap 128 |
| `pdfs` | PDFs (via Docling) | 512 tokens, overlap 64 |
| `release_notes` | Changelogs, release bodies | 256 tokens, overlap 32 |

**RepoAnalyzer** decision logic:
1. Clone/fetch repo via GitHub API
2. Count files by extension → determine which code collections to create
3. Check for docs site links in README / `mkdocs.yml` / `_config.yml`
4. Check for PDF assets in `docs/` subdirectories
5. Check for `examples/` or `samples/` directories
6. Present plan to user for confirmation (onboarding wizard)

---

## Ingestion Pipeline

### Sources

| Source | Tool | Notes |
|---|---|---|
| GitHub repo (code + docs) | PyGitHub + direct clone | Rate-limit aware; supports token auth |
| MkDocs / Sphinx / Docusaurus | Docling WebLoader or wget + Docling | Follows site nav |
| Raw web pages | Docling WebLoader | Configurable depth |
| PDFs | Docling | Layout-aware chunking |
| Jupyter notebooks | nbconvert + custom parser | Extract code + markdown cells |
| OpenAPI/Swagger | openapi-parser | Structured endpoint/schema docs |

### Incremental Update Strategy (from egeria-advisor learnings)

- Store `last_commit_sha` per collection in registry
- On refresh: `git log {last_sha}..HEAD --name-only` → only re-index changed files
- For web docs: HTTP `Last-Modified` / ETag headers; re-fetch only if changed
- For PDFs: hash-based change detection
- Delete+re-insert vectors for changed chunks; do not re-embed unchanged files

### DataPrepToolkit Integration

Use IBM's DataPrepToolkit for:
- PII detection and redaction before ingestion
- Duplicate chunk detection
- Language detection (route non-English docs appropriately)
- Quality filtering (remove boilerplate, license headers, auto-generated files)

---

## Agent Design

Built on **BeeAI** (multi-turn memory, tool use) with **AgentStack** for orchestration and runtime.

**Validated pattern** (from [lfai/ML_LLM_Ops](https://github.com/lfai/ML_LLM_Ops)): each agent is a `RequirementAgent` with `max_iterations=20`, retry logic, and streaming via `context.yield_async()`. Tools (e.g. `VectorStoreSearchTool`) wrap Milvus search and are registered at agent init. Middleware captures request/response/error per tool call for observability.

### CodeAgent
- Collections: `{project}_python_code`, `{project}_javascript_code`, etc.
- Tools: RAG retrieval, GitHub API (search code), syntax highlighter
- Specialization: "How do I use X?", "Show me an example of Y", "What does method Z do?"

### DocAgent
- Collections: `{project}_markdown_docs`, `{project}_web_docs`, `{project}_api_reference`
- Tools: RAG retrieval, web fetch (live docs for freshness)
- Specialization: Conceptual questions, architecture, getting started, configuration

### StatsAgent
- Source: SQLite time-series (pre-fetched from GitHub API), GitHub API live queries
- Tools: Pandas + Plotext (terminal graphs) / Plotly (web graphs)
- Specialization: Commit history, contributor counts, release cadence, LOC trends, star/fork growth
- Output: ASCII charts in terminal, interactive Plotly charts in web UI, PNG export

### CompareAgent
- Sources: Both projects' collections + stats
- Tools: Multi-project RAG, side-by-side structured response template
- Specialization: "Compare project A and B", "Which is more actively maintained?", "What features does X have that Y doesn't?"

### HealthAgent
- Source: GitHub API (issues, PRs, discussions), Arize data, community metrics
- Computed metrics: issue response time, PR cycle time, contributor diversity (Lorenz curve / Gini), bus factor estimate, activity trend
- Specialization: "Is this project actively maintained?", "How healthy is the community?"

---

## Statistics & Graphing

Pre-fetched and stored in SQLite time-series tables:

```
project_stats
  project_id, fetched_at
  stars, forks, watchers, open_issues
  contributors_count, commits_30d, commits_90d
  releases_count, latest_release, latest_release_at
  lines_of_code, file_count, module_count
  primary_language, language_breakdown (JSON)
```

On query, StatsAgent:
1. Pulls from SQLite (fast, offline-capable)
2. Optionally supplements with live GitHub API call
3. Renders graphs via **Plotext** (terminal) or **Plotly** (web)
4. Exports PNG via kaleido for PDF reports

Key graphs available:
- Commit frequency over time (12-month rolling)
- Contributor growth / active contributors per month
- Stars/forks over time
- Release cadence (time between releases)
- Language breakdown (pie/bar)
- Lines of code over time (requires cloning history — optional/expensive)
- Issue open/close rate

---

## Observability Stack

### MLflow (Experiment Tracking)
- Track: query text (hashed), intent type, collections used, retrieval latency, LLM latency, total latency
- Track: embedding model version, LLM model, top-k, min-score threshold
- Enables: latency regression detection, A/B testing retrieval configs

### Arize Phoenix (Local LLM Tracing)
- Open-source, runs locally at `localhost:6006` — no cloud account required
- Send: query embedding, response, retrieved context, user feedback signal via OpenTelemetry
- Monitor: embedding drift, response quality degradation, retrieval relevance over time
- Uses BeeAI agent middleware (request/response/error capture per tool call) as the hook point
- Alert: when response quality drops below threshold for a project's collections

### Local SQLite Metrics
- Fast, always-available, no external dependency
- Query log, collection health, system resources (same pattern as egeria-advisor)
- Powers the terminal dashboard

### Query Cache
- Redis or in-process LRU cache (configurable)
- Cache key: normalized query + project scope + top-k
- TTL: 1 hour default (configurable per collection — stats queries shorter, concept queries longer)
- From egeria-advisor: this delivers massive latency wins on repeated questions

### User Feedback
- Terminal: thumbs up/down prompt after each response
- Web: inline reaction buttons
- Feedback stored in SQLite, surfaced to Arize and MLflow

---

## Technology Stack

| Component | Choice | Rationale |
|---|---|---|
| Vector Store | **Milvus** | Multi-tenant namespacing via collection prefixes; better horizontal scale than pgvector for multi-project |
| Agent Framework | **BeeAI** | Already validated in egeria-advisor; good multi-turn memory |
| Agent Orchestration | **AgentStack** | Scaffolding for multi-agent pipelines; complements BeeAI |
| Document Parsing | **Docling** | Best-in-class PDF and web page parsing; layout-aware |
| Data Prep | **DataPrepToolkit** | PII, dedup, quality filtering pipeline |
| Experiment Tracking | **MLflow** | Already in use; lightweight and self-hosted |
| LLM Observability | **Arize Phoenix** | Open-source, runs locally at `localhost:6006`; tracing, embedding drift, hallucination detection — no account needed |
| GitHub Integration | **PyGitHub** + **GraphQL** | REST for metadata, GraphQL for complex stats queries |
| LLM | **Ollama** (default) + API adaptor | Local-first; Metal GPU acceleration on Apple Silicon; pluggable for OpenAI, Anthropic |
| Embeddings | **sentence-transformers** | `all-MiniLM-L6-v2` (384-dim); MPS acceleration on Apple Silicon via PyTorch |
| Terminal UI | **Rich** + **Typer** | Same pattern as egeria-advisor |
| Web UI | **FastAPI** + **HTMX** | Lightweight; no heavy JS framework needed |
| Graphs (terminal) | **Plotext** | ASCII charts in terminal |
| Graphs (web/export) | **Plotly** + **kaleido** | Interactive and PNG export |
| Package manager | **uv** | Fast, modern Python package management; replaces pip |
| Config | **Pydantic** + YAML | Same pattern as egeria-advisor |
| Metrics DB | **SQLite** | Zero-dependency, always available |

---

## LLM Abstraction

**Ollama is the default backend** — local-first, no API keys required, and uses Metal GPU acceleration on Apple Silicon (M1/M2/M3/M4). This makes the reference implementation runnable out of the box on a developer laptop with zero cloud dependencies.

A `LLMBackend` protocol abstracts the interface so API-based models can be swapped in without code changes:

```python
class LLMBackend(Protocol):
    def complete(self, prompt: str, **kwargs) -> str: ...
    def stream(self, prompt: str, **kwargs) -> Iterator[str]: ...

# Implementations:
class OllamaBackend(LLMBackend): ...    # default; Metal/CUDA accelerated
class OpenAIBackend(LLMBackend): ...
class AnthropicBackend(LLMBackend): ...
```

Config selects backend via `llm.backend` in `config/explorer.yaml`. On Apple Silicon, sentence-transformers embedding inference also accelerates via PyTorch MPS — no configuration needed, detected automatically.

---

## Key Design Decisions (from egeria-advisor Learnings)

1. **Classify before retrieving** — Intent classification saves latency and improves relevance; statistical queries should never hit the vector store
2. **Collection routing matters** — Selecting 2-3 relevant collections outperforms searching all of them
3. **Min-score threshold = 0.30** — Anything below is noise; better to say "I don't know" than hallucinate
4. **Chunk size is content-specific** — Code: 512, prose: 384, templates/examples: 1024
5. **Async observability** — MLflow/Arize tracking in background thread; never block the response
6. **Query cache first** — Biggest latency win; implement before optimizing retrieval
7. **Incremental indexing is not optional** — Without it, large repos are too expensive to re-index regularly
8. **Feedback loop closes the quality loop** — Without user signal, you're flying blind on response quality

---

## Phased Implementation Plan

### Phase 1 — Foundation (Weeks 1-3)
- [ ] Project scaffold (pyproject.toml, config, CLI skeleton with Typer)
- [ ] Project Registry (SQLite schema, CRUD operations)
- [ ] GitHub API integration (PyGitHub wrapper, rate-limit handling, token auth)
- [ ] RepoAnalyzer (content-type detection, collection plan generation)
- [ ] Onboarding wizard (interactive CLI: add project → detect → confirm → ingest)
- [ ] Basic ingestion pipeline (Python code, Markdown docs)
- [ ] Milvus multi-collection store (namespace per project)
- [ ] Basic RAG query (no agents yet — single collection, direct retrieval)

### Phase 2 — Ingestion Breadth (Weeks 4-6)
- [ ] Docling integration (PDF, web docs, MkDocs sites)
- [ ] JavaScript/TypeScript, Java, Go code parsers
- [ ] Jupyter notebook parser (nbconvert pipeline)
- [ ] OpenAPI/Swagger parser
- [ ] DataPrepToolkit integration (PII, dedup, quality filter)
- [ ] Incremental indexer (commit-diff based, hash-based for web/PDF)
- [ ] Scheduled refresh (APScheduler / cron integration)

### Phase 3 — Intelligence (Weeks 7-10)
- [ ] Intent classifier (query type routing)
- [ ] CollectionRouter (per-project collection selection)
- [ ] BeeAI multi-turn conversation agent
- [ ] CodeAgent (code search, method lookup)
- [ ] DocAgent (conceptual Q&A)
- [ ] StatsAgent (GitHub stats + Plotext charts)
- [ ] Query cache (LRU + Redis option)
- [ ] Re-ranker (cross-encoder for top-k refinement)

### Phase 4 — Advanced Agents (Weeks 11-13)
- [ ] CompareAgent (multi-project side-by-side)
- [ ] HealthAgent (community health scoring)
- [ ] Changelog / release summarization pipeline
- [ ] Project similarity clustering (embedding-space KMeans across projects)
- [ ] AgentStack orchestration layer

### Phase 5 — Observability & UX (Weeks 14-16)
- [ ] MLflow tracking (non-blocking background thread)
- [ ] Arize integration (embedding + response logging)
- [ ] SQLite metrics + terminal dashboard (Rich Live)
- [ ] User feedback collection
- [ ] Web UI (FastAPI + HTMX: query interface, project management, dashboard)
- [ ] Plotly graphs in web UI, PNG export
- [ ] REST API (project management + query endpoints)

### Phase 6 — Polish & Production (Weeks 17-18)
- [ ] Alerting (Slack webhook / email on new release, activity spike)
- [ ] Export (Markdown summary, PDF report via Docling)
- [ ] Private repo support (token encryption at rest)
- [ ] Performance benchmarking + latency budget enforcement
- [ ] Documentation and onboarding guide

---

## Directory Structure (Proposed)

```
project-explorer/
├── explorer/
│   ├── __init__.py
│   ├── config.py                  # Pydantic settings
│   ├── registry.py                # Project Registry (SQLite)
│   ├── rag_system.py              # Main orchestrator
│   ├── query_processor.py         # Intent classifier + router
│   ├── collection_router.py       # Per-project collection selection
│   ├── query_cache.py             # LRU + optional Redis
│   ├── llm_client.py              # LLM abstraction (Ollama / API)
│   ├── embeddings.py              # Sentence-transformer wrapper
│   ├── multi_collection_store.py  # Milvus multi-tenant store
│   ├── prompt_templates.py        # Per-agent prompt templates
│   ├── github/
│   │   ├── client.py              # PyGitHub + GraphQL wrapper
│   │   ├── analyzer.py            # RepoAnalyzer (content detection)
│   │   └── stats_fetcher.py       # Time-series stats → SQLite
│   ├── ingestion/
│   │   ├── pipeline.py            # Orchestrate full ingestion
│   │   ├── incremental.py         # Commit-diff / hash-based updates
│   │   ├── code_parser.py         # Python/JS/Java/Go parsers
│   │   ├── doc_parser.py          # Markdown + Docling (PDF, web)
│   │   ├── notebook_parser.py     # Jupyter .ipynb
│   │   ├── api_parser.py          # OpenAPI/Swagger
│   │   └── data_prep.py           # DataPrepToolkit integration
│   ├── agents/
│   │   ├── base.py
│   │   ├── code_agent.py          # Code search + method lookup
│   │   ├── doc_agent.py           # Conceptual Q&A
│   │   ├── stats_agent.py         # Statistics + graphing
│   │   ├── compare_agent.py       # Multi-project comparison
│   │   ├── health_agent.py        # Community health scoring
│   │   └── conversation_agent.py  # BeeAI multi-turn wrapper
│   ├── cli/
│   │   ├── main.py                # Typer CLI entry point
│   │   ├── interactive.py         # REPL mode
│   │   ├── wizard.py              # Onboarding wizard
│   │   └── formatters.py          # Rich output helpers
│   ├── web/
│   │   ├── app.py                 # FastAPI app
│   │   ├── routes/                # Query, project, stats endpoints
│   │   └── templates/             # HTMX templates
│   ├── dashboard/
│   │   ├── terminal_dashboard.py  # Rich Live dashboard
│   │   └── graphs.py              # Plotext + Plotly graph builders
│   └── observability/
│       ├── metrics_collector.py   # SQLite query metrics
│       ├── mlflow_tracking.py     # Non-blocking MLflow wrapper
│       ├── arize_client.py        # Arize LLM monitoring
│       └── feedback_collector.py  # User thumbs up/down
├── scripts/
│   ├── add_project.py             # Standalone project onboarding
│   ├── refresh_stats.py           # Fetch/update GitHub stats
│   ├── count_vectors.py           # Collection health check
│   └── test_end_to_end.py         # E2E test suite
├── config/
│   ├── explorer.yaml              # Primary config
│   ├── routing.yaml               # Intent classification rules
│   └── collection_config.py       # Collection type definitions
├── tests/
├── pyproject.toml
├── CLAUDE.md
└── README.md
```

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| GitHub API rate limits (5000 req/hr) | High | Medium | Cache aggressively; use GraphQL to batch; token auth for higher limits |
| Milvus schema incompatibility across projects | Medium | High | Strict per-project namespace; schema version field in metadata |
| Docling parsing failures (complex PDFs/sites) | Medium | Low | Graceful skip with warning; fallback to plain text extraction |
| LLM hallucination on low-retrieval-score responses | High | High | Enforce min-score=0.30; "I don't have enough information" response path |
| Incremental indexer missing deleted files | Medium | Medium | Periodic full-sync option; checksum registry per file |
| Arize data volume costs | Low | Medium | Sample high-traffic queries; only log to Arize in production mode |
| Private repo token security | Low | High | Encrypt at rest (keyring); never log tokens; scope to read-only |
