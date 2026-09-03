# Egeria Advisor documentation — consolidation plan

**Status:** `history/` and `design/` clusters 1–2 are DONE (2026-09-03).
Clusters 3–7 remain a proposal awaiting approval.
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

### 3. Monitoring and analytics — 3 files, ~5,400 words

`MONITORING_NEXT_STEPS` · `MONITORING_IMPLEMENTATION_STATUS` ·
`DATASET_TRACKING_AND_ANALYTICS_ENHANCEMENT`

Two of these are a status/next-steps pair, which usually means one supersedes the
other.

### 4. Runtime and hardware — 2 files, ~3,700 words

`ONNX_MIGRATION_AND_PRO_TRACK_PLAN` · `AMD_OPTIMIZATION`

Cross-check against `user-docs/ONNX_MIGRATION_GUIDE.md` — a design document and a
migration guide for the same change should not disagree, and if the migration is
complete both may be history.

### 5. Agents, routing, and code analysis — 4 files, ~3,800 words

`CLI_COMMAND_AGENT_DESIGN` · `AGENT_ERROR_AND_ROUTING_FIX` ·
`CODE_ANALYSIS_TOOLS_RESEARCH` · `CODE_ANALYSIS_UPDATE_GUIDE`

Cross-check against RE: code analysis moved *from* EA *to* RE, so some of this may
describe a capability that no longer lives here.

### 6. Session, state, and artifacts — 4 files, ~5,600 words

`SESSION_AND_INTERACTION_STATE` · `PER_USER_ARTIFACT_NAMESPACING` ·
`RELATIONSHIP_LINKING_SCOPE` · `REPORT_SPEC_BUILDER_DESIGN`

The loosest grouping. `REPORT_SPEC_BUILDER_DESIGN` may deserve to stand alone —
it is an active design area.

### 7. Open work — 4 files, ~3,750 words

`REMAINING_TODOS` · `TODO_IMPLEMENTATION_SUMMARY` · `egeria-wishlist` ·
`SPRINT_2026_03_07_SUMMARY`

These are trackers, not designs. The other three likely collapse into one
backlog, the way RE keeps a single `Backlog.md`. The sprint summary is dated —
and `history/` no longer exists, so it needs a status line rather than a move.

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
| `PYTHON_VERSION_SOLUTION` → `design/PYTHON_VERSION_FOR_ROCM.md` | **possibly operative** | ROCm is still referenced by `embeddings_onnx.py`, `embeddings.py`, `advisor.yaml` |
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
