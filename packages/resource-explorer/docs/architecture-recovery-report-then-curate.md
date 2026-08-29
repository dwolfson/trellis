# Architecture recovery — report, then curate

**Status:** design note, amending `architecture-recovery-design.md`. Written 2026-08-29 from Dan's
direction. Nothing here is built.

This changes what Phase 2 *is*. The existing design has RE derive an architecture and **write it into
Egeria** as a blueprint with components at `ContentStatus = Draft`, with §7.2's curation overlay
protecting human edits from the next re-derivation. This note replaces that with:

> **RE reports what the analysis believes. A curator decides whether it becomes real.**

Derivation writes observations. Nothing structural is created in Egeria until a human (later,
possibly an agent) chooses to materialise it.

---

## 1. Why this is the right default

**It is conservative and defensible.** RE asserting a blueprint claims a confidence the analysis
does not have. An annotation saying *"this analysis proposes these components, at this confidence,
from this evidence"* claims exactly what is true. Egeria's own vocabulary already separates these:
an Annotation is an observation from a dated act of analysis; a `SolutionComponent` is an assertion
about the world.

**The design never actually argued the other way.** `SurveyReport` appears twice in 2,100 lines of
`architecture-recovery-design.md`, both incidental — once deciding where `analyzerVersion` belongs
(§6.2), once noting a blueprint writes more elements than a report (§8.4). There is no section
weighing report-as-carrier against structural projection. Architecture recovery went straight to
structural elements while **every other analysis in RE reports through `SurveyReport` +
Annotations** (`EgeriaPublisher.publish()` → `DataDiscovery.create_annotation`, mirrored in the
database and filesystem publishers). Recovery was the odd one out, and the design did not say why
it earned that.

**The decisive reason, and it drives the tooling.** A curator may decline to materialise precisely
*because the fit is not good enough to use* — but **they cannot see that without looking at the
blueprint.** The proposal is a decision aid, and it has to be legible before it exists. That single
requirement is what §3 below is for, and it is why "just show the annotation JSON" is not an
answer.

**It also dissolves the design's own biggest stated risk.** §7.2 calls the curation overlay *"the
single biggest design risk in the whole feature"* — re-running a survey must not clobber human
curation, so human decisions accumulate in a durable overlay, keyed by qualified name, replayed
over freshly-derived IR before projection, with staleness, conflict surfacing and its own
reconciliation problem. **Under report-then-curate, re-derivation cannot clobber curation, because
the curated elements are ones RE never writes.** The overlay does not need solving; it needs
deleting. What remains is much smaller: a proposal that has already been materialised should be
able to say *"the analysis has changed since you accepted this"* — a diff to show, not an overlay
to replay.

## 2. Two corrections to §3.3a — both now applied to the design doc

### 2a. Blueprints **do** nest — §3.3a was wrong as written (now fixed)

§3.3a states as verified fact: *"There is **no blueprint-to-blueprint relationship**… blueprints do
not nest."* The first half is true; the conclusion does not follow. Traced through the type archive:

```
SolutionBlueprint  --extends-->  DesignModel  --extends-->  Collection
   OpenMetadataTypesArchive1_7.java:1109      OpenMetadataTypesArchive1_2.java:9647
   (SolutionBlueprintProperties extends DesignModelProperties extends CollectionProperties)

CollectionMembership   end1 = Collection      OpenMetadataTypesArchive1_2.java:3170
                       end2 = Referenceable   OpenMetadataTypesArchive1_2.java:3185
```

A `SolutionBlueprint` is a `Collection`, and a `Collection` may hold any `Referenceable` — which a
blueprint is. **So a blueprint can be a member of another blueprint, through the ordinary
Collection mechanism.** What is absent is a *dedicated* blueprint-to-blueprint relationship, which
is not the same claim.

§3.3a half-saw this already: it leans on the Collection nature to argue a component can belong to
several blueprints. The same property gives nesting.

