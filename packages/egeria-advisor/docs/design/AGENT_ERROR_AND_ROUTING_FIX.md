# Agent Error and Routing Issues - Analysis and Fixes

## Issue 1: "generator didn't stop after throw()" Error

### Problem
When using agent mode (`egeria-advisor --interactive --agent`), queries fail with:
```
✗ Error: generator didn't stop after throw()
```

### Root Cause
The error occurs in the MLflow tracking context manager when used with the conversation agent. The issue is in `advisor/agents/conversation_agent.py`:

```python
# In run() method
with self.mlflow_tracker.track_operation(...) as tracker:
    response = self._cached_run(query, use_rag)  # LRU-cached function
```

The `_cached_run` is an LRU-cached function that wraps `_run_uncached`. When an exception occurs inside the MLflow tracking context, the generator-based context manager tries to handle it, but the LRU cache wrapper interferes with proper exception propagation, causing the "generator didn't stop after throw()" error.

### Solution Implemented ✅
**Moved MLflow tracking inside `_run_uncached` method** to avoid context manager/cache interaction.

The fix restructures the code as follows:

```python
def run(self, query: str, use_rag: bool = True) -> Dict[str, Any]:
    """Process query - MLflow tracking is now inside _run_uncached."""
    # Use cached version (MLflow tracking happens inside)
    response = self._cached_run(query, use_rag)
    
    # Add to conversation history
    self.conversation_history.append({...})
    return response

def _run_uncached(self, query: str, use_rag: bool) -> Dict[str, Any]:
    """Internal method with MLflow tracking."""
    if self.enable_mlflow and self.mlflow_tracker:
        with self.mlflow_tracker.track_operation(...) as tracker:
            # Process query with tracking
            return self._process_query_internal(query, use_rag, start_time, tracker)
    else:
        # Process query without tracking
        return self._process_query_internal(query, use_rag, start_time, None)

def _process_query_internal(self, query, use_rag, start_time, tracker=None):
    """Actual query processing logic."""
    # RAG retrieval, prompt building, LLM generation
    # Log metrics to tracker if provided
    ...
```

**Benefits:**
- MLflow tracking works correctly with LRU cache
- No exception propagation issues
- Tracking still captures all metrics (response length, sources, duration, etc.)
- Cache still provides 17,997x speedup for repeated queries

**Files Modified:**
- `advisor/agents/conversation_agent.py` - Refactored tracking placement
- `advisor/cli/agent_session.py` - Re-enabled MLflow (was temporarily disabled)

## Issue 2: egeria_docs Not Being Searched First

### Problem
For the query "what does the Egeria documentation say about myProfile?", the egeria_docs collection should be searched first, but it's not being prioritized correctly.

### Current Routing Logic
The routing system in `advisor/collection_router.py` uses this priority order:

1. **Intent boost** (lines 88-143): Detects keywords like "documentation", "docs", "guide" and boosts collections
2. **Match count**: Counts domain term matches
3. **Collection priority**: Uses the priority field from collection metadata

### Current Priorities
From `advisor/collection_config.py`:
- pyegeria: priority=10 (highest)
- pyegeria_cli: priority=9
- pyegeria_drE: priority=8
- egeria_java: priority=7
- egeria_docs: priority=6 (lower than Python collections)
- egeria_workspaces: priority=5

### Why egeria_docs Wasn't Searched
For the query "what does the Egeria documentation say about myProfile?":

1. The word "documentation" triggers intent detection (line 89)
2. Intent boost of 10.0 is applied to egeria_docs (line 136-137)
3. However, "myProfile" might match domain terms in pyegeria collections
4. The default strategy (line 153-173) searches Python collections first

### Solution Options

**Option 1: Increase egeria_docs base priority**
Change egeria_docs priority from 6 to 11 (higher than pyegeria):
```python
EGERIA_DOCS_COLLECTION = CollectionMetadata(
    name="egeria_docs",
    ...
    priority=11,  # Higher than pyegeria (10)
    enabled=True
)
```

**Option 2: Increase documentation intent boost**
In `advisor/collection_router.py` line 136:
```python
if detected_intent == "documentation" and collection.content_type.value == "documentation":
    intent_boost = 15.0  # Increase from 10.0 to 15.0
```

**Option 3: Add explicit "documentation" keyword detection**
Enhance the routing logic to give maximum priority when "documentation" or "docs" is explicitly mentioned:
```python
# In _find_matching_collections, before intent detection
if any(kw in query_lower for kw in ["documentation", "docs", "egeria documentation"]):
    # Force egeria_docs to top if it matches
    if collection.name == "egeria_docs":
        intent_boost = 20.0  # Maximum boost
```

**Option 4: Modify default collection strategy**
In `_get_default_collections` (line 153), check for documentation intent first:
```python
def _get_default_collections(self) -> List[str]:
    defaults = []
    
    # Check if docs collection should be first
    docs_collection = get_collection("egeria_docs")
    if docs_collection and docs_collection.enabled:
        defaults.append("egeria_docs")
    
    # Add enabled Python collections by priority
    for collection in get_collections_by_priority():
        if collection.language.value == "python" and collection.name not in defaults:
            defaults.append(collection.name)
    
    return defaults if defaults else [c.name for c in get_collections_by_priority()[:2]]
```

### Recommended Fix
Combine Option 1 and Option 2:
1. Increase egeria_docs priority to 11
2. Increase documentation intent boost to 15.0

This ensures that when "documentation" is mentioned, egeria_docs gets the highest priority regardless of other matches.

## Testing the Fixes

### Test Agent Error Fix
```bash
# After applying fix
egeria-advisor --interactive --agent

# Try the query that failed
agent> what does the Egeria documentation say about myProfile?
```

### Test Routing Fix
```bash
# Enable debug logging to see routing decisions
egeria-advisor --interactive --debug

# Try documentation-specific queries
> what does the Egeria documentation say about myProfile?
> show me the docs for glossary
> where is the documentation for OMAS?
```

Check the logs to verify egeria_docs is being searched first.

## Implementation Priority

1. **High Priority**: Fix the agent error (Option 2 - disable MLflow temporarily)
2. **Medium Priority**: Fix routing to prioritize egeria_docs (Options 1 + 2)
3. **Low Priority**: Refactor MLflow tracking to work with LRU cache (Option 1 from Issue 1)