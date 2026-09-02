# Filesystem and database resource types — design inputs

**Not a design. Inputs to one**, gathered 2026-09-02 from Egeria's source at
`/Users/dwolfson/localGit/egeria-v6/egeria`. Dan: *"For FS and DB, we may need
more design work — Egeria already has survey types useful for both"*, and
*"we also need to include Annotation types in the discussion."*

The headline is that **the repo experience is a poor guide to FS and DB**,
because for repos Egeria had nothing and RE built everything. For filesystems
and databases Egeria ships working survey services and a richer annotation
vocabulary than RE currently uses.

---

## 1. Egeria already surveys filesystems and databases

**17 native survey action services** in the source tree:

| resource | services |
|---|---|
| **filesystem** | `FileSurveyService`, `FolderSurveyService`, `CSVSurveyService` |
| **database** | `PostgresDatabaseSurveyActionService`, `PostgresServerSurveyActionService`, plus Oracle, MSSQL, DB2 LUW and DuckDB variants (server + database for each) |
| **catalog** | `OSSUnityCatalogServerSurveyService`, `…InsideCatalogSurveyService`, `…InsideSchemaSurveyService` |
| **platform** | `OMAGServerPlatformSurveyService` |

**There is no repo survey service in that list.** That asymmetry explains the
whole shape of RE's repo work — 40 steps, its own surveyors, its own
persistence — and it does not carry over.

So the first design question for FS and DB is not "what steps do we write" but:

> **Is RE the surveyor, or the orchestrator and consumer of Egeria's?**

`docs/re-as-engine-host-plan.md` already frames this as four cases. Two are
live options here:

- **Case 3 (RE surveys locally)** — what repos do. Full control, no Egeria
  dependency, duplicates what Egeria already implements for these two types.
- **Case 1/2 (trigger, or claim and run, Egeria-native surveys)** — reuses
  `PostgresDatabaseSurveyActionService` and friends rather than reimplementing
  them.

**Blocked today either way by ISSUE-79**, not by design: a native survey
against a template-created asset fails server-side (`assetConnector` null).
That plan is ON HOLD for exactly this reason. See
`docs/egeria-blocker-review-2026-09-02.md`.

A likely honest answer is a split: let Egeria's services do the file/table/column
mechanics they already do well, and keep RE's own layer for the things it
adds that Egeria has no equivalent for (disposition, questions, RFA triage,
curation, the investigation model).

---

## 2. RE uses 7 annotation types; Egeria defines 18

RE's `ANNOTATION_TYPES_REGISTRY` covers seven. Egeria's type model defines
eighteen. **Twelve are unused**, and several are not obscure — they are
precise fits for work RE already does, or is about to.

**Used today:** `ClassificationAnnotation`, `ResourceMeasureAnnotation`,
`SchemaAnalysisAnnotation`, `DataClassAnnotation`, `QualityAnnotation`,
`RelationshipAdviceAnnotation`, `RequestForAction`.

**Unused, and directly relevant:**

| type | Egeria's own description | where it fits |
|---|---|---|
| **`CodeAnalysisAnnotation`** | *"A set of properties describing the content of the code in a code repository like GitHub."* | **exactly what RE does for repos today**, published as ResourceMeasure/SchemaAnalysis instead |
| **`ContributorAnalysisAnnotation`** | (0680 code-analysis model) | RE's CHAOSS metrics, community support, contributor concentration |
| **`ResourceProfileAnnotation`** | *"A collection of properties that characterize an aspect of a resource."* | data profiling — RE has its own shape for this |
| **`ResourceProfileLogAnnotation`** | — | profile results too large to inline |
| **`ResourcePhysicalStatusAnnotation`** | — | **filesystem**: size, timestamps, physical state |
| **`DataFieldAnnotation`** | *"A collection of properties about a data field, or number of data fields, in an Asset."* | **database**: column-level findings |
| **`DataGrainAnnotation`** | — | **database**: granularity of a table |
| **`FingerprintAnnotation`** | *"An annotation capturing digital resource fingerprint information."* | duplicate detection across files/tables |
| **`SemanticAnnotation`** | *"A recommendation of likely mappings to Glossary Terms for all or part of an Asset."* | glossary linkage — RE has no equivalent |

Also unused: `AssociatedAnnotation`, `ReportedAnnotation`, `DataFieldAnnotation`'s
siblings, and the base `Annotation`.

### Why this matters more than it looks

**`CodeAnalysisAnnotation` is the tell.** Egeria has a typed annotation whose
own description is "the content of the code in a code repository like GitHub",
and RE — which analyses code in GitHub repositories — does not use it. RE's
code findings are published as `ResourceMeasureAnnotation` and
`SchemaAnalysisAnnotation`, which are the generic shapes.

That is not a bug today; those annotations carry the information. But it means
**a consumer querying Egeria for code analysis will not find RE's** — the
publishing is correct and the type is generic, so it is invisible to a
type-scoped query. Same argument for contributor analysis.

For FS and DB the equivalent mistake would be publishing column-level findings
as generic measures when `DataFieldAnnotation` exists, and physical file state
as measures when `ResourcePhysicalStatusAnnotation` exists — with the added
cost that Egeria's *own* FS/DB survey services presumably emit the specific
types, so RE's output would not sit alongside theirs.

### The check to run before designing FS/DB steps

For each planned finding, ask **"does Egeria already have a type for this
shape?"** before reaching for `ResourceMeasureAnnotation`. The generic types
are a reasonable default only where nothing specific exists.

Worth doing retroactively for repos too — at least `CodeAnalysisAnnotation`
and `ContributorAnalysisAnnotation` — but as its own change, with the
migration question (what happens to already-published annotations of the
generic type) answered rather than assumed.

---

## 3. What is not yet established

- **What the native FS/DB services actually emit.** This document establishes
  that they exist and that Egeria has richer annotation types; it does *not*
  establish which types each service produces. Reading
  `PostgresDatabaseSurveyActionService` and `FolderSurveyService` would say,
  and would show how much RE would be duplicating under case 3.
- **Whether RE can author every relevant annotation type over REST.**
  `create_annotation` exists in pyegeria's `data_discovery.py`; whether a
  `SurveyReport` can be authored over REST at all is flagged as unverified in
  `re-as-engine-host-plan.md`.
- **Property shapes.** Each unused type has its own `…Properties` class; none
  were read here. Adopting one means matching its properties, not just its
  name.
- **Whether ISSUE-79 still reproduces** on the current deployment. The tracker
  records an Egeria-side investigation that disproved the original root-cause
  theory and an FVT suite now passing; whether this deployment still hits it
  is open.

## 4. Suggested sequence

1. Settle **surveyor vs orchestrator** for FS and DB first. Everything else
   depends on it, and it is a question about duplication and ownership, not
   about code.
2. Read what the native services emit, so the duplication cost is a measured
   number rather than an impression.
3. Decide the **annotation-type mapping** before writing steps — retrofitting
   published annotations is the expensive direction.
4. Only then design steps, and only for whatever RE is actually going to
   survey itself.
