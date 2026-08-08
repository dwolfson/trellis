# Filesystem Local Survey — Analytics Plan

**Status:** Design agreed (2026-07-13). §4 items 1-3, 5, 6 implemented (2026-07-13) — Technology Type string fixed, `classify_file_paths()` extracted and generalized, `LocalFileSystemSurveyor` split into a structure phase + profiling phase (kept as **one** Survey Definition step per 2026-07-13 follow-up direction — see the note in §3 below), `publish_step_annotations` rebuilt to emit the full Egeria-parity annotation set, `IGNORE_DIRS` tightened. §4 item 4 (register as a separate `re_analysis_steps` entry) superseded by that same one-step decision. Not yet done: within-step progress streaming (§5), and the new RFAs are still purely descriptive annotations, not real assignable Egeria actions — see the new "RFAs should become real Egeria actions" backlog item.
**Motivating problems:** (1) `docs/Backlog.md` "HIGH — Filesystem local survey hangs" — one monolithic blocking call with no progress feedback and errors visible only in the server console; (2) no comparable-content parity with what Egeria's own native filesystem survey produces, and no Survey Definition step granularity to speak of.
**Companion docs:** `docs/survey-definitions.md` (how `re_analysis_steps` are declared/dispatched), `docs/egeria-collaboration-and-survey-model.md` §6.1 (analysis-step inventory/registration — the longer-term "make this catalogable" item this plan is a concrete instance of).

---

## 1. What Egeria's native survey actually produces

Confirmed live against a running Egeria server (2026-07-13), via `EgeriaTechTypeCatalog.get_tech_type_detail("File System Directory")`:

- The real Technology Type is **`File System Directory`** (`deployedImplementationType-(File System Directory)`, `FileFolder` open-metadata type) — not `"File Folder"`, which is what `resource_explorer/surveyors/filesystem/survey_definition_adapter.py`'s `_ADAPTER.technology_type` currently guesses. **Action: fix this string** (see §4).
- Its survey process is `FileDirectory:CreateAndSurveyGovernanceActionProcess` (`FileDirectory:CreateAndSurvey`). **It is a single `GovernanceActionProcess` with one analysis step** ("Profiling Associated Resources") — Egeria does not decompose filesystem surveying into multiple chained steps the way a database survey might. This matters: there is no Egeria-side step granularity to mirror. Any decision to split RE's local survey into multiple `re_analysis_steps` should be justified on RE's own cost/architecture grounds, not on parity with Egeria.
- That one step produces **8 annotation types**, all under `analysisStepName: "Profiling Associated Resources"`:

| # | Egeria annotation | Type | What it captures |
|---|---|---|---|
| 1 | Capture File Counts | `ResourceMeasureAnnotation` | file/subdir counts, total size, hidden/symlink/executable/writable counts, inaccessible-file count, unique extension/filename counts, aggregate access/creation/modification timestamps, asset-type/deployed-implementation-type/file-type counts |
| 2 | Profile Deployed Implementation Types | `ResourceProfileAnnotation` | histogram: count per `deployedImplementationType` |
| 3 | Profile Asset Types | `ResourceProfileAnnotation` | histogram: count per potential Egeria asset type |
| 4 | Profile File Types | `ResourceProfileAnnotation` | histogram: count per `fileType` |
| 5 | Profile File Extensions | `ResourceProfileAnnotation` | histogram: count per raw extension |
| 6 | Missing File Reference Data | `RequestForAction` | files that couldn't be classified against Egeria's file reference data |
| 7 | Inaccessible files | `RequestForAction` | files whose basic attributes couldn't even be retrieved |
| 8 | Profile File Names to External Log | `ResourceProfileLogAnnotation` | full per-filename histogram — written to an external log, not an inline annotation, because it can be large |

## 2. Where RE stands today, gap by gap

`resource_explorer/surveyors/filesystem/local_filesystem_surveyor.py` (`LocalFileSystemSurveyor.run()`) currently produces: `total_files`, `total_data_files`, `total_size_bytes`, a `formats` histogram (by RE's own format label, not raw extension or Egeria's taxonomy), and per-data-file schema profiles (rows/cols/dtypes/nulls) via `DataProfilerSurveyor`.

