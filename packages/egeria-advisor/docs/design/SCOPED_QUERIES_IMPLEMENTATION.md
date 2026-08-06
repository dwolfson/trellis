# Scoped Queries Implementation Guide

## Problem Statement

Query: "How many classes are under the Pyegeria folder?"
Current behavior: Returns count for entire codebase
Expected behavior: Returns count only for pyegeria/ directory

## Root Cause

The path extraction works (extracts "pyegeria"), but the analytics module doesn't use it to filter results.

## Solution Architecture

### 1. Data Flow

```
User Query
    ↓
QueryProcessor.extract_path() → "pyegeria"  ✅ WORKING
    ↓
QueryProcessor.process() → returns analysis with path
    ↓
RAGSystem._process_query() → needs to pass path to analytics  ❌ MISSING
    ↓
AnalyticsManager.answer_quantitative_query(query, path_filter)  ❌ MISSING
    ↓
Filter statistics by path → return scoped results  ❌ MISSING
```

### 2. Required Changes

#### Change 1: Update QueryProcessor.process() to include path

**File:** `advisor/query_processor.py`

**Current code (line ~370):**
```python
result = {
    "original_query": query,
    "normalized_query": normalized,
    "query_type": query_type,
    "keywords": keywords,
    "context": context,
    "search_strategy": search_strategy,
    "enhanced_query": self._enhance_query(normalized, keywords)
}
```

**New code:**
```python
# Extract path if present
path_filter = self.extract_path(query)

result = {
    "original_query": query,
    "normalized_query": normalized,
    "query_type": query_type,
    "keywords": keywords,
    "context": context,
    "search_strategy": search_strategy,
    "enhanced_query": self._enhance_query(normalized, keywords),
    "path_filter": path_filter  # NEW
}
```

#### Change 2: Update RAGSystem to pass path to analytics

**File:** `advisor/rag_system.py`

**Current code (line ~104-107):**
```python
if query_analysis['query_type'] == 'quantitative':
    logger.info("Handling quantitative query with analytics module")
    response = self.analytics.answer_quantitative_query(user_query)
    return {
```

**New code:**
```python
if query_analysis['query_type'] == 'quantitative':
    logger.info("Handling quantitative query with analytics module")
    path_filter = query_analysis.get('path_filter')  # NEW
    if path_filter:
        logger.info(f"Applying path filter: {path_filter}")
    response = self.analytics.answer_quantitative_query(user_query, path_filter)  # MODIFIED
    return {
```

#### Change 3: Update AnalyticsManager to support path filtering

**File:** `advisor/analytics.py`

**Step 3a: Add path-filtered statistics methods**

Add after line 102:
```python
def get_total_classes(self, path_filter: Optional[str] = None) -> int:
    """
    Get total number of classes, optionally filtered by path.
    
    Args:
        path_filter: Optional path prefix to filter by (e.g., "pyegeria")
        
    Returns:
        Count of classes
    """
    if path_filter:
        return self._get_filtered_count("class", path_filter)
    return self.stats.get("code", {}).get("by_type", {}).get("class", 0)

def _get_filtered_count(self, element_type: str, path_filter: str) -> int:
    """
    Get count of elements filtered by path.
    
    This requires loading the detailed code elements data and filtering.
    For now, we'll use the vector store to count elements.
    
    Args:
        element_type: Type of element (class, function, method)
        path_filter: Path prefix to filter by
        
    Returns:
        Filtered count
    """
    # Load code elements from cache
    code_elements_file = self.cache_dir / "code_elements.json"
    
    if not code_elements_file.exists():
        logger.warning(f"Code elements file not found: {code_elements_file}")
        return 0
    
    try:
        with open(code_elements_file, 'r') as f:
            elements = json.load(f)
        
        # Normalize path filter
        path_filter = path_filter.lower().strip('/')
        
        # Count matching elements
        count = 0
        for element in elements:
            element_path = element.get('file_path', '').lower()
            element_kind = element.get('kind', '').lower()
            
            # Check if path matches and type matches
            if element_path.startswith(path_filter) and element_kind == element_type:
                count += 1
        
        return count
        
    except Exception as e:
        logger.error(f"Failed to filter elements: {e}")
        return 0
```

**Step 3b: Update answer_quantitative_query signature**

**Current code (line 138):**
```python
def answer_quantitative_query(self, query: str) -> str:
```

