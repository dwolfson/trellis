# The Approach Portfolio — evaluating, selecting and improving analysis methods

**Status:** design note, for review.
**Date:** 2026-08-20
**Origin:** an observation made after the architecture-recovery Phase 0 result
(`architecture-recovery-phase0-findings.md`), which needed a *bag* of approaches rather than one.
**Scope:** written from architecture recovery, but **not specific to it** — it applies to any RE
analysis where more than one method could produce the answer.

---

## 1. The observation

Phase 0 established that no single method recovers component boundaries. Manifests find declared
packages. Deployment artifacts find specified containers. Code markers find framework-shaped
subtrees. Coupling finds conventional ones. Each covers a different slice, and the union is still
incomplete — `Core` and `Observability` were missed by every method tried.

The generalisation: **for a hard analysis, the unit of work is not "the algorithm" but "the
portfolio".** That changes what the system has to be good at. Not *executing* an approach — that
part is easy — but **evaluating, selecting, retiring and learning from** approaches.

**This is RE's own funnel applied one level up.** The funnel says: run cheap things broadly,
escalate only what earns it, spend human attention where confidence is low. All of that applies
to approaches exactly as it applies to resources. That is why most of the machinery below already
exists and needs connecting rather than building.

---

## 2. Sufficiency, not correctness — the reframe that matters most

**Evaluation should ask "is this good enough for what this stage will do with the answer?", not
"is this correct?"**

Phase 0 reported T2 as ARI 0.56 and called it a qualified pass, as if correctness were the
target. But 0.56 is not one verdict, it is four:

| Stage | What it does with a partition | Is ARI 0.56 enough? |
|---|---|---|
| **Scouting** | nothing — needs no partition | n/a |
| **Discovery** | "which subsystem is undocumented?" | **yes, comfortably** |
| **Analysis** | component-scoped metrics (§6) | marginal — usable with confidence shown |
| **Assessment / publish** | a blueprint in the catalog of record | **no, not close** |

Two consequences:

- **A result is reported against a stage, never in the abstract.** "Qualified pass" should have
  read "pass for Discovery, qualified for Analysis, fail for publication". That is more useful and
  no harder to produce.
- **Stop as soon as the stage is satisfied.** If Discovery only needs a coarse partition, running
  coupling and distillation to sharpen it is wasted spend. **This is the funnel's own rule** —
  cheap first, escalate only what earns it — applied to approaches. It is also where the user
  should sometimes be asked directly: *"this is good enough for Discovery; sharpening it costs a
  distillation pass — worth it?"*

---

## 3. What has to be recorded

Point (4) of the observation — capture failures, not just successes — has a concrete gap. Phase 0
produced 32 findings, many of them failures with real diagnostic value:

- a `build.context` merge that dropped recall 0.78 → 0.48, and *why* (build unit to component is
  one-to-many)
- Jaccard silently mislabelling correct partial matches as novel boundaries
- two of eight code-marker rules wrong **in opposite directions** — one matching 620 times, one
  matching zero

**All of it is prose in a README.** None of it is queryable, so none of it can inform approach
selection, and periodic improvement analysis would have to re-read it by hand.

The fix is small because the table exists. `project_analysis_findings`
(`registry.py:866`) already carries `kind` / `check_name` / `label` / `confidence` /
`scope_locator` / `detail_json`. An approach **run** is an analysis outcome and fits it directly:

| column | carries |
|---|---|
| `kind` | `approach_run` |
| `check_name` | approach id (`code_markers`, `coupling`, `manifest`) |
| `label` | `recovered` / `partial` / `no_signal` / `regression` |
| `confidence` | the score, on whatever measure the perspective requires |
| `scope_locator` | the target, and the sub-scope if narrowed |
| `detail_json` | measures, thresholds, cost, what it missed |

Two properties this buys, both from §6.5's argument that uniformity is what makes things
queryable:

- **`AnnotationAgent` can answer approach questions for free** — *"which approaches have ever
  recovered a hub-shaped component?"* — because the table is generic.
- **A failure is a first-class record**, not an absence. `no_signal` and `regression` are
  outcomes, and a `regression` row is the most informative row in the table.

**A zero must be distinguishable from a not-run.** Finding 19's rule generalises: a zero means
either the thing is genuinely absent or the method is broken, and the two are indistinguishable
without a known-positive check. So an approach run records *whether it had a known-positive*, and
an approach with no known-positive check cannot report `no_signal` — only `unverified`.

---

## 4. Selecting the next approach — the modest version

Point (2) — learn from earlier approaches to select later ones — is achievable **without a model**,
and the ambitious version should be resisted until the modest one is exhausted.

