# Ground-truth partition — kubernetes/kubernetes

> **PRE-REGISTERED, `owner-published` provenance** — third fixture of this kind, after
> `prometheus.md` and `milvus.md`. The component set is transcribed from Kubernetes's own
> `content/en/docs/concepts/architecture/_index.md` in `kubernetes/website`, written by the
> Kubernetes authors with no knowledge of Resource Explorer. No detector has been run against this
> target. This file is committed first; the commit timestamp is the evidence (`README.md` rule 2).

**Target:** `kubernetes/kubernetes`
**Checkout:** clean `--depth 1 --filter=blob:none` clone of `master` (31300 tracked files)
**Perspective:** logical
**Vocabulary:** SolutionComponentType — the closed 13 (design doc §3.1)
**Written by:** transcribed by assistant from the owners' published architecture — see Provenance
**Written at:** 2026-08-22

**Source document:** `content/en/docs/concepts/architecture/_index.md` ("Cluster Architecture") in
**`kubernetes/website`** — a *different repository* from the one being surveyed.

---

## Why this fixture exists — the docs are not in the repo being surveyed

`kubernetes/kubernetes/docs/` contains exactly two entries, `.gitignore` and `OWNERS`. It is a
**tombstone** (spike finding 68): the documentation moved to `kubernetes/website`, which is actively
maintained. A survey that reads only in-repo docs finds nothing here, and a naive doc-freshness
metric scores Kubernetes at ~1400 days of abandoned documentation while the real docs were updated
the same day.

This is the concrete case behind design §5.5a(a) — **the outward hop to the project's doc site is not
an enhancement** — and it is the first fixture where the ground truth is sourced from a different
repository than the code.

---

## Provenance

| element | author |
|---|---|
| component set and control-plane/node grouping | **the Kubernetes authors** |
| **file globs** | **assistant** |
| `Type:` assignments | **assistant** |

Like `milvus.md` and unlike `prometheus.md`, **the source document contains no code links** — it
describes components operationally (what runs where) rather than by implementation. Mapping
`kube-apiserver` onto `cmd/kube-apiserver` + `pkg/kubeapiserver` + `pkg/controlplane` is assistant
inference. Every path below was verified to exist at `master` before this file was written (finding
66's rule), but **existence is not ownership**.

One mitigation Kubernetes offers that Milvus did not: the component names are also the **binary
names**, and the repo follows the `cmd/<binary>` convention exactly. The `cmd/` half of each glob is
therefore near-certain; the `pkg/` half is the inferred part.

---

## Shape — one-to-many again, and split across two top-level trees

Like Milvus, no component is a single directory. Unlike Milvus, each spans **two different top-level
trees** (`cmd/` and `pkg/`), so a proposer that only recognises directory containment cannot
reconstruct these at all — the union must reach across `cmd/kube-scheduler` and `pkg/scheduler`.

---

## Components

### kube-apiserver

- **Type:** Software Service
- **Files:**
  - `cmd/kube-apiserver/**`
  - `pkg/kubeapiserver/**`
  - `pkg/controlplane/**`
- **Identity:** control plane — the front end for the Kubernetes API
- **Provenance:** owner-published (globs and type assigned by assistant)
- **Notes:** the only component here that is clearly a request-serving service rather than a control loop.

### kube-scheduler

- **Type:** Long Running Daemon
- **Files:**
  - `cmd/kube-scheduler/**`
  - `pkg/scheduler/**`
- **Identity:** control plane — watches for unscheduled Pods and selects a node
- **Provenance:** owner-published (globs and type assigned by assistant)

### kube-controller-manager

- **Type:** Long Running Daemon
- **Files:**
  - `cmd/kube-controller-manager/**`
  - `pkg/controller/**`
- **Identity:** control plane — runs many logically independent control loops in one binary
- **Provenance:** owner-published (globs and type assigned by assistant)
- **Notes:** the doc names Node, Job, EndpointSlice and ServiceAccount controllers as examples and says the list is not exhaustive. They are loops *inside* this binary, not separate components, so `pkg/controller/**` is taken whole.

### cloud-controller-manager

- **Type:** Long Running Daemon
- **Files:**
  - `cmd/cloud-controller-manager/**`
  - `staging/src/k8s.io/cloud-provider/**`
- **Identity:** control plane — the cloud-provider-specific control loops; absent from on-premises clusters
- **Provenance:** owner-published (globs and type assigned by assistant)
- **Notes:** the doc is explicit that this component is optional and provider-specific. Most provider implementations live in separate repositories; what remains in-tree is the framework.

### kubelet

- **Type:** Long Running Daemon
- **Files:**
  - `cmd/kubelet/**`
  - `pkg/kubelet/**`
- **Identity:** node component — runs on every node, ensures containers are running in a Pod
- **Provenance:** owner-published (globs and type assigned by assistant)

### kube-proxy

- **Type:** Long Running Daemon
- **Files:**
  - `cmd/kube-proxy/**`
  - `pkg/proxy/**`
- **Identity:** node component — maintains network rules implementing the Service abstraction
- **Provenance:** owner-published (globs and type assigned by assistant)
- **Notes:** the doc marks this **optional** — a network plugin providing equivalent proxying replaces it.

---

## Excluded — not first-party

> Declared by the owners as cluster components but implemented outside this repository.

- **etcd** — the control plane's backing store; a separate project
- **Container runtime** — containerd / CRI-O, behind the CRI
- **Addons** — DNS, Dashboard, container resource monitoring, cluster-level logging, and CNI network plugins. All named in the architecture document, all separate projects.

---

## Known gaps in this ground truth

> Gaps in the **document**, not in any detector (§2a).

- **`staging/src/k8s.io/**`** — the published client libraries (`client-go`, `apimachinery`, `api`, `apiserver`, …). Enormous, first-party, and named nowhere in the cluster architecture, which describes running processes rather than libraries. `cloud-provider` is the one exception, claimed above.
- **`cmd/kubeadm/**`, `cmd/kubectl/**`** — real binaries in this repo. The architecture doc covers cluster components, not user or bootstrap tooling.
- **`pkg/api/**`, `pkg/apis/**`, `pkg/registry/**`, `pkg/volume/**`, `pkg/util/**`** and siblings — supporting packages the operational architecture does not place.
- **`test/**`, `hack/**`, `plugin/**`, `third_party/**`** — testing, tooling, vendored code.
