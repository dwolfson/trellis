# Resource Explorer — Admin Guide

**Last revised:** 2026-06-10

This guide covers installation, configuration, Egeria integration, scheduled analyses, and troubleshooting.

---

## Requirements

| Component | Minimum | Notes |
|-----------|---------|-------|
| Python | 3.12 | 3.13 supported |
| uv | any recent | package manager |
| SQLite | 3.35+ | ships with Python |
| Milvus | 2.4+ | required for RAG; Milvus Lite supported |
| Ollama | any | default LLM backend; can use OpenAI/Anthropic instead |
| Egeria | 5.x | required for catalog/survey; optional for RAG-only use |
| PostgreSQL | 12+ | only needed for database surveying |

---

## Installation

```bash
git clone https://github.com/PDR-Associates/resource-explorer
cd resource-explorer
uv sync
uv sync --extra dev --extra phoenix   # dev tools + Arize Phoenix tracing

cp .env.example .env
# Edit .env — see Configuration section below
```

---

## Configuration

All settings are in `.env` (loaded via `resource_explorer/config.py` using Pydantic Settings).

### Required

```bash
GITHUB_TOKEN=ghp_...          # GitHub personal access token (repo scope)
```

### LLM backend (default: Ollama)

```bash
LLM_BACKEND=ollama            # ollama | openai | anthropic
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

# If using OpenAI:
LLM_BACKEND=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# If using Anthropic:
LLM_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-8
```

### Milvus

```bash
MILVUS__URI=./data/milvus.db   # Milvus Lite (single file, no server needed)
# or
MILVUS__URI=http://localhost:19530  # Full Milvus server
```

### Egeria

```bash
EGERIA_PLATFORM_URL=https://localhost:9443
EGERIA_VIEW_SERVER=view-server
EGERIA_ENGINE_HOST=engine-host
EGERIA_USER_ID=garygeeke
EGERIA_USER_PASSWORD=secret
EGERIA_KAFKA_ENDPOINT=localhost:9092

# Default governance zones assigned to new assets when cataloging (JSON list)
EGERIA__DEFAULT_CATALOG_ZONES=["data-lake","analytics"]

# Default governance zones for survey-triggered asset creation
EGERIA__DEFAULT_SURVEY_ZONES=["survey-zone"]
```

Zone names can also be specified per-operation via the Egeria publish panel in the web UI (comma-separated text field), or via the `zone_names` field in the `POST /api/egeria/{slug}/publish` body.

Egeria is only required for:
- `resource-explorer survey --publish` (writes to Egeria catalog)
- Egeria-native database survey
- RFA lifecycle management
- Reading Egeria annotation results back into the survey report

### Observability (optional)

```bash
MLFLOW_TRACKING_URI=http://localhost:5025
PHOENIX_ENDPOINT=http://localhost:6006
```

---

## Starting external services

### Milvus Lite (simplest — no Docker needed)

Set `MILVUS__URI=./data/milvus.db` in `.env`. Milvus Lite runs in-process.

### Full Milvus (Docker)

```bash
docker run -d --name milvus -p 19530:19530 milvusdb/milvus:v2.4.0
```

### Ollama

```bash
ollama pull llama3.1:8b
ollama serve           # starts on :11434
```

### MLflow (optional)

```bash
mlflow server --port 5025
```

### Arize Phoenix (optional)

```bash
python -m phoenix.server.main    # starts on :6006
```

---

## Running the app

```bash
# Web UI (production-ready with uvicorn)
uv run resource-explorer web

# Development mode with auto-reload
uv run uvicorn resource_explorer.web.app:app --reload --port 8810
```

---

## Database storage

The SQLite registry is created automatically at first run:

```
Default location: ~/.resource-explorer/registry.db
Override: REGISTRY_DB_PATH=/path/to/registry.db
```

Back up this file to preserve all registered resources, survey history, activity log, and schedules.

---

## Adding resources

### Git repositories

```bash
uv run resource-explorer add-project https://github.com/org/repo

# Then index it (downloads + chunks + stores in Milvus)
uv run resource-explorer index my-repo
```

### PostgreSQL databases

```bash
uv run resource-explorer add-database \
  --host db.example.com \
  --port 5432 \
  --name production \
  --display-name "Production DB"
```

Or use the web UI: select **Databases** in the left sidebar → **+ Add Database**.

---

## Surveys

### Manual survey

```bash
# Local survey only
uv run resource-explorer survey my-repo

# Local survey + publish to Egeria
uv run resource-explorer survey my-repo --publish
```

The survey writes a row to `activity_log` and updates `project_file_type_counts`. Run it again to accumulate history for the diff banner and survey history chart.

### Scheduled surveys

