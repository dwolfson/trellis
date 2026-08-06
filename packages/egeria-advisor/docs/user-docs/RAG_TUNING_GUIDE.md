# RAG System Tuning Guide

## Problem: Poor Answer Quality

If the advisor is giving poor answers or can't answer basic questions, the RAG system needs tuning. This guide provides step-by-step improvements.

## Quick Diagnosis

### Test Basic Queries

```bash
egeria-advisor "What is a glossary?" --verbose
egeria-advisor "How do I create a collection?" --verbose
egeria-advisor "What is EgeriaClient?" --verbose
```

### Check What's Wrong

Common issues:
1. **No relevant sources found** → Retrieval problem
2. **Sources found but poor answer** → Generation/prompt problem
3. **Generic/hallucinated answers** → Context not being used
4. **Slow responses** → Performance tuning needed

## Tuning Steps

### Step 1: Improve Retrieval (Most Important)

#### 1.1 Lower the Similarity Threshold

Edit `config/advisor.yaml`:

```yaml
rag:
  retrieval:
    top_k: 10              # Increase from 5 to 10
    min_score: 0.5         # Lower from 0.7 to 0.5
    rerank: false
```

**Why**: A score of 0.7 is very strict. Lowering to 0.5 will retrieve more potentially relevant documents.

#### 1.2 Increase Context Length

```yaml
rag:
  context:
    max_length: 6000       # Increase from 4000
    format_style: detailed
    include_metadata: true
```

**Why**: More context gives the LLM more information to work with.

#### 1.3 Test Retrieval Directly

```bash
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
source .venv/bin/activate
python scripts/test_vector_search.py
```

This will show you what's being retrieved and the scores.

### Step 2: Improve Prompts

The prompts in `advisor/rag_system.py` need to be more specific about using the context.

#### 2.1 Check Current Prompt

```bash
grep -A 20 "def _build_prompt" advisor/rag_system.py
```

#### 2.2 Enhance System Prompt

The system prompt should emphasize:
- Use ONLY the provided context
- If context doesn't contain the answer, say so
- Cite specific sources
- Be specific and technical

Example improved prompt:
```python
system_prompt = """You are an expert assistant for the Egeria Python library (pyegeria).

CRITICAL INSTRUCTIONS:
1. Answer ONLY using the provided context below
2. If the context doesn't contain the answer, say "I don't have enough information in the context to answer that"
3. Be specific and technical - include class names, method names, and parameters
4. Always cite which file/class your information comes from
5. If showing code, make it complete and runnable

Context:
{context}

Remember: Use ONLY the information from the context above. Do not make up or infer information."""
```

### Step 3: Use a Better Model

The current model `llama3.2:3b` is small and may struggle with complex queries.

#### 3.1 Try a Larger Model

```bash
# Pull a larger model
ollama pull llama3.1:8b

# Or even better for code
ollama pull codellama:13b
```

#### 3.2 Update Configuration

Edit `config/advisor.yaml`:

```yaml
llm:
  models:
    query: llama3.1:8b          # Upgrade from 3b to 8b
    code: codellama:13b          # Use code-specialized model
    conversation: llama3.1:8b
```

**Trade-off**: Larger models are slower but much better quality.

### Step 4: Adjust LLM Parameters

#### 4.1 Lower Temperature for Factual Queries

Edit `config/advisor.yaml`:

```yaml
llm:
  parameters:
    temperature: 0.3           # Lower from 0.7 for more focused answers
    max_tokens: 3000           # Increase from 2000
    top_p: 0.9
    top_k: 40
    repeat_penalty: 1.2        # Increase from 1.1 to reduce repetition
```

**Why**: Lower temperature = more deterministic, factual answers.

#### 4.2 Increase Max Tokens

```yaml
rag:
  generation:
    temperature: 0.3           # Match LLM temperature
    max_tokens: 3000           # Allow longer answers
```

### Step 5: Verify Data Quality

#### 5.1 Check What's in the Vector Store

```bash
python scripts/count_vectors.py
```

Should show ~92,000+ entities total across 9 collections (see `docs/user-docs/COLLECTION_MAINTENANCE_GUIDE.md`
for the current per-collection breakdown).

#### 5.2 Test Search Quality

```bash
python -c "
from advisor.vector_store import get_vector_store
vs = get_vector_store()
results = vs.search('egeria_concepts', query_text='glossary', top_k=5)
for r in results:
    print(f'{r.score:.3f}: {r.metadata.get(\"name\", \"Unknown\")} - {r.metadata.get(\"file_path\", \"Unknown\")}')
"
```

Should return relevant glossary-related code.

### Step 6: Improve Query Processing

#### 6.1 Add Query Expansion

The query processor should expand queries to include synonyms and related terms.

For "glossary", also search for:
- "GlossaryManager"
- "glossary_manager"
- "create_glossary"
- "glossary term"

#### 6.2 Add Egeria-Specific Terms

