# Performance and Quality Analysis

## Current Issues

### 1. MLflow Error Still Occurring
**Error:** "generator didn't stop after throw()"
**Status:** The refactoring didn't fully resolve the issue

**Root Cause Analysis:**
The error persists because the MLflow tracking is still being called from within the LRU cache wrapper. The issue is more fundamental - we need to either:
1. Remove MLflow tracking from the conversation agent entirely
2. Use a different caching mechanism that doesn't interfere with context managers
3. Implement tracking at a higher level (in the CLI layer)

**Recommended Solution:**
Disable MLflow tracking in conversation agent and implement it at the CLI layer instead:
```python
# In advisor/cli/agent_session.py
def _handle_query(self, query: str):
    start_time = time.time()
    
    # Track at CLI level, not inside agent
    if self.mlflow_tracker:
        with self.mlflow_tracker.track_operation(...):
            result = self.agent.run(query, use_rag=True)
            # Log metrics here
    else:
        result = self.agent.run(query, use_rag=True)
```

### 2. Performance: 60+ Seconds Per Query

**Current Performance Issues:**

#### A. Multiple Collection Searches
The system searches multiple collections sequentially:
- pyegeria (10,000+ chunks)
- pyegeria_cli (5,000+ chunks)  
- pyegeria_drE (3,000+ chunks)
- egeria_docs (20,000+ chunks)
- egeria_java (50,000+ chunks)

**Each search involves:**
1. Embedding generation (200-500ms)
2. Vector search in Milvus (100-300ms per collection)
3. Re-ranking results (50-100ms)

**Total time for 3 collections:** 1-2 seconds just for retrieval

#### B. LLM Generation Time
- Model: llama3.1:8b (8 billion parameters)
- Generation time: 30-60 seconds for 500-1000 tokens
- This is the main bottleneck

#### C. No GPU Acceleration Detected
The slow generation suggests CPU-only inference. Need to verify:
```bash
# Check if AMD GPU is being used
rocm-smi
ollama ps  # Shows which device Ollama is using
```

### 3. Hallucinations

**Causes:**
1. **Insufficient Context:** RAG retrieval may not be finding relevant examples
2. **Wrong Collections Searched:** Code examples might be in different collections
3. **Model Limitations:** llama3.1:8b may not have enough capacity for code generation
4. **Poor Prompt Engineering:** Context not being used effectively

**Example Query:** "Give me a pyegeria example to create a digital product"
- Should search: pyegeria (tests directory has many examples), egeria_workspaces
- Currently searches: Likely pyegeria, egeria_docs (based on priority)
- **Key Insight:** pyegeria collection includes tests directory with extensive code examples
- The tests directory in pyegeria is the primary source of working code examples

## Recommendations

### 1. RAG Parameter Tuning

**Current Parameters (likely):**
```python
top_k = 5  # Number of chunks retrieved
chunk_size = 1000  # Characters per chunk
overlap = 200  # Overlap between chunks
```

**Recommended Changes:**

#### For Code Examples:
```python
# In advisor/rag_retrieval.py or collection config
CODE_EXAMPLE_PARAMS = {
    "top_k": 10,  # More examples
    "min_score": 0.7,  # Higher relevance threshold
    "prefer_complete_functions": True,  # Whole functions, not fragments
    "include_docstrings": True
}
```

#### For General Information:
```python
GENERAL_INFO_PARAMS = {
    "top_k": 5,  # Fewer chunks
    "min_score": 0.6,  # Lower threshold for broader context
    "prefer_documentation": True
}
```

**Implementation:**
```python
# In advisor/collection_router.py
def route_query_with_params(self, query: str) -> Dict[str, Any]:
    """Route query and determine optimal RAG parameters."""
    query_type = self._detect_query_type(query)
    
    if query_type == "code_example":
        return {
            "collections": ["pyegeria", "egeria_workspaces", "pyegeria_cli"],
            "top_k": 10,
            "min_score": 0.7,
            "prefer_collections": ["egeria_workspaces"]  # Examples first
        }
    elif query_type == "documentation":
        return {
            "collections": ["egeria_docs", "pyegeria"],
            "top_k": 5,
            "min_score": 0.6
        }
    # ... more query types
```

### 2. AMD GPU Acceleration

**Check Current Status:**
```bash
# 1. Verify ROCm installation
rocm-smi

# 2. Check Ollama GPU usage
ollama ps

# 3. Check Ollama configuration
cat ~/.ollama/config.json
```

**Enable GPU Acceleration:**
```bash
# Set environment variables
export HSA_OVERRIDE_GFX_VERSION=10.3.0  # For AMD GPUs
export OLLAMA_GPU_LAYERS=33  # Use GPU for all layers

# Restart Ollama
systemctl --user restart ollama
```

**Verify in Code:**
```python
# In advisor/llm_client.py
def __init__(self):
    # Check GPU availability
    import subprocess
    result = subprocess.run(['rocm-smi'], capture_output=True)
    if result.returncode == 0:
        logger.info("AMD GPU detected and available")
    else:
        logger.warning("AMD GPU not detected - using CPU")
```

