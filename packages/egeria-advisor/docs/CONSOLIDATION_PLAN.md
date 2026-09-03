# Egeria Advisor documentation — consolidation plan

**Status:** proposal, awaiting approval. Nothing here has been done.
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
| `history/` | 31 | 37,050 | phase-completion records — archive candidates |
| `archive/` | 18 | 19,294 | already archived; check nothing live is buried |
| `future/` | 2 | 2,269 | leave alone |
| top level | 2 | 26,536 | `PROJECT_SUMMARY.md` (18,757) is the entry point |

## Proposed clusters — `design/`, 32 files into roughly 7

Sizes are current word counts; the targets are estimates based on the ratio the
RE clusters achieved (roughly 2.5:1).

### 1. Query handling and answer quality — 7 files, ~8,300 words

`QUERY_CLASSIFICATION_AND_TRACKING` · `HALLUCINATION_ANALYSIS_AND_FIXES` ·
`RAG_QUALITY_IMPROVEMENTS` · `EXHAUSTIVE_QUERY_DETECTION` ·
`SCOPED_QUERIES_IMPLEMENTATION` · `SCOPED_QUERIES_TROUBLESHOOTING` ·
`PERFORMANCE_AND_QUALITY_ANALYSIS`

The strongest cluster: one subject, seven documents. Note that
`SCOPED_QUERIES_TROUBLESHOOTING` is operator-facing and may belong in
`user-docs/` rather than in the merged design document.

### 2. Indexing and collections — 6 files, ~7,400 words

`MULTI_COLLECTION_DESIGN` · `COLLECTION_SPECIFIC_PARAMETERS` ·
`STRUCTURED_METADATA_INDEXING` · `METADATA_FILTERING_ENHANCEMENT` ·
`INCREMENTAL_INDEXING_DESIGN` · `EGERIA_DOCS_SPLIT_STRATEGY`

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

These are trackers, not designs. The sprint summary is dated and belongs in
`history/`. The other three likely collapse into one backlog, the way RE keeps a
single `Backlog.md`.

### Left standing

`SYSTEM_ARCHITECTURE` and `egeria-advisor-plan` are the entry points and should
stay separate, as `Architecture.md` did in RE.

## `history/` — 31 files, 37,050 words

Named `PHASE2_COMPLETE`, `PHASE10.3_DESIGN`, `MULTI_COLLECTION_STATUS` and
similar: completion records for work that finished. **The directory name already
does the job a status line does**, so the question is only whether they should
stay in the repository at all — a maintainer judgement, not a mechanical one.

The RE approach was: export out of the repository, verify by checksum, then
delete. `history/` is the natural candidate for exactly that, and it is a third of
EA's documentation by volume.

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

`history/` first — it is the largest single reduction and the lowest-risk
judgement, because the directory already declares what the files are. Then
`design/` cluster 1, which is the most coherent and would prove the pattern on
this codebase before committing to it.
