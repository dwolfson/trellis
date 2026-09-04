# Runtime and hardware — embeddings, accelerators, ONNX

**Status:** consolidated design. Current as of 2026-09-03.
**Scope:** how embeddings are computed, which accelerators are supported, and the
state of the ONNX migration. For the operator instructions, see
`user-docs/ONNX_MIGRATION_GUIDE.md`.

> **This document consolidates three** notes: the ONNX migration plan (Track A
> only — see below), the AMD optimisation work, and the ROCm Python-version
> workaround rescued from `history/`.
>
> **§4 is the part to read first.** The ONNX migration is built and switched off,
> and the plan it came from also contained a 9-week product track that was never
> started.

---

## 1. The embedding path

Embeddings are `sentence-transformers/all-MiniLM-L6-v2`, 384-dimensional, with a
selectable backend:

```yaml
embeddings:
  backend: pytorch  # pytorch or onnx
  model: sentence-transformers/all-MiniLM-L6-v2
  device: auto  # Auto-detect best device: CUDA, ROCm (AMD), MPS (Apple), or CPU
  batch_size: 64
```

Two implementations exist behind that switch: `advisor/embeddings.py` (PyTorch)
and `advisor/embeddings_onnx.py` (ONNX Runtime).

## 2. Accelerator support

Both paths handle the same four cases, by different mechanisms:

| Hardware | PyTorch path | ONNX path |
|---|---|---|
| NVIDIA | `cuda` | CUDAExecutionProvider |
| **AMD** | ROCm — detected via `"hip" in device` | **MIGraphXExecutionProvider** |
| Apple Silicon | `mps` | CoreML / CPU |
| CPU | `cpu` | CPUExecutionProvider |

`device: auto` selects the best available and **falls back to CPU on failure**
rather than raising — the fallback is explicit in `embeddings.py`, which resets
`self.device = "cpu"` and reloads the model.

## 3. The ROCm Python-version constraint

A separate workaround exists for AMD ROCm: the PyTorch ROCm wheels did not cover
the Python versions available on the target machine, and the recommended option
was CPU-only PyTorch until that resolved.

**This may have aged out.** `requires-python` is now `>=3.12`, and the document
names specific versions that were current when it was written. Treat it as a
record of a real constraint rather than current instructions — verify against
the ROCm wheel matrix before acting on it.

---

## 4. Checked against the code, 2026-09-03

### 4a. The ONNX migration is complete and switched off

Everything the migration needed is present:

| | |
|---|---|
| implementation | `advisor/embeddings_onnx.py`, 12 KB |
| exported models | `models/all-MiniLM-L6-v2.onnx` **and** `.optimized.onnx` |
| export script | `scripts/convert_to_onnx.py` |
| benchmark suite | `scripts/benchmark_onnx.py` |
| active backend | **`pytorch`** |

So the work landed, the artefacts are on disk, and the switch was never flipped.

**No benchmark result is recorded anywhere.** The plan sets explicit targets —
"2x+ speedup on CPU", "3x+ speedup on GPU", "2-3x inference speedup" — and
builds the suite to measure them, but no document states what the suite actually
produced. So the question *"is ONNX faster here?"* has a script to answer it and
no recorded answer.

That is the thing to resolve before either flipping the switch or removing the
path: the migration is either an unrealised speedup or a measured
disappointment, and nothing on disk distinguishes those.

**Measured 2026-09-04 on M3 Max (Dev 1).** Command run from
`packages/egeria-advisor`:

```
uv run --package egeria-advisor python scripts/benchmark_onnx.py --batch-size <N> --num-texts <M>
```

Both benchmarks run CPU-only as written — `benchmark_pytorch()` hardcodes
`device="cpu"`, and `benchmark_onnx()` picks up whatever `onnxruntime` reports
as available providers (`CoreMLExecutionProvider`, `AzureExecutionProvider`,
`CPUExecutionProvider` on this Mac), so this is not an MPS-vs-CPU comparison —
the script has no MPS path for either backend. Four runs at different
`num_texts`/`batch_size` combinations, using the pre-exported
`models/all-MiniLM-L6-v2.onnx`:

| num_texts | batch_size | PyTorch texts/sec | ONNX texts/sec | Speedup (PyTorch time / ONNX time) | PyTorch RSS delta | ONNX RSS delta |
|---|---|---|---|---|---|---|
| 100 | 32 | 1483.7 | 217.8 | 0.15x | 12.0 MB | 177.2 MB |
| 500 | 16 | 1175.9 | 222.5 | 0.19x | 13.3 MB | 292.8 MB |
| 500 | 64 | 2249.0 | 320.4 | 0.14x | 40.7 MB | 1366.8 MB |
| 1000 | 16 | 1237.0 | 302.1 | 0.24x | 15.5 MB | 349.8 MB |
| 1000 | 64 | 2176.6 | 308.9 | 0.14x | 47.0 MB | 1210.3 MB |

Embedding quality (cosine similarity, all runs): mean/min/max 1.000000, std
0.000000 — ONNX and PyTorch produce numerically identical embeddings here, so
export correctness is not in question.

**The ONNX path did not meet its stated target on this hardware — it is
slower, not faster.** PyTorch on CPU beat ONNX by roughly 4-7x across every
batch size and corpus size tried, and ONNX's RSS delta was consistently
10-30x larger than PyTorch's. The suite's own success-criteria block reports
`✗ Speedup: 0.1x-0.2x < 2.0x` and `✗ Memory reduction: negative < 30%` on
every run; only the embedding-quality criterion passes. This contradicts the
plan's "2x+ speedup on CPU" target directly — on this M3 Max, with this
export, ONNX Runtime is not winning against `sentence-transformers`' own
(already reasonably optimized) CPU path, plausibly because
`benchmark_onnx()` does per-batch Python tokenization plus manual
mean-pooling/normalization in NumPy rather than a fused/optimized runtime
path, while `benchmark_pytorch()` calls straight into
`SentenceTransformer.encode()`. GPU/MPS speedup (the "3x+ on GPU" target) is
**not tested by this script at all** — the ONNX benchmark never requests
`CoreMLExecutionProvider` explicitly and PyTorch is pinned to `device="cpu"`,
so no accelerator comparison exists yet, on this hardware or any other.

**Conclusion for the switch:** based on this measurement, flipping
`backend: onnx` on this Mac would make embeddings slower and heavier, not
faster and lighter. Nothing here has been changed — `backend: pytorch`
remains as configured in `advisor/configdata/advisor.yaml`.

### 4b. Track B was never started, and has been split out

The source document was *"ONNX Migration & Egeria-Advisor-Pro Implementation
Plan"* — 600 lines, of which **474 were Track B**, a 9-week product track for
specialist agents and code-generation tooling.

None of it exists. `advisor/tools/` contains `beeai_tools.py`, `rag_tool.py` and
`rag_tools.py` — not the four tools the plan names — and `advisor/agents/pro/`
was never created.

It is now `future/EGERIA_ADVISOR_PRO.md`. Keeping the two together meant an
unstarted product plan sat under the same heading as completed infrastructure,
and **the document's own status line could only ever be right about one of them.**

### 4c. AMD support did land

Both embedding paths handle ROCm — `"hip" in self.device` in the PyTorch path,
`MIGraphXExecutionProvider` in the ONNX provider list. The AMD optimisation work
is real, independent of whether ONNX is the active backend.

---

## 5. Settled — do not reopen without re-measuring

| Question | Settled | On what basis |
|---|---|---|
| Is ONNX the active embedding backend? | **No** | `backend: pytorch`; the ONNX path is built and unselected |
| Is ONNX faster here? | **Unknown** — and measurable | The benchmark suite exists; no result is recorded anywhere |
| Should an accelerator failure raise? | **No** — fall back to CPU | `embeddings.py` resets to CPU and reloads rather than failing the request |
| Was AMD support delivered? | **Yes** | ROCm in the PyTorch path, MIGraphX in the ONNX provider list |
| Was Egeria-Advisor-Pro started? | **No** | Every artefact it names is absent; moved to `future/` |
| Is the ROCm Python-version workaround current? | **Unverified** | It names versions from when it was written; `requires-python` is now `>=3.12` |
