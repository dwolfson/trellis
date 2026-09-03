# Query handling and answer quality

**Status:** consolidated design. Current as of 2026-09-03.
**Scope:** how a query is classified and routed, how scoped and exhaustive
queries work, and what has been tried against hallucination and answer quality.
For the live routing table, see `CLAUDE.md`'s Query Flow. For the report path,
see the Report Pipeline rules there.

> **This document consolidates seven** notes from `design/`: query classification
> and tracking, scoped queries (implementation and troubleshooting), exhaustive
> query detection, hallucination analysis, RAG quality improvements, and the
> performance/quality analysis.
>
> **§6 is the part to read first.** Every claim below was checked against the
> code on 2026-09-03, and four of them no longer hold.

---

## 1. Query classification

Queries are classified into types, each with an expected collection set:

| Type | Trigger shape | Primary collections |
|---|---|---|
| `CONCEPT` | "what is", "define", "explain", "meaning of" | `egeria_concepts`, then `egeria_types` |
| `TYPE` | "what properties does X have" | `egeria_types` |
| `CODE` | "show me code for X" | `pyegeria`, `egeria_java` |
| `EXAMPLE` | "give me an example of X" | `pyegeria`, `egeria_workspaces` |
| `TUTORIAL` | "how do I X" | `egeria_general` |
| `TROUBLESHOOTING` | "why doesn't X work" | mixed |
| `COMPARISON` | "difference between X and Y" | mixed |
| `GENERAL` | everything else | router's default |

Classification is pattern-first (`routing.yaml`), with an LLM intent classifier
as the fallback for `general`. The pattern layer is deliberately primary: a
zero-temperature LLM call is still a call, and the common shapes are cheap to
match.

**Collection-level metrics** were the point of the tracking half of this design —
knowing *which collection answered* is what makes a routing regression visible,
because an answer that came from the wrong collection can still look plausible.

## 2. Scoped queries

A scoped query restricts retrieval to one source — "in pyegeria, how do I …".

**The root cause recorded here is worth keeping**, because it is a shape that
recurs: *path extraction worked and produced "pyegeria"; the analytics module
simply did not use it to filter.* The extraction was correct, the plumbing was
missing, and the symptom was an unscoped answer to a scoped question — which
looks like a retrieval-quality problem and is not.

### Troubleshooting

The operator-facing half, kept alongside the design because the two are hard to
use apart:

- **Scope silently ignored** — check that the extracted scope reaches the filter,
  not just that extraction succeeded. The two failed independently before.
- **Scope name not matching a collection** — the collection names are fixed (nine
  active); a scope that does not resolve should say so rather than fall back to
  unscoped retrieval, which produces a confident answer to a different question.

## 3. Exhaustive queries

Queries that must return *everything* — "all methods on `ProjectManager`" — rather
than the top-k most similar. Similarity retrieval is the wrong instrument here:
top-k by construction returns k, and the honest answer is a complete list.

Implemented in `advisor/agents/pyegeria_agent.py`: `is_exhaustive_query()` detects
the shape, `get_all_class_methods()` answers it from the symbol store rather than
from vector search. Reached through `ConversationAgent`.

## 4. Answer quality and hallucination

The analysis behind this recorded a **>80% hallucination rate** on Egeria
documentation questions and attributed it to three causes:

1. **Chunk granularity** — 512 tokens with 50 overlap fragments concepts that
   span paragraphs.
2. **Embedding model limits** — `all-MiniLM-L6-v2` is 384-dimensional with a
   256-token maximum, so long documentation passages are truncated before they
   are embedded.
3. **Collection routing** — an answer assembled from the wrong collection.

**What actually shipped is narrower than what was proposed** — see §6.

## 5. Performance and quality tracking

The metrics worth tracking were named as: retrieval latency, which collections
were consulted, score distribution of the returned chunks, and the cache hit
rate. The first and last are cheap and the middle two are what make a quality
regression attributable rather than merely visible.

---

## 6. Checked against the code, 2026-09-03

Consolidating these seven documents meant checking their claims rather than
carrying them forward. Four no longer hold.

### 6a. The headline recommendations were not adopted

`HALLUCINATION_ANALYSIS_AND_FIXES` names `chunk_size: 512` and
`all-MiniLM-L6-v2` as root causes. **Both are still the live configuration**
(`advisor/configdata/advisor.yaml`):

```yaml
rag:
  chunk_size: 512
  chunk_overlap: 50
  retrieval:
    top_k: 10              # Increased from 5 for more sources
    min_score: 0.30        # Keep at 0.30 - file type boosting handles quality
embeddings:
  model: sentence-transformers/all-MiniLM-L6-v2
```

So the two structural recommendations — larger chunks, a bigger embedding model —
were **not taken**, while the cheaper ones **were**: `top_k` went 5 → 10, and the
config's own comment says the score floor stays at 0.30 because boosting handles
quality.

That is either a decision that was never written down, or an open item that has
been quietly carried for months. **It should not be read as "these fixes are in
place."**

### 6b. A workaround for a removed backend is still in the code

`EXHAUSTIVE_QUERY_DETECTION` documents a *Milvus limitation workaround*: Milvus
could not combine multiple scalar filters, so the code filters on one field and
post-processes in Python.

**Milvus was fully removed** — migrated to pgvector in April 2026, with code,
config and dependency deleted in July. There are zero references in `pyproject.toml`
and none in `advisor/`. But `pyegeria_agent.py:270` still builds the single-field
filter and post-processes:

```python
filter_expr = f'class_name == "{class_name}"'
```

pgvector translates compound filter expressions (`translate_filter_expr` in
`vector_store_pg.py`), so the constraint that motivated this no longer exists. The
workaround is not *wrong* — it returns correct results — it is unnecessary work
carried forward, and the comment explaining it points at a system that is gone.

### 6c. Exhaustive query detection is live — a first check said otherwise

An initial grep suggested `PyegeriaAgent` was orphaned, imported only from
`conversation_agent.py.debug_backup`. **That was a malformed exclusion pattern in
the grep, not a finding.** The live `conversation_agent.py` imports it at line 21
and references it seven times. The feature is wired in and reachable.

Recorded because the near-miss is the point: a module that is 37 KB and *looks*
abandoned is exactly the kind of thing a consolidation deletes on a bad grep.

### 6d. It is missing from the agent table

`CLAUDE.md` lists nine agents and `PyegeriaAgent` is not among them, though it is
imported by `ConversationAgent` and owns the exhaustive-query path. A documentation
gap rather than a code one.

### 6e. There is a tracked backup file

`advisor/agents/conversation_agent.py.debug_backup` is committed. Noted in
passing, not addressed here.

---

## 7. Settled — do not reopen without re-measuring

| Question | Settled | On what basis |
|---|---|---|
| Should classification be LLM-first? | **No** — pattern-first | The common shapes match cheaply; the LLM is the fallback for `general` |
| Is top-k retrieval adequate for "all X" questions? | **No** | Top-k returns k by construction; exhaustive queries answer from the symbol store |
| Was the scoped-query bug a retrieval-quality problem? | **No** | Extraction worked; the filter was never applied. The symptom impersonated a quality problem |
| Should an unresolvable scope fall back to unscoped retrieval? | **No** | That answers a different question confidently |
| Were the chunk-size and embedding-model fixes applied? | **No** — see §6a | Both are still the live config; only `top_k` and boosting shipped |
| Is the Milvus scalar-filter workaround still needed? | **No** — see §6b | pgvector translates compound filters; the workaround is carried, not required |
| Is `PyegeriaAgent` orphaned? | **No** — see §6c | Live import in `conversation_agent.py:21` |
