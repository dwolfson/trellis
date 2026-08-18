# Survey Results dashboard — repo-wide, cross-stage results surface

**Status: planned, not yet built.**

## Context

Prompted by a direct question after re-authoring `Repo Coarse Scout`/`Repo Discovery Survey`/
`Repo Full Survey` against Egeria this session: once a Survey Definition is discoverable and
runnable from a phase's own "Survey" sub-tab (the existing D7 unified `_loadSurveyPanel()`
panel), where do its results actually show up?

Today: nowhere dedicated. `submitSurveyDefinitionRun()`'s result modal shows only a per-step
status list (ok/error) + a link out to Egeria's own catalog. The real findings/metrics data
lives entirely on Analysis/Assessment's per-`analysis_id` 📊 Results cards
(`ANALYSIS_KINDS`/`AnalysisKindResults`, `repo_survey_definition_adapter.py`) — 15 analysis
kinds today, each independently toggled open on its own catalog card.

Per direct discussion: that per-card model doesn't scale as every survey stage accumulates its
own results — Analysis/Assessment's card list isn't the right home for "give me the picture,"
only for "here's one specific check." Two things are needed, not one:

1. A **repo-wide, cross-stage Survey Results view** — one shared surface (not duplicated per
   intent) that groups related `analysis_id`s into real dashboards (e.g. a Security Overview
   pulling from `security_scan` + `security_features` + `ci_quality` + `license_classification`
   + `repo_conventions`' security-policy signal at once), filterable by the same Perspective
   vocabulary Questions/the Survey panel already use.
2. **Per-phase "is it worth going further" summary stats**, embedded directly in each phase's
   own overview (Scouting overview card today; Assessment/Analysis's catalog panel headers,
   not built yet) — a condensed signal, not the full dashboard, so a user doesn't have to leave
   the phase they're in just to decide whether to proceed to the next one.

## Key decisions

**D1 — Two tiers, not one.** Tier 1 (phase-scoped summary stats) and Tier 2 (repo-wide
dashboard view) are both in scope for this pass, per direct confirmation — they answer
different questions ("is this phase's signal good enough to proceed?" vs. "give me the whole
picture, organized sensibly") and neither substitutes for the other.

**D2 — Tier 2 lives as one shared component, reused as a sub-tab wherever "Survey" already
lives** (Scouting today, Enrichment today — both already call the shared `_loadSurveyPanel()`),
matching that exact precedent rather than duplicating a results view per host. A repo's results
are the same regardless of which intent's Survey sub-tab launched the run that produced them.

**D3 — New `SURVEY_RESULT_DASHBOARDS` registry, keyed by dashboard id, colocated in
`repo_survey_definition_adapter.py` next to `ANALYSIS_KINDS`** (the module already owns this
vocabulary):
```python
@dataclass
class SurveyResultDashboard:
    id: str
    title: str
    description: str
    analysis_ids: list[str]      # which ANALYSIS_KINDS entries this pulls from
    render: str = "grouped_cards"  # "grouped_cards" (reuse each id's existing
                                    # findings_list/metrics/custom renderer,
                                    # stacked under one dashboard heading) |
                                    # "custom" (a genuinely composite widget —
                                    # e.g. a single traffic-light score derived
                                    # from >1 analysis_id at once)
    custom_renderer: str | None = None   # JS function name, when render="custom"
```
`family` (already on `AnalysisKind` — `security_scan`/`security_features`/`ci_quality` are
already tagged `family="security"`) is a *grouping hint*, not the dashboard mechanism itself —
a dashboard's `analysis_ids` list is explicit and can span kinds with no shared `family` at all
(e.g. Security Overview also wants `license_classification` and `repo_conventions`, neither
currently `family="security"`). No `ANALYSIS_KINDS` changes required for this.

First dashboards (grounded in the real 15-entry registry, not hypothetical):
- **Security Overview** (`render="custom"`) — `security_scan`, `security_features`,
  `ci_quality`, `license_classification`, `repo_conventions` (its `security_policy_content`
  sub-finding specifically). One composite pass/gap/risk-tier scorecard up top, full
  `grouped_cards` detail underneath.
- **Health & Maturity** (`grouped_cards`) — `repository_health`, `maturity`.
- **Documentation & Conventions** (`grouped_cards`) — `documentation_coverage`,
  `repo_conventions`.
- **Dependencies** (`grouped_cards`) — `dependency_analysis`.
- **Code Structure** (`grouped_cards`) — `api_structure`, `code_symbol_extraction`,
  `language_file_classification`.
- **Data Profile** (`grouped_cards`) — `data_file_profiling`, `sub_resource_survey`.

Framework is the point of this pass — six real dashboards prove it end-to-end; more are a
one-entry addition afterward, not a new mechanism.

**D4 — Perspective filtering reuses the existing 12-name vocabulary and join, no new
authoring.** A dashboard's Perspective tags are *derived*, not hand-set: union of Perspectives
linked to any Question whose `answering.analysis_ids` (question_catalog.yaml) resolves through
`REPO_ANALYSIS_STEP_MAP`'s inverse to any of the dashboard's `analysis_ids` — the same
Question↔analysis_id join `generate_repo_survey_definition.py`'s `_build_step_key_to_questions()`
already performs, and the same Perspective-chip interaction pattern the Survey panel
(`_surveyPanelAvailablePerspectives`/`_toggleSurveyPanelPerspective`) already ships. Filtering a
dashboard list by active Perspectives hides any dashboard with zero matching tags; no filter
active shows all. repo-only for now — same graceful degrade as D7a (db/filesystem hosts get the
dashboard list with no Perspective row, nothing derivable to filter by).

**D5 — Tier 1 (per-phase summary stats) is a small, separate "headline" reader, not the full
results reader.** `AnalysisKindResults` gains an optional third callable:
```python
headline_reader: Callable[[registry, slug], dict | None] | None = None
# -> {"label": str, "status": "ok" | "warn" | "gap" | "info"} or None (no data yet)
```
For most kinds this is a 2-line wrapper around the existing `results_reader` (e.g.
`security_scan`'s headline is "{gap_count} security gap(s)" derived from the same findings list
`_security_results()` already returns) — not a new data source, a compression of the existing
one. A phase's stat row is: for every `ANALYSIS_KINDS` entry whose `analysis_catalog.yaml`
intent tag matches this phase, render its headline as a small colored stat tile. Scouting's
overview gets this first (its own dedicated `renderScoutingOverview()` already exists and has
an obvious slot); Assessment/Analysis's catalog panel header is the natural next placement,
noted here but not required to ship in the same pass as Tier 2.

**D6 — No new persistence.** Both tiers are pure read/aggregation layers over what
`ANALYSIS_KINDS`' existing `results_reader`/`trend_reader` already query (`project_analysis_findings`/
`project_analysis_metrics`, generic `kind`-parameterized tables from the analysis-kind
extensibility redesign). A dashboard is a *view composition*, not a new write path.

## Implementation

**`resource_explorer/surveyors/repo_survey_definition_adapter.py`**: `SurveyResultDashboard`
dataclass + `SURVEY_RESULT_DASHBOARDS: dict[str, SurveyResultDashboard]` (D3); `headline_reader`
field on `AnalysisKindResults` + one headline callable per existing kind (D5); a
`get_dashboard_perspectives(dashboard_id) -> list[str]` derived-join helper (D4), same shape as
the existing `_build_step_key_to_questions()`/`get_questions()` machinery in
`scripts/generate_repo_survey_definition.py` (likely promoted to a shared location both the
script and this module import, rather than duplicated).

**`resource_explorer/web/routes/projects.py`**: `GET /{slug}/survey-results` → every dashboard
in `SURVEY_RESULT_DASHBOARDS`, each with its resolved `analysis_ids`' results (via the existing
per-kind `results_reader`s), its render mode, and its derived Perspective tags. `GET
/{slug}/survey-results/summary?phase=X` → one stat tile per `ANALYSIS_KINDS` entry whose
`analysis_catalog.yaml` intent equals `X` and has a `headline_reader` (D5, Tier 1).

