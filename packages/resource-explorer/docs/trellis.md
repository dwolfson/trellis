# Trellis / Resource Explorer — component reference notes

**Status:** hand-authored reference outline describing runtime and deployment
components. Sibling to `egeria.md` and `workspaces.md`. **Not the scoring fixture** — the pre-registered
ground-truth partitions used to score architecture recovery live in
`tests/fixtures/architecture-ground-truth/` and are richer; these three are
descriptive notes, and the two sets deliberately differ.

## trellis / resource-explorer

## Runtime Components

### resource-explorer web

  
#### backend
- FastAPI web services supporting the front-end
- **Type:** Software Service
- **Files:**
  - `resource-explorer/resource_explorer/web/**`
#### front-end
- javascript single page applications
- **Type:** Application
- **Files:**
  - `resource-explorer/frontend-build/**`
  
### cli
- terminal based interface
- **Type:** Application
- **Files:**
  - `resource-explorer/resource_explorer/cli/**`
### textual
- textual based interface
- **Type:** Application
- **Files:**
  - `resource-explorer/resource_explorer/tui/**`
### RAG ingestion
- **Type:** Software Service
- **Files:**
  - `resource-explorer/resource_explorer/ingestion/**`
### Agents
- A bunch of different agents to support different analyses and interactions (code, compare, conversations, doc, examples, etc)

### Observability
- Support for mlflow and maybe arize
- feedback
- **Type:** Software Service
- **Files:**
  - `resource-explorer/resource_explorer/observability/**`

### prefect
- open source flow engine to choreograph execution of survey types
- **Type:** Software Service
- **Files:**
  - `resource-explorer/resource_explorer/prefect/**`
### surveyors
- microflows to perform different kinds of survey steps 
- **Type:** Software Service
- **Files:**
  - `resource-explorer/resource_explorer/surveyors/**`
### utility scripts
- a variety of scripts to support different kinds of operations
- **Type:** Application
- **Files:**
  - `resource-explorer/resource_explorer/utility_scripts/**`
