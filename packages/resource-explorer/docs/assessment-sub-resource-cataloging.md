# Assessment sub-resource cataloging — design pass

**Status: design only, not built.** Flagged as roadmap-only in `docs/repo-phase-visibility-model.md`'s
visibility-source matrix ("optionally catalog specific sub-resources (folders/files) as child assets —
not built, roadmap only"). This is that design pass, grounded in a direct read of `EgeriaPublisher`,
the three Assessment sub-surveyors, `project_file_inventory`'s schema, and pyegeria's actual asset-
creation APIs — not assumptions.

**Revised 2026-08-11** to separate *survey* from *catalog* as two distinct steps, rather than treating
"a sub-surveyor's finding mentions a file" as the trigger for creating it as an asset. See "Survey vs.
catalog" below — this is the central architectural correction from the original pass.

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

**D2 — `SecurityHygieneSurveyor`/`DocumentationSurveyor` stay exactly as they are — decoupled from
cataloging.** The original draft had them each emit a `flagged_files` list feeding cataloging directly;
that's removed. Those two surveyors keep doing exactly what they do today (repo-scoped presence/quality
findings) with zero changes. `SubResourceSurveyor`'s well-known-file heuristic (D1) will independently
reach the same files (SECURITY.md, README, etc.) for its own reason (structural significance, not
"security policy" or "doc quality") — the two surveyors' findings can agree in practice without being
architecturally coupled. This avoids a cross-surveyor dependency (one surveyor's output shape driving
another's behavior) that the original draft would have introduced.

**D3 — Model as DataFile *and* DataFolder Asset elements (matching the filesystem precedent), not
Collection membership.** Consistency with `EgeriaFileSystemSurveyor` matters more here than the two
approaches' minor capability differences — a catalog user browsing "files/folders across all resource
types" shouldn't hit two different element shapes depending on whether the parent happens to be a repo
or a filesystem mount. `AutomatedCuration.create_folder_element_from_template()` (proven, already used
by `EgeriaFileSystemSurveyor`) creates the folder assets; the existing format-specific DataFile template
selection creates the file assets. `CollectionManager`'s model stays the right choice for genuinely
organizational groupings elsewhere in this codebase; this is asset cataloging, not grouping.

**D4 — Folders can now be cataloged too, not just files** (reverses the original draft's D4 "no
intermediate Folder asset layer" — that constraint existed only because the original design's selection
was file-only and incidental; a real survey step with a folder-worthiness heuristic (D1) makes folder
assets a first-class, deliberate output, matching Egeria's own `survey-folders`/`survey-all-folders`
variants treating folders as surveyable in their own right). A worthy folder becomes a `DataFolder`
asset parented to the repo's `SourceControlLibrary`; a worthy file inside a worthy folder is parented to
*that* folder asset (real nesting), not flattened directly under the repo root. A worthy file whose
containing folder was *not* itself flagged worthy (e.g. a lone `SECURITY.md` at repo root, `max_depth`
1) is parented directly to the repo asset — matching D1's well-known-file rule, which doesn't require
its containing folder to also pass the folder heuristic.

**D5 — Fix the parent-linkage gap; do not repeat it.** Every cataloged asset (file or folder) gets a
real `parentGUID` and `parentRelationshipTypeName` set in the `create_elem_from_template` body — not
just a naming convention. **Unverified, needs a live check before implementation**: this design assumes
`NestedFile`/`NestedFolder` (or equivalent) are real Egeria open-metadata relationship types valid
between `SourceControlLibrary`→`DataFolder`, `DataFolder`→`DataFolder`, and `DataFolder`/
`SourceControlLibrary`→`DataFile` — those names were inferred by analogy to Egeria's own naming
conventions elsewhere, not confirmed by reading actual type definitions or a working call. **First
implementation step must be a throwaway `create_elem_from_template` call against a real Egeria instance
to confirm the relationship type name(s) and required properties for each of those three edge shapes**,
mirroring how other plans in this repo (e.g. the AST-ownership plan) front-loaded a pre-flight
verification phase before writing real code against an unconfirmed API shape.

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

## Implementation

**New `resource_explorer/surveyors/sub_surveyors/sub_resource_survey.py`**: `SubResourceSurveyor`,
`STEP = "SubResourceSurvey"`. Reads `project_file_inventory` via the registry, builds a folder tree in
memory by splitting `file_path` on `/`, applies D1's heuristics up to `max_depth`, and persists the
recommendation list via `upsert_finding(slug, "repo_sub_resource_survey", findings, surveyed_at=...)`
where each finding row's `detail_json` carries `{path, kind: "file"|"folder", reason, worthy: bool}` —
including the *not*-worthy entries too (so the finding can report "considered N, recommended M", not
just the winners).

**`resource_explorer/surveyors/repo_survey_definition_adapter.py`**: new `AnalysisKind` entry for
`sub_resource_survey` (id/step-key/surveyor registration, following the existing `ANALYSIS_KINDS`
registry pattern from the analysis-kind extensibility redesign — one new entry, not four hand-touched
files).

**`resource_explorer/surveyors/egeria_publisher.py`**: new private method,
`_catalog_sub_resources(self, asset_guid: str, finding: dict) -> None`, called when publishing the
`repo_sub_resource_survey` finding. Processes folder-kind entries first (creating each `DataFolder`,
`parentGUID` = the repo asset or an already-created ancestor folder's GUID), then file-kind entries
(`parentGUID` = its containing folder's GUID if that folder was itself created this pass, else the repo
asset GUID directly per D4). Each creation is qualified-name-guarded per D8.

**No registry schema changes** — the existing generic `project_analysis_findings` table (with its
`detail_json` column) covers the survey's recommendation list; no new table, no migration.

## Verification

- **Pre-flight (must happen before any other implementation work, per D5)**: throwaway
  `create_elem_from_template` calls against a real Egeria instance covering all three parent-child edge
  shapes (repo→folder, folder→folder, folder-or-repo→file), to confirm the real relationship-type
  name(s) and required `placeholderPropertyValues` for each — write down what's confirmed before writing
  the real `_catalog_sub_resources()` body.
- Unit tests: `SubResourceSurveyor` — heuristic correctness for each rule in D1 (well-known filenames at
  various depths, folder file-count boundary cases at 1/2/200/201, `max_depth` cutoff), and that the
  finding's `detail_json` includes both worthy and not-worthy entries with reasons. `EgeriaPublisher
  ._catalog_sub_resources()` — mocked `AutomatedCuration`: folders created before their contained files,
  correct `parentGUID` resolution (repo vs. an ancestor folder created this same pass vs. a
  previously-existing one found via lookup), skip-if-already-found idempotency, correct
  `parentRelationshipTypeName` per edge shape.
- Live: run `SubResourceSurveyor` against a real repo, confirm its finding's recommendation list looks
  sane by eye (not too broad, not empty) before ever publishing anything. Publish
  `steps=["repo_sub_resource_survey"]`, confirm the recommended folders/files appear as real, correctly
  nested Egeria assets (browsable via The Catalog, not just present in a raw search) — spot-check that a
  file inside a recommended folder is parented to *that folder's* GUID, not flattened to the repo root.
  Re-publish the same step and confirm no duplicates (D8). Publish a full survey (`steps=None`) and
  confirm sub-resource cataloging runs alongside every other step without disrupting them.
- Full RE test suite green.

## Explicitly deferred (destination on record, not designed here)

- `ApiStructureSurveyor`-driven cataloging (e.g. "the file with the most exported symbols") — it
  currently aggregates by language, not by file, so it has no existing per-file significance signal;
  `SubResourceSurveyor`'s own heuristics (D1) don't cover code-complexity-driven worthiness either.
  Revisit once/if `ApiStructureSurveyor` gains file-level scoring, as its own contribution to the
  worthiness recommendation list rather than a separate cataloging path.
- Tuning the D1 heuristics themselves (the 2–200 folder file-count range, the well-known-filename list,
  `max_depth`'s default of 2) against real, varied repos — first-pass defaults, expected to move after
  live use, same as `HealthSurveyor`'s scoring weights did.
- Analysis/Enrichment's own publish scoping beyond what already exists — out of scope for this doc,
  named in `repo-phase-visibility-model.md` as a separate future item.
