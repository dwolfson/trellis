# Repo context, and routing a bag of tools

**Status:** design note. Nothing here is built beyond the one worked example named in §3.
Written 2026-08-31 from Dan's direction, after Phase 2 of architecture recovery produced a
proposal that was unreadable for the repo the feature exists for.

---

## 1. The thesis, in Dan's words

> There is a high degree of diversity in both what repos hold, how they are structured, what
> their intended use is and how they are maintained. It seems that we need a bag of tools that,
> over time, will help us refine which tools are appropriate for which repos. Documentation is a
> good indicator for a strong open source project — but not at all useful for a repo containing
> tutorials.
>
> I doubt there will be a single magic bullet. We have to extract some context — is the repo
> code, is it deployable, is there embedded documentation, is there a documentation site — and
> then apply different analyses to see what we can discover.

This note takes that as settled and works out what it costs.

**The failure it is a response to.** Architecture recovery runs the same pipeline on everything.
On `egeria_git` that yields 878 live components — Java package paths — while the project's own
documentation describes it as Common Services, OMAS, OMVS, View Server and Integration Daemon.
`docs/architecture-recovery-docs-as-source.md` §1 measured the join between those two sets at
**zero**, and was blunt that no amount of better matching fixes it. The pipeline was not wrong;
it was the wrong pipeline for that repo, run because nothing decides which pipeline to run.

## 2. Most of the parts already exist, which changes what this is

The instinct is to design context extraction. It is largely built.

**`repo_classification` is the context extractor.** It already emits, per repo:

| finding | what it says |
|---|---|
| `repo_role` | library / application / middleware / tool / tutorial / samples / documentation |
| `expected_readme`, `expected_architecture`, `expected_examples`, `expected_deployment`, `expected_changelog`, `expected_api-reference` | where each artifact class should live, and whether it does |
| `architecture_recovery_gate` | run / skip, with a stated reason |

Measured across the corpus 2026-08-31 — 53 classified repos. **`repo_role` is multi-valued**:
`label` carries the primary role and `detail_json.roles` the full list.

```
primary role only : samples 16 · application 13 · documentation 11 · tutorial 5 ·
                    library 5 · middleware 2 · tool 1
ALL roles counted : application 27 · library 27 · samples 21 · tool 15 ·
                    documentation 11 · tutorial 8 · middleware 3
roles per repo    : 1→24  2→9  3→12  4→6  5→2
gate               : run 45 · skip 8
```

**More than half the corpus — 29 of 53 — is genuinely plural**, and one repo carries five roles.
This is the strongest single argument for Dan's framing, and it was nearly missed: counting only
the primary label gives a tidy distribution that would support a routing table keyed on one role,
and that table would mis-route 55% of the corpus. `data_prep_kit` is
`documentation + tutorial + samples + application` at once, and the right tools for it are the
union of four different answers, not the first one.

It also means routing cannot be a lookup. A repo that is both a library and a samples collection
should get the library treatment for its `src/` and the samples treatment for its `examples/` —
which is a *scoped* question, and `scope_locator` already exists to express it.

**Tools already declare what they need.** `StepInfo`/`AnalysisCatalogEntry` carry
`requires_resources` (zipball, clone), `fetch_cost`, `run_time`, `availability`, `target_shape`,
`intent`, `perspectives`, `resource_types`.

**So the gap is not extraction and not tool metadata. It is that nothing routes.** Every declared
field above answers *"what does this tool cost and what runtime inputs does it need"*. None answers
*"what must be true of this repo for this tool to say anything worth reading"*.

## 3. The one thing that does route, as a worked example

`repo_classification`'s `architecture_recovery_gate` was computed, stored, and read by nothing.
Measured 2026-08-31: 45 `run`, 8 `skip` — and `monocle`, gated `skip` for *"samples role present
and no structural evidence"*, carried **405 architecture findings**. The classification was right
and nothing acted on it.

It is now honoured (`1e07b01`), with three properties this note proposes generalising:

1. **A skip reports `skipped_by_design`, never "nothing found".** A gated repo did not look and
   find nothing; it did not look. `surveyors/result_status.py` exists for exactly this distinction.
