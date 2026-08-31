# Phase 2: Collection-Specific Parameters Implementation

**Status**: ✅ COMPLETE  
**Date**: 2026-03-02  
**Goal**: Implement collection-specific RAG parameters to reduce hallucination rate from 80% to 27%

## Overview

Phase 2 implements collection-specific parameters for chunk size, overlap, min_score thresholds, and top_k values. This allows each collection to be optimized for its content type, addressing the root cause of high hallucination rates.

## Problem Statement

The RAG system had an 80% hallucination rate due to:
1. **One-size-fits-all parameters**: 512 token chunks for all content types
2. **Weak embedding model**: 384 dimensions, truncates at 256 tokens
3. **Low retrieval threshold**: min_score of 0.30 allowed poor matches
4. **Generic prompts**: Didn't emphasize using retrieved context
5. **Overly broad collections**: egeria_docs mixed concepts with tutorials

## Implementation

### 1. Collection-Specific Parameters

Added four new parameters to `CollectionMetadata` in `advisor/collection_config.py`:

```python
@dataclass
class CollectionMetadata:
    # ... existing fields ...
    
    # RAG-specific parameters (NEW - Phase 2)
    chunk_size: int = 512  # Tokens per chunk
    chunk_overlap: int = 100  # Token overlap between chunks
    min_score: float = 0.35  # Minimum similarity score threshold
    default_top_k: int = 8  # Default number of results to retrieve
```

### 2. Collection Parameter Tuning

Each collection now has optimized parameters:

| Collection | chunk_size | chunk_overlap | min_score | default_top_k | Rationale |
|------------|------------|---------------|-----------|---------------|-----------|
| **pyegeria** | 512 | 100 (20%) | 0.35 | 10 | Standard code chunks, more results for code queries |
| **pyegeria_cli** | 512 | 100 (20%) | 0.35 | 10 | CLI commands similar to code |
| **pyegeria_drE** | 512 | 100 (20%) | 0.35 | 8 | Markdown processing code |
| **egeria_java** | 768 | 150 (20%) | 0.35 | 8 | Larger chunks for Java methods |
| **egeria_concepts** | 768 | 150 (20%) | 0.45 | 5 | High precision for definitions |
| **egeria_types** | 1024 | 200 (20%) | 0.42 | 6 | Complete type definitions |
| **egeria_general** | 1536 | 300 (20%) | 0.38 | 8 | Large chunks for tutorials |
| **egeria_workspaces** | 1536 | 300 (20%) | 0.38 | 6 | Complete examples |

**Key Insights**:
- **Concepts**: Smaller chunks (768), high threshold (0.45), fewer results (5) → Precision over recall
- **Types**: Medium chunks (1024), high threshold (0.42) → Complete definitions
- **Tutorials**: Large chunks (1536), lower threshold (0.38) → Complete context
- **Code**: Standard chunks (512-768), moderate threshold (0.35) → Balance

### 3. New Specialized Collections

Split `egeria_docs` into three specialized collections:

#### egeria_concepts
- **Path**: `site/docs/concepts/`
- **Purpose**: Short concept definitions and explanations
- **Parameters**: chunk_size=768, min_score=0.45, top_k=5
- **Domain Terms**: concept, definition, what is, explain, metadata, governance, etc.
- **Priority**: 12 (highest)

#### egeria_types
- **Path**: `site/docs/types/`
- **Purpose**: Detailed type system definitions and schemas
- **Parameters**: chunk_size=1024, min_score=0.42, top_k=6
- **Domain Terms**: type, schema, attribute, property, entity, typedef, etc.
- **Priority**: 11

#### egeria_general
- **Path**: `site/docs/` (excluding concepts/ and types/)
- **Purpose**: Tutorials, guides, and how-tos
- **Parameters**: chunk_size=1536, min_score=0.38, top_k=8
- **Domain Terms**: tutorial, guide, how-to, walkthrough, getting-started, etc.
- **Priority**: 9

**Migration Plan**:
1. Ingest new collections (egeria_concepts, egeria_types, egeria_general)
2. Validate routing works correctly
3. Disable old egeria_docs collection
4. Monitor metrics to confirm improvement

### 4. Code Changes

#### advisor/collection_config.py
- Added 4 new parameters to `CollectionMetadata`
- Defined 3 new specialized collections
- Updated ALL_COLLECTIONS registry
- Set collection-specific parameters for all 9 collections

#### advisor/ingest_to_milvus.py
- Updated `CodeIngester.__init__()` to use collection-specific chunk_size and chunk_overlap
- Falls back to defaults if collection not found in config
- Added Optional type hints for parameters

#### advisor/multi_collection_store.py
- Updated `search_with_routing()` to use collection-specific min_score and default_top_k
- Updated `search_specific_collections()` to use collection-specific parameters
- Each collection now uses its own optimized thresholds during search

#### advisor/prompt_templates.py
- Enhanced anti-hallucination instructions in system prompts
- Added explicit "NEVER FABRICATE" rules
- Added "ALWAYS CITE" requirements
- Added "BE HONEST" about missing information
- Added support for new specialized collections in collection_context

### 5. Expected Impact

Based on the design analysis, we expect:

| Query Type | Current Hallucination | Target Hallucination | Reduction |
|------------|----------------------|---------------------|-----------|
| **CONCEPT** | 85% | 20% | 76% |
| **TYPE** | 80% | 25% | 69% |
| **CODE** | 60% | 25% | 58% |
| **EXAMPLE** | 75% | 30% | 60% |
| **TUTORIAL** | 70% | 25% | 64% |
| **Overall** | **80%** | **27%** | **66%** |

**Key Improvements**:
1. **Concept queries**: High min_score (0.45) ensures precise matches
2. **Type queries**: Large chunks (1024) capture complete definitions
3. **Code queries**: More results (top_k=10) provide better context
4. **Tutorial queries**: Large chunks (1536) preserve complete examples

## Testing Strategy

### Unit Tests
- ✅ Collection metadata includes new parameters
- ✅ CodeIngester uses collection-specific chunking
- ✅ MultiCollectionStore uses collection-specific thresholds
- ✅ Prompt templates include anti-hallucination rules

### Integration Tests (Phase 3)
- [ ] Ingest new specialized collections
- [ ] Verify routing to correct collections
- [ ] Measure retrieval quality per collection
- [ ] Validate hallucination rate reduction
- [ ] Compare baseline vs. optimized metrics

## Next Steps (Phase 3)

1. **Ingest New Collections**
   ```bash
   # Clone egeria-docs if not already present
   cd /path/to/repos
   git clone https://github.com/odpi/egeria-docs.git
   
   # Ingest specialized collections
   python scripts/ingest_collections.py --collection egeria_concepts
   python scripts/ingest_collections.py --collection egeria_types
   python scripts/ingest_collections.py --collection egeria_general
   ```

2. **Validate Routing**
   ```bash
   # Test concept queries route to egeria_concepts
   python scripts/test_collection_routing.py --query "What is metadata governance?"
   
   # Test type queries route to egeria_types
   python scripts/test_collection_routing.py --query "What is the Asset entity type?"
   ```

3. **Capture Baseline Metrics**
   ```bash
   # Capture metrics before optimization
   python scripts/capture_baseline_metrics.py --output baseline_before.json
   ```

4. **Enable New Collections**
   ```python
   # In advisor/collection_config.py
   EGERIA_CONCEPTS_COLLECTION.enabled = True
   EGERIA_TYPES_COLLECTION.enabled = True
   EGERIA_GENERAL_COLLECTION.enabled = True
   EGERIA_DOCS_COLLECTION.enabled = False  # Disable old collection
   ```

5. **Measure Improvements**
   ```bash
   # Run test queries and measure hallucination rate
   python scripts/test_rag_quality_improvements.py
   
   # Capture metrics after optimization
   python scripts/capture_baseline_metrics.py --output baseline_after.json
   
   # Compare metrics
   python scripts/compare_baselines.py baseline_before.json baseline_after.json
   ```

## Files Modified

### Core Implementation
- `advisor/collection_config.py` - Added parameters, defined new collections
- `advisor/ingest_to_milvus.py` - Use collection-specific chunking
- `advisor/multi_collection_store.py` - Use collection-specific thresholds
- `advisor/prompt_templates.py` - Enhanced anti-hallucination instructions

### Documentation
- `docs/design/PHASE2_COLLECTION_PARAMETERS_IMPLEMENTATION.md` - This file
- `docs/design/EGERIA_DOCS_SPLIT_STRATEGY.md` - Collection split design (Phase 1)
- `docs/design/QUERY_CLASSIFICATION_AND_TRACKING.md` - Monitoring design (Phase 1)

## Success Criteria

Phase 2 is considered successful when:

1. ✅ All collections have optimized parameters defined
2. ✅ CodeIngester uses collection-specific chunking
3. ✅ MultiCollectionStore uses collection-specific thresholds
4. ✅ Prompt templates include strong anti-hallucination rules
5. ✅ New specialized collections are defined
6. [ ] New collections are ingested and indexed (Phase 3)
7. [ ] Hallucination rate reduced to ≤27% (Phase 3)
8. [ ] Metrics show improvement across all query types (Phase 3)

## Monitoring

Use the monitoring infrastructure from Phase 1 to track:

- **Collection Metrics**: Hit rate, avg_score, result_count per collection
- **Query Classification**: Distribution of query types
- **Assembly Metrics**: Diversity, overlap, utilization
- **MLflow Tracking**: 40+ metrics per query logged

See `docs/design/MONITORING_NEXT_STEPS.md` for integration instructions.

## References

- **Phase 1 Monitoring**: `docs/design/MONITORING_IMPLEMENTATION_STATUS.md`
- **Collection Split Design**: `docs/design/EGERIA_DOCS_SPLIT_STRATEGY.md`
- **Query Classification**: `docs/design/QUERY_CLASSIFICATION_AND_TRACKING.md`
- **RAG Quality Analysis**: `docs/design/RAG_QUALITY_IMPROVEMENTS.md`

## Conclusion

Phase 2 successfully implements collection-specific parameters that address the root causes of high hallucination rates. The system is now ready for Phase 3: re-ingestion and validation.

**Key Achievement**: Moved from one-size-fits-all parameters to optimized, collection-specific configurations that should reduce hallucination from 80% to 27% (66% reduction).