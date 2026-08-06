# Query Classification and Collection-Level Tracking Design

## Overview

This document describes the enhanced monitoring system that classifies queries, tracks collection-level performance, and provides detailed MLflow metrics for RAG quality analysis.

## Problem Statement

**Current State**:
- Queries tracked but not classified by type/intent
- No per-collection performance metrics
- No visibility into routing decisions
- Hard to diagnose which collections perform poorly
- Can't measure hallucination rate by query type

**Desired State**:
- Automatic query classification (concept/type/code/example/general)
- Per-collection retrieval metrics (precision, recall, latency)
- Routing decision tracking (which collections searched, why)
- Document assembly metrics (how chunks combined)
- MLflow integration for all metrics
- Hallucination detection per query type

## Query Classification System

### 1. Query Types

```python
class QueryType(Enum):
    """Types of user queries."""
    CONCEPT = "concept"           # "What is X?" - definitions
    TYPE = "type"                 # "What properties does X have?" - type system
    CODE = "code"                 # "Show me code for X" - implementation
    EXAMPLE = "example"           # "Give me an example of X" - usage examples
    TUTORIAL = "tutorial"         # "How do I X?" - step-by-step guides
    TROUBLESHOOTING = "troubleshooting"  # "Why doesn't X work?" - debugging
    COMPARISON = "comparison"     # "What's the difference between X and Y?"
    GENERAL = "general"           # General questions
```

### 2. Classification Rules

**Concept Queries**:
- Keywords: "what is", "define", "explain", "meaning of", "definition"
- Expected collections: egeria_concepts (primary), egeria_types (secondary)
- Expected chunk size: 768 tokens
- Expected min_score: 0.45 (high precision)

**Type Queries**:
- Keywords: "type", "property", "attribute", "field", "schema", "structure"
- Expected collections: egeria_types (primary), egeria_concepts (secondary)
- Expected chunk size: 1024 tokens
- Expected min_score: 0.42

**Code Queries**:
- Keywords: "code", "implementation", "function", "class", "method", "show me"
- Expected collections: pyegeria, pyegeria_cli, egeria_java
- Expected chunk size: 512 tokens
- Expected min_score: 0.35

**Example Queries**:
- Keywords: "example", "sample", "demo", "how to use", "usage"
- Expected collections: egeria_workspaces, pyegeria (tests)
- Expected chunk size: 1536 tokens
- Expected min_score: 0.38

**Tutorial Queries**:
- Keywords: "how do i", "tutorial", "guide", "step by step", "walkthrough"
- Expected collections: egeria_general, egeria_workspaces
- Expected chunk size: 1536 tokens
- Expected min_score: 0.38

**Troubleshooting Queries**:
- Keywords: "error", "doesn't work", "problem", "issue", "fix", "debug"
- Expected collections: egeria_general, pyegeria (tests), egeria_workspaces
- Expected chunk size: 1024 tokens
- Expected min_score: 0.35

**Comparison Queries**:
- Keywords: "difference", "compare", "versus", "vs", "better", "which"
- Expected collections: egeria_concepts, egeria_types, egeria_general
- Expected chunk size: 1024 tokens
- Expected min_score: 0.40

### 3. Topic Extraction

Extract domain-specific topics from queries:

```python
class QueryTopic(Enum):
    """Domain topics in queries."""
    GLOSSARY = "glossary"
    ASSET = "asset"
    METADATA = "metadata"
    GOVERNANCE = "governance"
    LINEAGE = "lineage"
    INTEGRATION = "integration"
    CONNECTOR = "connector"
    SERVER = "server"
    PLATFORM = "platform"
    API = "api"
    CLI = "cli"
    CONFIGURATION = "configuration"
    SECURITY = "security"
    UNKNOWN = "unknown"
```

**Topic Detection**:
- Use domain_terms from collection_config.py
- Match query against term lists
- Support multiple topics per query
- Track topic distribution over time

## Collection-Level Metrics

### 1. Per-Collection Retrieval Metrics

Track for each collection searched:

```python
@dataclass
class CollectionRetrievalMetrics:
    """Metrics for a single collection search."""
    collection_name: str
    query_type: QueryType
    query_topics: List[QueryTopic]
    
    # Search metrics
    search_time_ms: float
    chunks_retrieved: int
    chunks_above_threshold: int
    avg_score: float
    max_score: float
    min_score: float
    
    # Ranking metrics
    chunks_in_final_context: int
    avg_rank_in_final: float  # Average position in merged results
    
    # Quality metrics
    relevance_score: Optional[float]  # From user feedback
    hallucination_detected: bool
    
    # Routing metrics
    was_primary_collection: bool
    routing_confidence: float
```

### 2. Document Assembly Metrics

Track how chunks are combined:

