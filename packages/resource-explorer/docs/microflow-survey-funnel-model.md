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

## `AnalysisKind`'s results contract, `FormatSet`, and the Egeria-native View Spec/Annotation Spec — captured 2026-08-15

**Not two independent solutions — one lineage.** `FormatSet`'s
`question_spec` (`perspectives` + example `questions`) predates RE's real
`ScopedBy` Question/Perspective graph; the latter is the Egeria-native
elaboration of the former, not a coincidence. This reframes the whole
`AnalysisKindResults`/`FormatSet` comparison from "which one is right" to
"RE independently reinvented, in local Python, exactly what the
Egeria-native successor to `FormatSet` will eventually formalize" — the
same prototype-then-promote pattern already playing out for Dashboard
Sheet (see below), not something new to invent here.

- **Naming**: the Egeria-native successor to `FormatSet`/Report Spec is
  likely to be called a **View Spec** — "executing and displaying
  analyses is only one use case" (direct wording), so it isn't scoped to
  reports specifically.
- **A real, currently-unresolved gap surfaced along the way: master/detail
  and drill-down.** `Column.detail_spec: Optional[str]` (a report spec
  reference for a column's detail view) is `FormatSet`'s existing but
  loose answer — a bare string reference, no real drill-down semantics
  declared. RE independently built a *different*, uncoordinated answer to
  the same need: `AnalysisKindResults.trend_reader` is a wholly separate
  function alongside the main `results_reader`, not a `detail_spec`-style
  reference off the summary. Two ad hoc answers to "how do I get from
  summary to detail," not reconciled — named as a real gap the eventual
  View Spec/Annotation Spec should resolve properly, not something RE
  should also patch locally in the meantime.
- **`Generate Dashboard` as a real step type within a Survey** — not
  speculative, confirmed against the actual, already-working mechanism:
  `LOCAL_DASHBOARDS_TUTORIAL.md`/`local_dashboards_handler.py`
  (`egeria-workspaces-fs`) — a **Dashboard Sheet** (named ordered list of
  **Placements**), each Placement resolving to a **Report** (a real
  Egeria `Asset` subtype carrying a `FormatSet` reference + execution
  params), a nested sheet, or literal markdown text, rendered by the
  Local Dashboards portal app (`/local-dashboards`). A Generate-Dashboard
  microflow would: gather the report specs relevant to the survey's own
  produced annotation types, author (or update from a user-provided
  template) a Dr.Egeria markdown block (`Create Report`/`Create Dashboard
  Sheet`/`Link Report to Dashboard Sheet`/`Add Text on Dashboard Sheet`),
  execute it via the same `dr_egeria_run_block` round-trip used all
  session for foundations/questions/Survey Definitions. Real, buildable —
  and closes the "reuse the Local Dashboard work for presentation" thread
  from earlier in this same conversation, arriving on its own rather than
  forced.
  - **Real prerequisite, not yet met**: RE has zero `FormatSet`/report
    specs of its own today for anything `AnalysisKind` produces — nothing
    for a Generate-Dashboard step to assemble from until that exists.
  - **Explicit mutual-prototype status** (direct wording): "the annotation
    spec concept may come into play here — perhaps replacing some of this
    — but we can view this as a first prototype." Provisional on both
    sides right now — Dashboard Sheet is itself still local JSON, planned
    to migrate to a real Egeria `Collection` subtype (same
    `LOCAL_DASHBOARDS_TUTORIAL.md`), same lineage pattern as `FormatSet` →
    View Spec.

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
  "Survey"** — partially clarified 2026-08-15: real examples showed 12 of
  13 `ANALYSIS_KINDS` entries are already single-microflow, so most are
  trivially "just a Survey type" under this model. What's still genuinely
  open is narrower than originally framed — not "is `AnalysisKind` a
  Survey" but **"does `AnalysisKindResults` (the results/trend/render-mode
  contract) move onto a real Egeria View Spec/Annotation Spec once one
  exists, or stay RE-local"** — see the section above.
- **View Spec/Annotation Spec's actual shape** — inferred by analogy to
  `FormatSet` (the closest existing model), not confirmed against a real
  type definition, which doesn't exist yet on the Egeria side. Treat the
  section above as a hypothesis to validate later, not settled fact.

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
