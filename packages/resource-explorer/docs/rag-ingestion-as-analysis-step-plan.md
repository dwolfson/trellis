# Convert RAG ingestion into an Analysis-tier survey step

**Status: planned, not started. Written 2026-08-20 for execution in a separate session.**

## Why

`project_code_symbols`, `project_file_inventory` and `project_stats` each had the
same defect, found and fixed separately over 2026-08-19/20: a table that many
survey steps *read* but that no survey step *wrote*. Each was populated only by
RAG ingestion, `IncrementalIndexer`, or a registration-time side effect, so the
steps depending on it silently reported whatever an earlier, unrelated run had
left behind. Each was fixed the same way — by turning the implicit prerequisite
into a declared, ordered, re-runnable step (`repo_symbol_extraction`,
`repo_file_inventory`, `repo_git_statistics`).

**RAG ingestion is the last and largest instance of that pattern.** It populates
the pgvector collections that Chat, the query router and every RAG-backed answer
depend on, and it is not a survey step. It runs at registration
(`cli/wizard.py`), on webhook, from the scheduler, and from a bespoke on-demand
route branch — never as part of a survey, never with a survey's freshness
signal, never with results.

Two things make this more than tidiness:

1. **Analysis is where the repo's queryable representation gets built.** Every
   other stage produces annotations *about* a repo. Analysis additionally
   produces the thing Understanding and Chat *interrogate*. Ingestion is that
   production step, and it is currently invisible to the survey model.
2. **It is by far the most expensive operation here.** Embedding a large repo
   dwarfs a git-statistics pass (which itself takes ~7 minutes against
   odpi/egeria at full fidelity). Any future "compose a survey by budget" work
   needs ingestion to be a first-class step with declared cost, not a side
   effect that happens elsewhere.

## What already exists (do not rebuild)

Verified against the tree on 2026-08-20:

- **`analysis_catalog.yaml` already has `rag_ingestion`** — `intent: analysis`,
  `action: ingest`, `run_time: minutes`, `target_shape: whole_resource_only`,
  `annotation_types: []`, `recommended: false`,
  `egeria_registration.candidate: false`. **Do not add a new catalog entry.**
- **It is already dispatchable** two ways, both via an `action == "ingest"`
  special case rather than the step map:
  - `scheduler.py:287` — its own branch in `_run_repo_survey`, documented in that
    module's header (schedulable, unlike `action: "publish"`).
  - `web/routes/projects.py:695` — same check in the per-analysis run route,
    calling `IncrementalIndexer().refresh(project)` then
    `QueryCache().invalidate_project(slug)`.
- **`IncrementalIndexer.refresh(project)`** (`ingestion/incremental.py:40`) is the
  incremental path: compares `project.last_commit_sha` against the repo's latest
  SHA, does nothing when unchanged (but still profiles data files if that never
  ran), otherwise re-embeds only collections touched by changed files.
- **`IngestionPipeline.run(...)`** (`ingestion/pipeline.py:47`) is the full path,
  used at registration.
- `rag_ingestion` is **not** in `ANALYSIS_KINDS` and has **no results reader** —
  confirmed. That is the gap this plan closes.

## Decisions

**D1 — New step `repo_rag_ingestion`, wrapping `IncrementalIndexer.refresh()`,
not `IngestionPipeline.run()`.** The incremental path is the correct semantics
for a repeatable survey step: it is a no-op when the SHA is unchanged, which
makes the step cheap to include in a survey that runs often. Full ingestion stays
where it is, at registration — a survey step must never be the thing that decides
to embed a repo from scratch for the first time.

**D2 — `requires_resources={}`, i.e. no shared zipball.** `IncrementalIndexer`
downloads its own zipball (`incremental.py:114-125`) *conditionally* — only when
there are changed files. Declaring `zipball_root` would force a download on every
run including the no-op case, making the cheap path expensive. This is a
deliberate divergence from `repo_symbol_extraction`/`repo_file_inventory`, and
the reason must be written into the step's docstring: **the resource-sharing win
does not apply to a step whose common case is fetching nothing at all.**

