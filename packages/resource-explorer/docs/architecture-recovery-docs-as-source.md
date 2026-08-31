# Architecture Recovery — Documentation as a *source*, not only a lens

**Status:** §9 step 1 is BUILT (2026-08-31) — the unmatched-term population is now persisted
durably and uncapped under `check_name="undetected_term"`. **§9 step 2 has been run, and its
answer is negative: none of §5's three proposing tests separate overview from corpus, and one
of them inverts.** See §5a. Step 3 therefore does not start. Originally a design note recording a
decision (Dan, 2026-08-29: *"no scope_locator is fine"*) and the measurement that forces it.

Extends design doc **§5.5a** (documentation is a source, a dated source, and a
signal) and **§4.1** (four perspectives). It does not revise them; it closes the
gap between what §5.5a argued for and what was actually built.

---

## 1. The measurement

§5.5a made a strong, well-evidenced case for the **outward hop**: across twelve
repos, zero have an `ARCHITECTURE.md` at root, two have architecture docs
findable in-repo by name, and every one of the five checked has a separate,
actively-maintained docs repo. Step 0 without the hop would find architecture in
2 of 12 cases.

The hop was built. `github/doc_locations.py` resolves in-repo docs, sibling
repos, homepages and doc sites, and it works — on the corpus it locates a
document for 13 of 46 gate-approved repos, 4 in-repo and 9 in a sibling
repository. **The locating is not the problem.**

This is what it yields, latest `lens_run` per repo, read from
`project_analysis_findings` under `architecture_doc_lens`:

| repo | where the doc was found | components it named |
|---|---|---|
| `milvus` | in-repo | 22 |
| `egeria_workspaces_git` | in-repo | 12 |
| `sqlglot` | ingested-site | 6 |
| `amundsen` | in-repo | 4 |
| `enterprise_inference` | sibling-repo | 3 |
| **`egeria_git`** | **sibling-repo (`odpi/egeria-docs`)** | **1** |
| `monocle` | sibling-repo | 1 |
| `deep_causality` | ingested-site | 0 |
| `docling_eval` | sibling-repo | 0 |
| `docling_java` | sibling-repo | 0 |

Egeria is the case that motivated the outward hop, and it is the case that fails
hardest. `odpi/egeria-docs` was located and read. Egeria has **1,028 recovered
components — 999 of them labelled `logical`**. The document named **one**.

And the one is vacuous. Here is the entire match:

```
scope: open-metadata-resources/open-metadata-archives/core-content-pack/
       src/main/java/org/odpi/openmetadata/contentpacks/core/egeria
summary: named 'egeria' in the architecture document
```

A directory called `egeria`, matched on the term `egeria`, in a document about
Egeria. The real answer is **0 of 999**, on the best-documented system in the
corpus, with its documentation successfully fetched.

**That is not a matching-quality problem, and no amount of better string
matching fixes it.** The document names `Common Services`, `OMAS`, `OMVS`,
`View Server`, `Integration Daemon`. The pipeline proposed 999 Java package
paths. There is nothing to join.

## 2. Why the lens cannot fix this, stated as a rule it already breaks

§4.1 is explicit: *a component is only ever comparable to ground truth in its
own perspective*. That rule was learned expensively — the Phase 0 spike scored
16/16 on `egeria-workspaces` and 1 of ~10 on `trellis`, and the difference was a
deployment-perspective detector scored against a logical-perspective ground
truth.

The doc lens does the same thing. It joins a document that describes the
**logical** architecture against components that carry `perspective="logical"`
as a *label the proposer asserted*, not as a property of the evidence.
`coupling.propose()` emits:

```python
Component(slug="coupling::" + sub.replace("/", "::"), type=None,
          identity=Identity("module-path", sub), ...,
          perspective="logical", ...)
```

