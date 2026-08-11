# Repo scope-narrowing funnel: recommend → select → catalog → scoped analysis

**Status: draft, for discussion. Not yet implemented.**

## Context

Discussed 2026-08-11, prompted by the question "why can't I see sub-resource cataloging in the
UI?" Resource Explorer's whole architecture is a **successive-refinement funnel**: each phase
examines what's currently in scope, optionally *catalogs* it (tracks it durably — locally within
RE always, and in Egeria if/when the user chooses), and as a side effect often narrows the scope
for the next, deeper phase. "Catalog" here means the general sense — tracking something within
RE's own registry — not specifically "push to Egeria." The two are related but separable: Egeria
publish is a real, deliberate, optional action layered on top of local tracking, not a synonym
for it. Default is to do both (track locally *and* publish to Egeria), but the user can choose
local-only for exploratory/sandbox work.

This funnel already exists at the top level — the seven intents themselves (Scouting → Discovery
→ Assessment → Analysis → Enrichment → Understanding → Curate) are exactly this pattern. What
this doc addresses is the same pattern recurring *within* a single intent, using the concrete
worked example of a repo:

> We search, find repos, run a lightweight survey with git statistics, maybe decide to do a
> somewhat deeper one (at the same level) with coarse profiling. From that we might select
> certain folders (or all) to do deeper discovery surveys on. From that we might find subsets
> from those folders (or maybe their entirety) and run Assessment or Analysis activities.

## The funnel, mapped to what exists today

| Stage | RE mechanism today | Status |
|---|---|---|
| Search, find repos | Scouting → Discover (`GET /api/discovery/search`) | exists |
| Lightweight survey (git stats) | Scouting → Survey, "Run Scouting Scan" (`repo_health`+`repo_language`) | exists |
| Deeper same-level survey (coarse profiling) | Scouting → Coarse Profile (`IngestionPipeline.refresh_profile()`, whole-repo file/language shape) | exists |
| **Recommend which folders/files are worth a closer look** | `SubResourceSurveyor` (`repo_sub_resource_survey` step) — heuristic recommendation list, local-only, no Egeria | exists, **invisible in the UI** (no `analysis_catalog.yaml` entry, no frontend render mode — this is the immediate bug that started this conversation) |
| **Select which recommended items to actually pursue** | — | **does not exist.** `EgeriaPublisher._catalog_sub_resources()` catalogs *every* "worthy" recommendation automatically, with no review/selection gate |
| **Catalog the selection** (track locally; optionally push to Egeria) | — | **partially exists, wrong shape.** "Catalog" today is defined *only* as "create Egeria `FileFolder`/`DataFile` assets" (`_catalog_sub_resources()`) — there is no local-only representation of "this folder is now a tracked sub-resource," so there's no way to catalog without also publishing to Egeria |
| **Deeper survey/analysis scoped to the selection** | — | **does not exist at all.** Confirmed by direct code read: every Assessment/Analysis sub-surveyor (`DataProfilerSurveyor`, `ApiStructureSurveyor`, `SecurityHygieneSurveyor`, `DocumentationSurveyor`) queries its data source unconditionally by `project_slug` only — no sub-surveyor has a scope/path-narrowing parameter. `project_analysis_findings`/`project_analysis_metrics` have no scope column either — only `(project_slug, kind)`. `DataProfilerSurveyor.local_path` looks like scoping but isn't: it's a data-source switch (fresh local clone vs. stored profile), applied uniformly to the *entire* already-computed file set, not a filter |

**One piece of good news confirmed by direct code read**: local survey and Egeria publish are
*already* fully decoupled at the whole-survey level. `SurveyOrchestrator.run()` has zero Egeria
dependency and produces a plain-Python `SurveyResult`; `EgeriaPublisher.publish()` is a separate
call a caller can simply not make. This is exactly the "track locally, publish to Egeria only if
you choose" model already working today for the survey findings themselves (`project_analysis_findings`/`project_analysis_metrics`) — it just doesn't yet extend to the *sub-resource
cataloging* step, which currently has no local-only mode at all.

## Key decisions (draft — flagging where I'm not certain)

**D1 — Generic funnel vocabulary, decoupled from any specific resource type.** Repo is the
worked example, but the pattern should read the same for databases/filesystems eventually
(schemas → tables → columns is the same shape as repos → folders → files). This doc's concrete
schema/UI decisions below are repo-scoped for now; the vocabulary is written to generalize.

Four generic stages, repeatable/recursive:
1. **Survey** — examine what's in scope, produce findings/recommendations. Always local-only,
   already true today (`SurveyOrchestrator.run()`).
2. **Select** — human reviews recommendations, picks a subset to pursue further. New.
3. **Catalog** — the selection becomes a durable, addressable entity: always tracked locally;
   optionally also created as a real Egeria asset, per the user's choice at catalog time (default:
   both). New local-only mode; Egeria-creation part already exists (`_catalog_sub_resources()`)
   but currently isn't optional.
4. **Narrow** — the catalog becomes the new scope for the next Survey, recursively.

