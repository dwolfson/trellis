# Monitoring Implementation - Next Steps Guide

## Overview

This document provides a detailed guide for completing the monitoring implementation. Phase 1 Core is 75% complete. This guide covers the remaining 25% and subsequent phases.

**Current Status**: Phase 1 Core Complete (75%)
**Next Session Goal**: Complete Phase 1 Integration (25%)
**Estimated Time**: 8-10 hours

---

## Immediate Next Steps (Phase 1 Integration)

### Step 1: Integrate Monitoring with RAG Retrieval (3-4 hours)

**File to Update**: `advisor/rag_retrieval.py`

**Current State**: RAG retrieval works but doesn't track metrics

**Target State**: Every query tracked with full metrics

**Implementation**:

```python
# At top of file, add imports
from advisor.query_classifier import classify_query
from advisor.collection_metrics import get_collection_metrics_tracker
from advisor.assembly_metrics import get_assembly_metrics_tracker
from advisor.mlflow_tracking import get_mlflow_tracker
import uuid
import time

# In RAGRetriever.retrieve_and_build_context() method
def retrieve_and_build_context(
    self,
    query: str,
    top_k: Optional[int] = None,
    min_score: Optional[float] = None,
    filters: Optional[Dict[str, Any]] = None,
    format_style: str = "detailed",
    include_metadata: bool = True,
    prioritize_docs: bool = False
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Retrieve and build context with full monitoring.
    """
    # Generate unique query ID
    query_id = str(uuid.uuid4())
    start_time = time.time()
    
    # 1. CLASSIFY QUERY
    classification_start = time.time()
    classification = classify_query(query)
    classification_time_ms = (time.time() - classification_start) * 1000
    
    logger.info(
        f"Query classified as {classification.query_type.value} "
        f"(confidence: {classification.confidence:.2f})"
    )
    
    # 2. GET METRICS TRACKERS
    coll_tracker = get_collection_metrics_tracker()
    asm_tracker = get_assembly_metrics_tracker()
    mlflow_tracker = get_mlflow_tracker()
    
    # 3. RETRIEVE WITH COLLECTION TRACKING
    collection_metrics_list = []
    collection_results = {}
    
    if self.use_multi_collection and self.multi_store:
        # Multi-collection search with routing
        routing_start = time.time()
        multi_result = self.multi_store.search_with_routing(
            query=query,
            top_k=top_k or self.top_k,
            min_score=min_score or self.min_score,
            filters=filters
        )
        routing_time_ms = (time.time() - routing_start) * 1000
        
        results = multi_result.results
        collections_searched = multi_result.collections_searched
        
        # Track each collection's contribution
        for collection_name in collections_searched:
            # Get results for this collection
            coll_results = [
                r for r in results 
                if r.metadata.get('collection') == collection_name
            ]
            
            collection_results[collection_name] = coll_results
            
            # Track metrics
            was_primary = (collection_name == collections_searched[0])
            
            metrics = coll_tracker.track_collection_search(
                collection_name=collection_name,
                query_type=classification.query_type,
                query_topics=classification.topics,
                results=coll_results,
                search_time_ms=multi_result.collection_scores.get(collection_name, {}).get('search_time_ms', 0),
                min_score_threshold=min_score or self.min_score,
                was_primary=was_primary,
                routing_confidence=classification.confidence
            )
            collection_metrics_list.append(metrics)
    else:
        # Single collection search
        search_start = time.time()
        query_embedding = self.embedding_gen.generate_embedding(query)
        results = self.vector_store.search(
            collection_name="code_elements",
            query_embedding=query_embedding,
            top_k=top_k or self.top_k,
            filters=filters
        )
        search_time_ms = (time.time() - search_start) * 1000
        
        collections_searched = ["code_elements"]
        collection_results["code_elements"] = results
        
        # Track metrics
        metrics = coll_tracker.track_collection_search(
            collection_name="code_elements",
            query_type=classification.query_type,
            query_topics=classification.topics,
            results=results,
            search_time_ms=search_time_ms,
            min_score_threshold=min_score or self.min_score,
            was_primary=True,
            routing_confidence=1.0
        )
        collection_metrics_list.append(metrics)
    
    # Filter by minimum score
    filtered_results = [
        r for r in results
        if r.score >= (min_score or self.min_score)
    ]
    
    logger.info(f"Retrieved {len(filtered_results)} results (filtered from {len(results)})")
    
    # 4. BUILD CONTEXT WITH ASSEMBLY TRACKING
    assembly_start = time.time()
    context = self.build_context(
        results=filtered_results,
        include_metadata=include_metadata,
        format_style=format_style
    )
    assembly_time_ms = (time.time() - assembly_start) * 1000
    
    # Track which chunks made it to final context
    for collection_name, coll_results in collection_results.items():
        chunks_in_final = len([
            r for r in filtered_results
            if r in coll_results
        ])
        ranks_in_final = [
            i for i, r in enumerate(filtered_results)
            if r in coll_results
        ]
        
        coll_tracker.update_final_context_metrics(
            collection_name=collection_name,
            chunks_in_final=chunks_in_final,
            ranks_in_final=ranks_in_final
        )
    
    # Track assembly metrics
    assembly_metrics = asm_tracker.track_assembly(
        query_type=classification.query_type,
        query_topics=classification.topics,
        collections_searched=collections_searched,
        collection_results=collection_results,
        final_results=filtered_results,
        reranking_time_ms=assembly_time_ms,
        context_length_chars=len(context),
        max_context_length=self.max_context_length
    )
    
    # 5. PREPARE SOURCES
    sources = []
    for result in filtered_results:
        source_dict = {
            "text": result.text,
            "score": result.score,
            "file_path": result.metadata.get("file_path", "unknown"),
            "name": result.metadata.get("name", "unnamed"),
            "type": result.metadata.get("type", "unknown"),
            "module": result.metadata.get("module", ""),
        }
        sources.append(source_dict)
    
    # 6. LOG TO MLFLOW (LLM metrics will be added by caller)
    total_latency_ms = (time.time() - start_time) * 1000
    
    # Store metrics for later MLflow logging
    # (LLM time will be added by the caller)
    self._last_query_metrics = {
        'query_id': query_id,
        'query_text': query,
        'classification': classification,
        'collection_metrics': collection_metrics_list,
        'assembly_metrics': assembly_metrics,
        'total_latency_ms': total_latency_ms,
        'cache_hit': False  # Will be updated if from cache
    }
    
    return context, sources

# Add new method to log complete lifecycle
def log_query_to_mlflow(
    self,
    llm_time_ms: float,
    llm_tokens_input: int,
    llm_tokens_output: int,
    user_feedback_score: Optional[float] = None,
    hallucination_detected: bool = False
):
    """
    Log complete query lifecycle to MLflow.
    
    Call this after LLM generation is complete.
    """
    if not hasattr(self, '_last_query_metrics'):
        logger.warning("No query metrics to log")
        return
    
    metrics = self._last_query_metrics
    mlflow_tracker = get_mlflow_tracker()
    
    mlflow_tracker.track_query_lifecycle(
        query_id=metrics['query_id'],
        query_text=metrics['query_text'],
        classification=metrics['classification'],
        collection_metrics=metrics['collection_metrics'],
        assembly_metrics=metrics['assembly_metrics'],
        llm_time_ms=llm_time_ms,
        llm_tokens_input=llm_tokens_input,
        llm_tokens_output=llm_tokens_output,
        total_latency_ms=metrics['total_latency_ms'] + llm_time_ms,
        cache_hit=metrics['cache_hit'],
        user_feedback_score=user_feedback_score,
        hallucination_detected=hallucination_detected
    )
    
    logger.info(f"Logged query {metrics['query_id']} to MLflow")
```

