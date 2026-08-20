# Architecture Recovery — Phase 1 Plan

**Status:** plan, for review.
**Date:** 2026-08-20
**Follows:** `architecture-recovery-phase0-findings.md` (verdict: qualified pass)
**Design:** `architecture-recovery-design.md` · **Method:** `approach-portfolio-model.md`

---

## 1. Goal — ship to Discovery-sufficiency, not to correctness

Design §10's Phase 1 was "detectors + IR, no Egeria writes". Phase 0 built most of that as a
spike, so restating the goal by what it *delivers* rather than by what it constructs:

> **Phase 1 makes architecture recovery good enough for the Discovery stage, running inside RE as
> real survey steps, with nothing written to Egeria.**

Discovery is chosen deliberately, per the portfolio note §2. A partition at ARI ~0.56 is
comfortable for *"which subsystem is undocumented?"*, marginal for component-scoped metrics, and
nowhere near good enough to publish a blueprint. Targeting Discovery makes Phase 1 a **shippable
increment** with a defined stopping point, instead of an open-ended march toward publication
quality.

**The metric to move is coverage, not accuracy.** Phase 0's accuracy was fine — ARI 0.56, NMI 0.77
on what it proposed. Its problem was that it proposed 4 of 11 components covering 38 of 182 files.
Coupling already demonstrated it recovers 5 of the remaining 6. Phase 1's job is to collect that.

---

## 2. What already exists

Phase 0's spike is ~2,200 lines across nine modules, all working and all throwaway by design.
Phase 1 is substantially a **port**, which is a different and more predictable kind of work than
the last phase.

| Spike module | Lines | Phase 1 disposition |
|---|---|---|
| `exclusion.py` | 177 | **promote to a shared utility** — useful well beyond this feature |
| `ir.py` | 120 | port as the architecture IR |
| `detectors.py` | 445 | port — manifests, deployment units, compose |
| `code_markers.py` | 198 | port, with `rules/` as data |
| `imports.py` | 328 | port |
| `cochange.py` | 202 | port — **needs `git_clone_root`** |
| `coupling.py` | 406 | port, and **change its role** (§4.1) |
| `score.py` | 270 | keep as a test/eval harness, not a runtime step |
| `detect.py` | 70 | replaced by the step wiring |

**The spike has no tests.** That is correct for a spike and unacceptable for a port; test coverage
is a first-class item below, not an afterthought.

---

## 3. Prerequisites

**`git_clone_root` ResourceProvider.** Co-change needs history and a zipball has none.
`_acquire_zipball_root` (`repo_survey_definition_adapter.py:148`) is the pattern to follow;
`--filter=blob:none` keeps it cheap. This is design §5.7 gap 2 and it blocks one of the two
proposal signals.

**Nothing else.** `ast-grep-cli` is already a locked dependency; §5.7 gap 3 is closed.

---

## 4. The work

### 4.1 Coupling becomes a proposer, not a scorer

The single most important change, and it inverts what §5.5 specified.

Today `coupling.py` scores a partition someone else proposed. It must instead **contribute
components to the partition**: subtrees whose import and co-change cohesion clears a bar become
proposed components with their own evidence, ranked alongside marker-derived ones.

Two things this needs that Phase 0 did not build:

- **A null-model threshold.** The fixed cohesion bar is unresolved — 0.5 yields nothing, 0.3
  yields 5 of 5 correct, and 0.3 was chosen after seeing the data. Replace it with **Newman
  modularity**, which compares observed intra-cluster edges against those expected at random given
  the degree distribution, and so does not need a hand-set bar. This also fixes the degenerate
  cross-boundary ratio (findings 26/31), which is minimised by having no boundaries at all.
- **Hub detection.** `Core` was missed because a shared import hub structurally suppresses its own
  cohesion. Hubs are identifiable by the opposite signature — high fan-in from many components,
  low internal cohesion — so they need their own rule rather than a lower threshold.

### 4.2 Port into RE as survey steps

Two new `StepInfo` entries plus their `AnalysisKind` catalog entries, following
`repo_survey_definition_adapter.py`'s existing pattern:

| step key | wraps | resources | `target_shape` | `accepts_scope_locator` |
|---|---|---|---|---|
| `repo_arch_detect` | manifests + deployment + code markers → IR | `zipball_root` | `corpus` | yes |
| `repo_arch_coupling` | imports + co-change → proposals | **`git_clone_root`** | `corpus` | yes |

Both are `intent: analysis`, `source: local`, `action: survey`, `run_time: fast` — Phase 0
measured the whole toolchain at under 3 seconds per repo, so `fast` is honest rather than
optimistic.

They are two steps rather than one because they have different resource needs; grouping them in a
single Survey Definition still shares the checkout via `_run_batch`.

### 4.3 Evidence and results into the existing tables

- Evidence rows to `project_analysis_findings` with `kind='architecture_recovery'`, per design
  §5.4 — the shape already fits, including `scope_locator` as the join key.
