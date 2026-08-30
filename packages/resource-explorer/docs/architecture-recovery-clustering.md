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

**The affinity signals have data, but less than first stated — corrected 2026-08-29 after measuring
rather than reading the docstring.**

| Signal | What the corpus actually holds |
|---|---|
| `cochange_cohesion` | 1,617 rows across **11** resources, heavily skewed to zero: 703 are exactly 0, median 0.012, p90 0.133, max 0.875 |
| `import_cohesion` | **zero rows.** Computed only by the throwaway spike script; never wired into the product until 2026-08-29 |
| wires | **454 distinct** wires, of which **429 (94%)** resolve both endpoints to a known component. Concentrated: genaiexamples 222, genaicomps 51 |

Two corrections to earlier claims in this document and in the report-then-curate note:

* *"import_cohesion and cochange_cohesion are computed by `arch_recovery_coupling`"* — **only
  co-change was.** `persist_ir`'s docstring has claimed both since August; the import half was never
  connected to storage, the same shape as spike finding 89 (ports and wires computed by the spike
  harness and stored nowhere in the product). Wired 2026-08-29: the import graph was already built in
  that surveyor and `cohesion_table` is generic over edge shape, so it was three lines.
* *"9,118 port/wire findings across 25 resources"* — that counted **rows across every run**, not
  distinct wires. The distinct figure is 454. Same row-versus-entity confusion that has produced
  wrong numbers in this project before; the honest statement is that wires are the **best-resolving**
  signal (94% of endpoints resolve), not the largest.

### The threshold question, settled by measurement — and it needed no judgement after all

`import_cohesion` was wired on 2026-08-29 and the coupling step re-run on **milvus**, **egeria** and
**egeria-workspaces** to produce data. 1,085 values:

```
exactly 0     1020   94.0%   ########################################################
0 < x < 0.1     54    5.0%   ##
0.1 - 0.3        4    0.4%
0.3 - 0.5        0    0.0%
0.5 - 0.9        3    0.3%
0.9 - 1.0        4    0.4%
```

**Two values in the entire set fall between 0.3 and 0.7 (0.2%).** A component's imports either almost
all stay inside its subtree or almost all leave it — the metric is close to a boolean stored as a
float. So the exact bar barely matters: anything in that empty middle classifies all but two
components identically.

**And the bar already exists.** `coupling.COHESIVE_BAR = 0.35` is what the coupling surveyor already
classifies a subtree `cohesive` at, and `coupling.py` carries an explicit task rule against
re-tuning it. It sits inside the empty band, so two independent routes — an existing protected
constant and a fresh distribution — arrive at the same number. Clustering **reuses** it rather than
defining its own, with a test asserting they stay the same value.

Two earlier conclusions in this document are superseded:

* *"the distribution argues against a fixed global threshold"* — that was measured on
  `cochange_cohesion` (median 0.012, p90 0.133), which genuinely is a continuum and genuinely would
  need an arbitrary cutoff. `import_cohesion` is not, and it is the signal that ended up carrying
  this. Measuring the wrong one of the two metrics produced the wrong conclusion about both.
* *"a relative, per-repo rule is likely needed"* — not needed. Bimodality makes an absolute bar
  behave identically everywhere; what differs between repos is only **how many** components clear
  it, which is a fact about the repos rather than a defect in the bar.

What the bar actually selects, run against the three repos:

```
egeria_git              670 scopes with import_cohesion,  0 at/above 0.35
egeria_workspaces_git     2 scopes,                       2   (0.977, 0.975 — two deployments of PyegeriaWebHandler)
milvus                  413 scopes,                       5   (1.000 internal/core/build-support, ...)
```

Seven promotions out of 1,085. Rare, decisive, and silent on egeria — a large multi-module Java repo
whose subtrees cross-reference heavily, so no component is cohesive by this measure. That silence is
the correct answer, not a gap: it says co-location is all the evidence egeria offers, so egeria gets
Collections.

The **wire** signal remains available and unused for now: 454 distinct wires, 429 (94%) resolving
both endpoints, concentrated in genaiexamples (222) and genaicomps (51). It is the best-*resolving*
signal rather than the largest, and it is the obvious next one for the cases import cohesion cannot
reach.

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

