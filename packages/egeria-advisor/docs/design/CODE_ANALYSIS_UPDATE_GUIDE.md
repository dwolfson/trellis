# Code Analysis Update Guide

## Overview

The Egeria Advisor uses enhanced code analysis tools to provide accurate quantitative and relationship queries. This guide explains how to update the analysis data.

## Analysis Tools

### 1. Enhanced Metrics (Radon + Pygount)
- **Purpose**: Provides accurate code metrics
- **Metrics Collected**:
  - Lines of Code (LOC) and Source Lines of Code (SLOC)
  - Cyclomatic Complexity (CC)
  - Maintainability Index (MI)
  - Halstead Metrics (volume, difficulty, effort)
  - Folder-level breakdowns
- **Output**: `data/cache/enhanced_metrics.json`

### 2. Enhanced Relationships (AST Analysis)
- **Purpose**: Extracts code structure and relationships
- **Data Collected**:
  - Import statements and dependencies
  - Class definitions and inheritance
  - Function definitions and calls
  - Call graphs and import graphs
  - Circular import detection
- **Output**: `data/cache/enhanced_relationships.json`

## When to Update Analysis Data

Update the analysis data when:

1. **Code Changes**: After significant code changes to the target repository
2. **New Features**: When new modules or packages are added
3. **Refactoring**: After major refactoring efforts
4. **Periodic Updates**: As part of regular maintenance (weekly/monthly)

## How to Update

### Automatic Update (Recommended)

Run the comprehensive update script:

```bash
cd /path/to/egeria-advisor
./scripts/update_all_analysis.sh
```

This script will:
1. Activate the virtual environment
2. Run enhanced metrics generation
3. Run enhanced relationships generation
4. Report success/failure for each step

### Manual Update

If you need to run tools individually:

#### Update Metrics Only
```bash
cd /path/to/egeria-advisor
source .venv/bin/activate
python scripts/generate_enhanced_metrics.py
```

#### Update Relationships Only
```bash
cd /path/to/egeria-advisor
source .venv/bin/activate
python scripts/generate_enhanced_relationships.py
```

## Integration with RAG System

### Current Status

**The code analysis tools are NOT automatically run when updating the RAG system.**

The analysis data is:
- **Separate from vector embeddings**: Analysis data is cached independently
- **Loaded on demand**: Modules load cached JSON files when needed
- **Query-specific**: Only loaded when quantitative or relationship queries are detected

### Why Separate?

1. **Different Update Frequencies**: 
   - Vector embeddings: Updated when documentation/code structure changes
   - Analysis data: Updated when code metrics/relationships change

2. **Performance**:
   - Analysis is computationally expensive (AST parsing, metrics calculation)
   - Not needed for most query types (CODE_SEARCH, EXPLANATION, etc.)

3. **Flexibility**:
   - Can update analysis independently of RAG
   - Can skip analysis if only documentation changed

### Recommended Workflow

```bash
# 1. Update code analysis (when code changes)
./scripts/update_all_analysis.sh

# 2. Update RAG embeddings (when documentation/structure changes)
# (Use your existing RAG update process)

# 3. Test the system
python scripts/test_enhanced_analytics.py
python scripts/test_enhanced_relationships.py
```

## Query Types Using Analysis Data

### Quantitative Queries (Enhanced Analytics)
- "How many lines of code are in the project?"
- "What is the average complexity?"
- "Which folders have the most code?"
- "What is the maintainability index?"
- "Show me folder-level metrics"

### Relationship Queries (Enhanced Relationships)
- "What does module X import?"
- "What classes inherit from Y?"
- "What functions call Z?"
- "Show me the dependency graph"
- "Are there any circular imports?"

## Verification

After updating, verify the data:

```bash
# Check metrics file exists and is recent
ls -lh data/cache/enhanced_metrics.json

# Check relationships file exists and is recent
ls -lh data/cache/enhanced_relationships.json

# Run test scripts
python scripts/test_enhanced_analytics.py
python scripts/test_enhanced_relationships.py
```

## Troubleshooting

### Script Fails to Run

**Problem**: Permission denied
```bash
chmod +x scripts/update_all_analysis.sh
```

**Problem**: Virtual environment not found
```bash
# Recreate virtual environment
./scripts/recreate_venv.sh
```

### Analysis Takes Too Long

**Problem**: Large codebase
- The analysis tools process all Python files
- Expected time: 1-5 minutes for medium projects
- For very large projects (>100k LOC), consider:
  - Running during off-hours
  - Excluding test directories if not needed

### Metrics Look Wrong

**Problem**: Unexpected values
1. Check if virtual environments are being analyzed:
   - Script should skip `.venv`, `venv`, `__pycache__`
2. Verify target repository path in scripts
3. Check for recent code changes

### Missing Dependencies

**Problem**: Import errors
```bash
# Install required packages
pip install radon>=6.0.1 pygount>=1.6.1
```

## Future Enhancements

Planned improvements:

1. **Automatic Integration**: Option to run analysis during RAG updates
2. **Incremental Updates**: Only analyze changed files
3. **CI/CD Integration**: Run analysis in GitHub Actions
4. **Dead Code Detection**: Phase 3 with Vulture/Prospector
5. **Trend Analysis**: Track metrics over time with MLflow

## Files Reference

### Scripts
- `scripts/update_all_analysis.sh` - Main update script
- `scripts/generate_enhanced_metrics.py` - Metrics generation
- `scripts/generate_enhanced_relationships.py` - Relationship extraction
- `scripts/test_enhanced_analytics.py` - Test metrics queries
- `scripts/test_enhanced_relationships.py` - Test relationship queries

### Modules
- `advisor/enhanced_analytics.py` - Metrics query handler
- `advisor/enhanced_relationships.py` - Relationship query handler

### Data Files
- `data/cache/enhanced_metrics.json` - Cached metrics data
- `data/cache/enhanced_relationships.json` - Cached relationship data

## Questions?

For issues or questions:
1. Check the test scripts for examples
2. Review the generated JSON files for data structure
3. Consult `CODE_ANALYSIS_TOOLS_RESEARCH.md` for tool details