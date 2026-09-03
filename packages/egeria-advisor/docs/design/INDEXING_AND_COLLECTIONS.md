# Indexing and collections

**Status:** consolidated design. Current as of 2026-09-03.
**Scope:** how content is split across collections, what metadata is indexed
alongside it, how a collection is re-indexed incrementally, and how filters
reach the store. For how a query is routed to a collection, see
`QUERY_HANDLING_AND_QUALITY.md`.

> **This document consolidates six** notes from `design/`: the multi-collection
> design, collection-specific parameters, structured metadata indexing, metadata
> filtering, incremental indexing, and the `egeria_docs` split strategy.
>
> **§6 is the part to read first.** Every claim was checked against the code on
> 2026-09-03. Three of these documents describe work that has since shipped, and
> one describes a storage backend that was replaced.

---

## 1. Why several collections rather than one

A single index over Python source, Java source, CLI help, markdown tutorials and
notebook examples retrieves badly, because similarity in one register does not
mean relevance in another: a conceptual question matches prose that *mentions*
the concept, and a code question matches identifiers. Splitting by content kind
lets the router narrow before retrieval rather than re-ranking afterwards.

**Nine collections are enabled** (verified live, 2026-09-03):

| Collection | Content |
|---|---|
| `pyegeria` | Python SDK code and tests |
| `pyegeria_cli` | `hey_egeria` CLI commands |
| `pyegeria_drE` | Dr.Egeria markdown translator code |
| `egeria_java` | Core Java library (OMAS, OMAG, OMRS) |
| `egeria_concepts` | Core concept definitions |
| `egeria_types` | Type system and schema definitions |
| `egeria_general` | Tutorials, guides, how-tos |
| `egeria_workspaces` | Jupyter notebooks, deployment examples |
| `egeria_templates` | Dr.Egeria markdown command templates |

The router selects 1–N per query from the classified intent.

## 2. The `egeria_docs` split — done

`egeria_docs` was one collection holding concepts, type definitions and tutorials
together. Those three answer different question shapes and were competing with
each other inside a single similarity ranking, so a "what is X" question could be
answered from a tutorial's passing mention.

It was split into `egeria_concepts`, `egeria_types` and `egeria_general`.
**This shipped** — the three are live and `egeria_docs` is `enabled=False`.

## 3. Collection-specific parameters

Collections differ in what a useful chunk *is*: a Python method is a natural unit,
a tutorial section is not the same size, and a CLI help entry is smaller than
both. The design called for per-collection chunking and retrieval parameters
rather than one global setting.

Two collections additionally carry **extra scalar columns** beyond the base
schema, so structural facts are filterable rather than only embedded:

```python
"pyegeria": CollectionSchema(extra_columns=(
    ExtraColumn("element_type",  "VARCHAR(50)",  "", "''"),
    ExtraColumn("class_name",    "VARCHAR(200)", "", "''"),
    ExtraColumn("method_name",   "VARCHAR(200)", "", "''"),
    ExtraColumn("module_path",   "VARCHAR(500)", "", "''"),
    ExtraColumn("is_async",      "BOOLEAN",   False, "FALSE"),
    ExtraColumn("is_private",    "BOOLEAN",   False, "FALSE"),
))
```

## 4. Structured metadata indexing

The point of those columns: **some questions are not similarity questions.**
"Which methods on `ProjectManager` are async?" is a `WHERE` clause, and answering
it by embedding proximity produces a plausible list rather than a correct one.

Storing `class_name`, `method_name`, `element_type`, `module_path`, `is_async`
and `is_private` as real typed columns beside the vector makes the exact
questions exact, and leaves similarity for the questions that need it. This is
the same division `QUERY_HANDLING_AND_QUALITY.md` §3 relies on for exhaustive
queries.

## 5. Metadata filtering and incremental indexing

**Filtering.** A filter expression is translated into SQL by
`translate_filter_expr`, so a query can constrain on the scalar columns above and
on stored metadata. Filters compose — see §6b for why that matters.

**Incremental indexing.** Re-embedding a whole collection to pick up a handful of
changed files is the dominant cost in keeping an index current, so the indexer
tracks each file's path, modification time and content hash, and re-processes
only what changed. Its safety properties, as designed: verify entity counts
against the tracking record, detect orphaned entities, and keep the operation
auditable.