```python
@dataclass
class DocumentAssemblyMetrics:
    """Metrics for document assembly from multiple collections."""
    query_type: QueryType
    query_topics: List[QueryTopic]
    
    # Collection distribution
    collections_searched: List[str]
    collections_contributed: Dict[str, int]  # collection -> chunk count
    
    # Re-ranking metrics
    reranking_time_ms: float
    file_type_boosts_applied: Dict[str, float]  # file_type -> avg boost
    
    # Context building
    total_chunks_retrieved: int
    total_chunks_used: int
    context_length_chars: int
    context_truncated: bool
    
    # Cross-collection metrics
    chunk_diversity_score: float  # How diverse are sources?
    collection_overlap_score: float  # How much overlap between collections?
```

### 3. Query Lifecycle Metrics

Track entire query lifecycle:

```python
@dataclass
class QueryLifecycleMetrics:
    """Complete metrics for a query lifecycle."""
    query_id: str
    timestamp: float
    query_text: str
    query_type: QueryType
    query_topics: List[QueryTopic]
    
    # Classification
    classification_confidence: float
    classification_time_ms: float
    
    # Routing
    routing_strategy: str  # "targeted", "expanded", "default"
    routing_time_ms: float
    collections_routed: List[str]
    
    # Retrieval (per collection)
    collection_metrics: List[CollectionRetrievalMetrics]
    
    # Assembly
    assembly_metrics: DocumentAssemblyMetrics
    
    # LLM generation
    llm_time_ms: float
    llm_tokens_input: int
    llm_tokens_output: int
    
    # Total
    total_latency_ms: float
    
    # Quality (if available)
    user_feedback_score: Optional[float]
    hallucination_detected: bool
    answer_quality_score: Optional[float]
```

## MLflow Integration

### 1. Experiment Structure

```
egeria-advisor/
├── query-classification/
│   ├── run-{timestamp}/
│   │   ├── params/
│   │   │   ├── query_type
│   │   │   ├── query_topics
│   │   │   ├── routing_strategy
│   │   │   └── collections_searched
│   │   ├── metrics/
│   │   │   ├── classification_confidence
│   │   │   ├── total_latency_ms
│   │   │   ├── collection_{name}_search_time_ms
│   │   │   ├── collection_{name}_chunks_retrieved
│   │   │   ├── collection_{name}_avg_score
│   │   │   ├── assembly_time_ms
│   │   │   ├── context_length_chars
│   │   │   ├── llm_time_ms
│   │   │   ├── user_feedback_score
│   │   │   └── hallucination_detected
│   │   └── artifacts/
│   │       ├── query_details.json
│   │       ├── routing_decision.json
│   │       ├── collection_results.json
│   │       └── final_context.txt
```

### 2. Metrics to Track

**Classification Metrics**:
- `query_type`: Classified query type
- `query_topics`: Detected topics (as tags)
- `classification_confidence`: Confidence score (0-1)
- `classification_time_ms`: Time to classify

**Routing Metrics**:
- `routing_strategy`: "targeted", "expanded", "default"
- `routing_time_ms`: Time to route
- `collections_searched`: Number of collections
- `primary_collection`: Primary collection name

**Per-Collection Metrics** (prefix with `collection_{name}_`):
- `search_time_ms`: Search latency
- `chunks_retrieved`: Total chunks found
- `chunks_above_threshold`: Chunks passing min_score
- `chunks_in_final`: Chunks in final context
- `avg_score`: Average similarity score
- `max_score`: Best similarity score
- `avg_rank_in_final`: Average position in merged results

**Assembly Metrics**:
- `assembly_time_ms`: Re-ranking and merging time
- `total_chunks_retrieved`: Sum across collections
- `total_chunks_used`: Chunks in final context
- `context_length_chars`: Final context size
- `context_truncated`: Boolean
- `chunk_diversity_score`: Source diversity (0-1)

**LLM Metrics**:
- `llm_time_ms`: Generation time
- `llm_tokens_input`: Input tokens
- `llm_tokens_output`: Output tokens

**Quality Metrics**:
- `user_feedback_score`: User rating (1-5)
- `hallucination_detected`: Boolean
- `answer_quality_score`: Computed quality (0-1)

**Total Metrics**:
- `total_latency_ms`: End-to-end latency
- `cache_hit`: Boolean

### 3. Tags to Set

```python
tags = {
    "query_type": query_type.value,
    "query_topics": ",".join([t.value for t in query_topics]),
    "routing_strategy": routing_strategy,
    "collections_searched": ",".join(collections_searched),
    "primary_collection": primary_collection,
    "cache_hit": str(cache_hit),
    "hallucination_detected": str(hallucination_detected),
}
```

### 4. Artifacts to Log

