# Repo scope-narrowing funnel: recommend → select → catalog → scoped analysis

**Status: Phase 1 implemented, tested (860 tests), and live-verified end-to-end against
`sqlglot` (2026-08-11) — see "Phase 1 verification" at the end. Phase 2 (target-shape registry +
compatibility-gated scoped analysis, D5/D6) not started.**

**Decisions confirmed 2026-08-11 (third pass)**: D7 resolved (perspective stays a within-intent
filter, no schema change); mixed-shape kinds get one conservative shape, not per-output tagging,
until real friction shows up; D2's local table is generic across resource types from the start;
database's schema→table narrowing is acknowledged as a natural fit for later, no urgency now;
D6's payoff is repo-specific-weak/other-types-strong, and a genuinely new, repo-specific idea
(dependency-graph lateral exploration) was raised as a result — see the new section below.

**Decisions confirmed 2026-08-11 (fourth pass)**: database's per-card dispatch gap gets fixed
alongside Phase 2, not deferred indefinitely; `index_health` removed from `analysis_catalog.yaml`
(zero backing implementation, not worth advertising); `privilege_audit` kept as-is (also
unimplemented, but not worth deleting).

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

**Revision (2026-08-11, second pass)**: the first draft of this doc treated "select a scope,
catalog it, run deeper analysis on it" as roughly one linear gate. Discussion surfaced six real
problems with that framing, each addressed by its own decision below:

1. Sub-resource *identity* and how multiple surveys attach to one path weren't actually defined.
2. A selection UI needs to be a real filterable/sortable table over the metrics you're deciding
   from, not a plain checklist.
3. There is no single point in the funnel with "enough information" to select once — Scouting
   might select a little, Discovery might refine it further, and re-selection has to be a
   repeatable action against the same underlying catalog, not a one-time gate in one fixed place.
4. There is no universally-correct mapping of survey-type to scope — different organizations will
   want different answers, so the mapping needs to be config-driven and easy to move, not
   hardcoded.
5. Selecting a scope doesn't mean every survey in a phase should run against it — a survey type
   only makes sense against certain *shapes* of target (a whole corpus, a single container, a
   single leaf), and that compatibility has to gate what's even offered.
6. Point 5 can't be designed in the abstract — it needs grounding in what RE's actual survey types
   read today. That grounding pass is now done (see "Target-shape inventory" below) and it
   overturned at least one of my own earlier guesses.

## The funnel, mapped to what exists today

| Stage | RE mechanism today | Status |
|---|---|---|
| Search, find repos | Scouting → Discover (`GET /api/discovery/search`) | exists |
| Lightweight survey (git stats) | Scouting → Survey, "Run Scouting Scan" (`repo_health`+`repo_language`) | exists |
| Deeper same-level survey (coarse profiling) | Scouting → Coarse Profile (`IngestionPipeline.refresh_profile()`, whole-repo file/language shape) | exists |
| **Recommend which folders/files are worth a closer look** | `SubResourceSurveyor` (`repo_sub_resource_survey` step) — heuristic recommendation list, local-only, no Egeria | exists, **invisible in the UI** (no `analysis_catalog.yaml` entry, no frontend render mode — this is the immediate bug that started this conversation) |
| **Select which recommended items to actually pursue** | — | **does not exist.** `EgeriaPublisher._catalog_sub_resources()` catalogs *every* "worthy" recommendation automatically, with no review/selection gate |
| **Catalog the selection** (track locally; optionally push to Egeria) | — | **partially exists, wrong shape.** "Catalog" today is defined *only* as "create Egeria `FileFolder`/`DataFile` assets" (`_catalog_sub_resources()`) — there is no local-only representation of "this folder is now a tracked sub-resource," so there's no way to catalog without also publishing to Egeria |
| **Deeper survey/analysis scoped to the selection** | — | **does not exist for repos, and is only partially real for databases** — see "Target-shape inventory" below |

**One piece of good news confirmed by direct code read**: local survey and Egeria publish are
*already* fully decoupled at the whole-survey level. `SurveyOrchestrator.run()` has zero Egeria
dependency and produces a plain-Python `SurveyResult`; `EgeriaPublisher.publish()` is a separate
call a caller can simply not make. This is exactly the "track locally, publish to Egeria only if
you choose" model already working today for the survey findings themselves — it just doesn't yet
extend to the *sub-resource cataloging* step, which currently has no local-only mode at all.

## Target-shape inventory (grounded, 2026-08-11 code audit)