**Testing**:
```bash
# Test the integration
python -c "
from advisor.rag_retrieval import get_rag_retriever

retriever = get_rag_retriever()
context, sources = retriever.retrieve_and_build_context('What is a glossary?')
print(f'Context length: {len(context)}')
print(f'Sources: {len(sources)}')

# Log to MLflow
retriever.log_query_to_mlflow(
    llm_time_ms=150.0,
    llm_tokens_input=1000,
    llm_tokens_output=500
)
"
```

---

### Step 2: Update Collection Router (1-2 hours)

**File to Update**: `advisor/collection_router.py`

**Changes Needed**:

```python
# At top of file
from advisor.query_classifier import classify_query, QueryClassification

# In CollectionRouter class
def route_query_with_classification(
    self,
    query: str,
    query_terms: Optional[List[str]] = None,
    max_collections: int = 3
) -> Tuple[List[str], QueryClassification, float]:
    """
    Route query using classification.
    
    Returns:
        (collection_names, classification, routing_confidence)
    """
    # Classify query
    classification = classify_query(query)
    
    # Get expected collections for this query type
    expected_collections = self._get_collections_for_type(
        classification.query_type
    )
    
    # Filter to enabled collections
    enabled_expected = [
        c for c in expected_collections
        if any(coll.name == c for coll in self.collections)
    ]
    
    # Calculate routing confidence
    routing_confidence = classification.confidence
    
    # If no expected collections, fall back to original routing
    if not enabled_expected:
        collections = self.route_query(query, query_terms, max_collections)
        routing_confidence = 0.5
    else:
        collections = enabled_expected[:max_collections]
    
    logger.info(
        f"Routed {classification.query_type.value} query to: {collections} "
        f"(confidence: {routing_confidence:.2f})"
    )
    
    return collections, classification, routing_confidence

def _get_collections_for_type(self, query_type: QueryType) -> List[str]:
    """Get expected collections for a query type."""
    from advisor.query_classifier import QueryType
    
    type_to_collections = {
        QueryType.CONCEPT: ['egeria_concepts', 'egeria_types'],
        QueryType.TYPE: ['egeria_types', 'egeria_concepts'],
        QueryType.CODE: ['pyegeria', 'pyegeria_cli', 'egeria_java'],
        QueryType.EXAMPLE: ['egeria_workspaces', 'pyegeria'],
        QueryType.TUTORIAL: ['egeria_general', 'egeria_workspaces'],
        QueryType.TROUBLESHOOTING: ['egeria_general', 'pyegeria'],
        QueryType.COMPARISON: ['egeria_concepts', 'egeria_types'],
        QueryType.GENERAL: ['pyegeria', 'egeria_general'],
    }
    
    return type_to_collections.get(query_type, ['pyegeria'])
```