In the web UI, open **Analyses** for a resource, scroll to the **Schedule** section at the bottom, and set an interval per analysis. The background scheduler (started automatically with `resource-explorer web`) executes due analyses every 15 minutes.

To check what schedules are configured:

```python
from resource_explorer.registry import ProjectRegistry
r = ProjectRegistry()
print(r.get_schedules('repo', 'my-repo'))
print(r.get_due_schedules())
```

---

## Egeria integration

### Catalog a repository

```bash
uv run resource-explorer survey my-repo --publish
```

This runs a local survey, then calls `EgeriaPublisher` to create a `SourceControlLibrary` element in Egeria with file type annotations.

### Survey a database in Egeria

In the web UI, open a database survey report and click **Catalog & Survey in Egeria →**. This:
1. Creates a `PostgreSQLServer` and `PostgreSQLDatabase` element in Egeria (from templates)
2. Triggers `initiate_postgres_database_survey()` — async Egeria-native survey
3. Simultaneously runs a local schema scan for immediate display

Results from the Egeria survey appear with a ☁ badge when the survey completes (poll with **Re-survey in Egeria** button).

### RFA lifecycle

When a survey produces `RequestForAction` annotations, they appear in the **RFAs** panel. Assign and answer them there. Answers are currently stored locally in `resource_context`; Egeria write-back is planned.

---

## Observability

### MLflow

Visit `http://localhost:5025` to see experiment runs, query latencies, and retrieval scores. Each query creates an MLflow run automatically (non-blocking background thread).

### Arize Phoenix

Visit `http://localhost:6006` to see LLM traces, token usage, and agent spans. Instrumented via `openinference-instrumentation-beeai`.

---

## Upgrading

```bash
git pull
uv sync
uv run resource-explorer web   # schema migrations run automatically on startup
```

The registry schema uses `CREATE TABLE IF NOT EXISTS` guards — new tables are added transparently. No manual migration steps are needed for additive changes.

---

## Troubleshooting

### "Egeria connection failed"

Check `EGERIA_PLATFORM_URL` and that your Egeria chassis is running. Test connectivity:

```bash
curl -k https://localhost:9443/open-metadata/platform-services/users/garygeeke/server-platform/origin
```

### "No module named 'resource_explorer'"

Run commands via `uv run`:

```bash
uv run resource-explorer web     # correct
resource-explorer web            # wrong — uses system Python
```

### Survey history chart not showing

The diff banner and history chart require at least 2 survey runs. Run the survey twice:

```bash
uv run resource-explorer survey my-repo
# wait a moment, then run again
uv run resource-explorer survey my-repo
```

### Milvus connection refused

If using the full Milvus server, verify it's running:

```bash
docker ps | grep milvus
curl http://localhost:9091/healthz
```

Switch to Milvus Lite for development: set `MILVUS__URI=./data/milvus.db` in `.env`.

### Tests failing

```bash
uv run pytest tests/ -v --tb=short
```

Pre-existing external-service tests (Milvus, Egeria, GitHub) are skipped when the services are unavailable. All 208 core tests should pass without external services.

---

## API reference

Interactive API docs are available at `http://localhost:8810/docs` when the web server is running.

Key endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/` | List registered repos |
| `POST` | `/api/projects/{slug}/refresh` | Re-index a repo |
| `GET` | `/api/databases/` | List registered databases |
| `POST` | `/api/databases/{slug}/survey` | Run database survey |
| `GET` | `/api/egeria/{slug}/survey-report` | Get survey report (local SQLite — no Egeria needed) |
| `POST` | `/api/egeria/{slug}/survey` | Run local survey only |
| `POST` | `/api/egeria/{slug}/publish` | Run survey + publish to Egeria (accepts `{zone_names:[…]}`) |
| `GET` | `/api/egeria/{slug}/diff` | Get file count delta vs previous survey |
| `GET` | `/api/databases/{slug}/diff` | Get schema delta vs previous survey |
| `GET` | `/api/activity/` | List activity log entries (filterable by entity_type, intent, operation, status) |
| `GET` | `/api/activity/rfas` | List open RequestForAction annotations |
| `GET` | `/api/analyses/{resource_type}` | List available analyses (`?intent=…&perspective=…`) |
| `GET` | `/api/context/{entity_type}/{slug}` | Get resource context |
| `POST` | `/api/context/{entity_type}/{slug}` | Save resource context |
| `GET` | `/api/schedules/{entity_type}/{slug}` | Get analysis schedules |
| `POST` | `/api/schedules/{entity_type}/{slug}` | Save analysis schedule |
| `POST` | `/api/query/` | Submit a question (routed by intent — includes `survey_meta`) |
