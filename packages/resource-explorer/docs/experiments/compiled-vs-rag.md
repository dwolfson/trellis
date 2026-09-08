# Experiment: compiled evidence versus RAG-only answers

**Question** (context-compilation-design.md §9): do answers built on compiled evidence beat
answers the agent assembles for itself from retrieval? Everything about the compiler's effect on
answer quality is asserted until this runs.

**Status:** protocol and harness written 2026-09-08 (`scripts/experiment_compiled_vs_rag.py`).
Results are appended to this file's "Runs" section as they land; none yet.

## Design

| | |
|---|---|
| Unit | one (repository, catalog question, condition) |
| Questions | the full repo question catalog (52 entries on 2026-09-08), shuffled with a fixed seed so order does not follow catalog position; `--limit N` takes the first N of that order |
| Repositories | `egeria_python_git`, `kafka`, `docling` by default: the three with the deepest stored analysis results across different languages and communities |
| Conditions | `compiled`: `ConversationAgent(compiled_evidence=True)`, production behaviour. `rag`: the same agent with `compiled_evidence=False`, so it must search collections itself. **Nothing else differs**: same tools, prompt shape, model, tier, fallback |
| Answering model | whatever `LLM__OLLAMA__MODEL` and `EXPLORER_MODEL_TIER` resolve to; record them with each run (default `llama3.1:8b`, tier `dev`) |
| Perspectives | none set, the common case |
| Judge | `qwen2.5:32b` at temperature 0 with JSON output, a different and larger model than the answerer. Override with `EXPERIMENT_JUDGE_MODEL` |
| Ground truth for the judge | a **reference compile** for every row, in both conditions: which analyses had usable stored results and which are gaps, with their fact-layer states. The judge never sees the packed text, only the list |

## Rubric (per row, judged)

| Field | Meaning |
|---|---|
| `answers_question` | 0 not addressed, 1 partial, 2 direct and useful |
| `cites_evidence` | names a specific analysis, finding, file, metric or source |
| `claims_missing_result` | states a concrete result for an analysis the registry has no usable result for; the failure the compiler exists to prevent |
| `acknowledges_limits` | says what could not be determined, where that applies |
| `unsupported_claims` | count of specific claims not attributable to stored evidence or clearly labelled general knowledge |

Plus, unjudged: latency, the agent's `compile_id` (compiled condition) and whether it equals the
reference compile's id, which is the replayability check from §9 running for free.

## What would settle the question

- `claims_missing_result%` materially lower and `acknowledges_limits%` higher under `compiled`,
  across repos, is the compiler doing its main job.
- `answers_question` and `cites_evidence` not worse under `compiled` means the evidence is not
  crowding out the answer.
- If `rag` wins on `answers_question` for `human` or `direct` questions, that is expected and
  informative: those questions are not answered by stored analyses and the compiler should say so.
- Compile ids matching the reference in every compiled row is replayability holding over the run.

## Caveats stated up front

- One judge model, one answering model, one afternoon of state. Treat differences under about
  ten points as noise until a second run reproduces them; a human sample of disagreements is
  part of the protocol, not optional.
- The agent's fallback to plain retrieval on an exception is not distinguished from a normal
  answer in either condition.
- The reference compile persists like any compile (`context_compiles`, session
  `experiment:compiled_vs_rag`), so the run leaves rows behind by design.

## How to run

```bash
cd packages/resource-explorer
uv run python scripts/experiment_compiled_vs_rag.py --repos egeria_python_git --limit 3   # smoke
uv run python scripts/experiment_compiled_vs_rag.py                                      # full, resumable
uv run python scripts/experiment_compiled_vs_rag.py --summarise                          # tables only
```

Results: `data/experiments/compiled_vs_rag/results.jsonl` (one row per unit, resumable) and, when
MLflow is reachable, experiment `compiled_vs_rag` with one run per condition.

## Runs

### full-20260908 — 3 repos × 52 questions × 2 conditions = 312 rows, 0 errors

Answerer `llama3.1:8b`, tier `dev`, no perspectives; judge `qwen2.5:32b`. Results in
`data/experiments/compiled_vs_rag/results.jsonl`; MLflow experiment `compiled_vs_rag`, runs
`full-20260908-compiled` / `full-20260908-rag`.

| metric | compiled | rag |
|---|---:|---:|
| answers_question (0–2) | 1.03 | 0.56 |
| cites_evidence | 26% | 0% |
| claims_missing_result | 0% | 0% |
| acknowledges_limits | 39% | 19% |
| unsupported_claims (mean) | 1.13 | 1.17 |
| latency, median | 11.6 s | 10.2 s |

Paired per (repo, question): compiled scored higher on `answers_question` in 80 pairs, lower in 16,
tied in 60; mean difference +0.46 on a 0–2 scale. The direction held on every repo
(egeria_python_git 0.98 vs 0.81, kafka 1.00 vs 0.40, docling 1.10 vs 0.48) and on every
answering kind, including `human` (1.10 vs 0.48) and `gap` (1.00 vs 0.22), where the compiled
condition's advantage is that it says what is missing. Replayability: the agent's compile id equalled
the reference compile's id in 156 of 156 compiled rows.

**Read with the caveats above.** One answering model, one judge, one afternoon. Two things to
check by hand before believing the numbers: (1) `claims_missing_result` never fired in either
condition, which is either good news or a rubric that cannot detect it — sample the RAG rows for
analyses listed as gaps and see whether the judge missed any; (2) the 16 pairs where RAG scored
higher, to learn what the packed evidence displaced. Unsupported claims did not improve, so the
compiler changes what the model can say, not how disciplined it is about saying more.
