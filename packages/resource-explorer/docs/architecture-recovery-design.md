# Architecture Recovery — Deriving Solution Blueprints from Repositories

**Status:** design + plan. Review comments incorporated. All open questions resolved except **Q6**
(deliberately out of scope) and **Q13** (correctly deferred to after Phase 0). **Ready to plan.**
**Date:** 2026-08-19 (revised same day after review)
**Context:** extends the Scouting → Discovery → Analysis funnel with a new analysis class that
produces *design* metadata (Egeria Area 7) rather than measurements. See
`docs/survey-and-analysis-current-state-2026-08-19.md` for what RE does today.


> **Note on source tree.** The Egeria-side grounding in §3 (types, enums, pyegeria client methods) was
> verified against `/Users/dwolfson/localGit/egeria-v6/egeria` and `egeria-python` and is unaffected by
> the repo migration. **RE-side references — gap numbers, file paths, line numbers — were derived from
> the pre-migration standalone `resource-explorer` repo and inherit the staleness documented in
> `survey-and-analysis-current-state-2026-08-19.md`.** Re-verify anything RE-specific against
> `trellis/packages/resource-explorer` before acting on it.
>
> **Revision note.** The RE-side claims added in the post-review revision — §5.5, §5.6, §5.7, §6.0,
> §6.5, and the storage decisions in §5.4 — *were* verified against `trellis/packages/resource-explorer`
> (`registry.py`, `surveyors/repo_survey_definition_adapter.py`, `surveyors/prefect_adapter.py`,
> `agents/`, `configdata/analysis_catalog.yaml`). The staleness warning above still applies to the
> gap numbers (R1–R5) and to line references in the original §1–§4 and §6.1–§6.4.
>
> **2026-08-20 update, from `re/deferred-cleanup-followups` (79d74c8) — facts confirmed to bear on
> this doc, everything else in that session's changes is unrelated:**
> - **Annotation publishing has one canonical module now: `surveyors/annotation_props.py`.**
>   The three near-identical `_build_annotation_props` implementations that used to exist per-publisher
>   have been consolidated there (a real bug — `resourceProperties`/`confidenceLevel` field-name drift
>   and a missing RELATIONSHIP case — was found and fixed doing it), and a test asserts every publisher
>   produces byte-identical output. **If this feature's projection layer (§5.4, §6.1, §6.4) writes
>   `Annotation`/`CodeAnalysis` properties, go through that module rather than adding a fourth
>   `_build_annotation_props`.**
> - **`STEP_REGISTRY` order is now load-bearing, not just registration order** — it drives "Full
>   Survey (all steps)" execution order via the `*` sentinel in `repo_survey_types.csv`, and a step
>   that writes a table must precede its readers or the run silently reads stale data. Confirmed by
>   three new steps (`repo_git_statistics`, `repo_file_inventory`, `repo_homepage`) each fixing exactly
>   that bug. Directly relevant to §5.7: the proposed `repo_arch_detect` / `repo_code_metrics` /
>   `repo_sbom` / `repo_history_metrics` steps must be registered in an order consistent with what they
>   read and write, not just added.
> - **pyegeria floor is now `>=6.0.18.4`** (needed for `get_governance_action_process_graph` and an
>   ISSUE-63 delete fix). Below that floor, link-reconciliation tooling can silently no-op while
>   reporting removals — worth checking against whatever pyegeria version Phase 0/1 tooling pins.
> - **§3's `SourceControlLibrary` grounding gets one correction and one addition**, both verified by
>   walking the live type system: `SourceControlLibrary` inherits `url` from `Referenceable` (so it's
>   available without extension), and a project's external website is cataloged as a linked
>   `ExternalReference`, not a property on the library itself. Also: `SoftwareLibrary` is a **sibling**
>   of `SourceControlLibrary` under `ResourceManager`, not its parent — matters if any Area 7 modelling
>   here assumed a `SourceControlLibrary` *is a* `SoftwareLibrary`.

---

## 1. The idea in one paragraph

Statically analyse a repository to recover its **architecture** — what the software components are,
how each is run, and how they connect — and project that into Egeria as a **Solution Blueprint** with
**Solution Components**, **Ports** and **Linking Wires**. Derived output is marked as unvalidated and
enters a curation workflow where a human (or agent) promotes, corrects, or rejects it. The recovered
component becomes the *aggregation unit* for RE's existing repo analyses, which today have nowhere
useful to land.

---

## 2. Why this is worth doing — the reframe

The obvious framing is "a new analysis that draws architecture diagrams." That undersells it.

RE currently reports at two granularities, and both are wrong:

- **Whole-repo** — "this repo has 412 Python files, health score 0.72, 38 dependencies." Too coarse to
  act on. A monorepo and a single-purpose library get the same shape of answer.
- **File / symbol** — collected in `project_code_symbols`, `project_file_inventory`,
  `project_dependencies`, the Milvus chunks. Too fine to govern, and per the current-state doc, mostly
  **never published to Egeria at all** (gaps R3, R4, R5).

**The component is the missing middle.** Bus factor per *component* is actionable where bus factor per
*repo* is trivia (gap R1). Dependency risk per component tells you blast radius; per repo it tells you
nothing. Doc coverage per component identifies which subsystem is undocumented.

So this work does two things at once: it adds a genuinely new capability (design metadata), and it
gives several existing-but-orphaned analyses a granularity at which they become worth publishing.
That second effect is the stronger business case.

---

## 3. Grounding — verified facts about the target types

All verified against the local Egeria checkout (`/Users/dwolfson/localGit/egeria-v6/egeria`) and
`egeria-python`, not from documentation alone.

### 3.1 `SolutionComponentType` is a small closed vocabulary

From `frameworks/open-metadata-framework/.../refdata/SolutionComponentType.java`:

`Automated Action`, `Long Running Daemon`, `Multi-Step Process`, `Third Party Process`,
`Manual Process`, `Data Storage`, `Software Service`, `Software Library`, `User Interface`,
`Console Command`, `Data Distribution`, `Publishing`, `Insight Model`.

**This is the single most important fact in the design.** The classification target is not open-ended
— it is a 13-value enum, and most values are directly inferable from deployment artifacts. "How and
where is it run" is literally what this vocabulary encodes.

### 3.2 `SolutionPortDirection` is a 5-value enum

From `.../enums/SolutionPortDirection.java`: `Unknown(0)`, `Output(1)`, `Input(2)`,
`Input-Output(3)` (request-response provided), `Output-Input(4)` (request-response called), `Other(99)`.

Note Input-Output vs Output-Input distinguishes *serving* an interface from *calling* one — exactly
the client/server distinction static analysis can make from imports and framework decorators.

### 3.3 `SolutionLinkingWire` properties are populatable

Per 0735: `iscQualifiedNames`, `label`, `description`, `oneWay`, `integrationStyle`, `frequency`,
`protocol`, `dataExchanged`. Also `SolutionComponentPort` (component→port) and
`SolutionPortDelegation` (parent port → child port in decomposed hierarchies).

`iscQualifiedNames` **on the wire** means ISC attribution is a labelling pass over an existing wire
graph, not a separate extraction. Important for §9.

**But `SolutionLinkingWire` is a *relationship*, not an entity** (`OpenMetadataType.java:6335`), and
classifications attach only to entities. So the `Confidence` classification (§3.3b) **cannot be applied
to a wire.** `SolutionPort` *is* an entity (`OpenMetadataType.java:6345`), so the resolution is to carry
wire confidence on the ports the wire connects rather than inventing a mechanism. Recorded in Q4.

### 3.3a `SolutionBlueprint` is a Collection — and blueprints therefore DO nest

**Corrected 2026-08-29.** This section previously concluded *"blueprints do not nest"* and *"one
blueprint per repo"*. Both were wrong, and the second followed from the first. The original
observation — that there is no blueprint-to-blueprint *relationship* — is true; the conclusion drawn
from it is not, because nesting does not need a dedicated relationship when the type is a Collection.

`SolutionBlueprint` (`OpenMetadataType.java:6298`) is *"a collection of solution components that make
up a solution."* It is a `Collection` by inheritance, traced through the type archive:

```
SolutionBlueprint --extends--> DesignModel --extends--> Collection
  OpenMetadataTypesArchive1_7.java:1109      OpenMetadataTypesArchive1_2.java:9647
  (SolutionBlueprintProperties extends DesignModelProperties extends CollectionProperties)

CollectionMembership   end1 = Collection      OpenMetadataTypesArchive1_2.java:3170
                       end2 = Referenceable   OpenMetadataTypesArchive1_2.java:3185
```

A `Collection` may hold any `Referenceable`, and a `SolutionBlueprint` is one. **So a blueprint can
be a member of another blueprint, through the ordinary `CollectionMembership` mechanism.** No
blueprint-specific relationship is needed or exists.

Component-to-component nesting is separate and also available: `SolutionComposition`
(`OpenMetadataType.java:6303`) relates **SolutionComponents** to each other. `SolutionDesign` relates
a blueprint to a digital service or product. So there are two independent nesting axes — blueprints
within blueprints, and components within components — and they answer different questions.

**A repo is a storage boundary, not a solution boundary.** A monorepo can legitimately hold several
blueprints over different clusters of components, and the natural shape for one is a repo-level
blueprint whose members are sub-blueprints, each a coherent solution in its own right. What proposes
those clusters is undesigned work — see `architecture-recovery-report-then-curate.md` §2b.

The Collection nature also gives — independently of nesting — **membership of a component in more
than one blueprint.** Cross-repo composition therefore works by wiring components across blueprints
and collecting them into an estate-level blueprint, without duplicating anything. That is also the
only mechanism by which §9's estate-wide ISC candidates could work. Recorded in Q8.

### 3.3b `Confidence` is a classification on `Referenceable` — confirmed

`getConfidenceClassification()` (`OpenMetadataTypesArchive1_2.java:6951`) defines the `Confidence`
classification against **`Referenceable`**, so it applies to `SolutionComponent` and `SolutionPort`
directly. Properties, via `GovernedDataClassificationBase`:

`confidenceLevel` (int — a governance level from a valid-value set), `confidence` (int 0–100),
`statusIdentifier`, `steward`, `stewardTypeName`, `stewardPropertyName`, `source`, `notes`.

**`confidence` is an int 0–100** — the same scale as `project_analysis_findings.confidence`
(`registry.py:866`), so evidence and published confidence need no conversion. Confidence is an integer
0–100 throughout this design; there is no float scale anywhere.

**`confidenceLevel` uses the existing `ConfidenceLevel` valid-value set — and we do *not* extend it.**
From `refdata/ConfidenceLevel.java`: `Unclassified(0)`, `Ad Hoc(1)`, `Transactional(2)`,
`Authoritative(3)`, `Derived(4)`, `Obsolete(5)`, `Other(99)`.

These are **not** a degree scale, which is why they initially look like a poor fit. They are a
*provenance* scale — and provenance is exactly the axis this feature needs. The stock descriptions
land on our cases almost verbatim:

| Value | Egeria's own description | Our use |
|---|---|---|
| `Derived` | "derived from other data through an analytical process" | **the default for everything this feature emits** |
| `Authoritative` | "comes from an authoritative source; the best set of values" | human-curated **and** declared sources (§5.1) — genuinely the same epistemic status |
| `Ad Hoc` | "comes from an ad hoc process" | heuristic and LLM-derived claims |
| `Obsolete` | "comes from an obsolete source and must no longer be used" | **stale overlay entries** (§7.2) — a case that otherwise had no typed home |
| `Unclassified` | "no assessment of the confidence level" | not yet assessed |
| `Transactional` | narrow-scope transactional source | no natural use here; leaving an enum value unused is not a problem |

**Consequence: §5.4's `derivation` field is redundant and is removed.** It was a local reinvention of
`confidenceLevel`. That frees `source` to carry something more useful — the analyzer/detector id — and
leaves `steward` for who curated.

**Q12 therefore dissolves.** No level set to author, no upstream type change, and Phase 2 loses a
prerequisite.

**What it still does not answer** is the *evidence* half of Q4 — locations and excerpts have no home
here, which is why §5.4 keeps them RE-side.

### 3.3c Three orthogonal axes, not one

Worth stating explicitly because they are easy to conflate, and because all three are typed and
queryable — none needs `jsonProperties`:

| Axis | Carrier | Question |
|---|---|---|
| **Provenance** | `confidenceLevel` (`ConfidenceLevel`) | where did this claim come from? |
| **Degree** | `confidence` (int 0–100) | how sure are we? |
| **Workflow** | `ContentStatus` (§3.4) | has a human signed off? |

They correlate but are not substitutes. The case that proves it: a component can be `Active` — approved
and in use — while still `Derived`, meaning accepted by a curator but never independently re-verified
against the code. Collapsing the axes would lose that, and it is precisely the state most of a large
estate will sit in.