2. **The reason travels with the skip.** "Skipped" with no stated reason is indistinguishable from
   a failure on screen.
3. **The gate changes the default, not the permission.** `respect_gate=False` runs it anyway.
   Someone who wants an architecture read on a tutorial repo is entitled to it.

That is one gate, hand-wired, for one analysis. The rest of this note is what it would mean to
have this generally.

## 4. What to extract: context as declared facts, not inferences

The context vocabulary should be small, cheap, and *observable* — properties an analysis can
precondition on without anyone guessing:

| context fact | observable from | already available? |
|---|---|---|
| holds first-party code | `exclusion.scan`'s census, `first_party_ratio` | yes, computed in `arch_recovery_detect` |
| is deployable | Dockerfile / compose / k8s manifests | yes, `deployment_units` detector |
| has embedded documentation | in-repo doc paths | yes, `doc_locations` |
| has a documentation site | sibling repo / homepage / ingested site | yes, `doc_locations` outward hop |
| has tests | test directory conventions | partially — file inventory sees them |
| declares a package | manifests (npm/pypi/gradle/cargo) | yes, `*_manifests` detectors |
| repo role | `repo_classification` | yes |

Every row is already produced by something. What is missing is that they are **findings scattered
across kinds**, not a single context record an analysis can precondition on.

**The concrete proposal: `requires_context` alongside `requires_resources`.** A declared
precondition on repo facts, checked before dispatch, producing a `skipped_by_design` with a stated
reason when unmet. `architecture_recovery` would declare something like
`requires_context={"first_party_code": True}` and the hand-wired gate in §3 becomes one instance of
a general mechanism rather than a special case.

**What this must not become.** A precondition is not a quality judgement. "This repo has no
deployment units" is a fact; "this repo is not worth analysing" is not, and the distinction is the
one §3's third property protects.

## 5. Ports and wires belong in this conversation, and have been missing from it

Dan, 2026-08-31: *"We also haven't included ports and wires into the conversation — and they
probably should be."* Correct, and the omission is mine: Phase 2's proposal buried them in a JSON
payload inside a structural annotation. That is storage, not conversation.

Three reasons they deserve first-class treatment, and the third is the strongest:

**They are cheaper than components.** `interfaces.py` reads only artifacts the detectors already
parse — no ast-grep, no import graph, no clone. Its own docstring notes this keeps it at Discovery
tier. 26 of 60 repos have interface findings today.

**They are more discriminating.** A component list is a partition of the file tree, and every repo
has one whether or not it means anything — hence 878 for `egeria_git`. A wire is a claim that *this
thing talks to that thing*, which a file tree cannot manufacture. Where components are noisy, wires
are sparse and mostly real.

**The Egeria model treats them asymmetrically, and the proposal must too.** `SolutionPort` is an
**entity** (`OpenMetadataType.java:6345`); `SolutionLinkingWire` is a **relationship**
(`:6335`). So a port can be proposed, reviewed and materialised as a thing; a wire can only exist
between two ports that already do. That ordering constraint belongs in the proposal and in the
outbox's `depends_on_id` — it is exactly the dependency the outbox was built to enforce.

**Direction is load-bearing and already handled carefully.** `SolutionPortDirection` is a 5-value
enum where `Input-Output` means *provides* and `Output-Input` means *calls*; inverting them inverts
every dependency in the graph. `interfaces.py` claims the strong values only on direct evidence and
refuses to infer protocol from a port number, on the grounds that "treating convention as evidence
is how a plausible-but-unverifiable claim enters the catalog wearing the same confidence as a
measured one". That restraint should survive into the proposal rather than being flattened by a
renderer that wants every edge labelled.

## 6. Interest is a signal to surface, not a threshold to enforce

Dan: *"most of the time if we are discovering dozens of components, we are likely not producing
something of enough interest to the user — but we should let them decide."*

Measured, components per repo:

```
   0 components : 18 repos (of which some are gated skip)
1-10            : 18
11-30           :  4
31-100          : 13
100+            :  7
```

