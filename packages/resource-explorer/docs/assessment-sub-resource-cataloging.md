# Assessment sub-resource cataloging — design pass

**Status: design only, not built.** Flagged as roadmap-only in `docs/repo-phase-visibility-model.md`'s
visibility-source matrix ("optionally catalog specific sub-resources (folders/files) as child assets —
not built, roadmap only"). This is that design pass, grounded in a direct read of `EgeriaPublisher`,
the three Assessment sub-surveyors, `project_file_inventory`'s schema, and pyegeria's actual asset-
creation APIs — not assumptions.

**Revised 2026-08-11 (1st pass)** to separate *survey* from *catalog* as two distinct steps, rather than
treating "a sub-surveyor's finding mentions a file" as the trigger for creating it as an asset. See
"Survey vs. catalog" below.

**Revised 2026-08-11 (2nd pass)** to add real file/folder *metadata* capture (permissions, size, last-
update, ownership) and the Assessment-facing analytics built on top of it (kind/size/staleness/ownership
distributions, growth over time via re-survey) — see "Metadata capture" and "Analytics dimensions"
below, and D9-D13.

## Context

Assessment's job (per `repo-phase-visibility-model.md`) is "existing tables only, deeper analytics —
no new fetch": `SecurityHygieneSurveyor`, `DocumentationSurveyor`, and `ApiStructureSurveyor` all read
already-persisted data (`project_code_symbols`, `project_stats`, `project_code_relationships`) and
publish repo-scoped findings/metrics annotations. None of them produce per-file or per-folder Egeria
elements — `file_path` values are read for matching/grouping but never surfaced individually. That's
the gap this plan closes: a small number of *specific, individually-significant* files and folders (not
"every file in the repo") get cataloged as their own child Egeria assets, so someone browsing the
catalog can land directly on "the SECURITY.md this repo does/doesn't have," not just a repo-level
yes/no finding.

**What this explicitly is NOT**: a full filesystem-mirror of every repo file into Egeria. Grounded in
`project_file_inventory`'s real schema (`project_slug, file_path, file_size_bytes, indexed_at` — a flat
per-file row, no folder-node table), a repo can carry thousands of file rows; creating one Egeria asset
per row is both the wrong information architecture (nobody wants to browse a repo's `node_modules` as
1,200 individual Egeria assets) and prohibitively expensive (each `create_elem_from_template` call is a
real network round-trip to Egeria, and there's no bulk/batch variant in the APIs this codebase uses).

## Survey vs. catalog — the core distinction

Confirmed against Egeria's own native pattern, not just by analogy — `AutomatedCuration
.initiate_file_folder_survey(file_folder_guid, survey_name)` in the pyegeria this codebase depends on
operates on an **already-cataloged** folder GUID, and its own docstring lists four real survey variants:

```
Egeria:GovernanceActionType:AssetSurvey:survey-folders
Egeria:GovernanceActionType:AssetSurvey:survey-folder-and-files
Egeria:GovernanceActionType:AssetSurvey:survey-all-folders
Egeria:GovernanceActionType:AssetSurvey:survey-all-folders-and-files
```

That's Egeria's own model, and this design adopts its shape:

1. **Catalog the root once.** For repos, this already exists — `EgeriaPublisher._find_or_create_asset()`
   creates/finds the `SourceControlLibrary` asset. No new work needed here; the root is always cataloged
   as a precondition of publishing anything at all.
2. **Survey from that root, to a controllable depth.** The survey walks file/folder *characteristics*
   only — names, sizes, counts, extension mix — never content. Depth/scope is a real, tunable dial (the
   folders-only vs. folder+files, shallow vs. recursive axes Egeria's own variant names encode).
3. **The survey's output is a recommendation, not a side effect.** Walking/examining a file or folder
   does not catalog it. The survey's job is specifically to determine what's *worthy* of becoming its
   own asset for further analysis — cataloging is a separate, later, deliberate act that consumes that
   recommendation.

**Why RE can't just call Egeria's native `initiate_file_folder_survey` directly**: that engine needs the
folder to physically exist somewhere one of Egeria's own integration connectors can reach — true for
`EgeriaFileSystemSurveyor`'s genuinely-mounted filesystems, not true for repos. RE downloads a repo's
zipball into a `tempfile.TemporaryDirectory()` and deletes it immediately after profile refresh (the
no-persistent-clone convention this whole codebase relies on) — there's nothing durable left for
Egeria's native engine to survey afterward. So RE's own code has to *do* the survey step itself, using
`project_file_inventory` (already persisted by the Profile phase, file paths + sizes, no content) as the
data source — but it should adopt Egeria's same two-phase shape rather than re-inventing something
weaker.

## Metadata capture — what's actually available, and at what cost

The survey should capture real filesystem/git metadata (permissions, size, last-update, ownership,
created), not just path+size. What's genuinely available splits into two very different cost tiers —
confirmed by reading PyGithub's actual response shapes and this codebase's existing API usage, not
assumed:

**Tier 1 — free, already in the one API call RE makes today.** `GitHubClient`/`StatsFetcher` already
call `repo.get_git_tree(sha, recursive=True)` to build the file inventory. Each returned
`GitTreeElement` carries `mode` (`"100644"` regular, `"100755"` executable, `"120000"` symlink,
`"040000"` subtree) and `size` alongside `path` — RE's current code (`client.py`'s `list_files()`/
`_list_files_walk()`) reads `.path` and discards `mode`/`size` even though they cost nothing extra.
Capturing them for **every** inventoried file, not just the survey's worthy subset, is free.

**Also Tier 1 — cheap, one file, covers the whole repo.** `CODEOWNERS` (root, `.github/`, or `docs/`,
per GitHub's own lookup order) maps path *patterns* to owning teams/individuals. Parsing it is one file
fetch + local glob-pattern matching against every path already in the inventory — no per-file API cost,
and (unlike per-file commit history) it gives a real ownership signal for the *entire* repo, not just a
small flagged subset. `DocumentationSurveyor` already checks for `CODEOWNERS`'s mere *presence* (as one
of its hygiene files) but never parses its contents — this plan is the first thing to actually read it.

**Tier 2 — expensive, and does not have a batch form.** "Last commit that touched path X" and "first
commit that added path X" are git-history questions — the git tree/blob objects themselves are
content-addressed and carry no timestamp at all (this is inherent to git's object model, not a PyGithub
limitation). The only sources are `Repository.get_commits(path=X)` (REST, one call per file) or GraphQL's
`history(path: X)` (still one query per file to reach a specific path's history) — confirmed: **no
bulk/multi-path variant exists** in PyGithub's surface or in GitHub's REST API, and RE has zero existing
GraphQL client code to fall back on (a docstring in `client.py` claims GraphQL is "available via
`query()`" — confirmed false, no such method exists). Per-file, this is a real GitHub API cost that
scales with file count.

**The honest consequence**: a *complete, whole-repo* staleness/age distribution (every file's real
last-modified date) is not cheap and is explicitly out of scope for this pass — it would need either a
real `git clone` with history (a genuine architecture change away from RE's zipball-only, no-persistent-
clone convention) or GitHub GraphQL query batching (aliased sub-queries in one request, reducing N calls
toward N/50-ish — a real technique, but RE has no GraphQL client today, so this is new client
infrastructure, not a config toggle). D9 below scopes staleness capture to what's actually affordable
now: the survey's own small worthy-subset (already bounded by D1's heuristics), not the full inventory.

## Analytics dimensions — what Assessment should be able to show

Grounded in the cost tiers above, plus one important finding: **file-kind distribution and trending
already exist** — `FileClassifierSurveyor` already classifies files (Egeria-first: `file_classifier.py`
calls `ValidMetadataManager.get_valid_metadata_value()`/`get_valid_metadata_values()` against Egeria's
own `DataFile` valid-value set for `fileName`/`fileExtension`, falling back to a small built-in table
only when Egeria has no answer) and persists results to `project_file_type_counts`, an append-only,
`surveyed_at`-stamped table with a working trend reader (`query_file_type_history()`) already powering a
chart. **This plan should reuse that, not duplicate it** — "kind distribution, using Egeria's broader
value set" is mostly already built; the gap is everything *else*:

| Dimension | Source | Cost | Status |
|---|---|---|---|
| Kind/type distribution | `FileClassifierSurveyor` → Egeria `DataFile` valid values | Already paid for | **Already built** — reuse, don't duplicate |
| Size distribution | Tier 1 (git tree, free) | Free, whole repo | New — D10 |
| Permission/mode distribution (executable files, symlinks) | Tier 1 (git tree, free) | Free, whole repo | New — D10 |
| Ownership (CODEOWNERS-mapped) | Tier 1 (one file, free) | Free, whole repo | New — D9/D12 |
| Staleness/age distribution | Tier 2 (per-file commit history) | Expensive, no batch form | New, **scoped to the worthy subset only** — D9 |
| Growth over time | Re-survey + append-only snapshot | Same pattern as `project_file_type_counts` | New — D11 |

## Grounding (confirmed via direct code/API inspection, 2026-08-10/11)

- **The only existing parent→child asset-linkage mechanism in this codebase** is `AssetMaker
  .create_asset(body)` / `AutomatedCuration.create_elem_from_template(body)` with `parentGUID` +
  `parentRelationshipTypeName` set in the request body — there is no dedicated "create child asset"
  method. `EgeriaPublisher._create_survey_report()` and `_create_annotations()` already use exactly
  this pattern (`parentRelationshipTypeName: "ReportSubject"` / `"ReportedAnnotation"`).
- **Closest existing precedent**: `EgeriaFileSystemSurveyor.catalog_and_survey()` — creates one root
  `DataFolder` asset (`AutomatedCuration.create_folder_element_from_template()`) plus one `DataFile`
  child asset per data file in its inventory (`_create_data_file_asset()`, format-specific template
  GUIDs). **Real gap found in that precedent**: it sets `"isOwnAnchor": True` and never actually sets
  `parentGUID`/`parentRelationshipTypeName` linking each file asset back to the folder asset — so even
  this closest analog doesn't produce a real graph edge between parent and child today, only a
  same-`fileSystemName` naming convention. This plan should not silently inherit that gap (see D4).
  It also conflates survey and catalog into one pass (every inventoried data file is cataloged, none are
  merely surveyed-and-skipped) — this plan deliberately does not copy that part either.
- **`EgeriaDatabaseSurveyor` is a partial precedent, revised understanding**: it doesn't create per-
  schema/per-table assets in RE's own code — but it *does* trigger Egeria's own native async survey
  engine server-side, which is exactly the survey-then-selectively-catalog split this design wants,
  just for Postgres instead of repos. The reason RE can't reuse the *engine itself* for repos is the
  ephemeral-clone constraint above, not that the underlying model is wrong — the model is right, RE
  just has to implement the survey half itself.
- **pyegeria has no repo-file-specific convenience method.** `AutomatedCuration
  .create_folder_element_from_template()` is filesystem-shaped (`file_system` param) and DataFile
  templates are picked by format (CSV/Parquet/Excel/generic) — neither maps cleanly onto "a source file
  in a git repo," but both are directly reusable for whatever folders/files the survey step flags.
  `CollectionManager.create_folder_collection()` + `.add_to_collection()`
  (`CollectionMembershipProperties` relationship) is a real alternative: model sub-resources as
  Collection members instead of nested Asset elements. Decision D3 below picks between these.

## Key decisions

**D1 — The survey is a new, explicit step (`SubResourceSurveyor`), not an incidental byproduct of
existing findings.** New sub-surveyor, `sub_surveyors/sub_resource_survey.py`, `STEP =
"SubResourceSurvey"`. Reads only `project_file_inventory` (already persisted by the Profile phase — no
new fetch, matching Assessment's own "existing tables only" scope) and produces a **worthiness
recommendation list** — folders and files, each with a reason and a confidence — as its own finding
(`kind="repo_sub_resource_survey"`, using the existing generic `upsert_finding()`/`query_findings()`
machinery — no new table). This step does **not** call Egeria at all; like every other surveyor, it only
reads registry tables and returns annotations/findings.

Depth/scope is a real, named parameter (mirroring Egeria's own four variants), not a hardcoded default:
- `max_depth` (int, default **2**) — path segments from repo root. Depth 2 reaches e.g. `docs/README.md`
  or `src/index.ts` but not `src/lib/internal/deep/file.ts`. Chosen as the practical default because it
  catches virtually every hygiene-file and top-level-structure case while keeping the walk cheap even on
  large repos (`project_file_inventory` rows are already in memory once fetched — the cost that matters
  is downstream Egeria asset creation, not this scan).
- `include_folders` (bool, default **True**) — whether folders themselves are eligible for their own
  recommendation, not just files (reverses the original draft's "no folder assets" stance — see D4).

**Worthiness heuristics** (a starting, tunable set — not exhaustive, and deliberately simple enough to
explain in one line each; expected to need real-world tuning after live use, same as `HealthSurveyor`'s
scoring did):
- A file matching a fixed, well-known-significant name list (`SECURITY.md`, `LICENSE`, `CODE_OF_CONDUCT.md`,
  `CONTRIBUTING.md`, `README.md`, `CHANGELOG.md`) at any depth up to `max_depth` → always worthy,
  `reason="well_known_file"`.
- A folder at depth 1 (a repo's immediate top-level directories — `src/`, `docs/`, `tests/`, etc.) whose
  file count falls in a **"meaningfully browsable" range, default 2–200 files** → worthy,
  `reason="top_level_structural_folder"`. Below 2: not worth a folder-asset distinct from just flagging
  its one file directly (covered by the well-known-file rule if applicable). Above 200: too broad to be
  a useful single browsing target without deeper judgment this pass doesn't attempt (e.g. `node_modules`,
  vendored dependencies) — flagged as *not* worthy rather than silently included, so the survey's finding
  can show "47 folders seen, 6 recommended, 41 skipped as too broad/too small" rather than looking
  incomplete.
- Everything else at or beyond `max_depth`, or a folder outside the browsable range → not recommended.
- **Synthetic root folder rule** (added after D5's pre-flight check confirmed a file can never be
  parented directly to the repo's `SourceControlLibrary` — see D4): whenever at least one depth-1 file
  is worthy by the well-known-file rule, a synthetic root-folder entry (`path=""`, `reason=
  "root_container_for_worthy_files"`) is added to the worthy set automatically, even if depth-1's file
  count would otherwise fall outside the 2–200 browsable range. This is bookkeeping to satisfy Egeria's
  real type constraints, not a new judgment call — it never appears as a *skipped* candidate the way the
  file-count heuristic's rejections do.

**D2 — `SecurityHygieneSurveyor`/`DocumentationSurveyor` stay exactly as they are — decoupled from
cataloging.** The original draft had them each emit a `flagged_files` list feeding cataloging directly;
that's removed. Those two surveyors keep doing exactly what they do today (repo-scoped presence/quality
findings) with zero changes. `SubResourceSurveyor`'s well-known-file heuristic (D1) will independently
reach the same files (SECURITY.md, README, etc.) for its own reason (structural significance, not
"security policy" or "doc quality") — the two surveyors' findings can agree in practice without being
architecturally coupled. This avoids a cross-surveyor dependency (one surveyor's output shape driving
another's behavior) that the original draft would have introduced.

**D3 — Model as DataFile *and* FileFolder Asset elements (matching the filesystem precedent), not
Collection membership.** (Corrected 2026-08-11: Egeria's real type is `FileFolder`, not `DataFolder` —
confirmed live in D5's pre-flight check via both the relationship type descriptions and the actual
entity-type-mismatch error messages Egeria returned.) Consistency with `EgeriaFileSystemSurveyor`
matters more here than the two approaches' minor capability differences — a catalog user browsing
"files/folders across all resource types" shouldn't hit two different element shapes depending on
whether the parent happens to be a repo or a filesystem mount. `AutomatedCuration
.create_folder_element_from_template()` (proven, already used by `EgeriaFileSystemSurveyor`, template
resolved live via `_async_get_template_guid_for_technology_type("File System Directory")`) creates the
folder assets; the equivalent `"Data File"` technology-type template lookup creates the file assets
(the filesystem precedent's *hardcoded* CSV/Parquet/Excel template GUIDs happened to still be valid on
the live instance checked, but its hardcoded *generic*-file GUID did not — see D5). `CollectionManager`'s
model stays the right choice for genuinely organizational groupings elsewhere in this codebase; this is
asset cataloging, not grouping.

**D4 — Folders can now be cataloged too, not just files** (reverses the original draft's D4 "no
intermediate Folder asset layer" — that constraint existed only because the original design's selection
was file-only and incidental; a real survey step with a folder-worthiness heuristic (D1) makes folder
assets a first-class, deliberate output, matching Egeria's own `survey-folders`/`survey-all-folders`
variants treating folders as surveyable in their own right). A worthy folder becomes a `FileFolder`
asset parented to the repo's `SourceControlLibrary`; a worthy file inside a worthy folder is parented to
*that* folder asset (real nesting), not flattened directly under the repo root.

**Revised after D5's pre-flight check**: a worthy *file* can never be parented directly to the repo's
`SourceControlLibrary` — Egeria's real `NestedFile` relationship strictly requires a `FileFolder` on the
parent end (confirmed live, see D5). So the original plan for "a lone `SECURITY.md` at repo root, no
containing folder flagged worthy" — parent it directly to the repo asset — **does not work** and is
replaced: `SubResourceSurveyor`'s heuristic (D1) is revised so a synthetic **root folder** (representing
the repo's own top level, `relativePath=""`) is *always* included in the worthy set whenever at least
one top-level file is worthy, even if the root itself wouldn't otherwise pass the folder file-count
heuristic. Every worthy file's immediate parent is always some `FileFolder` — either a heuristic-flagged
real subfolder, or this always-present root-level one — never the `SourceControlLibrary` asset directly.

**D5 — Fix the parent-linkage gap; do not repeat it — confirmed live, 2026-08-11.** Every cataloged
asset (file or folder) gets a real `parentGUID` and `parentRelationshipTypeName` set in the
`create_elem_from_template` body — not just a naming convention. The pre-flight check flagged as
required before implementation has been run against a real Egeria instance (`qs-metadata-store`, via a
throwaway `SourceControlLibrary`→`FileFolder`→`FileFolder`/`DataFile` chain created and deleted against
the live `sqlglot` asset) and confirmed all three edge shapes, using Egeria's own error messages (which
name the exact expected entity types on each end when a type is wrong) and each type's own registered
description to pick the semantically correct name where more than one candidate technically succeeded:

| Edge | Confirmed relationship type | Egeria's own description |
|---|---|---|
| `SourceControlLibrary` → `FileFolder` | **`CapabilityAssetUse`** | "Defines that a server capability is associated with an asset." |
| `FileFolder` → `FileFolder` (subfolder) | **`FolderHierarchy`** | "A nested relationship between two file folders." |
| `FileFolder` → `DataFile` | **`NestedFile`** | "The link between a data file and its containing folder." |

`CapabilityAssetUse` was chosen over `ResourceList` for the first edge — both technically succeeded in
the live test, but `ResourceList` is a generic "supporting resources" link already reused 679 times in
this instance's catalog for unrelated purposes (actor profiles, projects, communities, ...), while
`CapabilityAssetUse` is semantically exact: `SourceControlLibrary` **is** a `SoftwareCapability`, and a
`FileFolder` **is** an `Asset` — "a capability is associated with an asset" is precisely this
relationship. `NestedFolder` (guessed in the original draft) does not exist as a type at all — Egeria's
real name for that edge is `FolderHierarchy`, confirmed by the same live check. Also confirmed live: the
generic-DataFile template GUID hardcoded in `EgeriaFileSystemSurveyor._create_data_file_asset()`
(`ae3067c7-cc72-4a18-88e1-746803c2c86f`) **does not exist on this Egeria instance** (a 404) — template
GUIDs are content-pack/environment-specific, not portable constants; the correct approach (used in the
pre-flight script and carried into Implementation below) is `AutomatedCuration
._async_get_template_guid_for_technology_type("Data File")`, resolved live rather than hardcoded.

**D6 — Cataloging happens in `EgeriaPublisher`, driven by `SubResourceSurveyor`'s finding — not inside
any surveyor.** Surveyors keep the existing clean layering: they read registry tables and return
annotations/findings (pure data, no Egeria calls); `EgeriaPublisher` is the only place that talks to
Egeria. `EgeriaPublisher`, when publishing the `repo_sub_resource_survey` finding, walks its
recommendation list and creates whatever's flagged as worthy (folders before the files inside them, so
each file's `parentGUID` is available by the time it's created).

**D7 — Publish-time, phase-scoped — reuses the existing `steps=` mechanism, new step key only.** The
Profile-phase plan already generalized `PublishRequest`/`POST /{slug}/publish` to accept `steps`. Add
`"repo_sub_resource_survey"` as a new step key (`SubResourceSurveyor`'s own `STEP` value, following the
existing convention every other step key already uses). Publishing that step catalogs whatever the
survey recommended; publishing the full survey (`steps=None`) includes it like every other step. No
separate "also catalog sub-resources" toggle — this is exactly the phase-scoped publish model every
other Assessment/Analysis finding already uses, just for a new kind of finding.

**D8 — Idempotent via qualified_name lookup, exactly like the two existing patterns already do.**
Qualified names: `SourceControlLibrary::{github_url}::{relative_path}` for both folders and files (a
folder and a file can't collide since a real filesystem never has both at the same path). Before
creating, search for an existing asset with that qualified name (same `find_software_capabilities`/
`get_guid_for_name`-style lookup `_find_or_create_asset()` and `EgeriaFileSystemSurveyor
._find_element_guid()` already use) — skip creation if found. No local GUID cache table needed (unlike
the top-level asset) — the recommended set stays small (single-to-low-double-digit assets per repo even
with folders included, per D1's browsable-range heuristic), so a live Egeria lookup on every publish is
cheap, and a local cache would just be one more place these GUIDs could drift from Egeria's own state.

**D9 — Metadata capture is tiered exactly along the cost lines above; staleness is scoped to the worthy
subset, not the full inventory.** `SubResourceSurveyor` (D1) gains two additional, independent
responsibilities beyond worthiness scoring:
- **Tier 1, full-repo, every survey run**: `mode` and `size` (already free per-file from the existing
  git tree call) get added as columns on `project_file_inventory` itself (`file_mode TEXT DEFAULT ''`,
  matching the table's existing nullable-default style) — populated by `StatsFetcher`/whatever already
  calls `get_git_tree()`, not by `SubResourceSurveyor`, since it's free data already flowing through an
  existing call, not a new fetch this surveyor needs to make itself. `SubResourceSurveyor` then reads
  it back out alongside `file_path`/`file_size_bytes` for its own analytics (D10).
- **Tier 1, full-repo, CODEOWNERS**: `SubResourceSurveyor` fetches `CODEOWNERS` once (root → `.github/`
  → `docs/`, GitHub's own lookup order, first hit wins) and pattern-matches it against every inventoried
  path — cheap, whole-repo, no new registry column needed since it's derived at survey time, not stored
  raw (see D12 for where the derived result lands).
- **Tier 2, worthy-subset only**: for each entry the worthiness heuristic already flagged (D1's small,
  bounded list — not the full inventory), `SubResourceSurveyor` calls `repo.get_commits(path=X)` once to
  get the most recent commit's date (`[0].commit.author.date`) as "last updated," and once more with
  pagination to the last page for "first added" (oldest commit touching that path) — both real API calls,
  but bounded by the same single-to-low-double-digit count D1 already established, not by repo size.
  **Explicitly not attempted for the full inventory** — see "Metadata capture" above for why.

**D10 — Size and permission-mode distributions are computed full-repo, every run, and persisted as a
metric snapshot — not part of the findings list.** These are repo-wide aggregate summaries (a histogram,
not per-path detail), which is exactly what the existing `project_analysis_metrics` table (generic,
`kind`-discriminated, from the earlier analysis-kind extensibility redesign) already models — no new
table. `SubResourceSurveyor` calls `upsert_metric(slug, "repo_sub_resource_survey", metric_name=
"size_distribution", metric_value=<total bytes>, detail={"buckets": {...}}, surveyed_at=...)` and again
for `"mode_distribution"` (counts of regular/executable/symlink). Bucket boundaries for size (e.g. <1KB,
1KB-10KB, 10KB-100KB, 100KB-1MB, >1MB) are a first-pass default, not validated against real repos yet —
flagged as tunable, same posture as D1's folder file-count range.

**D11 — Growth over time reuses `project_analysis_metrics`'s existing append-only + `surveyed_at`
shape — the identical pattern `project_file_type_counts`/`query_file_type_history()` already
established.** Every `SubResourceSurveyor` run appends new metric rows (D10) rather than overwriting —
this is already `upsert_metric()`'s behavior for every other `AnalysisKind`, so no new code path, just a
new `kind` value feeding into the generic `query_metrics_history()` reader that already exists. A
repo-size-over-time or file-count-over-time trend chart falls out of re-running this survey periodically
(e.g. via the existing schedule mechanism) with zero new trend-charting infrastructure.

**D12 — Ownership is CODEOWNERS-derived, attached per-entry in the survey's findings list, not a
separate table.** Each finding row (D1's `detail_json`) gains an `owners: list[str]` field — the
CODEOWNERS pattern(s) matching that path, resolved at survey time (D9). This applies to *every*
inventoried path the worthiness heuristic considered (worthy or not — CODEOWNERS matching is free, so
there's no reason to withhold it from the not-worthy entries the finding already lists), giving "who
owns this" for the whole repo's structure, not just the cataloged subset. No repos without a
`CODEOWNERS` file simply get `owners: []` everywhere — not treated as an error.

**"Visibility" — read as repo-level, already covered; not a new per-file signal.** The most direct
reading of "ownership/visibility" as a paired phrase is GitHub's own repo-level `visibility`/`private`
flag — already captured by `StatsFetcher`'s recent "persist the full GitHub attribute set" work
(`project_stats.visibility`/`is_private`) and displayed in Scouting. A *per-file* visibility concept
doesn't map cleanly onto a public (or even private) GitHub repo — every tracked file is equally visible
to anyone with repo access; there's no per-path ACL to surface. If a different meaning was intended
(e.g. "is this file publicly documented/exposed as an API surface" vs. internal-only), that's closer to
`ApiStructureSurveyor`'s deferred file-level-significance territory (see "Explicitly deferred") than a
metadata-capture concern — flagging the ambiguity rather than guessing further.

**D13 — Other dimensions considered, and why each is in/out of this pass:**
- **Orphaned/dead files** (inventoried but never referenced by anything in `project_code_relationships`)
  — genuinely free (RE already has both tables; this is a join, not a new fetch) and a real "worth a
  second look" signal. **In scope, folded into D1's worthiness heuristics** as an additional reason a
  file might be flagged (or, inversely, a reason a large unreferenced folder is *more* interesting to
  flag, not less) — not a separate feature.
- **Churn/edit-frequency hot-spots** (files that change unusually often, not just when they last
  changed) — same Tier 2 cost problem as staleness (needs per-file commit *counts*, not just the latest
  date; `get_commits(path=X)` would need to be paginated to completion to count accurately). **Out of
  scope this pass**, same reasoning as full-repo staleness.
- **License-header consistency per file** — requires reading file *content*, which the survey's own
  stated boundary explicitly excludes ("only file/folder characteristics ... not the contents"). **Out
  of scope**, and arguably belongs to a content-aware surveyor if ever built, not this one.
- **Binary vs. text mix** — derivable for free from the kind/type classification that already exists
  (`FileClassifierSurveyor`'s output already implies binary-vs-text per file via its type mapping). **Not
  a new capture**, just a possible new cross-tab view over data that already exists — worth noting as a
  cheap future addition to the frontend, not backend work.

## Implementation

**Registry** (`resource_explorer/registry.py`): `project_file_inventory` gains `file_mode TEXT DEFAULT
''` (D9, Tier 1) via the existing migration-list pattern (`for col, defn in [...]`) — the only schema
change in this whole plan. No new tables — the survey's worthiness/ownership list uses the existing
generic `project_analysis_findings` (D1/D12); the size/mode distributions and growth trending use the
existing generic `project_analysis_metrics` (D10/D11).

**`resource_explorer/github/client.py` / `stats_fetcher.py`**: whichever already calls `get_git_tree()`
for file inventory also captures `.mode` per entry and writes it into the new `file_mode` column —
mechanical, since the data is already in the response being discarded today.

**New `resource_explorer/surveyors/sub_surveyors/sub_resource_survey.py`**: `SubResourceSurveyor`,
`STEP = "SubResourceSurvey"`. Reads `project_file_inventory` (now including `file_mode`) via the
registry, builds a folder tree in memory by splitting `file_path` on `/`, applies D1's heuristics up to
`max_depth`, fetches and parses `CODEOWNERS` once (D9/D12), fetches Tier-2 commit dates only for the
worthy subset (D9), and persists two things: the recommendation list via `upsert_finding(slug,
"repo_sub_resource_survey", findings, surveyed_at=...)` — each row's `detail_json` carrying `{path,
kind: "file"|"folder", reason, worthy: bool, owners: list[str], last_updated_at?: str,
first_added_at?: str}` (the last two only present for worthy entries, per D9's Tier-2 scoping) — and the
size/mode distribution snapshots via `upsert_metric()` (D10/D11).

**`resource_explorer/surveyors/repo_survey_definition_adapter.py`**: new `AnalysisKind` entry for
`sub_resource_survey` (id/step-key/surveyor registration, following the existing `ANALYSIS_KINDS`
registry pattern from the analysis-kind extensibility redesign — one new entry, not four hand-touched
files).

**`resource_explorer/surveyors/egeria_publisher.py`**: new private method,
`_catalog_sub_resources(self, asset_guid: str, finding: dict) -> None`, called when publishing the
`repo_sub_resource_survey` finding. Processes folder-kind entries first (creating each `FileFolder` via
`create_elem_from_template()` with `parentGUID` = the repo asset and `parentRelationshipTypeName =
"CapabilityAssetUse"` for a folder parented directly to the repo, or `parentGUID` = an already-created
ancestor folder's GUID and `parentRelationshipTypeName = "FolderHierarchy"` for a subfolder — per D5's
confirmed types), then file-kind entries (`parentGUID` = its containing folder's GUID — always some
`FileFolder`, per D4's revised rule — and `parentRelationshipTypeName = "NestedFile"`). Each creation is
qualified-name-guarded per D8, and each created asset's properties include whatever D9 metadata that
entry carries (owners, last-updated, mode) as `additionalProperties` — the catalog gets the richer
metadata too, not just RE's own local findings view.

## Verification

- **Pre-flight — done, 2026-08-11 (per D5).** Throwaway `create_elem_from_template` calls run against
  the real `qs-metadata-store`/`qs-view-server` Egeria instance (using `sqlglot`'s live
  `SourceControlLibrary` asset as the parent), covering all three parent-child edge shapes, then cleaned
  up (`MetadataExpert.delete_metadata_element()`, verified via a follow-up search returning no residual
  elements). Confirmed relationship types recorded in D5. No code written against these types yet — that
  starts now.
- Unit tests: `SubResourceSurveyor` — heuristic correctness for each rule in D1 (well-known filenames at
  various depths, folder file-count boundary cases at 1/2/200/201, `max_depth` cutoff), and that the
  finding's `detail_json` includes both worthy and not-worthy entries with reasons. `EgeriaPublisher
  ._catalog_sub_resources()` — mocked `AutomatedCuration`: folders created before their contained files,
  correct `parentGUID` resolution (repo vs. an ancestor folder created this same pass vs. a
  previously-existing one found via lookup), skip-if-already-found idempotency, correct
  `parentRelationshipTypeName` per edge shape.
- Unit tests (D9-D12): `CODEOWNERS` parsing/pattern-matching against a representative set of paths
  (including the "no CODEOWNERS file" case → `owners: []` everywhere, not an error); Tier-2 commit-date
  fetching called only for worthy entries (mock-assert call count equals the worthy-set size, not the
  full inventory size — the actual cost-boundary regression guard); size/mode distribution bucketing
  (`upsert_metric()` calls, correct bucket assignment at boundary values); `file_mode` correctly captured
  and threaded through from the existing `get_git_tree()` call into `project_file_inventory`.
- Live: run `SubResourceSurveyor` against a real repo, confirm its finding's recommendation list looks
  sane by eye (not too broad, not empty) before ever publishing anything, and confirm `owners`/`file_mode`
  are populated correctly for a repo that has a real `CODEOWNERS` file. Publish
  `steps=["repo_sub_resource_survey"]`, confirm the recommended folders/files appear as real, correctly
  nested Egeria assets (browsable via The Catalog, not just present in a raw search) — spot-check that a
  file inside a recommended folder is parented to *that folder's* GUID, not flattened to the repo root,
  and that its Egeria `additionalProperties` carry the D9 metadata. Re-publish the same step and confirm
  no duplicates (D8). Publish a full survey (`steps=None`) and confirm sub-resource cataloging runs
  alongside every other step without disrupting them. Re-run the survey a second time (no repo changes)
  and confirm `project_analysis_metrics` gained a second, distinct `surveyed_at` row per D11 (the growth-
  over-time regression check) rather than overwriting the first.
- Full RE test suite green.

## Explicitly deferred (destination on record, not designed here)

- `ApiStructureSurveyor`-driven cataloging (e.g. "the file with the most exported symbols") — it
  currently aggregates by language, not by file, so it has no existing per-file significance signal;
  `SubResourceSurveyor`'s own heuristics (D1) don't cover code-complexity-driven worthiness either.
  Revisit once/if `ApiStructureSurveyor` gains file-level scoring, as its own contribution to the
  worthiness recommendation list rather than a separate cataloging path.
- Tuning the D1 heuristics themselves (the 2–200 folder file-count range, the well-known-filename list,
  `max_depth`'s default of 2) against real, varied repos — first-pass defaults, expected to move after
  live use, same as `HealthSurveyor`'s scoring weights did. Same posture applies to D10's size-bucket
  boundaries.
- **Full-repo staleness/age distribution** (every file's real last-modified date, not just the worthy
  subset) — needs either a real `git clone` with history (architecture change) or GitHub GraphQL query
  batching (new client infrastructure RE doesn't have today). Named explicitly in "Metadata capture"
  above so the cost tradeoff is on record, not designed here.
- **Churn/edit-frequency hot-spots** and **license-header consistency** (D13) — same Tier-2 cost problem
  and content-boundary problem respectively; not designed here.
- `ApiStructureSurveyor`-driven cataloging (e.g. "the file with the most exported symbols") — it
  currently aggregates by language, not by file, so it has no existing per-file significance signal;
  `SubResourceSurveyor`'s own heuristics (D1) don't cover code-complexity-driven worthiness either.
  Revisit once/if `ApiStructureSurveyor` gains file-level scoring, as its own contribution to the
  worthiness recommendation list rather than a separate cataloging path.
- Analysis/Enrichment's own publish scoping beyond what already exists — out of scope for this doc,
  named in `repo-phase-visibility-model.md` as a separate future item.