**D3 — Ordered LAST in `STEP_REGISTRY`.** Unlike the other three microflow steps,
nothing downstream reads what this writes — pgvector is consumed by Chat and the
query router, not by other survey steps. Placing it last means an expensive,
optional step never delays the cheap signals that a survey exists to produce.
`STEP_REGISTRY` order is also "Full Survey (all steps)" order (the `*` sentinel in
`repo_survey_types.csv`), so this is load-bearing, not cosmetic.

**D4 — Results reader reporting what is actually in pgvector, not what the run
did.** `MultiCollectionStore.count(collection)` (`vector_store_pg.py:213`) gives
live per-collection entity counts; `Project.collections` gives the per-project
collection names (e.g. `['egeria_git_markdown_docs', 'egeria_git_release_notes',
'egeria_git_java_code']`). A results view built from those answers the question a
user actually has — "is my chat index current, and how big is it?" — and stays
correct even when the step no-ops. Render mode `"metrics"`; no new table.

**D5 — Keep both existing dispatch paths working unchanged.** The
`action == "ingest"` branches in `scheduler.py` and `projects.py` must keep
functioning: existing schedules reference `rag_ingestion` by analysis id, and the
Analysis card's Run button uses that route. This plan *adds* a survey-step path;
it does not migrate the others. Removing them is a separate follow-up once the
step has proven itself, and should not be attempted here.

**D6 — Not added to any existing Survey Definition by default.** It joins "Full
Survey (all steps)" automatically via the `*` sentinel, which is correct — that
bundle is explicitly the everything case. It must **not** be added to Scouting
Survey, Coarse Profile Survey, Git Statistics Survey or Repo Discovery Survey:
those are fast tiers and this is the most expensive step in the system. A future
"Analysis Survey" is the natural home, and is out of scope here.

## Implementation

Follow `resource_explorer/surveyors/sub_surveyors/git_statistics.py` as the
closest template — it is the most recent of the three microflow steps and has the
same shape (wrap an existing operation, report what it did, degrade to a
reported failure rather than raising).

1. **`resource_explorer/surveyors/sub_surveyors/rag_ingestion.py`** (new).
   `RagIngestionSurveyor(BaseSurveyor)`, `STEP = "RagIngestion"`,
   `__init__(self, project, registry, surveyed_at=None)`.
   `run()`:
   - call `IncrementalIndexer().refresh(self.project)`
   - call `QueryCache().invalidate_project(slug)` — the existing route does this
     and the step must not silently skip it, or chat answers serve stale cache
   - read live counts via `MultiCollectionStore().count(c)` for each
     `project.collections`
   - return one `ResourceMeasureAnnotation` with `resource_properties`:
     `{collection_name: count, ..., "total_chunks": N, "collections": len(...),
     "last_commit_sha": project.last_commit_sha, "ingested": bool}`
   - wrap the refresh in try/except; on failure emit a `confidence=0` annotation
     naming the error rather than raising (matches `git_statistics.py` exactly).

2. **`sub_surveyors/__init__.py`** — import + `__all__` entry.

3. **`repo_survey_definition_adapter.py`**:
   - import `RagIngestionSurveyor` into the grouped sub-surveyor import
   - add `"repo_rag_ingestion": StepInfo(...)` **as the last entry** of
     `STEP_REGISTRY`, `accepts_surveyed_at=True`, no `requires_resources`
   - add `"rag_ingestion"` to `ANALYSIS_KINDS` mapping to `["repo_rag_ingestion"]`
     with `results=AnalysisKindResults(_rag_ingestion_results,
     _rag_ingestion_trend, "metrics", headline_reader=_rag_ingestion_headline)`
   - write those three readers next to `_api_structure_results` and friends.
     Trend: chunk count over time via `query_metrics_history(slug,
     "rag_ingestion", "total_chunks")` — which means the surveyor must also
     `registry.upsert_metric(slug, "rag_ingestion", {...}, surveyed_at=...)`,
     same as `health.py` now does. Headline: `"{N} chunk(s) across {M}
     collection(s)"`, status `ok`/`gap` on whether anything is indexed.