The second non-redundant case is `Obsolete` versus `ContentStatus.Deprecated`: *Deprecated* is a
decision ("stop using this"), *Obsolete* is a fact about the source ("this no longer reflects
reality"). A stale overlay entry pointing at deleted code is Obsolete, not Deprecated.

**A fourth axis is missing, and none of the three above can stand in for it (added 2026-08-30).**
Provenance, Degree and Workflow all answer some version of "is this claim correct, and has a human
signed off." None answer "is this claim worth a curator's attention *right now*" — the goal is not
architecture recovery for its own sake but recovery of *useful* artifacts, and usefulness is not
static: at one extreme everything recovered is worth surfacing, at the other almost nothing is.
Folding that into `Degree`/confidence conflates two different questions — a component can be
detected with high confidence and still be uninteresting (a leaf utility module), and a low-
confidence guess can be exactly what a curator needs to see. Needs its own field, not a reuse of
`confidence`. See `Backlog.md`'s "separate correct from useful" entry — not designed here, flagged
here because §7 is where it would eventually attach.

### 3.4 `ContentStatus` is the derived/validated axis — confirmed

From `.../enums/ContentStatus.java`:

`Draft(0)` "content is incomplete" · `Prepared(1)` "ready for review" · `Proposed(2)` "in review" ·
`Approved(3)` · `Rejected(4)` · `Active(5)` "approved and in use" · `Deprecated(6)` · `Other(99)`.

This is a proper review lifecycle, not a binary flag, and it already has the states this use case
needs.

**Confirmed: `ContentStatus` is settable on any authored `Referenceable`, including
`SolutionComponent`.** Setting it is an ordinary update with the status as a key in the JSON payload —
no special mechanism. `update_solution_blueprint_status` in pyegeria is most likely a legacy artifact
predating the move of `contentStatus` into the body; do not build against it as if it were the only
path, and do not infer from its existence that status is blueprint-scoped.

This resolves the granularity question: **per-component promotion works**, so the curation model in §7
stands as designed.

**Decision: use `ContentStatus`, do not invent a classification.** The `Incomplete` classification
(0790) means *partial*, not *unverified* — wrong semantics for our case, though possibly right for a
component we know we failed to fully resolve.

### 3.5 Versioning — `versionIdentifier` is the mechanism, not instance versions

Egeria has **two** version concepts, and the distinction matters:

1. **Instance version** — auto-incremented by the repository on every update, queryable via
   `asOfTime` / `getMetadataElementHistory` / `ElementVersions`. An audit trail of edits.
2. **`versionIdentifier`** — a user-controlled string property on `Referenceable`
   (`OpenMetadataProperty.java:244`, example value `V1.0`). Its declared purpose: *"to allow different
   versions of the same resource to appear in the catalog as separate assets."*

**We want `versionIdentifier`.** The semantics are materially different from what §8 originally
assumed: distinct versions are **separate catalog elements**, not successive states of one element.
That is the right model here — a blueprint for release 1.2 and a blueprint for release 2.0 are
genuinely different designs that should be independently retrievable and comparable, not a before/after
of one mutable object.

Instance versioning remains useful as the secondary audit trail (who corrected what, when, within a
version), but it is not the drift mechanism. See the revised §8.

### 3.6 pyegeria write path exists — and `ImplementedBy` is resolved

`pyegeria/omvs/solution_architect.py` provides `create_solution_blueprint`,
`create_solution_component`, `link_subcomponent`, `link_solution_linking_wire`,
`create_info_supply_chain`, `link_solution_design`, `link_component_to_actor`,
`update_solution_blueprint_status`, `get_solution_component_implementations`.

**`ImplementedBy` — resolved.** It is not on the solution-architect client; it is
`GovernanceOfficer.link_design_to_implementation(design_desc_guid, implementation_guid, body)`
(`pyegeria/omvs/governance_officer.py:2943`). The body carries `ImplementedByProperties` with:

`designStep`, `role`, `transformation`, `description`, `iscQualifiedName`, plus
`effectiveFrom`/`effectiveTo`.

Two consequences worth noting:

- `role` and `designStep` give us somewhere typed to record *how* a code artifact implements a
  component (e.g. `role: "entry-point"` vs `role: "supporting-module"`) — better than another
  `jsonProperties` blob.
- `iscQualifiedName` appears **here too**, alongside its presence on `SolutionLinkingWire`. ISC
  attribution therefore has two anchor points, both of which are labelling passes over structures we
  already derive. Reinforces §9.

**Status setting — resolved (§3.4).** `contentStatus` is an ordinary body key on any authored
`Referenceable`, so per-component promotion is available. No blocker for Phase 3.

**`SolutionComponentProperties` carries two fields worth planning around**, per the documented update
body:

- `versionIdentifier` — present directly on the component, not only the blueprint. Confirms §8.2's
  scheme is expressible.
- `additionalProperties` (map) — the interim carrier for anything not yet typed, and the documented
  extension point for §3.7.
- Also `plannedDeployedImplementationType` — a design-side statement of the intended implementation
  type. Our detectors infer the *actual* one, so this is a natural home for it, and the
  planned-vs-actual gap is itself a drift signal worth surfacing later.

### 3.7 `CodeAnalysis` — a real classification, documented but not implemented

Correcting the earlier reading. The `0780-Code-Analysis.md` page is a stub; the model lives entirely in
`0780-Code-Analysis.svg`. Parsing that SVG (from `dwolfson/egeria-docs`) gives the actual definition:

**`CodeAnalysis` is a «classification» applied to `Referenceable`**, with properties:

| Property | Type | Note |
|---|---|---|
| `firstRun`, `lastRun` | date | when analysis ran — gives derived metadata its own freshness signal |
| `analysisType` | string | which analysis produced this |
| `description` | string | |
| `lineCount`, `lineCountWithoutComments` | long | |
| `simpleConditionCount`, `complexConditionCount` | long | branching complexity |
| `setVariableCount` | long | |
| `simpleCalculation`, `complexCalculation` | long | |
| `dataReadCount`, `dataCreateCount`, `dataUpdateCount`, `dataDeleteCount` | long | **CRUD interaction profile** |
| `dataChecksCount` | long | validation density |
| `additionalProperties` | map&lt;string,string&gt; | the documented extension point |

**However: it is not implemented in the framework.** Case-insensitive grep for `codeanalysis` across
the entire Egeria checkout returns zero hits — no type definition, no properties class, nothing in the
type archives. `OpenMetadataWikiPages.MODEL_0780_CODE_ANALYSIS` is declared (`:813`) but referenced by
no type.

So the model is designed and published in the docs, but a client cannot apply the classification
today. Two observations:

- The property set is clearly shaped by legacy/COBOL-style program analysis — condition counts,
  calculation counts, CRUD counts. That turns out to suit our use case well: `dataReadCount` /
  `dataCreateCount` / `dataUpdateCount` / `dataDeleteCount` on a **SolutionComponent** is a compact,
  typed statement of that component's data interaction profile, which is exactly what governance
  wants to know and exactly what static analysis can produce.
- Because it attaches to `Referenceable`, it can go on a `SolutionComponent` directly — no
  intermediate type needed.

**Superseded — see §6.1.** `CodeAnalysis` will be implemented upstream, but as an **Annotation
subtype rather than a classification** (more flexible; links to the right artifact through existing
annotation relationships). The attribute set above is not being carried forward as-is — §6.2 proposes
a replacement first pass, and §6.3 records what is deliberately dropped and why.

The property table above is retained only as the record of what 0780 documented before this round.

---

## 4. Architecture of the solution

```
  repo
    │
    ├─ [A] Deterministic detectors ──┐
    │      deployment artifacts,      │
    │      entry points, configs      │
    │                                 ├──► Architecture IR ──► [C] Curation overlay ──► [D] Egeria projection
    ├─ [B] Distillation (heuristic    │      (normalised JSON)      (human decisions,        (Area 7 + ImplementedBy,
    │      + LLM), boundary naming  ──┘                              replayed)                ContentStatus=Draft)
    │
    └─ existing RE analyses ─────────────► re-aggregated per component (§6)
```

### 4.1 Four perspectives, not one architecture

**The most important structural revision in this document.** An earlier draft treated "the
architecture" as one thing recovered at one granularity. It is four different views of the same repo
information, and they are not interchangeable — they have different sources, different vocabularies,
different Egeria homes, and radically different availability.

| Perspective | Question it answers | Derived from | Egeria home | Vocabulary | Available |
|---|---|---|---|---|---|
| **Physical** | what is on disk | file tree, manifests, imports | Area 0/4 | 0280 Software Development Assets (`SourceCodeFile`, `ScriptFile`) | **always** |
| **Deployment specification** | what the repo *says* should run | Dockerfile, compose, entry points | **Area 7** + `plannedDeployedImplementationType` | Egeria technology types (`Apache Kafka Server`, `PostgreSQL Database Server`) | only where artifacts exist |
| **Logical** | what the software *is* | cohesion, naming, docs, judgement | **Area 7** | `SolutionComponentType` (13, closed) | needs inference or a human |
| **Dev / DevOps** | how it is built, tested, released | CI config, build files, test trees | Area 0 0280 + `SourceControlLibrary`; pipelines have **no good type** | weakest of the four | usually |

`ImplementedBy` (0737) remains the bridge, now specifically between **Logical** and the other three.

**Why this is load-bearing and not taxonomy for its own sake.** The Phase 0 spike scored **16/16** on
`egeria-workspaces` and **1 of ~10** on `trellis`, which reads as "works on one repo, fails on the
other". It is neither. The workspaces ground truth is a *deployment* architecture (container names,
services); the trellis ground truth is a *logical* one (agents, surveyors, observability, core). The
detectors read deployment and physical artifacts. **A deployment-perspective detector was being scored
against a logical-perspective ground truth**, and the original exit criteria would have recorded a
measurement error as a premise failure.

The same effect shows up in the type vocabularies. Asked to classify RE's front end, the maintainer
picked `Application` — which is not one of the 13 `SolutionComponentType` values but *is* a
`SoftwareCapability` subtype. That is not a mistake; it is classifying in the deployment perspective
when the logical one was asked for. Four perspectives, three vocabularies, and no signposting.

**Related work (added 2026-08-30, from a literature check against this design):** Murphy, Notkin &
Sullivan's software reflexion models (IEEE TSE 2001, building on their 1995 SIGSOFT paper) establish
the general technique this section is an instance of — an extracted model and a hypothesized
high-level model are kept as two artifacts related by a computed correspondence, never collapsed
into one. But reflexion, as published, is computed against **one** hypothesized model at a time; the
literature does not address running it once per perspective and reconciling the results. **Open
question this design inherits and does not answer:** can a component converge under Deployment while
diverging under Logical, and if so, is that one finding or two? See `Backlog.md`'s "borrow reflexion
models' three-way vocabulary" entry.

### 4.1a Specification, not deployment — the correction that renames a perspective

An earlier draft called the second perspective **Deployment** and mapped it to Area 0's
`SoftwareServer`, `DeployedSoftwareComponent` and `DeployedOn`. **That was wrong, and wrong in a way
that would have put fiction into the catalog.**

A repository contains no deployed container. It contains a *description* of a container — a compose
service definition and a Dockerfile — and the compose file that would start one. `quickstart-pyegeria-web`
is not a running thing this analysis observed; it is a name the repo declares for a container that
may never have been started anywhere.

Area 0's `ITInfrastructure` hierarchy is explicitly *"hardware and base software that supports an IT
system"* — actual infrastructure. Writing `SoftwareServer` from static repo analysis asserts that a
server exists. **`ContentStatus = Draft` does not repair this**: Draft means "content is incomplete",
not "this element may not correspond to anything real". A governance catalog that cannot distinguish
a running server from a YAML file describing one is worse than one that stays quiet.

**Egeria already models the distinction.** From `OpenMetadataProperty.java`:

| Property | Meaning | Where |
|---|---|---|
| `deployedImplementationType` (:249) | *"Name of a particular type of technology"* — e.g. `PostgreSQL Database Server`. Asserts what a real asset **is**. | actual assets / infrastructure |
| **`plannedDeployedImplementationType`** (:2504) | *"The type of software component that is **likely** to serve as an implementation for this solution component."* | **`SolutionComponent`** — Area 7 |

That second property is precisely this feature's output: a design element that names the technology
*likely* to implement it, without claiming an instance exists. Note Egeria's own wording — "likely".

**Revised mapping.** What a compose file yields is:

- a **`SolutionComponent`** (Area 7 design) — safe, asserts no infrastructure;
- carrying **`plannedDeployedImplementationType`** for the technology (`Apache Kafka Server`, …);
- with `solutionComponentType` from the closed 13;
- evidenced by **real Area 0 assets** — the compose file and Dockerfile genuinely exist and are
  properly catalogued as 0280 `YAMLFile` / `BuildInstructionFile`.

**Area 0's deployment types stay out of scope for this feature entirely.** They are populated by an
integration connector surveying a live environment, which is a different activity with a different
evidence base. If RE ever wants them, it must observe a running system, not read a repo.

Consequence for §4.2's vocabulary table: the `SoftwareCapability` subtypes (`Application`,
`EventBroker`, …) describe *deployed* capabilities and are therefore also unsafe as entity types
here. Their content survives as the technology-type **string** in
`plannedDeployedImplementationType` — which is the same vocabulary RE already consumes via
`find_technology_types` and `technology_type_processes.yaml`, so this is familiar ground rather than
a new dependency.

### 4.1b The perspectives must be enforced below the model, not only in it

§4.1 and §4.1a describe the perspectives as a **modelling** concept — which vocabulary a component
gets, which Egeria area it lands in. Nothing enforced them below that, and **three separate bugs
lived in exactly that gap.** All three were silent, and all three were invisible to unit tests for
the same reason: the objects were constructed correctly and only the plumbing was wrong.

| what served two purposes | consequence |
|---|---|
| `scope_locator` — path prefix **and** identity | 58 distinct components collapsed onto 10 keys; readers kept one container per compose file |
| import source roots — one global order for **two copies** of one package | 156 of 170 edges resolved into the wrong copy |
| one directory — the **code** view and the **change** view | coupling scanned an empty tree, proposed zero components on every repo |

The third is worth stating precisely, because it looks like a configuration typo and is not. Two
repo resources both yield "a directory" and are not interchangeable:

- **`zipball_root`** — files on disk, **no `.git`**
- **`git_clone_root`** — `--filter=blob:none --no-checkout`, so its root contains **only `.git`**

`--no-checkout` is *correct* for the history view: without it a treeless clone fetches every blob
in HEAD and defeats the filter. It became a bug the moment a second consumer with a different view
was pointed at the same artifact. Both satisfied "a path exists". Neither the type system nor any
test could tell them apart, **because the difference had never been written down.**

**The mechanism.** A provider declares what it supplies, a step declares what it reads, and a
mismatch fails at import:

```python
"git_clone_root": ResourceProvider(..., provides=frozenset({VIEW_HISTORY}))

"repo_arch_coupling": StepInfo(...,
    requires_resources={"zipball_root": "source_path", "git_clone_root": "history_path"},
    requires_views={"zipball_root": VIEW_SOURCE, "git_clone_root": VIEW_HISTORY})
```

Re-introducing the original defect now raises at import:

> `repo_arch_coupling: reads 'source' from 'git_clone_root', which provides ['history']`

**Failing at import rather than warning is deliberate.** A step wired to a resource that cannot
give it what it reads does not degrade — it silently produces nothing, which is indistinguishable
from *"this repo has no components"*. That is exactly how the defect survived a 1576-test suite
and a live run, and was caught only by checking a number against something already known.

A step that uses a resource without declaring what it reads is a failure too, not a default —
an undeclared assumption is the thing this exists to catch. `trellis-microflow`'s
`ResourceProvider.provides` carries opaque labels and assigns them no meaning; the vocabulary
belongs to the app.

**The general principle, and the one to carry into later phases:** a perspective distinction that
exists only in a design document will be violated by the plumbing, silently, and the violation
will look like an empty result rather than an error. Where two things are genuinely different
views of one system, the *pipes* have to know it — not just the model they carry.

Two of the three bugs above would have been import-time errors under this rule. The `scope_locator`
one would not: that is a key-semantics problem rather than a resource one, and it remains
unguarded (see §6.0).

### 4.1c The fourth: `scope_locator` carries two meanings, and one of them means "incomplete"

§4.1b closed the resource-capability gap and named the one it could not close. This is that one,
found by looking for it.

`scope_locator` in `project_analysis_findings` means two different things **for the same analysis
kind**:

| meaning | written by | example |
|---|---|---|
| **run scope** — this run was narrowed to a subtree (D5/D6) | any `accepts_scope_locator` step | `packages/foo` |
| **component identity** — this component *is* that subtree (§6.0) | architecture recovery | `packages/foo` |

They collide exactly. Run `repo_arch_detect` scoped to `packages/foo` and the component found
there keys on the identical string.

**The collision is not the damage; the missing distinction is.** A scoped run sees only part of the
repo, so its component set is *necessarily incomplete* — and nothing recorded that. Verified: zero
references to run scope anywhere in the persist path. A partial architecture was written with rows
indistinguishable from a complete one, so any reader merging them presents a fragment as the whole
thing, silently.

A second instance surfaced while testing the first. `query_findings(slug, kind, scope_locator="")`
defaults to `""` meaning *whole-resource* — the **run-scope** reading. A component row never keys on
`""`; it keys on its own path. So the default query returns nothing for architecture recovery, for
a reason that looks like "no data" and is actually "wrong question".

**Fix, and its limit.** Every row now carries `run_scope` and `partial` in `detail_json` — no schema
change, and it restores a question no consumer could previously ask: *is this result complete?*

Unlike §4.1b this **cannot** be an import-time error. Resource capability is a wiring property, so a
mismatch is checkable before anything runs. This is a *runtime value* ambiguity: the same column
legitimately holds both meanings and only the writer knows which. The honest fix is therefore to
make the distinction explicit **in the data**, not to enforce it structurally — and to say so rather
than imply the guard is as strong as §4.1b's.

**What the four have in common**, now that all of them are found: in every case an object was
constructed correctly and only a *key, path, or capability* was wrong; in every case the failure
mode was an empty or merged result rather than an exception; and in every case it was caught by
asking the data a question it could not answer, never by reading the code. A design that names
distinctions the plumbing does not carry will lose them — quietly, and in whichever layer nobody
thought to write them down.

### 4.1d Language is a boundary some signals cross and others cannot

Three findings turned out to be one constraint, and it is not "we need more extractors".

| finding | symptom |
|---|---|
| **54** | two-thirds of Java edges are wildcard imports — `import a.b.*` means *might use*, so cohesion over-approximates |
| **57** | Rust has no extractor, so coupling saw nothing and said nothing until `unverified` was wired |
| `web/static` | JavaScript with no Python imports, so cohesion cannot see it belonging with `web/routes` — yet a human knows both are the web tier |

**The common cause: an import edge cannot cross a language.** That is not a gap in our extractors,
it is what an import *is*. `index.html` will never import `projects.py`. So a component whose parts
are written in different languages has a seam that import cohesion is **structurally incapable** of
seeing — and adding a JavaScript extractor would not help, because the edge does not exist in either
language's syntax.

This is exactly where the maintainer's `web application` parent sits (§8.2a of
`trellis-revised.md`): one component, two independently substitutable sub-components, in two
languages, joined by nothing an importer can observe.

**Co-change is language-agnostic, and measurably sees the seam.** It operates on commits, not
syntax. Measured on trellis across the `web/routes` (Python) ↔ `web/static` (JS/HTML/CSS) boundary:

| | pairs |
|---|---|
| within-zone co-change | 9 |
| **cross-language co-change** | **18** |

The seam imports cannot see is **twice as visible** to co-change as the coupling within either
side, and the pairs are meaningful rather than incidental — `projects.py ↔ index.html`,
`feedback.py ↔ admin-feedback.html`, `discovery.py ↔ index.html`. Backend route and the page it
serves, changing together.

**And we compute it already without using it.** `coupling.propose()` takes `import_edges` only.
Co-change is calculated, attached as a supporting metric, and never reaches shape classification —
blind in exactly the place where it is the only signal that works.

### The position

**Use imports for within-language cohesion and co-change for cross-language seams.** Not one
replacing the other: they answer different questions, and each is weak where the other is strong.

- **Imports** — precise, directional, per-symbol; supports fan-in/fan-out dispersion (§4.1's
  connective shapes) and therefore the library/orchestrator distinction. Cannot cross a language.
- **Co-change** — crosses any boundary, needs no parser, works on Rust today. Non-directional,
  noisier, needs history, and sensitive to commit hygiene.

**How much this matters depends on the repo, and should be measured rather than assumed.** Extractor
coverage of first-party code files:

| repo | covered | uncovered |
|---|---|---|
| `egeria` | 99% | .sql, .sh |
| `trellis` | 96% | .sh, .js, .html |
| **`egeria-workspaces`** | **65%** | **.html 57, .sh 28, .js 7** |

A single-language repo barely notices. A polyglot one is a third invisible — and it is precisely
the polyglot repos where a component most often spans languages.

### Honest limits

- **n=1 seam.** The 18-vs-9 result is one boundary in one repo. A repo whose commits are
  "update everything" will show co-change everywhere and discriminate nothing.
- **Co-change cannot type a component.** It says "these belong together", never "this is a library"
  — that needs direction, which only imports supply. So it can find a seam it cannot characterise.
- **Not implemented.** `propose()` would need co-change edges alongside import edges, with the two
  weighted differently rather than pooled — pooling would let a noisy signal dilute a precise one.

### 4.2 Do not merge the vocabularies — map them

The obvious reaction is to reconcile `SolutionComponentType` with the `SoftwareCapability` subtypes.
**Resist it.** They differ because they describe different things: `Application` is a deployed
capability and `Software Service` is a designed component, and they are one system seen from two
layers rather than two names for one concept. `ImplementedBy` is precisely the relationship that joins
them, and collapsing the lists would destroy the distinction it encodes.

Nor does `SolutionComponentType` need extending for the cases seen so far — `User Interface` covers a
front end and a terminal UI, `Console Command` covers a CLI. §3.1 calls the closed 13-value vocabulary
"the single most important fact in the design" because it keeps classification tractable; extending it
is cheap and therefore dangerous. Extend only for a case that survives the mapping.

**What is needed instead:** every recorded type states *which vocabulary it came from*, and the
projection maps between them.

