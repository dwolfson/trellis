# Exhaustive Query Detection and Implementation

## Overview

The Egeria Advisor now supports **exhaustive queries** that return ALL items (e.g., all methods in a class) instead of just the top-k semantically similar results. This is critical for queries like "list all the methods in ProjectManager" which should return all 45 methods, not just 6-8 relevant ones.

## Problem Statement

### Before
- Query: "list all the methods in ProjectManager"
- Result: Only 6-8 methods (top-k semantic search results)
- Issue: User wants a COMPLETE list, not a relevance-ranked subset

### After
- Query: "list all the methods in ProjectManager"  
- Result: All 45 methods with descriptions
- Method: Direct database query with O(1) metadata filtering

## Detection Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. User Query: "list all the methods in ProjectManager"        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. ConversationAgent.run()                                      │
│    - Checks if query is for PyEgeria                            │
│    - Calls: pyegeria_agent.is_pyegeria_query(query)            │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. PyEgeriaAgent.is_pyegeria_query()                            │
│    - Stage 1: Check explicit indicators (class names, etc.)     │
│    - Stage 2: Do quick vector search (top-3)                    │
│    - Returns: True (score >= 0.25)                              │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. PyEgeriaAgent.answer()                                       │
│    - Classifies query type: 'method'                            │
│    - Calls: is_exhaustive_query(query)                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. PyEgeriaAgent.is_exhaustive_query()                          │
│    - Checks for patterns:                                       │
│      • 'list all', 'list the', 'show all', 'show the'          │
│      • 'get all', 'how many', 'what methods are in'            │
│    - Returns: True                                              │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. Extract Metadata Filters                                     │
│    - Calls: extract_pyegeria_filters(query)                     │
│    - Extracts: class_name = "ProjectManager"                    │
│    - Extracts: element_type = "method"                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. PyEgeriaAgent.get_all_class_methods(class_name)             │
│    - Direct Milvus query: filter by class_name                  │
│    - Post-filter in Python: element_type == 'method'            │
│    - Returns: List of 45 method dictionaries                    │
│    - Time: O(1) metadata lookup (not O(n) semantic search)     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 8. Format Response Directly (Bypass LLM)                        │
│    - Reason: LLM times out with 45+ methods (180s timeout)     │
│    - Creates numbered list in Python:                           │
│      1. **__init__**: ...                                       │
│      2. **_async_add_project_classification**: ...              │
│      ...                                                        │
│      45. **update_project**: ...                                │
│    - Returns formatted markdown directly                        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 9. Return to User                                               │
│    - Complete list of all 45 methods                            │
│    - Each with name and description                             │
│    - Suggestions for follow-up queries                          │
└─────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Detection Patterns (`is_exhaustive_query()`)

Located in: `advisor/agents/pyegeria_agent.py` lines 312-350

```python
exhaustive_indicators = [
    'how many',
    'what methods are in', 'what methods does',
    'list the methods', 'list methods',
    'show the methods', 'show methods',
    'list all', 'show all', 'get all methods',
    'list the', 'show the', 'get all',
    'all methods', 'all functions', 'complete list'
]
```

### 2. Direct Database Query (`get_all_class_methods()`)

Located in: `advisor/agents/pyegeria_agent.py` lines 244-310

**Why Direct Query?**
- Semantic search returns top-k (e.g., 10) most relevant results
- Exhaustive queries need ALL results regardless of relevance
- Direct database query with metadata filters is O(1) vs O(n)

**Implementation:**
```python
# Query by class_name only (Milvus limitation: can't combine filters)
filter_expr = f'class_name == "{class_name}"'
collection = Collection(self.collection_name)
results = collection.query(
    expr=filter_expr,
    output_fields=['method_name', 'element_type', 'metadata'],
    limit=500  # High limit to get all items
)

# Post-filter for methods in Python
method_results = [r for r in results if r.get('element_type') == 'method']
```

### 3. Direct Formatting (Bypass LLM)

Located in: `advisor/agents/pyegeria_agent.py` lines 738-773

**Why Bypass LLM?**
- LLM request with 45 methods (5,113 chars context) times out after 180s
- LLM tends to summarize rather than list all items
- Direct formatting is instant and guaranteed complete

**Implementation:**
```python
method_list = []
for i, m in enumerate(all_methods, 1):
    name = m.get('name', 'unknown')
    doc = m.get('docstring', 'No description')
    if len(doc) > 100:
        doc = doc[:97] + "..."
    method_list.append(f"{i}. **{name}**: {doc}")

answer = f"""# All Methods in {class_name}

Found **{len(all_methods)} methods** in the {class_name} class:

{chr(10).join(method_list)}
"""
```

## Milvus Limitation Workaround

**Problem:** Milvus doesn't support combining multiple scalar field filters:
```python
# This returns 0 results (doesn't work):
filter_expr = 'class_name == "ProjectManager" and element_type == "method"'
```

**Solution:** Filter by one field, post-process in Python:
```python
# Query by class_name only
filter_expr = 'class_name == "ProjectManager"'
results = collection.query(expr=filter_expr, ...)

# Post-filter in Python
methods = [r for r in results if r.get('element_type') == 'method']
```

## Testing

### Test Scripts

1. **`scripts/test_pyegeria_detection.py`**
   - Tests detection logic in isolation
   - Verifies `is_pyegeria_query()` and `is_exhaustive_query()`

2. **`scripts/test_full_agent_flow.py`**
   - Tests complete flow through ConversationAgent
   - Verifies routing and response formatting

### Manual Testing

```bash
# Start CLI in agent mode
egeria-advisor --interactive --agent --track

# Test exhaustive query
agent> list all the methods in ProjectManager

# Expected output:
# Found **45 methods** in the ProjectManager class:
# 1. **__init__**: ...
# 2. **_async_add_project_classification**: ...
# ...
# 45. **update_project**: ...
```

## Performance

### Metrics

| Metric | Semantic Search | Exhaustive Query |
|--------|----------------|------------------|
| Query Time | ~2-3s | ~0.5s |
| Results | Top-10 | All 45 |
| Accuracy | Relevance-based | 100% complete |
| LLM Calls | 1 (may timeout) | 0 (bypassed) |

### Advantages

1. **Faster**: Direct DB query vs semantic search + LLM generation
2. **Complete**: Guaranteed to return ALL items
3. **Reliable**: No LLM timeout issues
4. **Accurate**: No LLM hallucination or summarization

## Code Locations

| Component | File | Lines |
|-----------|------|-------|
| Detection patterns | `advisor/agents/pyegeria_agent.py` | 312-350 |
| Direct DB query | `advisor/agents/pyegeria_agent.py` | 244-310 |
| Direct formatting | `advisor/agents/pyegeria_agent.py` | 738-773 |
| Metadata extraction | `advisor/metadata_filters.py` | 80-110 |
| Routing logic | `advisor/agents/conversation_agent.py` | 176-215 |

## Future Enhancements

1. **Support for other classes**: Currently works for any class, tested with ProjectManager
2. **Support for other element types**: Could extend to list all functions, all classes, etc.
3. **Pagination**: For very large result sets (100+ items)
4. **Caching**: Cache exhaustive query results for faster repeated queries
5. **Java code support**: Extend to Java classes when Phase 3 indexing is complete

## Related Documentation

- [Metadata Filtering](./METADATA_FILTERING.md)
- [PyEgeria Agent Design](./PYEGERIA_AGENT.md)
- [Query Classification](./QUERY_CLASSIFICATION_AND_TRACKING.md)