**query_details.json**:
```json
{
  "query_id": "uuid",
  "timestamp": 1234567890.123,
  "query_text": "What is a glossary?",
  "query_type": "concept",
  "query_topics": ["glossary"],
  "classification_confidence": 0.95
}
```

**routing_decision.json**:
```json
{
  "strategy": "targeted",
  "collections_searched": ["egeria_concepts", "egeria_types"],
  "primary_collection": "egeria_concepts",
  "routing_confidence": 0.88,
  "routing_time_ms": 5.2
}
```

**collection_results.json**:
```json
{
  "egeria_concepts": {
    "search_time_ms": 45.3,
    "chunks_retrieved": 8,
    "chunks_above_threshold": 5,
    "chunks_in_final": 3,
    "avg_score": 0.72,
    "max_score": 0.89,
    "scores": [0.89, 0.78, 0.72, 0.65, 0.58]
  },
  "egeria_types": {
    "search_time_ms": 38.7,
    "chunks_retrieved": 6,
    "chunks_above_threshold": 2,
    "chunks_in_final": 1,
    "avg_score": 0.58,
    "max_score": 0.68,
    "scores": [0.68, 0.62, 0.55, 0.48]
  }
}
```

**final_context.txt**:
```
The assembled context sent to the LLM, with source annotations.
```

## Implementation Plan

### Phase 1: Query Classification (2 hours)

**File**: `advisor/query_classifier.py` (NEW)

```python
class QueryClassifier:
    """Classify queries by type and topic."""
    
    def classify(self, query: str) -> Tuple[QueryType, List[QueryTopic], float]:
        """
        Classify query by type and topics.
        
        Returns:
            (query_type, topics, confidence)
        """
        pass
```

**Features**:
- Pattern matching for query types
- Domain term matching for topics
- Confidence scoring
- Support for ambiguous queries

### Phase 2: Collection Metrics Tracking (3 hours)

**File**: `advisor/collection_metrics.py` (NEW)

```python
class CollectionMetricsTracker:
    """Track per-collection retrieval metrics."""
    
    def track_collection_search(
        self,
        collection_name: str,
        query_type: QueryType,
        results: List[SearchResult],
        search_time_ms: float
    ) -> CollectionRetrievalMetrics:
        """Track metrics for a single collection search."""
        pass
```

**Features**:
- Per-collection timing
- Score distribution analysis
- Ranking position tracking
- Quality metrics integration

### Phase 3: Document Assembly Tracking (2 hours)

**File**: `advisor/assembly_metrics.py` (NEW)

```python
class AssemblyMetricsTracker:
    """Track document assembly metrics."""
    
    def track_assembly(
        self,
        collections_searched: List[str],
        collection_results: Dict[str, List[SearchResult]],
        final_results: List[SearchResult],
        assembly_time_ms: float
    ) -> DocumentAssemblyMetrics:
        """Track metrics for document assembly."""
        pass
```

**Features**:
- Collection contribution analysis
- Re-ranking metrics
- Context building metrics
- Diversity scoring

### Phase 4: MLflow Integration (3 hours)

**File**: `advisor/mlflow_tracking.py` (UPDATE)

Add methods:
```python
def track_query_lifecycle(
    self,
    query_metrics: QueryLifecycleMetrics
):
    """Track complete query lifecycle in MLflow."""
    pass

def track_collection_performance(
    self,
    collection_metrics: CollectionRetrievalMetrics
):
    """Track per-collection performance."""
    pass
```

**Features**:
- Structured experiment logging
- Per-collection metrics
- Artifact logging
- Tag management

### Phase 5: Integration with RAG System (2 hours)

**Files**: 
- `advisor/rag_retrieval.py` (UPDATE)
- `advisor/multi_collection_store.py` (UPDATE)
- `advisor/collection_router.py` (UPDATE)

**Changes**:
- Add classification step before retrieval
- Track metrics at each stage
- Log to MLflow
- Store in metrics database

### Phase 6: Dashboard Updates (2 hours)

**Files**:
- `advisor/dashboard/terminal_dashboard.py` (UPDATE)
- `advisor/dashboard/streamlit_dashboard.py` (UPDATE)

**New Views**:
- Query type distribution
- Per-collection performance
- Routing effectiveness
- Hallucination rate by query type
- Topic trends

## Expected Benefits

### 1. Quality Insights

**Before**:
- "80% hallucination rate" - no breakdown
- Can't tell which collections are problematic
- No visibility into routing decisions

**After**:
- "Concept queries: 20% hallucination (egeria_concepts working well)"
- "Code queries: 35% hallucination (pyegeria needs tuning)"
- "Type queries: 25% hallucination (egeria_types good)"
- "Routing to wrong collections 15% of the time"

### 2. Performance Optimization