`identity.method` is `module-path` — a physical fact about the file tree — and
`perspective` is `logical` on the next line. Coupling establishes a *boundary*,
and the module docstring is scrupulous about that (`type` is deliberately left
`None` because "coupling establishes a BOUNDARY, not a
`SolutionComponentType`"). But the perspective field carries no such caution.
999 directory paths are filed under the same word as `OMAS`, and the lens joins
on the word.

**The consequence:** the only genuinely logical-perspective source in the whole
pipeline — the prose a human wrote to describe the system as a system — is the
one input that is forbidden from proposing anything.

`arch_lens`'s own guard says it out loud. When it has nothing to work with it
reports *"no components to label — the lens ran, the step it annotates has
not."* It is structurally downstream of detect and coupling and can only ever
attach labels to what they produced.

## 3. The decision

**A documentation-derived component may exist without a `scope_locator`.**

This is the crux, and it is what makes docs a source rather than a labeller. If
a component must name a path, the pipeline can only ever recover structure the
file tree already spells out — which is precisely the structure that produced
999 unreadable candidates for Egeria. If it need not, then `Common Services`,
`OMAS` and `OMVS` can exist as logical-perspective components proposed by the
document, and be bridged to code by `ImplementedBy` when — and only when —
something maps them.

`ImplementedBy` is already §4.1's designated bridge between Logical and the
other three, and §3.6 resolved its write path
(`GovernanceOfficer.link_design_to_implementation`). Its `role` and `designStep`
properties are the typed home for *how* a package implements a documented
component. This decision does not invent a mechanism; it supplies the mechanism
with the one thing it currently lacks — a logical-perspective component that was
not derived from a directory.

## 4. What actually changes, and what does not

Smaller than it sounds. `scope_locator_for()` **already** tolerates a component
with no `files`:

```python
files = component.files or []
if files: ...
# A files-less component (compose-derived, §8.2b's add-on and shared-infra
# tiers, which own no first-party code) has no path prefix to use, so the
# join key falls back to its slug.
return component.slug or component.identity.value
```

So a doc component keys on its slug, exactly as a compose service does, and the
store, the metrics table and the evidence join all work unchanged.

**The semantic difference is real even though the plumbing is not.** A
compose-derived component is files-less but *located* — it has a deployment
context and a compose file that declares it. A doc-derived component is
files-less and *unlocated*: nothing in the repository points at it. That
distinction must be carried explicitly, because §4.1c is the standing lesson on
exactly this failure — `scope_locator` already means two things, the collision
was harmless, and the *missing distinction* was the damage.

Three things to carry, all in fields that exist:

| carry | where | value |
|---|---|---|
| identity is documentary, not derived from a path | `Identity.method` | a new rung, `"documented-name"` |
| the component was never located in the tree | `Component.files` | empty, plus an explicit `located=False` in the persisted detail |
| provenance is the document, not inference | `confidence_level` | `"Authoritative"` where the doc is the project's own, per §3.3b |

`Identity.method` is a closed `Literal["deployment-unit", "package-name",
"module-path"]`. Adding `"documented-name"` is the one type change this needs,
and it is the right place: §8.2's precedence chain exists so a reader can tell a
strong identity claim from a weak one, and "the maintainers named it" belongs on
that chain rather than hidden in a detail blob.

**`type` stays `None`**, for coupling's reason. A document naming `OMAS` does
not tell us it is a `Software Service` rather than a `Software Library`. Emitting
a component with no type is already a supported shape.

## 5. The gate is the hard part, and the existing one does not transfer

`architecture_doc.undetected_is_meaningful()` already decides when unmatched doc
terms are worth reading. Its rule is a comparison, not a threshold, and it is
well argued:

> `terms <= components` needs no constant, cannot be quietly adjusted to make a
> number look better, and states the claim it rests on: **emphasis at scale is
> structure, not naming.**

Measured, the shapes are not close — `amundsen` 4 terms / 43 components, 100%
matched; `milvus` 1140 terms / 206 components, 2%.

**Do not reuse this gate for proposing.** It licenses *reading* — "these
unmatched terms are worth a human's attention" — and proposing is a much stronger
act. Two reasons, and the second is the serious one.

1. **The list is currently capped and non-durable.** `undetected[:50]` reaches
   the survey report's `json_properties`; `_record_run` persists only
   `{"documented": N, "evidence": ..., "kind": ...}`. Nothing about the
   unmatched population survives in the store. A source must be persisted like
   one.

2. **The denominator is the problem the gate is being asked to solve.** The rule
   passes when `terms <= components`. Egeria has 999 components — so essentially
   any document passes, *because* recovery was noisy. The repos where docs are
   most needed are the repos with the most candidates, and therefore the repos
   where this gate is most permissive. It is circular, and it is circular in the
   dangerous direction.

   It is not wrong for its own job: it asks "is this document an overview or a
   corpus of design docs?", and component count is a fine proxy for repo size
   there. It is wrong the moment the answer authorises writing.

**What a proposing gate should key on instead** — the shape of the *document*,
not the count of what recovery produced:

- **one document, not a corpus.** Milvus's 1140 terms come from 25 design
  documents; its architecture overview alone is the artifact §5.5a actually
  argued for. Proposing from a corpus proposes a table of contents.
- **the terms are structurally sibling** — one heading level, one list — rather
  than scattered across a document's whole depth.
- **an explicit self-description.** Milvus's page is *labelled* "logical
  architecture". §5.5a already noted this and it is the strongest available
  signal that the author intended these names as components.

That is a design sketch, not a specification, and it should be **measured before
being built** — the count is small enough to read by hand across the 13 repos
with a located document, which is the cheapest possible way to find out whether
the three tests above separate the cases.

## 5a. §9 step 2, run 2026-08-31 — the three tests do not work

Measured on the five repos that actually produce unmatched terms. The other six of the eleven
with a `lens_run` row yield zero — everything matched (`amundsen`) or no document was read — so
they cannot discriminate anything and are excluded rather than counted as passes.

| repo | sources read | terms | doc chars | modal heading level | self-describes | existing gate |
|---|---|---|---|---|---|---|
| `monocle` | 2 | 18 | 3,467 | 55% | no | usable |
| `egeria_git` | 1 | 30 | 18,231 | 50% | no | usable |
| `enterprise_inference` | 1 | 352 | 156,353 | 54% | **yes** | not usable |
| `egeria_workspaces_git` | 1 | 1,728 | 249,860 | 48% | no | not usable |
| `milvus` | 5 | 1,137 | 421,965 | 45% | **yes** | not usable |

**Test 1 — "one document, not a corpus" — fails.** The hypothesis was that a corpus shows up as
many documents; §1 cites Milvus's 1,140 terms coming from 25 design documents. But
`egeria_workspaces_git` reads **one** source and yields **1,728 terms** — more than Milvus's five
sources combined. A single document can be a corpus by itself, so source count does not separate,
and the test as written would license proposing from the noisiest document measured.

*Enabling detail, not previously recoverable:* `lens.evidence` records only the **first** source
that read, while terms are extracted from every readable source concatenated — so `docs/design-docs`
silently fronted five documents. `sources_read` is now persisted alongside each term; without it
this test could not have been evaluated even in principle.

**Test 2 — "terms are structurally sibling" — fails.** All five documents sit between 45% and 55%
of headings at their modal level. The two the existing gate calls usable (50%, 55%) fall *inside*
the range of the three it rejects (45%, 48%, 54%). No discrimination at all.

**Test 3 — "an explicit self-description" — inverts.** The two documents whose opening announces
"architecture" are `milvus` and `enterprise_inference` — the two largest corpora. Neither of the
two usable documents self-describes. Selecting on this test picks exactly the wrong documents. In
hindsight the mechanism is unsurprising: a large documentation site has "Architecture" in its
navigation, while a small focused overview is often titled with the project's own name.

**What does separate, and was not hypothesised: size.** Document length and term count both split
the sample with an order-of-magnitude gap — 3.5k/18k chars and 18/30 terms on one side, 156k/250k/422k
and 352/1,137/1,728 on the other. This is offered as an observation, **not as a proposed gate**:
it needs a threshold constant, which §5 explicitly argues against ("needs no constant, cannot be
quietly adjusted to make a number look better"), and n=5 cannot set one honestly.

### Limits of this measurement, stated rather than buried

- **n=5.** Three tests judged against five documents. A negative result on five is enough to stop
  step 3; it would not have been enough to start it.
- **Test 2 was measured by proxy.** The test speaks of *the terms* being structurally sibling;
  `extract_terms` returns a flat list with no record of which pattern (heading / bold / code span)
  or heading depth produced each term. What was measured is the *document's* heading distribution.
  Instrumenting term provenance is the honest version and was not done.
- **Test 3 used a permissive regex over the first 400 characters** — "architecture" with an
  optional qualifier. §5's actual example is Milvus's page being *labelled* "logical architecture".
  A stricter reading was not tested, and the 400-character window is this measurement's choice,
  not the design's.

### What follows

§9's own instruction — *"Step 3 should not start until step 2 has a number attached to it"* — is
satisfied, and the number says no. Docs-as-source does not proceed on these tests. Either a
different discriminator is found and measured on a larger sample, or documentation stays a lens.

Nothing about §3's decision (a doc-derived component may exist without a `scope_locator`) is
overturned; it was never the blocker. The blocker is deciding *which documents earn the right to
propose*, and that question is still open.

## 6. Staleness is not optional here

§5.5a(b) established that a prose architecture describes a *version*, and that
the version is recoverable — upper bound from the newest dead path a document
cites, lower bound from the churn of live paths it omits, four API calls, no Go
read. It applied that symmetrically: *"a recovered blueprint that cites paths
deleted two years ago is stale in exactly the same measurable way."*

While docs are a lens, staleness degrades a label. **Once docs are a source,
staleness manufactures components** — a document naming `internal/indexcoord`
would propose a component for a thing deleted in 2023.

So the dating in §5.5a(b) stops being an enhancement and becomes a
precondition: a doc-derived component must carry the document's date bounds in
its evidence record, and a proposal from a document dated outside the current
code's window is a *finding about drift*, not a component. This is the same
discipline §4.1a applied to compose files — describe what the artifact says
without asserting the thing exists.

## 7. What this must not become

The lens's founding rule is right and survives intact for the lens:

> A document that disagrees with the code is a **finding**, not a correction.
> "The doc names a component we did not find" is one of the more useful things
> this system can say, and silently adopting it would destroy exactly that.

Docs-as-source does not overturn that — it changes what *adopting* means. A
doc-derived component is a **proposal published to a curator** (see
`architecture-recovery-report-then-curate.md`), never a materialised blueprint,
and it is marked as proposed-by-documentation so the disagreement stays legible
rather than being laundered into agreement. The failure mode to avoid is a doc
component and a code component silently merging into one thing that looks
corroborated; §4.2's "map, never merge" is the standing rule and applies
unchanged.

## 8. Honest limits

- **Nothing here is measured on the proposing side.** Section 5's three tests
  are a hypothesis. The only measurements in this note are of the *existing*
  lens.
- **It will not help the 33 repos with no located document**, which is most of
  them. This raises the ceiling on the well-documented cases; it does nothing
  for the rest.
- **`arch_lens` runs after detect and coupling.** Docs-as-source needs a
  proposer that runs *alongside* them, which is a pipeline-ordering change this
  note does not design.
- **It does not fix Egeria's 999.** A handful of correct logical components
  beside 999 directory candidates is still 999 directory candidates. The
  clustering work and this are complementary, and neither substitutes for the
  other.

## 9. Staging

1. Persist the unmatched-term population properly — durable, uncapped, under its
   own `check_name`. Costs nothing, is reversible, and is the only way to
   measure section 5 at all.
2. Read the 13 located documents by hand against the three proposing tests.
   Report whether they separate overview from corpus.
3. Only then: `Identity.method += "documented-name"`, a doc proposer running
   beside detect, and locator-less components flowing to the curator.

Steps 1 and 2 are the ones worth doing next. Step 3 should not start until step
2 has a number attached to it.