**D2 — New local table for "tracked sub-resource," independent of Egeria.** Something like:
```sql
CREATE TABLE project_sub_resources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug   TEXT NOT NULL,
    path           TEXT NOT NULL,       -- relative path; '' = the repo root itself
    kind           TEXT NOT NULL,       -- 'file' | 'folder'
    cataloged_at   TEXT NOT NULL,
    source_finding TEXT DEFAULT '',     -- which survey run recommended it (traceability)
    egeria_guid    TEXT DEFAULT '',     -- '' until/unless published to Egeria
    UNIQUE(project_slug, path)
)
```
This is the missing "local catalog" — the thing D1's Select stage writes to. Egeria publish
becomes a *second*, optional step per row (or bulk): if chosen, run the existing
`_catalog_sub_resources()` logic for just the selected rows and store the returned GUID back.
Un-choosing Egeria at catalog time just leaves `egeria_guid` empty — pure sandbox tracking,
revisitable later (a repo can be re-published incrementally, matching D8's existing idempotency
guard).

**D3 — Selection UI reuses the existing Scouting-discover checklist pattern.** `SubResourceSurveyor`'s
recommendation list already looks exactly like `DiscoveredRepo` search results — a set of
candidates, some worthy, some not, needing a human "select which ones matter" pass. Scouting's
discover-results table already has this UI (checkbox column, "Select all new"/"Deselect all",
default-unchecked-except-recommended) — reuse that component rather than inventing a new pattern.
Confirm/submit writes to D2's table, with an "also publish to Egeria" checkbox (default checked
per the stated default, unchecking is the sandbox-mode escape hatch).

**D4 — `analysis_catalog.yaml` placement for `repo_sub_resource_survey`, reconsidered.** Given
this framing, it's *not* a normal Assessment/Analysis card to browse results on — it's a
funnel-narrowing step, more like Discovery's role ("find resources by what surveys revealed") than
a scored evaluation or structural extraction. Leaning toward **not** giving it a traditional
results card at all, and instead building it as its own small UI surface (recommendation list →
selection → catalog), similar in spirit to how Scouting's Discover tab is its own bespoke view
rather than a generic analysis-catalog card. Open question I don't want to guess past: should this
live under Scouting (as the next tab after Coarse Profile) or under Discovery (matching its
"survey reveals candidates" framing)? Scouting currently has Discover/Survey/Coarse
Profile/Disposition tabs — a "Sub-Resources" tab there would keep the whole repo-level funnel in
one place, but Discovery's stated purpose ("find resources by what surveys revealed") is a closer
semantic match.

**D5 — Scoped deeper survey/analysis (D1's "Narrow" stage applied to Assessment/Analysis) is
real, separate, larger work — not designed in this pass.** Confirmed by direct code read: it
needs (a) a `scope_path` parameter threaded into whichever sub-surveyors make sense to scope
(`ApiStructureSurveyor`/`DataProfilerSurveyor`/`SecurityHygieneSurveyor` plausibly; `DocumentationSurveyor` less obviously so — a doc-coverage check is naturally repo-wide), each
adding a path-prefix filter to its own queries (`project_code_symbols` already has `file_path`,
so this is mechanically possible for API-structure at least); (b) a `scope_path` column added to
`project_analysis_findings`/`project_analysis_metrics` (currently keyed only by
`project_slug, kind[, metric_name]` — no way to keep a folder-scoped run's results distinct from
a whole-repo run's under the same `kind` without this); (c) UI for "run this analysis scoped to
this cataloged sub-resource" and a way to view/compare scoped vs. whole-repo results. Flagging
this explicitly as its own follow-up design pass, not bundled into D1-D4 above — it touches five
surveyors and two core tables, versus D1-D4's one new table and one new UI surface.

## Explicitly not decided here (need your input)

- **D4's placement** (Scouting vs. Discovery) — see above, genuinely unsure which reads better.
- **Which sub-surveyors D5 should support scoping for first** — all four, or just the ones where
  "run this on just one folder" is obviously meaningful (API structure, data profiling, security)?
- **Whether `project_sub_resources` (D2) is repo-specific or should be designed as a generic
  cross-resource-type table now**, given D1's stated goal of the vocabulary generalizing to
  databases/filesystems later — building it generically now costs a bit more design care but
  avoids a rename/migration later if databases get their own "schema → table → column" narrowing.

## Suggested phasing (if this direction is right)

1. **Phase 1** — D2 (local table) + D3 (selection UI) + Egeria-publish-per-catalog-action choice.
   Makes the existing `SubResourceSurveyor`/`_catalog_sub_resources()` work actually visible and
   human-gated, without touching Assessment/Analysis surveyors at all.
2. **Phase 2** — D5 (scoped deeper survey/analysis). Larger, separate design pass once Phase 1's
   local-catalog table exists to scope *against*.

## Verification (once decisions are settled)

- Unit tests: `project_sub_resources` CRUD; selection UI submit round-trip (some selected →
  cataloged, unselected → left as findings-only); Egeria-publish-optional behavior (unchecked →
  `egeria_guid` stays empty, no Egeria calls made at all — a real regression guard, not just "it
  works when checked").
- Live: run the funnel end-to-end against a real repo — survey, review recommendations, select a
  subset (not all), catalog locally-only for one, catalog+publish for another, confirm the
  local-only one never touches Egeria and the published one appears correctly nested (reusing the
  D5/D8 verification already done for the underlying `_catalog_sub_resources()` mechanism).
- Full RE test suite green.
