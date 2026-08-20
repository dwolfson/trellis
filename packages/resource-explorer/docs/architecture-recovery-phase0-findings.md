# Architecture Recovery — Phase 0 Findings

**Verdict: QUALIFIED PASS.** Proceed to Phase 1, with a changed plan.
**Date:** 2026-08-20
**Plan:** `architecture-recovery-phase0-plan.md` · **Design:** `architecture-recovery-design.md`
**Spike:** `scripts/arch-spike/` (32 numbered findings) · **Ground truth:**
`tests/fixtures/architecture-ground-truth/`

---

## 1. The verdict, and what it rests on

Phase 0 asked one question: **can deterministic detectors find real component boundaries?**

The answer is the middle outcome the plan pre-defined in §6, and pre-defining it mattered — the
result is genuinely ambiguous and would have been easy to read as either success or failure
depending on which number was quoted.

**Where the detectors fire, they get the boundary right. They fire on 4 of 11 components.**

| T2 `trellis` (logical perspective) | value |
|---|---|
| file-partition **ARI** | **0.56** |
| file-partition **NMI** | **0.77** |
| components proposed | **4** of 11 |
| files scored | 38 of 182 ground-truth-assigned |

The four are exactly the subtrees using a *framework* — FastAPI, Typer, Textual, Prefect. The
other seven have no marker, and **no rule that could be written would find them**: `Agents`,
`Core`, `RAG ingestion`, `Observability`, `Surveyors`, `Utility scripts` are conventional
boundaries, not declared ones. There is nothing distinctive to match.

Refining §6's wording by measurement: boundaries are recovered where a manifest declares them
**or a framework marker fires**, and the union still leaves most of a code-first repo invisible.
That matters because most of the estate looks like trellis, not like egeria-workspaces.

**The deployment perspective is a different story and a much better one.** T1
`egeria-workspaces` scored **16/16** on the maintainer's named runtime components once the
detector read `container_name` rather than the compose service key. Deployment architecture is
*declared*, so it is recoverable; logical architecture is largely *conventional*, so it is not —
at least not by detectors alone.

---

## 2. The result that changes the plan

Import and co-change coupling — specified in §5.5 as **validation** signals, for scoring a
partition someone else proposed — turn out to be **proposal** signals, and they cover precisely
the gap above.

With no knowledge of the ground truth, coupling proposed five boundaries the detectors missed.
All five are real components:

| candidate subtree | ground truth | detector |
|---|---|---|
| `resource_explorer/surveyors` | Surveyors | none |
| `resource_explorer/agents` | Agents | none |
| `resource_explorer/ingestion` | RAG ingestion | none |
| `scripts/arch-spike` | Utility scripts | none |
| `trellis-microflow/trellis_microflow` | trellis-microflow | none |

**Five of the six components code markers structurally could not see. Precision 5/5, zero false
positives.** Only `Core` and `Observability` remain missed, and `Core` for a structural reason
worth carrying forward: it is a shared import **hub**, and hubs suppress their own internal
cohesion by construction. A cohesion-based signal cannot see a hub; that is a property of the
metric, not a tuning failure.

**Caveat, stated rather than buried.** At the default `min_cohesion=0.5` the result is zero;
`0.3` was chosen after seeing the data. Threshold calibration is an open Phase 1 question and
this must not be read as a tuned-in success. What was *not* fitted is the identity of the
recoveries — ground-truth names were matched blind, and 5/5 precision with zero false positives
is not the shape threshold-fishing noise takes.

---

## 3. Cost — the Discovery-tier claim holds, with room to spare

§5.6 estimated the detector layer at "about a minute on a large repo". Measured, on this
machine:

| target | first-party files | full detect (incl. 8 ast-grep rules) | imports | co-change |
|---|---|---|---|---|
| `trellis` | 1,305 | **1.00s** | 0.25s | 0.18s |
| `egeria-workspaces` | 1,763 | **0.70s** | 0.18s | 2.77s |
| `egeria` | 6,245 | **0.60s** | — | — |

**Everything, on every target, in under 3 seconds.** The estimate was too pessimistic by more
than an order of magnitude. The Discovery-tier placement in §5.6 is not just defensible, it is
conservative — this can run on every repo that clears Scouting without anyone noticing the cost.

Note the §6 measurement as originally specified (`scc` and `lizard`) was **not** run: neither is
in the toolchain any more, following the dependency decision in §5. What is measured above is
the toolchain that actually exists.

