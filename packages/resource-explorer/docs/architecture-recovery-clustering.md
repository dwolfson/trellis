# Clustering — what proposes a candidate blueprint

**Status:** design, 2026-08-29, from Dan's five points. Nothing built. The measurements below are
against the live registry and are the reason two of the five points need less work than expected and
one needs more.

Prerequisite context: `architecture-recovery-report-then-curate.md` §10 named the three signals
(deployed together / components that interact / same external interface) and left *what proposes the
clusters* undesigned. This is that piece.

---

## 1. There is no single right clustering — and the design already proved it

Dan: *"the clusters that make sense, the level of detail of the modules and the coarseness of ports
and wires is not a single answer — it depends on what you are trying to accomplish. If you are
maintaining the software your view might be quite different than if you are responsible for deploying
it or using it."*

This is **§4.1 of the main design**, which calls it *"the most important structural revision in this
document"*: the architecture is not one thing recovered at one granularity, but four views with
different sources, vocabularies, Egeria homes and availability — Physical (what is on disk),
Deployment specification (what the repo says should run), Logical (what the software is), Dev/DevOps
(how it is built and released).

**And §4.1 already has the empirical proof.** The Phase 0 spike scored **16/16** on
`egeria-workspaces` and **1 of ~10** on `trellis`, which reads as "works on one repo, fails on the
other". It was neither: the workspaces ground truth is a *deployment* architecture, the trellis one a
*logical* architecture, and a deployment-perspective detector was being scored against a
logical-perspective ground truth. The same evidence, clustered for the wrong purpose, looks like a
broken detector.

So the answer to "which clustering?" is not a preference — getting it wrong is measurably
indistinguishable from the tool not working.

### ⚠ Two different things are called "perspective" — do not conflate them

| | What it is | Can it drive behaviour? |
|---|---|---|
| **§4.1 architectural perspective** — physical / deployment / logical / dev | a property of each **component**, already carried on `Component.perspective` | **Yes** — populated and discriminating, measured below |
| **Question-catalog Perspective** — Admin, Security, Architecture, … (12 Title-Case) | display-filter tags on questions | **No** — measured 2026-08-24: *not one of the twelve reaches a single analysis another does not also reach*. Strictly nested; varies result size, never content. Demoted to a secondary ranking axis; **Purpose** is the discriminating one |

Clustering must key on the **first**. `investigation-framing-design.md` §3 settled that the second
cannot drive dispatch, and that finding stands — it just does not apply here, because it is a
different axis with different data behind it.

## 2. Measured: the data exists, and clustering has never run

Across all 42 resources with recovery results, 3,215 components:

```
perspective   logical      1747
              deployment   1300
              physical      168
              dev             0

blueprint     (empty)      3215   -- every component, without exception
```

Two facts follow. **The clustering axis is real and populated** — this is not a field that would have
to be introduced. And **no component has ever been assigned to a blueprint**, so the `blueprint`
grouping in the Mermaid renderer has never had data to render. Clustering is genuinely unbuilt rather
than partly built.

## 3. Measured: perspective-scoped grouping already reaches Dan's ~10 for deployment

Dan: *"Blueprints that are too complicated aren't very useful — we should try to keep the number of
components small — lets say around 10 or less … not a hard rule — just a goal for presentability and
usefulness."*

**CORRECTED 2026-08-29, an hour after this section was first written.** The first version measured
the number of *groups per repo* and reported the goal as met. That is the wrong metric: the goal is
the number of components **inside** a blueprint, not the number of blueprints. Re-measured
accordingly, applying the existing `scope_hierarchy.derive()` grouping *within one perspective* and
counting **members per cluster**:

