# Multi-Collection RAG System Design

## Overview

This document describes the multi-collection architecture for the Egeria Advisor RAG system, enabling intelligent routing of queries across multiple specialized Milvus collections.

## Architecture

### Collections

#### Phase 1: Python Collections (3)
1. **`pyegeria`** - Core PyEgeria library
   - **Source**: https://github.com/odpi/egeria-python.git
   - **Paths**: `/pyegeria`, `/tests`
   - **Content**: Python client library, REST API wrappers, async operations
   - **Domain Terms**: pyegeria, python-client, rest-client, async-client, widget

2. **`pyegeria_cli`** - hey_egeria CLI
   - **Source**: https://github.com/odpi/egeria-python.git
   - **Paths**: `/commands`
   - **Content**: CLI commands, command-line tools
   - **Domain Terms**: hey-egeria, cli, command, commands

3. **`pyegeria_drE`** - Dr. Egeria
   - **Source**: https://github.com/odpi/egeria-python.git
   - **Paths**: `/drE` (markdown translator)
   - **Content**: Markdown-to-pyegeria translator
   - **Domain Terms**: dr-egeria, markdown, document-automation

#### Phase 2: Java + Docs + Workspaces (3)
4. **`egeria_java`** - Egeria Java codebase
   - **Source**: https://github.com/odpi/egeria.git
   - **Content**: Java services, OMAS, OMAG, OMRS
   - **Domain Terms**: java, omas, omag, omrs, ocf, oif, access-service

5. **`egeria_docs`** - Egeria documentation
   - **Source**: https://github.com/odpi/egeria-docs.git
   - **Content**: Guides, tutorials, concepts, reference docs
   - **Domain Terms**: documentation, guide, tutorial, concept

6. **`egeria_workspaces`** - Deployment & examples
   - **Source**: https://github.com/odpi/egeria-workspaces.git
   - **Content**: Jupyter notebooks, deployment configs, examples
   - **Domain Terms**: workspace, notebook, jupyter, example, deployment

## Intelligent Query Routing

### Routing Strategy

The system uses domain terms from `query_patterns.py` to intelligently route queries to the most relevant collection(s):

```python
# Example routing logic
if "pyegeria" in query_terms or "python-client" in query_terms:
    collections = ["pyegeria"]
elif "hey-egeria" in query_terms or "cli" in query_terms:
    collections = ["pyegeria_cli"]
elif "dr-egeria" in query_terms or "markdown" in query_terms:
    collections = ["pyegeria_drE"]
elif "java" in query_terms or "omas" in query_terms:
    collections = ["egeria_java"]
elif "notebook" in query_terms or "jupyter" in query_terms:
    collections = ["egeria_workspaces"]
elif "documentation" in query_terms or "guide" in query_terms:
    collections = ["egeria_docs"]
else:
    # Default: search Python collections first, then docs
    collections = ["pyegeria", "egeria_docs"]
```

### Multi-Collection Search

For queries that span multiple domains:
1. Route to primary collection(s) based on domain terms
2. If results < threshold, expand to related collections
3. Merge results and re-rank by relevance score
4. Return top-k results across all collections

### Collection Relationships

```
pyegeria (core)
├── pyegeria_cli (uses pyegeria)
└── pyegeria_drE (uses pyegeria)

egeria_java (core)
├── egeria_docs (documents Java)
└── egeria_workspaces (uses Java + Python)
```

## Configuration Structure

### Collection Metadata

Each collection has metadata defining:
- **name**: Collection identifier
- **source_repo**: Git repository URL
- **source_paths**: Paths within repo to index
- **content_type**: code, documentation, examples
- **language**: python, java, markdown, mixed
- **domain_terms**: Terms that route queries to this collection
- **related_collections**: Collections to search if primary results insufficient

### Example Configuration

```yaml
collections:
  pyegeria:
    name: "pyegeria"
    source_repo: "https://github.com/odpi/egeria-python.git"
    source_paths:
      - "/pyegeria"
      - "/tests"
    content_type: "code"
    language: "python"
    domain_terms:
      - "pyegeria"
      - "python-client"
      - "rest-client"
      - "async-client"
      - "widget"
    related_collections:
      - "pyegeria_cli"
      - "pyegeria_drE"
      - "egeria_docs"
    
  pyegeria_cli:
    name: "pyegeria_cli"
    source_repo: "https://github.com/odpi/egeria-python.git"
    source_paths:
      - "/commands"
    content_type: "code"
    language: "python"
    domain_terms:
      - "hey-egeria"
      - "cli"
      - "command"
      - "commands"
    related_collections:
      - "pyegeria"
      - "egeria_docs"
```