Create a mapping of common terms:
```python
EGERIA_TERMS = {
    "glossary": ["GlossaryManager", "glossary_manager", "glossary term"],
    "collection": ["CollectionManager", "collection_manager"],
    "asset": ["AssetManager", "asset_manager", "Asset"],
}
```

## Quick Fixes (Apply Now)

### Fix 1: Lower Retrieval Threshold

```bash
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
nano config/advisor.yaml
```

Change:
```yaml
rag:
  retrieval:
    top_k: 10
    min_score: 0.5    # Changed from 0.7
```

Save and test:
```bash
egeria-advisor "What is a glossary?" --verbose
```

### Fix 2: Use Better Model (if available)

```bash
# Check available models
ollama list

# If you have llama3.1:8b
nano config/advisor.yaml
```

Change:
```yaml
llm:
  models:
    query: llama3.1:8b
```

### Fix 3: Lower Temperature

```bash
nano config/advisor.yaml
```

Change:
```yaml
llm:
  parameters:
    temperature: 0.3    # Changed from 0.7
```

## Testing Improvements

### Test Suite

Create `scripts/test_answer_quality.py`:

```python
#!/usr/bin/env python3
"""Test answer quality with various queries."""

test_queries = [
    "What is a glossary?",
    "How do I create a collection?",
    "What is EgeriaClient?",
    "Show me how to find assets",
    "What is the difference between OMVS and OMAS?",
]

for query in test_queries:
    print(f"\n{'='*60}")
    print(f"Query: {query}")
    print('='*60)
    # Run query and evaluate
```

### Evaluation Criteria

Good answer should:
1. ✅ Use information from the context
2. ✅ Cite specific classes/methods
3. ✅ Be technically accurate
4. ✅ Include code examples when relevant
5. ✅ Not hallucinate information

## Advanced Tuning

### Option 1: Re-rank Results

Install a re-ranker:
```bash
pip install sentence-transformers
```

Enable in config:
```yaml
rag:
  retrieval:
    rerank: true
    rerank_model: cross-encoder/ms-marco-MiniLM-L-6-v2
```

### Option 2: Hybrid Search

Combine vector search with keyword search:
```yaml
rag:
  retrieval:
    hybrid: true
    vector_weight: 0.7
    keyword_weight: 0.3
```

### Option 3: Query Decomposition

Break complex queries into sub-queries:
- "How do I create and populate a glossary?"
  → "How do I create a glossary?"
  → "How do I add terms to a glossary?"

## Monitoring Quality

### Use MLflow to Track

```bash
# View experiments
open http://localhost:5025
```

Track metrics:
- Response relevance
- Source quality
- User feedback
- Response time

### A/B Testing

Test different configurations:
1. Baseline (current)
2. Lower threshold (0.5)
3. Larger model (8b)
4. Both combined

## Expected Results

After tuning, you should see:

### Before
```
Query: What is a glossary?
Answer: A glossary is a collection of terms... [generic answer]
Sources: 0 relevant
```

### After
```
Query: What is a glossary?
Answer: In Egeria, a glossary is managed by the GlossaryManager class 
(pyegeria/glossary_manager.py). It's a collection of glossary terms that 
define business vocabulary. You can create one using:

glossary_mgr = GlossaryManager(...)
glossary = glossary_mgr.create_glossary(display_name="My Glossary")

Sources: 5 relevant (GlossaryManager, create_glossary, examples)
```

## Recommended Configuration

Based on testing, this configuration works well:

```yaml
rag:
  retrieval:
    top_k: 10
    min_score: 0.5
    rerank: false
  context:
    max_length: 6000
    format_style: detailed
  generation:
    temperature: 0.3
    max_tokens: 3000

llm:
  models:
    query: llama3.1:8b  # or llama3.2:3b if 8b too slow
  parameters:
    temperature: 0.3
    max_tokens: 3000
    repeat_penalty: 1.2
```

## Next Steps

1. **Apply Quick Fixes** (5 minutes)
   - Lower min_score to 0.5
   - Lower temperature to 0.3
   - Test immediately

2. **Upgrade Model** (if needed, 10 minutes)
   - Pull llama3.1:8b
   - Update config
   - Test again

3. **Improve Prompts** (30 minutes)
   - Edit rag_system.py
   - Make prompts more specific
   - Test with various queries

4. **Monitor & Iterate** (ongoing)
   - Use MLflow to track quality
   - Collect user feedback
   - Continuously tune

## When to Move to Next Phase

Move to Phase 5 (Agents) or Phase 7 (Query Understanding) when:
- ✅ Basic queries get good answers (>80% quality)
- ✅ Sources are relevant (>3 good sources per query)
- ✅ Response time is acceptable (<5 seconds)
- ✅ Users are satisfied with answers

If still poor after tuning:
- Consider re-ingesting data with better chunking
- Try different embedding models
- Add more context from documentation

---

**Quick Start**: Apply Fix 1 and Fix 3, then test. This should immediately improve quality.