```
DEPLOYMENT perspective                    clusters over 10 members:  13 of 115  (89% within goal)

resource                comps  clusters   largest   member counts
genaiexamples             546         8       135   [135, 110, 104, 86, 84, 9, ...]
genaicomps                289         4       203   [203, 83, 2, 1]
enterprise_rag             86        13        24   [24, 22, 8, 8, 5, 4, ...]
workshops                  43         5        16   [16, 10, 9, 4, 4]
milvus                     31         5        11   [11, 8, 8, 3, 1]
egeria_workspaces_git      59        15         8   [8, 7, 6, 6, 6, 5, ...]
polaris                    58        17         7   [7, 7, 5, 4, 4, 4, ...]
kafka                      31         6         7   [7, 7, 7, 6, 3, 1]
marquez                    13         2         7   [7, 6]
```

**102 of 115 deployment clusters already sit within the ~10 goal**, and most repos are entirely
within it — `egeria_workspaces_git` tops out at 8, `polaris` at 7, `kafka` at 7. The conclusion from
the first version survives, but the reason is different and worth stating precisely: it is not that
grouping produces few clusters, it is that most clusters it produces are already small enough to read.

**The failures are concentrated, not spread.** Two monorepos account for 7 of the 13 oversized
clusters, with single groups holding 203 and 135 components. Those are not a clustering failure —
they are a group that needs *another level*, which is precisely what §4 (hierarchies) is for. The
algorithm therefore has a recursion step: group, and for any cluster still over the goal, subdivide
using the next level of scope, stopping when within goal or when no further structure exists. A
cluster that cannot be subdivided is **reported as oversized rather than silently emitted** — the
same "no silent caps" rule the renderer follows for diagram size.

The **logical** perspective is a different problem: `egeria_git` produces 279 top-level groups from
924 components, so it fails on cluster *count* before member count is even interesting.

### And that split is exactly what §4.1 predicts

§4.1's availability column, written before any of this was measured:

* Deployment specification — *"only where artifacts exist"*, derived from Dockerfiles and compose
  files, which are **declarations a human wrote about grouping**. Clustering them is reading a
  boundary someone already drew.
* Logical — *"needs inference or a human"*.

So the perspective that clusters cleanly is the one whose boundaries were authored, and the
perspective that does not is the one the design already said requires judgement. **The measurement
did not discover a gap in the clustering algorithm; it located the gap where the design said it
would be.**

## 4. Hierarchies are the abstraction mechanism, and the machinery is built

Dan: *"Hierarchies are our friends … as we cluster with a particular context in mind, we can use
hierarchies to provide the abstractions that make the representations more understandable."*

`projection.py` already implements exactly this — *"store the hierarchy; project a level"* — with
`STAGE_PROJECTION_DEPTH` mapping a consumer to the depth it wants (`discovery: 0`, `assessment: 1`,
`analysis: None`). Nothing there needs redesigning; it needs **a clustering to project**, and a
context to choose the depth for.

The composition to build is therefore: **filter by perspective → group by signal → project to a
depth that meets the ~10 goal.** Depth becomes the dial that enforces presentability, and because the
full hierarchy is always persisted, a curator can go deeper without re-deriving anything.

**One measured caution.** Depth alone does not do it: rendering the corpus showed `genaicomps`
collapsing well at depth 0 (13 nodes) while `milvus` barely moved (104), because milvus carries many
root-level components with nothing to collapse into. Depth is the dial *after* clustering, not
instead of it.

## 5. Context arrives through the survey, and the mechanism already exists

Dan: *"We can have specialized surveys or parameterized surveys to pass in the desired context(s)."*

This lands on a decision already taken: `architecture-recovery-report-then-curate.md` §7 established
that **the survey is the unit of intent** — a survey is chosen to achieve a goal, so whether a curator
is asked to review a proposal is a *step in the survey definition*, not a mode on the analysis.

Clustering context is the same shape. A survey definition carries the perspective(s) to cluster for;
the analysis does not guess. Two forms, both natural:

* **Specialised** — "recover the deployment architecture", a definition whose clustering step is fixed
  to one perspective.
