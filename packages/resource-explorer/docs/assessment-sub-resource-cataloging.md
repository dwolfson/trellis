# Assessment sub-resource cataloging — design pass

**Status: design only, not built.** Flagged as roadmap-only in `docs/repo-phase-visibility-model.md`'s
visibility-source matrix ("optionally catalog specific sub-resources (folders/files) as child assets —
not built, roadmap only"). This is that design pass, grounded in a direct read of `EgeriaPublisher`,
the three Assessment sub-surveyors, `project_file_inventory`'s schema, and pyegeria's actual asset-
creation APIs — not assumptions.

## Context

Assessment's job (per `repo-phase-visibility-model.md`) is "existing tables only, deeper analytics —
no new fetch": `SecurityHygieneSurveyor`, `DocumentationSurveyor`, and `ApiStructureSurveyor` all read
already-persisted data (`project_code_symbols`, `project_stats`, `project_code_relationships`) and
publish repo-scoped findings/metrics annotations. None of them produce per-file or per-folder Egeria
elements — `file_path` values are read for matching/grouping but never surfaced individually. That's
the gap this plan closes: a small number of *specific, individually-significant* files (not "every
file in the repo") get cataloged as their own child Egeria assets, so someone browsing the catalog can
land directly on "the SECURITY.md this repo does/doesn't have," not just a repo-level yes/no finding.

**What this explicitly is NOT**: a full filesystem-mirror of every repo file into Egeria. Grounded in
`project_file_inventory`'s real schema (`project_slug, file_path, file_size_bytes, indexed_at` — a flat
per-file row, no folder-node table), a repo can carry thousands of file rows; creating one Egeria asset
per row is both the wrong information architecture (nobody wants to browse a repo's `node_modules` as
1,200 individual Egeria assets) and prohibitively expensive (each `create_elem_from_template` call is a
real network round-trip to Egeria, and there's no bulk/batch variant in the APIs this codebase uses).

## Grounding (confirmed via direct code/API inspection, 2026-08-10)

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
  same-`fileSystemName` naming convention. This plan should not silently inherit that gap (see D3).
- **`EgeriaDatabaseSurveyor` is not a usable precedent** — it never creates per-schema/per-table assets
  itself; it triggers Egeria's own native async Postgres survey engine to do that server-side. Repos
  have no equivalent native engine, so RE's own code has to do the creation here.
- **pyegeria has no repo-file-specific convenience method.** `AutomatedCuration
  .create_folder_element_from_template()` is filesystem-shaped (`file_system` param) and DataFile
  templates are picked by format (CSV/Parquet/Excel/generic) — neither maps cleanly onto "a source file
  in a git repo." `CollectionManager.create_folder_collection()` + `.add_to_collection()`
  (`CollectionMembershipProperties` relationship) is a real alternative: model sub-resources as
  Collection members instead of nested Asset elements. Decision D2 below picks between these.

## Key decisions

**D1 — Selection is finding-driven, not a blanket file-inventory walk.** Only files a sub-surveyor's
own existing analysis already singled out as individually meaningful get cataloged — the annotation
that names the file *is* the trigger, not a separate `project_file_inventory` scan. Per surveyor:
- `SecurityHygieneSurveyor`: the specific hygiene files it already checks for by name (SECURITY.md,
  CI config file, LICENSE) — when found present, catalog that exact file. Typically 0-3 files/repo.
- `DocumentationSurveyor`: the hygiene/doc files it already identifies (README, CHANGELOG, docs/ index)
  — typically 1-5 files/repo.
- `ApiStructureSurveyor`: **deferred, not in this pass.** It currently aggregates by *language*, not
  by file, and has no existing "this file matters more than that one" signal (complexity is tracked
  per-symbol, not rolled up per-file) — inventing a threshold (top-N by symbol count?) would be a new,
  unvalidated heuristic rather than surfacing something the surveyor already decided. Revisit once/if
  `ApiStructureSurveyor` itself gains file-level significance scoring.

This keeps the count small (single digits per repo, not hundreds) and ties every cataloged asset back
to a concrete "why this file" reason a human can see in the annotation that produced it.

**D2 — Model as DataFile Asset elements (matching the filesystem precedent), not Collection
membership.** Consistency with `EgeriaFileSystemSurveyor` matters more here than the two approaches'
minor capability differences — a catalog user browsing "files across all resource types" shouldn't hit
two different element shapes (Asset vs. Collection-member) depending on whether the parent happens to
be a repo or a filesystem mount. `CollectionManager`'s model stays the right choice for genuinely
organizational groupings (it's already used that way elsewhere in pyegeria); this is asset cataloging,
not grouping.

**D3 — Fix the parent-linkage gap; do not repeat it.** Every cataloged file asset gets a real
`parentGUID` (the repo's own `SourceControlLibrary` asset GUID, already cached via
`registry.get_egeria_asset_guid()`) and `parentRelationshipTypeName` set in the `create_elem_from_template`
body — not just a shared `fileSystemName`-style naming convention. **Unverified, needs a live check
before implementation**: this design assumes `NestedFile` (or equivalent) is a real Egeria open-metadata
relationship type valid between `SourceControlLibrary` and a file-shaped asset — that name was inferred
by analogy to `NestedFolder`/`NestedFile`'s existence elsewhere in Egeria's metadata model, not
confirmed by reading actual type definitions or a working call. **First implementation step must be a
throwaway `create_elem_from_template` call against a real Egeria instance to confirm the relationship
type name and required properties**, mirroring how other plans in this repo (e.g. the AST-ownership
plan) front-loaded a pre-flight verification phase before writing real code against an unconfirmed API
shape.

**D4 — No intermediate Folder asset layer.** Because D1 keeps the cataloged set sparse (a handful of
files, not a directory tree), each file asset hangs directly off the repo's `SourceControlLibrary`
asset with a `relativePath` property (e.g. `docs/SECURITY.md`) rather than building and maintaining a
parallel Folder-node graph for what might be 2-3 files total. If a future pass wants comprehensive
per-folder structure (not just flagged files), that's a materially bigger feature — worth its own
design, not bolted onto this one.

**D5 — Cataloging happens in `EgeriaPublisher`, not inside the sub-surveyors.** Surveyors currently
have a clean, enforced layering: they read registry tables and return annotations (pure data, no Egeria
calls) — `EgeriaPublisher` is the only place that talks to Egeria. Sub-resource cataloging must respect
that boundary rather than reaching into `AssetMaker`/`AutomatedCuration` from inside a surveyor. Concretely:
`SecurityHygieneSurveyor`/`DocumentationSurveyor` each gain a small, additive `flagged_files: list[dict]`
field in their existing finding's `detail_json` (e.g. `{"file_path": "SECURITY.md", "role": "security_policy"}`)
— no new table, no schema change to `project_analysis_findings` (the `detail_json` column already exists
and is exactly for this kind of extra structured payload). `EgeriaPublisher`, when publishing a finding
that carries `flagged_files`, calls the new cataloging step per file after the finding's own annotation
is created.

**D6 — Publish-time, phase-scoped — reuses the existing `steps=` mechanism, no new publish flag.**
The Profile-phase plan already generalized `PublishRequest`/`POST /{slug}/publish` to accept `steps`,
producing a scoped `SurveyResult`/publish for just those steps. Sub-resource cataloging rides the same
mechanism with zero new API surface: publishing `steps=["repo_security"]` catalogs whatever files that
step's finding flagged; publishing the full survey (`steps=None`) catalogs everything every step flagged.
No separate "also catalog sub-resources" toggle — if a finding flagged a file, publishing that finding
always catalogs it, matching this codebase's existing "publish is deliberate but not partial" convention
(nothing here introduces a second layer of publish granularity).

**D7 — Idempotent via qualified_name lookup, exactly like the two existing patterns already do.**
Qualified name: `SourceControlLibrary::{github_url}::{relative_path}`. Before creating, search for an
existing asset with that qualified name (same `find_software_capabilities`/`get_guid_for_name`-style
lookup `_find_or_create_asset()` and `EgeriaFileSystemSurveyor._find_element_guid()` already use) — skip
creation if found, matching the top-level asset's own idempotency behavior. No local cache table needed
for the GUIDs (unlike the top-level asset, which caches via `registry.get_egeria_asset_guid()`) — the
per-file set is small enough that a live Egeria lookup on every publish is cheap, and a local cache would
just be one more place these GUIDs could drift from Egeria's own state.

## Implementation

**`resource_explorer/surveyors/sub_surveyors/security_hygiene.py` / `documentation.py`**: each finding's
existing `detail_json`-producing dict gains a `flagged_files` key (list of `{file_path, role}`) alongside
whatever it already returns — additive, no change to the finding's existing summary/status/confidence
fields or to `upsert_finding()`'s signature.

**`resource_explorer/surveyors/egeria_publisher.py`**: new private method, e.g.
`_catalog_flagged_files(self, asset_guid: str, finding: dict) -> None`, called from wherever findings for
a published step get turned into annotations. For each `flagged_files` entry: build the qualified name,
look up an existing GUID, and if absent call `create_elem_from_template()` with `parentGUID=asset_guid`,
`parentRelationshipTypeName=<confirmed via D3's pre-flight check>`, and placeholder properties
(`fileName`, `filePathName` = relative path, `description` = the flagged role, e.g. "Security policy file").

**No registry schema changes** — `detail_json` on the existing `project_analysis_findings` table already
covers `flagged_files`; no new table, no migration.

## Verification

- **Pre-flight (must happen before any other implementation work, per D3)**: one throwaway
  `create_elem_from_template` call against a real Egeria instance, linking a test DataFile-shaped asset
  under an existing `SourceControlLibrary` test asset, to confirm the real relationship-type name and
  required `placeholderPropertyValues` — write down what's confirmed before writing the real
  `_catalog_flagged_files()` body.
- Unit tests: `SecurityHygieneSurveyor`/`DocumentationSurveyor` — `flagged_files` populated correctly
  for the present/absent cases of each hygiene file (regression guard against their existing
  finding-building tests, additive only). `EgeriaPublisher._catalog_flagged_files()` — mocked
  `AutomatedCuration`: creates when absent, skips when the qualified name is already found, correct
  `parentGUID`/`parentRelationshipTypeName` in the request body.
- Live: publish `steps=["repo_security"]` for a real repo that has a SECURITY.md, confirm exactly one
  new file-scoped asset appears in Egeria's catalog, correctly linked under the repo's own
  `SourceControlLibrary` asset (browsable via The Catalog, not just present in a raw search). Re-publish
  the same step and confirm no duplicate asset is created (D7's idempotency). Publish a full survey
  (`steps=None`) for a repo with both SECURITY.md and a README and confirm both get cataloged.
- Full RE test suite green.

## Explicitly deferred (destination on record, not designed here)

- `ApiStructureSurveyor` file-level cataloging (needs its own file-significance heuristic first — D1).
- Folder-level (not just flagged-file) cataloging — a materially bigger feature (D4).
- Analysis/Enrichment's own publish scoping beyond what already exists — out of scope for this doc,
  named in `repo-phase-visibility-model.md` as a separate future item.