**Identify Bottlenecks**:
- "egeria_java searches take 2x longer than pyegeria"
- "Re-ranking adds 50ms overhead"
- "Context truncation happening 30% of the time"

**Optimize Parameters**:
- "Concept queries need min_score=0.45 (currently 0.35)"
- "Code queries should use top_k=15 (currently 10)"
- "Type queries benefit from chunk_size=1024 (currently 512)"

### 3. Routing Improvements

**Measure Effectiveness**:
- "Targeted routing: 85% success rate"
- "Default routing: 60% success rate"
- "Expanded routing: 70% success rate"

**Identify Misroutes**:
- "Concept queries routed to code collections 12% of time"
- "Example queries missing egeria_workspaces 8% of time"

### 4. Collection Health

**Per-Collection Quality**:
```
Collection Performance Report:
- egeria_concepts: 92% precision, 15ms avg latency, 5% hallucination
- egeria_types: 88% precision, 18ms avg latency, 8% hallucination
- pyegeria: 75% precision, 25ms avg latency, 20% hallucination
- egeria_java: 70% precision, 45ms avg latency, 25% hallucination
```

**Actionable Insights**:
- "egeria_java needs re-ingestion with better chunking"
- "pyegeria tests should be separate collection"
- "egeria_concepts performing excellently"

## MLflow Queries for Analysis

### 1. Query Type Performance

```python
# Get average hallucination rate by query type
runs = mlflow.search_runs(
    experiment_names=["egeria-advisor"],
    filter_string="tags.query_type = 'concept'"
)
hallucination_rate = runs["metrics.hallucination_detected"].mean()
```

### 2. Collection Effectiveness

```python
# Compare collection performance
for collection in ["egeria_concepts", "egeria_types", "pyegeria"]:
    runs = mlflow.search_runs(
        filter_string=f"tags.primary_collection = '{collection}'"
    )
    avg_score = runs[f"metrics.collection_{collection}_avg_score"].mean()
    avg_latency = runs[f"metrics.collection_{collection}_search_time_ms"].mean()
    print(f"{collection}: score={avg_score:.3f}, latency={avg_latency:.1f}ms")
```

### 3. Routing Analysis

```python
# Analyze routing strategies
for strategy in ["targeted", "expanded", "default"]:
    runs = mlflow.search_runs(
        filter_string=f"tags.routing_strategy = '{strategy}'"
    )
    success_rate = (1 - runs["metrics.hallucination_detected"]).mean()
    print(f"{strategy}: {success_rate:.1%} success rate")
```

### 4. Topic Trends

```python
# Track topic distribution over time
runs = mlflow.search_runs(
    experiment_names=["egeria-advisor"],
    order_by=["start_time DESC"]
)
topic_counts = runs["tags.query_topics"].value_counts()
```

## Testing Strategy

### 1. Unit Tests

Test each component:
- Query classification accuracy
- Metrics calculation correctness
- MLflow logging functionality

### 2. Integration Tests

Test end-to-end:
- Query → Classification → Routing → Retrieval → Assembly → MLflow
- Verify all metrics logged correctly
- Check artifact creation

### 3. Performance Tests

Measure overhead:
- Classification time: <5ms
- Metrics tracking time: <10ms
- MLflow logging time: <20ms
- Total overhead: <35ms (acceptable)

## Timeline

**Total: 14 hours**

1. Query Classification: 2 hours
2. Collection Metrics: 3 hours
3. Assembly Metrics: 2 hours
4. MLflow Integration: 3 hours
5. RAG Integration: 2 hours
6. Dashboard Updates: 2 hours

**Recommendation**: Implement in parallel with collection-specific parameters and egeria docs split.

## Success Metrics

After implementation, we should be able to answer:

1. **"Which query types have highest hallucination rate?"**
   - Answer: "Code queries: 35%, Concept queries: 20%"

2. **"Which collections perform best?"**
   - Answer: "egeria_concepts: 92% precision, pyegeria: 75%"

3. **"Is routing working correctly?"**
   - Answer: "Targeted routing: 85% success, Default: 60%"

4. **"Where should we focus optimization efforts?"**
   - Answer: "Improve pyegeria chunking, fix code query routing"

5. **"Are collection-specific parameters helping?"**
   - Answer: "Yes, concept queries improved from 85% → 20% hallucination"

## Conclusion

This enhanced monitoring system provides:

✅ **Query classification** - Understand what users are asking
✅ **Collection-level metrics** - Measure per-collection performance
✅ **Routing visibility** - See which collections searched and why
✅ **Assembly tracking** - Understand how chunks combined
✅ **MLflow integration** - Comprehensive experiment tracking
✅ **Actionable insights** - Data-driven optimization decisions

**This is essential infrastructure for maintaining and improving RAG quality over time.**