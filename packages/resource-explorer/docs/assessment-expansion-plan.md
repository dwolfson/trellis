# Assessment expansion: Sub-Resources relocation + 4 new analyses

**Status: planned, not yet built.**

## Context

Two threads converged in conversation (2026-08-13):

1. **Sub-Resources belongs in Assessment, not Scouting.** Its own design doc
   (`docs/assessment-sub-resource-cataloging.md`) is explicit: *"Assessment's job... is
   'existing tables only, deeper analytics — no new fetch': `SecurityHygieneSurveyor`,
   `DocumentationSurveyor`, and `ApiStructureSurveyor` all read already-persisted data...
   None of them produce per-file or per-folder Egeria elements... That's the gap this plan
   closes."* It only ended up in Scouting's UI rail because the "Scouting workflow redesign"
   plan (D6) needed a home for it at the time — a placement decision, not a reflection of
   the feature's own design intent.

2. **Four real Assessment-tier gaps** surfaced while building the Scouting
   Question/Perspective/Intent model (`docs/dr-egeria/resource_questions.csv`): license/
   copyleft classification, an unused-but-already-fetched `security_and_analysis` GitHub
   field, CODEOWNERS presence, and CI-quality (today's `security_scan` only checks "does a
   CI config file exist," not whether it runs anything meaningful).

This plan covers both, grounded in a direct code read (not assumptions) of the existing
Sub-Resources implementation and the `AnalysisKind` extensibility pattern already
established by `documentation_coverage`/`security_scan`.

---

## Part A — Move Sub-Resources into Assessment

### Decisions

**D1 — Assessment gets its own 2-tab sub-nav**, mirroring Scouting's
`_scoutingSubnavHtml`/`_scoutingSubTab`/`_showScoutingSubTab` pattern exactly: **📋 Analyses**
(today's flat catalog-card grid, unchanged content/behavior) + **🗂 Sub-Resources** (the
existing, fully-built panel, relocated). New `_assessmentSubnavHtml(active)` /
`_assessmentSubTab` / `_showAssessmentSubTab(tab)`, same shape, same naming convention.

**D2 — Zero backend changes.** Confirmed via direct code read: every Sub-Resources route
(`/api/projects/{slug}/sub-resources...` in `web/routes/projects.py`) is already
resource-*type*-scoped (`resource_type="repo"`), not funnel-stage-scoped — no route path
contains "scouting," and `registry.py`'s `sub_resources` table/CRUD
(`catalog_sub_resource`/`list_sub_resources`/etc.) are keyed the same way. This is a pure
UI relocation.

**D3 — Move, don't duplicate.** Delete `_scoutingSubnavHtml`'s `sub-resources` tab entry
(`index.html:1368`), `_showScoutingSubTab`'s branch (`:1390`), the
`scouting-sub-resources-view` div (`:386`), and its three `showMainView` wiring points
(const, hide-list, branch at `:4783-4785`). Re-create equivalent entries under the new
Assessment sub-nav, keeping the existing logic (`loadScoutingSubResourcesView`,
`_renderScoutingSubResourcesView`, `_runSubResourceSurvey`, `_subResSort`,
`_subResApplyFilter`, `_renderCatalogedSubResourcesSection`, `_runScopedAnalysis`,
`_loadScopedAnalysisResults`, `_subResSelectAll`, `_submitSubResourceCatalog` — the whole
`index.html:5350-5744` block) but retargeting:
  - Rename `loadScoutingSubResourcesView` → `loadAssessmentSubResourcesView` (and the
    `_render...`/other helper names correspondingly, or keep the internal names and just
    swap the entry points — implementer's call, consistency with Scouting's own naming is
    the only real constraint).
  - Swap the DOM id `scouting-sub-resources-view` → `assessment-sub-resources-view`
    everywhere it's used (`index.html:5398,5451,5576,5697,5704` and the view div itself).
  - Swap every `_scoutingSubnavHtml('sub-resources')` prefix call (`:5399,5413,5454,5520`)
    to `_assessmentSubnavHtml('sub-resources')`.
  - `selectedProject` (the slug source) is unchanged — it's a global, not Scouting-scoped.

**D4 — `_loadAnalysisCatalogPanel` needs one small param added.** It currently fully
overwrites `view.innerHTML` on every path (`index.html:1560,1595,1633,1693`) with no sub-nav
wrapper — used identically by both `loadAssessmentPanel()` and `loadAnalysisPanel()` today
(`:1538-1544`). Add an optional `subnavHtml: string = ''` param so Assessment's "Analyses"
sub-tab can pass `_assessmentSubnavHtml('analyses')` while `loadAnalysisPanel()` (unaffected
by this plan — Analysis intent isn't getting a sub-nav) keeps passing nothing. Every
`view.innerHTML = ...` assignment inside `_loadAnalysisCatalogPanel` and
`renderAnalysisCatalogCards` needs the prefix prepended.

**D5 — `showMainView`'s `assessment` branch needs to route through a dispatcher**, same
shape as `showScoutingPane()` → `_showScoutingSubTab()`. Today it just calls
`loadAssessmentPanel()` directly (`:4764` region); after this change it needs an
`_showAssessmentSubTab(tab)` step so arriving at the Assessment intent lands on whichever
sub-tab was last active (mirrors `_scoutingSubTab`'s persistence-across-selection-changes
behavior).

**D6 — Repoint any other callers.** Grep the whole frontend for `sub-resources` /
`_showScoutingSubTab('sub-resources')` as part of implementation (not just the two call
sites already found) — don't assume those are the only cross-links (e.g. a Scouting overview
card button, if one exists, pointing at the old location).

### Implementation

- `resource_explorer/web/static/index.html`: all of the above — new
  `_assessmentSubnavHtml`/`_assessmentSubTab`/`_showAssessmentSubTab`; relocate the
  `5350-5744` Sub-Resources block's entry points and DOM-id/prefix references;
  `_loadAnalysisCatalogPanel`'s new `subnavHtml` param; `showMainView`'s `assessment`
  branch → dispatcher.
- No changes to `web/routes/projects.py` or `registry.py` (confirmed above — D2).

### Verification

- Sub-Resources panel still lists/catalogs/publishes/runs-scoped-analysis identically from
  its new home — same manual pass already used to verify it originally (survey → select
  worthy → catalog → publish → scoped-analysis run), reached via Assessment > Sub-Resources
  instead of Scouting > Sub-Resources.
- Assessment > Analyses (the relocated flat catalog grid) unchanged in content/behavior —
  regression check, not just "does it still render."
- Grep confirms zero remaining `scouting-sub-resources` / Scouting-side sub-resources
  references.
- Full RE test suite green (UI-only change; no Python tests should be affected, run them
  anyway).

---

## Part B — Four new Assessment analyses

Each follows the exact `AnalysisKind`/`StepInfo` pattern already used by
`documentation_coverage`/`security_scan` (`repo_survey_definition_adapter.py`), persisting
into the existing generic `project_analysis_findings`/`project_analysis_metrics` tables via
`upsert_finding`/`upsert_metric` with a `kind` string — **no new schema for any of the
four**. None need `scope_locator` (`accepts_scope_locator=True`) for this first cut — all
four are whole-repo checks, not naturally scoped to a cataloged sub-resource; that's a
per-step opt-in already built (not a schema change), left for a later pass if e.g. per-folder
license auditing in a monorepo becomes wanted.

### B1 — License/copyleft classification (`license_classification`)

New `LicenseClassifierSurveyor` (`sub_surveyors/license_classifier.py`). Input: GitHub's own
license field (already fetched, free — `stats_fetcher.py`'s `_license()`) + a small static
SPDX-id → risk-tier lookup table (permissive: MIT/BSD/Apache-2.0/...; weak-copyleft:
LGPL/MPL/EPL; strong-copyleft: GPL/AGPL; source-available: BSL/SSPL/Commons-Clause;
unknown/no-license). Closes 2 real gaps flagged in the Scouting CSV ("Are there any
restrictions for use?", "What explicit license... copyleft terms?" — currently GAP-tagged).
A static lookup table is a legitimate, immediately-buildable first cut from data RE already
has; deeper tooling (FOSSology/LicenseFinder/ClearlyDefined, already named as candidates in
the CSV) is a future upgrade, not required here.

`StepInfo("repo_license_classification", LicenseClassifierSurveyor, ...)`;
`AnalysisKind("license_classification", ["repo_license_classification"],
results=AnalysisKindResults(_license_results, None, "findings_list"))` — single finding
`{check_name: "license_risk_tier", label: <tier>, summary, confidence}`. No `trend_reader`
needed (license rarely changes; `trend_reader: Callable | None` is already optional).

### B2 — `security_and_analysis` interpreter (`security_features`)

New `SecurityFeaturesSurveyor`, reading `project_stats.security_and_analysis_json` (already
fetched — `stats_fetcher.py:405-421` — zero new API calls, no zipball needed). One finding
per feature name (7 total: `advanced_security`, `dependabot_security_updates`,
`secret_scanning`, `secret_scanning_ai_detection`, `secret_scanning_non_provider_patterns`,
`secret_scanning_push_protection`, `secret_scanning_validity_checks`) — `label: "pass"` if
status `== "enabled"`, `"gap"` if `"disabled"`, **skip entirely** (don't emit a finding) if
`None` (feature data unavailable, per the fetcher's own docstring: populated only for repos
the connected token administers — "empty for everything else, which is most repos being
scouted"). Skipping rather than reporting a false gap avoids penalizing repos where GitHub
simply never exposed the data.

**Bug found alongside this** (fix in the same pass, same data): the existing raw display of
this field on the Scouting overview card (`index.html:4871`,
`Object.entries(d.security_and_analysis || {}).filter(([, v]) => v)`) treats *any* truthy
string as "on" — a `"disabled"` feature would incorrectly render as enabled. One-line fix:
filter on `v === "enabled"` instead of plain truthiness.

### B3 — CODEOWNERS presence (`codeowners_presence`)

Needs one new registry function — confirmed no exact-filename lookup exists today
(`get_file_inventory`/`get_file_inventory_with_sizes` return the whole per-repo list
unfiltered). Add e.g. `file_exists(slug, *candidate_paths) -> str | None` doing an indexed
`WHERE project_slug=? AND file_path IN (...)` query (the table's existing
`UNIQUE(project_slug, file_path)` constraint makes this cheap) — check the 3 real
GitHub-recognized locations: `CODEOWNERS`, `.github/CODEOWNERS`, `docs/CODEOWNERS`.

Implementation choice for the check itself: either a small standalone surveyor, or (probably
cleaner) fold it into `DocumentationSurveyor` as one more `ClassificationAnnotation` — same
shape as its existing README/CHANGELOG/CONTRIBUTING checks, same "which governance files
exist" family it already owns. Either is compatible with the generic `upsert_finding` model;
decide during implementation.

### B4 — CI-quality (`ci_quality`)

Real gap: `security_scan` today only checks "does a CI config file exist" (presence), not
whether it runs anything meaningful. Needs to read workflow YAML *content* — still ②a/②b
tier (already-fetched zipball content, not a new fetch category), a real step up from
presence-only.

New `CiQualitySurveyor`, reading `.github/workflows/*.yml` content (available via the same
zipball `IngestionPipeline`/`refresh_profile` already downloads) for job/step keywords
suggesting test/lint/build stages (`pytest`, `npm test`, `go test`,
`ruff`/`eslint`/`flake8`, `docker build`, etc.) — a heuristic keyword match, not full YAML
semantic parsing, matching this codebase's existing "cheap structural signal, not full
understanding" pattern (e.g. `DocumentationSurveyor`'s own presence checks). Findings:
`{check_name: "ci_runs_tests"|"ci_runs_lint"|"ci_runs_build", label: "pass"|"gap"}`.

Most involved of the four (needs actual zipball content access, not just already-fetched
metadata) — reasonable to sequence last.

### Shared implementation notes (all 4)

- Each gets a `StepInfo` entry in `STEP_REGISTRY`, an `AnalysisKind` entry in
  `ANALYSIS_KINDS` (`intent: assessment`), and a matching new entry in
  `configdata/analysis_catalog.yaml`'s `repo_analyses` list (that file's existing schema/
  header comment documents every field — follow it, don't invent a new shape).
- For the 3 `findings_list`-rendered kinds (license/security-features/codeowners),
  `_REPO_RESULTS_RENDER_MODE`/`_REPO_TREND_LABEL` need a frontend entry each —
  `findings_list` itself needs **zero new rendering code** (confirmed generic).
- Once real (non-GAP) `analysis_ids` exist for these, update the Scouting CSV's 3
  GAP-tagged rows this closes (`Answering Analysis` column) and regenerate
  `question_catalog.yaml`/`scouting-questions.md` — small follow-up, noted here so it isn't
  forgotten, not part of this plan's core scope.

### Verification (Part B)

- Unit tests per surveyor: mirrors existing `DocumentationSurveyor`/`SecurityHygieneSurveyor`
  test patterns — mocked file inventory / mocked `project_stats` row → correct findings.
- Registry: new `kind` strings round-trip through the existing generic
  `upsert_finding`/`query_findings` mechanism (already covered structurally by Phase B's own
  tests — new tests just confirm the new kind strings specifically).
- Live: run each of the 4 against a real repo — e.g. `sqlglot` for license/CI-quality (a real
  active OSS repo with workflows), `trellis` itself for `security_features` since it's
  org-owned and should actually have non-null data, unlike most scouted repos.
- Full RE test suite green.