4. **`docs/dr-egeria/repo_survey_types.csv`** — no edit needed. The `*` sentinel
   picks the step up for `RepoFullSurvey` automatically. Regenerate and re-author
   (see Verification).

5. **`tests/test_rag_ingestion_surveyor.py`** (new), modelled on
   `tests/test_git_statistics_surveyor.py`.

## Verification

Run in this order; do not skip the live steps.

- `uv run pytest tests/ -q` — full suite green. Expect
  `test_all_step_keys_are_registered` in
  `tests/test_repo_survey_definition_adapter.py` to fail until you add
  `repo_rag_ingestion` to its exhaustive set. **That failure is correct** — it is
  a registry-completeness guard doing its job. Update it, do not weaken it.
- New unit tests: refresh is called; `QueryCache.invalidate_project` is called;
  a refresh failure produces a `confidence=0` annotation rather than raising;
  counts come from `MultiCollectionStore.count`, mocked.
- Ordering test, mirroring the one in `test_repo_survey_definition_adapter.py`:
  `repo_rag_ingestion` is **last** in `STEP_REGISTRY`.
- `uv run python scripts/generate_repo_survey_definition.py` — confirm Full
  Survey goes 20 → 21 steps and no other definition changes.
- Author in Egeria and reconcile — **both, in this order, always**:
  ```
  cd docs/dr-egeria/survey-definitions
  <venv>/bin/dr_egeria --process --summary-only repo-survey-definition-full.md
  cd ../../..
  <venv>/bin/python scripts/reconcile_survey_definition_links.py --dry-run   # inspect
  <venv>/bin/python scripts/reconcile_survey_definition_links.py             # apply
  <venv>/bin/python scripts/reconcile_survey_definition_links.py --dry-run   # confirm 0 duplicates
  ```
  Dr.Egeria's `Link First/Next Process Step` commands are **not idempotent** —
  re-authoring an already-linked process duplicates every edge, which makes each
  step look "branching" and takes the whole Survey Definition out of service.
  Reconciling is not optional. It requires `pyegeria >= 6.0.18.4`; on older
  versions its deletes silently no-op while reporting success.
- Live: run the step alone against a real repo and confirm (a) a no-op when the
  SHA is unchanged, (b) a real re-embed after a change, (c) the Analysis Results
  card populates with chunk counts.

## Known hazards in this codebase

Learned the hard way over 2026-08-19/20; each cost real time.

- **The candidates endpoint caches for 300s.** After authoring a Survey
  Definition, restart the web server before checking the UI, or you will see the
  old list and conclude the authoring failed.
- **`git status` before building anything.** Work committed in an earlier session
  was rebuilt from scratch once in this session because `git log <file>` was not
  checked first, producing a duplicate function definition.
- **Grep for the call, not the name.** A claim that five surveyors called
  `StatsFetcher().fetch()` came from matching the word in docstrings that said
  "already fetched by StatsFetcher, no new API call". There was one real call.
- **Do not edit `packages/egeria-advisor/data/repos/egeria-python`.** It is RAG
  corpus data, not a working repo. The real checkout is
  `/Users/dwolfson/localGit/egeria-python`.
- **`git commit -s`** — DCO sign-off is required in this repo.

## Out of scope

Named so they are not attempted opportunistically:

- Retiring the `action == "ingest"` branches in `scheduler.py`/`projects.py` (D5).
- An "Analysis Survey" survey type grouping the analysis-tier steps (D6).
- Step-level cost/tier metadata so surveys can be composed by budget. This step
  is the strongest argument for it, but it is a design change across
  `StepInfo`, the CSV and the scheduler.
- Ingesting the project's external website (`projects.homepage_url`, populated by
  `repo_homepage`) into the vector store. Real, wanted, and a separate piece of
  work — the docs site explains what a project is *for* in a way the source tree
  does not.
