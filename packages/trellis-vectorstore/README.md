# trellis-vectorstore

Shared pgvector-backed vector store, used by both `resource-explorer` and `egeria-advisor`.

Extracted from two independently-evolved but structurally similar `PgVectorStore`
implementations. See `docs/trellis-vectorstore-extraction.md` (repo root) for the full
design rationale — every constructor parameter on `PgVectorStore` traces to a confirmed,
deliberate behavioral difference between the two original implementations, not a guess.

Neither app should need to change any of its own call sites: each keeps its existing
`vector_store_pg.py`/`vector_store.py` module as a thin adapter that subclasses/configures
this package's `PgVectorStore` to reproduce its own pre-extraction behavior exactly.
