# Funnel stage data-needs review: what do we need to know, when

**Status: draft, first pass — for discussion, not yet decided or implemented.**

## Context

Grew out of a live question: "I selected sub-resource survey and it gave an error" led to finding
and fixing a real performance bug (`SubResourceSurveyor`'s commit-history pagination — see git log),
which led to a broader question — is Understanding the right home for Git Statistics trend charts,
and *when* should RAG ingestion and AST/language analysis actually happen? Tracing the code
surfaced a real, unintentional gap: **`OnboardingWizard.run()` triggers full RAG ingestion of every
configured collection unconditionally at `add` time** — before Scouting has told anyone whether the
repo is even worth a closer look. That's backwards from the funnel's own premise (cheap-first,
narrow-as-you-go — the same logic already applied to sub-resource cataloging in
`docs/repo-scope-narrowing-funnel.md`).

Confirming the instinct: `analysis_catalog.yaml` already tags `rag_ingestion` with `intent: analysis`
— the catalog metadata agrees ingestion is Analysis-tier work. The code just doesn't respect that;
it runs the expensive step at Scouting-tier registration regardless.

This doc reviews, stage by stage: purpose, what's actually needed to fulfill it, what survey/analysis
work runs, what gets displayed, what (if anything) gets catalogued to Egeria and when, and — new
dimension — what the chat interface should be able to answer at that point. Outline form per the
user's request (a table got too wide once "catalogued" and "chat" were added).

## Vocabulary carried over from the Profile-phase plan

Five visibility sources, since every stage's "what do we need to know" maps to a subset of these:
- **①** GitHub API metadata (name, stars, description, activity) — cheap, already self-refreshing.
- **②a/②b** File/language shape of the zipball (file inventory, symbols) — medium cost, one zipball
  download; today's "Profile" tab.
- **②c** Vector/AI content analysis (RAG ingestion, chat) — expensive, embeds actual file content.
- **②d/②e** Other/cross-repo analysis — not built.
- **③** What Egeria already knows (native surveys, existing catalog entries).
- **④** User-supplied context (Enrichment's Context form).

---

## Scouting

**Purpose (canon):** broad inventory across many resources, fast, summary view.

**What we need to know:** is this repo active, roughly what is it, is it worth a closer look at all.
Nothing here requires reading file content or even file *names* — GitHub's own repo metadata
answers all of it.

**Surveys that run:** `repository_health` (`HealthSurveyor` — activity/community/freshness scoring
from `project_stats`), `language_file_classification`'s `repo_language` sub-step (primary language
from GitHub API, no zipball). The "Repo Coarse Scout" Survey Definition chains exactly these two —
by design, API-only, no clone needed.

**What's displayed:** Scouting overview card — description, stars/forks/contributors, primary
language, last-pushed, `last_surveyed_at`/`is_published` badges. Sidebar lifecycle badges
(🆕/📊/☁).

**What's catalogued, when:** optional, explicit "Publish registration only" button — `steps=
["repo_health"]` published through the same `EgeriaPublisher.publish()` everything else uses,
creating/finding the `SourceControlLibrary` asset with a minimal `SurveyReport`. Never automatic.

**Current gap:** `add`/registration (`OnboardingWizard.run()`) triggers full `IngestionPipeline.run()`
— every RAG collection embedded — *before* any of the above even runs. This is the misplaced-cost
problem this doc exists to fix.

**Chat at this stage (draft):** "how active is this repo," "what does it do," "who maintains it" —
all answerable from ① alone. Should **not** need ②c to work.

---

## Discovery

**Purpose (canon):** find resources by what surveys revealed; launch Survey Definitions.

**What we need to know:** nothing new — pure search/filter over whatever's already been surveyed,
plus the mechanism to launch a Survey Definition against a resource.

**Surveys that run:** none — Discovery never triggers new work itself, it dispatches to
`survey_definition_executor.py`'s generic loop when a user explicitly runs one.

**What's displayed:** Survey Definition candidates + Discovery's search/import UI (org discovery,
saved/list sources).

**What's catalogued, when:** whatever the launched Survey Definition itself catalogs (native Egeria
processes, `publish_step_annotations`) — not a Discovery-specific concern.

**Chat at this stage:** not really a distinct chat surface — Discovery is a launch mechanism, not a
"tell me about this resource" context.

---

## Assessment

**Purpose (canon):** scored evaluation of a specific resource against criteria, slow/async, detailed
annotations.

**What we need to know:** dependency posture, security/doc hygiene — *structural* facts about the
repo, not its content. Needs ②a/②b (file inventory) but not ②c (embedded content).

**Surveys that run:** `security_scan` (`SecurityHygieneSurveyor` — SECURITY.md/CI/LICENSE
presence), `documentation_coverage` (`DocumentationSurveyor` — README/CHANGELOG/CONTRIBUTING
presence + quality label). Both read `project_file_inventory`, populated by Profile's zipball scan —
no content embedding needed.

**What's displayed:** Assessment cards with `findings_list` results (pass/gap per check) + trend.

**What's catalogued, when:** per-card "Publish this analysis" (generalized `PublishRequest.steps`,
Profile-phase plan D3) — scoped `SurveyReport` with just that card's annotations. Explicit, per-card.

**Chat at this stage (draft):** "does it have a security policy," "is documentation adequate," "what
gaps exist" — all answerable from findings tables, no ②c needed.

---

## Analysis

**Purpose (canon):** structural/quantitative analysis (not scored) — dependencies, profiling, API
extraction.

**What we need to know:** dependency list per ecosystem, data-file schema profiles, public API
surface (functions/classes/methods). API extraction specifically needs `project_code_symbols` —
this is where AST/language analysis actually earns its place, and *only* here (nothing upstream of
Analysis reads symbols).

**Surveys that run:** `dependency_analysis` (`DependencySurveyor`), `data_file_profiling`
(`DataProfilerSurveyor`, `target_shape: corpus` — now scopable to a cataloged sub-resource, Phase 2
of the scope-narrowing-funnel work), `api_structure` (`ApiStructureSurveyor`, also `corpus`-scoped) —
**but `api_structure` only *reads* `project_code_symbols`, it never populates it.** Symbols get
populated exclusively by `_ingest_code()` (RAG-collection ingestion, a side effect) or Profile's
"also refresh code symbols" checkbox (`refresh_profile(include_symbols=True)`, no RAG needed). This
is the real reason `rag_ingestion` is tagged `intent: analysis` in the catalog already — Analysis is
genuinely the first point that needs anything beyond file *structure*.

**What's displayed:** Analysis cards, same `findings_list`/`metrics`/`custom` render modes as
Assessment; scoped-analysis UI on cataloged sub-resources (Phase 2, just shipped) for
`data_file_profiling`/`api_structure`.

**What's catalogued, when:** same per-card scoped publish pattern as Assessment.

**Proposed fix:** `rag_ingestion`'s trigger point should move here (or to an explicit user action
reachable from here), not fire unconditionally at `add`. `api_structure`'s card could itself trigger
symbol extraction (via `refresh_profile(include_symbols=True)`, no RAG needed) rather than silently
showing empty results when symbols were never populated — this decouples "I want API structure" from
"I want full content-search RAG," which today are needlessly coupled through `_ingest_code()`.

**Chat at this stage (draft):** "what are this repo's dependencies," "does it use library X," "what's
the public API of module Y," "how complex is function Z" — all answerable from survey tables, still
no ②c (content embedding) required if API-structure-only questions are in scope. Content-level
questions ("show me how X is implemented") would need ②c.

---

## Enrichment

**Purpose (canon):** human-supplied facts (environment, ownership, sensitivity), human-paced.

**What we need to know:** nothing derived — pure form input via the Context API.

**Surveys that run:** none.

**What's displayed:** Context form.

**What's catalogued, when:** Egeria asset property updates, on form submit.

**Chat at this stage:** N/A — Enrichment writes, doesn't answer.

---

## Understanding

**Purpose (canon):** visualize trends over time — charts (stars, commits, schema, etc.), fast.

**What we need to know:** historical snapshots already captured by earlier stages — nothing new to
fetch. Stars/Commits from `project_stats` history (Scouting-tier data, just charted over time);
Languages/Health from the same surveys as Scouting/Assessment; File Types from
`FileClassifierSurveyor` (Profile-tier, ②a/b).

**Surveys that run:** none new — this is purely a read/chart layer over `stats.py`'s `/charts/*`
routes, all backed by tables other stages already wrote.

**What's displayed:** 5 chart tabs (Stars, Commits, Languages, Health, File Types), all Plotly
trend lines.

**What's catalogued, when:** N/A — Understanding never writes.

**Open question (from the original message):** is Understanding actually the wrong *label* for
this, or is the real issue that Languages/Health can silently show stale/empty data when their
upstream survey never ran (the `project_code_symbols` gap above)? Leaning toward the latter — the
charts genuinely are trend visualizations (matches canon), the problem is data-freshness guarantees
upstream, not the charts' placement.

**Chat at this stage:** trend questions ("is activity growing or shrinking," "when did doc coverage
improve") — needs history tables, already available regardless of ②c.

---

## Curate

**Purpose (canon):** make a resource easier to find/trust for reuse — tags, feedback, curator notes.

**What we need to know:** nothing derived — human curatorial input, same shape as Enrichment but
ongoing rather than one-time.

**Surveys that run:** none directly, but `egeria_publish` (the full/whole-repo publish action) is
tagged `intent: curate` in the catalog — cataloging-to-Egeria is modeled as a Curate-tier decision:
"this is trustworthy/complete enough to put in the shared catalog of record."

**What's displayed:** tags/feedback/curator-notes CRUD panel.

**What's catalogued, when:** the full publish action lives here conceptually, though in practice
it's also reachable earlier (Scouting's "Publish registration only," Assessment/Analysis's per-card
publish) — Curate's `egeria_publish` is the "publish everything surveyed so far" superset action.

**Chat at this stage:** "what's this repo tagged as," "what feedback has it gotten" — curatorial
metadata, no ②c needed.

---

## Cross-cutting: RAG ingestion (②c) doesn't map cleanly to any single stage

Restating the core finding: none of Scouting → Curate's *stated purposes* need embedded file
content — every one of them is answerable from structural/metadata survey tables. Content-level RAG
chat ("how does X work," "show me an example of Y") only pays off once a resource has cleared a real
decision point — plausibly `disposition` reaching `tracking`/`investigating` (Scouting's own
existing vocabulary for "this is worth pursuing"), or an explicit "index for chat" action a user
takes deliberately, mirroring how sub-resource cataloging and Egeria publish are already both
explicit, never-automatic actions elsewhere in this design.

**Not decided yet — needs your input:**
1. Does gating ingestion behind `disposition` (tracking/investigating) match your mental model, or
   should it be a separate, even-more-explicit action (like a "💬 Enable chat for this repo" button)?
2. Should `add`/registration stop calling `IngestionPipeline.run()` entirely, replaced by Scouting's
   existing Profile tab + a new explicit ingestion trigger? What does a *cheap* `add` need to still
   do (repo metadata row, nothing else)?
3. For chat questions that need `project_code_symbols` but not embedded content (API-structure
   questions), should chat be able to answer those *without* full RAG ingestion having run — i.e.
   does chat need a "structural" mode distinct from its RAG-backed "content" mode?
4. Per-stage chat scoping above is a first draft — flagged in your message as needing refinement
   throughout. Which stage's chat-question list feels most wrong to you first?
