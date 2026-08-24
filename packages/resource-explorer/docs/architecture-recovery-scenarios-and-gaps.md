# End-to-end scenarios and the gap list

**Written 2026-08-23**, at the maintainer's request: *"let's review our plan and build a task/gap
list. We should figure out how we build out end-end scenarios, not just the individual pieces."*

That is the right criticism. A lot of capability now exists — three classification modules, a
registered Discovery step, Go support, ports and wires, a five-repo scored corpus — and **none of it
yet forms a path a user can walk from end to end.** This document is organised by scenario rather
than by component, and each scenario is traced until it breaks.

Status vocabulary: **built** = exists and is reachable in a survey; **built, unwired** = code exists,
nothing calls it; **designed** = written down, not built; **blocked** = waiting on someone else.

---

## Scenario A — "I found a repo. Should I care?"

The cheapest complete journey, and the closest to working.

| step | status |
|---|---|
| register + scout the repo | **built** |
| classify role, locate expected artifacts | **built** (`repo_classification`, runs first in Discovery) |
| decide run/skip for the expensive tiers | **built** (`recovery_gate`) |
| report the skip as a *success* | **BLOCKED** — no `step_outcome` label fits a deliberate skip |
| offer a disposition ("adopt / monitor / ignore") | **designed** (§5.5d) |

**Breaks at:** the outcome vocabulary, then disposition. The gate works and its result is legible as
a finding, but the funnel's biggest win — deciding *not* to spend — still reports as something less
than a success.

**Smallest fix that completes it:** agree a sixth outcome (or relax `no_signal`) with the owner of
`step_outcome.py`, then map gate + role to a disposition. Disposition may need no new vocabulary —
Egeria's `ResourceUse` is a strong candidate (§5.5d) and has not been checked.

---

## Scenario B — "Recover this repo's architecture and put it in the catalog"

The most-built and the least-finished.

| step | status |
|---|---|
| gate says run | **built** |
| detect components (Python/Java/JS/Go) | **built**, scored on 5 repos |
| ports and wires | **built, unwired** — `interfaces.py` produces them; `detect.py` does not call it |
| distil candidates to an answer | **DESIGNED ONLY** — §5.2, Phase 5 |
| publish to Egeria as a blueprint | **designed** — Phase 2, gated on outbox/retry (§8.4) |

**Breaks at:** distillation, hard. Recall is essentially solved (Prometheus 11/11, Kubernetes 6/6,
Milvus 3/5 + 2 at 99.8%) and precision is not: **3270 candidates for 6 declared components** on
Kubernetes. Ranking narrows that to hundreds, not tens (finding 77). Nothing turns hundreds into an
answer a human reads.

**This is the single biggest blocker in the system.** Everything downstream — the catalog, the
blueprint, any disposition that depends on structure — is waiting behind it.

---

## Scenario C — "We already use X. Is it still OK?"

The motivation the design most recently added (§5.5d, motivation 4), and the least served.

| step | status |
|---|---|
| know that we use it, and how | **MISSING ENTIRELY** — no corpus of our own usage exists |
| evaluate robustness / security | partly built (security surveyors) but not motivated by 4b |
| detect that an upgrade is needed | **designed** — inherently recurring, so it is Automate, not a one-shot |
| notify | **built** (subscriptions + RFA) |

**Breaks at the first step**, and this is the finding worth repeating from §5.5d: for an in-use
resource there is a second corpus — which version we run, which APIs we call, how deeply it is
embedded — and **none of it lives in the repo being surveyed.** Every motivation under 4 is partly
unanswerable from the repo alone. Scenario C cannot be completed by improving repo analysis.

---

## The gap list, ordered by what unblocks the most

1. **Distillation (§5.2, Phase 5).** Blocks Scenario B entirely and every catalog-facing outcome.
   Detection is solved; this is not. Largest single piece of remaining work.
2. **Outcome vocabulary for a deliberate skip.** Blocked on another owner; small, and completes
   Scenario A's reporting.
3. **Wire `interfaces.py` into `detect.py` + the IR, with unit tests.** Small, and it is the input
   Scenario B's distillation and any "does it fit our infrastructure" question both need.
4. **Disposition (§5.5d).** Check `ResourceUse` before inventing — the same check that paid off twice
   already. Turns findings into an answer.
5. **Motivation (§5.5d) and the derived black/white lens (§5.5e).** Selects question sets; the lens
   is nearly free once motivation exists.
6. **Egeria projection (Phase 2).** Gated on outbox/retry (§8.4).
7. **A usage corpus.** Unblocks Scenario C; genuinely new input, not a refinement.

## Known defects, none blocking

- `find_artifact("readme")` prefers a nested README over the repo root.
- The gate over-runs on documentation repos carrying their own build tooling (`kubernetes/website`).
  Safe direction: a false RUN wastes a tier, a false SKIP loses work.
- trellis `Web backend` misses exactly one file, `web/app.py`.
- Go package-level import cohesion is structurally ~0 without recursive rollup subtrees.
- The `cmd/X` + `pkg/X` merge is unsolved; the name-based rule was deliberately not shipped
  (finding 78) and needs a repo nobody has looked at to test it.

## Deferred by decision, not oversight

- **Exposure and consumption model** — what kind of thing is being exposed (library to import,
  service to call, container to run, dataset to read). §5.5e defers it; §5.5f's ports and wires are
  its concrete half and can proceed without it.
- **User intent**, raised 2026-08-23 and deferred to its own discussion.
