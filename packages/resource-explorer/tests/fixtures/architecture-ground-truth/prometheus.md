# Ground-truth partition — prometheus/prometheus

> **PRE-REGISTERED — and by a new route.** The component set in this file was **not written by a
> maintainer of this project and not inferred from the code.** It is transcribed from the Prometheus
> project's own published architecture document,
> [`documentation/internal_architecture.md`](https://github.com/prometheus/prometheus/blob/main/documentation/internal_architecture.md),
> written by the Prometheus authors years before Resource Explorer existed. See "Provenance" below —
> this is a different kind of pre-registration from `trellis.md` / `egeria-workspaces.md` / `egeria.md`,
> and it is deliberately labelled as such rather than blended in with them.
>
> No detector has been run against this target. This file is committed first; the commit timestamp is
> the evidence, per `README.md` rule 2.

**Target:** `prometheus/prometheus`
**Checkout:** clean `--depth 1 --filter=blob:none` clone of `main` (1668 tracked files)
**Perspective:** logical
**Vocabulary:** `SolutionComponentType` — the closed 13 (design doc §3.1)
**Written by:** transcribed by assistant from the owners' published architecture doc — see Provenance
**Written at:** 2026-08-22

**Source document:** `documentation/internal_architecture.md`
**Source last modified:** 2021-06-17 (its own last commit — **five years stale relative to `main`**)
**Source self-declared version:** the doc states *"Code links and explanations are based on Prometheus
version 2.3.1. Future Prometheus versions may differ."* — and pins every code link to `/blob/v2.3.1/`.

---

## Provenance — read this before using the file

This partition has **three different authorships inside it**, and they must not be conflated:

| element | author | note |
|---|---|---|
| component set and boundaries | **the Prometheus authors** | the doc's own `##` sections; nobody involved had seen Resource Explorer |
| file globs | **the Prometheus authors**, generalised | the doc links to specific files (`storage/fanout.go`, `promql/engine.go`, `notifier/notifier.go`, …); the assistant widened file → owning directory |
| `Type:` assignments | **assistant** | the owners do not use Egeria's vocabulary, so every mapping onto the 13 values is a judgement call and is contaminated |

So report scores the way `README.md`'s Provenance section prescribes, but with a **new provenance
class**: `owner-published`. Every component below carries
`Provenance: owner-published (type assigned by assistant)`.

The reason this counts as pre-registered despite being transcribed by an assistant, where
`README.md` rule 1 forbids assistant-drafted partitions: rule 1 exists to stop a partition being
*inferred from the code it is then scored against*. Here the component set was fixed in a published
document years earlier. The assistant's contribution is transcription and type assignment, both
declared. **The type column is the contaminated one** — if a score depends on it, say so.

---

## Version — this is a back-level document, deliberately used anyway

The doc declares itself as describing **v2.3.1** (released 2018). Every path it cites was resolved
against both refs before this file was written (design doc §5.5a(b), spike finding 66):

| path | `v2.3.1` | `main` |
|---|---|---|
| `cmd/prometheus`, `config`, `discovery`, `scrape`, `storage`, `storage/remote`, `promql`, `rules`, `notifier`, `web` | present | present |
| `tsdb` | **absent** | present |

`tsdb` was a separate repository (`prometheus/tsdb`) at v2.3.1 and was later vendored in-tree. The doc
is therefore **internally version-inconsistent**: twelve sections pin their links to `/blob/v2.3.1/`,
while the Local storage section alone links to `/blob/main/tsdb/db.go` — one section was patched later
and the rest were not.

**This file targets `main`, not `v2.3.1`**, because that is what a real survey would see. Every glob
below resolves at `main`. The declared *component set* survives the five-year gap intact — all
thirteen sections still correspond to real top-level packages — which is itself worth recording: the
logical architecture proved more durable than the line-level code links inside the same document.

---

## Components

### Main function

- **Type:** Long Running Daemon
- **Files:**
  - `cmd/prometheus/**`
- **Identity:** the server process entry point; instantiates every other component and runs them in an actor-like model
- **Provenance:** owner-published (type assigned by assistant)
- **Notes:** the doc's **Termination handler** and **Reload handler** are `##`/`###` sections in their own right but are goroutines *inside* `main.go` — sub-file granularity, not separately partitionable. They are folded in here rather than dropped, and a detector that does not find them is not wrong.

### Configuration

- **Type:** Software Library
- **Files:**
  - `config/**`
- **Identity:** `config.LoadFile()` / the `config.Config` structure
- **Provenance:** owner-published (type assigned by assistant)

### Service discovery

- **Type:** Automated Action
- **Files:**
  - `discovery/**`
- **Identity:** `discovery.Manager`
- **Provenance:** owner-published (type assigned by assistant)
- **Notes:** the doc declares **two** components here — "Scrape discovery manager" and "Notifier discovery" — but says of the latter that it *"is a `discovery.Manager`"* and *"internally it works like the scrape discovery manager"*. They are two **runtime instances of one component**, not two components, and one directory backs both. Merged on the substitutability criterion. A detector cannot separate them from files alone, and should not be scored as if it could.

### Scrape manager

- **Type:** Automated Action
- **Files:**
  - `scrape/**`
- **Identity:** `scrape.Manager`; one scrape pool per `scrape_config`, one scrape loop per target
- **Provenance:** owner-published (type assigned by assistant)

### Fanout storage

- **Type:** Software Library
- **Files:**
  - `storage/*.go`
- **Identity:** `storage.Storage` implementation proxying local + remote; merges reads, duplicates writes
- **Provenance:** owner-published (type assigned by assistant)
- **Notes:** deliberately `storage/*.go` and not `storage/**` — `storage/remote/` is its own declared component below.

### Local storage

- **Type:** Data Storage
- **Files:**
  - `tsdb/**`
- **Identity:** `tsdb.DB` — the on-disk time series database
- **Provenance:** owner-published (type assigned by assistant)
- **Notes:** the one component whose doc link points at `main` rather than `v2.3.1`; see the Version section.

### Remote storage

- **Type:** Data Distribution
- **Files:**
  - `storage/remote/**`
- **Identity:** `remote.Storage`; one `remote.QueueManager` per `remote_write` section
- **Provenance:** owner-published (type assigned by assistant)

### PromQL engine

- **Type:** Software Library
- **Files:**
  - `promql/**`
- **Identity:** evaluates PromQL against the storage
- **Provenance:** owner-published (type assigned by assistant)
- **Notes:** the type here is the **least** contaminated of the thirteen — the doc states outright that the engine *"does not run as its own actor goroutine, but is used as a library"*, so `Software Library` is the owners' own characterisation, not an assistant's inference.

### Rule manager

- **Type:** Automated Action
- **Files:**
  - `rules/**`
- **Identity:** `rules.Manager`; evaluates recording and alerting rules on `evaluation_interval`
- **Provenance:** owner-published (type assigned by assistant)

### Notifier

- **Type:** Publishing
- **Files:**
  - `notifier/**`
- **Identity:** `notifier.Manager`; enqueues alerts from the rule manager and dispatches to Alertmanager
- **Provenance:** owner-published (type assigned by assistant)
- **Notes:** `Publishing` vs `Data Distribution` is a genuine coin-flip against this vocabulary. Recorded as a known-weak type assignment rather than silently picked.

### Web UI and API

- **Type:** User Interface
- **Files:**
  - `web/**`
- **Identity:** serves the UI at `/`, the API under `/api/v1`, console templates under `/consoles`
- **Provenance:** owner-published (type assigned by assistant)
- **Notes:** one declared component covering both a human UI and a programmatic API. `web/ui/` is the TypeScript frontend and is included.

---

## Unassigned OK

> First-party paths the published architecture does not place. Listing them here excludes them from
> scoring, so this is kept deliberately short.

- `docs/**`
- `documentation/**`
- `scripts/**`
- `.github/**`
- `*.md`
- `Makefile*`
- `Dockerfile*`

> Drafted from the doc, `console_libraries/**` and `consoles/**` were also listed here — the doc
> discusses console templates served under `/consoles`. **Both directories were removed from
> Prometheus in 3.0 and do not exist at `main`**, so they were struck before this file was committed.
> Noted rather than silently dropped: it is a third instance of the doc's v2.3.1 vintage showing
> through, alongside `tsdb` and `relabel`. `validate.py` did **not** catch it — it glob-checks
> component globs but not `Unassigned OK` globs, which is a real gap given `README.md`'s own warning
> that over-listing here hides misses.

---

## Known gaps in this ground truth

> These are gaps in the **document**, not in any detector. A detector that reports these is **not**
> producing false positives, and §2a's rule applies — finding more structure must not score worse.

- **`cmd/promtool/`** — a second binary shipped from this repo. The doc scopes itself to "the Prometheus server" and never mentions it. It is a real component that the ground truth omits.
- **`model/`, `internal/`, `plugins/`, `schema/`, `tracing/`, `compliance/`, `prompb/`, `template/`, `util/`** — top-level packages at `main` that did not exist, or were not discussed, when the doc was written. Unplaced by the owners, so unscoreable here.
- **`relabel/`** — existed at v2.3.1 and the doc discusses relabeling behaviour, but never as a component with a home. At `main` it has moved under `model/`.
