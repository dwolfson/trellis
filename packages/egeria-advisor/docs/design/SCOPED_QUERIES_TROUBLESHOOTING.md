# Scoped Queries Troubleshooting Guide

## Issue: Scoped Queries Not Working in CLI

If you're seeing incorrect results when testing scoped queries through the CLI (e.g., "How many classes are under the Pyegeria folder?" returns 196 instead of 191), the implementation is correct but your application needs to reload the updated code.

## Verification

Run the test script to verify the implementation works:

```bash
python scripts/test_scoped_queries.py
```

**Expected output:**
- ✓ All path extraction tests pass
- ✓ Analytics returns 191 classes for pyegeria
- ✓ Analytics returns 196 classes for entire codebase

If these tests pass, the code is working correctly.

## Solutions

### Solution 1: Restart Your Application

If using the CLI:
```bash
# Exit the current CLI session
exit

# Start a new session
egeria-advisor query
```

### Solution 2: Restart Python Process

If using Python directly:
```bash
# Kill any running Python processes
pkill -f "python.*advisor"

# Start fresh
python -m advisor.cli.main
```

### Solution 3: Reload Modules (Interactive Python)

If using IPython or Jupyter:
```python
# Reload all advisor modules
import importlib
import sys

# Remove cached modules
for module in list(sys.modules.keys()):
    if module.startswith('advisor'):
        del sys.modules[module]

# Re-import
from advisor.rag_system import get_rag_system
rag = get_rag_system()
```

### Solution 4: Restart Jupyter Kernel

If using Jupyter notebooks:
1. Click "Kernel" menu
2. Select "Restart Kernel"
3. Re-run your imports

## How Scoped Queries Work

### Architecture Flow

```
User Query: "How many classes are under the Pyegeria folder?"
     ↓
QueryProcessor.extract_path() → "pyegeria"
     ↓
RAGSystem._process_query() → passes path_filter
     ↓
AnalyticsManager.answer_quantitative_query(query, path_filter="pyegeria")
     ↓
get_total_classes(path_filter="pyegeria") → uses directory_stats.json
     ↓
Result: "There are 191 classes in the pyegeria directory."
```

### Key Components

1. **Path Extraction** (`query_processor.py`)
   - Detects patterns: "in X folder", "under X", "within X", "from X"
   - Extracts directory name (e.g., "pyegeria", "commands")

2. **Path Propagation** (`rag_system.py`)
   - Passes `path_filter` from query analysis to analytics

3. **Path Filtering** (`analytics.py`)
   - Uses `directory_stats.json` for fast lookups
   - Falls back to entire codebase if no filter

### Directory Statistics

The system uses pre-computed statistics in `data/cache/directory_stats.json`:

```json
{
  "pyegeria": {
    "classes": 191,
    "functions": 2081,
    "methods": 1891,
    ...
  },
  "commands": {
    "classes": 5,
    "functions": 402,
    "methods": 31,
    ...
  }
}
```

Generate/update these statistics:
```bash
python scripts/generate_directory_stats.py
```

## Testing Queries

### Scoped Queries (Should Use Path Filter)

```
✓ "How many classes are under the Pyegeria folder?"
  → 191 classes in pyegeria directory

✓ "How many functions in the commands directory?"
  → 402 functions in commands directory

✓ "How many methods within pyegeria?"
  → 1,891 methods in pyegeria directory
```

### Unscoped Queries (Should Use Entire Codebase)

```
✓ "How many classes are in the codebase?"
  → 196 classes in egeria-python codebase

✓ "How many total functions?"
  → 2,483 functions in egeria-python codebase
```

## Common Issues

### Issue: Path Not Extracted

**Symptom:** Query has directory name but path_filter is None

**Cause:** Query doesn't match extraction patterns

**Solution:** Use supported patterns:
- "in [directory] folder"
- "under [directory]"
- "within [directory]"
- "from [directory]"

### Issue: Wrong Directory Name

**Symptom:** Path extracted but no statistics found

**Cause:** Directory name doesn't match statistics file

**Solution:** Check available directories:
```python
from advisor.analytics import get_analytics_manager
analytics = get_analytics_manager()
print(analytics.directory_stats.keys())
# Output: dict_keys(['pyegeria', 'commands', '_total'])
```

### Issue: Statistics File Missing

**Symptom:** Warning "Directory statistics file not found"

**Solution:** Generate statistics:
```bash
python scripts/generate_directory_stats.py
```

## Debug Mode

Enable detailed logging to see the full flow:

```python
from loguru import logger
import sys

# Enable debug logging
logger.remove()
logger.add(sys.stderr, level="DEBUG")

# Now test your query
from advisor.rag_system import get_rag_system
rag = get_rag_system()
result = rag.query("How many classes are under the Pyegeria folder?")
```

Look for these log messages:
1. `Processed query: type=quantitative, keywords=5, path_filter=pyegeria`
2. `Applying path filter: pyegeria`
3. `Loaded directory statistics from data/cache/directory_stats.json`

## Still Not Working?

If you've tried all solutions and it still doesn't work:

1. **Verify code changes are saved:**
   ```bash
   git status
   git diff advisor/analytics.py
   ```

2. **Check Python is using correct files:**
   ```python
   import advisor.analytics
   print(advisor.analytics.__file__)
   # Should point to your working directory
   ```

3. **Run the test suite:**
   ```bash
   python scripts/test_scoped_queries.py
   ```

4. **Check for import caching issues:**
   ```bash
   # Remove all .pyc files
   find . -type f -name "*.pyc" -delete
   find . -type d -name "__pycache__" -delete
   ```

## Contact

If the issue persists after trying all solutions, the problem may be in your specific environment setup. Check:
- Python version (should be 3.10+)
- Virtual environment is activated
- All dependencies are installed
- No conflicting advisor packages