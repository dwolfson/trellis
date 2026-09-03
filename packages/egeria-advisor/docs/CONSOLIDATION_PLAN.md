# Egeria Advisor documentation — consolidation plan

**Status: COMPLETE (2026-09-03).** `history/` cleared and all seven `design/`
clusters resolved — five merged, cluster 6 reviewed and **deliberately not
merged**, cluster 7 folded into the existing `BACKLOG.md` rather than becoming a
new document. `design/` went from **32 files to 14**.

Two clusters were *not* consolidations, and that is the useful result: a plan
that assumed seven merges got five. See clusters 6 and 7 below for why.
**Written:** 2026-09-02, after consolidating Resource Explorer's documentation
from 92 top-level documents to 35 across seven clusters.

---

## Why this is a plan and not a completed pass

The same work was done on Resource Explorer this session, and it went well because
that session had spent two days inside RE's code — enough to tell a superseded
plan from a live one, and to recognise when a document's own claim about itself
was wrong. **That context does not exist for Egeria Advisor.**

Consolidation deletes files. The check that makes it safe is not mechanical: it is
knowing whether a decision recorded in one document is still true, already in the
code, or quietly reversed somewhere else. Doing that from filenames alone would
produce a tidier directory and a less trustworthy one.

So this is the inventory and the proposed grouping, for review.

## What is already right here

**EA's documentation is better organised than RE's was.** It has real
subdirectories — `design/`, `user-docs/`, `history/`, `future/`, `archive/` —
where RE had 92 files in one flat directory. The separation of *history* from
*design* in particular is the distinction RE had to reconstruct by reading status
lines.

| directory | files | words | assessment |
|---|---|---|---|
| `design/` | 32 | 43,223 | the real consolidation target |
| `user-docs/` | 25 | 32,524 | guides; likely fine, may have overlap |
| ~~`history/`~~ | ~~31~~ | ~~37,050~~ | **done 2026-09-03** — was gitignored, never in the repo; 5 rescued, 26 archived |
| `archive/` | 18 | 19,294 | already archived; check nothing live is buried |
| `future/` | 2 | 2,269 | leave alone |
| top level | 2 | 26,536 | `PROJECT_SUMMARY.md` (18,757) is the entry point |

## Proposed clusters — `design/`, 32 files into roughly 7

Sizes are current word counts; the targets are estimates based on the ratio the
RE clusters achieved (roughly 2.5:1).

### 1. Query handling and answer quality — **DONE 2026-09-03**

7 files, 8,294 words → `QUERY_HANDLING_AND_QUALITY.md`. Merged: query
classification and tracking, scoped queries (implementation and troubleshooting),
exhaustive query detection, hallucination analysis, RAG quality improvements, and
the performance/quality analysis.

`SCOPED_QUERIES_TROUBLESHOOTING` stayed with the design rather than moving to
`user-docs/` as this plan suggested — the troubleshooting steps are only
intelligible next to the root cause they came from.

**Four claims did not survive the check against the code**, which is the value of
the pass and is recorded in the new document's §6:

- the two headline hallucination fixes (bigger chunks, bigger embedding model)
  were never adopted — both are still the live config, while the cheaper
  recommendations did ship;
- a Milvus scalar-filter workaround is still in `pyegeria_agent.py:270` though
  Milvus was removed in July and pgvector has no such limitation;
- `PyegeriaAgent` looked orphaned on a first grep and is not — a malformed
  exclusion pattern, caught before it reached the document;
- it is missing from `CLAUDE.md`'s agent table.

### 2. Indexing and collections — **DONE 2026-09-03**

6 files, 7,371 words → `INDEXING_AND_COLLECTIONS.md`.

**Four claims checked against the code changed what the document says:**

- the `egeria_docs` split shipped — nine collections enabled, `egeria_docs`
  `enabled=False`, so that strategy doc was a completed plan;
- the per-collection schema is no longer EA-local. It moved into the shared
  `trellis-vectorstore` package, and Resource Explorer imports the same one, so
  a schema change now affects two applications;
- incremental indexing state moved from SQLite to Postgres. The design still
  specified `data/index_state.db`, and `FileTracker.__init__` still accepts a
  `db_path` its own docstring says is ignored, while the caller computes it;
- `egeria_docs` still carries 22 live routing keywords. Verified inert — the
  router guards on `.enabled` — so dead config rather than a misroute.

### 3. Monitoring and analytics — **DONE 2026-09-03**

3 files, 5,416 words → `MONITORING_AND_ANALYTICS.md`. This plan predicted the
status/next-steps pair meant one superseded the other. It was worse than that:

- **two of the four "completed" next steps did not happen in the files they
  name.** Monitoring integrates from `rag_system.py`, not `rag_retrieval.py`, and
  the router never imports the classifier — `route_query()` takes `intent` and is
  handed the classification. Both are integrated; the checklist points at two
  files containing none of it;