---

### Step 3: Create Unit Tests (2-3 hours)

**File to Create**: `tests/test_monitoring.py`

```python
"""Unit tests for monitoring components."""

import pytest
from advisor.query_classifier import (
    classify_query, QueryType, QueryTopic, get_query_classifier
)
from advisor.collection_metrics import (
    get_collection_metrics_tracker, CollectionRetrievalMetrics
)
from advisor.assembly_metrics import (
    get_assembly_metrics_tracker, DocumentAssemblyMetrics
)


class TestQueryClassifier:
    """Test query classification."""
    
    def test_concept_query(self):
        """Test concept query classification."""
        classification = classify_query("What is a glossary?")
        assert classification.query_type == QueryType.CONCEPT
        assert QueryTopic.GLOSSARY in classification.topics
        assert classification.confidence > 0.7
    
    def test_type_query(self):
        """Test type query classification."""
        classification = classify_query("What properties does GlossaryTerm have?")
        assert classification.query_type == QueryType.TYPE
        assert classification.confidence > 0.7
    
    def test_code_query(self):
        """Test code query classification."""
        classification = classify_query("Show me code for creating an asset")
        assert classification.query_type == QueryType.CODE
        assert classification.confidence > 0.7
    
    def test_example_query(self):
        """Test example query classification."""
        classification = classify_query("Give me an example of using pyegeria")
        assert classification.query_type == QueryType.EXAMPLE
        assert classification.confidence > 0.7
    
    def test_expected_collections(self):
        """Test expected collections suggestion."""
        classifier = get_query_classifier()
        classification = classify_query("What is a glossary?")
        expected = classifier.get_expected_collections(classification)
        assert 'egeria_concepts' in expected
    
    def test_expected_parameters(self):
        """Test expected parameters suggestion."""
        classifier = get_query_classifier()
        classification = classify_query("What is a glossary?")
        params = classifier.get_expected_parameters(classification)
        assert 'chunk_size' in params
        assert 'min_score' in params
        assert 'top_k' in params
        assert params['min_score'] == 0.45  # High for concept queries


class TestCollectionMetrics:
    """Test collection metrics tracking."""
    
    def test_track_search(self):
        """Test tracking a collection search."""
        tracker = get_collection_metrics_tracker()
        tracker.clear_history()  # Start fresh
        
        # Create mock results
        class MockResult:
            def __init__(self, score):
                self.score = score
        
        results = [MockResult(0.8), MockResult(0.6), MockResult(0.4)]
        
        # Track search
        metrics = tracker.track_collection_search(
            collection_name="test_collection",
            query_type=QueryType.CONCEPT,
            query_topics=[QueryTopic.GLOSSARY],
            results=results,
            search_time_ms=50.0,
            min_score_threshold=0.5,
            was_primary=True,
            routing_confidence=0.95
        )
        
        assert metrics.chunks_retrieved == 3
        assert metrics.chunks_above_threshold == 2
        assert metrics.avg_score == pytest.approx(0.6, rel=0.01)
        assert metrics.max_score == 0.8
        assert metrics.min_score == 0.4
        assert metrics.get_precision() == pytest.approx(2/3, rel=0.01)
    
    def test_collection_summary(self):
        """Test collection summary generation."""
        tracker = get_collection_metrics_tracker()
        tracker.clear_history()
        
        # Track multiple searches
        class MockResult:
            def __init__(self, score):
                self.score = score
        
        for i in range(5):
            results = [MockResult(0.8), MockResult(0.6)]
            tracker.track_collection_search(
                collection_name="test_collection",
                query_type=QueryType.CONCEPT,
                query_topics=[QueryTopic.GLOSSARY],
                results=results,
                search_time_ms=50.0,
                min_score_threshold=0.5
            )
        
        # Get summary
        summary = tracker.get_collection_summary("test_collection")
        assert summary['total_searches'] == 5
        assert summary['avg_chunks_retrieved'] == 2.0
        assert summary['avg_precision'] == 1.0  # All above threshold


class TestAssemblyMetrics:
    """Test assembly metrics tracking."""
    
    def test_track_assembly(self):
        """Test tracking document assembly."""
        tracker = get_assembly_metrics_tracker()
        tracker.clear_history()
        
        # Create mock results
        class MockResult:
            def __init__(self, score, file_path):
                self.score = score
                self.text = f"text_{score}"
                self.metadata = {'file_path': file_path}
        
        coll1_results = [MockResult(0.8, "file1.py"), MockResult(0.7, "file2.py")]
        coll2_results = [MockResult(0.6, "file3.py")]
        final_results = [MockResult(0.8, "file1.py"), MockResult(0.6, "file3.py")]
        
        # Track assembly
        metrics = tracker.track_assembly(
            query_type=QueryType.CONCEPT,
            query_topics=[QueryTopic.GLOSSARY],
            collections_searched=["coll1", "coll2"],
            collection_results={"coll1": coll1_results, "coll2": coll2_results},
            final_results=final_results,
            reranking_time_ms=10.0,
            context_length_chars=1000,
            max_context_length=8000
        )
        
        assert metrics.total_chunks_retrieved == 3
        assert metrics.total_chunks_used == 2
        assert metrics.get_utilization_rate() == pytest.approx(2/3, rel=0.01)
        assert metrics.chunk_diversity_score >= 0.0
        assert metrics.chunk_diversity_score <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

**Run Tests**:
```bash
python -m pytest tests/test_monitoring.py -v
```

---

### Step 4: Create Baseline Capture Script (2 hours)

**File to Create**: `scripts/capture_baseline_metrics.py`

```python
"""
Capture baseline metrics before re-ingestion.

This script runs a set of test queries and captures current
system performance for comparison after improvements.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Any
from loguru import logger

from advisor.rag_system import RAGSystem
from advisor.query_classifier import classify_query


# Test queries for each type
TEST_QUERIES = {
    "concept": [
        "What is a glossary?",
        "Define metadata",
        "Explain governance",
        "What is an asset?",
        "What is lineage?",
    ],
    "type": [
        "What properties does GlossaryTerm have?",
        "What attributes are in Asset?",
        "What fields does Connection have?",
    ],
    "code": [
        "Show me code for creating a glossary",
        "How do I use pyegeria to create an asset?",
        "Give me code for connecting to Egeria",
    ],
    "example": [
        "Give me an example of using pyegeria",
        "Show me a sample notebook",
        "Example of creating a connection",
    ],
    "tutorial": [
        "How do I get started with Egeria?",
        "How do I set up a server?",
        "How do I configure a connector?",
    ],
}


def capture_baseline() -> Dict[str, Any]:
    """
    Capture baseline metrics.
    
    Returns:
        Dict with baseline metrics
    """
    logger.info("Starting baseline capture...")
    
    # Initialize RAG system
    rag = RAGSystem()
    
    baseline = {
        "timestamp": time.time(),
        "queries_by_type": {},
        "overall_stats": {
            "total_queries": 0,
            "total_latency_ms": 0,
            "total_chunks_retrieved": 0,
            "hallucinations_detected": 0,
        }
    }
    
    # Run queries for each type
    for query_type, queries in TEST_QUERIES.items():
        logger.info(f"Testing {query_type} queries...")
        
        type_results = []
        
        for query in queries:
            logger.info(f"  Query: {query}")
            
            # Classify query
            classification = classify_query(query)
            
            # Run query
            start_time = time.time()
            try:
                result = rag.query(query)
                latency_ms = (time.time() - start_time) * 1000
                
                # Extract metrics
                query_result = {
                    "query": query,
                    "classification": {
                        "type": classification.query_type.value,
                        "topics": [t.value for t in classification.topics],
                        "confidence": classification.confidence,
                    },
                    "latency_ms": latency_ms,
                    "collections_searched": getattr(result, 'collections_searched', []),
                    "chunks_retrieved": getattr(result, 'chunks_retrieved', 0),
                    "chunks_used": getattr(result, 'chunks_used', 0),
                    "success": True,
                    "error": None,
                }
                
                # Update overall stats
                baseline["overall_stats"]["total_queries"] += 1
                baseline["overall_stats"]["total_latency_ms"] += latency_ms
                baseline["overall_stats"]["total_chunks_retrieved"] += query_result["chunks_retrieved"]
                
                logger.info(f"    Latency: {latency_ms:.1f}ms, Chunks: {query_result['chunks_retrieved']}")
                
            except Exception as e:
                logger.error(f"    Error: {e}")
                query_result = {
                    "query": query,
                    "classification": {
                        "type": classification.query_type.value,
                        "topics": [t.value for t in classification.topics],
                        "confidence": classification.confidence,
                    },
                    "success": False,
                    "error": str(e),
                }
            
            type_results.append(query_result)
        
        baseline["queries_by_type"][query_type] = type_results
    
    # Calculate averages
    total_queries = baseline["overall_stats"]["total_queries"]
    if total_queries > 0:
        baseline["overall_stats"]["avg_latency_ms"] = (
            baseline["overall_stats"]["total_latency_ms"] / total_queries
        )
        baseline["overall_stats"]["avg_chunks_retrieved"] = (
            baseline["overall_stats"]["total_chunks_retrieved"] / total_queries
        )
    
    logger.info("Baseline capture complete!")
    logger.info(f"Total queries: {total_queries}")
    logger.info(f"Avg latency: {baseline['overall_stats'].get('avg_latency_ms', 0):.1f}ms")
    
    return baseline


def save_baseline(baseline: Dict[str, Any], output_path: Path):
    """
    Save baseline to file.
    
    Args:
        baseline: Baseline metrics
        output_path: Output file path
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(baseline, f, indent=2)
    
    logger.info(f"Baseline saved to: {output_path}")