- Component-scoped measures to `project_analysis_metrics`.
- **No new tables.** §6.5's argument stands: uniformity is what makes `AnnotationAgent` able to
  query any analysis for free, and a bespoke table forfeits that.

### 4.4 A results view

The AnalysisKind results reader/renderer so the partition is visible in RE — design §10's
"output viewable in RE". Components, their evidence, their confidence, and **which approach
proposed each**, since that last one is what makes the portfolio legible.

This is also the natural first home for the evidence rows, which currently have **no consumer at
all** (portfolio note §7).

### 4.5 Tests

The port is where a spike's untested assumptions become production defects. Minimum:

- Fixture-based tests for each detector against small synthetic trees — a repo with a Dockerfile
  and no manifest, layered compose with `container_name` in an override, a tracked `node_modules`.
  **Every Phase 0 finding that was a bug becomes a regression test**, which is the cheapest
  possible use of 32 written-up findings.
- `validate.py` and the ground-truth fixtures move into the normal test run, so a detector change
  that breaks the pre-registered partition fails CI rather than being discovered later.

### 4.6 Portfolio backfill — the small experiment

Portfolio note §8, and deliberately scoped to an afternoon: record Phase 0's four approaches
across three targets into `project_analysis_findings` as `kind='approach_run'`, failures included,
then check whether §4's selection rules fall out of that data.

If they do, the portfolio model is worth building in Phase 2. **If four approaches over three
repos yield nothing a person could not have said unaided, that is a real answer** and it is much
better to have it now than after building a selection engine.

---

## 5. Exit criteria — stated per stage

Phase 0's verdict was one number where it should have been four. Phase 1's is stated properly.

**Ships when Discovery-sufficient:**

| criterion | Phase 0 | Phase 1 target |
|---|---|---|
| components proposed (T2) | 4 of 11 | **≥ 9 of 11** |
| file coverage (T2, in scope) | 38 of 182 (21%) | **≥ 70%** |
| partition accuracy (ARI) | 0.56 | **≥ 0.5 maintained** |
| T1 deployment recall | 18/27 | **≥ 18/27 maintained** |
| runtime per repo | < 3s | **< 10s** including the clone |

The ≥9 target is not aspirational: it is 4 marker-derived plus the 5 coupling already recovered.
Accuracy is a *maintenance* target — the risk in Phase 1 is trading precision for coverage, so it
is stated as a floor rather than a goal.

**Explicitly NOT Phase 1 exit criteria** — these belong to later stages and chasing them here is
how the phase slips:

- Analysis-sufficiency (component-scoped metrics) — needs accuracy Phase 1 is not targeting.
- Publication-sufficiency (a blueprint in Egeria) — needs curation, which is Phase 3.
- `Core` and `Observability` specifically. Hub detection (§4.1) may reach them; if it does not,
  that is a finding for Phase 2's distillation, not a blocker here.

---

## 6. What changed from design §10's Phase 1

| §10 said | Phase 0 changed it to |
|---|---|
| implement the §5.1 detector table | **mostly done** — port it, and do not expand the rule set (findings 19/20: more markers would not have helped) |
| distillation heuristics only, no LLM | unchanged for Phase 1, but distillation **moves earlier than Phase 5**, scoped to hubs and naming |
| coupling as validation (§5.5) | **coupling as proposal** — the phase's main new work |
| four survey steps (§5.7) | **two** — `repo_code_metrics` and `repo_sbom` are metrics, not boundaries, and belong with Phase 4 |
| "testable with zero Egeria dependency" | unchanged, and now also **testable against pre-registered ground truth**, which did not exist when §10 was written |

---

## 7. Risks

**Trading precision for coverage.** The obvious way to hit ≥9 components is to lower every
threshold. The ARI floor exists to catch that, and the ground-truth fixtures make it visible
rather than a judgement call.

**Coupling generalising worse than it looked.** It scored 5/5 on one repo. Trellis is a
well-factored Python monorepo, which is close to the best case for import cohesion. Phase 1 should
run it against at least one repo unlike trellis before treating 5/5 as representative — `egeria`
(231 Gradle modules, Java) is the obvious adversarial target and was never scored.

**Porting quality.** 2,200 lines of throwaway code moving into a package that other people
maintain. §4.5 is the mitigation; the temptation to port first and test later is the failure mode.

**Threshold calibration remaining unsolved.** If modularity does not produce a stable bar,
Phase 1 needs a fallback — probably per-repo relative ranking (take the top-N most cohesive
subtrees) rather than an absolute threshold. Decide early; it affects the API.

---

## 8. Sizing

Bigger than Phase 0 and more predictable, since most of it is porting known-working code.
Roughly **two to three weeks**, dominated by §4.2 (the RE integration) and §4.5 (tests), with §4.1
the only genuinely novel work.

Order: prerequisites → §4.1 (coupling as proposer, since it determines the API) → §4.2 port →
§4.5 tests alongside, not after → §4.3/§4.4 surfaces → §4.6 backfill last, as it is independent.
