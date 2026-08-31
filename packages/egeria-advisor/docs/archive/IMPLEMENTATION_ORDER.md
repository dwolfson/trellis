# Implementation Order for Hallucination Fixes

## ⚠️ CRITICAL: Do NOT Re-ingest Yet!

**Why**: Re-ingestion is expensive (time + compute). Implement all changes first, then re-ingest once.

---

## Correct Order

### Phase 1: Code Changes (Do First) ✅

**Before any re-ingestion**, implement these code changes:

#### 1. Add Collection-Specific Parameters (30 min)

**File**: `advisor/collection_config.py`

Add parameters to `CollectionMetadata`:

```python
@dataclass
class CollectionMetadata:
    """Metadata for a Milvus collection."""
    
    # ... existing fields ...
    
    # NEW: Chunking parameters
    chunk_size: int = 512
    chunk_overlap: int = 100
    
    # NEW: Retrieval parameters  
    min_score: float = 0.35
    default_top_k: int = 10
    
    # NEW: Processing hints
    use_semantic_chunking: bool = False
    respect_boundaries: List[str] = field(default_factory=list)
```

Update each collection definition:

```python
PYEGERIA_COLLECTION = CollectionMetadata(
    name="pyegeria",
    # ... existing fields ...
    chunk_size=512,
    chunk_overlap=100,
    min_score=0.35,
    default_top_k=10,
    use_semantic_chunking=True,
    respect_boundaries=["function", "class"]
)

EGERIA_DOCS_COLLECTION = CollectionMetadata(
    name="egeria_docs",
    # ... existing fields ...
    chunk_size=1024,        # LARGER for docs
    chunk_overlap=200,
    min_score=0.40,         # HIGHER threshold
    default_top_k=8,
    use_semantic_chunking=True,
    respect_boundaries=["section", "heading"]
)

EGERIA_WORKSPACES_COLLECTION = CollectionMetadata(
    name="egeria_workspaces",
    # ... existing fields ...
    chunk_size=1536,        # LARGEST for narratives
    chunk_overlap=300,
    min_score=0.38,
    default_top_k=6,
    use_semantic_chunking=True,
    respect_boundaries=["step", "example"]
)

EGERIA_JAVA_COLLECTION = CollectionMetadata(
    name="egeria_java",
    # ... existing fields ...
    chunk_size=768,         # Larger than Python
    chunk_overlap=150,
    min_score=0.35,
    default_top_k=8,
    use_semantic_chunking=True,
    respect_boundaries=["method", "class"]
)
```

#### 2. Update Ingestion Pipeline (30 min)

**File**: `advisor/data_prep/pipeline.py`

Make chunking use collection parameters:

```python
def chunk_document(
    content: str,
    collection_name: str,
    file_path: str
) -> List[str]:
    """Chunk document using collection-specific parameters."""
    from advisor.collection_config import get_collection
    
    # Get collection metadata
    collection = get_collection(collection_name)
    if not collection:
        # Fallback to defaults
        chunk_size = 512
        chunk_overlap = 100
    else:
        chunk_size = collection.chunk_size
        chunk_overlap = collection.chunk_overlap
    
    # Use appropriate chunking strategy
    if file_path.endswith('.py'):
        return chunk_python_code(content, chunk_size, chunk_overlap)
    elif file_path.endswith('.md'):
        return chunk_markdown(content, chunk_size, chunk_overlap)
    else:
        return chunk_text(content, chunk_size, chunk_overlap)
```

#### 3. Update Retrieval to Use Collection Parameters (15 min)

**File**: `advisor/rag_retrieval.py`

Use collection-specific retrieval parameters:

```python
def retrieve(
    self,
    query: str,
    collection_names: Optional[List[str]] = None,
    top_k: Optional[int] = None,
    min_score: Optional[float] = None
) -> List[SearchResult]:
    """Retrieve with collection-specific parameters."""
    from advisor.collection_config import get_collection
    
    # If no override, use collection defaults
    if collection_names and not top_k:
        # Use first collection's default
        collection = get_collection(collection_names[0])
        if collection:
            top_k = collection.default_top_k
            min_score = min_score or collection.min_score
    
    # ... rest of retrieval logic ...
```

#### 4. Update Prompt Templates (15 min)

**File**: `advisor/prompt_templates.py`

Add explicit instructions:

```python
RAG_PROMPT_TEMPLATE = """You are an expert on Egeria and pyegeria.

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

Update agents to use new template:

**File**: `advisor/agents/conversation_agent.py`

```python
from advisor.prompt_templates import RAG_PROMPT_TEMPLATE

# Use in generate_response()
prompt = RAG_PROMPT_TEMPLATE.format(
    context=context,
    question=query
)
```

---

### Phase 2: Configuration Updates (5 min) ✅

**File**: `config/advisor.yaml`

Update global defaults (will be overridden by collection-specific):

```yaml
rag:
  chunk_size: 1024          # Increase default
  chunk_overlap: 200        # Increase overlap
  retrieval:
    top_k: 10               # Keep at 10
    min_score: 0.35         # Increase from 0.30
    rerank: false
```

---

### Phase 3: Re-ingestion (Do Last) ⏰

**ONLY AFTER** all code changes are complete:

```bash
# Test that code changes work
python -c "from advisor.collection_config import get_collection; print(get_collection('egeria_docs').chunk_size)"
# Should print: 1024

# Re-ingest collections with new parameters
python scripts/ingest_collections.py --all --force