**New code:**
```python
def answer_quantitative_query(self, query: str, path_filter: Optional[str] = None) -> str:
    """
    Answer a quantitative query about the codebase.
    
    Args:
        query: User's quantitative question
        path_filter: Optional path to filter results by
        
    Returns:
        Formatted answer with statistics
    """
    query_lower = query.lower()
    
    # Build scope description
    scope = f"the **{path_filter}** directory" if path_filter else "the egeria-python codebase"
    
    # Detect what the user is asking about
    if "how many class" in query_lower:
        count = self.get_total_classes(path_filter)
        return f"There are **{count:,} classes** in {scope}."
    
    elif "how many function" in query_lower:
        count = self.get_total_functions(path_filter)
        return f"There are **{count:,} functions** in {scope}."
    
    # ... update all other methods similarly
```

### 3. Alternative Approach: Pre-compute Directory Statistics

Instead of filtering on-the-fly, we could pre-compute statistics per directory during the data preparation phase.

**Pros:**
- Faster queries (no filtering needed)
- More accurate (uses same extraction logic)
- Can include additional per-directory metrics

**Cons:**
- Requires regenerating statistics
- Larger cache files
- Need to update extraction scripts

**Implementation:**

Create `scripts/generate_directory_stats.py`:
```python
#!/usr/bin/env python3
"""Generate per-directory statistics for scoped queries."""

import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any

def generate_directory_stats(code_elements_file: Path, output_file: Path):
    """Generate statistics grouped by directory."""
    
    with open(code_elements_file, 'r') as f:
        elements = json.load(f)
    
    # Group by directory
    dir_stats = defaultdict(lambda: {
        'classes': 0,
        'functions': 0,
        'methods': 0,
        'files': set(),
        'total_elements': 0
    })
    
    for element in elements:
        file_path = element.get('file_path', '')
        kind = element.get('kind', '')
        
        # Get directory (first path component)
        parts = file_path.split('/')
        if len(parts) > 0:
            directory = parts[0]
            
            dir_stats[directory]['total_elements'] += 1
            dir_stats[directory]['files'].add(file_path)
            
            if kind == 'class':
                dir_stats[directory]['classes'] += 1
            elif kind == 'function':
                dir_stats[directory]['functions'] += 1
            elif kind == 'method':
                dir_stats[directory]['methods'] += 1
    
    # Convert sets to counts
    result = {}
    for directory, stats in dir_stats.items():
        result[directory] = {
            'classes': stats['classes'],
            'functions': stats['functions'],
            'methods': stats['methods'],
            'files': len(stats['files']),
            'total_elements': stats['total_elements']
        }
    
    # Save results
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"Generated directory statistics: {output_file}")
    print(f"Directories analyzed: {len(result)}")

if __name__ == "__main__":
    cache_dir = Path("cache")
    generate_directory_stats(
        cache_dir / "code_elements.json",
        cache_dir / "directory_stats.json"
    )
```

Then update `AnalyticsManager` to load and use these pre-computed stats.

### 4. Recommended Approach

**Use the pre-computed approach** because:
1. Better performance
2. More maintainable
3. Can add more metrics easily
4. Consistent with existing architecture

### 5. Testing Strategy

Create `scripts/test_scoped_queries.py`:
```python
#!/usr/bin/env python3
"""Test scoped query functionality."""

from advisor.rag_system import get_rag_system

def test_scoped_queries():
    rag = get_rag_system()
    
    test_cases = [
        "How many classes are in the pyegeria folder?",
        "Count functions under src/utils",
        "How many methods in the admin module?",
        "Total files in tests directory",
    ]
    
    for query in test_cases:
        print(f"\nQuery: {query}")
        result = rag.query(query)
        print(f"Response: {result['response']}")
        print(f"Path filter: {result.get('path_filter', 'None')}")

if __name__ == "__main__":
    test_scoped_queries()
```

### 6. Implementation Steps

1. ✅ Add path extraction to QueryProcessor (DONE)
2. ⏳ Generate directory statistics script
3. ⏳ Update AnalyticsManager to load directory stats
4. ⏳ Update QueryProcessor.process() to include path
5. ⏳ Update RAGSystem to pass path to analytics
6. ⏳ Update AnalyticsManager.answer_quantitative_query() to use path
7. ⏳ Test scoped queries
8. ⏳ Document new capability

### 7. Expected Results

**Before:**
```
Query: "How many classes are under the Pyegeria folder?"
Response: "There are 156 classes in the egeria-python codebase."
```

**After:**
```
Query: "How many classes are under the Pyegeria folder?"
Response: "There are 42 classes in the pyegeria directory."
```

## Next Session

Start with Step 2: Generate directory statistics script, then proceed through the remaining steps.