Every survey/analysis kind that exists today, and what shape of target it can mechanically operate
on if scope were narrowed below "the whole resource." **Corpus** = works over the whole resource
or any container + everything recursively below it, because the underlying query/walk is already
per-leaf and just needs a path-prefix filter. **Single-container** = has a real hierarchy in its
own code shape (e.g. database's schema→table) but doesn't sensibly recurse arbitrarily deep.
**Whole-resource-only** = the data it reads is inherently a single aggregate for the whole
resource; narrowing it isn't a query change, it's a different analysis.

### Repo

| Analysis kind | Reads | Shape | Why |
|---|---|---|---|
| `repo_file_size` | `project_file_inventory` (per-file) | **Corpus** | Synthetic per-file table; `WHERE file_path LIKE 'dir/%'` is trivial. |
| `repo_api_structure` | `project_code_symbols` (has `file_path`, currently unfiltered) | **Corpus** | Per-symbol/per-file table; path-prefix filter trivial to add. |
| `repo_data_profiling` | `project_file_inventory` + `project_data_profiles`, both per-file | **Corpus** | Same as above. |
| `repo_file_classification` | Flat path list from `project_file_inventory`/fallbacks | **Corpus** | `classify_file_paths()` is explicitly path-agnostic already. |
| `repo_sub_resource_survey` | `project_file_inventory` (per-file) | **Corpus** | Its own "depth-1 folder" heuristic naturally re-baselines to whatever root is passed in. |
| `repo_file_structure` | **Mixed**: `project_code_symbols` (per-file, 2 of 3 annotations) + `project_stats` (1 aggregate row) | **Whole-resource-only (by decision, not by necessity)** | Two of three outputs are genuinely path-filterable; the size/loc aggregate isn't. Per D-resolved below, RE stays with one shape per kind rather than per-output tagging until real friction shows up — so this kind takes its most restrictive shape rather than gaining special-case logic. Revisit if this turns out to matter in practice. |
| `repo_language` | `project_stats.language_breakdown` (1 aggregate row, GitHub-computed) | **Whole-resource-only** | No per-file/per-directory row exists to filter — would need re-deriving from `project_code_symbols` instead, a different analysis. |
| `repo_health` | `project_stats` + live GitHub stats (stars/forks/releases) | **Whole-resource-only** | Repo-level GitHub metadata; no folder/file concept applies. |
| `repo_documentation` | `project.collections` + hygiene filenames | **Whole-resource-only** | README/CHANGELOG/LICENSE presence and doc-collection membership are inherently repo-root concepts. "Does this folder have its own README" is a different, unbuilt question. |
| `repo_security` | Hygiene filenames + `project_stats.license` | **Whole-resource-only** — **correction from my first draft**, which guessed this was "plausibly" scopable. It isn't: SECURITY.md/LICENSE presence is a root-level artifact by definition; a subfolder doesn't have "its own" security policy. |

### Database

| Analysis kind | Backing | Shape | Why |
|---|---|---|---|
| `schema_inventory` | `get_schema_info()` — **already loops per-schema in its own code** | **Whole-DB → schema → table**, a real existing hierarchy | Narrowing to one schema is a one-line change (skip the loop); narrowing to one table is also natural (`_get_tables_for_schema` already returns one dict per table). |
| `row_count_snapshot` | `pg_stat_user_tables`, unfiltered but has `schemaname`/`relname` per row | **Single-container-or-corpus** | Trivial to filter to one schema or a table list; a single-column floor makes no sense (counts are table-level). |
| `privilege_audit` | **No implementation exists at all.** | n/a | Aspirational, zero backing code — kept in the catalog anyway (confirmed 2026-08-11): not worth deleting, low priority to build. If built, likely whole-DB-or-schema in spirit (grants aren't folder-like). |
| `egeria_db_survey` | Egeria's native async survey, triggered by asset guid only | **Whole-resource-only** | No schema/table target parameter exists in the trigger API. |

**Also found, unrelated to scope shape but relevant to trusting any of this**: the web UI's "Run"
action for database analyses doesn't dispatch by catalog id at all — clicking any of the three
remaining database cards (`schema_inventory`/`row_count_snapshot`/`privilege_audit`) triggers the
identical whole-database `DatabaseSurveyor.survey()`, regardless of which was clicked. Repo already
does real per-card scoped dispatch (`REPO_ANALYSIS_STEP_MAP`); database doesn't. **Confirmed
2026-08-11: fix this alongside the rest of this doc's implementation**, not deferred — a
prerequisite for database ever getting real scope-narrowing is first making its per-card dispatch
real. `index_health` (confirmed 2026-08-11: removed from `analysis_catalog.yaml` — zero backing
implementation, not worth advertising) is no longer in this list.

### Filesystem

| Analysis kind | Backing | Shape | Why |
|---|---|---|---|
| `filesystem_inventory` | `LocalFileSystemSurveyor`, walks recursively from `self.root_path` | **Corpus — the cleanest case of all three resource types** | The surveyor was never table-query-based; it's already parameterized by a single root path. Pointing that path at any subfolder instead of the configured mount point produces the identical shape of result for that subtree. No query/schema change needed at all. |

## Key decisions

**D1 — Generic funnel vocabulary, decoupled from any specific resource type.** Repo is the worked
example and the concrete implementation below is repo-scoped, but the target-shape inventory above
already confirms the same four generic stages recur for database (schema→table has a real
hierarchy) and filesystem (the cleanest corpus case of the three). Four stages, repeatable and
non-linear (see D4):
1. **Survey** — examine what's in scope, produce findings/recommendations. Always local-only,
   already true today.
2. **Select** — human reviews recommendations, picks a subset to pursue further.
3. **Catalog** — the selection becomes a durable, addressable entity: always tracked locally;
   optionally also created as a real Egeria asset, per the user's choice at catalog time (default:
   both).
4. **Narrow** — the catalog becomes the new scope for the next Survey, recursively — but only for
   survey types whose target shape is compatible with what was selected (see D6).

**D2 — New local table for "tracked sub-resource," independent of Egeria, built generically across
resource types from the start (confirmed — not repo-specific, even though repo ships first).**
Identity is `(resource_type, resource_slug, locator, kind)`; survey associations are NOT a new
junction table.
```sql
CREATE TABLE sub_resources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type  TEXT NOT NULL,       -- 'repo' | 'database' | 'filesystem'
    resource_slug  TEXT NOT NULL,       -- project_slug / database_slug / filesystem_slug
    locator        TEXT NOT NULL,       -- hierarchical locator: repo/fs relative path;
                                         -- database is 'schema' or 'schema.table'. '' = the
                                         -- resource root itself. THIS is the sub-resource's name.
    kind           TEXT NOT NULL,       -- 'file' | 'folder' (repo/fs); 'schema' | 'table' (database)
    cataloged_at   TEXT NOT NULL,
    source_finding TEXT DEFAULT '',     -- which survey run recommended it (traceability)
    egeria_guid    TEXT DEFAULT '',     -- '' until/unless published to Egeria
    UNIQUE(resource_type, resource_slug, locator)
)
```
`locator`'s meaning is resource-type-specific (a path for repo/filesystem, a dotted
schema/schema.table reference for database) but the table itself, its CRUD, and the selection UI
built against it (D3) are shared. This table only records *that something is a tracked target* —
it is not where "which surveys ran against it" lives. That question is answered by extending
`project_analysis_findings`/`project_analysis_metrics` (and their eventual database/filesystem
counterparts) with a `scope_locator` column (default `''` = whole-resource, matching every
existing row unchanged): "what's been run against `docs/`" becomes
`WHERE project_slug=? AND scope_locator='docs'`, the same shape of query already used for
`WHERE scope_locator=''` today. Multiple surveys against one cataloged locator fall out of this
for free — no new table needed for that part.