**This is "map, never merge," and the name has a quarter-century of prior art.** Murphy, Notkin &
Sullivan's software reflexion models (IEEE TSE 2001) apply exactly this discipline to the narrower
case of one extracted model against one human model: disagreement is computed and displayed, never
resolved by rewriting either side. On the data-curation side, CleanGraph (arXiv:2405.03932) attaches
confidence/source/extractor metadata per edge in a knowledge graph and routes low-confidence matches
to a human queue rather than auto-merging — the same shape applied to entity resolution instead of
architecture. Neither source gives a name to the curator's verdict itself; reflexion's own vocabulary
for how two models relate — **convergence** (they agree), **divergence** (they disagree),
**absence** (one names something the other doesn't) — is a candidate for §7.1's curator-action
vocabulary. See `Backlog.md`.

### 4.3 Successive refinement — perspectives map onto the funnel

The four are not derived at once. Each stage's output is what the next one draws on, and the ordering
follows availability and cost rather than importance:

| Stage | Perspective | Character |
|---|---|---|
| **Scouting** | — | one presence check: does this repo have a deployment architecture at all? Routes everything downstream. |
| **Discovery** | **Physical** | deterministic, always available; produces the path-prefix map §6.0 depends on |
| **Analysis** | **Deployment** + **Dev** | deterministic where artifacts exist; this is what the Phase 0 detectors already do well |
| **Assessment / Curate** | **Logical** | needs distillation and a human, seeded by the cheap perspectives rather than started cold |

This lands on existing RE machinery rather than new infrastructure: `resource_questions.csv` →
`question_catalog.yaml` already carries `stage` and `answering_mechanism` across 41 questions, with
"Code Analysis" already among the mechanisms. Architecture recovery becomes **new question rows in an
existing catalog**, tagged by perspective and stage.

It also dissolves the "how far down should the partition go?" question, which has no general answer
because it was three questions wearing one coat:

- **Physical** — depth is given by the artifact. A package is a package, a module is a module. No judgement.
- **Deployment** — depth is given by the deployable unit. No judgement.
- **Dev** — depth is given by the pipeline and test layout. Little judgement.
- **Logical** — depth **is** the judgement, and it is the only place it is.

Which is exactly why the logical perspective is the one that needs a human or an LLM, and why the
other three must not wait for it.

### 4.4 The Dev/DevOps perspective earns its place

Weakest Egeria support of the four, and still worth having, for two reasons that have nothing to do
with completeness.

**It gives a home to the files the other perspectives discard.** Docs, tests and CI config are
`unassigned_ok` from every other view — but they are not unassigned, they are this perspective's
content. A repo where a third of the files are "unowned" is not well modelled; it is modelled from
only three of four angles.

**RE already collects this data and has nowhere to put it.** `repo_ci_quality`, `repo_conventions`
(build automation, deployment evidence), and §6.2's `testFileCount` all exist and land nowhere
architectural — the same orphaned-analysis problem §6 exists to solve, in a fourth instance.

It passes the test for being a perspective rather than a cross-cutting concern: it partitions the same
repo *differently*, cutting across components, and answers questions with real governance value —
which components have no tests, what the release path is, what is built but never deployed.

**Known gap, stated rather than glossed:** Egeria's 0280 Software Development Assets are *file-level*
(`SourceCodeFile`, `BuildInstructionFile`, `ScriptFile`, `PropertiesFile`, `YAMLFile`), not
architecture-level, and there is **no pipeline type** — `GovernanceActionProcess` is the nearest fit
and is not a natural one. This perspective may be the first genuine case for a new type, and that case
should be made from Phase 0 evidence rather than assumed now.

---

### 4.5 Layer model (revised)

| Layer | Egeria area | Source | Confidence |
|---|---|---|---|
| **Implementation inventory** — packages, dependencies, licences | Area 0 / 4 | deterministic tools (Syft, existing `dependency_parser.py`) | high, factual |
| **Deployment** — servers, capabilities, containers | Area 0 (`SoftwareServer`, `DeployedSoftwareComponent`, `DeployedOn`) | deployment artifacts | high where present, absent otherwise |
| **Design** — blueprint, components, ports, wires | **Area 7** | detectors + distillation | derived, needs curation |
| **The bridge** — `ImplementedBy` | 0737 | join between design and the rest | derived |

An earlier draft folded deployment into implementation inventory. That was wrong: deployment has its
own Egeria types and a completely different availability profile — total on `egeria-workspaces`,
entirely absent on `trellis`.

---

## 5. Extraction design

### 5.1 Detectors first, call graphs last

**Deliberate departure from the tool list in the source analysis.** Joern and SCIP are heavy,
language-limited, and answer "what calls what" — which is *not* the boundary question. Component
boundaries and runtime shape are declared in deployment and configuration artifacts, which are cheap,
deterministic, and multi-language for free.

| Signal | Files | Yields |
|---|---|---|
| Container definitions | `Dockerfile*`, `*.containerfile` | `Long Running Daemon` / `Console Command`, entry command, exposed ports |
| Compose / orchestration | `docker-compose*.y*ml`, `k8s/*.y*ml`, Helm charts | component set, inter-service wires, protocols, `Data Storage` components |
| Service units | `*.service`, supervisord, Procfile | `Long Running Daemon` |
| Package entry points | `[project.scripts]`, `setup.py` console_scripts, `package.json` bin/scripts, `Main-Class` | `Console Command` |
| Web framework markers | FastAPI/Flask/Spring/Express route decorators & registrations | `Software Service`, ports with direction `Input-Output` |
| Client libraries | psycopg/SQLAlchemy, kafka clients, boto3, requests to known hosts | wires, `protocol`, `integrationStyle`, direction `Output-Input` |
| Scheduler / worker | Celery, APScheduler, cron, Prefect/Airflow DAGs | `Automated Action`, `Multi-Step Process`, `frequency` |
| Front-end build | `index.html`, SPA bundlers, static handlers | `User Interface` |
| Library shape | published package with no entry point | `Software Library` |
| Monorepo layout | workspace members, `uv`/pnpm/Gradle multi-module | candidate component partition |
| **Variant / near-duplicate** | per-file content hashes across candidate components | variant relationships, accidental-copy RFAs (§8.2a) |

RE already has tree-sitter (`ingestion/ast_chunker.py`) and dependency parsing
(`ingestion/dependency_parser.py`) to build on. Add call-graph tooling **only if** boundary detection
proves insufficient in Phase 1 — do not commit to it up front.

The variant row is cheap — hash every file, then compute directional containment between candidate
components — and it catches something no structural detector can see: two components that look unrelated
by path and manifest while being near-copies of each other. §8.2a has the worked example and the
modelling rules.

**Detection engine: `ast-grep`.** The code-marker rows above (web frameworks, client libraries,
scheduler/worker, entry points) should not be hand-written Python regex. `ast-grep` is a single Rust
binary running tree-sitter across ~20 languages, with rules expressed as YAML structural patterns.
Writing the detector table as ast-grep rule files buys three things: multi-language coverage for free,
detectors that are **data rather than code** (reviewable, extensible, curatable without a release), and
a stable rule id per match that becomes the `detector` field in §5.4's evidence. The file-presence rows
(Dockerfile, compose, k8s, service units) stay as ordinary parsers — use `dockerfile-parse` and PyYAML
rather than regex, and note that Trivy already ships parsers for Dockerfile / compose / k8s / Helm /
Terraform if piggybacking beats writing them.

**Declared architecture outranks inferred architecture.** Before any inference runs, check for sources
where the architecture is *stated* rather than derived:

| Source | Yields | Confidence |
|---|---|---|
| `catalog-info.yaml` (Backstage) — RE's `repo_conventions` step already looks for it | component identity, type, owner, dependencies | highest — human-authored |
| OpenAPI / AsyncAPI specs | ports, directions, protocols, `dataExchanged` | high |
| Compose / k8s service names and labels | component names, wires | high |
| `pyproject.toml` / `package.json` / Gradle workspace members | component partition and **stable identity** (§8.2) | high |

Where these exist they short-circuit distillation entirely — there is nothing to infer and nothing for
the LLM to name. Treat their absence, not their presence, as the interesting case.

### 5.2 Distillation — the noise reducer

Detectors produce candidates; distillation decides the component set. Responsibilities:

0. **Read the repo's own architecture and deployment documentation** (§8.2c). Prose docs stating the
   component set, the deployment tiers, or which divergences are intentional are detector-invisible but
   directly readable here, and they outrank inference. This is not invention — it is reading a human's
   statement about their own architecture, which is the highest-confidence evidence available.
1. **Partition** the repo into components (cluster by directory, entry point, and deployment unit —
   the *artifact* sense of deployment unit, per §8.2's floor).
2. **Classify** each into the 13-value `SolutionComponentType` vocabulary.
3. **Name** each in human terms.
4. **Infer ports** and directions from interfaces served vs. consumed.
5. **Infer wires** between components, populating `protocol` / `integrationStyle` / `frequency` /
   `dataExchanged` / `oneWay`.
6. **Emit evidence** for every claim (see §5.4).

**Step 0, added after Phase 0 planning: exclusion.** Before any of the above, filter the file set —
`.gitignore`-aware, plus an explicit vendor denylist (`node_modules`, `.venv`, `site-packages`,
`vendor/`, `target/`, `dist/`, `build/`, `__pycache__`).

This is not tidiness. Vendored dependency trees are **committed to git in real repos** — in
`egeria-workspaces`, 1697 of 1703 tracked `.js` files are `node_modules`, so they are present in every
zipball and clone. Each vendored package carries a manifest declaring a package name, which is
**identity precedence 1 in §8.2**. A detector applying that rule faithfully to an unfiltered tree emits
hundreds of spurious components, each with a real name, a real manifest and real evidence, and every
downstream number is then wrong.

The distinction that matters: this noise is **structural and mechanical**, not low-confidence. No amount
of distillation or LLM adjudication fixes it, because each spurious component looks entirely legitimate
in isolation. It must be excluded *before* detection, never filtered after. The rest of §5.2 assumes
noise means "weak candidates"; this is a different and larger problem.

Heuristics own steps 1, 4, 5; the LLM owns 2 and 3 and adjudicates ambiguous partitions. **Rule: the
LLM never invents a component with no detector evidence behind it.** Its job is naming, classifying,
and merging — not discovery. This keeps hallucinated architecture out of the catalog.

### 5.3 The Architecture IR

A normalised JSON intermediate representation at roughly C4 container/component level, produced and
stored **before** any Egeria write. Everything downstream — projection, curation, drift — reads the IR.

Rationale: the IR is diffable, testable without an Egeria server, and reviewable by a human before it
becomes metadata. It also means re-derivation and re-publication are separable operations.

### 5.4 Evidence and confidence are first-class

Every component, port and wire carries an evidence record justifying each individual claim about it.
A claim is one assertion — "this is a `Software Service`", "this wire uses `HTTPS`" — not a whole
component.

```json
{
  "subject":   {"kind": "component|port|wire", "slug": "resource-explorer.web"},
  "assertion": "solutionComponentType=Software Service",
  "detector":  "ast-grep:fastapi-app-construction",
  "locations": [{"path": "resource_explorer/web/app.py", "line": 42,
                 "excerpt": "app = FastAPI(title=...)"}],
  "confidence": 90,
  "confidenceLevel": "Derived"
}
```

`confidenceLevel` uses Egeria's stock `ConfidenceLevel` values (§3.3b) rather than an RE-local
`derivation` vocabulary — the two were the same axis, so there is one field, and it publishes without
translation.

Curation is impossible without showing *why* a component was proposed, and per the current-state doc,
RE's habit of stuffing untyped detail into `jsonProperties` makes it unqueryable — evidence must not go
the same way.

**Storage — RE-side, in the existing generic findings table.** `project_analysis_findings`
(`registry.py:866`) already carries exactly this shape and needs no schema change:

| Column | Carries |
|---|---|
| `kind` | `architecture_recovery` |
| `check_name` | the assertion |
| `label` | `accept` / `uncertain` / `conflict` |
| `confidence` | INTEGER 0–100 — **the same scale as Egeria's `ConfidenceProperties.confidence`**, so no conversion |
| `scope_locator` | the component's path prefix — the join key to everything else (§6) |
| `detail_json` | the `locations` array, plus `detector` and `confidenceLevel` |

That the fit is exact is not a coincidence: the generic findings table was built for uniformly-shaped
analysis output, and evidence is analysis output. Reusing it also means evidence is immediately visible
to the annotation-Q&A agent (§6.5) with no extra tooling, and lives in the same store as the §7.2
curation overlay — which the overlay needs anyway.

**What reaches Egeria — the reasoning, not the receipts.** Base `AnnotationProperties` already provides
typed fields for the justification:

- `expression` — the detector rule id that fired
- `explanation` — human-readable why
- `analysisStep` — which pass produced it
- `confidence` — the same 0–100 integer

and on the `Confidence` classification itself: `confidenceLevel` (provenance), `source` (the analyzer
id), `steward` (who curated).

Locations and excerpts stay RE-side. A curator or agent that wants the receipts follows `scope_locator`
back into RE. **Nothing goes into `jsonProperties`.** Q4 resolved on this basis (§11).


### 5.5 Validating the partition — three independent signals

Detectors *propose* a partition. Nothing above *checks* it, and a partition nobody checked is exactly
the kind of plausible-looking output that erodes trust. Score every proposed partition against two
signals the detectors structurally cannot see:

1. **Import coupling.** A partition whose components all import each other is wrong regardless of what
   the Dockerfiles say. Build the module import graph and measure cross-boundary edge density.

   **Correction (found while planning Phase 0):** an earlier draft named RE's
   `project_code_relationships` table as the source. It cannot serve — its schema
   (`registry.py:608`) is `relationship_type` / `source_name` / `target_name`, **name-to-name with no
   `file_path`**, and it holds `inherits_from` edges, not imports. Joining it against
   `project_code_symbols` (which does carry `file_path`) recovers path pairs, but yields an
   *inheritance* graph — a much weaker boundary signal than imports.

   **Extract imports with ast-grep instead.** Import statements are among the most trivially matchable
   constructs in any language, and ast-grep is already the detection engine (§5.1), so the marginal
   cost is near zero. Do *not* adopt `grimp`/`import-linter`: grimp resolves modules by importing them,
   so it needs the dependency environment installed rather than just a checkout — real operational cost
   for a graph we can extract statically. Per-language alternatives (`dependency-cruiser`, `jdeps`,
   `go list -deps`) remain available if the ast-grep graph proves too thin.

2. **Co-change coupling.** Files that always change together belong to one component even when the
   directory layout disagrees. It is the signal most likely to *contradict* the detectors usefully —
   directory structure records intent, co-change records reality.

   **Also corrected:** `project_commits` (`registry.py:548`) carries `sha` / `message` / author /
   `committed_at` and **no per-file change data**, so it cannot produce this either. The source is
   `git log --name-only` or `code-maat` over a real clone — which is why `git_clone_root` (§5.7 gap 2)
   is a prerequisite for this signal outside the Phase 0 spike, where local checkouts stand in.

**This gives Phase 0 a sharper exit criterion** than "recognisable to you": run all three — detector
partition, import coupling, co-change coupling — and ask whether they agree with each other and with a
**pre-registered** hand-written partition. See `docs/architecture-recovery-phase0-plan.md`, which makes
the criterion falsifiable by requiring the expected answer to be written down before the detectors run. Three independent signals converging is evidence the premise holds. Two agreeing
and one dissenting is a finding. All three disagreeing means §5.1 needs rethinking before anything is
built.

### 5.5a Documentation is a source, a *dated* source, and a signal — three separate uses

The Milvus ground-truth exercise (spike README findings 65–67) produced three lessons about project
documentation. They are not one lesson: each puts docs to a different use, and each lands in a
different part of this design.

**(a) Always look for documentation first — including documentation that is not in the repo.**

§5.2's step 0 already reads in-repo docs. The Milvus case shows that is not sufficient: the
authoritative logical architecture — four layers, named components, explicitly labelled *logical* —
is published at `milvus.io/docs/architecture_overview.md`, **not** in `milvus-io/milvus`. A survey
that only reads the repo would miss the single best description of the system it is trying to
recover. The repo does carry `docs/` (a `README.md`, `design-docs/`, `agent_guides/`, `archive/`),
but the front-door architecture page lives on the project's doc site.

**Measured across twelve repos** (spike finding 68 — `egeria`, `egeria-workspaces`, `milvus`,
`airflow`, `kubernetes`, `grafana`, `prometheus`, `kafka`, `elasticsearch`, `polars`, `ray`, `redis`):
**zero** have an `ARCHITECTURE.md` at root, **two** have architecture docs findable in-repo by name,
**eleven** declare a homepage, and **every one of the five checked has a separate, actively-maintained
docs repo** (`kubernetes/website`, `odpi/egeria-docs`, `milvus-io/milvus-docs`, `prometheus/docs`,
`redis/redis-doc`). Step 0 as written would find architecture in **2 of 12 cases**. The outward hop is
not an enhancement; without it the best available description of the system is missed almost every time.

So step 0 needs an outward hop: resolve the project's documentation site (from `README.md` links,
repository metadata, or the package manifest homepage) and treat the published architecture page as a
first-class input. This is a fetch, and it is the right kind — cheap, once, and it can save every
expensive tier downstream. Consistent with CLAUDE.md rule 17: zero-fetch is a proxy for cheap, and
here the measurement wins.

**(b) A prose architecture describes a *version*, and the version is recoverable from the repo.**

Documentation and code drift, and prose rarely carries a version stamp. But **every path a document
cites is dateable**: `GET /repos/{o}/{r}/commits?path={p}&per_page=1` returns the last commit that
touched it, and for a path that no longer exists that is effectively its deletion date.

Two bounds follow, each one cheap call per path:

- **Upper bound on vintage** — the newest of the now-dead paths a document cites. A description
  naming `internal/indexcoord` (last touched 2023-01), `internal/querynode` (2023-04),
  `internal/mq` (2024-06) and `internal/indexnode` (2025-03) cannot be describing anything after
  ~March 2025.
- **Lower bound on blind spot** — the churn of live paths it omits. The same description omitted
  `internal/streamingnode` and `internal/distributed/mixcoord`, both committed to within the last
  fortnight.

Together those dated the document as roughly seventeen months stale, from four API calls and without
reading a line of Go.

Because the published docs usually live in a **sibling git repo** rather than a rendered site
(finding 68 — `milvus-io/milvus-docs` carries `site/en/reference/architecture/`, eight markdown pages
under version control), a document can be dated **two independent ways**: by its own commit history,
and by the last-commit dates of the paths it cites. The two cross-check each other, and no heuristic
dating is needed.

This applies symmetrically. It is a check on a maintainer's doc, on an LLM's proposal, **and on our
own output** — a recovered blueprint that cites paths deleted two years ago is stale in exactly the
same measurable way, and §5.4's evidence records are the natural place to carry the dates.

**(c) Documentation health is itself an architectural signal — arguably a strong one.**

Whether a project documents its architecture, and whether that documentation is *current*, is
evidence about the project independent of anything the docs say. The gradient is roughly:

| observation | reading |
|---|---|
| architecture documented, docs churn tracks code churn | mature and maintained — the strongest state |
| documented, docs lag code by a long interval | back-level docs; the project has moved and the description has not |
| documented once, no longer touched | abandoned documentation — a health signal about the project, not just the doc |
| stale docs *archived* rather than left in place | deliberate curation; strictly stronger than simply having docs |
| no architecture documentation at all | either immature, or small enough not to need one — needs the maturity signals to disambiguate |

Milvus sits at the top of that table: `docs/` last touched 2026-08-21 against `internal/` at
2026-08-22 — a one-day lag — and a `docs/archive/` that is itself actively maintained.

Three consequences for this design:

1. **This is a Discovery-tier signal, not an Analysis one.** It reads commit dates over two path
   sets. It costs nothing and it gates the expensive tiers, which is exactly rule 17's test.
2. **It feeds triage, which we already know we need.** Spike finding 58's false positives were
   settled by a human reading a README that said the repo's intent was a tutorial. Doc health is the
   measurable half of the same judgement: *is there an architecture here worth recovering, and does
   the project believe there is?*
3. **It cannot be measured until (a) is done — the two are coupled, not independent.** The naive
   metric (commit recency of `docs/` against code) scores **Kubernetes at 1412 days of untouched
   documentation** against code touched two days ago. `kubernetes/kubernetes/docs/` in fact holds
   exactly two entries, `.gitignore` and `OWNERS`: it is a **tombstone**, and the real docs moved to
   `kubernetes/website`, pushed today. Measuring doc health without first resolving where the docs
   live returns the *opposite* of the truth on precisely the projects that most deserve a good answer.

   This is a proxy that quietly stopped encoding the thing it proxied for — the same failure shape as
   the name-matching scorer that outlived the identity rules. `docs/` mtime means "documentation is
   maintained" only while the documentation is still in `docs/`.

   **The tombstone is itself detectable, and is a positive signal.** A docs directory holding only
   `OWNERS`/`.gitignore`/README stubs indicates deliberate relocation — the same class of curation
   marker as Milvus's maintained `docs/archive/` or Egeria's `saved/`. Projects that abandon
   documentation leave it rotting in place; projects that move it leave a marker.

4. **Do not turn it into a score.** A marketing-maintained doc site can coexist with rotting
   in-repo docs, and a small, stable, mature library may document lightly on purpose. Report the
   observation and its dates as evidence (§5.4); let the confidence axes (§3.3c) and a human carry
   the interpretation. Recording "docs lag code by N days" is defensible; ranking projects by it is
   not.

**(d) The outward hop was built, and it measured near-zero on the case that motivated it.**
Added 2026-08-29. `doc_locations.py` resolves sibling repos and doc sites as (a) asks, and it works
— 13 of 46 gate-approved repos get a document located. But the lens built on top of it named **1 of
Egeria's 999 logical components**, from `odpi/egeria-docs`, and that one match is a directory called
`egeria` matching the term `egeria`. The document names `Common Services`, `OMAS`, `OMVS`; the
pipeline proposed Java package paths. Nothing joins, and better matching cannot make it join.

The diagnosis is a §4.1 violation this document did not anticipate: `coupling.propose()` asserts
`perspective="logical"` beside `identity.method="module-path"`, so a directory path and `OMAS` are
filed under the same word and the lens joins on it. The only genuinely logical source in the
pipeline is the one input forbidden from proposing anything.

Decision (Dan, 2026-08-29): **a documentation-derived component may exist without a
`scope_locator`** — docs become a source, bridged to code by `ImplementedBy` (§3.6, §4.1). The
consequences, the gate this needs (the existing `undetected_is_meaningful` licenses *reading*, not
*proposing*, and its denominator is circular), and why §5.5a(b)'s dating becomes a precondition
rather than an enhancement are in **`architecture-recovery-docs-as-source.md`**.

### 5.5b What the repo *is* — classification before analysis

**Maintainer direction, 2026-08-22.** Before asking *what is the architecture of this repo*, ask
**what does this repo represent**: a library, an application, middleware, a tutorial, a set of
samples, documentation, a tooling repo — or a *family* of repos playing different roles.

The reason is not taxonomy for its own sake. **The classification determines which analyses are
relevant and which questions are worth asking.** Recovering a solution blueprint from a tutorial
repository is not a weak result; it is the wrong question. A samples repo has no architecture to
recover, and reporting one is a false positive no confidence score can rescue. Middleware and an
application have different port/wire expectations. A documentation repo should be answering "is it
current, and does it match the code it documents" (§5.5a) rather than "what are its components".

This generalises three things already established rather than adding a new idea:

- **Spike finding 58/60** — the `workshops` false positives were settled by a human reading a README
  that said the repo's *intent* was a tutorial. That is exactly this classification, applied by hand,
  once.
- **§5.5a(c) doc health** — already framed as "the measurable half of the triage judgement finding 58
  needed a human for". Repo classification is the other half of the same triage.
- **Rule 17's funnel** — Discovery exists to decide whether the expensive tiers are worth paying for.
  Classification is the cheapest possible gate: it can rule out whole *categories* of analysis, not
  just individual steps.

Signals already in hand, none of which need new collection: the README's own statement of intent
(finding 60), published architecture documentation and whether any exists (§5.5a), manifest
`packages`/`bin`/`scripts` declarations, presence or absence of deployment artifacts (a repo with no
Dockerfile and no compose file is not an application — `trellis.md` records exactly that), the ratio
of test/example/notebook files to source, and dependency direction (a library is depended upon; an
application depends).

#### It is a gate, not a weighting — and the outcome vocabulary has no word for it

**Maintainer, same session:** *"If we classify a repo as being a tutorial there is no point trying to
discover an architecture."*

That is stronger than down-weighting a result, and the design should say so plainly: on a repo
classified as a tutorial (or samples, or documentation), **architecture recovery does not run.** Not
"runs and scores low", not "runs and is reported with low confidence" — does not run. The cost saved
is the whole tier, which is what makes this the cheapest gate in the funnel rather than one more
filter applied after the expensive work has already happened.

**This exposes a gap in the five-label outcome vocabulary** (`resource_explorer/step_outcome.py`), and
it is not ours to fix unilaterally — that module is owned elsewhere and the labels were agreed jointly:

| label | why it does not fit a deliberate skip |
|---|---|
| `recovered` / `partial` | nothing ran |
| `no_signal` | "genuinely nothing to find — **and provably so**"; its constructor requires `known_positive=True`, i.e. evidence the detector works. We did not run, so we can prove nothing |
| `unverified` | "could not run, or ran with nothing to validate against" — closest, but wrong in the part that matters: we **could** have run and **chose not to**, which is a success of the funnel, not a failure of it |
| `regression` | unrelated |

A skip-because-irrelevant is a *good* outcome and currently reads as a degraded one. Whatever the
label ends up being — `not_applicable`, or `no_signal` with the `known_positive` requirement relaxed
for classification-gated skips — **the distinction that must survive is "we didn't run because it
would have been the wrong question" versus "we ran and found nothing".** Conflating them would make
the funnel's biggest win indistinguishable from its most common failure. Raise with the owner of
`step_outcome.py` rather than adding a sixth label here.

#### Two questions, not one: repo **role** and project **topology**

**Maintainer, same session.** Classification has a second axis. Beyond *what is this repo*, there is
*how does this project distribute its concerns across repos* — and that is a question of **style and
trend**, not correctness. Some projects keep a clean set of purpose-built repos; others jumble
tutorials, docs and code together. Both are legitimate, and the difference changes **where to look
for what**.

This is why RE has a project structure above repos at all: `projects.parent_slug`,
`projects.group_slug`, `projects.homepage_url` and `projects.docs_url` already exist in the registry.
The topology question has a home in the data model; nothing has been asking it.

**We already have five measured topologies**, gathered for the ground-truth work (finding 68) before
this framing existed:

| project | code | documentation | architecture published? |
|---|---|---|---|
| `milvus` | `milvus-io/milvus` | **sibling repo** `milvus-io/milvus-docs` | yes, versioned by branch |
| `kubernetes` | `kubernetes/kubernetes` | **sibling repo** `kubernetes/website`; in-repo `docs/` is a **tombstone** | yes |
| `prometheus` | `prometheus/prometheus` | **both** — in-repo `documentation/` *and* `prometheus/docs` | yes, in-repo, five years stale |
| `egeria` | `odpi/egeria` | **sibling repo** `odpi/egeria-docs` | no — mostly archived under `saved/` |
| `egeria-workspaces` | one repo | **in-repo**, mixed with code and tutorials | no |

Four of five separate documentation into its own repo. That is the trend, and a heuristic that
assumes otherwise will be wrong most of the time.

#### The expectation set — and reporting *where*, not *whether*

The maintainer's proposal, which is the actionable half:

1. **Classify the kind of thing** from the project's documentation and web site.
2. **Derive what a mature project of that kind should have**, then go looking for it.
3. **The result is itself part of the classification**, and it tells you where to look for everything else.

The design decision that makes this work: **the output for each expected artifact is a *location*,
not a boolean.** Four outcomes — `in-repo`, `in a sibling repo`, `on the doc site`, `not found` — and
only the fourth is an absence.

**Finding 68 is the cautionary tale for exactly this heuristic.** "Where is the documentation?"
answered naively against `kubernetes/kubernetes` returns *nothing, and stale for 1400 days*. The
correct answer is "in `kubernetes/website`, updated today". A boolean checklist would have marked
Kubernetes as undocumented. The location-valued answer is what makes the heuristic safe, and it
**requires the outward hop of §5.5a(a) as a hard prerequisite**, not an enhancement.

Indicative expectation sets — to be validated, not adopted as written:

| role | expected | notably *not* expected |
|---|---|---|
| application | deployment artifacts, install/quickstart, configuration reference, architecture doc, release notes | published package manifests |
| library | API reference, usage examples, versioning/changelog, published package | deployment artifacts — `trellis.md` records exactly this: "no Dockerfiles, no compose files … it has no deployment perspective at all" |
| middleware | deployment artifacts, configuration reference, integration/connector docs, compatibility matrix | end-user UI docs |
| tutorial / samples | stated intent, step-by-step content, sample data, environment setup | architecture, deployment topology |

**Absence is evidence in two directions, and they must not be conflated.** No deployment artifacts in
something classified as an application is a *maturity* finding. No deployment artifacts in something
classified as a library is *confirmation* of the classification. The same observation means opposite
things depending on the declared role — which is precisely why role must be established first.

**The failure mode to design against** is the one §5.5a(c) already names: an expectation checklist
turns into a maturity score, and a maturity score punishes deliberate choices. A small stable library
documents lightly on purpose; a project may deliberately keep tutorials in-tree. **Report the
findings and their locations as dated evidence; do not rank projects on the count.**

#### Offer to widen the scope — never widen it silently

**Maintainer, same session.** When the expected artifacts for a project's role are not in the repo
the user named, **ask whether to include other repos of the project**.

The location-valued lookup makes this nearly free: resolving where documentation lives *already*
produces the candidate list. Having found `kubernetes/website`, the remaining question is not
"which repo?" but simply "shall I include it?".

Four constraints, each with a reason:

1. **Ask; do not auto-add.** Silent scope expansion is the failure mode. It causes fetches the user
   did not ask for, and it produces results that cannot be compared with the previous run of the same
   analysis. There is precedent for this interaction: the maintainer's earlier answer on ambiguous
   partitions — *"if we are truly unsure we can present the user with a file tree with checkboxes"*.
2. **Record the scope with the result.** Adding a repo changes the denominator of every coverage and
   score. `trellis.md`'s `Scope:` line exists precisely because a wrong denominator makes a number
   meaningless (whole-repo coverage reads 15% where in-scope coverage is 48%). §6.2 already argues
   that a metric moving between two runs is ambiguous without `analyzerVersion`; **the set of repos in
   scope is the same kind of provenance and must travel with the result.**
3. **Classification must come first.** What is "missing" is only defined relative to the role.
   Asking "where are the deployment artifacts?" for a library is noise, not a gap — a library is
   *expected* not to have them (§5.5b, and `trellis.md` records exactly this).
4. **Use the mechanisms that exist.** RFA is already the carrier for "the system needs something from
   a human", and the registry already models repo families (`projects.parent_slug`,
   `projects.group_slug`) with an Admin Groups UI on top. This is a new *question*, not new
   plumbing.

**Why this is good funnel behaviour rather than a nag.** The ask is cheap, it happens before the
expensive tiers, and the alternative is worse than a prompt: analysing a code repo whose architecture
documentation lives in a sibling repo produces a confident, wrong "no architecture documented"
finding. That is the Kubernetes tombstone case (finding 68) reaching the user as a conclusion instead
of a question.

#### The gate must NOT trigger on the primary role alone

Found while building the classifier, and it corrects the "gate" subsection above.