---

## 4. What pre-registration caught

The plan's §4 required the expected partition to be written down and committed **before** any
detector ran, and forbade editing it afterwards. It earned its place three times:

1. **It caught a detector bug immediately.** Both `PyegeriaWebHandler` copies collapsed into one
   component under an unqualified slug. The pre-registered answer — two components, split by
   deployment unit — is what identified it as a bug rather than a judgement call.
2. **It stopped a score being rescued.** When perspective filtering dropped T1 recall from 21/27
   to 18/27, dual-tagging would have restored 21. It was rejected *because* it would: the real
   cause is a granularity inconsistency in the fixture itself, which names one 9-container
   bundle as a single component alongside single containers as single components. **18/27 is the
   honest number**, and the fixture issue is recorded for a `-revised.md` rather than edited away.
3. **It made the coupling result meaningful.** The five recovered boundaries were matched against
   names written down before the signal existed. Without that, "cohesion found Surveyors" would
   be unfalsifiable.

**Contamination is recorded, not denied.** Some ground-truth components were filled in with
assistant help, marked per component with a `Provenance:` line, and every score is reported twice
— maintainer-authored only, and maintainer-plus-assisted. One further honesty note: the trellis
component count was reported to the maintainer before T2's ground truth was written, so T2 is not
a clean pre-registration. The contamination runs the safe way — the draft *contradicts* the
detector output rather than echoing it — but it is a caveat on T2's numbers.

---

## 5. Corrections to the parent design

Phase 0's main output is not the score. It is **eighteen** corrections to a design that had been
reviewed twice before any code ran. Grouped by how much they changed.

### Changed the model

- **§4 — one architecture became four perspectives.** The spike scored 16/16 on one repo and
  1-of-10 on another, which reads as "works here, fails there". It is neither: one ground truth
  is a deployment architecture, the other logical, and the detectors read deployment and
  physical. A perspective mismatch that the original exit criteria would have recorded as a
  premise failure.
- **§4.1a — "deployment" is a *specification* perspective.** A repo contains no running
  container, only a description of one. Mapping it to Area 0 `SoftwareServer` /
  `DeployedSoftwareComponent` would assert infrastructure that was never observed, and
  `ContentStatus = Draft` does not repair that — Draft means *incomplete*, not *may not
  correspond to anything real*. Egeria already provides
  `plannedDeployedImplementationType` for naming a likely implementation without claiming one
  exists. **Raised by the maintainer, not found by the tooling.**
- **§8.2 — identity precedence reordered**, deployment unit ahead of declared package name.
  `egeria-workspaces` ships `PyegeriaWebHandler` twice under one package name for two
  deployments; package-name-first merged two deliberately distinct components. §8.2b then added
  the floor that stops the rule over-splitting: a separate deployed *artifact*, not a runtime
  configuration flag.
- **§5.5 — coupling signals are proposal, not validation** (§2 above).

### Corrected a fact

- **Blueprints do not nest.** `SolutionBlueprint` is a Collection; nesting is
  `SolutionComposition` between *components*. Q8's answer became "one blueprint per deployable
  solution", and `egeria-workspaces` ships two.
- **`SolutionLinkingWire` is a relationship**, so the `Confidence` classification cannot attach
  to it. Wire confidence rides on the connected ports.
- **`ConfidenceLevel` needs no extension.** Its values are a *provenance* scale, not a degree
  scale — `Derived`, `Authoritative`, `Ad Hoc`, `Obsolete` map onto this feature almost verbatim,
  and `Obsolete` gives stale overlay entries a typed home. Q12 dissolved; Phase 2 lost a
  prerequisite.
- **`KnownDuplicate` / `PeerDuplicateLink` are the wrong types** for deployment variants — their
  semantics are *deduplication*, which would instruct the catalog to merge two deliberately
  separate components.
- **`project_code_relationships` cannot supply an import graph** (name-to-name, no `file_path`,
  inheritance only) and **`project_commits` cannot supply co-change** (no per-file data). §5.5
  named both as sources; neither works.

### Corrected the method

- **Exclusion must run before detection, and is not tidiness.** `node_modules` is *tracked* in
  `egeria-workspaces` — 1,697 of 1,703 tracked `.js` files, making the repo 29% first-party.
  Every vendored `package.json` declares a package name, which is identity precedence 1. An
  unfiltered tree would emit hundreds of spurious components, each with a real name and real
  evidence. Added as §5.2 step 0.