## 7a. Wire cohesion does NOT work as an affinity signal — a negative result

Tried 2026-08-29, and recorded because the failure is informative and someone
will otherwise try it again.

Computing a cluster's wire cohesion the same way import cohesion is computed —
internal edges over internal-plus-boundary — gives:

```
157 clusters touching a wire:  median 0.750   p90 1.000   at/above 0.35: 106 (68%)
```

Reusing `COHESIVE_BAR` there would promote **two thirds of all clusters** to
composed components — the opposite of the rare-and-decisive behaviour the rule
wants. The cause is visible in the raw rows: `internal=1 boundary=0` scores a
perfect 1.0. **84 of 157 clusters had one or two wires in total**, and a ratio
over one observation carries no information.

A minimum-observation guard (the pattern `COCHANGE_SEAM_MIN_WEIGHT` already
uses) thins it honestly but does not rescue it: requiring 10 wires leaves six
clusters corpus-wide.

**Improving discovery did not fix it either**, which is the part worth knowing.
Adding compose environment references as a wire source (below) produced 2.6x
more wires — 24 to 63 across three repos, milvus alone 12 to 44 — and the
distribution barely moved: no cluster exceeded five wires. Better discovery
improved the graph's *fidelity* without concentrating it, because a service's
configuration typically names things outside its own group.

**Conclusion: import cohesion is an affinity signal; wires are an evidence
signal.** Imports are dense enough per component to support a ratio (413 scopes
on milvus alone); wires are declarations of individual connections and there are
only ever a handful per group. Wires remain valuable for what they are — the
best-*resolving* signal at 94% endpoint resolution, and what makes a diagram
answer "what talks to what".

## 7b. Discovery, not tuning — what the wire investigation actually found

Asked why wire volume was so low, the answer was not thresholds:

**Ports had six discoverers; wires had one.** Ports came from compose `expose:`
and `ports:`, OpenAPI, `.proto`, GraphQL and Thrift. Wires came from compose
`depends_on` — and only that. `depends_on` is the weakest declaration available;
the code's own comment says it *"states startup ordering … but says nothing
about whether traffic returns"*.

Two sources were added:

* **Compose environment references.** `KAFKA_CFG_ZOOKEEPER_CONNECT=zookeeper:2181`
  names a service, a port and a direction — strictly more than `depends_on`
  says. Merged one-edge-per-pair, preferring the environment reference, since
  counting a pair twice inflates every measure computed over these wires.
* **Spring application declarations** (`spring_app.py`). Egeria has **no compose
  files at all**, so no amount of compose work could ever have found its wires:
  its architecture is declared in `application.properties` and server config
  documents. Reading those took egeria from 0 wires to 8, and from no deployment
  perspective to one.

The general lesson, four measurements deep: **when a signal looks too sparse to
use, check what discovers it before tuning what consumes it.** Three of the four
measurements said the signal was not the problem.

## 7c. Deployment style is an attribute, not a component — one platform, three ways

Dan, 2026-08-29: *"I think Development and Containerized isn't the right framing
— its Native Java vs Containerized vs Choreographed containers (e.g. quickstart
and freshstart) which are choreographed with compose or kubernetes."*

He was right, and the overcount it names was measurable. Egeria carried **14
deployment components** — two platforms of five servers each, plus PostgreSQL
and a phantom called `test` — for **one platform with five servers**.

### Where the duplication came from

`spring_app.discover()` emitted one platform per `*application.properties` file,
and egeria has three:

| file | `platform.name` | servers |
|---|---|---|
| `application.properties` | Development OMAG Server Platform | 5 |
| `container.application.properties` | Containerized OMAG Server Platform | **the same 5** |
| `test.application.properties` | *(none)* | **none** |

The first two are not two platforms. The release workflow
(`.github/workflows/merge-v6.yml:75`) does:

```
cp -f container.application.properties \
      .../assembly/platform/application.properties
```

