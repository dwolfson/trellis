# Ground-truth partition — trellis

> **PRE-REGISTERED**, with provenance marked per component (see `README.md`).
> Scored **per perspective** — a component is only compared against detectors that read
> the same perspective (plan §5a, design §4.1).

**Target:** trellis
**Checkout:** `/Users/dwolfson/localGit/egeria-v6/trellis`
**Perspective:** logical
**Vocabulary:** SolutionComponentType (design doc §3.1, 13 closed values)
**Written by:** dwolfson
**Written at:** 2026-08-20

> No **Blueprints** section — trellis ships one solution.
>
> trellis has **no Dockerfiles, no compose files, no `catalog-info.yaml`**, so it has no
> deployment perspective at all. Everything below is the *logical* architecture — which is
> why the manifest/deployment detectors are not expected to recover it (plan §6).

---

## Components

### Web backend

- **Type:** Software Service
- **Perspective:** logical
- **Files:**
  - `packages/resource-explorer/resource_explorer/web/routes/**`
  - `packages/resource-explorer/resource_explorer/web/app.py`
- **Notes:** FastAPI web services supporting the front-end.
- **Provenance:** maintainer (glob narrowed to `routes/` by assistant to separate it from the SPA)

### Web front-end

- **Type:** User Interface
- **Perspective:** logical
- **Files:**
  - `packages/resource-explorer/resource_explorer/web/static/**`
  - `packages/resource-explorer/frontend-build/**`
- **Notes:** JavaScript single-page applications. Maintainer originally typed this
  `Application`, which is a `SoftwareCapability` subtype (deployment vocabulary), not one of
  the 13 `SolutionComponentType` values — see design §4.2. `User Interface` is the logical
  equivalent; both are correct in their own perspective.
- **Provenance:** maintainer (type remapped by assistant)

### CLI

- **Type:** Console Command
- **Perspective:** logical
- **Files:**
  - `packages/resource-explorer/resource_explorer/cli/**`
- **Notes:** Terminal based interface.
- **Provenance:** maintainer (type remapped from `Application`)

### Textual TUI

- **Type:** User Interface
- **Perspective:** logical
- **Files:**
  - `packages/resource-explorer/resource_explorer/tui/**`
- **Notes:** Textual based interface.
- **Provenance:** maintainer (type remapped from `Application`)

### RAG ingestion

- **Type:** Multi-Step Process
- **Perspective:** logical
- **Files:**
  - `packages/resource-explorer/resource_explorer/ingestion/**`
- **Provenance:** maintainer (type assigned by assistant — maintainer left it blank)

### Agents

- **Type:** Software Service
- **Perspective:** logical
- **Files:**
  - `packages/resource-explorer/resource_explorer/agents/**`
- **Notes:** Agents supporting different analyses and interactions (code, compare,
  conversation, doc, examples, …).
- **Provenance:** maintainer named it; type and files filled by assistant

### Observability

- **Type:** Software Service
- **Perspective:** logical
- **Files:**
  - `packages/resource-explorer/resource_explorer/observability/**`
- **Notes:** MLflow and possibly Arize; feedback.
- **Provenance:** maintainer

### Prefect orchestration

- **Type:** Automated Action
- **Perspective:** logical
- **Files:**
  - `packages/resource-explorer/resource_explorer/prefect/**`
- **Notes:** Open-source flow engine choreographing execution of survey types.
- **Provenance:** maintainer (type remapped from `Software Service` — Prefect adapters
  orchestrate rather than serve; revisit if you disagree)

### Surveyors

- **Type:** Multi-Step Process
- **Perspective:** logical
- **Files:**
  - `packages/resource-explorer/resource_explorer/surveyors/**`
- **Notes:** Microflows performing different kinds of survey steps.
- **Provenance:** maintainer (type remapped from `Software Service`)

### Core

- **Type:** Software Library
- **Perspective:** logical
- **Files:**
  - `packages/resource-explorer/resource_explorer/*.py`
- **Notes:** The 19 top-level modules — `registry.py`, `rag_system.py`, `config.py`,
  `query_processor.py`, `collection_router.py`, `scheduler.py`, `llm_client.py`,
  `embeddings.py`, `vector_store_pg.py` and siblings. Confirmed by the maintainer as a real
  component rather than unassigned; a directory-clustering detector cannot find it, because
  it is defined by *not* being in a directory.
- **Provenance:** maintainer confirmed the component; files filled by assistant

### Utility scripts

- **Type:** Console Command
- **Perspective:** logical
- **Files:**
  - `packages/resource-explorer/scripts/**`
- **Notes:** Maintainer wrote `resource_explorer/utility_scripts/`, which does not exist —
  the directory is `packages/resource-explorer/scripts/`.
- **Provenance:** maintainer (path corrected by assistant)

---

## Unassigned OK

> Under the **logical** perspective only. Most of these belong to the **Dev/DevOps**
> perspective (design §4.4) and should move there once it is written up — they are not
> genuinely unowned.

- `docs/**`
- `packages/*/tests/**`
- `packages/resource-explorer/data/**`
- `logs/**`
- `htmlcov/**`

---

## Excluded — not first-party

- `packages/resource-explorer/resource_explorer/web/static/vendor/**`
