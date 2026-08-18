# Survey Type / Question-driven perspectives / report-spec data-fetching / step-implementation mapping

**Status: design pass complete (2026-08-16), not yet built. Four independent, loosely-coupled threads — see "Sequencing" at the end for a suggested build order.**

## Context

Follow-on from the RFA/Egeria-ToDo-sync work (`docs/rfa-egeria-todo-followup.md`) and D5's microflow restructuring. Survey Types are Egeria-native `GovernanceActionProcess` objects (matching the already-real "Repo Coarse Scout" precedent, authored via Dr.Egeria — see `docs/unified-survey-execution-model-plan.md`), not a new local RE construct. This doc closes out the four open threads named when that was settled:

1. Resource-type as a third visibility dimension (Repo/DB/FS), alongside funnel-phase and perspective.
2. Perspective-gated analysis composition should be Question-driven (via the existing `ScopedBy` Question/Perspective graph), not `AnalysisKind.family`-driven.
3. Report-spec construction needs a way to know how to fetch each annotation's data.
4. Mapping each microflow step to its actual execution mechanism (RE-local Python, Prefect, or a real Egeria Governance Service).

## 1. Resource-type as a many-to-many dimension on `AnalysisKind`

**Decision:** `AnalysisKind.resource_type` becomes `list[str]`, not a single string — a given analysis (e.g. file/language classification) can legitimately apply to more than one resource type (Repo and FS both have a file tree; DB doesn't). Default `["repo"]` for every existing repo-only entry (no behavior change for what exists today); a shared analysis declares `["repo", "filesystem"]` once it's built.

**Backlog, not built now:** `analysis_catalog.yaml` itself outgrowing plain YAML — noted as a real future need (more structure than a flat file comfortably carries once resource-type, perspective-question mapping, and family all compose), explicitly low priority. No format migration planned in this pass; the list-valued `resource_type` field works fine in YAML as-is.

**Implementation:** `repo_survey_definition_adapter.py`'s `AnalysisKind` dataclass (D2 of the analysis-kind-extensibility work) gains `resource_type: list[str] = field(default_factory=lambda: ["repo"])`. Any UI/route filtering that currently assumes one resource type per `AnalysisKind` needs a `resource_type in kind.resource_type` check instead of `==`. No schema/table changes — this is a catalog-metadata field, not persisted per-run data.

## 2. Question-driven perspective composition via `ScopedBy` — and per-perspective answer overrides

**Decision (corrected from the first pass):** perspective-gated composition is already substantially built as data, not a new mechanism to invent. `docs/dr-egeria/resource_questions.csv` (42 rows) — read via `question_catalog_reader.py` into `QuestionCatalogEntry` — already carries per-perspective relevance as one `X` column per perspective (Financial/Governance/Steward/Data Owner/Consumer/App-AI Builder/Privacy/Community/Data Expert/Security/Architecture/Admin) against each question, plus `Answering Analysis`/`Answering Mechanism` columns. This *is* the CSV the ScopedBy/Question/Perspective graph in Egeria itself mirrors (per the lineage note in `[[egeria-resource-explorer-redesign]]`'s "Unification Thread" — Question/Perspective/ScopedBy were first prototyped in this CSV-driven form before propagating into Egeria as native types).

**The real gap:** today one CSV row has exactly one `Answering Analysis`/`Answering Mechanism` pair, applied uniformly to every perspective marked `X` on that row. That's wrong for questions whose *meaning* genuinely differs by perspective — "how much does it cost to run this?" means something different to Financial (cloud spend, licensing) than to Architecture (compute/complexity cost). A single answering-analysis column can't represent that.

**Fix — extend the CSV schema, not the code architecture:** add per-perspective override columns, sparse (only populated where a perspective's interpretation genuinely diverges from the row's default `Answering Analysis`/`Answering Mechanism`). Two reasonable shapes, pick one when building:
- (a) A second pair of columns per perspective that needs an override (`Financial: Answering Analysis`, `Financial: Answering Mechanism`, ...) — verbose but keeps the CSV flat and diffable.
- (b) A single `Perspective Overrides` column holding a compact `perspective:analysis_id` list (e.g. `Financial:cost_estimation_analysis; Architecture:compute_complexity_analysis`), parsed by `csv_to_question_catalog_yaml.py` into `QuestionAnswering`'s existing structure plus a new `overrides: dict[str, QuestionAnswering]` field.

`QuestionCatalogEntry.answering` stays the default; a new `answering_for(perspective: str) -> QuestionAnswering` method returns the override when one exists for that perspective, else falls through to the default — this is the one code change needed in `question_catalog_reader.py`; `csv_to_question_catalog_yaml.py` needs to parse whichever column shape is chosen.

**Not built now, explicitly deferred per discussion:** which questions actually need an override (only "cost" was named as a confirmed example) — that's a content pass over the 42-row CSV, not a schema question, and should happen incrementally as specific perspective/question mismatches are actually noticed in use, not as an upfront audit.

## 3. Report-spec data-fetching — matches EA's existing `action_function` model

**Decision:** no new architecture. Confirmed against `[[egeria-advisor-report-spec-design]]`'s existing model: a `ReportSpec`'s `action_function` (the "FROM") plus optional `detail_specs` (sequential sub-queries, the "analysis function that does some processing") is exactly the shape described — `AnalysisStep` produces `Annotation`s of a given `AnnotationType`, stored to RE and/or Egeria; a report spec's `action_function` retrieves them (parameterized for filter/scope), and an optional post-processing step derives further attributes.

**The real gap:** most existing report specs use plain pyegeria `find`/`get` calls as their `action_function` — none yet fetch RE's own survey `Annotation`/`SurveyReport` data (local SQLite tables, or Egeria's `Annotation` graph once published). Closing this is **new `action_function` implementations**, not new architecture:
- One family of `action_function`s reading RE's local generic `project_analysis_findings`/`project_analysis_metrics` tables (from the analysis-kind-extensibility work), parameterized by `kind` — the RE-local, always-current path.
- One family reading Egeria's `Annotation`/`SurveyReport` graph directly via pyegeria, for report specs that need the Egeria-of-record view (post-publish) rather than RE's local cache.
- These compose with the saved-queries work already in flight (per the report-spec design memory) — a saved query is itself a natural `action_function` candidate once that mechanism exists.

**Not built now:** the specific new `action_function`s — this is implementation work to do as each report spec that needs survey-annotation data is actually authored, not a batch to build speculatively ahead of demand.

## 4. Step-implementation mapping — SUPERSEDED, see `re-as-engine-host-plan.md`

**This section is superseded (2026-08-17).** The `EmbeddedProcess`/`Link Action to Action Executor` split described below was overtaken by a better architecture: modeling RE itself as a registered Egeria Governance Engine that claims `GovernanceActionExecutor`-wired steps like any other engine. Under that model, RE-hosted steps use the exact same native mechanism as Egeria-engine steps — no `EmbeddedProcess` authoring gap to fill at all. See `docs/re-as-engine-host-plan.md` for the full design (execution-permutation matrix, the reachability dimension, and the concrete pyegeria/Egeria gaps — filed as `PYEGERIA_ISSUES.md` ISSUE-49, which downgrades ISSUE-48 below to a lower-priority, independent design-time-authoring gap rather than a blocker).

Original text kept for reference:

**Decision:** a Survey Definition step's implementation is declared via one of two Egeria-native mechanisms, chosen by where the step actually executes — not a single universal mechanism:

- **Steps executed by a real Egeria Governance Service, on an Egeria Engine Host** → `Link Action to Action Executor` (`GovernanceActionExecutorProperties`, already supported in pyegeria's `ActionAuthor.link_governance_action_executor()`, added 2026-07-15 — **flagged in `egeria-python/CLAUDE.md` as not yet verified against a live server**). Its own javadoc scopes it explicitly to "the governance engine that it will call" — genuinely the right mechanism for this case, not a workaround.
- **Steps executed elsewhere** (RE-local Python via `survey_definition_executor.py`'s sub-surveyor dispatch, or a future Prefect flow) → a real, design-time `EmbeddedProcess` element (`EmbeddedProcessProperties`, base type — **not** its `TransientEmbeddedProcess` subtype, which is Egeria's auto-created *runtime instance* record for a process that already ran, parent of `FunctionCallProperties`/`AnalyticsModelRunProperties`/`GovernanceActionProcessInstanceProperties`). Confirmed via direct Java source read (`EmbeddedProcessProperties extends ActionProperties`, sibling of `ToDoProperties`/`ReviewProperties` — the "Action" family, not the `GovernanceDefinition` family Action Author's other 7 commands author into) that the base type is the right slot for a persistent "what implements this, and how" declaration; nothing in Dr.Egeria authors it today.

**RE's own migration, once pyegeria/Dr.Egeria support exists (tracked as `PYEGERIA_ISSUES.md` ISSUE-48, filed this session):** `survey_definition_reader.py`'s local `additionalProperties.executes_at`/`re_analysis_step` convention (invisible to any other Egeria client) migrates onto the real relationship — `executes_at="resource-explorer"` becomes a link to an `EmbeddedProcess` element representing RE's own dispatch mechanism; `executes_at="egeria"` steps (if any end up being real Governance Service calls) become `Link Action to Action Executor` links instead. This is blocked on ISSUE-48's authoring support landing in pyegeria/Dr.Egeria — not started, not startable, until then.

## Sequencing

These four threads are independent and can land in any order or in parallel:

1. **#1 (resource_type list)** — smallest, self-contained, no external dependency. Good first pick if picking one to start.
2. **#3 (report-spec action_functions)** — build incrementally, driven by actual report-spec authoring demand, not as a batch.
3. **#2 (CSV per-perspective overrides)** — schema + reader change is small; content-filling (which questions need overrides) happens incrementally as real perspective/question mismatches surface.
4. **#4 (EmbeddedProcess)** — blocked on pyegeria/Dr.Egeria authoring support (ISSUE-48). Nothing to build on the RE side until that lands; `Link Action to Action Executor`'s live-server verification (also part of ISSUE-48) is independent and could happen sooner.

## Verification

- #1: unit test — an `AnalysisKind` with `resource_type=["repo", "filesystem"]` is selected for both facets, excluded for `"database"`; existing single-resource-type entries keep their exact current filtering behavior (regression guard, `resource_type=["repo"]` default).
- #2: unit test — `csv_to_question_catalog_yaml.py` parses a row with a per-perspective override correctly into `QuestionAnswering.overrides`; `answering_for("financial")` returns the override, `answering_for("architecture")` (no override on that row) falls through to the default; a row with no overrides at all behaves identically to today (regression guard).
- #3: no batch verification — each new `action_function` gets its own test as it's built, per the existing report-spec design's own validation rules (Report Spec Builder Design Rule C: validate against the named client class).
- #4: not testable until ISSUE-48 lands. When it does: live-verify `Create Embedded Process` + the new link command against a real server, then live-verify `Link Action to Action Executor` (closing out its own long-standing unverified flag) against a real Governance Engine Host.