| Egeria annotation | RE today | Gap |
|---|---|---|
| Capture File Counts | partial (files/data-files/size only) | missing hidden/symlink/executable/writable/inaccessible counts, timestamps, unique extension/filename counts |
| Profile Deployed Implementation Types / Asset Types / File Types | ❌ | not computed at all for filesystems |
| Profile File Extensions | 🟡 | have a `formats` histogram, but keyed by RE's own label, not raw extension or Egeria's `fileType`/`deployedImplementationType` |
| Missing File Reference Data (RFA) | ❌ | unclassified files aren't tracked as a distinct category |
| Inaccessible files (RFA) | ❌ | `_walk_directory`'s `PermissionError` is `log.warning`'d and dropped — never reaches the survey result, the activity log, or the user (this is the same failure pattern that made the last run look like a "hang": real problems, silently swallowed) |
| Profile File Names to External Log | ❌ (not needed inline; see §3) | — |
| *(no Egeria equivalent)* Per-file schema profiling (rows/cols/dtypes/nulls) | ✅ | **RE already exceeds Egeria's native survey here** — keep this, it's a real value-add, not scope to cut for parity |

`FileClassifierSurveyor` (`resource_explorer/surveyors/file_classifier/file_classifier_surveyor.py`) already does almost exactly what annotations #2–5 need — it classifies files by `(deployedImplementationType, fileType, assetTypeName)` using a cache backed by Egeria's own `ValidMetadataValues` reference data (`type_cache.py`), and produces a `ClassificationAnnotation` per group plus a `ResourceMeasureAnnotation` extension breakdown. Today it's repo-only: `_collect_file_paths()` reads `project_code_symbols`/`project_file_inventory` (repo-specific registry tables). It does not depend on GitHub data or anything else repo-specific beyond that one method.

## 3. Step design: two steps, drawn at the cost boundary, not the annotation boundary

Per direction agreed 2026-07-13: don't fragment into one step per annotation type. If you're already asking the OS for a file's `stat()` info, get everything that call offers in the same pass rather than walking the tree again per annotation. The real, meaningful boundary is **cost**: a cheap metadata-only pass (one `stat()` + one extension lookup per file) vs. an expensive content-reading pass (opening and parsing every data file's bytes). That boundary also happens to be exactly where the "hang" came from — the second, expensive pass is where the CSV/xls parsing errors and multi-minute runtimes lived — so it's a natural place for a real step split regardless of Egeria parity.

### Step 1 — `filesystem_structure` (replaces today's monolithic pass, metadata-only)

One walk, one `stat()` per file. For each file: size, hidden/symlink/executable/writable flags, access/creation/modification times, extension — plus the same Egeria-reference-data classification `FileClassifierSurveyor` already does. Produces, in one pass:

