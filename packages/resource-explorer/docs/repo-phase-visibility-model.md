# Repo phase / visibility-source / publish model

Working reference for how the seven-intent model applies specifically to
**repos**, worked out across a live-testing session that started from one
question ("what does 'Refresh & profile' actually mean?") and ended up
grounding the whole Scouting → Enrichment lifecycle. Kept here so the
reasoning doesn't have to be re-derived next time — update this file as the
model evolves, don't let it go stale.

## The five visibility sources

Every repo-analysis capability ultimately reads from one of these. Naming
them explicitly is what made the phase boundaries fall out cleanly:

1. **GitHub API** — stars, forks, contributors, `pushed_at`, etc. Cheap,
   already self-refreshing (`StatsFetcher`, `HealthSurveyor`'s auto-refresh).
2. **Zipball content analysis** — requires downloading the repo:
   - **2a — file inventory**: type, size, last-update, path shape. Refreshed
     by `IngestionPipeline.refresh_profile()` (→ `project_file_inventory`).
   - **2b — language/classification analysis**: file-type and language
     breakdown, computed *from* 2a's data by `FileClassifierSurveyor`/
     `LanguageSurveyor`/`FileStructureSurveyor` (→ `project_file_type_counts`).
     This is a **survey that interprets 2a's data**, not a data-fetch itself —
     see "Refresh vs. survey" below.
   - **2c — vector/AI content analysis**: chunked + embedded into pgvector,
     refreshed independently via `IncrementalIndexer` ("Refresh & Re-ingest").
   - **2d/2e — other and cross-repo analysis**: not built.
3. **What Egeria already knows** — existing catalog relationships, lineage,
   related assets. Not yet consumed anywhere in RE's own analysis; a future
   read-path.
4. **User-supplied context** — Enrichment's Context form: ownership,
   sensitivity, environment. Never derivable from the repo itself.
5. **Curate-tier commentary** — tags, feedback, curator notes, ratings/
   journal (mentioned, not yet built) — layered on top of an already-
   catalogued resource, not itself a visibility source.

## Refresh vs. survey — the distinction that mattered most

Two different kinds of action get conflated easily, and conflating them was
the root of the original "Refresh & profile" confusion:

- **Refresh** = update the substrate. No interpretation, no annotations, no
  findings table. `IngestionPipeline.refresh_profile()` (2a), `IncrementalIndexer.refresh()`
  (2c) are refreshes — same category as each other, different category from
  everything below.
- **Survey** = read the substrate and produce `Annotation`s / findings,
  via a `SurveyOrchestrator.run(slug, steps=[...])` call. `FileClassifierSurveyor`
  (2b), `SecurityHygieneSurveyor`, `ApiStructureSurveyor`, etc. are surveys.

A survey can silently read *stale* substrate if nothing refreshed it first —
this was the exact mechanism behind three intents' worth of frozen data
(`project_code_symbols` was written only at initial ingestion, never by any
refresh path, until the Coarse Profile tab's `include_symbols` option closed that
gap). Whenever adding a new capability, ask which category it is before
building it — the two need different triggers, different scheduling
treatment (`action: profile`/`ingest` vs. a `steps=[...]` survey run), and
arguably different UI (a plain "Refresh" button vs. a results-bearing card).

## Phase × visibility-source × publish-scope matrix

| Phase (UI) | Visibility source(s) | Action(s) | Kind | Publish scope (if chosen) |
|---|---|---|---|---|
| **Scouting → Survey tab** | ① GitHub API only | `repository_health` (`repo_health` step) | Survey | `steps=["repo_health"]` — minimal catalog entry (asset register/find + one `repository_health` annotation). This is what "Publish registration only" sends. |
| **Scouting → Coarse Profile tab** | ②a (file inventory) + ②b (classification), auto-chained | `repo_profile_refresh` (refresh) → `language_file_classification` (`repo_language`+`repo_file_classification`+`repo_file_structure`, survey) | Refresh, then survey | `steps=["repo_language","repo_file_classification","repo_file_structure","repo_data_profiling"]` — "Publish this phase's findings" |
| **Assessment** | Existing tables only — no new fetch, deeper analytics | `security_scan`, `documentation_coverage`, `dependency_analysis` | Survey | Findings annotations; optionally catalog specific sub-resources (folders/files) as child assets — **not built, roadmap only** |
| **Analysis** | ②c (vector/AI) + ②d/②e (other/cross-repo, not built) | `rag_ingestion` (refresh), `api_structure` (survey) | Refresh + survey | Deeper metrics/trend annotations |
| **Enrichment** | ④ user-supplied context | Context form | Human input | Asset property updates, relationships |
| **Curate** | ⑤ commentary layer | Tags/feedback/notes | Human input | Not a publish action in the survey sense |

`egeria_publish` (the original, unscoped "Publish to Egeria Catalog" button,
still on the deep report view) is `steps=None` — full survey, all annotations,
one `SurveyReport`. Every phase-scoped publish above reuses the exact same
`POST /{slug}/publish` route with a non-empty `steps` list — no separate
publish mechanism was built; see `PublishRequest.steps` in `web/routes/egeria.py`.

**Updated 2026-08-27 — this was accurate for the Assessment/Analysis "Run →" flow described
above, but not the whole picture.** The deferred "default to publish, opt out for exploratory
work" flag this note used to describe is now built, but implemented as a project-assignment
gate rather than an opt-out toggle: both this route (`projects.py`'s `run_single_analysis`) and
Survey Definition runs (`survey_definition_executor.py`, used by the Discovery tab and Scouting
scans) now auto-publish to Egeria via `EgeriaPublisher.publish()` whenever the survey produced
annotations AND `ProjectRegistry.has_assigned_egeria_project()` is true for the resource — i.e.
publish happens automatically once a human has decided the resource belongs in Egeria
(`entity_egeria_project_context.status == "linked"`), and stays local-only otherwise. Manual
publish via the button described above still works regardless, for re-publishing or explicitly
cataloging an unassigned resource.

Worth knowing this correction exists: the Survey Definition path had actually been publishing
**unconditionally** — no gate at all, not even the loose one this route already had — until this
same pass added `has_assigned_egeria_project()` to it too, so both paths are consistent now.

## The three-way "Discovery" naming collision

Resolved once, worth restating so it doesn't get re-litigated by accident:

1. **Canonical `discovery` nav intent** (top-level tab) — launches Egeria
   Survey Definitions (`survey_definitions.py`). By design has zero
   `analysis_catalog.yaml` entries (CLAUDE.md rule 17).
2. **Scouting's "Discover" sub-tab** — finding *new* candidate repos to
   scout (search/list discovery sources). Unrelated to #1.
3. **The informal usage** ("download the zipball, look at file/language
   shape") from early design discussion — this is what visibility sources
   2a/2b actually are. It is **not** built under either #1 or #2's label.
   It lives as Scouting's **"Coarse Profile"** sub-tab instead, specifically to
   avoid colliding with #1/#2. If you hear "Discovery" used loosely in
   conversation, check which of these three is actually meant.

## `ANALYSIS_KINDS` step-key vocabulary (repo_survey_definition_adapter.py)

The single source of truth `REPO_ANALYSIS_STEP_MAP`/`REPO_ANALYSIS_RESULTS_MAP`
are derived from, kept here as a flat lookup table:

| `analysis_id` | step key(s) | family | has results view |
|---|---|---|---|
| `language_file_classification` | `repo_language`, `repo_file_classification`, `repo_file_structure` | — | ✅ (added with the Coarse Profile tab) |
| `repository_health` | `repo_health` | — | ❌ (covered by Scouting overview's own stat cards) |
| `dependency_analysis` | `repo_dependency` | — | ✅ |
| `security_scan` | `repo_security` | `security` | ✅ |
| `documentation_coverage` | `repo_documentation` | — | ✅ |
| `data_file_profiling` | `repo_data_profiling` | — | ✅ |
| `api_structure` | `repo_api_structure` | — | ✅ |
| `rag_ingestion` | *(not a survey step — `action: ingest`, dispatches to `IncrementalIndexer`)* | — | ❌ |
| `repo_profile_refresh` | *(not a survey step — `action: profile`, dispatches to `IngestionPipeline.refresh_profile()`)* | — | n/a (chains into `language_file_classification`'s results) |
| `egeria_publish` | *(not a survey step — `action: publish`, explicit write, excluded from scheduling)* | — | n/a |

`repo_file_size` has no catalog entry at all — never independently
schedulable/runnable, stays bundled only in a full `steps=None` survey.
