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
