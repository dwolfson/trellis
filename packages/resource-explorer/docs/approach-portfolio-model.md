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

## 2a. Granularity is not precision — and depth is never discarded

**A correction, and the scoring model was wrong before it.** Asked how a nested proposal should
score against a flat ground truth, the framing offered was: a proposer that emits
`surveyors/` *and* its five subdirectories scores 1 hit and 5 false positives, precision 0.17.

That is wrong, and wrong in a way that would have pushed the design toward throwing away work.

| | question it answers | a sub-component is… |
|---|---|---|
| **Precision** | is what we proposed **real**? | not an error — it corresponds to something |
| **Granularity** | at what **level** did we express it? | a finer expression of the same truth |

`surveyors/database` is a real, coherent subsystem. The fixture records `Surveyors` as one
component because that is the level its author needed, not because `database` is a fiction.
Counting it as a false positive punishes the proposer for knowing more than the fixture does.

**The contrast that shows this is not mere permissiveness**: the `workshops` repo (finding 58)
proposed 45 components for a repo of tutorial materials. That **is** a precision failure — there
is no architecture there to be fine-grained about. The test is *"does this correspond to something
real?"*, not *"is this coarser or finer than expected?"*

So:

- **A node inside a matched ground-truth component is a refinement**, not an error.
- **A node corresponding to nothing** is a precision error — or a gap in the fixture, which finding
  47 showed is a real possibility.
- **Finding more structure never scores worse.** It costs compute and storage; it does not cost
  correctness.

### Depth is kept, not pruned

The stronger consequence is about storage, not scoring. Extra granularity *"isn't necessary at this
time — might be worth keeping and using later."*

That rules out the whole family of designs that pick a level and discard the rest. If Discovery
needs a coarse partition and Analysis a fine one (§2), then computing depth and throwing it away
means recomputing it when the next stage asks — and re-deriving is exactly what the curation
overlay exists to avoid re-doing (design §7.2).

**Store the hierarchy; project a level.** Egeria supports this natively — `SolutionComposition`
nests `SolutionComponent`s (design §3.3a) — so retaining depth is not a workaround, it is what the
target model expects. A consumer takes the level it needs; nothing computed is thrown away.

This also retires the question finding 56 spent an experiment on. *"Which depth?"* was never
answerable, because it was the wrong question: the generator should not choose a level at all.

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
| `label` | the outcome — one of the five below |
| `confidence` | the score, on whatever measure the perspective requires |
| `scope_locator` | the target, and the sub-scope if narrowed |
| `detail_json` | measures, thresholds, cost, what it missed |

**The outcome vocabulary — five labels, and they are what Egeria calls a produced guard.**

| label | meaning |
|---|---|
| `recovered` | the approach produced what it claims to |
| `partial` | produced something, but knowingly incomplete (e.g. a scoped run — design §4.1c) |
| `no_signal` | genuinely nothing to find, **and a known-positive check proves the method works** |
| `unverified` | could not run at all, or ran with no known-positive to validate against |
| `regression` | worse than a previous run on the same target |

`unverified` was previously stated only in the prose rule below and not listed here, which made the
vocabulary read as four labels. It is five.

**Outcome and cause are separate fields, and that is a constraint rather than a preference.**
Verified against `NextGovernanceActionProcessStepProperties`: an Egeria guard carries exactly
`guard: Optional[str]` and `mandatory_guard: Optional[bool]` — **a single flat token, no structured
payload**. So outcome and cause cannot both ride in the guard, which fixes the split:

| | carrier | why |
|---|---|---|
| **outcome** (the five above) | the **guard** | a flat token is exactly what a `NextGovernanceActionProcessStep` can branch on |
| **cause** (`no_homepage`, `self_published`, `no_known_positive`, `run_scope`) | the **finding row** | `project_analysis_findings.detail_json`, where `run_scope`/`partial` already live |