This matters most for monorepos, where the natural shape is a repo-level blueprint whose members
are sub-blueprints, each a coherent solution in its own right.

### 2b. One blueprint per repo is wrong

§3.3a concludes: *"For a monorepo this means: one blueprint per repo, each package a top-level
`SolutionComponent`."* A monorepo can legitimately hold **several blueprints over different
clusters of components** — a repo is a storage boundary, not a solution boundary. The blueprint is
the unit of *solution*, and one repo may contain several, or contribute components to one that
spans repos (which §9's estate-level ISC candidates already assume).

**This is new work, and it should be named rather than assumed:** *what proposes the clusters?*
Today the IR has coupling and cohesion signals per component and no notion of a blueprint at all.
Cluster proposal is a distinct step — and under report-then-curate it is a *proposal*, so it is
allowed to offer more than one candidate clustering and let the curator choose. That is a far
easier problem than getting it right unattended, and it is only available because we stopped
writing the answer directly into Egeria.

## 3. The curator's review surface

The requirement from §1: the curator must see the proposed architecture **as it would look
materialised**, because that view is what tells them whether the fit is good enough to use.

**Render the proposal as a Mermaid diagram, in the shape Egeria would show once materialised.**
Same components, same nesting, same wires and port directions, same grouping into blueprints — so
that judging the picture is judging the thing. If the rendered proposal and the materialised
element graph would differ, the review is being conducted against something other than the
decision.

The renderer is **first-cut work, not refined tooling** — see §8 for why the tier boundary falls between visualisation and interaction rather than between diagram and list.

Notes on making that true rather than approximately true:

- **One renderer, two inputs.** The same rendering code should accept either the proposal (RE's IR)
  or the materialised element graph (read back from Egeria), so "what you approved" and "what
  exists" are comparable by construction, and post-materialisation drift is a diff of two diagrams.
- Mermaid is already the house format for this — Egeria renders Mermaid, Dr.Egeria emits it, and
  `egeria-shared-kroki` is running in the stack. Nothing new is required to display it.
- **Show the evidence with the picture.** Every proposed component carries `confidence`, its
  proposer, and `sampleSize`/`samplePercent`/`samplingMethod` (§6.1). A curator declining a
  blueprint for poor fit needs to see *which parts* are weak, so confidence belongs in the visual —
  not in a table beside it.
- **Derived structural nodes must be visibly distinct.** `scope_hierarchy.py` deliberately refuses
  to emit derived ancestors as components — *"a derived parent is a structural node, never a
  component… emitting them as ordinary components would invent evidence."* That restraint is right
  and it is exactly the kind of judgement a curator should make with evidence in front of them, so
  a grouping node must render as a grouping node, not as a component that happens to have children.

## 4. Curation generalises — do not build it repo-shaped

Two directions, both of which argue for the same thing:

1. **Curation will become AI-assisted, and eventually partly automated.** The act being automated
   is *deciding whether a proposal is good enough to materialise* — so a proposal needs to be a
   first-class, inspectable, machine-readable object with its evidence attached, not a rendering
   artefact. An agent that recommends acceptance and a human who accepts should be acting on the
   same record. §6.5's `AnnotationAgent` is the natural reader.
2. **Other resource kinds need the same act.** Databases and filesystems already produce analyses
   through the same publishers, and they will have their own proposals to accept or decline.

So the review surface should be built as **"review a proposal and decide whether to materialise
it"**, with architecture recovery as the first *kind* of proposal, not as an
architecture-recovery-specific screen. The lifecycle (§7.1: derived → proposed → accepted/rejected,
rejections retained so the next derivation does not cheerfully re-propose them) is generic; only
the renderer and the materialiser are kind-specific.

## 5. What this changes in `architecture-recovery-design.md`

| Section | Change |
|---|---|
| §3.3a | **Correct two errors.** Blueprints *do* nest via `CollectionMembership` (evidence in §2a above); and one-blueprint-per-repo is wrong — a monorepo may hold several |
| §7.1 Lifecycle | Now governs a **proposal**, not a Draft element already in Egeria; `ContentStatus` promotion applies from materialisation onward. **Its `Rejected`-state machinery is no longer needed in that form** — see §9 |
| §7.2 Overlay | **Largely deleted.** Re-derivation cannot clobber curation when RE writes no curated elements. What survives is a much smaller need: tell a curator when the analysis behind an already-materialised blueprint has changed |
| §8.3 Drift | Was a set diff between two blueprint versions. Becomes a diff between two **proposals** (and, separately, proposal vs materialised graph). `analyzerVersion` stays load-bearing for exactly the reason §6.2 gives |
| §10 Phase 2 | Was "Egeria projection at Draft". Becomes **"publish the proposal"** — recovery annotations against the repo asset, carrying the proposed components, hierarchy, wires, ports and candidate blueprint clusters. Whether a curator is *asked* to act is a separate survey-definition step (§7) |
| §10 Phase 3 | Was "curate the blueprint RE wrote". Becomes **"review a proposal and materialise it"** — the renderer, the decision surface, and the materialiser that creates real blueprints and components on acceptance |
| §9 ISCs | Unchanged in intent, but now explicitly downstream of materialisation: estate-level candidates need components that exist |

## 6. What this does *not* change — and one thing it makes harder

**Outbox/retry (§8.4) is still required, and still first.** Annotations are Egeria writes too. A
proposal that publishes half its annotations is a proposal that misrepresents the analysis, which
is the same failure as a half-published blueprint with a smaller blast radius.

**Annotations become the only carrier, so atomicity matters more** — a proposal that publishes half
its annotations misrepresents the analysis.

**But not identity, and I had that wrong** (corrected 2026-08-29 in
`docs/outbox-publishing-design.md` D2). Republishing a proposal on every re-derivation is *not* an
identity problem: each re-derivation is a new survey run, which legitimately mints its own
`SurveyReport` with its own annotations — that is what a survey report is, and RE's own bookkeeping
already shows 10 distinct report GUIDs for `deep_causality` over three days. Only a *retry of one
publish* has to converge, and there the identity is already stable, because `surveyed_at` is stamped
when the `SurveyResult` is constructed and an outbox replays a stored payload. What is missing is
narrower: `_create_annotations` creates blind, where `_find_or_create_asset` searches first.

**Sequencing, unchanged from the outbox note's §6, with proposals slotted in:**

1. Annotation identity (outbox design D2) — blocks everything.
2. Outbox/retry, so a proposal publishes wholly or not at all.
3. Proposal publication (revised Phase 2).
4. Renderer + review surface + materialiser (revised Phase 3).
5. Cluster proposal — candidate blueprints within a repo (§2b). Can run in parallel with 4; it
   changes what a proposal contains, not how it is reviewed.

## 7. Resolved — the survey is the unit of intent (was Q-A)

**A survey is chosen to achieve a goal, and the analysis is part of it.** So whether anyone is asked
to curate is a property of *which survey you ran*, not a mode on the analysis:

| Survey definition | What it does |
|---|---|
| analysis only | derives the architecture and publishes the proposal as annotations. Nobody is asked for anything |
| analysis + curation request | the same analysis, plus a step that raises an **RFA** asking a curator to review the proposal and decide whether to create Egeria artifacts |

This resolves Q-A without needing a separate answer about where proposals live: **the proposal is
always published as annotations**, exactly like every other analysis in RE, and its non-authoritative
status comes from what it *is* — an observation from a dated act of analysis — not from a status flag
holding it back. Authority arrives only when a curator materialises components and blueprints. The
earlier worry about "unaccepted proposals visible in the catalog" dissolves: they are analysis
output, and the catalog is already full of analysis output.

**The curation request should be a step, not a flag.** Survey Definitions are composed of steps, so
"ask a curator" is one more step in a definition rather than a new mode on the analysis step. Two
consequences: no new survey machinery is required, and the choice gets expressed where every other
survey choice already is. It also means the RFA step is independently schedulable, reusable across
resource kinds (§4), and visible in the same place as the rest of the definition.

The machinery this leans on largely exists: `log_rfa()` writes RFAs, the RFA drawer surfaces them,
and `rfa_egeria_sync.py` already syncs an RFA to a real Egeria ToDo via `MyProfile.create_my_todo`.
§7.3 of the main design anticipated exactly this (*"curation as RFA"*), and the open backlog item on
making RFAs real assignable Egeria actions is the same work, now with a second concrete driver.

### 7a. A rule that falls out of combining this with rejection-is-final (§9)

If an RFA-raising survey is **scheduled**, then rejecting a proposal and letting the schedule run
again re-raises the same proposal automatically — which is precisely the *"next derivation
cheerfully re-proposes them"* failure §7.1 of the main design was written to avoid.

**So: the analysis-only definition is the one that gets scheduled; the curation-requesting definition
is user-initiated.** Periodic surveys keep the analysis fresh without generating unrequested work for
a curator, and asking for a decision stays a deliberate act. This is not a constraint imposed on the
model — it is what the model already implies, but it is the kind of thing that only shows up when
someone schedules the wrong definition, so it is written down here.

## 8. Resolved — tooling in two tiers (was Q-B)

Full curation tooling is a significant effort and should not gate the first useful version.

**First cut, deliberately crude:** list the proposed components (clustered, and showing nesting where
it exists), the proposed wiring and ports, and the candidate blueprints — and let the curator create
the particular objects they want. Selection and creation, nothing clever.

**And the first cut may not need new RE tooling at all.** A curator's review surface is a report over
one SurveyReport's annotations, which is exactly what Egeria Advisor's Report Spec Builder builds.
`DataDiscovery.get_annotations_for_element` already defaults `report_spec="Annotations"`, and its
parameters map one-to-one onto the builder's three categories. What is missing is target-type
coverage for Survey Report / Annotation (absent from all 150 catalog specs, same root cause as
IB-9), a pass-through column format for embedded Mermaid, and the `MERMAID`/`REPORT-GRAPH` output
formats exposed in the UI — filed as **RS-8..RS-11** in `egeria-advisor/BACKLOG.md`, with the
reasoning in that repo's `docs/design/REPORT_SPEC_BUILDER_DESIGN.md`.

**One finding from working that through, and it confirms §11's placement.** pyegeria's own `MERMAID`
output **cannot draw a proposal** — it graphs Egeria elements, and a proposal's components do not
exist as elements yet. So the diagram must be generated by RE at publish time and carried in the
annotation, exactly as §11 concludes; the report spec's job is to *surface* it, not derive it. After
materialisation pyegeria's renderer becomes usable, which is what makes approved-versus-existing a
diff of two diagrams.

**Later, and conceivable rather than scoped:** merge/split, re-clustering, editing a proposal before
accepting it, bulk operations, agent-recommended acceptance (§4).

**One adjustment to where the tier boundary falls.** The Mermaid view belongs in the *first* cut, not
the refined one. Generating Mermaid from the IR is string generation over a graph we already hold —
it is one of the cheapest things in this whole feature. What is genuinely expensive is
**interaction**: click-to-select, merge, split, re-cluster, edit-then-accept. So the boundary is
*visualisation vs interaction*, not *diagram vs list*.

That distinction matters because of the requirement in §1: a curator may decline **because the fit is
not good enough to use**, and a list of component names does not support that judgement — the shape
does. A cheap picture plus crude create-buttons is a genuinely usable first tier; a list plus
create-buttons is not, for the decision we most care about.

## 9. Resolved — re-derivation and rejection (was Q-C, Q-D)

**Q-C — what happens on re-derivation after acceptance.** Nothing automatic. This is exactly why the
human is in the loop: presented with a changed proposal against an existing blueprint, they may
choose to update that blueprint or to create a new distinct one. Neither is a reconciliation rule RE
gets to apply. So the diff is *informational input to a human choice*, and no
"accepted-then-diverged" element state is needed — the earlier §7.2-shaped instinct to model this
was a residue of RE owning the elements.

**Q-D — rejection is final for that proposal.** A rejected proposal is not reconsidered and does not
get re-raised. Changing your mind is not a state transition on the old proposal — it is **re-issuing
the survey**, which produces a fresh analysis and a new RFA. The re-survey is the mechanism, and it
is a deliberate act by definition.

This is a simplification of the main design's §7.1, which retained rejected components in a
`Rejected` state specifically so the next derivation would not re-propose them. That machinery is no
longer needed in that form: rejection closes an RFA, and re-proposal requires someone to run the
curation-requesting survey again. **`analyzerVersion` is not the discriminator** — the human's
decision to re-survey is.

## 10. Candidate clusters — the first-pass signals

**Designed 2026-08-29 in `architecture-recovery-clustering.md`**, which supersedes this section's
"undesigned work" framing. The headline: clustering must key on the **§4.1 architectural
perspective** (physical/deployment/logical/dev — a property each component already carries, measured
as populated: logical 1747, deployment 1300, physical 168), *not* on the question-catalog Perspective
that was measured non-discriminating for dispatch. And splitting by perspective before grouping
already reaches the ~10-component goal for the **deployment** perspective on most repos using
machinery that exists (genaiexamples 546 components → 8 groups; genaicomps 289 → 4). The logical
perspective does not (egeria_git 924 → 279) — which is exactly where §4.1 says a human is needed.

What proposes a candidate blueprint. Three signals, all reading evidence RE already collects, and
deliberately not a clustering algorithm looking for structure in the abstract:

**1. What is deployed together.** Components that ship as one unit are a solution in the sense a
person means it. RE already records this in the scope locator itself — `compose::agent` means "the
`agent` service declared in that compose file", and the compose file is a real deployment unit
someone named. `scope_hierarchy.py` already groups on exactly this, and §8.2b's three tiers of
"deployment" already say which of them mint components, so the discrimination this needs exists.

**2. Which components interact with each other**, and more sharply than "they import each other" —
**if ports and wires can be distinguished, the wire graph is the signal.** `interfaces.propose()`
already emits ports and wires, and a wire carries direction. A cluster is then a densely-wired
subgraph with sparse crossing, which is a real graph question over a graph we already build rather
than a heuristic over file paths.

**3. Do components contribute the same external interfaces.** Components that jointly present one
API surface are one solution to whoever consumes it, however they are laid out in the repo. This is
the signal most aligned with what a blueprint is *for*, and it is the one whose input is weakest
today: `Backlog.md`'s standing HIGH item is precisely that interface extraction answers *"does it
expose something"* rather than *"can I use it"*, and §5.5f already calls the external interface the
biggest gap and a cheap one. **This signal should be specified now and built after that item lands**
— not dropped, and not faked from what extraction returns today.

Two notes on using them:

- **They will disagree, and that is information.** Deployed-together and interface-sharing pulling
  apart is a fact about the repo worth showing a curator, not a conflict to resolve silently by
  weighting. Under report-then-curate a proposal may carry more than one candidate clustering, so
  disagreement can be *presented* rather than arbitrated.
- **No signal, no cluster.** Consistent with §5's "no metric, no number" rule: a component no signal
  groups stays ungrouped rather than being swept into a nearest cluster.

## 11. What the RFA carries

**The RFA is per SurveyReport, and it is thin.** The details live in the report; the RFA is the ask.

It carries:

- **Provenance** — which survey, run at what time, over which resource. A curator needs to know what
  produced this before deciding anything about it.
- **The goal** — *"identify artifacts to publish to Egeria."* Stated, because the survey was chosen
  to achieve a goal (§7) and the RFA is where that goal reaches a person.
- **A link to the SurveyReport**, which carries the annotations holding everything the curator needs
  to decide.

**This resolves the earlier open question about payload** — there is no tension between "enough to
open the review surface" and "enough to stand alone as an Egeria ToDo", because both are satisfied by
provenance + goal + a link. Nothing about components, ports or clusters belongs on the RFA itself.

**One consequence, and it changes §3.** If the SurveyReport is what the curator reads, then the
**Mermaid graphs belong in the annotations**, generated at publish time — not rendered only inside
RE's own UI. That is a better placement than §3 originally assumed:

- any consumer can show the proposal — Egeria's own UI, a report over the annotations, or RE —
  without each reimplementing a renderer;
- the diagram is captured *as of that run*, alongside the evidence it was drawn from, rather than
  being re-derived later from an IR that has since moved;
- it is consistent with the survey provenance model: the report is the record of what the analysis
  said, and the picture is part of what it said.

The "one renderer, two inputs" rule in §3 still holds, and gets easier: the publish-time renderer
emits the proposal diagram into the annotation, and the same code renders a materialised element
graph read back from Egeria, so approved-versus-existing stays a diff of two diagrams.

## 12. Built 2026-08-29 — the publish-time renderer

`resource_explorer/surveyors/arch_recovery/mermaid.py`, emitted by `persist.py` as an
`architecture_diagram` finding at whole-resource scope, once per run. When Phase 2 publishes
proposals, that value is what goes into the annotation.

Decisions worth keeping:

- **Determinism is a requirement, not a nicety.** The text is republished on every re-derivation,
  so an unchanged analysis must render byte-identically — otherwise every run reads as a change,
  and outbox/retry is converging on a value that never settles. Everything sorts; ids are sanitised
  slugs rather than hashes, so a reader can compare two runs' diagrams node by node.
- **Structural nodes stay visibly distinct**, per §3 — a grouping node renders as a subgraph titled
  *"— grouping only"*, and `scope_hierarchy.missing_ancestors` is now shared with `persist.py` so
  the set drawn is provably the set persisted. A node drawn as a component but persisted as
  structural would show a curator a different architecture from the one the findings describe.
- **A grouping node inherits its children's blueprint when they agree**, and stays unassigned when
  they do not — children spanning two blueprints is a fact worth seeing, not one to settle by
  majority. Where composition and blueprint membership disagree, the membership is stated on the
  node, because blueprint membership is Collection membership and is independent of nesting.
- **Unresolvable wire endpoints render as external** rather than being dropped: a missing edge is a
  different architecture, not a tidier one. (`interfaces.propose` attributes compose wires by
  service *name* while ports are attributed by component *slug* — both resolve.)
- **The diagram lives under its own kind, `architecture_diagram`, not under `architecture_recovery`.**
  Not a filing preference. `context_compile.py` calls `query_findings(slug, analysis_id)`, which
  defaults to whole-resource scope; every recovery finding is written at *component* scope, so that
  query returns nothing and the compiler correctly falls through to the analysis's own results
  reader. A whole-resource finding under the recovery kind would make it return exactly one row — a
  Mermaid blob — and **suppress that fallback**, replacing the architecture section of a prompt with
  a picture drawn for a curator rather than evidence a model can reason over. Capping its size
  downstream limits the damage but does not restore the reader. Ports and wires already live under
  `architecture_interfaces` for the same reason, with their own results reader.
- **A diagram is not a claim.** It is stored with `confidence: 0` and `not_a_claim: true`: it
  asserts nothing of its own, it renders claims that each carry their own confidence, drawn on the
  nodes. 100 would read as certainty about the architecture; anything lower as doubt about the
  drawing.
- **No diagram when a run found no components** — one would imply a proposal exists where the run
  found none. The component-count metric already carries that outcome.

Verified by rendering through the running `egeria-shared-kroki` container rather than by eye: six
adversarial cases (empty IR, quotes/brackets/braces/newlines/backslashes in labels, deep nesting,
external wires, all five `SolutionPortDirection` values, two blueprints) all return HTTP 200, as do
real corpus renders of `milvus` and `genaicomps` at three depths.

### The measurement that matters, and it is a problem

Rendered against the live registry:

```
resource      components   nodes at depth 0   depth 1   depth full
milvus               221                104        169          289
genaicomps           317                 13        310          343
```

**At the default projection depth (1), these are not diagrams a curator can judge** — 137 shown
components for milvus, 296 for genaicomps. The renderer is honest about it (the caption states what
was collapsed) but honesty is not legibility, and §1's whole premise is that the picture is the
decision instrument.

Depth 0 fixes genaicomps (13 nodes) and does far less for milvus (104), because milvus carries many
root-level deployment/identity components with no parent to collapse into — so *depth alone is not
the control that makes this readable*. This is the open question in §12 sharpened into a measured
one: the answer is probably clustering (§10) rather than projection, since a candidate blueprint is
exactly the unit that would make 104 root components into a handful of groups.

**Not fixed by lowering the default.** That would trade one unreadable view for a different one and
hide the finding. Recorded instead.

**Swept across the whole corpus** (all 42 resources with recovery results, rendered and posted to
kroki):

```
rendered            42
kroki failures       1   genaiexamples — MaxTextSizeError, 59,791 chars vs a 50,000 limit
too large to judge  12   >40 shown components at the default depth
                         (genaiexamples 585, genaicomps 296, egeria_git 178, milvus 137, …)
```

So it is not two awkward repos: **more than a quarter of the corpus produces a proposal no curator
could read**, and one produces a diagram no renderer will draw at all. `RENDERER_CHAR_LIMIT` is now
a named constant, and an oversized diagram is **stored and labelled** (`char_count`,
`exceeds_renderer_limit`) rather than truncated — a silently shortened architecture is a different
architecture, and the failure must be discoverable before a curator opens it rather than at that
moment.

### The signals for clustering — measured, after two wrong queries

Feasibility of §10's three signals against data that exists today:

| Signal | Available now? |
|---|---|
| **1. Deployed together** | **Yes** — 20 of 42 resources carry deployment-derived components (5,851 of 11,965 components) |
| **2. Components that interact** | **Yes** — 9,118 port/wire findings across 25 resources (`genaicomps` alone: 1,422 ports, 1,305 wires) |
| **3. Same external interface** | **No** — needs the standing interface-extraction item, as §10 already says |

**Both numbers took three attempts, and the first two failures were the query, not the data** — the
standing prior in `Backlog.md` held again. Ports and wires are stored under `kind =
"architecture_interfaces"`, **not** `architecture_recovery`, and their `check_name` is dynamic
(`port:{name}`, `wire:{target}`), so a reasonable-looking query against the recovery kind returns a
confident zero. Anyone reading interface data must query that kind and match the prefix.

The consequence for §10: **signal 2 is not blocked, it is the best-supported of the three**, and it
is exactly the signal that would turn milvus's ~100 root-level components into a handful of
densely-wired groups. That makes wire-density clustering the first thing to build, not the second.

Also worth knowing for the annotation carrier: a full-depth genaicomps diagram is ~33KB of text.

## 13. Still open

- **Cluster signal 3 depends on unbuilt work** (§10) — interface extraction has to answer "can I use
  it" before "same external interface" can group anything. Specified now, built after.
- **How many candidate clusterings is useful rather than paralysing?** A proposal may carry several
  (§10), but a curator shown six clusterings of 82 components has been given a worse problem, not a
  better one.
- **How to make a large proposal legible.** Measured in §12: depth alone does not do it, because a
  repo can have a hundred root-level components with nothing to collapse into. Clustering (§10) is
  the likelier answer, which makes it a prerequisite for the review surface rather than a
  parallel workstream.
- **Where a ~33KB diagram lives on the annotation.** `additionalProperties` is a
  `map<string,string>`; whether a diagram of that size belongs there, in `jsonProperties`, or
  attached another way is unresolved.