What is needed is `(repo characteristics) → (approach, outcome)`, and **the characteristics are
already collected by Scouting**: language mix, presence of deployment artifacts, monorepo layout,
size, first-party ratio. Those are exactly the axes that predicted the Phase 0 outcomes.

From a handful of repos this yields rules of the shape:

> No deployment artifacts, >80% Python, single package → markers recover ~35% of components,
> coupling ~80%. **Run coupling first.**

> Compose-rich, low first-party ratio → deployment detectors recover ~100% of declared
> containers. **Markers add nothing; skip them.**

That is a lookup keyed on characteristics, honest about small samples, and useful from the third
repo onward. It also degrades gracefully: an unfamiliar characteristic profile just means "run the
cheap ones and find out", which is the current behaviour.

**Resist**: learned ranking models, per-repo tuning, anything needing a corpus RE does not have.
The estate is tens of repos, not thousands.

---

## 5. Asking for help — optional, with a declared consequence

Point (5). Some questions are cheap for a human and impossible for a detector. Phase 0 produced a
measured example: *"are the two `PyegeriaWebHandler` copies one component or two?"* took the
maintainer seconds, no algorithm could have answered it, and the answer **reordered the identity
precedence chain in §8.2** — deployment unit ahead of declared package name, a design change that
propagated through the rest of the phase.

Design rules, all of which follow from wanting this to survive estate scale:

1. **Never blocking.** A question that halts an analysis does not survive 200 repos. The analysis
   proceeds on its best guess and records that it did.
2. **The consequence of skipping is stated.** *"Skipping means these two are reported as one
   component, and per-component metrics will merge them."* The user is choosing a known
   degradation, not ignoring a nag — and choosing it is often correct.
3. **The answer is recorded as an answer, not as a result.** It goes to the curation overlay
   (§7.2), keyed by stable qualified name, so re-derivation does not ask again.
4. **Ask only where the answer changes something.** A disambiguation that does not alter the
   output is noise, and noise is how a channel like this gets ignored.
5. **RFA is the existing channel** (§7.3, `rfa_actions`) — this is RFA used *during* analysis for
   disambiguation, rather than only *after* it for findings. That is a widening of an existing
   mechanism, not a new one.

The honest framing for the user is that their attention is the scarcest input in the system, so it
should be spent only where it is worth more than the compute it replaces — and they should be able
to see that trade and decline it.

---

## 6. Bounding it — the risk

**A portfolio with an evaluation harness is exactly the shape of a research project that never
ships.** Approaches accumulate, each defensible, none retired, and the ranking machinery grows
faster than the results.

Proposed bounding rule:

> **An approach earns a place only by beating the current portfolio on a target it already
> covers, or by covering a target no current approach reaches. An approach that does neither on
> two consecutive evaluations is retired, and its failure record is kept.**

Retirement matters as much as admission. Keeping the record while dropping the code is what makes
this an improvement loop rather than an accumulation.

Two further limits worth stating now:

- **The harness must stay cheaper than the approaches it ranks.** Phase 0's whole toolchain runs
  in under 3 seconds per repo; an evaluation layer costing minutes would invert the economics.
- **Approaches are compared per perspective, never across.** Phase 0 established this the hard way
  (§4.1): a method that recovers deployment architecture is not "better" than one that recovers
  logical architecture. They answer different questions.

---

## 7. What already exists

Deliberately listed, because the amount of new machinery is smaller than the idea suggests.

| Need | Existing |
|---|---|
| catalogue of approaches with cost/tier | `configdata/analysis_catalog.yaml`, §5.6 cost tiers |
| record an approach outcome | `project_analysis_findings` / `_metrics` (generic, `scope_locator`-keyed) |
| query outcomes | `AnnotationAgent` (§6.5c) — free, because the tables are uniform |
| ask a human | `rfa_actions` + the RFA drawer (§7.3) |
| record the answer durably | the curation overlay (§7.2) |
| repo characteristics for selection | Scouting-tier analyses, already collected |
| evaluate a partition | `score.py` / `coupling.py` from Phase 0 |
| stage semantics for sufficiency | the eight intents, already canonical |

**Genuinely new:** an approach *identity* and its outcome vocabulary; the sufficiency-per-stage
thresholds; the selection lookup; and the retirement rule.

---

## 8. Suggested first step

Do not build the portfolio manager. **Backfill Phase 0's own results into the outcome table** —
four approaches (manifest, deployment, code markers, coupling) across three targets, with the
failures included — and see whether the selection rules in §4 fall out of that data or not.

If they do, the model is worth building. If four approaches over three repos produce nothing a
person could not have said unaided, that is a real answer too, and it costs an afternoon to find
out rather than a phase.
