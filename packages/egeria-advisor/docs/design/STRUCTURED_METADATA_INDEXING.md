# Structured Metadata Indexing Design

## Overview

This document describes the design for adding structured metadata indexing to all Egeria Advisor collections. Currently, collections only store basic metadata (file_path, chunk_index), which limits query precision and requires relying solely on semantic similarity scores.

## Problem Statement

### Current State
All collections (pyegeria, cli_commands, egeria_java) have minimal metadata:
```python
{
    "file_path": "/path/to/file.py",
    "collection": "pyegeria",
    "chunk_index": 0,
    "total_chunks": 29
}
```

### Issues
1. **Poor Query Routing**: Queries like "what methods does ProjectManager have?" get low similarity scores (0.30) because class names aren't indexed
2. **No Direct Lookups**: Can't filter by class name, method name, or command name
3. **Slow Searches**: Must rely on semantic search for everything
4. **Inaccurate Results**: Similar-sounding but unrelated items may rank higher than exact matches

## Solution: Structured Metadata Schema

### 1. PyEgeria Collection

**Metadata Fields:**
```python
{
    # Existing fields
    "file_path": str,           # Path to source file
    "collection": str,          # "pyegeria"
    "chunk_index": int,         # Chunk number
    "total_chunks": int,        # Total chunks in file
    
    # NEW: Code structure metadata
    "element_type": str,        # "class", "method", "function", "module", "property"
    "class_name": str,          # e.g., "ProjectManager", "GlossaryManager"
    "method_name": str,         # e.g., "create_project", "get_glossary"
    "parent_class": str,        # For methods: parent class name
    "signature": str,           # Full method signature with parameters
    "parameters": List[str],    # List of parameter names
    "return_type": str,         # Return type annotation
    "is_async": bool,           # Whether method is async
    "is_private": bool,         # Whether element is private (_name)
    "decorators": List[str],    # List of decorators
    "docstring": str,           # Docstring text (for semantic search)
    "module_path": str,         # e.g., "pyegeria.admin_services"
}
```

**Example:**
```python
{
    "file_path": "/repos/egeria-python/pyegeria/project_manager.py",
    "collection": "pyegeria",
    "chunk_index": 5,
    "total_chunks": 20,
    "element_type": "method",
    "class_name": "ProjectManager",
    "method_name": "create_project",
    "parent_class": "ProjectManager",
    "signature": "create_project(self, project_name: str, description: str = None) -> dict",
    "parameters": ["self", "project_name", "description"],
    "return_type": "dict",
    "is_async": False,
    "is_private": False,
    "decorators": [],
    "docstring": "Create a new project in Egeria...",
    "module_path": "pyegeria.project_manager"
}
```

### 2. CLI Commands Collection

**Metadata Fields:**
```python
{
    # Existing fields
    "file_path": str,
    "collection": str,
    "chunk_index": int,
    "total_chunks": int,
    
    # NEW: Command structure metadata
    "command_type": str,        # "main", "subcommand", "option", "flag"
    "command_name": str,        # "hey_egeria", "dr_egeria"
    "subcommand": str,          # "platform", "server", "glossary", etc.
    "full_command": str,        # "hey_egeria platform status"
    "options": List[str],       # ["--url", "--user", "--password"]
    "flags": List[str],         # ["--verbose", "--json", "--help"]
    "required_options": List[str],  # Options that are required
    "description": str,         # Command description
    "examples": List[str],      # Usage examples
    "aliases": List[str],       # Alternative command names
}
```

**Example:**
```python
{
    "file_path": "/repos/egeria-python/pyegeria/commands/hey_egeria.py",
    "collection": "cli_commands",
    "chunk_index": 0,
    "total_chunks": 1,
    "command_type": "subcommand",
    "command_name": "hey_egeria",
    "subcommand": "platform",
    "full_command": "hey_egeria platform status",
    "options": ["--url", "--timeout"],
    "flags": ["--verbose", "--json"],
    "required_options": ["--url"],
    "description": "Check platform status",
    "examples": [
        "hey_egeria platform status --url https://localhost:9443",
        "hey_egeria platform status --url https://localhost:9443 --json"
    ],
    "aliases": []
}
```

### 3. Egeria Java Collection

**Metadata Fields:**
```python
{
    # Existing fields
    "file_path": str,
    "collection": str,
    "chunk_index": int,
    "total_chunks": int,
    
    # NEW: Java code structure metadata
    "element_type": str,        # "class", "interface", "enum", "method", "field"
    "class_name": str,          # e.g., "AssetOwner", "GlossaryManager"
    "method_name": str,         # e.g., "createAsset", "getGlossary"
    "parent_class": str,        # For methods: parent class
    "package": str,             # e.g., "org.odpi.openmetadata.accessservices.assetowner"
    "signature": str,           # Full method signature
    "parameters": List[str],    # Parameter types and names
    "return_type": str,         # Return type
    "modifiers": List[str],     # ["public", "static", "final"]
    "annotations": List[str],   # ["@Override", "@Deprecated"]
    "javadoc": str,             # Javadoc text
    "implements": List[str],    # Interfaces implemented
    "extends": str,             # Parent class
}
```

**Example:**
```python
{
    "file_path": "/repos/egeria/open-metadata-implementation/.../AssetOwner.java",
    "collection": "egeria_java",
    "chunk_index": 3,
    "total_chunks": 15,
    "element_type": "method",
    "class_name": "AssetOwner",
    "method_name": "createAsset",
    "parent_class": "AssetOwner",
    "package": "org.odpi.openmetadata.accessservices.assetowner",
    "signature": "public String createAsset(String userId, AssetProperties properties)",
    "parameters": ["String userId", "AssetProperties properties"],
    "return_type": "String",
    "modifiers": ["public"],
    "annotations": [],
    "javadoc": "Create a new asset in the metadata repository...",
    "implements": [],
    "extends": "AssetOwnerBase"
}
```