def main():
    """Main function."""
    # Capture baseline
    baseline = capture_baseline()
    
    # Save to file
    output_path = Path("data/baseline_metrics.json")
    save_baseline(baseline, output_path)
    
    # Print summary
    print("\n" + "="*60)
    print("BASELINE METRICS SUMMARY")
    print("="*60)
    print(f"Total Queries: {baseline['overall_stats']['total_queries']}")
    print(f"Avg Latency: {baseline['overall_stats'].get('avg_latency_ms', 0):.1f}ms")
    print(f"Avg Chunks Retrieved: {baseline['overall_stats'].get('avg_chunks_retrieved', 0):.1f}")
    print("\nBy Query Type:")
    for query_type, results in baseline['queries_by_type'].items():
        successful = sum(1 for r in results if r.get('success', False))
        print(f"  {query_type}: {successful}/{len(results)} successful")
    print("="*60)


if __name__ == "__main__":
    main()
```

**Run Baseline Capture**:
```bash
python scripts/capture_baseline_metrics.py
```

---

## Summary of Next Steps

### Immediate Work (8-10 hours)

1. ✅ **RAG Integration** (3-4 hours)
   - Update `advisor/rag_retrieval.py`
   - Add monitoring calls
   - Test integration

2. ✅ **Router Updates** (1-2 hours)
   - Update `advisor/collection_router.py`
   - Use query classification
   - Test routing

3. ✅ **Unit Tests** (2-3 hours)
   - Create `tests/test_monitoring.py`
   - Test all components
   - Ensure 100% pass rate

4. ✅ **Baseline Capture** (2 hours)
   - Create `scripts/capture_baseline_metrics.py`
   - Run baseline capture
   - Save metrics for comparison

### After Completion

**Phase 1 Complete**: Full monitoring operational
**Phase 2 Next**: Implement collection-specific parameters
**Phase 3 Final**: Re-ingest and validate improvements

---

## Success Criteria

### Phase 1 Complete When:
- ✅ All monitoring components integrated
- ✅ Every query tracked with full metrics
- ✅ MLflow logging operational
- ✅ All tests passing
- ✅ Baseline metrics captured

### Expected Outcome:
- Complete visibility into RAG quality
- Data-driven optimization capability
- Foundation for continuous improvement

---

## Notes

- Keep monitoring overhead low (<50ms per query)
- Log to MLflow asynchronously if possible
- Cache classification results for repeated queries
- Monitor monitoring system performance

---

## Contact

For questions or issues, refer to:
- `docs/design/MONITORING_IMPLEMENTATION_STATUS.md`
- `docs/design/QUERY_CLASSIFICATION_AND_TRACKING.md`
- Implementation files in `advisor/`