**D3 — Selection UI is a real filterable/sortable metrics table, not a checklist.** The
`SubResourceSurveyor` recommendation list already carries D9/D10's metadata (size, mode, owners,
last-updated) per entry — the selection UI should surface those as real columns you can sort and
filter by, reusing the exact component pattern already built for Scouting's discover-results table
(checkbox column, column sort, client-side filter, "Select all"/"Deselect all", default-unchecked
except what the heuristic already marked worthy) rather than a plain list of checkboxes. Confirm
writes to D2's table, with an "also publish to Egeria" checkbox (default checked, unchecking is
the sandbox-mode escape hatch).

**D4 — Selection/cataloging is a repeatable action reachable from multiple places, not a one-time
gate in one fixed UI location.** There's no single point in the funnel with "enough information"
to select once and be done — a user might catalog a couple of obviously-important folders from
Scouting, then come back after a deeper Discovery-stage survey and catalog more (or reconsider
earlier choices) with better information. The UI for "review recommendations → select → catalog"
needs to be a reusable panel/component backed by the same `project_sub_resources` table, invokable
from wherever the user currently has relevant information — not hard-coded to live under exactly
one of Scouting or Discovery. This replaces my first draft's D4, which asked "which single intent
should own this" — the answer is that ownership-by-one-intent was the wrong frame.