* **Parameterised** — one definition taking the perspective(s) as a step parameter.

Either way the context is *declared where the intent is already declared*, and a proposal records
which context produced it — so two clusterings of the same repo are comparable rather than
contradictory. **A repo may legitimately hold several blueprints** (§3.3a, corrected 2026-08-29), and
"the deployment blueprint" and "the logical blueprint" of one repo are the clearest case of that.

## 6. Asking a human is the designed outcome, not the fallback

Dan: *"clustering may require, in some situations, human interaction — this is not a failure, it is a
recognition that we don't know enough about what they are trying to understand or accomplish … It is
better to ask for help than it is to give bad but confident answers."*

The measurement in §3 turns this from a principle into a **route**. The logical perspective is where
automatic grouping runs out — 279 roots on `egeria_git` — and it is the perspective §4.1 independently
says *"needs inference or a human"*. Two independent lines arriving at the same place is a strong
signal that this is the boundary rather than a gap to engineer away.

And the machinery to ask already exists: report-then-curate publishes a **proposal**, and a survey
definition may carry a step that raises an **RFA** asking a curator to review it. A proposal that
cannot cluster confidently does not need a new mechanism — it needs to say so and use the one that is
already there.

Three things follow for how this should behave:

* **A proposal may carry more than one candidate clustering.** Under report-then-curate it is a
  proposal, not an answer, so offering two or three groupings and letting a curator pick is *easier*
  than getting one right unattended.
* **Disagreement between signals is information.** Deployed-together and interface-sharing pulling
  apart is a fact about the repo worth showing, not a conflict to settle silently by weighting.
* **No signal, no cluster.** Consistent with §5's "no metric, no number": a component nothing groups
  stays ungrouped rather than being swept into the nearest cluster.

**Deliberately deferred:** interactive experimentation — a curator re-clustering, merging, splitting
and re-projecting to find a view that serves them. Dan names it as future work and it should stay
future work, but the path is recorded here so the earlier stages do not foreclose it. The thing that
would foreclose it is materialising a single clustering as *the* answer, which report-then-curate
already prevents.

## 7. Why a cluster is a Collection and not a parent component

Asked by Dan, 2026-08-29: *"Why not use components and sub-components for clustering?"* It is the
obvious alternative — `SolutionComposition` nests components natively and the IR already carries
`parent_slug` — so the reason not to should be written down rather than rediscovered.

**The reason is evidence, and it is the only one that holds.** `scope_hierarchy` already refuses to
emit derived ancestors as components, in its own words: *"A derived parent is a structural node,
never a component. These ancestors have no marker evidence of their own — nothing detected
`internal/`, its children were detected — so they carry no type, no confidence and no proposer.
Emitting them as ordinary components would invent evidence."*

A cluster is in the same position. `comps/animation/deployment` is a real boundary — a person put
those services in that directory — but nothing detected a *component* there. It has no
`SolutionComponentType`, no confidence, no proposer. **A Collection says "these belong together",
which is what was observed. A component says "this is a thing", which was not.**

### Affinity is the test, and it decides which one you get

Dan's rule, 2026-08-29: **no affinity leads you to collections.** Where the members genuinely cohere
— they call each other, change together, depend on each other — there is grounds to assert a
containing component, and composition is right. Where they are merely *co-located*, the grouping is
real but the group is not a thing, and a Collection is the honest carrier.

That maps directly onto the signals, and it is a sharper rule than "clusters are Collections":

| Signal | What it observes | Affinity? | Carrier |
|---|---|---|---|
| Same compose file / `deployment_context` (§10 signal 1) | declared **co-location** — someone filed these together | no | **Collection** — a blueprint |
| Wire density (signal 2) | components that actually interact | **yes** | grounds for a **composed component** |
| `import_cohesion` / `cochange_cohesion` | modules that import each other, or change together | **yes** | grounds for a **composed component** |
| Same external interface (signal 3) | joint presentation of one API surface | **yes** | grounds for a **composed component** |

