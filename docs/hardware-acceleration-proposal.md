# Hardware acceleration: detect what a machine has, and install only what it can use

Proposal, 2026-11-11. Status: for the project owner's decision (§7). Scope: Resource Explorer, Egeria Advisor and
the shared packages that run PyTorch models: Docling's PDF layout and table models, and sentence-transformers
embeddings.

## 1. Summary

Two separate problems need two separate mechanisms:

- **Which PyTorch build is installed** (CUDA for NVIDIA, ROCm for AMD, CPU-only) can only be decided when the
  environment is built. A running program cannot swap builds. Today every Linux install gets the NVIDIA (CUDA 13)
  build and its 15 NVIDIA runtime packages, about 4.5 GB, including the Docker images and hedwig, which have no
  NVIDIA GPU. Proposal: one optional extra per build (`cpu`, `cuda`, `rocm`) chosen per machine, CPU-only by
  default on Linux; macOS unchanged (its standard build already includes Apple's GPU support).
- **Which device each run uses** is decided at run time, and today three pieces of code decide it three different
  ways. Proposal: one small shared function that every consumer asks, which looks at what the installed PyTorch
  can actually use, refuses known-bad combinations, takes an environment override, and says what it chose and why.

Measured on hedwig (§2): the GPU makes PDF conversion about **2.1 times faster** with **identical output**, and
the first run on a machine pays a one-time compile cost.

## 2. What was measured

### 2.1 Hedwig: AMD Radeon 890M (Strix Point, gfx1150), 24 CPU cores

Docling 2.150 (RE's options: OCR off, table structure on), the same 113 pages of public sustainability PDFs in
every run, seconds per page:

| Sample | Pages | CPU, 4 threads | GPU (ROCm 7.2), warm | Speed-up |
|---|---|---|---|---|
| NAICS manual, front matter | 25 | 1.62 | 0.89 | 1.8× |
| NAICS manual, code pages | 25 | 0.95 | 0.36 | 2.6× |
| GWP tables | 9 | 1.02 | 0.45 | 2.2× |
| JRC emission factors (table-dense) | 13 | 11.0 | 5.5 | 2.0× |
| SPG methodology | 21 | 1.12 | 0.47 | 2.4× |
| Value-chain standard | 20 | 0.97 | 0.53 | 1.8× |
| **Total** | 113 | 259–271 s | **127 s** | **≈2.1×** |

- **Output:** the GPU's Markdown is word-for-word identical to the CPU's on all six samples.
- **First run:** the very first GPU run took 303 s, with two samples 4 times slower than the CPU, and a 40 s
  warm-up. ROCm compiles a kernel the first time it meets a new input shape and caches it on disk; a second, fresh
  process ran at the warm speed with a 7 s warm-up. So the cost is once per machine, not once per process.
- **Support:** `torch 2.13.0+rocm7.2` uses gfx1150 directly. The commonly needed `HSA_OVERRIDE_GFX_VERSION`
  workaround was not needed.
- **CPU threads are not a lever.** Docling uses 4 threads by default. At 16, light pages got 10–25% faster but the
  table-dense pages got slower (13.4 s/page against 11.0); the total did not improve (279 s).
- **Run-to-run noise** is about 4% (259 s and 271 s for the same CPU run).
- **Table-dense documents dominate** on every device: JRC is about 10 times any other sample. A GPU halves a
  rebuild's time; it does not change which documents are slow.

### 2.2 Laz: Apple silicon (MPS)

Docling on MPS failed on every page until transformers 5.22.2 fixed RT-DETR's hard-coded float64 (gate b354); with
the upgrade (#1057) the coordinator confirmed Docling logs `Accelerator device: 'mps'` and the real-PDF test
passes (b357). There is no MPS timing yet: the same script (§6, step 1) gives one.

## 3. What there is today

### 3.1 Devices, chosen in three places, three ways

| Where | Default | Order | Notes |
|---|---|---|---|
| RE embeddings (`resource_explorer/embeddings.py`) | `auto` (`EmbeddingsConfig.device`) | MPS, CUDA, CPU | MPS before CUDA; no reason recorded |
| EA embeddings (`advisor/embeddings.py`) | `cpu` (`EMBEDDING_DEVICE`) | CUDA/ROCm, MPS, CPU | logs the GPU's name; falls back to CPU on failure |
| Docling (`trellis_artifact_tree.adapters_pdf.keep_off_mps`, RE's `build_pdf_converter`) | Docling's `AUTO` | Docling's own | CPU instead of MPS only when transformers is older than 5.22.2, or `TRELLIS_DOCLING_ALLOW_MPS` says so |

The same machine can therefore embed on one device and convert PDFs on another, and nothing records which.

### 3.2 Installs: the NVIDIA build everywhere on Linux

`uv.lock` resolves `torch` from PyPI. On Linux that wheel is the CUDA 13 build, and it brings `triton` and 15
`nvidia-*` packages. In hedwig's shared environment that is 2.7 GB of NVIDIA libraries, 1.1 GB of torch and
690 MB of triton. Both Docker images install the same. On a machine without an NVIDIA GPU, all of it is unused.
(EA also lists `onnxruntime-gpu`, which has no macOS arm64 wheel; that is why `--all-extras` fails on a Mac,
CLAUDE.md "uv".)

The ROCm build for AMD is larger again: the wheel is 6.2 GB and installs to about 16 GB, so it should never be a
default.

## 4. Proposal A: one device choice at run time

A small shared function, for example `trellis_accel.pick_device(purpose)`, returning the device and the reason:

1. **Override:** `TRELLIS_DEVICE` = `cpu` | `cuda` | `mps` | `auto` (default `auto`). An override the installed
   PyTorch cannot honour is refused with a sentence, never quietly replaced. `rocm` is accepted as a name for
   `cuda`, since PyTorch reports AMD GPUs through the CUDA API.
2. **NVIDIA or AMD:** `torch.cuda.is_available()`. `torch.version.hip` says which one, for the record.
3. **Apple:** `torch.backends.mps.is_available()`, unless a known-bad combination applies. Today that is one rule,
   moved from `keep_off_mps`: transformers older than 5.22.2 runs Docling's layout model on the CPU. The rules live
   in one place, each with the incident that justified it.
4. **Otherwise the CPU.**

Every consumer asks it: RE's and EA's embeddings, and Docling (as `AcceleratorOptions(device=...)`). The choice and
its reason go in the log at start-up and in each run's record (a rebuild's progress, a survey's activity entry), so
a slow or failed run says what it ran on.

Two settings stay per purpose, because they differ in practice: EA's embeddings default to `cpu` today on purpose,
and a purpose can keep its own default while still asking the shared function when it is `auto`.

The ONNX embedding path in EA (`onnxruntime` / `onnxruntime-gpu`) is a separate stack; it is out of scope here
and noted in §7.

## 5. Proposal B: install the PyTorch build each machine can use

Optional extras in the workspace, at most one per environment, each pointing `torch` (and `torchvision`) at its
own index:

```toml
# root pyproject.toml (sketch)
[project.optional-dependencies]
cpu  = ["torch", "torchvision"]
cuda = ["torch", "torchvision"]
rocm = ["torch", "torchvision"]

[tool.uv]
conflicts = [[{ extra = "cpu" }, { extra = "cuda" }, { extra = "rocm" }]]

[tool.uv.sources]
torch = [
  { index = "pytorch-cpu",  extra = "cpu",  marker = "sys_platform == 'linux'" },
  { index = "pytorch-cuda", extra = "cuda", marker = "sys_platform == 'linux'" },
  { index = "pytorch-rocm", extra = "rocm", marker = "sys_platform == 'linux'" },
]
# torchvision the same

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true
# pytorch-cuda: .../whl/cu130; pytorch-rocm: .../whl/rocm7.2, the same way
```

- **macOS:** no extra; PyPI's build already includes MPS.
- **Linux images and CI:** `cpu`. Expected saving about 3.4 GB per image (the NVIDIA libraries and triton).
- **A Linux machine with an NVIDIA GPU:** `cuda`. **With an AMD GPU (hedwig):** `rocm`.
- **The lock** records all three, and only the chosen one is downloaded.

Two things to settle in a spike before relying on this, because they are where uv's behaviour decides the design:

1. **A bare `uv sync` from the root** (CLAUDE.md, "uv") must keep giving every session a working environment. With
   no extra chosen, `torch` falls back to PyPI's (CUDA) build, which is today's behaviour. Whether to make `cpu` the
   default on Linux instead, and how (uv has default groups, not default extras), is the open question.
2. **The ROCm download is large and the network can drop it.** On hedwig a 6.2 GB download reset after 1.2 GB.
   Pre-fetching the wheel with a resumable download, then installing from the local file, worked; the install
   step should support that, and its temporary files must not go to a small RAM-backed `/tmp` (16 GB unpacked).

Choosing a build per machine needs a probe that runs before any PyTorch is installed: `nvidia-smi`, `/dev/kfd`
plus the GPU's `gfx_target_version` in `/sys/class/kfd`, or `uname -s` = Darwin. That can be a small script that
prints the extra to use; it chooses nothing on its own.

## 6. Rollout

1. **Measure laz:** run the same timing script on Apple's GPU and on its CPU, for the MPS column in §2.
2. **Proposal A** (runtime): the shared function and its tests; switch Docling, RE's embeddings and EA's
   embeddings to it; record the device in each run. Behaviour on today's machines is unchanged, except that the
   choice is now said.
3. **Spike for Proposal B:** a branch with the extras, `uv lock`, and builds on Linux CPU, on hedwig with `rocm`,
   and on a Mac with no extra; both images built with `cpu`, and their size compared with today's.
4. **Proposal B** (install): the extras, the probe script, the images on `cpu`, and the documentation (CLAUDE.md
   "uv", `docs/packaging.md`).

## 7. Questions for the project owner

1. **Is the CPU-only build the Linux default** (images, CI, a fresh checkout), with `cuda`/`rocm` opt-in per
   machine? Or does the default stay PyPI's CUDA build, with `cpu` opt-in for the images only?
2. **Should hedwig move to `rocm`?** It halves PDF conversion and costs about 16 GB of disk and one slow first run.
   Its shared environment is used by every session on hedwig, so this is a shared-environment change.
3. **Embeddings on the GPU too?** EA defaults to the CPU on purpose today. Proposal A keeps each purpose's
   default; whether EA should move to `auto` is a separate call.
4. **EA's ONNX path:** keep `onnxruntime-gpu` as an extra (NVIDIA only), or retire it in favour of the PyTorch path?