**D5 — Target-shape compatibility must be config-driven and extensible, not hardcoded — no
mapping here is universally correct. One shape per analysis kind (confirmed) — no per-output
tagging until real friction shows up.** Different organizations will reasonably want different
answers to "should `repo_security` ever be offered against a single folder" — the inventory above
is RE's own best-guess grounding, not gospel. Mirror the existing `ANALYSIS_KINDS`/`STEP_REGISTRY`
extensibility pattern already used elsewhere in this codebase: add a `target_shape` field to each
`analysis_catalog.yaml` entry (`corpus` | `single_container` | `single_leaf` | `whole_resource_only`)
rather than encoding shape compatibility as branching logic anywhere in Python. A new analysis kind
declares its own shape in one YAML field; nothing else needs to change to make the compatibility
check aware of it. Mixed-output kinds like `repo_file_structure` take their single most-restrictive
shape (see the table above) rather than gaining per-output special-casing — simplicity wins until
there's a concrete case where it doesn't.

**D6 — Selecting a scope must gate which analyses are even offered, not just parameterize all of
them — though this payoff is uneven across resource types, confirmed weaker for repo than for
database/filesystem.** Directly from the inventory: repo's own analysis kinds split heavily toward
whole-resource-only (health, language, documentation, security, and now file-structure by D5's
single-shape decision) — only four of ten repo kinds are actually corpus-shaped. Database's
schema→table hierarchy and filesystem's clean recursive-corpus shape get more real mileage out of
this gating than repo does. Keep D6 as the general mechanism (it's still correct for the kinds that
do vary), but don't expect it to be repo's highest-value payoff — that turned out to be something
else, see "Lateral exploration via dependencies" below.

**D7 — `perspectives` stays a pure within-intent filter (confirmed, no schema change).**
`perspectives` (`dba`/`data_scientist`/`steward`/`security`/`all`) continues to narrow which cards
are visible *within* whichever intent tab is already active; it does not influence which intent a
kind is placed under. `intent` stays a single scalar per `analysis_catalog.yaml` entry — no move to
`(intent, perspective)` pairs. This resolves what the first revision flagged as the highest-leverage
open question, in favor of the simpler existing model.

## Other decisions confirmed, not requiring new design

- **Database's schema→table narrowing** is acknowledged as a natural fit for D1-D6's model
  whenever it's built — no urgency, no design changes needed now beyond what's already generic
  (D2). Noted explicitly since "we haven't spent a lot of effort recently beyond Repos" is the
  reason it's not further along, not a sign the model doesn't fit.
- **`repo_file_structure`'s mixed-shape output** — resolved by D5 (single most-restrictive shape,
  not per-output tagging).
- **`project_sub_resources`/`sub_resources` (D2) is generic across resource types**, confirmed —
  see the revised schema above.

## Still open (need your input)

- **Dependency-graph lateral exploration** (new, see below) — how far does the "follow a
  dependency to its own source repo" chain go before stopping, and does it write anything (a
  suggestion, a disposition-`undecided` pre-registration) or purely surface a "you might also want
  to scout these" list for the human to act on?

## Lateral exploration via dependencies (new, repo-specific — not part of the vertical funnel above)

Everything above is a *vertical* narrowing pattern — repo → folder → file, schema → table →
column. Repo dependency analysis suggests a genuinely different, *lateral* pattern: `repo_dependency`
already surveys a repo's declared external dependencies (`project_dependencies`, populated by
`DependencySurveyor` from manifest files) — each dependency is itself, often, a real open-source
repo with its own `SourceControlLibrary`. Two ideas raised, neither designed here:

1. **Dependency health** — a future summary view answering "how healthy are the things this repo
   depends on" (staleness, maintenance activity, security posture of each dependency) — a natural
   extension of `repo_dependency`'s existing data, read *about* the dependencies rather than
   surveying them directly.
2. **Dependency-driven Scouting discovery** — following a dependency to its own GitHub repo could
   feed directly into Scouting's existing "candidate repos to explore" flow (`discovery.py`'s
   search/import path already built this session), rather than requiring a fresh manual search.
   This needs an explicit stopping rule (depth limit, opt-in per hop, dedup against
   already-registered/already-dispositioned repos) — "you obviously have to stop somewhere," in the
   user's own words — not designed here, just named so it's on record as the next real idea once
   the vertical funnel work above lands.

## Suggested phasing (if this direction is right)

1. **Phase 1 — implemented 2026-08-11.** D2 (local table) + D3 (selection UI, reusable per D4) +
   Egeria-publish-per-catalog-action choice. Makes the existing `SubResourceSurveyor`/
   `EgeriaPublisher.publish_sub_resources()` (renamed from `_catalog_sub_resources()` — it's no
   longer an automatic side effect of a full publish, always an explicit, separate action now)
   work actually visible and human-gated, without touching Assessment/Analysis surveyors at all.
   See "Phase 1 verification" below for what shipped and how it was confirmed.
