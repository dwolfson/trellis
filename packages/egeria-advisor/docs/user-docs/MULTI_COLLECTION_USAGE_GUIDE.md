# Multi-Collection Usage Guide

**This document is superseded.** It described an early 6-collection Milvus architecture
(`egeria_docs`, `egeria_glossary`, `egeria_samples`) that no longer exists — even several of
the collection *names* and *purposes* described here are wrong (e.g. `pyegeria_drE` was never
a "data retrieval engine"; it's the Dr. Egeria markdown translator).

The current system runs 9 pgvector collections (~92,400 entities). See:

- **[Collection Maintenance Guide](COLLECTION_MAINTENANCE_GUIDE.md)** — current collection
  definitions, RAG parameters, and design rationale
- **[Query Routing Guide](QUERY_ROUTING_GUIDE.md)** — how queries are routed to collections
