# The microflow/survey/funnel-phase model — one shape for most of what RE does

**Status: framing doc, capturing a real unification confirmed 2026-08-15 —
partly already built (independently, before this was named as the
governing principle), partly genuinely open. Not a build plan; see
"Relationship to other docs" for where the mechanics live.**

## The model

- **Microflow** — the atomic unit of work. Self-contained: acquires
  whatever shared resource it needs (D6, `unified-survey-execution-
  model-plan.md`), does whatever write(s)/refresh(es) are required to
  make its data current, reads what it just ensured, emits `Annotation`s.
  One `StepInfo`, one Egeria-visible step (an `EmbeddedProcess`/
  `TransientEmbeddedProcess` from Egeria's own point of view, per the
  active-governance discussion this session).
- **Survey** — a named, ordered composition of microflows. The *same*
  microflow can appear in more than one Survey type — a user picks a
  Survey to match their actual need ("just re-check git statistics" vs.
  "complete refresh"), not a fixed one-size-fits-all bundle. This is D1's
  original framing ("one Survey concept: a named, ordered bundle of
  steps"), just extended past repo-analysis steps to *everything* —
  RAG ingestion, language analysis, potentially human actions.
- **Funnel phase** (Scouting/Discovery/Assessment/Analysis/Enrichment/…)
  — presents the user a choice of Surveys whose produced annotations
  answer that phase's `ScopedBy` Questions (`survey-question-context-
  plan.md`'s D1/D2, already built). Configurable, changeable — the phase
  doesn't hardcode which Surveys belong to it; the `ScopedBy` graph does.
- **Sub-tab shape per phase** — genuinely open, not yet designed as a
  formal decision, but has independently converged close to: one tab to
  select/run Surveys, one to visualize results, one for Questions, one
  for Disposition — Scouting additionally has Search (candidates aren't
  registered resources yet, nothing else needs it).

## What's already true — confirmed against the actual codebase, not asserted

- **D1** already states the composition principle; this doc doesn't
  invent it, it generalizes it past repo `STEP_REGISTRY` steps.
- **D7/D7a** (`unified-survey-execution-model-plan.md`) already built
  "phase presents Survey choices scoped by that phase's Questions" —
  the shared `renderSurveyPanel()`, `phase=`/`perspectives=` filtering
  against the real `ScopedBy` graph. Live-verified this session.
- **The sub-tab shape already converged independently, phase by phase**,
  without this being a stated principle: Scouting has 5 tabs (Search/
  Survey/Coarse Profile/Questions/Disposition), Assessment has 4
  (Analyses/Sub-Resources/Questions/Disposition), Enrichment gained a 4th
  this session (Context/Survey/Questions/Disposition). Nobody planned
  this top-down — each phase kept needing the same things. Naming it now
  means the next phase that needs a sub-tab uses the shape instead of
  rediscovering it.
- **D6**'s resource-sharing mechanism (designed, not yet implemented) is
  confirmed to generalize past repo/zipball-sharing to whatever future
  microflows need shared resources (e.g. a shared DB connection for
  database-type microflows) — not a repo-specific mechanism that happens
  to also work elsewhere.

## What this newly unifies — real, not yet built

- **RAG ingestion as a microflow.** Today `IngestionPipeline` is a fully
  separate subsystem — invisible to `STEP_REGISTRY`/`SurveyOrchestrator`/
  D6's resource-sharing/Discovery's candidates. Same category of seam as
  the file-profiling one D5 just closed. A documentation-related Question
  needing an "ingest for RAG" answer becomes a real, selectable microflow
  like any other, rather than a bolted-on separate pipeline a Survey can
  never reference.
- **D5's revised microflow design** (File Analysis / Data Analysis / CI
  Workflow Analysis / Repo Conventions Analysis / Symbol Extraction — see
  `unified-survey-execution-model-plan.md`'s D5) is the first concrete
  instance of this model actually being designed in detail, not just
  stated as a principle.
- **Enrichment as a Survey with a human microflow — floated, not
  committed** ("if it makes sense," direct wording). A microflow that's a
  human action is exactly the `WAITING`/To Do shape from the
  active-governance discussion — and RE already has the real mechanism
  for it, built for an unrelated reason: the RFA redesign
  (`rfa-egeria-todo-followup.md`, decided 2026-08-15) already mirrors
  `ToDoProperties` and syncs with a real Egeria `ToDo`. A human microflow
  would be: create the work item, the step's Engine Action/local
  equivalent waits, the human's response becomes the microflow's
  Annotation. This doesn't need A2A/D8 to work locally — the mechanism
  already exists independent of that (deferred) thread. If pursued,
  CLAUDE.md rule 17's Enrichment exception ("zero entries in the analysis
  catalog... by design") stops being a permanent exception and becomes
  "not yet migrated."

## Explicitly open — named, not resolved here

- **Cross-resource-type generalization.** Database and filesystem
  surveying each have their own separate `survey_definition_adapter.py`
  today, parallel to but independent from the repo one. "One model for
  most of what RE does" means these converge too — real, unscoped work,
  not a given just because the repo side unifies.
- **Sub-tab shape as a formal decision** — described above as an
  observed convergence, not yet a designed, deliberate spec (which tabs
  for which phases, whether Discovery/Analysis need their own Search-like
  tab, etc.).
- **Enrichment-as-Survey** — floated, explicitly "if it makes sense," not
  decided either way.
- **`analysis_catalog.yaml`'s `AnalysisKind` registry's relationship to
  "Survey"** — not addressed directly in this session's discussion. Under
  this model, is an `AnalysisKind` entry just another (single-microflow)
  Survey type, or does it stay a parallel, YAML-driven concept alongside
  real `GovernanceActionProcess`-backed Surveys? Real question, not yet
  asked directly, let alone answered.

## Relationship to other docs

- `unified-survey-execution-model-plan.md` — the actual execution
  mechanics (D1–D8: execution-locus cases, publish semantics, D6's
  resource-sharing mechanism, D8's deferred A2A engine). This doc is the
  framing layer above it, not a replacement.
- `survey-question-context-plan.md` — the `ScopedBy` Question/Perspective/
  Funnel-Stage graph that makes "phase presents relevant Surveys" possible
  at all.
- `rfa-egeria-todo-followup.md` — the human-work-item mechanism a human
  microflow would actually use.