- **per-collection retrieval metrics are durable only when MLflow is running.**
  `collection_metrics.py` has exactly one consumer, `mlflow_tracking.py`. The
  `collection_health` table is the part that reaches Postgres unconditionally —
  the two are easy to conflate and only one survives MLflow being down.

### 4. Runtime and hardware — **DONE 2026-09-03**

3 files → `RUNTIME_AND_HARDWARE.md`, plus a split. The ROCm Python-version note
rescued from `history/` joined this cluster; `user-docs/ONNX_MIGRATION_GUIDE.md`
stays where it is as operator instructions.

**The ONNX migration is complete and switched off.** Implementation, both
exported model files, the export script and the benchmark suite are all present;
`backend: pytorch`. And **no benchmark result is recorded anywhere** — the plan
sets 2-3x targets and builds a suite to measure them, so the question "is ONNX
faster here" has a script and no answer. That is worth resolving before either
flipping the switch or deleting the path.

**Track B was never started.** The source document was 600 lines, of which 474
were a 9-week "Egeria-Advisor-Pro" product plan whose every named artefact is
absent. It is now `future/EGERIA_ADVISOR_PRO.md`. Keeping it with completed
infrastructure meant the document's own status line could only be right about
half of itself.

### 5. Agents, routing, and code analysis — **DONE 2026-09-03**

4 files, 3,778 words → `AGENTS_AND_CODE_ANALYSIS.md`.

**This plan's cross-check was half right, and the wrong half mattered more.**
"Code analysis" names two unrelated capabilities in this codebase, described in
separate documents using the same phrase:

- **Symbol extraction did transfer**, and completely. EA reads
  `resource_explorer.project_code_symbols` through a shim that mirrors the old
  method names so call sites did not change; the write path was removed from
  `ingest_file()`. `code_symbol_store.py` and its tables are kept unwritten as a
  **deliberate rollback net (decision D8)** — a considered state, not drift, and
  worth knowing before someone tidies away tables that look unused.
- **Repository metrics did not.** Radon/Pygount and their scripts are still EA's,
  so `CODE_ANALYSIS_UPDATE_GUIDE`'s instructions are live. Reading the two
  documents as one subject would have retired working instructions — which is
  exactly what this plan's own cross-check invited.

Also found: the cache those metrics write to (`data/cache/enhanced_metrics.json`)
is absent, so anything consuming them is reading nothing.

### 6. Session, state, and artifacts — **REVIEWED 2026-09-03, NOT MERGED**

`SESSION_AND_INTERACTION_STATE` · `PER_USER_ARTIFACT_NAMESPACING` ·
`RELATIONSHIP_LINKING_SCOPE` · `REPORT_SPEC_BUILDER_DESIGN`

This plan called it "the loosest grouping". Checked against the code and against
`CLAUDE.md`, **it is not a grouping at all** — four separate live designs that
share only the fact that none of them fitted the other five clusters. Merging
them would have produced one document with four unrelated subjects and destroyed
two authoritative pointers.

| | Why it stands alone |
|---|---|
| `REPORT_SPEC_BUILDER_DESIGN` | cited in `CLAUDE.md`'s **header** as the report-spec architecture, and backed by six numbered rules (A–F) |
| `RELATIONSHIP_LINKING_SCOPE` | cited in `CLAUDE.md` **rule 27** as the "full design and rollout scope" |
| `PER_USER_ARTIFACT_NAMESPACING` | live open design (**SS-4**, one of 14 SS- items in `BACKLOG.md`), one question still open. Verified unbuilt: `_drafts_path()` is a fixed root with no user component |
| `SESSION_AND_INTERACTION_STATE` | design-only, and its diagnosis still holds — `_activeDraftId` is still used 53 times in `index.html` with no flow-state object |

**Both status lines were verified rather than trusted**, since two of them are
months old and this consolidation has already found four documents claiming a
state the code contradicted.

Work done here instead: the six conversational attributions in
`PER_USER_ARTIFACT_NAMESPACING` were rewritten as dated maintainer decisions,
keeping their force while removing the first-person framing. They were the only
such references anywhere in EA's live documentation.

**The lesson for clusters that look loose: check whether the residue is one
subject or several before merging it.** A cluster defined by what is left over is
not a cluster.

### 7. Open work — **DONE 2026-09-03**

Not a merge: **no fifth tracker was created.** EA already has a live `BACKLOG.md`
(4,894 words, eight sections), so the question was what of these four is still
open and where it belongs.

**Three were one day's snapshots.** `REMAINING_TODOS`,
`TODO_IMPLEMENTATION_SUMMARY` and `SPRINT_2026_03_07_SUMMARY` are all dated
2026-03-07 — a sprint and its TODO captures. Their contents were checked item by
item rather than assumed stale:

- most entries were already ✅, and the list's own conclusion was *"NONE — all
  critical functionality is working"*;
- **"Re-enable singleton pattern, `advisor/vector_store.py` line 455"** is
  obsolete. That file is now **42 lines** — rewritten during the pgvector
  migration — and the caching it asked for already exists one level up, where
  `MultiCollectionStore` is a singleton holding a single store;
- **"Performance benchmarking"** was the one live item. It is now **PM-1** in
  `BACKLOG.md`, merged with the ONNX finding from cluster 4, because they are the
  same gap twice: a benchmark harness that exists and a number that was never
  recorded.

Archived out-of-repo and deleted.

**`egeria-wishlist` is not a tracker of EA's work at all** and stays. It lists
feature gaps in **Egeria and pyegeria themselves**, which makes it complementary
to `egeria-python`'s `PYEGERIA_ISSUES.md` — that is the canonical tracker for
*bugs*, this is the place for "the API could do X" rather than "the API does X
wrong". It now says so at the top, because filing it under `design/` alongside
EA's own designs is exactly what made it look like a fourth backlog.

### Left standing

`SYSTEM_ARCHITECTURE` and `egeria-advisor-plan` are the entry points and should
stay separate, as `Architecture.md` did in RE.

## `history/` — DONE 2026-09-03, and the premise was wrong

**`docs/history/` was gitignored** (`packages/egeria-advisor/.gitignore:209`,
`/docs/history/`). All 31 files were local-only working notes that **had never
been in the repository at all** — `git ls-files` returned zero for that
directory. This plan's claim that it was "a third of EA's documentation by
volume" was true of the working tree and false of the repository, and the
recommendation to start there because it was "the largest reduction" was
therefore built on a measurement of the wrong thing.

What that hid was more interesting than what it counted. **Five of the 31 were
not history**, and one was a real defect:

| file | verdict | evidence |
|---|---|---|
| `PHASE6_CLI_GUIDE` → `user-docs/CLI_GUIDE.md` | **live user documentation** | the CLI exists (`egeria-advisor = advisor.cli.main:cli`) and `--interactive` is still its entry point; `CLI_COMMAND_AGENT_GUIDE` is a different feature and never mentions it |
| `PHASE5_LESSONS_LEARNED` → `design/BEEAI_INTEGRATION_LESSONS.md` | **still relevant** | `beeai-framework` is still a dependency, so the difficulties it records are a live caution |
| `FRAMEWORK_COMPARISON` → `design/` | **reference** | informed a framework choice still in force |
| `PYTHON_VERSION_SOLUTION` → `design/RUNTIME_AND_HARDWARE.md` | **possibly operative** | ROCm is still referenced by `embeddings_onnx.py`, `embeddings.py`, `advisor.yaml` |
| `PHASE9_USE_CASE_EXAMPLES` → `future/USE_CASE_EXAMPLES.md` | **unbuilt** | declares itself "Design Phase, Priority: High" — open work, not a completion record |

**A user guide for a shipping CLI was invisible to anyone cloning the
repository**, because it happened to be named after the phase that produced it
and filed with the completion records. The directory name was doing the
classifying, and it was wrong about five files out of 31.

The remaining 26 were genuine completion records and are archived out-of-repo
(checksum-verified) and removed from the working tree. Four surviving documents
pointed into `history/`; those pointers were **already dangling for everyone but
this machine**, and now say the target is archived rather than linking nowhere.

## What to check before merging anything

Learned from the RE passes, in the order they cost time:

1. **A document's claim about itself can be wrong.** One RE file was labelled a
   stub and deleted; it was one of three parallel reference notes and had to be
   restored. Read the file, not the filename.
2. **Verify claims survive before deleting.** Extract the load-bearing claims from
   each source, then check them present in the consolidation. Give every source a
   non-empty claim list — an empty one passes by construction — and normalise
   whitespace, or a line wrap reads as a missing claim.
3. **Do not repoint references inside dated records.** A morning brief, an
   incident narrative, a processed command log: rewriting a reference in a record
   of what was done makes the record wrong.
4. **Protect "merged from" attributions.** Three separate variants of that damage
   occurred across the RE clusters. Excluding files by name beat every regex
   lookbehind.
5. **Export and checksum-verify before deleting**, not after.

## Recommended order

`history/` is done. Next is `design/` cluster 1 (query handling and answer
quality) — seven documents on one subject, the most coherent grouping here, and
the right place to prove the pattern on this codebase before committing to it.

**And carry forward the lesson `history/` produced:** check each file against the
code before believing where it was filed. Five of 31 were misfiled, including a
user guide for a shipping CLI. A directory name is a claim about its contents,
and claims are the thing to verify.