- **`git ls-files` beats reimplementing `.gitignore`.** Tracked-only removes `.venv` and
  `site-packages` without parsing a single ignore rule.
- **Compose files cannot be identified by filename**; detection must be by content. The
  filename rule missed *every solution deployment* in `egeria-workspaces`, whose compose files
  are named after the solution, while happily finding the optional add-ons — reporting the least
  important tier and missing the most important.
- **`container_name` is the component's name, and it is declared.** Reading the service key
  matched 2 of 16 maintainer-named components; `container_name` matched 16 of 16.
- **Compose is layered**, so services must be merged across every file in a deployment unit; a
  per-file pass loses the override that carries the human-facing name.
- **A Dockerfile without a manifest is still a component** — that is identity precedence rung 1,
  and it was not firing at all, which is why the most substantial component in
  `egeria-workspaces` went entirely unreported.
- **Measure containment, not similarity** — twice. First for deployment variants (§8.2a), then
  again in the coupling scorer, where Jaccard silently mislabelled a correct partial match as a
  novel boundary. The design doc already contained the rule and the code did not follow it; the
  same error in two places is a reason to look for a third.
- **The cross-boundary ratio is degenerate as a ranking metric** — minimised by having no
  boundaries, so a one-component partition scores zero and coarseness wins. Meaningful within a
  granularity, meaningless across one. Phase 1 should use Newman modularity or quote the
  constraint.
- **A zero from a code marker is a finding, not a pass.** It means either the technology is
  absent or the pattern is broken, and the two are indistinguishable without a known-positive
  file. Two of eight drafted rules were wrong in opposite directions — one matched 620 times
  (every two-argument `.get()` call in Python), one matched zero (missed Prefect entirely).
- **Prefer wheel-distributed tools to system binaries.** `ast-grep-cli` on PyPI removed the only
  hard prerequisite; the binary resolved from `.venv/bin` and *not* from PATH despite a Homebrew
  install, which is the argument landing in practice.

---

## 6. What changes for Phase 1

1. **Promote coupling from validation to proposal.** It is cheaper than distillation and it
   recovered 5 of 6 marker-less components. It should run alongside the detectors, not after
   them as a scoring step.
2. **Move LLM distillation earlier** than Phase 5, but scope it to what coupling *cannot* do:
   hub-shaped components like `Core`, and naming. Component-set F1 of 0.00 on T2 is not a
   detection failure — the boundaries agreed, only the names differed, and §5.2 assigns naming
   to the LLM precisely because detectors cannot produce human names.
3. **Do not increase the rule-writing estimate.** More markers would not have helped; the missing
   components have nothing to match on. Effort belongs in coupling and distillation.
4. **Calibrate the cohesion threshold properly**, with a null model rather than a fixed bar.
5. **Different perspectives need different measures.** Component-set agreement is right for
   deployment, where names are declared; file-partition ARI/NMI is right for logical, where they
   are not. Plan §5a's rule, one level deeper than it was written.
6. **`git_clone_root` remains a real prerequisite** for anything beyond the spike — Phase 0 read
   local checkouts, and co-change needs history a zipball does not carry.

---

## 7. What Phase 0 did not answer

- **The two validation signals were never tested against a *wrong* partition.** They agreed with
  ground truth; whether they would reject a bad partition is untested, and that is the other half
  of what §5.5 claimed.
- **`Core` and `Observability` remain unrecovered** by any mechanism tried.
- **Threshold calibration** (§2's caveat).
- **T3 `egeria` was not scored** — its ground truth stayed at shape level by design, and the
  231-module Gradle partition was never expanded.
- **Nothing was written to Egeria.** Phase 0 was deliberately standalone: no registry, no
  publisher, no network. Every claim here is about extraction, none about projection.
- **The dev/devops perspective (§4.4) has no detector at all.** It was defined during Phase 0 and
  never exercised.

---

## 8. Assessment

The premise — that boundaries are declared in deployment and configuration artifacts — is **true
for deployment architecture and false for logical architecture**. That is a narrower claim than
§5.1 made, and it is the single most useful thing Phase 0 established.

The feature survives because the gap has a cheap answer that was already half-specified in the
design: coupling signals, promoted from the validation role §5.5 gave them. Phase 0 cost a few
days and changed the plan in four material ways; the alternative was discovering the same things
in Phase 2, with Egeria writes and a curation UI already built on top of them.

**Proceed to Phase 1**, with §6's changes applied.
