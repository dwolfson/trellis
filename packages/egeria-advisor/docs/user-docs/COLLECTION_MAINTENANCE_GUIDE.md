# Collection Maintenance Guide

Guide for understanding, maintaining, and updating the Egeria Advisor vector collections.

---

## Collection overview

Egeria Advisor indexes content from four upstream Git repositories into nine pgvector collections (~92,400 entities total). Each collection targets a distinct content type and is tuned accordingly — chunk size, overlap, similarity threshold, and result count all vary based on the nature of the material.

The authoritative definitions live in `advisor/collection_config.py`. This guide explains the design choices documented there.

---

## Collection definitions and RAG parameters

### Parameter rationale by content type

Before the per-collection table, here is why each parameter class differs:

**Chunk size** controls how much text is stored per vector. Smaller chunks suit code (functions are natural, self-contained units) while larger chunks suit narrative content where ideas span multiple paragraphs.

**Chunk overlap** carries context across chunk boundaries. Code needs moderate overlap to keep class/method context. Self-contained template files need none.

**Min score** sets the similarity floor for retrieval. Precise, well-defined content (concept definitions, type schemas) warrants a higher threshold; fuzzy intent matching (templates, tutorials) benefits from a lower one.

**Top k** controls how many chunks are retrieved. Code queries benefit from more examples; precise concept or template queries need fewer but higher-quality results.

### Collection matrix

| Collection | Content | Source paths | Chunk | Overlap | Min score | Top k | Priority |
|---|---|---|---|---|---|---|---|
| `pyegeria` | Python SDK code and tests | `pyegeria/`, `tests/` | 512 | 100 | 0.35 | 10 | 10 |
| `pyegeria_cli` | `hey_egeria` CLI command handlers | `commands/` | 512 | 100 | 0.35 | 10 | 9 |
| `pyegeria_drE` | Dr. Egeria markdown processing code | `md_processing/`, `docs/` | 512 | 100 | 0.35 | 8 | 8 |
| `egeria_java` | Egeria core Java (OMAS, OMAG, OMRS) | `.` (full repo) | 768 | 150 | 0.35 | 8 | 7 |
| `egeria_concepts` | Core concept definitions (short) | `site/docs/concepts/` | 768 | 150 | 0.45 | 5 | 12 |
| `egeria_types` | Type system and schema definitions | `site/docs/types/` | 1024 | 200 | 0.42 | 6 | 11 |
| `egeria_general` | Tutorials, guides, how-tos | `site/docs/` (excl. concepts/types) | 1536 | 300 | 0.38 | 8 | 9 |
| `egeria_workspaces` | Jupyter notebooks, deployment examples | `.` (full repo) | 1536 | 300 | 0.38 | 6 | 5 |
| `egeria_templates` | Dr. Egeria markdown command templates | `sample-data/templates/` | 2048 | 0 | 0.30 | 5 | 12 |

`egeria_docs` exists in the registry but is **disabled** — it was split into `egeria_concepts`, `egeria_types`, and `egeria_general`.

### Per-collection design notes

**`pyegeria`, `pyegeria_cli`, `pyegeria_drE`** — Python code collections

- 512-token chunks capture a complete function with its docstring.
- 100-token overlap keeps class context visible at chunk boundaries.
- min\_score 0.35 is appropriate for code: semantic similarity is more precise than for prose.
- top\_k 10 gives the LLM multiple examples to synthesise from.

**`egeria_java`** — Java code

- Java methods are more verbose than Python; 768-token chunks are needed to capture a complete method.
- Otherwise follows the same logic as the Python collections.

**`egeria_concepts`** — Short concept definitions

- The source documents are short (one concept per file) and highly precise.
- min\_score 0.45 is the highest threshold in the system — a concept definition that doesn't clearly match the query is noise.
- top\_k 5 is conservative; retrieving too many concept snippets makes answers verbose without adding value.
- priority 12 (highest) so that "what is X?" queries pull from here before any other collection.

**`egeria_types`** — Type system definitions

- Type definitions are longer than concept definitions (full attribute tables, relationship lists) so chunk size is 1024.
- min\_score 0.42 is high but slightly lower than concepts — type queries are often more exploratory.

**`egeria_general`** — Tutorials and guides

