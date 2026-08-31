# Resource Explorer — Architecture

**Last revised:** 2026-08-30. Supersedes the 2026-06-10 revision, which described a
SQLite-only registry, ten sub-surveyors and eleven web routes — the counts are now 51 tables,
33 sub-surveyors and 25 route modules.

This document describes **shape**: layers, boundaries, and how work flows through them. It
deliberately does not enumerate every module, because the previous revision did and that is
precisely what went stale — 157 modules existed that it did not mention. Directories and
responsibilities change slowly; file lists change weekly.

- Conventions and rules for *working on* this code: [`../CLAUDE.md`](../CLAUDE.md)
- Getting it running: [the workspace quickstart](../../../QUICKSTART.md)
- What is being worked on: [`Backlog.md`](Backlog.md)

---

## Overview

Resource Explorer discovers, understands and catalogs information resources — Git
repositories, PostgreSQL databases and file systems — using [Egeria](https://egeria-project.org/)
as the catalog of record.

**Egeria-first, but not Egeria-dependent.** Every survey result that can be written to Egeria
should be. Local storage is a cache and a queue, so the tool keeps working while Egeria is
unreachable and reconciles afterwards. RAG-based querying needs no Egeria at all.

Two layers:

1. **Survey layer** — collects structure and metadata from resources, writes locally, and
   publishes to Egeria.
2. **Query layer** — answers natural-language questions from survey metadata, RAG over
   pgvector, and specialist agents.

---

## Storage

**The registry is PostgreSQL by default**, in a named `resource_explorer` schema inside the
`egeria_advisor` database shared with Egeria Advisor. SQLite remains a supported fallback via
`REGISTRY_DATABASE_URL` — used by tests and single-user setups. Both are driven through the
same `ProjectRegistry` API; nothing above it knows which is underneath.

*(The previous revision claimed "all persistent state lives in a single SQLite file". That
stopped being true when the shared Postgres instance arrived, and the claim survived because
nothing tested it.)*

Vector data lives in the same Postgres via pgvector, in per-resource collections named
`{slug}_{collection_type}`, created lazily on first insert.

### Table families

51 tables, which group into six families rather than needing individual description:

| Family | Examples | Shape |
|---|---|---|
| **Resource identity** | `projects`, `databases`, `file_systems`, `db_servers`, `project_aliases`, `project_groups` | One row per registered resource |
| **Collected facts** | `project_stats`, `project_commits`, `project_file_inventory`, `project_code_symbols`, `project_dependencies` | Refreshed in place or appended per run |
| **Analysis results** | `project_analysis_findings`, `project_analysis_metrics`, `project_file_type_counts` | Append-only, `surveyed_at`-stamped, latest-batch reads |
| **Human judgement** | `resource_context`, `resource_tags`, `resource_feedback`, `resource_curator_notes`, `repo_dispositions`, `investigations` | What a person decided, never inferred |
| **Machine attention** | `resource_schedules`, `notification_subscriptions`, `rfa_actions` | Recurring work and its delivery |
| **Egeria linkage** | `project_egeria_surveys`, `entity_egeria_project_context`, `egeria_linkage_status`, `survey_definition_cache` | What is published, and what Egeria said |

Two properties matter more than the list:

- **Analysis results are append-only.** A survey run does not overwrite its predecessor; it
  adds a `surveyed_at`-stamped batch. History is the point — trends, and "what changed since
  last time", both depend on it.
- **Collected facts and analysis results are different tables on purpose.** Most analyses do
  not write to `project_analysis_findings`; they read `project_stats` or the file inventory and
  report over it. Assuming the findings table is where results live is a mistake that has been
  made twice, most recently by the context compiler.

---

## Directory map

```
resource_explorer/
├── registry.py             # every table, every read/write. Postgres or SQLite.
├── config.py               # Pydantic settings
├── scheduler.py            # daemon thread — runs due schedules, fires subscriptions
├── facts.py                # FactLayer: reads what is known, never runs anything
├── step_outcome.py         # recovered / partial / no_signal / unverified / regression
│   surveyors/result_status.py   # measured / nothing_found / not_established / never_run / …
│
├── rag_system.py           # query orchestrator
├── query_processor.py      # intent classification + agent routing
├── collection_router.py    # which pgvector collections a query needs
├── context_compile.py      # question → ContextSpec → packed context + manifest
│
├── github/                 # API client, stats fetcher, org importer, source cache
├── ingestion/              # repo → chunks → pgvector; incremental re-index
├── agents/                 # BeeAI specialist agents (stats, code, doc, health, …)
├── surveyors/              # the survey layer — see below
├── web/                    # FastAPI app, 25 route modules, single-page UI
├── cli/                    # Typer CLI
└── observability/          # MLflow, Phoenix, metrics
```

Shared libraries live outside this package and are imported: `trellis-vectorstore`,
`trellis-context`, `trellis-artifact-tree`, `trellis-microflow`, `trellis-querycache`,
`trellis-auth`. See the [workspace architecture](../../../docs/trellis-architecture.md).

---

## The survey layer

### Three concepts, deliberately distinct

Conflating these has caused real bugs, so they are named precisely:

| Concept | What it is | Where it lives |
|---|---|---|
| **Survey Definition** | A named, ordered graph of steps — "run these, in this order" | Egeria, as a `GovernanceActionProcess`; mirrored locally in authored Dr.Egeria documents |
| **Step** (microflow) | One unit of work — "classify the languages" | `surveyors/sub_surveyors/`, 33 of them, keyed by a step name like `repo_health` |
| **Analysis** | A catalog entry describing a result a person can look at | `configdata/analysis_catalog.yaml`, tagged by intent |

An analysis usually maps to one step, occasionally to several, and four steps have no analysis
at all. They are not synonyms and the mapping is explicit
(`REPO_ANALYSIS_STEP_MAP`, `REPO_ANALYSIS_RESULTS_MAP`).

### Flow

```
SurveyOrchestrator.run(slug, steps=None)
  → resolves steps (all, or a named subset)
  → acquires shared resources once (zipball, git clone) via trellis-microflow
  → runs each step → Annotation objects
  → writes results to the step's own table
  → writes ONE activity_log entry
  → optionally publishes to Egeria
```

`steps=None` runs everything; a list runs exactly those. That parameter is what lets a single
analysis, a whole Survey Definition, or a scheduled bundle all share one execution path.

**Resources are acquired once per run, not once per step.** A zipball download shared across
eleven steps is the difference between a survey taking 14 seconds and 110.

### Two coordinators, neither of which is RE

RE is not a workflow engine. Either **Egeria coordinates** and RE executes leaf steps as an
engine host, or **RE coordinates** and hands the graph to **Prefect**. Each step declares
`executes_at: resource-explorer | prefect | egeria`. With Prefect unreachable, steps fall back
to running in-process — safe, one connection attempt slower.

### Publishing

`EgeriaPublisher` finds or creates a `SourceControlLibrary` asset by exact `qualifiedName`,
then attaches a `SurveyReport` and one annotation per result. The exact-match search is load-
bearing: a prefix match once made two sibling repos share an asset, and each other's findings.

---

## The query layer

```
Query (web / CLI / A2A)
  → QueryCache                        hit → return
  → QueryProcessor.classify()
      ├── survey_meta → answered from the registry, no vector search
      ├── statistical / comparison / examples / code_search / conceptual / health → specialist agent
      └── general → RAG (CollectionRouter → pgvector → LLM)
  → optionally: compiled evidence (see below)
  → LLM generation
  → async: tracing, metrics, cache store
```

`survey_meta` is evaluated first and never touches pgvector — "when was this last surveyed"
is a registry read, and routing it through retrieval would be slower and worse.

### Compiled context

A newer path, and the one that changes answer quality most. `context_compile.py` turns a
question into a `ContextSpec`: the question catalog already maps Purpose and Perspective to
questions and to the analyses that answer them, so those analyses become **sections**, stored
results become **candidates**, and `trellis-context` packs what fits a character budget.

What it returns alongside the text matters as much as the text:

- **manifest** — what was packed and at which rung, what was dropped for budget, and what is
  **missing**
- **derivation** — why each section is there: this Purpose ranked that question, which
  dispatches this analysis

Sections resolve through the **fact layer**, not raw results, so a gap distinguishes *never
ran* from *ran and found nothing*. Nothing is executed to fill a gap — a compile never blocks
on a survey.

---

## Cross-cutting: absence is a first-class result

The single most common bug class in this codebase is **a result that looks like an answer and
is not**. Three vocabularies exist to prevent it, and they are not interchangeable:

- `surveyors/result_status.py` — `measured` / `nothing_found` / `not_established` /
  `never_run`, plus `skipped_by_design` and `misgrouped` for results that are absent on
  purpose rather than by failure
- `step_outcome.py` — `recovered` / `partial` / `no_signal` / `unverified` / `regression`,
  where `CONCLUSIVE` deliberately excludes `unverified`
- The compile manifest's **gaps**, which name analyses with no stored result

A zero from an analysis that never ran and a zero from one that ran and found nothing are
different facts. Surfaces that flatten them produce confident wrong answers, which is worse
than an error because nothing looks broken.

---

## The eight intents

`scouting` · `discovery` · `assessment` · `analysis` · `enrichment` · `understanding` ·
`curate` · `automate`

These are canonical strings, used in the activity log, UI filters, analysis catalog tags and
query routing. The axis that separates the early stages is **does this collect, or does it
reason over what is already collected** — not evaluative-versus-structural. See `CLAUDE.md`
rule 17, which carries the full reasoning and its exceptions.

---

## The activity log

Every scout, survey, catalog, publish and RFA operation writes an entry. It is the audit
trail and the UI's history view, and it is also load-bearing for correctness: the
"was this ever published?" check that distinguishes *lost an asset* from *never catalogued*
reads it rather than guessing.

---

## Key design rules

The full numbered list lives in [`../CLAUDE.md`](../CLAUDE.md) and is not duplicated here —
one copy, deliberately. The ones with the most architectural reach:

- Classify intent before touching the vector store (rule 1)
- Activity log entries for **all** operations, not just Egeria publishes (rule 16)
- The eight intent labels are canonical (rule 17)
- `HybridDatabaseSurveyor` must run the local scan immediately after triggering Egeria's
  async native survey (rule 15)