## Directory Structure

```
egeria-advisor/
├── advisor/
│   ├── collection_router.py      # NEW: Intelligent query routing
│   ├── multi_collection_store.py # NEW: Multi-collection vector store
│   ├── collection_config.py      # NEW: Collection metadata
│   ├── query_patterns.py         # EXISTING: Domain term patterns
│   ├── vector_store.py           # UPDATE: Support multiple collections
│   ├── rag_retrieval.py          # UPDATE: Multi-collection search
│   └── config.py                 # UPDATE: Collection configurations
├── data/
│   ├── repos/                    # NEW: Git repositories
│   │   ├── egeria-python/
│   │   ├── egeria/
│   │   ├── egeria-docs/
│   │   └── egeria-workspaces/
│   └── cache/                    # Collection-specific caches
│       ├── pyegeria_stats.json
│       ├── pyegeria_cli_stats.json
│       └── pyegeria_drE_stats.json
└── scripts/
    ├── clone_repos.py            # NEW: Clone all git repos
    ├── ingest_collection.py      # NEW: Ingest single collection
    └── ingest_all.py             # NEW: Ingest all collections
```

## Implementation Phases

### Phase 1: Infrastructure (Current)
- [ ] Create collection configuration system
- [ ] Create collection router with intelligent routing
- [ ] Extend vector_store.py for multi-collection support
- [ ] Update rag_retrieval.py for multi-collection search
- [ ] Create repo cloning scripts
- [ ] Create collection ingestion scripts

### Phase 2: Python Collections
- [ ] Clone egeria-python repo
- [ ] Ingest pyegeria collection
- [ ] Ingest pyegeria_cli collection
- [ ] Ingest pyegeria_drE collection
- [ ] Test Python-specific queries
- [ ] Validate routing logic

### Phase 3: Java + Docs + Workspaces
- [ ] Clone remaining repos
- [ ] Ingest egeria_java collection
- [ ] Ingest egeria_docs collection
- [ ] Ingest egeria_workspaces collection
- [ ] Test cross-domain queries
- [ ] Implement result merging and re-ranking

### Phase 4: Optimization
- [ ] Add collection-specific embeddings strategies
- [ ] Implement caching for frequent queries
- [ ] Add monitoring and metrics
- [ ] Performance tuning

### Phase 5: Automation (Future)
- [ ] Create Airflow DAGs for each collection
- [ ] Implement incremental updates
- [ ] Add change detection
- [ ] Set up automated testing

## Benefits

### Precision
- Queries target specific collections based on domain
- Reduces irrelevant results from unrelated codebases
- Faster searches due to smaller collection sizes

### Maintainability
- Independent updates per collection
- Clear separation of concerns
- Easy to add new repositories

### Scalability
- Add new collections without affecting existing ones
- Parallel ingestion and updates
- Collection-specific optimization

### Performance
- Smaller collections = faster queries
- Targeted searches reduce vector comparisons
- Efficient resource utilization

## Query Examples

### Python-Specific Queries
```
"How do I use pyegeria widgets?"
→ Routes to: pyegeria

"What hey_egeria commands are available?"
→ Routes to: pyegeria_cli

"How does Dr. Egeria translate markdown?"
→ Routes to: pyegeria_drE
```

### Cross-Domain Queries
```
"How do I connect pyegeria to an Egeria server?"
→ Routes to: pyegeria, egeria_docs

"Show me examples of using OMAS with Python"
→ Routes to: pyegeria, egeria_java, egeria_workspaces
```

### Documentation Queries
```
"What is a glossary in Egeria?"
→ Routes to: egeria_docs

"Show me Egeria deployment examples"
→ Routes to: egeria_workspaces, egeria_docs
```

## Future Enhancements

1. **Semantic Routing**: Use embeddings to determine collection relevance
2. **Query Expansion**: Automatically expand queries to related collections
3. **Result Fusion**: Advanced merging strategies (reciprocal rank fusion)
4. **Collection Weighting**: Prioritize collections based on query type
5. **Feedback Loop**: Learn from user interactions to improve routing
6. **Multi-Language Support**: Handle queries in different languages
7. **Version Management**: Support multiple versions of each collection
8. **A/B Testing**: Compare routing strategies

## Monitoring & Metrics

Track per collection:
- Query volume
- Average response time
- Result relevance scores
- Cache hit rates
- Index size and growth
- Update frequency

## Conclusion

This multi-collection architecture provides a scalable, maintainable, and high-performance foundation for the Egeria Advisor RAG system. The intelligent routing ensures users get precise, relevant results while maintaining system efficiency.