## Implementation Plan

### Phase 1: Update Data Extraction (Week 1)

#### 1.1 Enhance Code Parser
**File:** `advisor/data_prep/code_parser.py`

- Update `CodeElement` dataclass to include all new fields
- Enhance AST parsing to extract:
  - Method signatures with full parameter info
  - Decorators and annotations
  - Module paths
  - Return type annotations
- Add Java parser using `javalang` library
- Add CLI command parser using regex/AST

#### 1.2 Create Specialized Extractors
**New Files:**
- `advisor/data_prep/python_extractor.py` - Enhanced Python code extraction
- `advisor/data_prep/java_extractor.py` - Java code extraction
- `advisor/data_prep/cli_extractor.py` - CLI command extraction

### Phase 2: Update Ingestion Pipeline (Week 1-2)

#### 2.1 Modify Vector Store Schema
**File:** `advisor/vector_store.py`

- Update `create_collection()` to support additional metadata fields
- Ensure Milvus schema includes all new fields as VARCHAR or JSON
- Add metadata field validation

#### 2.2 Update Ingestion Logic
**File:** `advisor/ingest_to_milvus.py`

- Modify `ingest_code_elements()` to extract and store new metadata
- Update chunking logic to preserve metadata across chunks
- Add metadata validation before insertion

#### 2.3 Create Collection-Specific Ingesters
**New Files:**
- `scripts/ingest_pyegeria_with_metadata.py`
- `scripts/ingest_cli_commands_with_metadata.py`
- `scripts/ingest_java_with_metadata.py`

### Phase 3: Update Query Logic (Week 2)

#### 3.1 Add Metadata Filtering
**Files:** `advisor/agents/pyegeria_agent.py`, `advisor/agents/cli_command_agent.py`

- Add filter-based searches: `filter={"class_name": "ProjectManager"}`
- Combine semantic search with metadata filtering
- Implement two-stage search:
  1. Exact metadata match (if available)
  2. Semantic search fallback

#### 3.2 Update Query Detection
- Use metadata for faster query classification
- Check if class/method exists before semantic search
- Improve confidence scores based on metadata matches

### Phase 4: Re-ingestion (Week 2)

#### 4.1 Backup Current Collections
```bash
# Export current collections
python scripts/export_collection.py --collection pyegeria --output backup/
python scripts/export_collection.py --collection cli_commands --output backup/
python scripts/export_collection.py --collection egeria_java --output backup/
```

#### 4.2 Re-ingest with Metadata
```bash
# Drop and recreate with new schema
python scripts/ingest_pyegeria_with_metadata.py --drop-existing
python scripts/ingest_cli_commands_with_metadata.py --drop-existing
python scripts/ingest_java_with_metadata.py --drop-existing
```

#### 4.3 Validate Results
- Check metadata completeness
- Verify search accuracy improvements
- Compare query routing before/after

## Expected Benefits

### 1. Improved Query Routing
- **Before:** "what methods does ProjectManager have?" → score 0.30 (borderline)
- **After:** Direct lookup via `filter={"class_name": "ProjectManager"}` → instant, accurate

### 2. Faster Searches
- Metadata filtering is O(1) vs semantic search O(n)
- Can skip embedding generation for exact matches
- Reduce vector search space with filters

### 3. Better Agent Accuracy
- CLI Agent: Direct command name matching
- PyEgeria Agent: Exact class/method lookups
- Java Agent: Package and class filtering

### 4. Enhanced User Experience
- More accurate results
- Faster response times
- Better handling of specific queries

## Testing Strategy

### Unit Tests
- Test metadata extraction for each language
- Validate schema compliance
- Test filter queries

### Integration Tests
- End-to-end ingestion with metadata
- Query routing with metadata filters
- Agent responses with metadata-enhanced search

### Performance Tests
- Compare search times before/after
- Measure query routing accuracy
- Benchmark metadata filtering vs semantic search

## Rollback Plan

If issues arise:
1. Restore from backup collections
2. Revert to previous ingestion scripts
3. Keep new code but disable metadata filtering
4. Gradual rollout: one collection at a time

## Success Metrics

- **Query Routing Accuracy:** >95% (up from ~85%)
- **Search Speed:** <100ms for metadata-filtered queries
- **Agent Confidence:** Average >0.8 (up from ~0.6)
- **User Satisfaction:** Measured via feedback system

## Timeline

- **Week 1:** Phase 1-2 (Extraction + Ingestion updates)
- **Week 2:** Phase 3-4 (Query logic + Re-ingestion)
- **Week 3:** Testing and validation
- **Week 4:** Production deployment and monitoring

## Dependencies

### Python Libraries
- `javalang` - Java code parsing
- `tree-sitter` - Alternative parser (optional)
- `pygments` - Syntax highlighting and parsing

### Infrastructure
- Milvus 2.6+ with JSON field support
- Sufficient storage for expanded metadata (~2x current size)

## Future Enhancements

1. **Semantic Metadata Search:** Embed metadata fields for fuzzy matching
2. **Relationship Graphs:** Link classes, methods, and commands
3. **Version Tracking:** Track metadata changes over time
4. **Auto-completion:** Use metadata for IDE-like suggestions
5. **API Documentation:** Generate API docs from metadata

## References

- [Milvus Metadata Filtering](https://milvus.io/docs/boolean.md)
- [Python AST Documentation](https://docs.python.org/3/library/ast.html)
- [Javalang Library](https://github.com/c2nes/javalang)