**Expected Performance Improvement:**
- CPU: 30-60 seconds per query
- GPU: 3-8 seconds per query (10x faster)

### 3. Different Models for Different Tasks

**Recommended Model Strategy:**

#### For Code Examples:
```python
CODE_MODEL = "codellama:7b"  # Specialized for code
# OR
CODE_MODEL = "deepseek-coder:6.7b"  # Better code understanding
```

#### For General Information:
```python
GENERAL_MODEL = "llama3.1:8b"  # Current model, good for general Q&A
```

#### For Documentation:
```python
DOCS_MODEL = "mistral:7b"  # Fast, good for factual responses
```

**Implementation:**
```python
# In advisor/agents/conversation_agent.py
class ConversationAgent:
    def __init__(self, ...):
        self.models = {
            "code": get_ollama_client(model="codellama:7b"),
            "general": get_ollama_client(model="llama3.1:8b"),
            "docs": get_ollama_client(model="mistral:7b")
        }
    
    def _select_model(self, query: str, query_type: str):
        """Select appropriate model based on query type."""
        if "example" in query.lower() or "code" in query.lower():
            return self.models["code"]
        elif "documentation" in query.lower():
            return self.models["docs"]
        return self.models["general"]
```

### 4. Multi-Collection Assembly Strategy

**Current Approach:** Sequential search of multiple collections
**Problem:** Slow, redundant, may miss best results

**Recommended Approach:** Parallel search with intelligent assembly

```python
# In advisor/rag_retrieval.py
import asyncio
from concurrent.futures import ThreadPoolExecutor

class MultiCollectionRetriever:
    def retrieve_parallel(self, query: str, collections: List[str]) -> List[Result]:
        """Search multiple collections in parallel."""
        with ThreadPoolExecutor(max_workers=len(collections)) as executor:
            futures = {
                executor.submit(self._search_collection, query, col): col
                for col in collections
            }
            
            all_results = []
            for future in futures:
                collection = futures[future]
                try:
                    results = future.result(timeout=5.0)  # 5 second timeout
                    all_results.extend(results)
                except Exception as e:
                    logger.warning(f"Collection {collection} search failed: {e}")
        
        # Re-rank combined results
        return self._rerank_results(all_results, query)
    
    def _rerank_results(self, results: List[Result], query: str) -> List[Result]:
        """Re-rank results from multiple collections."""
        # Boost results from preferred collections
        for result in results:
            if result.metadata.get('collection') == 'egeria_workspaces':
                result.score *= 1.2  # Boost example collection
        
        # Sort by adjusted score
        return sorted(results, key=lambda r: r.score, reverse=True)[:10]
```

**Expected Performance:**
- Sequential: 3 collections × 300ms = 900ms
- Parallel: max(300ms) = 300ms (3x faster)

### 5. Query-Specific Routing

**Implement Smart Routing:**

```python
# In advisor/collection_router.py
def route_code_example_query(self, query: str) -> Dict[str, Any]:
    """Special routing for code example queries."""
    # Extract what they want to create
    entities = self._extract_entities(query)  # "digital product"
    
    return {
        "primary_collections": [
            "egeria_workspaces",  # Jupyter notebooks with examples
            "pyegeria"  # Core library code
        ],
        "fallback_collections": [
            "pyegeria_cli",  # CLI examples
            "egeria_docs"  # Documentation
        ],
        "search_strategy": "parallel",
        "top_k": 10,
        "prefer_complete_examples": True,
        "filter_by_entity": entities  # Only chunks mentioning "digital product"
    }
```

## Implementation Priority

### High Priority (Fix Now)
1. **Disable MLflow in conversation agent** - Fixes the error
2. **Verify GPU acceleration** - 10x performance improvement
3. **Add egeria_workspaces to code example routing** - Fixes hallucinations

### Medium Priority (Next Sprint)
4. **Implement parallel collection search** - 3x faster retrieval
5. **Add query-type specific parameters** - Better relevance
6. **Implement model selection by query type** - Better quality

### Low Priority (Future)
7. **Advanced re-ranking** - Marginal improvements
8. **Caching layer** - Only helps repeated queries
9. **Query expansion** - Complex, may not help

## Testing Plan

```bash
# 1. Test with GPU
export HSA_OVERRIDE_GFX_VERSION=10.3.0
egeria-advisor --interactive --agent
# Query: "Give me a pyegeria example to create a digital product"
# Expected: < 10 seconds, actual code example

# 2. Test routing
python scripts/test_routing_fix.py
# Verify egeria_workspaces is searched for code examples

# 3. Test different models
# Edit advisor/llm_client.py to use codellama:7b
egeria-advisor --interactive
# Query: "Show me code to create a glossary"
# Expected: Better code quality
```

## Metrics to Track

1. **Query Latency:**
   - Target: < 10 seconds (with GPU)
   - Current: 60+ seconds

2. **Relevance:**
   - Target: 80%+ of queries get relevant results
   - Measure: User feedback (positive/negative)

3. **Hallucination Rate:**
   - Target: < 10% of responses contain hallucinations
   - Measure: Manual review + user feedback

4. **Collection Hit Rate:**
   - Target: Correct collection searched 90%+ of time
   - Measure: Log analysis