and the Dockerfile then `COPY`s that directory. **The container image's
`application.properties` IS `container.application.properties`** — the same file
at two points in one build. `platform.name` differs because the author labelled
each for its runtime, which is a *style*, not an identity.

The third declares nothing at all: an empty `startup.server.list` and no
`platform.name`, so the name fell through to the filename and produced a
component called `test`.

### The rule, and the case that stops it going too far

**Declarations that share a directory AND declare the same server set are one
platform deployed several ways.** A comparison, not a threshold — the same
discipline as §7's affinity bar and `undetected_is_meaningful`'s
`terms <= components`. Nothing here can be tuned to make a number look better.

The contrast case is what makes it safe, and it is in the corpus already:

```
egeria              application.properties            5 servers  ] same dir,
                    container.application.properties  same 5     ] same set -> ONE

egeria-workspaces   runtime-volumes/freshstart-.../    fs-metadata-store, ... ] different dirs,
                    runtime-volumes/quickstart-.../    qs-metadata-store, ... ] disjoint  -> TWO
```

Workspaces' two platforms are genuine peers — Dan's *choreographed* case,
started by compose — and must not merge. They do not, on either half of the key.

**The directory half was added because a test caught the rule being too loose.**
Server-set equality alone merged two platforms named Alpha and Beta sitting in
separate directories, and the pre-existing
`test_the_notes_say_an_environment_may_span_repos` failed. Two deployments can
legitimately run the same server names; the directory is what
`Identity.deployment_context` already means, so the second half of the key was
free.

### Style comes from what REFERENCES the file, not from its name

| style | evidence |
|---|---|
| `choreographed` | referenced from a path containing `compose` / `k8s` / `kubernetes` / `helm` / `kustomiz` |
| `containerized` | referenced from a Dockerfile or an image-building CI workflow |
| `native-java` | the bare `application.properties` — what a plain `java -jar` reads |
| *(none)* | an unrecognised profile token: no style rather than a guessed one |

Filename is the fallback, never the first test. Measured, the reference test is
what gets workspaces right: it choreographs from
`compose-configs/egeria-freshstart/egeria-freshstart.yaml`, which no
`docker-compose.yml` filename test reaches.

One subtlety worth stating because getting it wrong is silent: the *destination*
of a substitution — the literal `application.properties` a workflow writes — is
skipped. Styling it would style the platform's own canonical file according to
whichever workflow happened to be read first, which is order-dependent.

**A note on where this evidence lives.** Deployment style is decided by CI
workflows, Dockerfiles and compose files — all **Dev/DevOps-perspective**
artifacts, the perspective §4.1 rates *"weakest of the four"* and for which
pipelines have *"no good type"*. The signal that disambiguates the deployment
perspective comes from the perspective we model worst. Worth knowing before
anyone trusts it further than the evidence table above.

### Result

| | before | after |
|---|---|---|
| egeria deployment components | 14 | **6** (platform + 5 servers) |
| egeria clusters | — | **1**, of 6 — inside §7's target of ~10 |
| egeria ports | 16 rows, 8 distinct | **8** |
| egeria wires | 8 rows | **5** |
| workspaces platforms | 2 | **2** — unchanged, as required |

### Two things the merge broke, and both were silent

Wires and ports are built **per declaration**, so merging left one copy per
profile. Ports arrived as 16 rows for 8 distinct topics, each exactly doubled,
and `to_ir` lands them all on the same server slug. Wires carried a `platform`
name that no longer named any component, which `to_ir` attributes by — an edge
pointing at nothing, raising nothing.

Both are deduplicated **keyed on the owning platform**, not on the port or wire
alone. Two platforms that were never merged may legitimately declare a same-named
server with the same topic, and collapsing those would delete a real distinction
to fix a bookkeeping one — §4.1a's discipline applied to interfaces.

### Two tests passed vacuously, and that is the finding worth keeping

The port and wire dedup tests both passed the moment they were written. They
asserted `len(keys) == len(set(keys))` and `all(...)` over lists that were
**empty**, because the fixtures used `endpoint.address` where the code reads
`endpoint.networkAddress`, and an endpoint key outside `_ENDPOINT_KEY_HINTS`.
An empty list is unique and satisfies `all()`.

