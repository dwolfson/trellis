# Phase 3: Re-Ingestion & Validation Execution Guide

**This was a one-time execution runbook for the Phase 3 hallucination-reduction work
(Mar 2026) and has been fully executed** — see `docs/PROJECT_SUMMARY.md`, Phase 7b, for the
outcome (documentation hallucination rate fell from ~80% to ~27% after the `egeria_docs`
split and per-collection parameter tuning). It also referenced Milvus, which the project no
longer uses (pgvector is the active backend).

For current re-ingestion instructions, see:

- **[Repository Update Guide](REPO_UPDATE_GUIDE.md)** — updating repos and re-ingesting collections
- **[Collection Maintenance Guide](COLLECTION_MAINTENANCE_GUIDE.md)** — collection definitions and RAG parameters

The full historical detail of this phase (including the original step-by-step commands) is
preserved for reference in `docs/history/` phase documents and `docs/design/` phase reports.