- Tutorial steps and guide sections need large chunks (1536) to stay coherent; a step split mid-instruction loses meaning.
- 300-token overlap preserves the narrative thread across chunk boundaries.
- min\_score 0.38 and top\_k 8 cast a moderately wide net — general queries are inherently broader.

**`egeria_workspaces`** — Jupyter notebooks and deployment examples

- Same chunking logic as `egeria_general` because the dominant content is narrative example code.
- top\_k 6 (not 8) — complete notebook examples are longer, so fewer chunks avoid exceeding the LLM context window.
- priority 5 (lowest) — workspace content is secondary to docs and code for most queries.

**`egeria_templates`** — Dr. Egeria markdown command templates

- Each template file is a single, self-contained Dr. Egeria command. Splitting across files would make templates useless.
- chunk\_size 2048 keeps an entire template in one chunk. chunk\_overlap 0 — there is nothing to overlap.
- min\_score 0.30 is the lowest in the system. Template retrieval is intent-matching (the user says "create a project" and we need to find the `Create Project` template), which is inherently fuzzier than concept or code retrieval.
- priority 12 (tied highest) — template queries should resolve here before hitting general docs.

---

## Upstream repositories

| Repository | Collections indexed |
|---|---|
| `https://github.com/odpi/egeria-python.git` | `pyegeria`, `pyegeria_cli`, `pyegeria_drE`, `egeria_templates` |
| `https://github.com/odpi/egeria.git` | `egeria_java` |
| `https://github.com/odpi/egeria-docs.git` | `egeria_concepts`, `egeria_types`, `egeria_general` |
| `https://github.com/odpi/egeria-workspaces.git` | `egeria_workspaces` |

Local clones are expected under `data/repos/` by the ingestion scripts. The pgvector backend runs at `localhost:5442` (database `egeria_advisor`).

---

## Checking collection status

```bash
# Count vectors per collection
python scripts/count_vectors.py

# Run the quick E2E health check
python scripts/test_end_to_end.py --categories environment,config,vector_store

# Admin dashboard (web UI must be running)
open http://localhost:8880/admin
```

---

## Re-ingesting a collection

Use the incremental indexer to refresh a single collection without touching the others:

```bash

# Re-index one collection (drops and rebuilds)
uv run --package egeria-advisor python -m advisor.incremental_indexer --collection pyegeria

# Common targets
uv run --package egeria-advisor python -m advisor.incremental_indexer --collection egeria_concepts
uv run --package egeria-advisor python -m advisor.incremental_indexer --collection egeria_templates
```

To re-index all collections from scratch, from a guaranteed-consistent snapshot of every
upstream repo:

```bash
scripts/full_reset.sh --yes
```

See [Repo Update Guide](REPO_UPDATE_GUIDE.md#full-reset) for what this does. For a lighter
touch that doesn't delete and re-clone existing checkouts:

```bash
# 1. Update upstream repos in place
python scripts/clone_repos.py --phase all --update

# 2. Re-ingest all collections
python scripts/ingest_collections.py --phase all --force
```

---

## Adding a new collection

1. Define a `CollectionMetadata` instance in `advisor/collection_config.py`. Choose parameters using the rationale above.
2. Add it to `ALL_COLLECTIONS` in the same file.
3. Add domain terms to `config/routing.yaml` under `collection_domain_terms` so the `CollectionRouter` can select it.
4. Run `uv run --package egeria-advisor python -m advisor.incremental_indexer --collection <new_name>` to populate it.
5. Verify with `python scripts/count_vectors.py` and a test query via the Web UI.

---

## Modifying RAG parameters

Collection-level parameters (`chunk_size`, `chunk_overlap`, `min_score`, `default_top_k`) are set in `advisor/collection_config.py`. The global fallback values are in `config/advisor.yaml` under `rag:`.

After changing parameters, the collection must be re-ingested — the chunk size and overlap affect how documents are split at index time, not just at query time.

---

## Enabling and disabling collections

Set `enabled: True/False` on the `CollectionMetadata` instance in `advisor/collection_config.py`. The `CollectionRouter` will ignore disabled collections without any other configuration change. Restart the web UI after modifying this file.

---

## See also

- `advisor/collection_config.py` — authoritative collection definitions
- `config/routing.yaml` — domain terms and routing patterns per collection
- `docs/user-docs/RAG_TUNING_GUIDE.md` — troubleshooting poor answer quality
- `docs/user-docs/QUERY_ROUTING_GUIDE.md` — how queries are routed to collections
