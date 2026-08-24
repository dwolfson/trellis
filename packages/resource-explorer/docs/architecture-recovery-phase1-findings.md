# Architecture Recovery — Phase 1 Measurement Findings

**Status: measurement goals MET. Engineering work not started.**
**Date:** 2026-08-20
**Plan:** `architecture-recovery-phase1-plan.md` · **Preceded by:** `architecture-recovery-phase0-findings.md`

---

## 1. The numbers

All five exit criteria from plan §5 are met, several by a wide margin.

| criterion | Phase 0 | target | **actual** |
|---|---|---|---|
| components proposed (T2, logical) | 4 of 11 | ≥ 9 of 11 | **13 of 13** *(see method note)* |
| file coverage (T2, in scope) | 21% | ≥ 70% | **97%** (184 of 190) |
| partition accuracy (ARI) | 0.56 | ≥ 0.5 held | **0.969** (NMI 0.977) |
| T1 deployment recall | 18 of 27 | ≥ 18 of 27 held | **18 of 27** |
| runtime per repo | < 3s | < 10s | **5.3s** |

> **METHOD NOTE, added after the number failed to reproduce.** "13 of 13" is measured by
> **max file-overlap F1 with a 0.5 threshold** — each ground-truth component matched to whichever
> proposed component overlaps it most, counted if F1 ≥ 0.5. That is the matcher that was actually
> run, and this document did not say so.
>
> Under **strict containment** — a ground-truth component matched only when some proposed node's
> file set equals it exactly — the same data gives **10 of 13**. Both numbers are correct; they
> measure different things. Ten components are reconstructed exactly, three more are reconstructed
> approximately.
>
> `score.py`'s own component-set measure gives **0 of 13**, because it matches on exact *names* and
> detectors emit directory basenames (`surveyors`) where the fixture has human names (`Surveyors`) —
> the artifact recorded as spike finding 21.
>
> So three matchers give 13, 10 and 0 on identical data. **A component count is meaningless without
> its matcher**, and a later session was right to report that the headline figure could not be
> reproduced. Quote the method with the number from here on; ARI/NMI are unaffected, being
> partition-level measures that need no matcher.

The coverage target was the one that mattered — Phase 0's accuracy was already fine and its
problem was that it saw a fifth of the repo. That is what changed.

## 2. What actually got it there

**Coupling inverted from scorer to proposer** (plan §4.1), which was the phase's one genuinely
novel piece. Two findings came out of it, one against the plan:

- **Newman modularity failed as a threshold.** §4.1 proposed it specifically to remove the
  hand-set cohesion bar. Measured, `Q > 0` is positive for **15 of 16** candidates — in a sparse
  import graph almost any subtree beats chance. Q survives as a *ranking*, not a bar. Recorded as
  a plan-level miss rather than quietly substituted.
- **Directional dispersion is what discriminates.** A cohesion bar rejects any *connective*
  component: `Core` has 27 internal import edges against 238 fan-in — cohesion 0.09, obviously a
  real component, unreachable by any threshold on that ratio. But its fan-in is spread evenly
  across 14 neighbours, and that is measurable as normalised entropy. Three shapes result, and
  only the third is genuinely not a component: **cohesive**, **connective** (library by fan-in,
  orchestrator by fan-out), and **merge-candidate** (externals concentrated on one neighbour it
  belongs to).

**The residue rule**, stated properly: a component owns everything beneath it that nothing else
claims. This is a **trade, not a clean win** — it took `Utility scripts` to exact and `Core` from
exact to 0.51, because the two ground-truth entries disagree about residue ownership deliberately.
Kept and recorded rather than special-cased, since special-casing is tuning to the fixture.

**Two bugs found by measurement, not by reasoning:**

- **Per-file import resolution.** `imports.py` resolved every absolute import against one global
  source-root list. `egeria-workspaces` ships `PyegeriaWebHandler` twice, both copies are source
  roots, so a sibling import in a *quickstart* handler resolved into the *freshstart* copy — 156
  of 170 quickstart edges were wrong. Fixed; trellis barely moved (1165 → 1185 edges), which is
  exactly why it hid.
- **Two retractions.** Phase 0's finding 32 (zero cross-copy import edges, offered as independent
  corroboration of the identity answer) and finding 36 (flat repos as a *layout* problem) were
  both artifacts of that one bug and are withdrawn.

## 3. What is NOT done

**Everything still lives in `scripts/arch-spike/`** — explicitly throwaway, imported by nothing,
with **zero tests**. The measurement half of Phase 1 is complete; the engineering half has not
started.

Outstanding from plan §4:

| item | state |
|---|---|
| §3 `git_clone_root` prerequisite | **done** |
| §4.1 coupling as proposer | **done** |
| §4.2 port into RE as two survey steps | not started |
| §4.3 evidence into the existing tables | not started |
| §4.4 results view | not started |
| §4.5 tests | not started |
| §4.6 portfolio backfill | not started |

Also open: the **flat-repo candidate generator** (designed and evidenced — Q 0.427, four
communities, clear connective-library leaders — but not built), and **Java extraction**, which
still blocks the only adversarial target.

## 4. Two decisions that are not the tooling's

- **Residue ownership.** `Core` and `Utility scripts` disagree about it on purpose, and no
  mechanical rule reproduces both. Cheap for a human to answer, impossible to derive — the
  disambiguation-worth-asking case from `approach-portfolio-model.md` §5a.
- **The orphans.** `github/`, `configdata/` and `dashboard/` are files the fixture never assigns.
  A `-revised.md` question, not a detector's judgement.

## 5. Confidence in these numbers

**High for what they measure; narrow in what they establish.** Two repos, both ours, both Python,
thresholds set by inspection on one of them, and T2's ground truth is not a clean pre-registration
(the component count was known before the fixture was written — contamination that runs the safe
way, since the fixture contradicts the detector rather than echoing it).

`Backlog.md` carries a standing item to re-run the whole evaluation at roughly **8–10 surveyed
repos of varied shape**, or the first time a real user disagrees with a published partition.
Re-running is hours, because `score.py` and the fixtures already exist — the real cost is writing
pre-registered ground truth for the new targets, and that is exactly what makes the re-check worth
doing rather than a re-confirmation.

**Declared met, and moving on to the port.**