- `ResourceMeasureAnnotation` — the full counts annotation (files, subdirs, size, hidden/symlink/executable/writable counts, inaccessible count, unique extension/filename counts, min/max timestamps) — matches Egeria annotation #1.
- `ClassificationAnnotation` × N, one per `(deployedImplementationType, fileType)` group, reusing `FileClassifierSurveyor`'s existing grouping logic — covers Egeria annotations #2–4 in one shot (they're all groupings of the same classification pass, not separate work).
- `ResourceMeasureAnnotation` — extension breakdown (raw extensions, not RE's `formats` label) — matches Egeria annotation #5.
- `RequestForActionAnnotation` — unclassified files (files with no `deployedImplementationType`/`fileType`/`assetTypeName` match) — matches Egeria annotation #6.
- `RequestForActionAnnotation` — inaccessible files (currently-swallowed `PermissionError`s during `_walk_directory`, plus any `stat()` failures) — matches Egeria annotation #7. **This directly fixes the silent-failure half of the "hang" bug** — these now show up in the survey result and activity log instead of only the server console.

No file-content reads in this step — it should stay fast even over a large/noisy tree, which also gives the frontend something to show quickly instead of waiting on the full profiling pass.

### Step 2 — `filesystem_data_profiling` (existing `DataProfilerSurveyor` pass, unchanged in kind)

Reads and parses each classified data file's contents (`pandas`/`pyarrow`) to profile schema — this is the expensive, failure-prone part (malformed CSVs, missing `xlrd`, huge files). Already exists; the main change needed is collecting per-file failures into a `RequestForActionAnnotation` summary instead of only `log.warning`, so profiling errors are visible to the user (not just the server console) without being a wall of individual toasts.

No Egeria-native equivalent exists for this step — it's pure RE value-add, kept as-is.

Both steps register independently in `resource_explorer/surveyors/filesystem/survey_definition_adapter.py`'s `re_analysis_steps` dict, the same pattern repo's adapter already uses — a Survey Definition author can chain both, or reference either alone (e.g. a fast "structure only" scouting pass vs. a deeper assessment pass that adds profiling).

## 4. Concrete implementation steps

1. **Fix the Technology Type string.** `filesystem/survey_definition_adapter.py`: `technology_type="File Folder"` → `"File System Directory"`. This is likely *why* no Survey Definition candidates show up for filesystems today — if anyone authors a Survey Definition tagged `supported_technology_type: File System Directory` (the real value), RE's candidate lookup wouldn't have matched it against the old guessed string. Also update `egeria_technology_type_name` (used for the `EgeriaTechTypeCatalog.get_produced_annotation_types` call in `survey_definitions.py`) to the confirmed real name so the "native processes"/"produced annotation types" info shown to the user is accurate instead of silently empty.
2. **Generalize `FileClassifierSurveyor`'s file-path source.** Extract `_collect_file_paths()`'s registry-table dependency behind a small seam (e.g. accept an optional `file_paths: list[str]` override, or split into `_collect_file_paths()` for repos + a shared classification core both callers use) so a plain path list — which the filesystem walk already has in hand — can drive the same classification logic without a repo-shaped registry underneath it.
3. **Rewrite `LocalFileSystemSurveyor` into the two-step shape above.** Single walk producing the richer per-file metadata (`os.stat()` fields, extension, classification) in step 1; existing `DataProfilerSurveyor` call as step 2, now collecting failures into a `RequestForActionAnnotation` instead of dropping them into `log.warning`.
4. **Update `filesystem/survey_definition_adapter.py`** to register both `filesystem_structure` and `filesystem_data_profiling` as separate `re_analysis_steps` entries (mirroring repo's `_build_re_analysis_steps()` pattern), each with its own `re_analysis_step_info` description/annotation-types for the candidates UI.
5. **Update `EgeriaFileSystemSurveyor.publish_step_annotations`** to build the new annotation set (`ResourceMeasureAnnotation` counts + classification + extension breakdown + the two RFAs from step 1, `SchemaAnalysisAnnotation` per profiled file from step 2 — already implemented) instead of today's single flat `ResourceMeasureAnnotation` + `SchemaAnalysisAnnotation` pair built directly from the old `survey_data` shape.
6. **Tighten `IGNORE_DIRS`** while touching this code anyway (bare `venv`, not just `.venv` — the concrete cause of the multi-minute scan across dozens of stray venvs in the original bug report) — same file, same change, no reason to defer it to a separate pass.

## 5. What this does and doesn't fix

**Fixes:** silent inaccessible/unclassified-file failures (now surfaced as RFAs), missing content-parity with Egeria's native survey (counts, classification, extension histograms), the wrong Technology Type string blocking Survey Definition discovery, and — incidentally, since step 1 is now a fast metadata-only pass — most of the "feels like a hang" experience, since the expensive part is now a separable, individually-observable step.

**Does not fix:** true progress streaming within a single step (step 2 profiling a very large tree is still one blocking call from the browser's perspective, just a smaller and better-bounded one than before) — that's still the "HIGH — Filesystem local survey hangs" backlog item's remaining scope if step 2 alone still proves too slow in practice. Also does not address the broader "Analysis-step inventory and registration" backlog item (making `re_analysis_steps` itself a catalogable Egeria registry rather than a hardcoded Python dict) — this plan adds two well-scoped entries to that same hardcoded dict, it doesn't change the dict's nature.
