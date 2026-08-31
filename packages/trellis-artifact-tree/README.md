# trellis-artifact-tree

The containment tree over ingested artifacts — the structure that retrieval
chunks and compression rungs are both cut from.

**Why a shared package rather than one app's table.** Resource Explorer and
Egeria Advisor each run their own repo → parse → chunk → embed pipeline. That is
a confirmed divergence, not accidental duplication (`docs/ingestion-pipeline-audit.md`
item 3: windowed-chunk RAG vs. semantic-unit RAG), and it is being left alone.
But it means **both apps produce trees**, not just consume them — so the
cross-schema read pattern that works for RE's code symbols cannot serve this.
The write path has to live somewhere both apps can call.

**Adapters live here, behind extras.** Code and PDF parsing are common to both
apps -- both already depend on `docling` and `tree-sitter` today -- so putting
those adapters "in the app that needs them" would name both apps and duplicate
the parser. Instead the core install is stdlib-only (model, store, registry,
markdown, generic fallback) and heavier adapters come from extras:
`trellis-artifact-tree[code]`, `[pdf]`. A consumer that only wants the model and
store pays for neither.

**Not a vector store.** Embeddings are `trellis-vectorstore`'s business, and a
leaf node references its chunks by id. Both live in the same Postgres, so
structure and vectors join in one query without either package knowing the
other's tables.

**The distinction it exists to hold.** Chunk size is a *tuned parameter* driven
by artifact category and content profile. Rung boundaries are a *containment*
question — a structural unit can contain several chunks. Neither derives from
the other, and code written against "chunks" alone cannot express a compression
ladder.

See `docs/context-compilation-design.md` §15 (the tree), §21 (format
independence and graceful degradation), and §8 (package boundary).

## Using it

```python
from trellis_artifact_tree import AdapterRegistry, ArtifactTreeStore
from trellis_artifact_tree.model import Provenance

registry = AdapterRegistry()      # Markdown and HTML by default
tree = registry.parse(
    artifact_id="docs/guide.md",
    kind="markdown",              # picks the adapter
    source=text,
    provenance=Provenance(...),
)

store = ArtifactTreeStore(conn)
store.create_schema()
store.put(tree)
```

`AdapterRegistry()` carries Markdown and HTML only; pass `adapters=[...]` (or call `register`)
to add the code, docling and generic-text adapters. Each turns one artifact into a containment
tree of `DocItem` nodes, and the `Rung` on a node is what `trellis-context` packs at when the
budget is tight.

`TreeDiagnosis` reports trees that parsed without error and still say nothing useful — a
27,000-character single node is valid and useless, so parsing cleanly is not the same as parsing
well.