`odpi/egeria-workspaces` classifies as **`tutorial`, `application`, `library`** — all three correct.
Its README says it is *"a fully pre-configured, Docker Compose-based platform for **learning**,
experimenting with, and operating Egeria"* and *"designed for learning and small-team use"*, and it
carries 37 Jupyter notebooks in `workbooks/` and `coco-workbooks/`. `tutorial` ranks **primary**.

**And it is target T1, from which architecture recovery scored 18/27.** A gate keyed on the primary
role would skip the repo whose deployment architecture we have most successfully recovered.

So primacy is the wrong trigger. The gate's real question is not *"what is this repo mostly?"* but
*"is there an architecture here worth recovering?"* — and that is answered by the **presence of
structural evidence**, not by which role sorted first:

> **Skip architecture recovery when a tutorial/samples/documentation role is present AND no
> deployment or structural artifacts were found. Never on the primary role alone.**

Under that rule `egeria-workspaces` runs (25 compose files), a pure notebook workshop does not, and
`kubernetes/website` does not. The primary role still drives the **expectation set** — what a mature
project of this kind should have — which is what it is good for.

**Why the distinction was invisible until now.** Single-role classification conflates "what it mostly
is" with "what it contains". The multi-valued decision separates them, and the gate must key on
*containment* while the expectation set keys on *primacy*. Two different questions, two different
readings of the same classification.

#### Vocabulary check against Egeria — done, and nothing existing fits

§3.1's lesson was that `SolutionComponentType` **already existed** rather than needing invention, so
the same check was run before defining a role vocabulary. Searched
`frameworks/open-metadata-framework/.../refdata/` (the same directory
`SolutionComponentType.java` lives in) at `egeria-v6`:

| candidate | what it actually encodes | verdict |
|---|---|---|
| `DeployedImplementationType` (~120 values) | *deployed runtime artifacts* — `SOFTWARE_SERVER`, `DOCKER_CONTAINER`, `REST_API`, `SOURCE_CODE_FILE`, connectors, file types | **wrong axis.** Describes what a thing IS at runtime, not what a body of work represents. No `library`, `tutorial`, `samples`, `documentation` |
| `ResourceUse` (29 values) | how a resource is *used in a governance flow* — `SURVEY_RESOURCE`, `CATALOG_RESOURCE`, `INFORM_STEWARD` | wrong axis |
| `Category` (7 values) | metadata namespaces — `OPEN_METADATA_TYPES`, `SUSTAINABILITY`, `CLINICAL_TRIALS` | unrelated |
| `ProjectStatus`, `ProjectPhase`, `ProjectHealth` | lifecycle state of a *project*, not its kind | unrelated |

**There is no existing Egeria vocabulary for what a repository represents.** The check was still worth
running: it rules out a wrong reuse, and it found the adjacent slot is already occupied.

**The adjacent slot, and why role must not go in it.** `egeria_publisher.py:295` already writes
`"deployedImplementationType": "GitHub Repository"` for every catalogued repo. That is the *hosting
technology*, not the role — and "GitHub Repository" is not one of the enum's ~120 values, which
confirms the property is free text backed by an extensible valid value set. Overloading it with
`library` / `tutorial` would collide two orthogonal facts in one property, the §4.1c mistake
(`scope_locator` meaning two things) in a new place.

