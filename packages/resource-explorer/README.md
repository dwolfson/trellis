# Resource Explorer

**Resource Explorer** discovers, understands, and catalogs information resources — Git repositories, PostgreSQL databases, and file systems — using [Egeria](https://egeria-project.org/) as the central metadata catalog.

> Successor to [Project Explorer](https://github.com/LF-AI/project-explorer). Egeria-first architecture; Egeria is optional for RAG-only use.

---

## Quick Start

```bash
# Install
uv sync
cp .env.example .env          # set GITHUB_TOKEN, EGERIA_*, LLM_BACKEND, …

# Start the web UI
uv run resource-explorer web  # → http://localhost:8810
```

Start the external services required for RAG and Egeria integration:
```bash
# pgvector — shared with Egeria Advisor's egeria_advisor Postgres database.
# In a Trellis monorepo checkout this is normally already running, managed
# by egeria-workspaces-fs's compose-configs/shared-infra/shared-infra.yaml
# (port 5442). For a from-scratch environment without it:
docker run -p 5442:5432 -e POSTGRES_DB=egeria_advisor -e POSTGRES_USER=egeria_advisor -e POSTGRES_PASSWORD=advisor pgvector/pgvector:pg17

# Ollama (default LLM backend)
ollama pull llama3.1:8b && ollama serve
```

---

## What it does

| Intent | Description |
|--------|-------------|
| **Scouting** | Fast broad inventory across many resources |
| **Assessment** | Deep analysis of a specific resource (schema, security, quality) |
| **Discovery** | Find resources by what surveys revealed |
| **Enrichment** | Provide human context; answer open RequestForAction annotations |

---

## Documentation

| Document | Audience |
|----------|----------|
| [docs/user-guide.md](docs/user-guide.md) | Daily users — web UI walkthrough, chat, intents |
| [docs/architecture.md](docs/architecture.md) | Developers — module map, query/survey flows, key design decisions |
| [docs/admin-guide.md](docs/admin-guide.md) | Operators — installation, Egeria setup, scheduling, troubleshooting |
| [docs/survey-activity-design.md](docs/survey-activity-design.md) | Architects — full design specification for survey/activity/annotation system |
| [docs/surveyor-reference.md](docs/surveyor-reference.md) | Developers — surveyor API reference |
| [docs/database-surveyor-design.md](docs/database-surveyor-design.md) | Developers — PostgreSQL surveyor internals |

---

## CLI reference

```bash
uv run resource-explorer --help

# Add resources
resource-explorer add-project https://github.com/org/repo
resource-explorer add-database --host localhost --port 5432 --name mydb

# Survey
resource-explorer survey <slug>          # full local survey
resource-explorer survey <slug> --publish  # survey + publish to Egeria

# Web + agents
resource-explorer web      # FastAPI web UI on :8810
resource-explorer serve    # A2A agent server
resource-explorer chat     # interactive CLI chat
```

---

## Tech stack

Python 3.12+, FastAPI, PostgreSQL/pgvector (registry + vector store, shared with Egeria Advisor), pyegeria, psycopg2, BeeAI, Ollama (default LLM), Tailwind CSS, Plotly.js.