---

## 6. Checked against the code, 2026-09-03

### 6a. Per-collection schema is no longer EA-local

`COLLECTION_SPECIFIC_PARAMETERS` and `MULTI_COLLECTION_DESIGN` describe structures
that have since **moved into the shared `trellis-vectorstore` package**. What were
module-level dicts (`_TABLE_DDL`, `_EXTRA_COLUMNS`, `_COL_DEFAULTS`,
`_TABLE_NAME_MAP`) are now real constructor config — `CollectionSchema` and
`ExtraColumn` — passed to a shared `PgVectorStore`:

```python
from trellis_vectorstore import CollectionSchema, ExtraColumn, PgVectorStoreConfig, translate_filter_expr
from trellis_vectorstore.pg import PgVectorStore as _SharedPgVectorStore
```

**Resource Explorer imports the same package.** So these are no longer EA design
decisions in isolation — a change to the schema contract now affects two
applications, and that is the fact most likely to be missed by someone reading
the original documents.

### 6b. The filter translator is shared too

`translate_filter_expr` comes from the same package. This is what makes the
Milvus-era workaround recorded in `QUERY_HANDLING_AND_QUALITY.md` §6b
unnecessary: compound scalar filters translate to SQL `AND`, which is exactly the
thing Milvus could not do and the reason that workaround exists.

### 6c. Incremental indexing state moved from SQLite to Postgres

`INCREMENTAL_INDEXING_DESIGN` specifies a SQLite tracking database at
`data/index_state.db`, with a `CREATE TABLE indexed_files` schema.

**The implementation uses Postgres.** `indexed_files` and `index_metadata` are
created by `ConsolidatedDBManager` (`advisor/db_consolidated.py:85,97`) in the
same `egeria_advisor` database the vectors live in, and self-provision on first
connect.

The migration left a vestige. `FileTracker.__init__` still takes `db_path`:

```python
def __init__(self, db_path: Optional[Path] = None):
    """db_path: Ignored, retained for signature compatibility."""
    self.db_manager = get_db_manager()
```

— and its caller still computes the path that is then ignored
(`incremental_indexer.py:266`):

```python
db_path = Path(config.get("data_dir", "data")) / "index_state.db"
self.tracker = FileTracker(db_path)
```

Harmless, and misleading in the specific way that costs time later: a reader
looking for the indexing state will look for a SQLite file that is never created.

### 6d. `egeria_docs` still has a live keyword block

`routing.yaml` carries 22 routing keywords for `egeria_docs` — "documentation",
"guide", "tutorial", "concept", "omas", "omag", "omrs", "architecture",
"overview" and others — uncommented, in the same form as the enabled collections.

**It is inert**, and this was checked rather than assumed: `CollectionRouter`
initialises from `get_enabled_collections()` and guards the docs path explicitly
(`collection_router.py:232`, `if docs_collection and docs_collection.enabled`).
So a query matching "documentation" cannot be routed to a collection with no
data.

Dead config rather than a defect — but it reads as live, and several of those
keywords are exactly the ones the three replacement collections now want.

---

## 7. Settled — do not reopen without re-measuring

| Question | Settled | On what basis |
|---|---|---|
| Should everything live in one collection? | **No** | Similarity in one register does not mean relevance in another; the router narrows before retrieval |
| Was splitting `egeria_docs` worth it? | **Yes, and it shipped** | Three replacements live, `egeria_docs` `enabled=False` |
| One global chunking/retrieval setting? | **No** | A Python method, a tutorial section and a CLI help entry are not the same unit |
| Should structural facts be embedded only? | **No** | "Which methods are async" is a `WHERE` clause; embedding proximity gives a plausible list, not a correct one |
| Re-index a whole collection on change? | **No** | Path, mtime and content hash identify what actually changed |
| Is the per-collection schema EA-local? | **No, not any more** | It moved to `trellis-vectorstore`; Resource Explorer consumes the same package |
| Is indexing state in SQLite? | **No** — Postgres | `ConsolidatedDBManager` creates `indexed_files`/`index_metadata`; the `db_path` argument is explicitly ignored |
| Can `egeria_docs` still be routed to? | **No** | The router guards on `.enabled`; its keyword block is inert |
