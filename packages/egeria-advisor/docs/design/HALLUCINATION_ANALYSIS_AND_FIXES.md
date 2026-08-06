# Hallucination Analysis and Fixes

## Problem Statement

**Observation**: >80% hallucination rate, especially for Egeria documentation questions

**Critical Issue**: The RAG system is not providing relevant context to the LLM, causing it to generate fabricated answers instead of using retrieved information.

---

## Root Cause Analysis

### 1. Chunk Granularity Issues

**Current Settings** (`config/advisor.yaml`):
```yaml
rag:
  chunk_size: 512
  chunk_overlap: 50
```

**Problems**:
- **512 tokens is too small** for documentation
- Documentation concepts span multiple paragraphs
- Context is fragmented across chunks
- Overlap of 50 tokens is insufficient (only 10%)

**Evidence**:
- Diagnostic showed markdown docs retrieved but no code
- File type boosting can't fix if chunks don't contain complete concepts

### 2. Embedding Model Limitations

**Current Model**: `sentence-transformers/all-MiniLM-L6-v2`
- **Dimension**: 384 (small)
- **Max length**: 256 tokens (very limited)
- **Training**: General domain, not code/documentation specific

**Problems**:
- Truncates long documentation passages
- Not optimized for technical documentation
- Poor semantic understanding of Egeria concepts

### 3. Collection Routing Issues

**Diagnostic Results**:
- Query "show me a test example for creating a glossary"
- Routed to: `egeria_workspaces` only
- Should route to: `pyegeria` + `egeria_docs`

**Problem**: Documentation queries don't search code collections

### 4. Retrieval Quality

**Current Scores**: 0.30-0.47 (low to medium)
- Scores below 0.5 indicate poor semantic match
- Retrieved chunks may not answer the question
- LLM receives irrelevant context

### 5. Prompt Engineering

**Current**: Generic RAG prompt
**Problem**: Doesn't emphasize using retrieved context
**Result**: LLM ignores context and hallucinates

---

## Solutions (Priority Order)

### 🔴 CRITICAL: Fix Chunk Granularity

**Problem**: 512 tokens too small for documentation

**Solution 1: Increase Chunk Size**
```yaml
rag:
  chunk_size: 1024      # Double size for complete concepts
  chunk_overlap: 200    # 20% overlap for context continuity
```

**Solution 2: Adaptive Chunking**
- Code: 512 tokens (current)
- Documentation: 1024 tokens
- Markdown headers: Use as natural boundaries

**Implementation**:
```python
# In data_prep/pipeline.py
def get_chunk_size(file_path: str) -> int:
    if file_path.endswith('.md'):
        return 1024  # Documentation needs larger chunks
    elif file_path.endswith('.py'):
        return 512   # Code is more modular
    return 768       # Default
```

### 🔴 CRITICAL: Upgrade Embedding Model

**Current**: `all-MiniLM-L6-v2` (384 dim, 256 tokens)

**Recommended Models**:

1. **`all-mpnet-base-v2`** (Best balance)
   - Dimension: 768 (2x better)
   - Max length: 384 tokens
   - Better semantic understanding
   - Still fast enough

2. **`gte-large`** (Best quality)
   - Dimension: 1024
   - Max length: 512 tokens
   - State-of-the-art performance
   - Slower but much better

3. **`bge-large-en-v1.5`** (Best for retrieval)
   - Dimension: 1024
   - Optimized for RAG
   - Excellent for documentation

**Implementation**:
```yaml
# config/advisor.yaml
embeddings:
  model: sentence-transformers/all-mpnet-base-v2  # Upgrade
  device: auto
  batch_size: 32  # Reduce for larger model
  normalize: true
  max_length: 384  # Increased
```

**Migration**:
```bash
# Re-embed all collections with new model
python scripts/reingest_with_new_embeddings.py
```

### 🟡 HIGH: Fix Collection Routing

**Problem**: Documentation queries don't search code collections

**Solution**: Add cross-collection routing rules

```python
# In advisor/collection_router.py
CROSS_COLLECTION_RULES = {
    'documentation': ['egeria_docs', 'pyegeria', 'egeria_workspaces'],
    'code_example': ['pyegeria', 'egeria_workspaces', 'egeria_docs'],
    'concept': ['egeria_docs', 'egeria_java', 'pyegeria'],
}
```

### 🟡 HIGH: Improve Prompt Engineering

**Current Problem**: Generic prompt doesn't emphasize context

**Solution**: Explicit instruction to use retrieved context

```python
ENHANCED_PROMPT = """You are an expert on Egeria and pyegeria.

CRITICAL INSTRUCTIONS:
1. ONLY answer based on the provided context below
2. If the context doesn't contain the answer, say "I don't have enough information"
3. NEVER make up information or code examples
4. Quote relevant parts of the context in your answer
5. If you see code examples in the context, use them directly

Context:
{context}

Question: {question}

Answer (based ONLY on the context above):"""
```

### 🟡 HIGH: Increase Retrieval Threshold

**Current**: `min_score: 0.30` (too low)

**Problem**: Allows irrelevant chunks

**Solution**: Dynamic threshold based on query type

```python
def get_min_score(query_type: str) -> float:
    if query_type == 'documentation':
        return 0.45  # Higher for docs (need relevance)
    elif query_type == 'code':
        return 0.35  # Medium for code
    else:
        return 0.30  # Default
```