If a cause ever needs to reach a *later step* rather than only be recorded, the model's carrier is
**Produced Request Parameters** ("new parameters generated by the service, passed to subsequent
steps"), not the guard. Read, not yet exercised.

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

> **TESTED 2026-08-20 AT n=3 — THE RULES BELOW DO NOT HOLD. See §8's result.** The two worked
> examples are kept as illustrations of the *shape* a rule would take, not as findings. One is
> circular and one is disconfirmed:
>
> - The *"markers ~35%"* figure matches trellis's measured 4/11 = 36% — but this note was written
>   **after** `architecture-recovery-phase0-findings.md` (commits `973e6d0` then `726b338`), so
>   that is Phase 0's own result reflected back, not independent confirmation. The coupling half
>   of the same example (*"~80%"*) is nearer 62% in isolation.
> - The *"compose-rich → deployment ~100%"* example is **disconfirmed**. `egeria-workspaces`
>   matches its preconditions exactly and deployment recall measured **18/27 = 67%**.
>
> Do not cite either as evidence.

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

## 5a. RFA is the wrong shape for most of this — the channel is a conversation

§5 above framed the human channel as RFA. **That is too narrow, and narrow in a way that matters.**

RFA is one-directional, ticket-shaped and asynchronous: the system asks, the human answers later,
one question at a time. That is the right shape for *findings* — "this component has bus factor
1, someone should look". It is the wrong shape for **triage and refinement**, which is what
selecting among approaches actually requires.

RE already has the better channel and it is not being used for this: the chat panel, the agent
layer, and one or more LLMs.

### What a conversation gives that a ticket cannot

- **Bidirectionality.** The human wants to ask *why* before deciding whether a boundary is right.
  §5.4's evidence model — file, line, detector, excerpt, per claim — was built for exactly that
  question and **has no interactive consumer today**. A form field cannot answer "what made you
  think this?"; an agent over the evidence table can.
- **Iteration inside one context.** Architecture recovery is propose → correct → re-derive →
  propose again. A ticket queue serialises that into round-trips measured in days.
- **Correcting premises, not just outputs.** This is the difference that matters. A queue surfaces
  *findings*; a conversation surfaces *wrong assumptions*, and those are worth more.

### The worked example is this project

Phase 0 produced eighteen corrections to a design that had been reviewed twice. The ones that
changed the model all came from conversational turns in which the maintainer questioned a premise:

| What was said | What it changed |
|---|---|
| *"the container is not really there — just the description of it"* | §4.1a: deployment became a **specification** perspective; Area 0 infrastructure types ruled out of scope |
| *"two components that share 90% of their code"* | §8.2: identity precedence reordered, deployment unit ahead of package name |
| *"I was looking a bit coarser"* | §4.3's how-far-down question, and §2's sufficiency-per-stage reframe |

**No ticket would have carried any of them.** None is a finding about a result; each is a
correction to what the system believed it was doing.

### The architectural caution

**The session is the interface. It is not the system of record.**

A conversation is ephemeral; the curation overlay (§7.2) is durable and is what makes
re-derivation safe. Every decision taken in chat must land in the overlay keyed by stable
qualified name — otherwise the next run discards it, which is precisely the failure §7.2 exists to
prevent. Get this wrong and the result is a pleasant interface that forgets everything, which is
worse than a ticket queue that remembers.

The same applies to the *reasons*. "These are two components because they are separate
deployments" is more durable than the decision alone: it is the rule that answers the next twenty
cases, and it belongs in the record.

### Two consequences worth naming

**An LLM is an approach in the portfolio, not a separate category.** If it proposes boundaries, it
is evaluated by §3's outcome record and retired by §6's rule exactly like coupling or code
markers. "Maybe multiple" is genuinely useful here: a second model as an independent **second
opinion** on a low-confidence boundary is a portfolio member whose entire value is disagreeing
with the first, and disagreement is a signal the current design has no other way to generate.

**Agents that ask are a different shape from agents that answer.** §6.5 designed `AnnotationAgent`
and `ArchitectureAgent` to answer questions about results. Asking requires an agent to know its
own uncertainty and to present competing readings with the evidence for each. That is available —
confidence and evidence are first-class (§5.4, §3.3b) — but it is a different prompt, a different
surface, and it should be designed rather than assumed to fall out.

### Scale — this is a tier, not a replacement

An interactive session does not survive 200 repos, so this is not conversation *instead of* RFA.
It is the funnel again, applied to human attention:

| Channel | Cost | Use for |
|---|---|---|
| **Fully automatic** | none | everything, always; record confidence and move on |
| **RFA / batch** | low, async | findings; disambiguations that can wait; breadth |
| **Interactive session** | high, synchronous | depth on repos that earn it; premise correction; portfolio triage |

Reserve the session for what earns it — a flagship repo, a recurring disagreement across many
repos, or a result the funnel says is not yet good enough for its stage (§2). Everything else
stays automatic or async, with confidence shown.

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
| ask a human, async | `rfa_actions` + the RFA drawer (§7.3) |
| ask a human, interactive | the chat panel + `agents/` — exists, unused for this (§5a) |
| interrogate a proposal's reasoning | `project_analysis_findings` evidence rows (§5.4) — exists, **no consumer** |
| record the answer durably | the curation overlay (§7.2) |
| repo characteristics for selection | Scouting-tier analyses, already collected |
| evaluate a partition | `score.py` / `coupling.py` from Phase 0 |
| stage semantics for sufficiency | the eight intents, already canonical |

**Genuinely new:** an approach *identity* and its outcome vocabulary; the sufficiency-per-stage
thresholds; the selection lookup; the retirement rule; and an agent that **asks** rather than
answers (§5a).

---

## 8. Suggested first step

Do not build the portfolio manager. **Backfill Phase 0's own results into the outcome table** —
four approaches (manifest, deployment, code markers, coupling) across three targets, with the
failures included — and see whether the selection rules in §4 fall out of that data or not.

If they do, the model is worth building. If four approaches over three repos produce nothing a
person could not have said unaided, that is a real answer too, and it costs an afternoon to find
out rather than a phase.

### Result (2026-08-20): the rules do not fall out. Do not build the manager yet.

Run as specified. 21 `approach_run` rows across four approaches and three targets, failures and
regressions included, plus 15 `repo_characteristics` rows — all into
`project_analysis_findings`, no new table. Spike README findings 48–51 carry the detail.

**The grid is qualitatively full but half `unverified`** — the whole `egeria` row (two of four
approaches structurally cannot run on a repo with zero tracked `.py` files) and half of
`egeria-workspaces`'s. §3's `unverified`-vs-`no_signal` distinction earned its keep immediately:
coupling on `egeria` is *unverified* because it cannot run at all, while coupling on
`PyegeriaWebHandler` is a genuine *no_signal* because a known-positive sits right beside the zero
(Q = 0.427, four communities — finding 38). Without that distinction both would have been recorded
as zeros and the grid would have looked twice as informative as it is.

**Neither worked example survived** (see the note in §4). One is circular, one is disconfirmed by
the single repo positioned to test it.

**What this does and does not mean.** It does *not* mean the portfolio model is wrong. It means
three repos, with half the grid unverified, is not a sample a lookup table can be built from — and
that more analysis of *these* three will not help, since 47 findings have already characterised
them about as thoroughly as they can be. What is needed is more repos, ideally covering the
profile combinations §4's examples name.

**Decision: do not build the portfolio manager, the selection lookup, or the retirement rule.**
Revisit at the 8–10 repos `Backlog.md` already schedules for the measurement re-check — the same
sample serves both, so this costs nothing extra to wait for.

The afternoon was well spent. It cost one session to establish that the selection layer is
premature, versus discovering it after a selection engine existed and had to be unwound.