**Everything built so far is a co-location signal**, which is why everything built so far produces
blueprints — and that is correct rather than a limitation of the first cut. `docker_compose::` and
`comps/animation/deployment` say where a thing was *declared*, not that its members belong to one
another.

**And the affinity signals already have data.** `import_cohesion` and `cochange_cohesion` are
computed by `arch_recovery_coupling` and attached per component via `persist_ir`'s `extra_metrics` —
**1,617 cohesion metric rows in the corpus today**. So the composed-component route is not a future
capability requiring new analysis; it needs a rule for how much cohesion is enough to assert a
component, which is a judgement, and under report-then-curate a proposal can put that judgement to a
curator rather than settling it silently.

This also explains the shape the corpus is in. The logical perspective — the one that will not
cluster by co-location (`egeria_git` 924 → 279) — is precisely where the affinity signals live, since
cohesion is computed over imports and co-change rather than over deployment artifacts. **The
perspective co-location cannot group is the perspective affinity can.**

### A correction to a second argument that does not hold

An earlier version of this answer also claimed composition could express only *one* hierarchy, so
Collection membership was required for §1's several-clusterings-per-context. **That is wrong about
Egeria.** Checked in the type archive:

```
SolutionComposition   end1 = SolutionComponent, RelationshipEndCardinality.ANY_NUMBER
                      end2 = SolutionComponent, RelationshipEndCardinality.ANY_NUMBER
                      OpenMetadataTypesArchive1_7.java:822-860
```

Both ends are `ANY_NUMBER`, so a component may have several composition parents and **multiple
overlapping composition hierarchies over the same components are fully supported by the model**.

The single-parent constraint is **ours, not Egeria's**: `Component.parent_slug` is a single string.
That is an RE modelling choice, and if multiple composition hierarchies were ever wanted it is the
thing that would have to change — a real but ordinary cost, not a blocker. It is worth being precise
about which side a constraint lives on, because "the model does not allow it" and "our IR does not
represent it yet" lead to different work.

### Where sub-components ARE the right answer

Composition is not the loser of this argument — it is already in use and stays. Where the parent *is*
a detected thing (a package that declares its modules, a service composed of declared sub-services),
`parent_slug` is filled from the scope locator and the renderer nests by it. The division is:

* **Composition** where evidence supports a parent that is itself a component.
* **Collection membership** where the grouping is real but the group is not a component.

And that division is exactly the tension that surfaced when clustering was wired in: the scope
locator claimed `docker_compose` was the parent of all 203 genaicomps services, which is a locator
artifact rather than a detected thing, so the blueprint had to win the display (§8). `rollup()` builds
nested **blueprints** rather than nested components for the same reason — a repo-level grouping of
sub-groupings asserts membership, which is all the evidence supports.

## 8. Build order

1. **Cluster within the deployment perspective**, using `scope_hierarchy` grouping that already
   exists, and project to the ~10 goal. Measured above as most of the way there on most repos — the
   cheapest real result available, and it makes the renderer's blueprint grouping meaningful for the
   first time.
2. **Carry the perspective in the survey definition** (§5), so a proposal records the context it was
   clustered for.
3. **Wire density as the second signal** (report-then-curate §10 signal 2) — 9,118 port/wire findings
   across 25 resources under `kind="architecture_interfaces"`, the best-supported of the three
   signals. This is what should be tried against the logical perspective before concluding it needs a
   human.
4. **RFA the cases that do not cluster**, rather than emitting a low-confidence grouping (§6).
5. **Same external interface** (signal 3) stays blocked on the standing interface-extraction item —
   extraction answers "does it expose something", not "can I use it".

Not in the plan: a general-purpose clustering algorithm over the component graph. Every signal above
reads a boundary something already declared — a compose file, a wire, an interface. That is the
difference between recovering an architecture and inventing one.