### 🟢 MEDIUM: Hybrid Search

**Problem**: Pure vector search misses exact term matches

**Solution**: Combine vector + keyword search

```python
# Pseudo-code
def hybrid_search(query, top_k=10):
    # Vector search (semantic)
    vector_results = vector_search(query, top_k=top_k)
    
    # Keyword search (exact matches)
    keyword_results = keyword_search(query, top_k=top_k//2)
    
    # Merge with RRF (Reciprocal Rank Fusion)
    return merge_results(vector_results, keyword_results)
```

### 🟢 MEDIUM: Re-ranking

**Problem**: Initial retrieval may not be optimal

**Solution**: Use cross-encoder for re-ranking

```python
from sentence_transformers import CrossEncoder

reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

def rerank_results(query, results, top_k=5):
    # Score each result with cross-encoder
    pairs = [(query, r.content) for r in results]
    scores = reranker.predict(pairs)
    
    # Re-sort by cross-encoder scores
    reranked = sorted(zip(results, scores), 
                     key=lambda x: x[1], 
                     reverse=True)
    
    return [r for r, s in reranked[:top_k]]
```

---

## Implementation Plan

### Phase 1: Quick Wins (1-2 hours)

1. **Increase chunk size**: 512 → 1024 for documentation
2. **Improve prompt**: Add explicit instructions
3. **Increase min_score**: 0.30 → 0.40 for docs
4. **Fix routing**: Add cross-collection rules

**Expected Impact**: 30-40% reduction in hallucinations

### Phase 2: Model Upgrade (2-4 hours)

1. **Upgrade embedding model**: all-MiniLM-L6-v2 → all-mpnet-base-v2
2. **Re-ingest collections**: With new embeddings
3. **Test retrieval quality**: Run diagnostics

**Expected Impact**: 40-50% reduction in hallucinations

### Phase 3: Advanced Features (4-8 hours)

1. **Implement hybrid search**: Vector + keyword
2. **Add re-ranking**: Cross-encoder
3. **Adaptive chunking**: File-type specific

**Expected Impact**: 60-70% reduction in hallucinations

---

## Diagnostic Commands

### 1. Check Current Chunk Sizes
```bash
# Analyze chunk distribution
python scripts/analyze_chunk_sizes.py
```

### 2. Test Embedding Quality
```bash
# Compare embedding models
python scripts/compare_embeddings.py
```

### 3. Measure Retrieval Quality
```bash
# Run diagnostic with different settings
python scripts/diagnose_rag_quality.py --min-score 0.4 --top-k 15
```

### 4. Test Prompt Variations
```bash
# A/B test prompts
python scripts/test_prompts.py
```

---

## Expected Results

### Current State
- Hallucination rate: >80%
- Retrieval scores: 0.30-0.47
- Chunk size: 512 tokens
- Embedding dim: 384

### After Phase 1 (Quick Wins)
- Hallucination rate: ~50%
- Retrieval scores: 0.40-0.60
- Chunk size: 1024 tokens (docs)
- Better prompts

### After Phase 2 (Model Upgrade)
- Hallucination rate: ~30%
- Retrieval scores: 0.50-0.70
- Embedding dim: 768
- Better semantic matching

### After Phase 3 (Advanced)
- Hallucination rate: ~15-20%
- Retrieval scores: 0.60-0.80
- Hybrid search
- Re-ranking

---

## Monitoring Improvements

### Key Metrics to Track

1. **Hallucination Rate**
   - Use feedback system
   - Track "not helpful" responses

2. **Retrieval Quality**
   - Average relevance score
   - % of queries with score >0.5

3. **Context Usage**
   - Does LLM use retrieved context?
   - Track citations/quotes

4. **User Satisfaction**
   - Feedback ratings
   - Follow-up question rate

---

## Immediate Action Items

### 1. Quick Fix (Do Now)
```bash
# Update config
vim config/advisor.yaml
# Change:
# chunk_size: 512 → 1024
# min_score: 0.30 → 0.40

# Re-ingest egeria_docs with larger chunks
python scripts/reingest_collection.py egeria_docs --chunk-size 1024
```

### 2. Test Improvement
```bash
# Run diagnostic
python scripts/diagnose_rag_quality.py

# Test specific query
python -m advisor.cli.main agent
> what is a digital product in Egeria?
# Check if answer uses documentation
```

### 3. Measure Impact
```bash
# Compare before/after
python scripts/compare_hallucination_rate.py
```

---

## Root Cause Summary

**Why >80% hallucination rate?**

1. **Chunks too small** (512 tokens)
   - Documentation concepts fragmented
   - Context incomplete

2. **Embedding model weak** (384 dim)
   - Poor semantic understanding
   - Truncates long passages

3. **Routing issues**
   - Documentation queries miss code collections
   - Cross-collection search needed

4. **Low retrieval threshold** (0.30)
   - Allows irrelevant chunks
   - LLM receives noise

5. **Generic prompts**
   - Doesn't emphasize using context
   - LLM defaults to hallucination

**The Fix**: Larger chunks + better embeddings + improved routing + explicit prompts

---

## References

- Embedding models: https://huggingface.co/spaces/mteb/leaderboard
- Chunking strategies: https://www.pinecone.io/learn/chunking-strategies/
- RAG best practices: https://www.anthropic.com/research/retrieval-augmented-generation