2. **Phase 2 — not started.** D5 (target-shape registry) + D6 (compatibility-gated scoped analysis). Larger,
   separate design pass — touches five-plus surveyors and two core tables, once Phase 1's local
   catalog exists to scope *against*. **Confirmed 2026-08-11: database's per-card dispatch fix
   (`REPO_ANALYSIS_STEP_MAP`-equivalent for database) happens alongside this phase** — a
   prerequisite for database's schema→table narrowing to mean anything, since all three remaining
   database cards currently trigger the identical whole-DB survey regardless of which was clicked.

## Phase 1 verification (done, 2026-08-11)

**What shipped, with two deviations from the design above, both noted at the point they were
made:**
- `sub_resources` table (D2's schema) gained one extra column beyond what's written above:
  `detail_json` — a denormalized snapshot of the source finding's owners/dates at catalog time,
  so `publish_sub_resources()` never needs to re-join back to `project_analysis_findings` (which a
  later survey run could have superseded). Everything else matches D2 exactly.
- D4 left "which intent owns the selection UI" deliberately unresolved (repeatable action,
  reachable from wherever). Phase 1 shipped it as a fifth Scouting sub-tab ("🗂 Sub-Resources",
  alongside Search/Survey/Coarse Profile/Disposition) — a real decision, not a re-opening of D4's
  point: the panel/component itself (`loadScoutingSubResourcesView`) is a normal, callable
  function, not hard-wired into Scouting's routing in a way that would block adding a second entry
  point (e.g. from Discovery) later without rework.

**Backend**: `sub_resources` registry table + CRUD (`catalog_sub_resource`/`uncatalog_sub_resource`/
`list_sub_resources`/`set_sub_resource_egeria_guid`, all idempotent per D4); `EgeriaPublisher
.publish_sub_resources(resource_slug, github_url, asset_guid, locators)` replacing the old
auto-triggered `_catalog_sub_resources()` — reads only already-locally-catalogued rows, never
findings directly; three new routes (`GET/POST/DELETE /api/projects/{slug}/sub-resources[/catalog]`)
with ancestor-folder auto-inclusion at catalog time (mirroring `SubResourceSurveyor`'s own
guarantee — promoted `_ancestor_folder_paths` to a public module-level `ancestor_folder_paths()`
so the route didn't need to reach into a private survey-internal method).

**Frontend**: new Scouting sub-tab, reusing the sortable/filterable table pattern from Scouting's
discover-results view (D3) — click-to-sort columns (path/kind/worthy/reason/last-updated),
substring filter, checkbox column pre-checked for "worthy" findings, already-catalogued rows shown
disabled with a ☁ Published / 🗂 Catalogued status badge, "also publish to Egeria" checkbox
(default checked).

**Tests**: 25 new (9 registry CRUD, 12 rewritten `EgeriaPublisher` tests for the new
`publish_sub_resources()` signature, 14 new route tests including the ancestor-auto-inclusion
regression guard) — 860 total passing.

**Live, against `sqlglot`, through the real UI** (not just direct Python/API calls): sortable
columns and substring filter both confirmed correct; catalogued `LICENSE` locally-only
(unchecked "publish to Egeria") and confirmed via direct registry query that `egeria_guid` stayed
empty and zero Egeria calls were made — the sandbox-mode escape hatch actually works, not just "it
works when checked"; catalogued `CHANGELOG.md` with Egeria publish checked and confirmed both it
and its ancestor synthetic-root folder resolved to the *exact same* Egeria GUIDs as an earlier,
unrelated live-verification pass earlier in this session — real proof that qualifiedName-based
idempotency holds across independent publish calls, not just within one. Ancestor auto-inclusion
confirmed both for the local-only and Egeria-publish paths, through the real click path (not a
direct function call).

## Verification (Phase 2, once its decisions are settled)

- Unit tests: D5's target-shape registry — every existing analysis kind's declared shape matches
  the inventory above (regression guard against the audit going stale); D6's menu-filtering — a
  single-leaf-selected sub-resource never offers a whole-resource-only kind.
- Live: from a cataloged sub-resource, run a scoped analysis and confirm the menu only offers
  target-shape-compatible kinds; confirm database's per-card dispatch fix actually runs only the
  clicked analysis, not the whole-DB survey, mirroring the regression check already done for repo's
  `REPO_ANALYSIS_STEP_MAP` when it shipped.
- Full RE test suite green.
