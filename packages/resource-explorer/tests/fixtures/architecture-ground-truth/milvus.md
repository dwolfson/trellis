# Ground-truth partition — milvus-io/milvus

> **PRE-REGISTERED, `owner-published` provenance** — the second fixture of this kind, after
> `prometheus.md`. The component set is transcribed from Milvus's own published architecture,
> `site/en/reference/architecture/{architecture_overview,main_components}.md` in
> `milvus-io/milvus-docs`, written by the Milvus authors with no knowledge of Resource Explorer.
> No detector has been run against this target. This file is committed first; the commit timestamp
> is the evidence (`README.md` rule 2).

**Target:** `milvus-io/milvus`
**Checkout:** clean `--depth 1 --filter=blob:none` clone of `master`
**Perspective:** logical
**Vocabulary:** SolutionComponentType — the closed 13 (design doc §3.1)
**Written by:** transcribed by assistant from the owners' published architecture — see Provenance
**Written at:** 2026-08-22

**Source documents:** `site/en/reference/architecture/architecture_overview.md` and
`main_components.md` in `milvus-io/milvus-docs`
**Source last modified:** both 2026-05-09 — **3½ months old**, against Prometheus's five years
**Source version:** the docs repo's default branch is **`v3.0.x`**. Milvus versions its documentation
*by branch*, so the doc-to-code version question is answered structurally rather than by a prose
disclaimer of the kind `prometheus.md` had to rely on. This is the strongest version signal seen in
any source so far (design §5.5a(b)).

---

## Provenance — and why this file is MORE contaminated than `prometheus.md`

| element | author |
|---|---|
| component set, count, and layer grouping | **the Milvus authors** — "five core components and three third-party dependencies", stated verbatim |
| **file globs** | **assistant** — see below |
| `Type:` assignments | **assistant** |

**The globs are the weak point, and materially weaker than in `prometheus.md`.** The Prometheus doc
linked to specific source files, so its globs were the owners' own file references widened to owning
directories. **The Milvus docs contain no code links at all** — they describe components purely
conceptually. Mapping `Coordinator` onto `internal/coordinator` + `internal/rootcoord` +
`internal/datacoord` + `internal/querycoordv2` + `internal/streamingcoord` is *assistant inference
from directory names*, not a transcription.

Every directory below was verified to exist at `master` before this file was written (spike finding
66's rule: resolve every claimed path against the tree). But existence is not the same as ownership —
**a wrong-but-existing mapping is exactly the failure mode that verification does not catch**, and it
is the reason `prometheus.md` is the better of the two fixtures despite its five-year-old source.

Report scores from this file with the glob authorship stated. If a component misses, "the ground
truth's globs were wrong" is a live hypothesis here in a way it is not for Prometheus.

---

## A harder shape than Prometheus, on purpose

Prometheus's eleven components mapped **1:1 onto Go package directories**, which is the easiest
possible case. Milvus's five map **one-to-many onto scattered directories** — `Coordinator` alone
spans six, split across `internal/` and `internal/distributed/`. Every component here can only be
matched as a *union of refinements* (§2a), never as an exact node.

That is the point of adding it. A detector that recovers Prometheus perfectly has not been shown to
handle components whose files do not sit under one root.

---

## Components

### Proxy

- **Type:** Software Service
- **Files:**
  - `internal/proxy/**`
  - `internal/distributed/proxy/**`
- **Identity:** Layer 1, the access layer — stateless, one or more per cluster
- **Provenance:** owner-published (globs and type assigned by assistant)
- **Notes:** the doc stresses statelessness and MPP result aggregation; `Software Service` over `Long Running Daemon` on that basis.

### Coordinator

- **Type:** Long Running Daemon
- **Files:**
  - `internal/coordinator/**`
  - `internal/rootcoord/**`
  - `internal/datacoord/**`
  - `internal/querycoordv2/**`
  - `internal/streamingcoord/**`
  - `internal/distributed/mixcoord/**`
- **Identity:** Layer 2 — "the brain of Milvus"; exactly one active across the cluster
- **Provenance:** owner-published (globs and type assigned by assistant)
- **Notes:** the current docs declare **one** Coordinator. Earlier Milvus (≤2.3) had four separate coordinators, and the `rootcoord`/`datacoord`/`querycoordv2` directories are survivors of that split now unified behind `coordinator` and `distributed/mixcoord`. **The six-directory glob is the single most inferred claim in this file.**

### Streaming Node

- **Type:** Long Running Daemon
- **Files:**
  - `internal/streamingnode/**`
  - `internal/distributed/streamingnode/**`
  - `internal/distributed/streaming/**`
- **Identity:** Layer 3 — the shard-level "mini-brain"; growing-data query, WAL-backed recovery, growing→sealed conversion
- **Provenance:** owner-published (globs and type assigned by assistant)

### Query Node

- **Type:** Software Service
- **Files:**
  - `internal/querynodev2/**`
  - `internal/distributed/querynode/**`
- **Identity:** Layer 3 — loads historical data from object storage and serves historical queries
- **Provenance:** owner-published (globs and type assigned by assistant)
- **Notes:** the directory is `querynodev2`; an unversioned `querynode` exists only under `internal/distributed/`.

### Data Node

- **Type:** Automated Action
- **Files:**
  - `internal/datanode/**`
  - `internal/distributed/datanode/**`
- **Identity:** Layer 3 — offline processing of historical data: compaction and index building
- **Provenance:** owner-published (globs and type assigned by assistant)
- **Notes:** `Automated Action` because the doc describes scheduled offline work rather than request serving. A uniform `Long Running Daemon` across all four worker/control components is a defensible alternative reading, since the doc says each component "can be deployed independently on Kubernetes".

---

## Excluded — not first-party

> Layer 4 (Storage) is declared by the owners as **three third-party dependencies**, not Milvus
> components. They own no first-party code and are listed here rather than as components, the same
> way `kafka`/`postgres` are handled in `egeria-workspaces.md`.

- **Meta Store** — etcd
- **Object Storage** — S3 / MinIO / Azure Blob
- **WAL Storage** — Kafka / Pulsar / Woodpecker

---

## Known gaps in this ground truth

> Gaps in the **document**, not in any detector. A detector reporting these is not producing false
> positives (§2a).

- **`internal/core/**`** — the C++ compute core (Knowhere / Segcore). Real, large, and named nowhere in the architecture overview.
- **`internal/storage/**`, `internal/metastore/**`, `pkg/mq/**`, `pkg/streaming/**`** — the first-party *clients* for the three third-party dependencies. The doc names the dependencies, never the code that talks to them.
- **`cmd/**`** — the binaries. Unmentioned.
- **`internal/{agg,allocator,cdc,compaction,flushcommon,http,json,kv,parser,registry,snapshotio,storagecommon,storagev2,tso,types,util,views,mocks}/**`** — supporting packages the logical architecture does not place.
- **`client/**`, `tests/**`, `tools/**`** — SDK, test suites, tooling.
