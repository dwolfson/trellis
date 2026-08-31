# Trellis — Workspace Architecture

**Written:** 2026-08-30. There was no workspace-level architecture document before this; the
README covered layout and rationale, and each app documented itself, but nothing described how
the pieces relate.

This is the shape of the whole repo. For either app's internals, follow the links at the end.

- Getting it running: [QUICKSTART.md](../QUICKSTART.md)
- Why one repo, and how to add a member: [README.md](../README.md)
- Cross-session git conventions: [CLAUDE.md](../CLAUDE.md)

---

## What Trellis is

A `uv` workspace holding **two applications** and **six shared libraries**, with one lockfile
and one `.venv`.

The two apps are independently deployable services. The monorepo is a source-organisation and
dependency-resolution decision, **not a runtime-topology one** — neither app is built,
deployed or run as part of the other. That constraint is load-bearing: a change that couples
their runtime behaviour is out of scope for this workspace's design, however convenient.

| | What it does | Egeria |
|---|---|---|
| **Resource Explorer** | Discovers, surveys and catalogs information resources — repos, PostgreSQL databases, filesystems | Catalog of record; optional for RAG-only use |
| **Egeria Advisor** | Conversational assistant for Egeria and pyegeria; governance-plan authoring; report-spec building | Required for action/report queries |

They meet in two places and nowhere else: **one Postgres instance**, and the **six shared
libraries**.

---

## The dependency graph

```
        egeria-advisor                    resource-explorer
              │                                   │
    ┌─────────┼──────────┐         ┌──────┬───────┼────────┬─────────────┐
    ▼         ▼          ▼         ▼      ▼       ▼        ▼             ▼
 trellis-  trellis-  trellis-  trellis- trellis- trellis- trellis-  trellis-
  auth    querycache vectorstore microflow context vectorstore querycache artifact-tree
                                                      │
                                                      ▼
                                             trellis-artifact-tree
```

Declared, not incidental — both apps list their `trellis-*` dependencies explicitly in their
own `pyproject.toml`, and `[tool.uv.sources]` at the root resolves them to workspace members.

**The arrows only ever point down.** No library imports an app, and only one library imports
another (`trellis-context` → `trellis-artifact-tree`, for `Rung`). A library that needed an app
would mean the boundary was drawn in the wrong place.

### What makes something a library rather than an app

A `trellis-*` member has **no CLI, no web server, no Egeria client and no credentials**. It is
imported and never deployed. The moment one of those is needed, the thing is an app.

This is not bureaucratic: it is what makes the libraries testable as pure functions of their
input, and what stops a shared dependency quietly acquiring a runtime.

---

## The six libraries

| Library | Owns | Used by |
|---|---|---|
| **trellis-vectorstore** | pgvector access — one `PgVectorStore` where there were two | both |
| **trellis-querycache** | TTL + LRU query cache | both |
| **trellis-auth** | JWT auth and Portal SSO token exchange | EA |
| **trellis-artifact-tree** | The containment tree over an ingested artifact — the structure retrieval walks, and the rungs it can degrade to | RE |
| **trellis-context** | `ContextSpec` + a deterministic packer: bounded context under a budget, plus a manifest saying what it did | RE |
| **trellis-microflow** | Resource-sharing primitives — acquire a zipball or clone once, share it across the steps that need it | RE |

The first extraction was `trellis-vectorstore`, and its README is the worked example: every
constructor parameter traces to a confirmed behavioural difference between the two original
implementations rather than a guess. That is the standard for an extraction — reproduce both
callers' behaviour exactly, then converge deliberately.

---

## Shared infrastructure

One PostgreSQL instance (`egeria_advisor`, port 5442) with the pgvector extension, and the
separation inside it is the thing to understand:

| | Egeria Advisor | Resource Explorer |
|---|---|---|
| Schema | `public`, unqualified | `resource_explorer`, named |
| Collections | Fixed set of 9, provisioned at web-app startup | Per-resource `{slug}_{type}`, created lazily on first insert |
| Registry | Its own tables in `public` | 51 tables in its schema |

The named schema is why RE's setup has one manual step the quickstart calls out: the shared
container's init script creates the database and the extension, not RE's schema.

Also shared, all optional: **Ollama** (LLM), and **MLflow** / **Phoenix** / **Prefect** /
**Kroki** where configured. None is required to run either app.

---

## Where the two apps genuinely converge

Worth naming, because it is where duplication keeps reappearing:

- **Vector access and caching** — solved, by extraction.
- **Question → evidence.** Both apps answer questions over a corpus with an LLM. RE compiles
  bounded context with a manifest (`trellis-context`); EA routes to specialist agents and RAG.
  These have not converged and there is no current plan that they should.
- **Intent and perspective vocabularies.** Both classify what a user is trying to do. The
  vocabularies are *not* shared, and one attempt to align them has already been reverted: RE
  retired its own four perspectives in favour of Egeria's twelve, and EA has its own roles.
  Aligning these is a real design question, not a refactor.

---

## Conventions that hold across the workspace

**One shared `.venv`.** There is no per-package virtualenv and nothing to activate. Every
command runs from the workspace root, usually via `uv run --package <name> ...` or a `make`
target.

**Absence is a first-class result.** Both apps must distinguish *measured zero* from *never
looked*. RE has explicit vocabularies for it (`result_status.py`, `step_outcome.py`); the
principle is workspace-wide, because a confident wrong answer is worse than an error — nothing
looks broken.

**Several sessions work in this checkout at once.** No whole-tree git operations; name the
paths. See [CLAUDE.md](../CLAUDE.md) — it is a real constraint here, not hygiene advice.

**Archived docs are kept, not deleted**, under a stated test: *nothing points at it*, measured
by reference count, rather than *the work is done*. Both apps have a `docs/archive/README.md`
explaining what moved and why.

---

## Where to go next

| For | Read |
|---|---|
| Resource Explorer's internals | [packages/resource-explorer/docs/Architecture.md](../packages/resource-explorer/docs/Architecture.md) |
| Working on Resource Explorer | [packages/resource-explorer/CLAUDE.md](../packages/resource-explorer/CLAUDE.md) |
| Egeria Advisor's internals | [packages/egeria-advisor/docs/design/SYSTEM_ARCHITECTURE.md](../packages/egeria-advisor/docs/design/SYSTEM_ARCHITECTURE.md) |
| Working on Egeria Advisor | [packages/egeria-advisor/CLAUDE.md](../packages/egeria-advisor/CLAUDE.md) |
| The context-compilation subsystem | [context-compilation-architecture.md](context-compilation-architecture.md), [design](context-compilation-design.md), [usage](context-compilation-usage.md) |
| How a library got extracted | [trellis-vectorstore-extraction.md](trellis-vectorstore-extraction.md), [trellis-auth-extraction.md](trellis-auth-extraction.md) |
