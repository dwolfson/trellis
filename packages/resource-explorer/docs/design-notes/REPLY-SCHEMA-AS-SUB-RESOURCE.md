# Reply: schema is the aggregation grain now, and a sub-resource next

**Replying to:** `ASK-SCHEMA-AS-SUB-RESOURCE.md` (#263).
**From:** the design session, 2026-09-24.
**Read against:** `main` at `1f56d2df`.
**Status:** an opinion, given conversationally to the coordinating session
the same day and recorded here. The project owner's D3 ruling (2026-09-20)
already covers the model; what follows is how it applies to this layer.

---

## 0 · The diagnosis is right, and the precedent is the wrong one

The ask's read holds: `db_classification`, `db_relationship_graph`,
`db_fingerprint` (and `schema_conventions`, and every §16 coverage/grain
analysis once built) aggregate at the wrong grain. "Edge count 0,
component count 3" for `coco_pharma` is correct for three single-table
schemas and meaningless as a statement about the database; once
`coco_ods` (23 tables, real FK graph) is visible it is averaged into the
same number and the finding that matters — *that schema is a transactional
model and the others are not* — disappears.

`repo_sub_resource_survey` is not the model to copy. It answers an
advisory question, "which folders are worth promoting", because folder
membership in a repository carries no meaning by itself. Schema membership
is **total and by construction**: every table is in exactly one schema.
That is an aggregation grain, not a promotion candidate.

## 1 · Both shapes, in order; they are not alternatives

### Shape 1, now — schema-scoped output, no new registration

Schema becomes the aggregation grain of every structural database
analysis. No new plumbing: `target_shape` and `scope_locator` already exist
(`surveyors/scoping.py` is the repo path-prefix version), and the
structured tables from stream 3 carry `schema` on every row, so a schema
scope is a `WHERE` clause.

| Analysis | Per schema | Whole-database rollup (labelled as a rollup, never an average) |
|---|---|---|
| `db_classification` | the schema's kind (transactional, analytical, reference, staging, copy) | the *set* of kinds present, with counts |
| `db_relationship_graph` | components and FK density within the schema | per-schema summaries **plus cross-schema FK edges reported as a database-level fact in their own right** |
| `db_fingerprint` | schema signature | the list of schema signatures — this is what will show that `coco_pharma.coco_ods` is a copy of the `coco_ods` database, the finding the whole-database version buries |
| `schema_conventions`, `db_documentation_coverage` | checks and ratios per schema | totals, with the per-schema spread |
| `coverage_signals`, `coverage_profile`, `preliminary_fit`, `requirement_fit` (design §16) | per schema — a lens may fit one schema and not the database | the best-fitting schema named |
| `grain_determination` | already per table; nothing to do | — |

Exclude `pg_catalog`, `information_schema` and `pg_toast*` by default;
treat `public` as a schema like any other.

### Shape 2, next — schema as a registered sub-resource (D3, literally)

Rows in the existing `sub_resources` table, keyed `(resource_type, slug)`,
created **deterministically from the inventory** — every non-system schema,
parent = the database — not as candidates and not by advice. D3's
"first-class on direct registration" then means exactly what it says: a
user who registers a schema directly gets a top-level resource; every
other schema is a sub-resource with what design §6.5 promised (the same
analyses, `target_shape: single_container`, the sub-resource navigation
control in the designer brief).

Rule A support: Egeria's own Postgres survey emits `RelationalSchemaMetric`
measurements per schema (`PROBES-2026-09-21.md`: one schema-measurement
annotation type among the four), and its technology types already separate
`DeployedDatabaseSchema` from the database. Per-schema rows are what the
native read-back materialises anyway; shape 2 gives them somewhere to land.

## 2 · Interaction with the credential-capability work

Schema is the natural unit of the capability probe
(`REPLY-DATABASE-CREDENTIAL-CAPABILITY-VISIBILITY.md` §3): `USAGE` is per
schema, `SELECT` is per table within it. So:

- "measured within credential scope" becomes a **per-schema state** — a
  schema with `USAGE` and no `SELECT` renders as "structure only" rather
  than being silently counted;
- the launcher's "needs `read` on N of M tables" **lists them by schema**,
  which is what a database owner grants on anyway;
- the incident's numbers become legible: "3 of 8 schemas readable; 3 of 26
  tables" instead of "3 tables".

Build shape 1 and the probe in the same slice; they share the rows.

## 3 · Filesystems: same disease, different anatomy

Membership is by construction there too — every file is in exactly one
folder — but the meaningful level is not fixed: a root may be one
homogeneous dataset or five unrelated drops. So the mechanism is shared
(`scope_locator`, per-scope output, a `sub_resources` row when promoted)
and only the *which level* rule differs:

- **Databases:** fixed — schema.
- **Filesystems:** discovered — report at the first level where the
  children's classifications disagree (`filesystem_classification` and
  `path_conventions` decide); a folder becomes a sub-resource row when
  that rule promotes it.
- **Datasets:** per distribution or split, from the descriptor.

## 4 · What closes the ask

Shape 1 closes the bug and belongs in Phase 1 with the structured tables
and the capability probe. Shape 2 is D3 for this layer and belongs
immediately after, because the navigation, the per-schema credential state
and per-schema lens fit all read from `sub_resources`. Neither needs a new
project-owner ruling; D3 already gave it.