This is the session's recurring pattern in its smallest form — *check what
discovers a signal before trusting what consumes it* — and it now has a guard
rather than a lesson: both tests assert the fixture produced something before
asserting anything about it.

### Validated against two projects nobody designed it for — and it broke

Everything above was measured on exactly two repos, both Egeria. On 2026-08-29
`open-metadata/OpenMetadata` and `apache/polaris` were pulled to test it, chosen
because they are JVM metadata systems of comparable scale and neither is
Egeria-shaped.

**`polaris` found a real defect in the day-old rule.** It is Quarkus, not
Spring — and Quarkus uses `application.properties` too. It declares two
applications:

```
runtime/defaults/src/main/resources/application.properties
    quarkus.application.name=Apache Polaris Server
runtime/admin/src/main/resources/application.properties
    quarkus.application.name=Apache Polaris Admin Tool
```

Neither has a `startup.server.list` (an Egeria concept with no Quarkus
equivalent) and neither sets `platform.name` or `spring.application.name`. So
**the no-servers-and-no-name rule dropped both** — the rule that correctly killed
egeria's phantom `test` component also killed every Quarkus application it would
ever meet. Two real components read as zero.

Worth being precise about what changed, because the previous behaviour was not
good either: before the rule, both files produced a component called `platform`,
from the filename fallback. So the score went **2 junk components → 0 components
→ 2 correct components**, and only the last of those is right.

The fix is one table row. `_NAME_KEYS` now holds the three spellings of one
concept — `platform.name`, `spring.application.name`, `quarkus.application.name`
— in precedence order, because an Egeria platform hosting servers is a different
thing from the framework's name for the process and, where both exist, the
platform name is what a curator wants.

**Zero servers is a legitimate shape, not a failed read.** Egeria's
several-servers-in-one-process has no Quarkus analogue; a Quarkus application is
simply a platform with no sub-components.

**The directory half of the merge key earned its place a second time.** Polaris'
two applications both declare *zero* servers, so the server-set half of the key
makes them identical. Only the directory keeps them apart. That half was added
the same day because a test caught the rule being too loose, and this is an
independent case that would have failed without it.

**`openmetadata` found a coverage boundary, and is correctly silent.** It is
Dropwizard: configuration lives in `conf/openmetadata.yaml`, and the repo
contains **no `*application.properties` at all**. Zero platforms is the right
answer, and it is worth recording as a *measured* boundary rather than an
assumed one — this module reads properties files, not every JVM configuration
format.

| repo | framework | before | after |
|---|---|---|---|
| egeria | Spring Boot | 14 components | 6 |
| egeria-workspaces | Spring Boot | 2 platforms | 2 |
| **polaris** | **Quarkus** | **0** | **2** |
| **openmetadata** | **Dropwizard (YAML)** | **0** | **0** — correct |

**The lesson is about the sample size, not the bug.** A rule measured on two
repos from one project family met its third project and was wrong within
minutes. It was cheaply wrong — a table entry, caught by running rather than
reasoning — which is an argument for widening the corpus early and often, not
for trusting the next two-example rule more.

### Known consequence, not yet addressed

**Renaming a component's slug orphans its rows rather than superseding them.**
`query_findings` returns rows at `MAX(surveyed_at)` *per `scope_locator`*, so a
scope nothing writes any more keeps its last value forever. Dropping the
`spring::` prefix left **14 orphaned scopes on `egeria_git`**, still readable and
still wrong, and this consolidation will orphan a further 12 when egeria is
re-surveyed (`Development-OMAG-Server-Platform::*` and
`Containerized-OMAG-Server-Platform::*`).

Deliberately not fixed here, and deliberately not deleted — nothing in this
pipeline should quietly remove evidence. Designed separately in
**`architecture-recovery-scope-tombstoning.md`**, which finds that the actual
leak is `query_finding_scopes` (no recency filter at all — a scope, once
written, is enumerable forever), that a withdrawal row alone therefore changes
nothing, and that withdrawal must be attributed to the writing step or
`repo_arch_detect` and `repo_arch_coupling` will erase each other's components
alternately and forever.

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
