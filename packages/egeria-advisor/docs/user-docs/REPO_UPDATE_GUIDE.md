# Repository Update and Incremental Indexing Guide

This guide explains how to update cloned repositories and incrementally update the pgvector store with new or modified content.

## Full reset

If the downloaded repos under `data/repos/`, the pgvector store, and `config/advisor.yaml`
have drifted out of sync with each other — e.g. a repo directory was deleted after
ingestion, or only some collections were re-ingested after a repo update — the fastest
way back to a known-good state is a full reset:

```bash
scripts/full_reset.sh          # prompts for confirmation
scripts/full_reset.sh --yes    # skip confirmation (for automation)
```

This deletes and re-clones all 4 source repos (`egeria-python`, `egeria`, `egeria-docs`,
`egeria-workspaces`), then force re-ingests every enabled collection from that single
consistent snapshot, then prints row counts per collection to verify. It does not touch
MLflow runs, query cache, or feedback data. Expect this to take a while — `egeria`'s Java
monorepo is the largest checkout, and every collection's embeddings are regenerated from
scratch.

Use the incremental workflow below for routine day-to-day updates; use the full reset when
you suspect drift or want a guaranteed-consistent baseline.

## Quick Reference

```bash
# 1. Update repositories from GitHub
./scripts/update_repos.sh

# 2. Check what would be ingested (dry run)
python scripts/ingest_collections.py --dry-run --phase all

# 3. Incremental update (changed files only)
python -m advisor.incremental_indexer --collection pyegeria

# 4. Force full re-ingest of a specific collection
python scripts/ingest_collections.py --collection pyegeria --force

# 5. Ingest all collections
python scripts/ingest_collections.py --phase all --force

# 6. Count vectors per collection
python scripts/count_vectors.py
```

## Setup: Vector Store

Egeria Advisor uses **pgvector** (PostgreSQL with the pgvector extension) as its vector store.

Required services (must be running before indexing):
- **pgvector** at `localhost:5442` — database: `egeria_advisor`, user: `egeria_advisor`
- **Ollama** at `localhost:11434` — for LLM inference

Configuration is in `config/advisor.yaml` under the `pgvector` key.

## Step-by-Step Guide

### 1. Initial Repository Setup

```bash
# Clone all required repositories
python scripts/clone_repos.py

# Creates:
# data/repos/egeria-python/     (pyegeria SDK)
# data/repos/egeria/            (Java core)
# data/repos/egeria-docs/       (documentation)
# data/repos/egeria-workspaces/ (example notebooks)
```

### 2. Update Repositories from GitHub

```bash
cd data/repos/egeria-python && git pull origin main && cd ../../..
cd data/repos/egeria && git pull origin main && cd ../../..
cd data/repos/egeria-docs && git pull origin main && cd ../../..
cd data/repos/egeria-workspaces && git pull origin main && cd ../../..
```

Or use the helper script:

```bash
chmod +x scripts/update_repos.sh
./scripts/update_repos.sh
```

### 3. Incremental Indexing

The incremental indexer compares file modification times and content hashes, updating only changed chunks:

```bash
python -m advisor.incremental_indexer --collection pyegeria
python -m advisor.incremental_indexer --collection pyegeria_drE
```

**When to use incremental vs. full re-ingest:**

| Situation | Command |
|-----------|---------|
| Normal repo update (some files changed) | `python -m advisor.incremental_indexer --collection <name>` |
| Collection config changed (new paths or patterns) | `python scripts/ingest_collections.py --collection <name> --force` |
| First-time setup | `python scripts/ingest_collections.py --phase all --force` |
| Embedding model changed | `python scripts/ingest_collections.py --phase all --force` |

**Note:** If the incremental indexer finishes immediately with no output, the files haven't changed since the last index — use `--force` with `ingest_collections.py` to rebuild.

### 4. Available Collections

| Collection | Content | pgvector table |
|---|---|---|
| `pyegeria` | Python SDK code & tests | `pyegeria` |
| `pyegeria_cli` | hey_egeria CLI commands | `pyegeria_cli` |
| `pyegeria_drE` | Dr. Egeria markdown translator | `pyegeria_dre` |
| `egeria_java` | Core Java library | `egeria_java` |
| `egeria_concepts` | Core concept definitions | `egeria_concepts` |
| `egeria_types` | Type system and schema | `egeria_types` |
| `egeria_general` | Tutorials, guides, how-tos | `egeria_general` |
| `egeria_workspaces` | Jupyter notebooks | `egeria_workspaces` |
| `egeria_templates` | Dr. Egeria command templates | `egeria_templates` |

The pgvector table for `pyegeria_drE` is named `pyegeria_dre` (normalised lowercase). The `_TABLE_NAME_MAP` in `advisor/vector_store_pg.py` handles this mapping.

`egeria_docs` is disabled — its content is split across `egeria_concepts`, `egeria_types`, and `egeria_general`.

### 5. Ingest by Phase

```bash
# Phase 1: Python collections (pyegeria, pyegeria_cli, pyegeria_drE)
python scripts/ingest_collections.py --phase 1 --force

# Phase 2: Java, docs, workspaces
python scripts/ingest_collections.py --phase 2 --force

# All phases
python scripts/ingest_collections.py --phase all --force
```

### 6. Verify Index State

```bash
# Count vectors per collection
python scripts/count_vectors.py

# Terminal dashboard (refreshes every 5 seconds)
python -m advisor.dashboard.terminal_dashboard
```

## How Ingestion Works

1. **Reads configuration** from `advisor/collection_config.py`
2. **Locates source files** based on collection paths and file patterns
3. **Parses code** — extracts classes, functions, methods with metadata
4. **Chunks content** — chunk_size=512, top_k=10, min_score=0.30
5. **Generates embeddings** — 384-dim sentence-transformer (all-MiniLM-L6-v2)
6. **Stores in pgvector** — HNSW index for efficient similarity search

## Troubleshooting

### pgvector connection refused

```bash
# Check the database is running and accessible
psql -h localhost -p 5442 -U egeria_advisor -d egeria_advisor -c "SELECT COUNT(*) FROM information_schema.tables;"
```

Verify connection settings in `config/advisor.yaml`:
```yaml
pgvector:
  host: localhost
  port: 5442
  database: egeria_advisor
  user: egeria_advisor
```

### Embedding model not found

The system uses `sentence-transformers/all-MiniLM-L6-v2`. Pre-download if offline:

```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

### Git pull fails with conflicts

```bash
cd data/repos/egeria-python
git fetch origin
git reset --hard origin/main
cd ../../..
```

## Related Documentation

- [Quick Start Guide](QUICK_START.md)
- Architecture overview: `CLAUDE.md` in the repo root