# Or one at a time (recommended for testing)
python scripts/ingest_collections.py --collection egeria_docs --force
python scripts/ingest_collections.py --collection pyegeria --force
python scripts/ingest_collections.py --collection egeria_workspaces --force
```

---

## Why This Order Matters

### ❌ Wrong Order (Re-ingest First)
1. Re-ingest with old parameters (512 chunks)
2. Realize parameters are wrong
3. Update code
4. Re-ingest AGAIN with new parameters (1024 chunks)

**Result**: 2x time, 2x compute, wasted effort

### ✅ Correct Order (Code First)
1. Update code with collection-specific parameters
2. Test that parameters are read correctly
3. Re-ingest ONCE with correct parameters

**Result**: 1x time, 1x compute, done right

---

## Step-by-Step Checklist

### Before Re-ingestion

- [ ] **1. Update `advisor/collection_config.py`**
  - [ ] Add chunk_size, chunk_overlap, min_score, default_top_k to CollectionMetadata
  - [ ] Set values for each collection (see table above)
  - [ ] Test: `python -c "from advisor.collection_config import get_collection; print(get_collection('egeria_docs').chunk_size)"`

- [ ] **2. Update `advisor/data_prep/pipeline.py`**
  - [ ] Make chunk_document() use collection parameters
  - [ ] Implement collection-specific chunking strategies
  - [ ] Test: `python -c "from advisor.data_prep.pipeline import chunk_document; print(len(chunk_document('test', 'egeria_docs', 'test.md')))"`

- [ ] **3. Update `advisor/rag_retrieval.py`**
  - [ ] Use collection.default_top_k if not specified
  - [ ] Use collection.min_score if not specified
  - [ ] Test: `python scripts/test_retrieval_params.py`

- [ ] **4. Update `advisor/prompt_templates.py`**
  - [ ] Add explicit instructions to RAG_PROMPT_TEMPLATE
  - [ ] Update agents to use new template
  - [ ] Test: `python -c "from advisor.prompt_templates import RAG_PROMPT_TEMPLATE; print(RAG_PROMPT_TEMPLATE)"`

- [ ] **5. Update `config/advisor.yaml`**
  - [ ] Increase chunk_size to 1024
  - [ ] Increase chunk_overlap to 200
  - [ ] Increase min_score to 0.35
  - [ ] Test: `python -c "from advisor.config import get_full_config; print(get_full_config()['rag']['chunk_size'])"`

### After Code Changes

- [ ] **6. Verify all changes**
  ```bash
  # Run quick verification
  python scripts/verify_config_changes.py
  ```

- [ ] **7. Backup current collections** (optional but recommended)
  ```bash
  # Export current data
  python scripts/export_collections.py --output backup/
  ```

### Re-ingestion

- [ ] **8. Re-ingest collections**
  ```bash
  # Start with most important (documentation)
  python scripts/ingest_collections.py --collection egeria_docs --force
  
  # Then code collections
  python scripts/ingest_collections.py --collection pyegeria --force
  
  # Then others
  python scripts/ingest_collections.py --collection egeria_workspaces --force
  python scripts/ingest_collections.py --collection egeria_java --force
  ```

### Verification

- [ ] **9. Test improvement**
  ```bash
  # Run diagnostic
  python scripts/diagnose_rag_quality.py
  
  # Test specific queries
  python -m advisor.cli.main agent
  > what is a digital product in Egeria?
  > how do I create a glossary term?
  ```

- [ ] **10. Monitor results**
  ```bash
  # Check feedback
  > /fstats
  
  # View dashboard
  streamlit run advisor/dashboard/streamlit_dashboard.py
  ```

---

## Time Estimates

| Phase | Task | Time | Can Skip Re-ingest? |
|-------|------|------|---------------------|
| 1 | Update collection_config.py | 30 min | N/A |
| 1 | Update pipeline.py | 30 min | N/A |
| 1 | Update rag_retrieval.py | 15 min | N/A |
| 1 | Update prompt_templates.py | 15 min | N/A |
| 2 | Update advisor.yaml | 5 min | N/A |
| 3 | Re-ingest egeria_docs | 10-20 min | ❌ NO |
| 3 | Re-ingest pyegeria | 15-30 min | ❌ NO |
| 3 | Re-ingest egeria_workspaces | 10-20 min | ❌ NO |
| 3 | Re-ingest egeria_java | 30-60 min | ⚠️ Optional |
| **Total** | | **2-3 hours** | |

---

## Quick Start Script

I'll create a script to help with this:

```bash
# Run this to implement all code changes
python scripts/implement_collection_params.py

# Then re-ingest
python scripts/ingest_collections.py --all --force
```

---

## Summary

### ✅ DO THIS ORDER:

1. **Code changes** (1.5 hours)
   - Update collection_config.py
   - Update pipeline.py
   - Update rag_retrieval.py
   - Update prompt_templates.py

2. **Config changes** (5 min)
   - Update advisor.yaml

3. **Verify** (10 min)
   - Test that parameters are read correctly
   - Run verification script

4. **Re-ingest** (1-2 hours)
   - Re-ingest all collections with new parameters
   - Test improvement

### ❌ DON'T DO THIS:

1. ~~Re-ingest first~~
2. ~~Then update code~~
3. ~~Re-ingest again~~

**Reason**: Wastes 2x time and compute

---

## Next Steps

1. Review this implementation order
2. Start with Phase 1 (code changes)
3. Test each change
4. Only re-ingest after all code is ready
5. Monitor improvement

See `docs/design/COLLECTION_SPECIFIC_PARAMETERS.md` for parameter details.