**Recommended shape: a new Egeria valid value set, not a Python enum.** Valid value sets are the
framework's native extension mechanism — `ConfidenceLevel` is one, and the maintainer has already
confirmed they can be extended ("confidence level is defined in valid values — we can extend it if we
want"). A valid value set is catalogable, queryable, and extensible without a code change, where a
hardcoded Python enum is none of those and would have to be migrated the first time the list is wrong.

**Open, deliberately.** The vocabulary is not chosen yet, and the temptation to invent a closed enum
should be resisted until it is checked against Egeria's existing types — `SoftwareCapability`
subtypes and `plannedDeployedImplementationType` may already carry part of this, the same way §3.1's
13-value `SolutionComponentType` turned out to exist rather than needing invention. Whether one repo
gets one classification, or a monorepo gets one per workspace member, is also open — `trellis` alone
contains an application, two libraries and a spike.

**A companion question — capturing the user's intent — was raised at the same time and deliberately
deferred to a separate discussion.** What the repo *is* and what the user *wants from it* are two
different filters on which analyses matter, and conflating them would be a mistake.

### 5.5c Learning from user feedback — and the two things that look alike

**Maintainer direction, 2026-08-22:** *"we need to continuously get feedback from the user to allow
us to continue to refine our weights, scoring and algorithms — perhaps some of them dynamically."*

Right, and necessary: every table in §5.5b is provisional, the role vocabulary is a first guess, and
the expectation sets were written from five projects. Nothing here improves without correction from
people who know the repos.

But two mechanisms hide under "learn from feedback", and conflating them would dismantle the only
uncontaminated measurement this project has.

#### (a) Feedback as **labelled examples** — safe, and the high-value half

A user saying *"this is a tutorial, not an application"* is a **data point**: a labelled example with
an author, a date, and a repo. Stored that way it is durable, auditable, and reusable for purposes
not yet imagined. This is the half to build first, and RE already has the plumbing — `curate.py`'s
`resource_feedback` / `resource_curator_notes`, the RFA lifecycle, and the activity log. **Capturing
feedback is not new infrastructure; it is a new question asked through existing surfaces.**

#### (b) Feedback as **weight adjustment** — where the danger is

Three rules this project has already paid for, each of which auto-tuning would violate by default:

1. **Never tune on the pre-registered fixtures.** `README.md` rule 3 forbids editing them *because a
   partition inferred from the code and then compared against that code measures nothing*. A weight
   fitted to make `prometheus.md` score 11/11 makes that 11/11 meaningless. Feedback-derived examples
   must form a **separate, growing corpus**, and the fixtures must never enter it.
2. **A rule fitted to the repos you have measured is not a rule** (findings 65, 78). The `kube-`
   prefix pairing was not shipped for exactly this reason. Feedback arrives from repos the user
   happens to care about, which is a biased sample by construction — the correction is a **frozen
   holdout**, not more data.
3. **A moving weight is a moving denominator.** §6.2 already argues that a metric which changes
   between two runs is ambiguous without `analyzerVersion` — did the code change, or the detector?
   Silently-adjusting weights make *every* number incomparable across runs. So any weight set must be
   **versioned and recorded with the result**, exactly like `analyzerVersion` and the in-scope repo
   set (§5.5b).

#### The ordering constraint

**You cannot safely auto-tune without a way to detect that tuning made things worse.** That detector
is the pre-registered corpus scored by strict containment (§2a, finding 61) — currently Prometheus
11/11, Kubernetes 6/6, Milvus 3/5, trellis 9/11, egeria-workspaces 18/27. It works *only* while it
stays out of the training loop.

So the sequence is: **capture labelled feedback → make weights explicit, versioned and stated with
every result → require a holdout run before any weight change → only then consider anything
dynamic.** Static-but-versioned is not a lesser version of dynamic; it is the thing that makes
dynamic detectable.

#### The failure mode to name out loud

A system that tunes on recent feedback gets better at **agreeing with recent users** rather than at
being right, and it degrades invisibly, because the same feedback that shifts the weights also shapes
what anyone thinks to check. §5.5a(c)'s guardrail — report the observations, do not rank them — is
the same instinct one layer up: **prefer a system that shows its evidence and is corrected, over one
that quietly converges on approval.**

### 5.5d User motivation → disposition → next steps

**Maintainer, 2026-08-23.** Step back from the repos and ask why anyone is looking at one at all.
Motivation drives **disposition** and **next steps**, and therefore which questions — and hence which
survey types — are relevant.

The motivations, as given:

| # | motivation |
|---|---|
| 1 | gain general understanding |
| 2 | assess potential competition |
| 3 | prospect for components, runtimes or tools that might be useful |
| 4 | the components/runtimes/tools are **already in use**: (a) learn to use them, (b) evaluate robustness/security/viability, (c) decide whether to upgrade, (d) compare with alternatives, (e) investigate expanding their use |
| 5 | the repo is **data** — analogous questions, different kinds: quality, currency, documentation |

Possibly several at once, as with roles.

#### The structural line inside the list

**1–3 are about resources you do not use; 4 is about resources you do.** That is not a label, it
changes what evidence *exists*. For an in-use resource there is a second corpus — which version you
are on, which APIs you actually call, how deeply it is embedded, who owns the integration — and
**none of it lives in the repo being surveyed.** RE has no such corpus today. Every motivation under
4 is partly unanswerable from the repo alone, and pretending otherwise would produce confident
answers to the wrong question. Worth naming before anything is built: *4 needs an input we do not
have*.

#### 5 is not a sixth motivation

It is the observation that the **question set is resource-type-specific while the motivation set is
not**. "Is it current?", "is it documented?", "can I depend on it?" are the same motivations aimed at
a different kind of thing. That is good news: motivation **composes with** resource type rather than
multiplying against it, so a data resource does not need its own motivation taxonomy.

#### Disposition is the new idea, and it is the missing top layer

RE produces annotations and findings — *evidence*. A **disposition** is an answer: adopt, avoid,
monitor, upgrade, replace, ignore, investigate further. That is what a decision-maker actually wants,
and nothing in the system currently produces it.

**And Egeria may already have the vocabulary.** §5.5b's check found `ResourceUse` and set it aside as
the wrong axis *for role* — which it is. But for disposition and next steps it looks close to right:
`CERTIFY_RESOURCE`, `CATALOG_RESOURCE`, `UNCATALOG_RESOURCE`, `PROVISION_RESOURCE`, `CHOOSE_PATH`,
`WATCH_DOG`, `CREATE_SUBSCRIPTION`, `IMPROVE_METADATA`, `INFORM_STEWARD`, `GENERATE_INSIGHT`. Those
are *governance actions on a resource* — which is what a next step is. **Check this properly before
inventing a disposition vocabulary**, exactly as §3.1's `SolutionComponentType` turned out to exist.

Note `WATCH_DOG` and `CREATE_SUBSCRIPTION` in particular: motivation 4c (*do we need to upgrade?*) is
inherently **recurring**, not a one-shot survey. It is the Automate intent by another name, which
suggests some motivations imply a *schedule* rather than a run.

#### Four axes now exist — keep them apart

| axis | question | vocabulary |
|---|---|---|
| **role** (§5.5b) | what *is* this resource? | 7 values, provisional |
| **motivation** (here) | why am I looking at it? | this list, provisional |
| **perspective** | who am I? | dba / data_scientist / steward / security |
| **intent** (the 8 UI tabs) | how am I working right now? | Scouting … Automate |

These are genuinely different, and merging any two would repeat the §4.1c mistake — one field, two
meanings — which this project has now hit three times. In particular **motivation is not the eight UI
intents**: those are *modes of working*, this is *why*. "Evaluate robustness" (motivation) is pursued
*through* Assessment (mode).

**The combinatorial risk is real and has an answer.** Four axes multiply if each independently
filters. They do not have to: questions in `docs/dr-egeria/resource_questions.csv` already carry
funnel stage and perspective, so **motivation selects question sets** and the existing facets do the
rest. One mapping, not a cross-product.

#### The discipline that keeps this from becoming a taxonomy nothing uses

**Every motivation must change something concrete** — which questions are asked, which survey types
run, or which disposition is offered. **If two motivations produce identical behaviour, they are one
motivation.** That is a falsifiable test, and it should be applied to this list before it is adopted:
on current evidence 4b (*evaluate robustness/security/viability*) and 3 (*is this worth using?*) may
well collapse, and 1 (*general understanding*) may turn out to be the absence of a motivation rather
than one of them.

### 5.5d-i Disposition — the vocabulary check came back negative, for the first time

§5.5d named **disposition** as the missing top layer: the system produces *evidence*, and a decision
maker wants an *answer*. It also flagged `ResourceUse` as a strong candidate, on the strength of
value names like `CERTIFY_RESOURCE`, `WATCH_DOG`, `CHOOSE_PATH` and `UNCATALOG_RESOURCE`.

**Checked, and it is the wrong axis.** Reading the descriptions rather than the names:

| value | Egeria's own description |
|---|---|
| `CATALOG_RESOURCE` | *"Extract metadata from the real-world resource and add it to the open metadata repositories"* |
| `WATCH_DOG` | *"Monitor for changes to a **metadata element** and its related elements"* |
| `INFORM_STEWARD` | *"Send notification to a steward"* |
| `UNCATALOG_RESOURCE` | *"Remove asset and associated metadata … from the open metadata repositories"* |

These are **governance operations on metadata**, not judgements about a resource. `UNCATALOG_RESOURCE`
means "stop cataloguing this", not "don't adopt this". Same mistake as reading it as a role vocabulary
in §5.5b — the names suggest a decision and the semantics are an operation.

**This is the first negative result from that check**, after `SolutionComponentType` (§3.1),
`SolutionPortDirection` (§3.2), `SolutionLinkingWire` (§3.3) and the Area 0 `SoftwareCapability`
subtypes all turned out to exist and be reusable. It was still worth running: it rules out a wrong
reuse that the value names actively invite, and it located the adjacent concept.

#### What Egeria models is the ACTION, not the RECOMMENDATION

`ToDo`, `Certification` / `CertificationType`, `GovernanceAction`, `ActionTarget` — all real, all
downstream. A disposition is upstream of every one of them: *"this looks like it should be upgraded"*
precedes the ToDo that upgrades it.

So disposition is a **small new vocabulary**, and its value is that its consequences map onto
mechanisms that already exist:

| disposition | what it leads to, all of which exist |
|---|---|
| adopt / approve | `Certification` against a `CertificationType` |
| monitor | an Automate subscription (`notification_subscriptions`), delivered as an RFA |
| act (upgrade, replace, investigate) | an RFA today, an Egeria `ToDo` when that integration lands |
| nothing to do | no action — and this must read as a *complete answer*, not an empty one |

#### Three constraints, carried from the rest of §5.5

1. **A recommendation, not a verdict.** It carries the evidence that produced it, and it must never
   imply the system decided. Same reason §5.5a(c) forbids scoring: a confident-looking output
   punishes deliberate choices the system cannot see.
2. **No score, and no ranking of resources by disposition.** "Three repos need attention" is a
   count of findings; "these repos scored worst" is not something this can support.
3. **"Nothing to do" is an answer.** For a repo the gate skipped, the disposition is
   *nothing-to-do*, and it should render like `SKIPPED_BY_DESIGN` does — neutral and complete —
   rather than as an absence. Reuse that reader-state vocabulary rather than inventing a parallel one.

### 5.5e Black box / white box — a lens derived from motivation, not a fifth axis

**Maintainer, 2026-08-23.** Some questions are answerable from the outside — *how do I operate this,
does it fit my infrastructure* — and some require looking inside — *how do I tune it, is it secure,
is it well built*.

**This is not another axis to keep apart from the other four.** It is largely *determined* by
motivation (§5.5d), so it should be **derived and shown, never selected**. Making it a user choice
would add the fifth independent filter §5.5d just warned about; deriving it costs nothing and
explains the resulting question set to the user.

| motivation | lens |
|---|---|
| 4a learn to use it | black box |
| 3 prospect — would this be useful? | black box |
| 4e expand its use | black box (mostly — fit and limits) |
| 4b evaluate robustness / security / viability | **white box** |
| 2 assess competition | **white box** (what have they actually built) |
| 4c upgrade? | **both** — compatibility is black box, breaking changes and risk are white box |
| 1 general understanding | undetermined — further evidence that 1 may be the *absence* of a motivation |

#### Why it is worth naming: we have already built one of each

- **Black box** — role classification, doc-location resolution, expectation sets (§5.5b). These read
  only what a project *exposes*: README, published docs, manifests, deployment artifacts.
- **White box** — architecture recovery. It reads source, import graphs and co-change history.

Naming the split describes structure that already exists rather than inventing any.

#### And it is approximately the funnel boundary we already have

Black-box evidence is cheap and largely already collected — GitHub API, manifests, docs. White-box
evidence needs a fetch and a parse — zipball, clone, ast-grep, import resolution. So the lens tracks
**Discovery vs Analysis/Assessment** (CLAUDE.md rule 17) closely enough to be useful as an
explanation of it.

It also explains the one case that never fit: `architecture_recovery` is **white box yet cheap**
(~5s/repo), which is exactly why it needed a named rule-17 exception. The tier is defined by *cost*,
the lens by *where the evidence lives*, and they usually but not always agree.

#### Deferred, deliberately: how the resource is exposed and consumed

The larger question the maintainer raised alongside this — *is it a library you import, a service you
call, a container you run, a dataset you read?* — is **its own thread and is not recorded here.** It
is close to role (§5.5b) without being it: a thing can be a library *and* expose a REST API. It
determines what "using it" even means, and therefore what a black-box question can be. Picking it up
should start there rather than by extending any table above.

### 5.5f The external interface is the biggest gap, and it is cheap

**Maintainer, 2026-08-23:** the external interfaces a resource exposes, and their characteristics,
are an under-analyzed aspect. Checked rather than assumed, and it is stronger than "under-analyzed":

| specified | built |
|---|---|
| `IR.ports` | **empty** — `# not in this slice`, and **nothing anywhere populates it** |
| `IR.wires` | **empty** — same |
| §5.2 step 4, "infer ports and directions from interfaces served vs. consumed" | not built |
| §5.2 step 5, "infer wires ... `protocol` / `integrationStyle` / `frequency` / `dataExchanged` / `oneWay`" | not built |
| §3.2 `SolutionPortDirection`, a 5-value enum | never written |

`ApiStructureSurveyor` does not close this — it counts symbols and module structure, which is
internal shape, not exposed surface.

#### Why this matters more than it looks: it undercuts the black-box half

§5.5e says black-box questions are *how do I operate this, does it fit my infrastructure*. But
everything black-box we have built reads **metadata *about* the resource** — README, published docs,
manifests, deployment artifacts — and **not the interface *of* the resource.**

So today the system can say *"this is an application with deployment artifacts and a current
architecture doc"* and cannot say *"it serves these three REST endpoints, consumes this Kafka topic,
and needs these two ports open."* The second is what "does it fit our infrastructure" actually means.
**The black-box half is weaker than §5.5e implies, and this is the gap.**

#### The vocabulary already exists — for the third time

`SolutionPortDirection` (§3.2) and `SolutionLinkingWire`'s properties are already in Egeria and
already in this design; nothing populates them. That is the same pattern as `SolutionComponentType`
(existed, §3.1) and the `ResourceUse` candidate for disposition (§5.5d): **check before inventing.**

#### And it is cheap — unusually so for the biggest gap

Interface evidence is disproportionately **black-box observable**, much of it in artifacts already
fetched:

- OpenAPI / Swagger documents, `.proto` files, GraphQL schemas
- compose `ports:` / `expose:`, `EXPOSE` in a Dockerfile, Kubernetes `Service` manifests
- declared entry points and console scripts (already read by `go_subsystems` and the manifest detectors)
- event topics and queue names in configuration

Most needs no source parsing at all, which puts it at **Discovery tier by rule 17's own test** —
cheap, and it gates the expensive tiers. That is an unusual combination: the largest missing piece is
also among the least expensive to start.

#### Its relationship to the deferred thread

This is the concrete, buildable half of the exposure/consumption question §5.5e deferred. **A port is
how a resource is exposed**; the deferred thread is the broader model of what kind of thing is being
exposed (library to import, service to call, container to run, dataset to read). Ports and wires can
be populated without settling that model, and doing so would give it evidence to be designed against
rather than reasoned about.

### 5.6 Tooling — what to adopt, and what it costs

Everything below is either a subprocess emitting JSON or a plain Python library. No daemons, no
servers, no persistent state — which is what makes them all trivially wrappable as microflow steps
(§5.7). Cost tier maps onto the funnel: cheap enough to run on everything that passes Scouting, versus
expensive enough to spend only on resources that earned it.

| Tool | Role | Shape | Cost | Tier |
|---|---|---|---|---|
| `scc` | file/line/comment counts, per-language, **per directory** | Go binary, JSON | ~1s on a large repo | **Discovery** |
| `ast-grep` | the §5.1 code-marker detectors, as YAML rules | Rust binary, JSON | seconds | **Discovery** |
| `dockerfile-parse` + PyYAML | container / compose / k8s / service-unit parsing | pure Python | milliseconds | **Discovery** |
| `lizard` | cyclomatic complexity, max nesting, function counts, **~15 languages** | Python lib | seconds–1 min, scales with code volume | **Discovery** |
| `syft` | SBOM across ~20 ecosystems, with package→file mapping | Go binary, CycloneDX/SPDX | tens of seconds | **Analysis** |
| `trivy` | SBOM + vulnerabilities + IaC misconfig + secrets; also ships compose/k8s/Helm/Terraform parsers | Go binary, JSON | first run pulls a large vuln DB, then seconds | **Analysis** (cache the DB) |
| `PyDriller` | per-path churn, contributors, ownership, code age — the Q11 sibling annotation | Python lib | **minutes**; needs git history | **Analysis** |
| `code-maat` | co-change coupling (§5.5) | JVM jar over `git log` output | cheap *given* the log | **Analysis** |
| Structurizr | **export target**, not extraction — validates the IR maps onto C4 | schema / DSL | n/a | optional |

**The whole detector layer is Discovery-tier.** `scc` + `ast-grep` + config parsing + `lizard` together
run in about a minute on a large repo with no network beyond the zipball. That means the component
partition — the thing everything else depends on — is affordable at estate scale and can run on every
repo that clears Scouting. This is the single most important cost fact in the design.

**Two things are genuinely expensive, and the funnel should gate them:**

- **Git history.** A full clone is the largest cost in this feature. Mitigate with `--filter=blob:none`
  (treeless — metadata without file contents, a large win) and a bounded window: bus-factor and churn
  questions almost always concern recent history, so cap at N months rather than mining the full log.
- **LLM distillation (§5.2).** Cost scales with component count and evidence volume. Gate it: invoke
  the LLM **only** for components where detector confidence falls below threshold, and **only** for
  naming, classification, and merge adjudication — small prompts over distilled evidence, never
  whole-repo reading. A repo whose architecture is fully declared (§5.1) should invoke it zero times.

Deliberately not adopted: `radon` (Python-only; `lizard` supersedes it), `grimp` (§5.5),
`scancode-toolkit` (heavy; RE's existing `repo_license_classification` is sufficient), Joern / SCIP /
stack-graphs (§10 Deferred — but note SCIP indexers emit a specified protobuf, so if symbol-granularity
`ImplementedBy` is ever needed, you consume an index rather than adopt a framework; that is the
cheapest re-entry point).

### 5.7 Wrapping as survey steps

The extension point already exists and needs no redesign: one `StepInfo` in `STEP_REGISTRY` plus one
`AnalysisKind` in `analysis_catalog.yaml`, per
`surveyors/repo_survey_definition_adapter.py`. `SurveyOrchestrator` derives its surveyor-construction
dict from `STEP_REGISTRY` automatically, and `prefect_adapter.py` dispatches by `step_name` +
`runner_kwargs` — so a new step is **Prefect-dispatchable with zero Prefect-specific work**.

Proposed steps:

| Step key | Wraps | `target_shape` | `accepts_scope_locator` | `requires_resources` |
|---|---|---|---|---|
| `repo_arch_detect` | ast-grep rules + config parsers → the IR | `corpus` | yes | `zipball_root` |
| `repo_code_metrics` | `scc` + `lizard` → §6.2 attributes | `corpus` | yes | `zipball_root` |
| `repo_sbom` | `syft` | `corpus` | yes | `zipball_root` |
| `repo_history_metrics` | `PyDriller` + `code-maat` → Q11 sibling annotation | `corpus` | yes | **`git_clone_root`** |

Three infrastructure notes, two of which are real gaps:

1. **Zipball sharing already works.** All of these need a real checkout, and `_acquire_zipball_root` +
   `trellis_microflow.resolve_resources` already dedupe it. Critically, dedup only happens *within* a
   single `SurveyOrchestrator.run()` call — which is what `_run_batch` provides. So these belong as
   **steps of one Survey Definition**, not four independent analyses: one download for the whole group.
   This is the strongest argument for the survey-path unification work.

2. **Gap: git history.** A zipball has no `.git`. `PyDriller` and co-change coupling need one. That is a
   **new `ResourceProvider` — `git_clone_root`** — alongside `_acquire_zipball_root`, doing a treeless
   clone. Q11's sibling annotation type currently has no data source without it; this is a
   prerequisite, not a detail.

3. **Gap: binary provisioning.** `scc`, `ast-grep`, `syft`, `trivy` are Go/Rust binaries, not pip
   installs. Bake pinned versions into the RE image and expose a version probe — which is precisely
   what §6.2's `analyzerVersion` is for. The network-dependent steps (`syft`, `trivy` DB pulls) want
   Prefect task-level retries; the rest are pure functions of a checkout and need none.

---

## 6. Component-scoped analytics (the payoff)

Once a component partition exists, re-aggregate RE's existing analyses to component granularity and
publish those. This directly addresses gaps named in the current-state doc:

| Existing analysis | Today | Per component |
|---|---|---|
| Contributor tiers / bus factor (`stats_fetcher.py:209-261`, gap **R1**, unpublished) | per repo — trivia | **per component — actionable risk**; a `Software Service` with bus factor 1 is a real finding |
| Dependencies (`dependency_parser.py`) | per repo | per component → real blast radius, and the input to the vulnerability use case |
| Symbol counts / API surface (gap **R4**) | aggregate counts only | per component, and the component's *ports* are its genuine public surface |
| Doc coverage (`documentation.py`) | repo-level label | which subsystem is undocumented |
| Security posture (`security.py`) | repo-level | which component carries the risk |
| Commit history (gap **R2**) | repo time series | per-component change velocity → which parts are volatile |

This is where the orphaned R-gaps get a home. Worth sequencing early (Phase 4) rather than treating as
a follow-on, because it is the clearest demonstration of value.

### 6.0 This is not new machinery — a component is a scope locator

**The single most important consequence of Q3's answer.** If component identity is a module path
(§8.2), then *a component is a path prefix* — and RE already has a path-prefix mechanism: the
`scope_locator` column and `accepts_scope_locator` flag from the repo scope-narrowing funnel
(`docs/repo-scope-narrowing-funnel.md`, D5/D6).

So "re-aggregate existing analyses per component" is **not a new aggregation layer**. It is running the
existing scope-locator-capable steps once per component path. Every step already flagged
`accepts_scope_locator=True` in `STEP_REGISTRY` becomes component-scoped for free:
`repo_file_size`, `repo_api_structure`, `repo_data_profiling`, `repo_file_classification` — plus the
new §5.7 steps, which are all `target_shape: corpus`.

`project_analysis_findings` and `project_analysis_metrics` (`registry.py:866`, `:898`) both already
carry `scope_locator`, and both are already indexed on it. The storage question is answered before it
is asked.

Three consequences:

- **Phase 4 is much cheaper than it reads.** It is largely a loop and a projection, not a redesign.
  Re-sequence accordingly.
- **`scope_locator` is the universal join key** — evidence (§5.4), metrics, findings, and the Egeria
  component's qualified-name slug all key off the same path prefix.
- **It raises the stakes on Q3.** Identity is now load-bearing for the analytics story too, not just for
  upsert stability.

### 6.1 Carrier: a `CodeAnalysis` **Annotation**, not a classification

**Decision:** `CodeAnalysis` becomes an Annotation subtype rather than a classification — more
flexible, and it links to the right artifact through existing annotation relationships rather than
being pinned onto one element. Being an Annotation also means it inherits `AnnotationProperties`:

`annotationType`, `summary`, `explanation`, `expression`, `analysisStep`, `confidence`, `units`,
`absoluteUncertainty`, `relativeUncertainty`, `jsonProperties`, and **`sampleSize` / `samplePercent` /
`samplingMethod`**.

Two consequences for the attribute design:

- **`confidence` is already there** — §5.4's per-claim confidence requirement is satisfied by the base
  type; do not add a second confidence field.
- **`sampleSize`/`samplePercent`/`samplingMethod` already answer "how much did we look at"** — so no
  coverage or files-skipped attributes are needed. Reuse them, and populate them honestly when a
  component is only partially analysed.

The existing 0780 attribute set is **not** a good first pass. `setVariableCount`,
`simpleCalculation`/`complexCalculation` and the condition counts are COBOL-era program-analysis
metrics that do not generalise across modern multi-paradigm code, and nobody would act on them.

### 6.2 Proposed first-pass attributes

Scoped to metrics that are reliably extractable across languages, comparable between components and
over time, and answer a question someone actually asks.

**Scale and shape**

| Attribute | Type | Note |
|---|---|---|
| `fileCount` | int | |
| `lineCount` | long | total physical lines |
| `codeLineCount` | long | excludes blanks and comments |
| `commentLineCount` | long | explicit rather than derived — deriving breaks if a sibling field is absent |
| `primaryLanguage` | string | |
| `languageCount` | int | polyglot components carry real maintenance cost |

**Interface surface** — the component's public face; pairs with its ports

| Attribute | Type | Note |
|---|---|---|
| `publicSymbolCount` | long | exported functions, classes, endpoints |
| `entryPointCount` | int | mains, CLI commands, route handlers, task definitions |

**Data interaction** — the most governance-relevant group, and the part of 0780 worth keeping

| Attribute | Type | Note |
|---|---|---|
| `dataReadCount`, `dataCreateCount`, `dataUpdateCount`, `dataDeleteCount` | long | CRUD profile |
| `dataStoreCount` | int | distinct stores touched — blast-radius magnitude |
| `externalCallCount` | long | calls out of the component |

**Complexity**

| Attribute | Type | Note |
|---|---|---|
| `functionCount` | long | also makes mean complexity derivable |
| `cyclomaticComplexityTotal` | long | |
| `cyclomaticComplexityMax` | int | **the important one** — a single 200-complexity function is the real risk, and means hide it |
| `maxNestingDepth` | int | |

**Hygiene and provenance**

| Attribute | Type | Note |
|---|---|---|
| `testFileCount` | int | |
| `documentedSymbolCount` | long | with `publicSymbolCount`, gives doc coverage *of the public surface* — the actionable form |
| `analyzerName`, `analyzerVersion` | string | see below |

`analyzerVersion` earns its place: without it, a metric that moves between two blueprint versions is
ambiguous — did the code change, or did our detector improve? **Drift comparison (§8.3) is
untrustworthy without it.** Alternative placement is the SurveyReport, but one report can carry
annotations from several analyzers, so it belongs on the annotation.

**Corollary — one annotation per analyzer per component, not one per component.** A single component's
metrics come from several tools (`scc` for scale, `lizard` for complexity, `ast-grep` for interface
surface, `PyDriller` for history). A single `analyzerName`/`analyzerVersion` pair cannot honestly
describe an annotation aggregating all of them. Emit one annotation per analyzer, distinguished by
`annotationType`; the Annotation model supports many-per-element without strain.

This resolves §6.3's bus-factor exclusion as a side effect: repository-history metrics stop being a
special case needing separate justification and become simply *another analyzer's annotation* against
the same component. The Q11 sibling type is then a naming exercise, not a structural one.

**Smaller first cut, if wanted:** the six scale fields, the four CRUD counts, and `analyzerVersion`
carry most of the value. Complexity and hygiene can follow.

### 6.3 Deliberately excluded

- **Bus factor, contributor count, churn** — not code analysis. They change when nobody touches the
  code (a contributor leaves), which makes the annotation's freshness semantics incoherent. These want
  a **sibling annotation type** over repository history. Worth defining separately; note this is the
  home for gap **R1**, so §6's table above should be read as spanning two annotation types, not one.
- **Lists** (dependencies, data stores, endpoints) — the annotation carries **magnitude**; the
  **topology** belongs on wires, ports and relationships. Duplicating identities into scalar properties
  guarantees the two representations drift.
- **Fan-in / fan-out, instability** — derivable from the wire graph; storing them duplicates what
  `SolutionLinkingWire` already encodes.
- **Language breakdown map** — map properties are unqueryable, the exact failure mode the current-state
  doc documents repeatedly.
- **Security / vulnerability counts** — different lifecycle; a CVE appears without the code changing.
- **`firstRun` / `lastRun`** — the SurveyReport carries timing.
- **`analysisType`** — that is `annotationType` on the base.
- **`dataChecksCount`** — interesting for data quality, but probably not reliably extractable across
  languages. Revisit after Phase 0.

**Open call, deliberately deferred:** which of these justify *typed* properties versus
`additionalProperties`. Decide after Phase 0 shows what we can extract reliably across languages —
typing a property we can only populate for Python is worse than leaving it untyped, because it looks
queryable and silently isn't.

### 6.4 Interim carrier while the type lands

The new Annotation type is expected within a day or so. Until it exists:

- Use the **base `Annotation`** with the metrics in `additionalProperties`.
- Swap to the typed `CodeAnalysis` annotation once available.
- **No migration needed** — this is a test environment, so previously written annotations can simply be
  re-derived rather than converted.

This removes the upstream dependency from Phase 4's critical path: work proceeds against the interim
carrier and the swap is a projection-layer change, not a redesign.

### 6.5 Agents over annotations — the generalisation

Three distinct roles for LLMs in this feature, deliberately separated because they have different risk
profiles and different owners:

**(a) Inside extraction (§5.2).** Naming, classification, merge adjudication, and drafting a
component's `description`. Bounded by the standing rule: *the LLM never invents a component with no
detector evidence behind it.* Cost-gated per §5.6 — invoked only below a confidence threshold.

**(b) Curation assistant (§7).** Given the evidence and the proposed partition, draft the rationale a
curator reads, propose merges and splits, and triage which RFAs actually matter. The human still
decides; the agent removes the reading.

**(c) Q&A over annotations — the generalisation, and the biggest lever here.**

RE has specialist agents for code, dependencies, health, stats, docs and comparison
(`agents/code_agent.py` and siblings), but **no agent over annotations**. From the agent layer's
perspective, every survey RE has ever run is write-only. That is a large, invisible gap: the analyses
are the product, and nothing can be asked about them.

Two agents, layered:

- **`AnnotationAgent` — generic, covers every analysis kind including ones not yet written.** Tools:
  `query_annotation_types()` (the `annotation_types` table, `registry.py:1342`, already populated from
  `ANNOTATION_TYPES_REGISTRY` — a ready-made schema catalog for the model to reason over),
  `query_findings(slug, kind, scope_locator)`, `query_metrics(slug, kind, metric_name, scope_locator)`.

- **`ArchitectureAgent` — specialises it with the blueprint graph:** components, ports, wires and their
  `scope_locator`s. Answers the questions this feature exists to make askable — *"what talks to the
  database?"*, *"which component has the worst bus factor?"*, *"what changed architecturally between
  1.2 and 2.0?"* The last one is §8.3's drift diff with a natural-language front end.

**Why the generic agent is possible at all: because findings and metrics are uniformly shaped.** One
agent covers every kind precisely because `project_analysis_findings` /
`project_analysis_metrics` are generic tables rather than per-analysis bespoke ones. Every new analysis
becomes queryable **for free**, with no agent work.

That makes §6.3's "annotations carry magnitude, not lists" rule and the generic-findings-table
discipline the *same* rule, arriving from two directions. It is now load-bearing for the agent story as
well as the data-modelling one — worth defending when the next analysis is tempted to add its own
table.

**Also worth doing, cheaply:** embed component descriptions and the IR into the vector store as an
`architecture` collection. `CollectionRouter` already routes by collection, so architecture becomes
semantically searchable alongside code with no new retrieval machinery.

**Sequencing note.** `AnnotationAgent` does not depend on this feature at all — it could ship today
against the existing analyses and would immediately be useful. It is listed in the plan below because
architecture recovery is what makes it *compelling*, not what makes it *possible*. Splitting it out
early is a reasonable call.

---

## 7. Curation

Curation is not a review screen bolted on at the end — it is the mechanism that makes derived metadata
safe to publish at all. Three parts.

### 7.1 Lifecycle

```
  derived ──► Draft ──► Prepared ──► Proposed ──► Approved/Active
                 │                        │
                 └────► (Rejected) ◄──────┘
```

- Derivation always publishes at `ContentStatus = Draft`. Nothing derived is ever born Active.
- RE's Curate intent presents the derived blueprint against its evidence.
- Curator actions: **accept**, **rename**, **reclassify** (change `solutionComponentType`), **merge**
  two components, **split** one, **reject**, **add a missing** component the detectors couldn't see.
- Promotion to `Prepared`/`Proposed` signals human review; `Active` is the validated state.
- Rejected components go to `Rejected`, **not deleted** — otherwise the next derivation cheerfully
  re-proposes them.

Confirmed available: `ContentStatus` is settable per component (§3.4), so promotion works at the
granularity this model needs — a curator can accept one component and leave its neighbour in Draft.

**Promotion moves two axes, not one** (§3.3c): `ContentStatus` advances through the workflow, and
`confidenceLevel` moves `Derived` → `Authoritative` when a human actually signs off on the claim. They
are set together but mean different things — a curator can accept a component into `Active` while
leaving it `Derived` if they are accepting it provisionally rather than vouching for it.

### 7.2 The curation overlay — the hard problem

**Re-running the survey must not clobber human curation.** This is the single biggest design risk in
the whole feature. Without a solution, the second survey undoes every correction from the first, and
curators stop trusting the tool permanently.

Design: human decisions are recorded as a **durable overlay**, separate from the IR, keyed by stable
qualified name:

```
  raw IR (re-derived each run)  +  curation overlay (accumulated)  =  published blueprint
```

Overlay entries: renames, type overrides, merges, splits, rejections, manual additions, plus who
decided and when. Re-derivation regenerates the raw IR freely; the overlay replays on top before
projection.

Consequences to accept up front:

- Overlay entries can go **stale** — a rejected component whose code was deleted, a rename pointing at
  a component that no longer exists. Needs its own reconciliation surface, and it is the same
  divergence problem as `Backlog.md:13` in a new place. **Stale entries are marked
  `confidenceLevel = Obsolete`** (§3.3b) — *"comes from an obsolete source and must no longer be
  used"* is exactly this case, and it is a typed, queryable state rather than an RE-local flag. Note
  this is distinct from `ContentStatus.Deprecated`, which is a decision rather than a fact about the
  source (§3.3c).
- When re-derivation and the overlay **conflict** (detector now says `Software Service`, human said
  `Software Library`), the human wins, but the conflict must be **surfaced**, not silently swallowed.
  Silent precedence is how the tool starts lying.
- Overlay storage is RE-local (it is about RE's derivation process, not enterprise truth). That runs
  straight into the unsolved per-user partitioning problem — noted as **Q6**, not solved here.

### 7.3 Curation as RFA

LLM assistance in curation is scoped in §6.5(b): draft the rationale, propose merges and splits, triage
RFAs — the human still decides.

Low-confidence components and unresolved boundaries should raise `RequestForAction` annotations —
"component boundary uncertain, needs human review." This gives RFAs a second concrete use case beyond
survey findings, and connects to the open `Backlog.md:53` work on making RFAs real assignable Egeria
actions. Consistent with the funnel: derivation is cheap and automatic, human attention is spent where
confidence is low.

---

## 8. Churn and versioning

Re-deriving a blueprint on every survey would thrash GUIDs — and a blueprint has an order of magnitude
more elements than a survey report, so this is `Backlog.md:13` amplified.

Revised per §3.5: **`versionIdentifier` is the mechanism**, and because distinct versions surface as
separate catalog elements, the model is *snapshot-per-version*, not mutate-in-place.

### 8.1 What mints a new version

**Proposal: tie `versionIdentifier` to the repository's own release identity** — git tag, release, or
explicit pin. Rationale: a blueprint describes the architecture *of a particular version of the
software*, so blueprint versions should track software versions rather than survey-run timestamps.
Consequences:

- Re-deriving within the same release **upserts in place** — corrections, better detectors and curation
  all accumulate against that release's blueprint without minting versions.
- A new release mints a **new** blueprint version, seeded from the previous one so curation carries
  forward (§7.2 overlay replays onto it) rather than starting from a blank review queue.
- Repos with no release discipline need a fallback. **Resolved (Q10): a precedence chain**, taking the
  first that yields a value:

  1. **`git describe --tags`** from HEAD. This degrades gracefully rather than failing — `v1.2-14-gabc123`
     says *"14 commits past 1.2"*, which is itself the drift signal we want. **Truncate to the tag part
     for `versionIdentifier`** so it does not mint a version per commit; keep the full string as a
     property for precision.
  2. **Published package version** — PyPI, npm, Maven. Often present where git tags are not, and Syft
     (§5.6) surfaces it as a side effect of SBOM generation rather than as extra work.
  3. **`0.0.0+HEAD`** — a single always-upserting pseudo-version. Loses drift history, which is the
     honest outcome for a repo with no release identity at all; do not fake one.

### 8.2 Identity and qualified names

- **Stable qualified names remain load-bearing.** Revised:
  `{repo}::{versionIdentifier}::SolutionComponent::{stable-slug}` — the slug derives from the
  component's *identity*, never from its LLM-assigned display name, which will change between runs and
  must not break identity.

- **`{project}::` is deliberately dropped from the qualified name (Q7).** The architecture of a repo is
  a fact about the repo, not about whoever is looking at it; namespacing by project means two teams
  curate the same public repo twice and neither benefits from the other's work. Instead **the project
  is a link, not a namespace** — attach the blueprint to the owning project by collection membership.
  Q6's per-user partitioning then applies only to the **curation overlay** (§7.2), which is where
  view-dependence actually belongs, rather than forking the entire blueprint. Consequence to accept: the
  shared blueprint reflects whoever promoted last, so the rule is *shared blueprint = canonical
  curation; project overlays are proposals until promoted.*

- **Identity precedence (Q3), in order — revised after a real counterexample:**
  1. **Deployment unit** — compose/k8s service name, systemd unit, deployment-config directory.
  2. **Declared package name** — `[project].name`, `package.json` `name`, Maven `artifactId`. Survives
     directory moves; the right answer for code-first repos with nothing deployed.
  3. **Normalised module path** — strip conventional roots (`src/`, `packages/`, `lib/`) before slugging.

  **Why deployment unit leads (§8.2a).** An earlier draft had declared package name first, on stability
  grounds. `egeria-workspaces` disproves that ordering: it ships `PyegeriaWebHandler` twice, once for
  the QuickStart deployment and once for FreshStart, with the *same package name* and deliberately
  different admin behaviour. Package-name-first collapses two genuinely distinct components into one.

  **But "deployed separately" needs a floor, or the rule over-splits (§8.2b).** It means a separate
  deployed *artifact* — its own image, compose service, or deployment directory. It does **not** mean a
  runtime configuration flag. The same repo also selects between three runtime modes
  (`demo-quickstart`, `local-quickstart`, `freshstart`) via two flags in `demo_config.py`; those are one
  component with configuration, not three components.

- **Where a deployment context exists, it qualifies the slug**, otherwise identically-named packages
  collide within one repo: `egeria-quickstart::PyegeriaWebHandler` and
  `egeria-freshstart::PyegeriaWebHandler`. Deployment-unit names are at least as stable as package names
  here — the package name is the *same* for both — so leading with deployment costs nothing in
  stability.

  The doc previously listed these three as alternatives; the *precedence* matters more than the pick.
  Note the tension §8.2 names elsewhere: a raw module path **is** the directory, so `foo/` → `src/foo/`
  would mint a new component and orphan its overlay. Normalisation reduces this; a genuine rename is
  handled as an **overlay alias entry**, not by trying to detect moves.
- **Upsert by qualified name**, never create-if-missing-by-search.
- Note the tension: putting `versionIdentifier` in the qualified name makes versions cleanly separate
  but makes "the same component across versions" a join rather than an identity. That join is exactly
  what drift comparison needs, so it must be reliable — the stable slug is what carries it. **Q3**
  (component identity) is therefore *more* important under this model, not less.

### 8.2a Variants — components that share most of their code

The `PyegeriaWebHandler` case is not an oddity; it is the general **deployment-variant** problem, and it
needs a modelled answer because detectors will meet it constantly in repos that ship more than one
configuration.

Measured on `egeria-workspaces` (tracked, first-party files only):

| | |
|---|---|
| `egeria-quickstart/PyegeriaWebHandler` | 138 files |
| `egeria-freshstart/PyegeriaWebHandler` | 94 files |
| Shared relative paths | 90 — of which **60 byte-identical, 30 divergent** |
| Unique to quickstart / freshstart | 48 / **4** |

**Measure containment, not similarity.** Only 4 files are unique to freshstart, so freshstart is very
nearly a *subset* of quickstart: 96% of its files exist in the other component. Symmetric measures hide
this — Jaccard is 0.63 by path and 0.42 by identical content, which reads as "moderately similar" and
badly understates a near-containment relationship. Any duplication detector must report **directional
containment** as the primary figure.

**The 30 divergent files are the finding.** Some of that divergence is intentional — the deployments
have different admin requirements — and some is almost certainly drift. **No tool can tell those apart**,
which makes it exactly the right thing to raise as an RFA (§7.3): *"30 of 90 co-located files differ
between two components declared as variants — intentional?"* That is a genuinely useful question the
maintainer cannot easily ask today, and it is a better demonstration of this feature's value than the
component diagram.

### 8.2b Three tiers of "deployment" — and only one of them mints components

`egeria-workspaces` turns out to contain three structurally different things that all get called
deployments, and collapsing them is the main way this model goes wrong. Getting the tiers right is what
keeps blueprint counts sane.

| Tier | Example | Mints a component? | Mints a blueprint? |
|---|---|---|---|
| **Solution deployment** | QuickStart, FreshStart — full solutions, first-party code, different auth/admin models | **yes** | **yes** |
| **Optional runtime add-on** | the 11 under `optional-associated-runtimes/` — Airflow, Atlas, Dagster, Spark, DuckDB, Milvus, MLflow, Ollama, Prefect, Superset, Unity Catalog | yes — third-party components | **no** |
| **Runtime mode** | `demo-quickstart` / `local-quickstart` / `freshstart`, selected by flags in `demo_config.py` | **no** — one component, configured | no |

**The add-on tier is why "blueprint per deployment config" would be wrong.** Each of the 11 is one or
two compose files and 1–26 files total, with no first-party code — they deploy third-party runtimes into
Docker. Giving each its own blueprint would produce 13 blueprints for one repo, most of them containing
a single third-party component. They are **optional component sets that compose into a solution**, and
Collection membership (§3.3a) is exactly the mechanism: an add-on's components join whichever
blueprint(s) actually deploy them.

This is also the cleanest available test of the shared-membership model — 11 add-ons across 2 solutions
is a real composition problem rather than a hypothetical one.

**The runtime-mode tier is the trap.** Those three modes share code *and* directory, differing only by
flag. Any rule phrased as "deployed separately means separate components" splits them if applied
naively. The floor in §8.2 exists for this case.

### 8.2c The repo may document its own architecture in prose

`ENVIRONMENT_DIVERGENCE.md` in `compose-configs/` states the runtime-mode table, which files are meant
to diverge and why, and the rule for shared code. It exists because copying one environment's file over
the other's has repeatedly caused breakages.

Two consequences:

- **It largely pre-answers §8.2a's divergence RFA.** The 30 divergent files are not an open question
  for a maintainer who has read this doc — much of that divergence is documented as intentional. Raising
  an RFA that the repo already answers would be noise, and would make the tool look like it had not
  looked.
- **This is a *declared architecture* source that §5.1's table cannot consume.** It is prose, not a
  manifest — detector-invisible, but squarely readable by the LLM. So distillation's remit (§5.2) should
  include **reading the repo's own architecture and deployment documentation** before proposing
  boundaries. That stays inside the standing rule — the LLM is not inventing a component, it is reading
  a human's statement about one, which is the highest-confidence evidence available.

Where such a doc exists, it should be treated like `catalog-info.yaml`: declared, and outranking
inference.

**Do not model this with `KnownDuplicate` / `PeerDuplicateLink`** (0465, `OpenMetadataType.java:4415`,
`:4425`). Their semantics are *deduplication* — "duplicate resolution processing is required", i.e.
these are the same thing and should be consolidated. Applying them here would instruct the catalog to
merge two components that are deliberately separate. This is the same wrong-semantics trap as
`Incomplete` in §3.4.

They are, however, exactly right for the **other** case the same detector finds: accidental copy-paste
that *should* be one component. So the detector emits a candidate and the human classifies it, and the
classification picks the representation:

| Human verdict | Representation |
|---|---|
| Intentional variant | two `SolutionComponent`s, no duplicate link; overlap recorded as an annotation |
| Accidental copy | `KnownDuplicate` + `PeerDuplicateLink`; resolution required |

A concrete instance of §7.3's "curation as RFA", with real Egeria types behind each branch rather than
a review screen for its own sake.

### 8.3 Drift

Compare blueprint version A against version B as two element sets, matched on stable slug:
components added / removed / reclassified, wires added / removed, ports changed direction. This is a
straightforward set diff rather than a temporal query, and it reads naturally as "what changed
architecturally between release 1.2 and 2.0."

Instance versioning / `asOfTime` stays available as the within-version audit trail — who corrected
what, when — but is not the drift mechanism.

### 8.4 Prerequisite

Reliable writes. RE's publishers are fire-and-forget today — **re-derived from the code, not
cited**: an earlier version of this sentence attributed the phrase to the current-state doc §0 and
it does not appear there at all (checked 2026-08-26, zero occurrences). The characterisation holds;
the citation did not, and a false citation is worse than none because it stops the next reader
checking. This feature writes far more elements per run.

**CORRECTED 2026-08-29 — annotation identity is NOT the blocker this section previously described.**
The paragraphs that stood here (written 2026-08-26) said an annotation's qualifiedName carries the
run timestamp and a positional index, that no stable substitute exists (134 annotations across 7
types on `egeria_workspaces_git`), and therefore that the prerequisite had a prerequisite: a change
to the annotation model. **That analysis conflated two different things and overstated the work.**

The two things:

1. **Retrying one publish** — the case an outbox actually serves.
2. **Converging a later survey run onto an earlier run's annotations** — which Egeria's survey model
   never asked for.

**For (1) the identity is already stable.** `SurveyResult.surveyed_at` is
`field(default_factory=datetime.utcnow)` (`survey_report.py:109`) — stamped when the result is
*constructed*, at survey time, not at publish time. An outbox stores the payload, so a retry replays
the same `surveyed_at` and the same list order and produces byte-identical qualifiedNames. The
timestamp is not a defect; it is the run's identity, which is exactly what
`Annotation::{slug}::{surveyed_at}::{i}` is for, and the index is stable within a stored payload.

**For (2) divergence is correct behaviour.** A `SurveyReport` *is* a dated record of one act of
analysis, so each run legitimately mints its own with its own annotations beneath it — visible in
RE's own bookkeeping, where `deep_causality` carries 10 distinct `egeria_report_guid` values over
three days. Converging run B onto run A would destroy survey history rather than protect it.

So the 134-vs-7 collision measurement was real but answered a question nobody needs to ask, and the
cross-wire hazard is reachable only by attempting cross-run convergence — which is now explicitly
not the plan. **"Remove the timestamp" remains the wrong move**, but for a better reason than first
given: it would collapse distinct survey runs into one.

**What is genuinely missing is narrow and publisher-layer.** `_create_annotations` calls
`create_annotation` blind, where `_find_or_create_asset` (`egeria_publisher.py:277`) and
`publish_sub_resources` both search by qualifiedName first and are already safe to retry. The real
failure mode is a crash after Egeria wrote the annotation but before the outbox recorded success;
replaying that row would create a duplicate. Two things settle it, neither a model change:

- **Verify whether Egeria enforces qualifiedName uniqueness on annotations** — a test against a live
  server. `_find_or_create_asset` searches rather than relying on a uniqueness error, which hints it
  does not, but that is an inference from how the code is written, not a verified fact.
- **Generalise lookup-then-create to annotations**, which the deduplication of the three publishers'
  near-identical `_create_annotations` was going to do anyway.

**Net: annotation identity does not block the outbox.** It is one publisher-layer change plus one
live-server check.

The visibility ordering written here in the earlier version still holds as a way of thinking about
the failure modes — a *missing write* leaves a gap someone eventually notices; a *duplicate* is
harder to see, because everything expected is present and merely repeated; a *cross-wire* is hardest
of all, because the right number of results are there, each well-formed, with only their content
attached to the wrong thing.

Design in `docs/outbox-publishing-design.md` (D2, §4 and top of §6's sequencing).

**The outbox/retry work is a prerequisite, not a nice-to-have** — a
half-published blueprint is worse than none.

---

## 9. Information Supply Chains — scoped down

Agreed: ISCs are the weak half, and per your steer we are **not** promising automated ISCs.

- A blueprint is a static structure readable from one repo. An ISC is an end-to-end *business* flow,
  usually spanning repos, carrying a name only a human or a well-briefed agent can assign.
- Within a single repo an ISC is often either trivial or meaningless — real supply chains cross
  system boundaries.
- What we *can* do cheaply: because `iscQualifiedNames` lives **on the wire** (§3.3), ISC attribution
  is a labelling pass over a wire graph we already have. Once several repos are analysed, path-finding
  across the combined graph yields ISC **candidates**.
- **Position: derive wires, offer candidates, let humans/agents name and bound them.** Deferred to a
  later phase; explicitly not in the Phase 1–5 plan below.

---

## 10. Plan

Revised after the §5.5–5.7 tooling pass and §6.0's simplification. Two prerequisites moved earlier;
Phase 4 got substantially cheaper.

### Phase 0 — Spike (dogfood)
**Planned in detail: `docs/architecture-recovery-phase0-plan.md`.**

Run detectors against three targets chosen to test different things — `egeria-workspaces` (via the
current `-fs` checkout) as the richest case, covering code-versus-deployment reconciliation, polyglot
detection, duplicate-component identity, and the vendored-noise problem above; `trellis`/RE as the
premise test (it has **no** deployment artifacts at all, so code-level markers must carry the whole
partition); and `egeria` for scale. Compare the three §5.5
signals against a **pre-registered** hand-written partition, without LLM help.

Exit criteria are pass / **qualified pass** / fail, decided in advance. The qualified pass — boundaries
recovered only where a package manifest declares them — is the most likely outcome and changes the
Phase 1 estimate rather than killing the feature.

Standalone throwaway scripts over local checkouts: no RE integration, no Egeria, no Prefect, no
registry writes. A negative result must cost nothing to discard.

Secondary, independent of the result: time `scc` and `lizard` to test §5.6's Discovery-tier cost claim.

### Phase 0.5 — Infrastructure prerequisites
Small, but both block later phases and neither is a detail:
- **`git_clone_root` `ResourceProvider`** (treeless clone) alongside `_acquire_zipball_root` — without
  it Q11's history metrics have no data source (§5.7 gap 2).
- **Binary provisioning** — pin `scc`, `ast-grep`, `syft`, `trivy` into the RE image with a version
  probe feeding `analyzerVersion` (§5.7 gap 3).

### Phase 1 — Detectors + IR, no Egeria writes
Implement §5.1's detector table **as ast-grep rules plus config parsers**, the §5.3 IR, and §5.4's
evidence into `project_analysis_findings`. Declared-architecture sources (§5.1) short-circuit inference
where present. Distillation heuristics only — no LLM yet. Add the §5.7 steps to `STEP_REGISTRY` and
`analysis_catalog.yaml`. Output viewable in RE. Testable with zero Egeria dependency.

### Phase 2 — Egeria projection at Draft
Blueprint, components, subcomponents, ports, wires, `ImplementedBy`. All at `ContentStatus = Draft`.
Stable qualified names and upsert per the revised §8.2 — **no `{project}::` prefix**; attach to the
project by collection membership. `ImplementedBy` via
`GovernanceOfficer.link_design_to_implementation`, populating `role` and `designStep` (§3.6).
`versionIdentifier` per §8.1's precedence chain. `Confidence` classification on components and ports —
`confidenceLevel = Derived`, `confidence` 0–100, `source` = analyzer id (§3.3b); wires excepted (§3.3),
their confidence riding on the connected ports.
**Prerequisite:** outbox/retry publishing (§8.4). *(The confidence-level set is no longer a
prerequisite — the stock `ConfidenceLevel` values are used unextended.)*

### Phase 3 — Curation
Curate-intent review surface, the overlay (§7.2), per-component promotion through `ContentStatus`,
RFAs for low-confidence components. Overlay is keyed by the same `scope_locator` as everything else.

### Phase 4 — Component-scoped analytics
**Substantially cheaper than originally scoped (§6.0):** a component is a path prefix, so this is
largely running existing `accepts_scope_locator=True` steps once per component and projecting the
result — not a new aggregation layer. Publish §6.2's attributes as **one annotation per analyzer per
component**. Interim carrier per §6.4; swap to the typed annotation when it lands, re-deriving rather
than migrating.

Given how much cheaper this became, consider pulling a slice of it into Phase 1 — component-scoped
metrics with no Egeria write are the most legible demonstration that the partition is real.

### Phase 4.5 — `AnnotationAgent` + `ArchitectureAgent` (§6.5c)
Generic Q&A over `annotation_types` / `project_analysis_findings` / `project_analysis_metrics`, then the
architecture specialisation over the blueprint graph. Embed the IR as an `architecture` collection.
**Sequencing is genuinely open (Q14)** — `AnnotationAgent` has no dependency on this feature and would
be useful today; it is placed here because architecture recovery is what makes it compelling.

### Phase 5 — LLM distillation + drift
Add LLM naming/classification within §5.2's rule (never invents components) and §5.6's cost gate (only
below a confidence threshold, only small prompts). Add the §8.3 drift comparison and reporting, with
`ArchitectureAgent` as its natural-language front end.

### Deferred
ISC candidate derivation (§9). Defining Egeria's 0780 model (§3.7). Call-graph tooling (Joern/SCIP)
unless Phase 0 shows detectors are insufficient — and if so, via SCIP's protobuf index rather than
framework adoption (§5.6).

---

## 11. Open questions

**Resolved in this revision** (answers given in review, grounded against the Egeria checkout where they
made a type claim):

- ~~**Q1** — Where is the `ImplementedBy` write path?~~ **RESOLVED:**
  `GovernanceOfficer.link_design_to_implementation` (`governance_officer.py:2943`), body carries
  `ImplementedByProperties` (`designStep`, `role`, `transformation`, `description`,
  `iscQualifiedName`). Phase 2 unblocked.
- ~~**Q2** — Can `ContentStatus` be set per component?~~ **RESOLVED:** yes — settable on any authored
  `Referenceable`, as an ordinary body key. Per-component promotion works; §7 stands.
- ~~**Q3** — component identity for qualified names?~~ **RESOLVED: module path**, refined into a
  precedence chain — **deployment unit → declared package name → normalised module path** (§8.2), with
  the deployment context qualifying the slug where one exists. Renames are handled as overlay aliases,
  not by move detection.

  *Revised once more* after `egeria-workspaces` supplied a counterexample: it ships `PyegeriaWebHandler`
  twice under the same package name for two different deployments, so package-name-first would have
  merged two deliberately distinct components. Deployment unit now leads (§8.2a).

  This answer carries far more weight than expected either way: it makes a component a **path prefix**,
  which is what §6.0 builds the entire analytics story on.
- ~~**Q4** — where do evidence and confidence live?~~ **RESOLVED, in two halves.**
  *Confidence:* the `Confidence` classification, confirmed against `Referenceable`
  (`OpenMetadataTypesArchive1_2.java:6951`, §3.3b) — `confidence` int 0–100 matches RE's existing scale,
  `confidenceLevel` carries provenance using the stock `ConfidenceLevel` values unextended, `source`
  carries the analyzer id, `steward` carries the curator. §5.4's proposed `derivation` field was a
  reinvention of `confidenceLevel` and has been removed.
  *Evidence:* stays **RE-side** in `project_analysis_findings` (§5.4), which already has the exact shape
  including `scope_locator`, `confidence` and `detail_json`. Egeria receives the *reasoning* in typed
  base-`AnnotationProperties` fields (`expression`, `explanation`, `analysisStep`). Nothing in
  `jsonProperties`.
  *Carry-over:* wires cannot be classified (§3.3) — wire confidence rides on the connected `SolutionPort`s.
- ~~**Q5** — conflict-resolution UX?~~ **RESOLVED:** part of curation and RFAs (§7.2, §7.3). The
  requirement that conflicts be **surfaced rather than silently resolved** stands unchanged.
- ~~**Q7** — personal or shared project?~~ **RESOLVED, but not as originally asked.** The project is a
  **link, not a namespace**: `{project}::` is dropped from the qualified name and the blueprint attaches
  to the owning project by collection membership (§8.2). Per-user divergence lives in the overlay, not in
  duplicated blueprints.
- ~~**Q8** — monorepos?~~ **RESOLVED: one blueprint per *deployable solution*** — usually one per repo,
  but not always, and `egeria-workspaces` is the exception that shows why: it ships **two** solution
  deployments (QuickStart and FreshStart) from one repo, each with its own component set and auth model.
  Forcing them into one blueprint would misrepresent both.

  **"Solution deployment" is doing precise work in that sentence** — see §8.2b's three tiers. The same
  repo also carries 11 *optional runtime add-ons* and 3 *runtime modes*, and neither mints a blueprint.
  Counting every deployment artifact would yield 13+ blueprints for one repo, most holding a single
  third-party component.

  Blueprints being Collections (§3.3a) makes this work cleanly: the two solution blueprints **share** the
  `shared-infra.yaml` components (`kafka`, `postgres`, `kroki`, `proxy`), optionally admit the add-ons'
  components, and hold their own variant components (§8.2a). Shared membership rather than duplication.

  **Corrected 2026-08-29 — the "blueprints nest" half IS available.** This previously read "not
  available", reasoning from the absence of a blueprint-to-blueprint relationship. But a
  `SolutionBlueprint` is a `Collection` and `CollectionMembership` admits any `Referenceable`, so a
  blueprint nests inside a blueprint through the ordinary mechanism — full type chain in §3.3a. Note
  this entry's own example already assumed **two** blueprints in one repo, which the old §3.3a
  ("one blueprint per repo") contradicted; §3.3a was the outlier and has been corrected.
  Component-to-component nesting via `SolutionComposition` remains separately available, and
  Collection membership still gives what it always gave: a component can belong to several
  blueprints, which is how cross-repo composition and §9's estate-wide ISC candidates would work.
- ~~**Q9** — where do Phase 4's metrics land?~~ **RESOLVED:** `CodeAnalysis` as an Annotation subtype
  (§6.1), base `Annotation` + `additionalProperties` as the interim carrier (§6.4). Further resolved in
  this revision: **one annotation per analyzer per component** (§6.2), not one aggregate.
- ~~**Q10** — what mints a version with no release discipline?~~ **RESOLVED:** releases, per the
  precedence chain in §8.1 — `git describe --tags` truncated to the tag → published package version
  (PyPI/npm/Maven, surfaced free by Syft) → `0.0.0+HEAD` always-upsert.
- ~~**Q12** — author a `confidenceLevel` valid-value set?~~ **RESOLVED: no — use the stock
  `ConfidenceLevel` values unextended** (`refdata/ConfidenceLevel.java`, §3.3b). They read as a poor fit
  only if read as a degree scale; they are a *provenance* scale, and `Derived` / `Authoritative` /
  `Ad Hoc` / `Obsolete` map onto this feature's cases almost verbatim — `Obsolete` in particular gives
  §7.2's stale overlay entries a typed home they previously lacked. Degree stays on `confidence`
  (int 0–100), workflow stays on `ContentStatus`; three orthogonal axes, all typed (§3.3c).
  **Phase 2 loses a prerequisite as a result, and no upstream type change is needed.**
- ~~**Q14** — does `AnnotationAgent` ship inside this feature or ahead of it?~~ **RESOLVED: ahead of
  it.** It has no dependency on architecture recovery, works against every analysis RE already runs, and
  is possible only because `project_analysis_findings` / `project_analysis_metrics` are generic. Split
  out as its own piece of work; §6.5c and Phase 4.5 describe the content, not the sequencing.
- ~~**Q11** — the sibling annotation type for repository history?~~ **RESOLVED in principle:** we define
  our own annotation types, as several other analyses will need anyway. Structurally it stops being a
  special case once §6.2's one-annotation-per-analyzer rule holds — history is just another analyzer.
  **But it has a real prerequisite:** git history is not in a zipball, so it needs the `git_clone_root`
  resource provider (§5.7 gap 2). Not optional if §6's value case is to be met in full.

**Still open:**

- **Q6** — overlay storage and per-user partitioning. Narrowed but not solved: §8.2 now confines it to
  the curation overlay rather than the blueprint, which makes it a smaller problem than it was. Still
  the third instance of an already-unsolved problem; do not solve it here, but do not accidentally
  re-solve it badly either.
- **Q13** — which §6.2 metrics justify *typed* properties versus `additionalProperties`. Deferred to
  after Phase 0, as before — but note §5.6's tool choices (`scc`, `lizard`) make multi-language
  extraction achievable for more of the set than the original hedge assumed, so the typed set can
  probably be larger than §6.3 implies.

---

## 12. Assessment

**Feasible** — blueprints yes; ISCs only semi-automatically, and scoped out accordingly.
**Worthwhile** — first RE analysis producing design metadata, and it rescues several orphaned
analyses by giving them a granularity worth publishing at (§6).
**Innovative** — architecture recovery is a decades-old research area and C4-from-code tools exist;
what is unusual is targeting a governance catalog's design types rather than a diagram, so the output
is queryable, linkable to glossary and governance, and diffable over time. The novelty is the
destination, not the extraction.

**Biggest risk** is not extraction accuracy — it is §7.2. A tool that discards human corrections on
every re-run will be abandoned regardless of how good its detectors are.

**Two things changed the shape of this after review.** First, Q3's answer makes a component a path
prefix, which collapses §6 from a new aggregation layer into a loop over machinery RE already has —
the payoff section got much cheaper to build. Second, the annotation-Q&A generalisation (§6.5c) is a
larger prize than architecture recovery itself: it makes *every* analysis RE runs askable, and it is
available cheaply because the findings and metrics tables are generic. Architecture recovery is the
thing that makes it compelling, not the thing that makes it possible.

**Readiness:** every design question that blocked planning is answered, and nothing that remains blocks
a phase. Q6 is deliberately out of scope (and now confined to the overlay rather than the blueprint);
Q13 is correctly deferred to after Phase 0, since it is a question Phase 0 exists to answer. Notably,
**no upstream Egeria type change is on the critical path** — the stock `ConfidenceLevel` values, the
`Confidence` classification, `ContentStatus`, and base `AnnotationProperties` cover the model as
designed, with the typed `CodeAnalysis` annotation being a swap rather than a blocker (§6.4).
**This is plannable.**