The distribution is bimodal-ish and the tail is where the noise lives. But "dozens means
uninteresting" is a *prior*, not a fact about any given repo — a genuine 60-component system exists.

So: **surface it, default modestly, let it be raised.** Already done for the proposal's naming
limit (`dbb5e7b`): `max_named` defaults to 200, takes any integer, `None` removes it, and the
summary reports `components_not_named` with "raise it to name them all". A limit that hides its own
existence reads as "these are all the components there are", which is silent truncation wearing a
different hat.

## 7. How the portfolio actually refines over time

The hardest part of Dan's framing is *"over time will help us refine which tools are appropriate
for which repos"*. That requires knowing which tools produced something worth having.

**The first draft of this section said nothing records that. It was wrong, and the correction is
the useful part.** Outcomes are already harvested and persisted:
`step_cost_observer.describe_work()` reads the outcome label off the annotations the orchestrator
already holds — so a step that has not adopted the vocabulary still contributes its count — and
`record()` writes them as `observed_outcomes` into `project_analysis_metrics` under
`kind='step_cost'`.

So the portfolio question is answerable **today**, by query, with no new storage. Run
2026-08-31:

| repo role | step | runs | of which reported `unverified` |
|---|---|---|---|
| application | `repo_manifest_parse` | 17 | 7 |
| application | `repo_dependency` | 3 | 3 |
| samples | `repo_file_structure` | 7 | 6 |
| samples | `repo_manifest_parse` | 24 | 2 |
| documentation | `repo_manifest_parse` | 13 | 0 |

`repo_file_structure` returning `unverified` on six of seven `samples` repos is exactly the
tool-fit signal this section was arguing had to be built first. It was already there.

**What is actually missing, in order of cost:**

1. **Coverage.** Only 11 of ~33 sub-surveyors emit an outcome at all. The rest record `[]`, which
   is honest — a step that has not adopted the vocabulary is not claiming anything — but
   contributes nothing to tool-fit. This is the cheapest real improvement and the one with the
   largest effect on the table above.
2. **Aggregation.** `["no_signal", "recovered", "unverified"]` on one `repo_manifest_parse` run is
   three annotations disagreeing, with no rule for what the *step* achieved. A stated precedence
   is needed — the defensible one is least-conclusive-wins, since a step with an unverified part
   cannot claim its whole answer is complete.
3. **Discoverability.** The data lives under `kind='step_cost'`, which is where you look for
   timing, not for tool-fit. A correctness non-issue and a findability real one — this section's
   own error is the evidence.
4. **Only then tune the routing table.** Anything earlier is guessing about which tools work, and
   the docs-as-source measurement (§9 step 2, 2026-08-31) is a standing warning about what happens
   when plausible tests are built before being measured: all three failed, and one inverted.

## 8. Honest limits

- **§4's `requires_context` is a sketch.** One hand-wired gate is not evidence that a general
  mechanism is right, and the context facts in the table are individually available but have never
  been assembled into one record.
- **The component-count bands in §6 mix gated and ungated repos**, so the `0` band conflates "looked
  and found nothing" with "correctly never looked" — the exact distinction §3 property 1 exists to
  keep. Worth re-measuring once the gate has been in effect for a while.
- **Nothing here addresses `egeria_git`'s 878.** §8 of docs-as-source is explicit that documentation
  and clustering are complementary and neither substitutes for the other; routing decides *whether*
  to run a tool, not how to make a noisy tool quiet.
- **The multi-role finding above was a correction, not a design input.** The first version of
  this note reported the primary-label distribution as though it were the role distribution — a
  correct count of the wrong population, and the fourth of that shape in one day. It was caught
  only because the gate's own summaries said "documentation/samples/tutorial role present" while
  the table showed one role per repo, and the contradiction was checked rather than smoothed over.
- **Scoped routing (§2's closing point) is asserted, not designed.** That a plural repo wants
  different tools on different subtrees follows from the measurement; how a router would express
  that, and whether the analyses can honour a scope they did not choose, is not worked out here.