**`resource_explorer/web/static/index.html`**: new shared `_loadSurveyResultsPanel(entityType,
slug, viewElId, subnavHtml)` (D2), mirroring `_loadSurveyPanel()`'s structure — Perspective
filter row (D4) + dashboard cards, each either stacked `grouped_cards` (reuses
`_renderFindingsListResults`/`_renderMetricsResults`/the existing per-`analysis_id` custom
renderers unchanged) or a new `custom` widget (Security Overview's composite scorecard, the one
genuinely new renderer this pass). New "📊 Results" sub-tab added next to "📊 Survey" wherever
that sub-tab already exists (Scouting first; Enrichment's own `survey` sub-tab is the natural
second, since it already reuses the same shared-component precedent). Tier 1: a small stat-row
component embedded in `renderScoutingOverview()` (D5) — Assessment/Analysis embeds noted as a
natural follow-up, not blocking this pass.

## Verification

- Unit tests: `SURVEY_RESULT_DASHBOARDS` — every dashboard's `analysis_ids` resolve to real
  `ANALYSIS_KINDS` entries (regression guard against a dashboard referencing a renamed/removed
  id, same spirit as the D3 CSV↔`STEP_REGISTRY` guard from `repo-survey-catalog-completion-plan.md`);
  Perspective-derivation join produces the expected union for a dashboard spanning kinds with
  different Question linkages; headline readers return `None` gracefully on no-data rather than
  raising.
- Route tests: `GET /{slug}/survey-results` shape (all 6 dashboards present, `render`/
  `custom_renderer` correctly threaded); `GET /{slug}/survey-results/summary?phase=scouting`
  returns exactly the stat tiles scouting-tagged kinds contribute, empty for a phase with none.
- Live: run enough of the repo Survey Definitions/analyses against a real repo to populate every
  dashboard's underlying data, confirm the new Results sub-tab renders all 6 with correct
  Perspective tags, confirm the Security Overview's composite score reflects real gap/risk-tier
  data (not just the underlying findings lists individually), confirm Scouting's new stat row
  updates after a Scouting Scan run.
- Full RE test suite green.
