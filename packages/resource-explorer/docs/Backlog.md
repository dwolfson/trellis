# Resource Explorer — Backlog

**Purpose:** A running list of work items that are agreed as worth doing but are not yet scheduled into a phase of an active design document. When an item is picked up for real design/implementation, move its detail into (or link from) the relevant design doc and leave a one-line pointer here.

This is a list, not a design doc — keep entries short. Link to a full design doc/section when one exists.

**Egeria/pyegeria bugs (as opposed to RE's own bugs)** are tracked in `egeria-python`'s `PYEGERIA_ISSUES.md` — the canonical tracker, unified `ISSUE-#` numbering — not here. RE's own `docs/egeria-pyegeria-issues.md` is superseded and frozen at 6 entries; it is kept for history only.

**Current-state map (2026-08-19):** `docs/survey-and-analysis-current-state-2026-08-19.md` maps how surveys, analysis and curation work — the axes on which the two survey-launch paths diverge, an inventory of which analyses reach Egeria and which don't, and a suspected bug (filesystem annotations never publish). **It was derived from the pre-migration standalone repo and carries a staleness warning — line numbers need re-checking, and it predates `run_batch` in the executor.** Several items below are corrected there. Related: `docs/architecture-recovery-design.md` (deriving Solution Blueprints from repos).

---

## Next up — priorities as of 2026-08-26

Marked at the end of the architecture-recovery thread. Findings 96–119 in
`scripts/arch-spike/README.md` are that thread's record; this is what is left and
what is deliberately not.

**1. Phase 2 — Egeria projection of recovered architecture.** Still the largest unbuilt piece,
but **"nothing from architecture recovery reaches Egeria" stopped being true on 2026-08-30** —
`arch_recovery/materializer.py`'s `ComponentMaterializer` writes a real `SolutionComponent` when
a curator accepts a proposed component. That path is deliberately narrow: accepted verdicts
only, a bare component with no blueprint or relationships, and no retraction if a verdict is
later reversed. So the *blueprint* projection is unbuilt; a single-component projection is not.

Its one remaining prerequisite is **outbox/retry publishing** (design §8.4, still design-only) —
a blueprint writes far more elements per run than anything currently published, and the design
is blunt that *"a half-published blueprint is worse than none."* Its other prerequisite is done:
projection has a hierarchy to collapse (finding 117, milvus 204-at-every-depth → 82/142/216/221).

**2. `security_features` should report `skipped_by_design`.** GitHub returns
`security_and_analysis` only to repository admins, so the analysis is **structurally impossible
for third-party repos** — 2 of 60 populated. That is a fact about the world, not a failed run,
and it is the strongest case for that state anyone has found. Presentation session's finding.

**3. The silent field-allowlist pattern**, filed under *Corpus, signals & testing*. Three
instances in one day, one closed with a superset guard (finding 118); the sweep across other
sites is unowned. The action that matters: check each allowlist against its **current** source
shape, not the shape it had when written — none of the three was wrong when written.

**Deliberately closed, with a measurement behind each — do not reopen without re-measuring:**
the LLM adjudicator (the doc lens reaches Milvus's real components more cheaply where
documentation exists); milvus site ingestion (302-loops for every user agent including a
browser one); doc-kind chunking selection (0 of 20 collections are API-reference shaped);
boilerplate stripping and version collapsing (both already work, finding 119); `misgrouped`'s
emitter and guard-based branching (nothing would behave differently); Java `src` naming and the
`cmd/X`+`pkg/X` merge (both downgraded by measurement, finding 97).

**Small and real, low value:** Go cohesion without recursive rollup; `find_artifact("readme")`
preferring a nested README over the root one; rule 17's guard validating a step's *declaration*
rather than its behaviour.


## Open items

Grouped by area. Within a group, the most actionable entries come first.

### The outbox drain does not serialise, and its docstring says it does

**Filed 2026-09-02, while a batch republish had the web server deliberately
stopped — deliberately filed BEFORE restarting it, because restarting hides
the symptom and the bug goes back to being invisible until two drainers
happen to overlap again.**

`ProjectRegistry.claim_due_outbox_elements()` does not claim. It is a plain
`SELECT` — no `FOR UPDATE`, no `SKIP LOCKED`, no status transition — and
`drain_outbox()` marks a row `done` only *after* its create succeeds. Two
drainers therefore select the same rows and both call `apply_element`.

Its docstring asserted the opposite ("the drain marks each row in flight as it
takes it"). That is corrected in place now, but the correction is a note, not
a fix. **A function named `claim_` that performs no claim, documented as doing
the locking it does not do, is worse than an undocumented race: the next
reader checks, finds the claim described, and concludes it is handled.**

The hazard is asymmetric, which is what makes it worth fixing rather than
noting:

- **Annotations survive it.** The second create is rejected as a duplicate
  qualifiedName, `apply_element` adopts the existing GUID, one element exists
  and two rows are marked done.
- **Annotation links do not.** They go through a multi-link `attach()` that
  duplicates silently instead of upserting, and there is no reconciler for
  annotation-level duplicates the way `scripts/reconcile_survey_definition_links.py`
  exists for step links. A duplicate link is permanent and invisible.

**The usual second drainer is not a person.** It is `scheduler.py`'s loop
inside any running `resource-explorer web`, firing every
`_CHECK_INTERVAL_SECONDS` (900) whether anyone is at the keyboard or not. So
"do not run two republishes at once" is not sufficient guidance — a single
operator with the app open is already two drainers.

**Fix:** serialise the claim — `SELECT ... FOR UPDATE SKIP LOCKED`, or a
`status='running'` transition in the same transaction as the select — so the
property holds by construction instead of by remembering to stop the server.
Until then, stopping the web server is the mitigation, and it is a mitigation
for one run rather than a fix.

### Survey execution

> **STATUS 2026-09-01, later the same day: the precondition half of this is BUILT and this entry is
> stale where it says otherwise.** `survey_orchestrator.py:226-241` evaluates a step's
> `requires_context`, and on a failed precondition emits a `SKIPPED_BY_DESIGN` annotation carrying
> the reason and records `result.skipped_steps[step_key]`. `step_preconditions.PRECONDITIONS`
> defines `has_dependencies`, `has_versioned_dependencies`, `has_file_inventory` and
> `has_code_symbols`, and `repo_cve_scan` declares `has_versioned_dependencies` in production.
>
> Caught by an agent scoping the GAP analyses, which read this entry as a statement of current
> state and would have rebuilt the orchestrator plumbing. Verified against the source before this
> note was written. **What remains open is the vocabulary, not the mechanism** — richer context
> facts (`first_party_code`, `is_deployable`, `has_documentation_site`) per
> `docs/repo-context-and-tool-routing.md` §4, and guard evaluation in the EXECUTOR, which is
> separate and still unbuilt.
>
> The entry is kept rather than deleted because the reasoning below is what the built feature
> honours, and because a backlog item that silently disappears leaves no record of why it was
> closed. An entry that outlived what it described, in a document whose whole job is to describe
> what is outstanding.

**No conditional execution of survey steps — every selected step runs, whether or not it can say
anything.** Raised by Dan 2026-09-01. `SurveyOrchestrator.run()` iterates
`list(all_surveyors.items())` and runs each in turn. The only filters are the cost ceilings
(`max_fetch_cost`/`max_compute_cost`) and an explicit `steps=` list. There is **no way for a step to
declare a precondition on the state a previous step produced**, and no way to skip one whose input
is absent.

The consequences are already visible, and they are not crashes:

- **`cve_scan` on a repo with no parsed dependencies.** It reads `project_dependencies`, finds
  nothing, and correctly declines rather than claiming "no CVEs". Right behaviour — but it ran, was
  timed, was published as an analysis, and contributed nothing. `security_summary` then counts it
  among its 8 `INPUT_KINDS` as *never ran*, and below `MIN_INPUTS_FOR_VERDICT` withholds a verdict.
  A step that cannot say anything still consumes a slot in the picture.
- **The distinction that has to survive.** `surveyors/result_status.py` already separates
  `NOTHING_FOUND` from `SKIPPED_BY_DESIGN` from `NEVER_RUN`. Conditional execution must produce the
  middle one — *skipped, with a stated reason* — never silence. A step that vanishes from a report
  is indistinguishable from one that ran and found nothing, which is the failure this codebase keeps
  removing. `repo_classification`'s `architecture_recovery_gate` is the worked example of doing it
  right (`docs/repo-context-and-tool-routing.md` §3): it reports `skipped_by_design`, the reason
  travels with the skip, and `respect_gate=False` still runs it — the gate changes the default, not
  the permission.

**What is missing, concretely.** `StepInfo` declares `requires_resources` (zipball, clone) and
`requires_views`, both about *runtime inputs*. Neither expresses "this step needs rows in
`project_dependencies`" or "this step is pointless on a repo with no first-party code". The design
note already proposes the shape — `requires_context` alongside `requires_resources`, checked before
dispatch, producing a `skipped_by_design` with a reason when unmet
(`docs/repo-context-and-tool-routing.md` §4) — but nothing is built beyond the one hand-wired gate.

**Egeria already has the branching half of this, and it is worth not reinventing.** Reported
2026-09-01 by a concurrent session that read `EngineActionHandler.initiateNextEngineActions`
(lines 2839-2945) in the Java source directly — **recorded here second-hand; not verified from the
source by the author of this entry**, so confirm before building on it:

- Each `NextGovernanceActionProcessStep` link carries a `guard` and a `mandatoryGuard`.
- `validNextAction = (guard == null)`; otherwise the link fires only if that guard string appears in
  the previous step's `outputGuards`.
- A step emits guards through `recordCompletionStatus(status, outputGuards, ...)` and may emit
  several.
- `mandatoryGuard` is a **join, not a branch** — `runEngineActionIfReady` holds a prepared action
  until every mandatory guard has arrived from its upstreams.

So the model is "one step, several outgoing links each with a guard, follow the ones whose guard
fired". That is a real answer to *which steps run*, and it means RE should express conditionality in
Egeria's vocabulary rather than inventing a parallel one.

**What Egeria's model does NOT give you is the part this entry is actually about.** Guards say which
links *fire*; nothing records what therefore *did not run*, or why. A step that is simply never
reached leaves no trace, which is precisely the silence that makes `NOTHING_FOUND` and `NEVER_RUN`
indistinguishable downstream. Whatever is built has to add the `SKIPPED_BY_DESIGN`-with-a-reason
record on top of guard evaluation — it will not come for free with the guards.

**Related, and deliberately kept separate:** step *ordering* is a different problem and is currently
correct. Producers precede consumers in `STEP_REGISTRY`, verified live 2026-08-31 (one `amundsen`
survey produced 880 dependency rows and 8 cve_scan findings in the same run) and now guarded by
`tests/test_step_execution_order.py`. That order is positional and undeclared, so the test exists to
stop it regressing silently; **if conditional execution is built, it should express the data
dependency it already relies on rather than adding a second implicit mechanism beside it.**

### Admin surface: Option B (separate pages), and possible Trellis-wide centralisation

**Deferred by decision 2026-09-01, not dropped.** Dan: *"agree in general — do the fix recommended
and put option B in backlog to be revisited. Its quite possible that we may need to centralize admin
across trellis at some point — so lets not lose this in the day to day."*

`docs/admin-surface-options.md` recommends **staying inline for now** and fixing the existing drift
first. That recommendation is accepted. This entry holds what was deferred.

**Option B — extract admin into separate static pages** served by the same app, following the
`admin-feedback.html` precedent (RE has no JS bundler; a "separate site" costs about what that page
cost, not a second app). Measured pressure at time of deferral: `index.html` is **15,774 lines** and
the most-churned file in the package — **166 commits since 2026-08-06**, next closest
`docs/Backlog.md` at 116, peaking at 23 in one day. But that is co-occurrence, **not proven merge
conflicts**, and the distinction was made honestly rather than used to argue for a rewrite.

**Triggers to revisit** (any one):
- A real merge conflict in `index.html`, not just contention.
- A pane whose operator-only content has no reason to share the analyst UI's session or
  resource-selection context — **Prefect and Logs are closest**.
- **The open-demo deployment** (see the entry below). That changes the calculus: EA's separate
  `/admin` was discounted as weak precedent partly *because* it is unauthenticated, which stops being
  a reason to dismiss the split and becomes a reason the split needs auth.
- **Trellis-wide admin centralisation** — Dan's own flag, and the largest version of this. RE, EA and
  Workspaces Portal each have their own admin surface with their own auth posture and their own
  triage vocabulary; the surveys in `docs/feedback-signals-shared.md` and
  `docs/feedback-triage-from-workspaces.md` are already evidence of three implementations converging
  on the same needs. If admin is going to be shared, extracting RE's into pages first is a
  prerequisite step rather than wasted work.

**What must not be lost in any split** (all with line references in the options doc): Egeria
Alignment's dry-run/confirm split, undetermined-reported-separately-from-clean, expensive repairs
unticked by default, per-action destructive warnings, and fixed apply ordering. These took a full
session to get right and a loose re-implementation would silently lose them.

### Feedback as a signal of where the system is weak, not just of what a user disliked

**Raised by Dan 2026-09-01**, and it is a different axis from triage status:

> *"there is another status or point — that what is being reported indicates a gap in either training
> data, rules, routing, or agent behavior — we would want to periodically sweep through this (and the
> chat scores) for continuous improvement"*

Triage answers *what do we do with this report*. This answers *what does this report tell us is
missing*, and the two are independent: a report can be `not_an_issue` for the reporter and still be
the clearest evidence available that routing is wrong.

Proposed as a **second, orthogonal classification** — not more values on `triage_status`, which would
conflate a disposition with a diagnosis. Candidate categories, from Dan's own list: **training data ·
rules · routing · agent behaviour**, plus an explicit *not-a-system-gap* and an *unclassified* that
is distinct from "reviewed and found to be none of these". Absence must not read as a decision — the
same rule as everywhere else here.

**The sweep is the point, not the field.** A classification nobody aggregates is a dropdown. What is
wanted is a periodic pass over feedback AND chat scores together, looking for concentrations — three
reports blaming routing in one area is a finding that no single report is. Scope should include:
`feedback`, `resource_feedback`, and the chat signal (`chunk_feedback`, now trinary — see
`docs/feedback-signals-shared.md`), since a low chat score and a written complaint may be the same
gap seen twice.

Prerequisites, in order: RE has **no way to change any feedback state today** — the gated
`PATCH /api/feedback/{id}` exists and no UI calls it (`docs/feedback-triage-from-workspaces.md`).
That must land first, and `/api/curate/feedback` must be gated, before adding a second field that
also needs writing.

Not scoped: whether the classification is made by a person, suggested by an agent and confirmed, or
both; how the sweep is scheduled; and what it produces — a report, a RequestForAction, or backlog
entries.

### Auth posture when RE and EA reach the open demo environment

**Dan, 2026-09-01: "RE and EA will at some point also be in the open demo environment."** Recorded
because it puts an expiry date on reasoning committed the same day, and that reasoning is now in a
docstring that would otherwise be read as timeless.

`web/admin_auth.py` is fail-closed: absent admin configuration, every admin request is denied. Its
stated justification is that **RE has nothing to defer to** — no multi-user authentication of its
own, and no authenticating layer behind it. That is true of RE today and stops being true in a
public demo.

Egeria Workspaces Portal has already solved this shape, and `demo_feedback_handler.py::_is_admin()`
is the model rather than the counter-example it was briefly mistaken for (see
`docs/feedback-triage-from-workspaces.md` §5, framing withdrawn): **two modes — a public demo
requiring an external identity, and a local mode relying on Egeria's own users.** RE will need the
same distinction, and should adopt that pattern rather than reinvent one.

**What this changes about work already done or planned:**

- **`/api/curate/feedback` gating moves from "outstanding" to "required".** It is currently ungated,
  and on 2026-09-01 it was widened to serve the page-level feedback store. Contact fields are
  stripped as an interim (`cb99d72`) — that was sized as a stopgap for a single-operator local app.
  In an open demo it is the difference between a form and a mailing list.
- **The interim becomes insufficient, not merely redundant.** Stripping hides contact fields from a
  listing; it does nothing about who may WRITE. Triage editing (`PATCH /api/feedback/{id}`, gated
  today) and any future admin write must not inherit an ungated sibling.
- **The feedback store holds real submissions with `wants_response` and `consent_to_contact`.**
  Consent given to a local tool is not consent given to a public deployment. Whether existing rows
  may be carried into a demo environment at all is a question for Dan, not a default.
- **`docs/admin-surface-options.md` recommended staying inline**, partly because EA's separate
  `/admin` is unauthenticated and therefore weak precedent. In an open demo that stops being a
  reason to dismiss the split and becomes a reason the split needs auth — the recommendation should
  be revisited against the demo requirement, not just against file contention.

Not scoped: which identity provider, whether RE and EA share a session, whether the demo runs
read-only, and what happens to the admin token that exists today.

### Reporting levels

**Improvement suggestions as a third reporting level, keyed off who is asking.** Raised by Dan
2026-09-01 while reviewing `docs/gap-analyses-design.md`. Deliberately deferred; recorded so the
GAP analyses are built without precluding it.

An analysis can report at three levels, and today only two exist:

| level | mechanism | state |
|---|---|---|
| overall finding / score | `project_analysis_findings.label` + `.confidence` | built, used |
| the evidence behind it | `.detail_json`, and Egeria's `AnnotationExtension` | partly built — see below |
| suggestions for improvement | `RequestForAction` annotation | type exists, used ONLY for internal survey errors (`base_surveyor.py:39`) |

**The hook already exists and nothing reads it.** Investigations carry `purposes`, validated against
`ProjectCharter.purposes` (`registry.py:4265-4275`): *Assess, Certify, Deploy, Explore, Learn,
Maintain, Select, Share*. Dan's point is that a suggestion depends on whether the asker MAINTAINS
the artifact or CONSUMES it — `Maintain` versus `Select`/`Deploy` — and that distinction is already
modelled, validated on write, and consumed by nothing.

So the item is well-formed rather than vague: **drive `RequestForAction` content off the
investigation's declared purpose.** "Add a SECURITY.md" is advice for a maintainer; "this project
publishes no security policy — weigh that in your selection" is the same finding for a consumer.
Same evidence, different action, and issuing the maintainer's version to a consumer is noise.

**What must be true NOW so this stays possible later**, and it is the reason this is recorded rather
than only remembered: **the finding, its evidence and any recommendation must be separately
addressable.** Evidence flattened into a summary string cannot be re-read by a recommender built
later, and the alternative is re-running every survey to get it back. `AnnotationExtension`
(`OpenMetadataType.java:6010`, model 0610 — *"Additional information to augment an annotation"*) is
the modelled way to link a summary annotation to the evidence annotations behind it. **RE has never
created one.**

`AnnotationReview` (model 0612, `OpenMetadataType.java:6020`) is the adjacent type for a stewardship
review of an annotation, and is the more likely home for an accepted/rejected suggestion than a
bare RequestForAction.

Not scoped: whether a purpose maps to one recommendation set or several, what happens when an
investigation declares five purposes at once (common — one live investigation declares eight), and
whether a recommendation is itself a finding with a lifecycle or a rendering of one.

### Test reliability

#### `test_survey_definition_generator_guard.py` mutates the real docs directory, and is only safe alone

Found 2026-09-01, in the working tree rather than by a failing test — `git status` showed
`.generated.json` **deleted** and `repo-survey-definition-assessment.md` carrying a mechanical
`"Assessment Survey"` -> `"Assessment Survey X"` rename that nobody had made.

Both come from the test file itself. It operates on the **real**
`docs/dr-egeria/survey-definitions/` directory, not a `tmp_path` copy:

    DEFS = Path(__file__).resolve().parent.parent / "docs" / "dr-egeria" / "survey-definitions"
    target.write_text(original.replace("Assessment Survey", "Assessment Survey X"))   # :91
    PROVENANCE.unlink(missing_ok=True)                                                 # :108

Its `restore` fixture snapshots every document plus the sidecar and puts them back, and **is correct
in isolation**. The failure needs two runs: session A snapshots, session B snapshots *A's mutated
state*, A restores, B restores what it captured — and the tree keeps a snapshot of a half-mutated
directory. With the sidecar gone, every definition then looks hand-edited, so the guard tests fail
for a reason that has nothing to do with the code under test.

**It is not a flaky test. It is a test whose correctness depends on being the only one running**,
and nothing declares that property. Three sessions running suites in one shared checkout is now
routine, so this will recur.

Fixes, roughly by cost:

1. **Copy the directory to `tmp_path`** and point the generator at it — the generator already takes
   paths, so this is mostly fixture work, and it removes the shared-state dependency entirely.
2. **A file lock** around the module, so concurrent runs serialise rather than interleave. Cheaper,
   and leaves the tree mutated while it runs — a `git status` mid-suite still lies.
3. **Leave it and document it.** Current state: correct alone, silently wrong concurrently.

Recovering from an occurrence is `git checkout --` on the two paths, after reading `git status` for
them — the damage is confined to that directory and is always the same shape.



**`test_local_flow_execution_fallback` failed once and has not reproduced.** Seen 2026-08-31 in a
full run on `c650df6`: 3075 passed / 1 failed. An immediate rerun of the same command, same commit,
same `-p no:randomly`, gave 3076 passed / 0 failed. The test passes alone (8.3s) and passes as a
whole file.

**Status: open, cause unknown, one observation.** Recorded rather than closed because a fix that
did not reproduce the failure cannot be shown to have fixed it.

What has been ruled out, so nobody re-walks it:

- **Not port contention.** The test is pure mocks and binds nothing. The port in the Prefect noise
  comes from Prefect's own `prefect_test_harness`, not from our code.
- **Not "a non-opted-in module poisons Prefect's cached client first."** This was the leading
  hypothesis and it explained every symptom — passes alone, passes per-file, fails in the suite.
  It was falsified: first-wins on a fixed sequence predicts a *deterministic* failure, and two
  fixed-order runs disagreed. The mechanism it described is real (the fallback at
  `prefect_adapter.py:153` calls the real `re_survey_flow`, using Prefect's own client rather than
  the patched one) — it just is not what happened.
- **Not a Prefect server left running by a concurrent session.** Reported as evidence and then
  withdrawn: the "prefect processes" were `ps | grep "[p]refect"` matching the reporting session's
  own `zsh -c` wrapper line. The bracket idiom stops grep matching itself; it does nothing about the
  shell carrying the pattern as an argument.

Do **not** read `Stopping temporary server on http://127.0.0.1:<port>` or `ValueError: I/O
operation on closed file` as a reproduction signature. Both appear in runs where this test passes;
they are Prefect teardown noise.

If it recurs, capture the assertion text — not a `tail` of the run, which buries the summary under
Prefect's teardown logging.


### Architecture recovery

#### MEDIUM — telemetry for surveys, and the LLM-based survey step

*(Opened 2026-08-30, from the decision-trace work — `architecture-recovery-decision-trace.md` §5.)*

The decision trace is now persisted as findings, and that doc argues it should **not** go to
MLflow, Phoenix or OTEL: decision provenance is read months later by resource and must be durable
and queryable, while telemetry is sampled, retention-limited and keyed by trace id. **That part
stands.** Two things around it do not, and want revisiting.

**1. "Surveying is deterministic Python" is false as a general claim** (Dan, 2026-08-30). It is
true of `repo_arch_detect` and `repo_arch_coupling`, which is all the original reasoning had in
front of it. **A survey step can perform LLM-based analysis**, and where it does:

- Phoenix/`BeeAIInstrumentor` instrumentation *is* directly relevant to that step — there is a real
  model interaction to trace, with prompt, tokens and latency;
- the step is **non-deterministic**, so the reproducibility argument that holds for the two
  deterministic steps does not transfer;
- there are then **two traces to keep apart**, not one: the model interaction (Phoenix/OTEL) and
  the decision it produced (durable, per-resource, `architecture_decisions`).

§16 of `context-compilation-design.md` already makes the matching argument one layer up — agent
output must be *written down, versioned and provenance-stamped before it is packable*, precisely
because agents are non-deterministic. A survey step that calls a model needs the same discipline,
and the decision trace is the natural home for the written-down half. Worth checking whether any
step already does this and is currently unprovenanced.

**2. Execution telemetry for surveys has no home and no owner.** Per-step and per-detector timings,
failure points, hot paths. OTEL is the right shape and nothing emits it. Not urgent — there is no
open performance question, and the one measurement that mattered
(`_withdraw_vacated` at 93ms over 10,135 rows) was answered with `time.perf_counter()`. Open it
when there is a question to answer, and note the scaling item below is the likeliest trigger.

**If tracing is added, the shape to use** is a span per survey step carrying the *finding id* — a
pointer to the durable record, not a second copy of it. Dual-writing means two stores that can
disagree, and the span copy is the one that expires.

#### ~~HIGH — take architecture results into Curate~~ — DECIDED AND BUILT 2026-08-30

*(Opened 2026-08-30 listing four candidate shapes and saying "none of this is designed yet".
Dan chose the first and S1 built it the same day. This entry was left stale for several hours and
was still being reported as an open design question when it was neither — corrected on Dan
noticing. Then corrected AGAIN by S2, who had built the backend and pointed at the differing
`Claude-Session` trailers on `6f3afeb` and `2a22c99` to prove it. Verified before accepting. Two
attribution errors on one row, both from reading a summary instead of the commits — which is exactly
what `re-multi-session-attribution` says not to do.)*

**The shape: accept / reject / retype a proposed component.** The pipeline is explicitly a
*proposal* (§4.1a, `report-then-curate`) and a curator's verdict was the missing half. It rides the
Confidence/ContentStatus axis (§3.3b/§3.4) rather than introducing a vocabulary.

Landed in three slices:

| | |
|---|---|
| `6f3afeb` | accept/reject/retype on a proposed component — the backend (`web/routes/curate.py`, the `architecture_component_verdicts` table, `registry.py` methods) — **S2** |
| `2a22c99` | verdicts wired into the architecture card — **S1** |
| `f34d3c5` | **accepted proposals materialized as real Egeria `SolutionComponent`s** — **S1** |

That third one is the one that closes the loop `report-then-curate` opened: a proposal a human
accepted stops being a local finding and becomes a catalog element.

**Still open from the original four**, and genuinely undesigned rather than merely unclaimed:

- **Correct a name.** The live case is still the best argument: the disambiguator renamed Atlas'
  main distribution config to `distro` because six modules shared the token `atlas` — unique and
  truthful, and not what a curator would choose. No rule can know which member of a collision
  deserves the shared name.
- **Curator notes at component scope.** `resource_curator_notes` is whole-resource; architecture
  recovery is scope-keyed throughout.
- **Promote a reviewed set toward publication** — the ContentStatus ladder `report-then-curate`
  describes and nothing yet walks end to end.

See also the reflexion-vocabulary entry below: convergence/divergence/absence is a ready-made naming
for the verdict axis, and worth reading before the next slice invents its own.

#### HIGH — `architecture_recovery` costs 110s to fetch and 5.9s to run — fix the acquisition

*(Opened 2026-08-30 as a tier question; **reframed the same day by profiling**, which killed three of
the four options it originally listed. Dan's steer: the work likely goes into the analysis
implementation, not the catalog.)*

**The analysis was never slow.** Profiled on `egeria_python_git`:

| | |
|---|---|
| compute, against a local checkout | **5.9s** — detect 3.1s, coupling 2.8s |
| `zipball_root` + `git_clone_root` acquisition | 15.7s |
| **the same two steps via `SurveyOrchestrator`** | **110.5s** |

`architecture-recovery-phase1-findings.md` §3's **"5.3s per repo"** — the figure CLAUDE.md rule 17
cites to justify Discovery placement — is **correct and still holds**. Nothing regressed. The cost
is entirely in *how the route acquires the repo*.

**Where it goes.** cProfile over exactly what the route calls:

```
738 calls    95.1s   {method 'poll' of 'select.poll' objects}    <- waiting on git subprocesses
36569 calls  12.2s   {method 'read' of '_ssl._SSLSocket'}        <- network, inside the profile
```

Same step, same repo: **2.8s against a local checkout, 92.1s through the orchestrator.** The
difference is `_acquire_git_clone_root`'s `--filter=blob:none --no-checkout`. Co-change analysis then
runs `git` history commands against a **treeless** clone, and git lazily fetches from the remote for
anything absent — so each operation pays network round-trips. Our `select.poll` time is git's
network time.

**Two candidate fixes, neither decided:**

- **Cache the acquired roots.** Both providers clone into a *fresh tempdir every run*
  (`_acquire_zipball_root`, `_acquire_git_clone_root`), so a repo is downloaded twice per run, every
  run, forever. A cache keyed on commit SHA would make the second run of anything nearly free — and
  it would benefit every step declaring these resources, not just this one.
- **Give co-change what it actually needs.** It wants commit metadata and pathnames, which a
  treeless clone *has*. Something is reaching for blob content and triggering the lazy fetch;
  finding what would be a smaller, more surgical fix than caching.

Worth doing the second first: it is diagnostic, and its answer determines whether the first is a
performance nicety or the only option.

**The instrumentation that flagged this is misattributing, and that is its own small bug.** The run
emitted:

> `repo_arch_coupling — declares compute_cost='medium' (ceiling 60s) but took 92.1s with no
> connections, so that is compute`

It is 92.1s of *network*, in a child process, invisible to whatever counts connections. So the guard
built to catch exactly this case reported the opposite and nobody was reading the line anyway.

**What this does NOT need.** The entry originally offered four options; the measurement leaves one:

- ~~re-tier out of Discovery~~ — the analysis *is* Discovery-cost at 5.9s
- ~~re-map the Discovery question to something cheaper~~ — same reason
- ~~decouple `availability` from `run_time`~~ — `run_time` was never wrong about compute
- **fix the acquisition** ✅

`run_time: fast` therefore stays, and is now *defensible* rather than merely unchanged — with the
caveat that it describes compute while a user experiences compute **plus** acquisition. If the
acquisition fix lands, the two converge and the question disappears. If it does not, the honest tag
is about the whole experience and the tier question comes back.

Open, unresolved: whether `architecture_recovery` belongs in the **Analysis** intent rather than
Discovery on other grounds — that is a separate judgement from cost, and cost no longer forces it.

**Resolved the same day, separately, by S1 in a different session:** Dan ruled directly —
"architecture recovery is an analysis step and belongs there." `intent: analysis` now, `run_time:
fast` unchanged (this entry's reasoning above stands; the ruling was on tiering grounds, not cost).
Recorded together in `analysis_catalog.yaml`'s entry so neither change reads as having overridden
the other.

**Still open and unclaimed as of 2026-08-30 (S1):** both candidate fixes above (cache the acquired
roots; give co-change what it actually needs). S1 is coordinating with S2 before claiming either —
see cross-session note, same date.

**"Give co-change what it actually needs" — SOLVED, same day, by dwolfson-59** (reported via S2,
not yet merged into `ui/architecture-focus`): the answer was `git log --name-only`'s **default
inexact rename detection**, which scores blob-content similarity and is exactly what defeats
`--filter=blob:none` — 86 lazy fetches, confirmed by a packet trace. Fix is `--find-renames=100%`:
an exact rename compares blob OIDs already present in the tree, so it costs nothing extra, while
inexact detection has to fetch and diff content. Commit `63e7ec6` on `re/deferred-cleanup-followups`
(`cochange.py` only), merged into `re/survey-flows` at `d9e619f`.

Reported new measurement (dwolfson-59, via S2 — not independently re-run by S1): acquisition now
dominates the route's remaining cost rather than the reverse — 86% of `egeria_python_git`'s total for
`repo_arch_coupling`, 61% for `docling_parse`. **This dissolves the tiering question further than
this entry's own "the two converge and the question disappears" anticipated** — the cache-the-roots
fix above is now the more clearly load-bearing of the two remaining candidates, since the per-run
network chattiness this fix closed was the bigger of the two costs the earlier profiling found.

**Cache the acquired roots — DONE 2026-08-30.** Built by dwolfson-59 (not S1 — a three-way crossed
assignment: Dan gave it to S1 directly, S2 separately told dwolfson-59 to take it after dwolfson-59
flagged it as provider-shaped. Sorted between the three sessions before either duplicate build
started: dwolfson-59 finished it, S1 reviewed rather than rebuilding.

`resource_explorer/github/source_cache.py` — `SourceCache`, SHA-keyed, 4 GiB LRU budget, atomic
rename on write (two racers both do the work, one wins the rename, loser's copy is discarded).
Caches the **artifact** (`.zip`, treeless clone) rather than the extracted/checked-out directory —
every run still gets its own private tempdir via extraction or `git clone --local`, so concurrent
surveys cannot see each other's mutations. That boundary matters more than usual for a git clone
specifically: `git log` writes to `.git` for its own bookkeeping, so a shared clone would be a
corruption risk, not merely a leak. Keyed on the commit SHA (one extra API call, ~0.49s) rather than
the repo, so a stale hit is structurally impossible rather than merely unlikely; when the SHA can't
be resolved, or `shallow_since` is given (a bounded clone must never share a key with an unbounded
one), the cache is bypassed entirely and the old uncached behaviour runs unchanged.

Measured (dwolfson-59, `odpi/egeria-python`): acquisition 22.64s cold → 1.28s warm. Full route for
`egeria_python_git`: 110.5s originally → 30s after the rename fix above → **14.4s** now.

**S1's review** (cherry-picked as `a7e5364` on `ui/architecture-focus`, from `f8710eff` on
`re/deferred-cleanup-followups`):

- Confirmed the two load-bearing design calls are right: artifact-not-working-directory for
  isolation, SHA-keying for correctness. Would not have designed it differently.
- Found and fixed one real regression while closing the test-coverage gap dwolfson-59 flagged
  themselves (their two pre-existing provider test files route through the *uncacheable* path only,
  by design, so the cached path integration was untested): the cached branch of `zipball_root()`
  built `root / subproject_path` with **no existence check at all**, silently handing a caller a
  non-existent directory instead of `download_zipball()`'s `ValueError` listing available
  directories. Added `TestZipballRootCaching`/`TestGitCloneRootCaching` (9 new tests) exercising the
  actual integration seam — cache hit, cache miss, two-calls-share-one-download, and the
  `shallow_since`-bypasses-caching guarantee — plus the regression test that caught the bug above.
- **Eviction race — FIXED, same day, after dwolfson-59 pushed back on how "narrow" S1's first pass
  called it.** `_evict()`'s LRU sweep could delete a **directory** entry (a cached treeless clone)
  while a concurrent `local_clone()` was still hardlink-copying from it — `shutil.rmtree` mid-walk
  against files another process is reading. Zipball entries were always safe from this via POSIX
  `unlink`-of-open-file semantics; directory entries were not. S1's first framing ("requires the
  cache to be genuinely over budget AND mid-read at that exact moment") understated it: at ~50 MB
  per zipball, the 60-repo corpus is ~3 GB against the 4 GiB default — **over budget is the steady
  state once the cache fills, not an edge case** — and concurrent surveys are normal now, not
  hypothetical. Fixed with `eviction_grace_seconds` (default 60s): an entry touched more recently
  than that is never an eviction candidate, even if it is the oldest remaining and the cache stays
  over budget as a result — cheap, since `get()`'s touch is instant and the actual use
  (extraction/`clone --local`) measures 0.28-0.39s, so a generous window costs nothing in the case
  that matters. `total_bytes()` still counts protected entries, so budget accounting stays honest.
  Two other gaps stay open, unfixed, same category as before: no age bound/per-repo cap beyond
  overall LRU, and no invalidation on a tag/branch pointer moving under an already-held SHA.

Suite: 3033 passed + 9 new, 10 skipped (dwolfson-59's count plus S1's additions; not independently
re-run against the full corpus).

#### ~~MEDIUM — acquisition is now the whole cost~~ — SOLVED 2026-08-30

*(Restored: this entry and the one below were lost when a `--theirs` conflict resolution on this
file during the `ui/architecture-focus` merge dropped both. Second casualty of the same
cherry-pick-then-merge; found only by going looking for one of them.)*

After `63e7ec6` removed the blob-fetch cost, the download was essentially the entire wall-clock —
86% of the route for `egeria_python_git`, 61% for `docling_parse` — because both providers cloned
into a fresh tempdir every run. **Solved by `f8710ef`'s `SourceCache`**: acquisition 22.64s → 1.28s
warm, full route 110.5s → 14.4s. See the entry above for the design.

#### ~~LOW — `_COCHANGE_MAX_FILES = 50` is unvalidated~~ — MEASURED 2026-08-30, keep it

*(Opened by S2's review of `63e7ec6`; closed the same day by measuring it. The cap is defensible —
but it does not do what its name suggests, and that is the part worth keeping.)*

**Distribution**, four repos with real history. The six `--depth 1` clones pulled today were
excluded: a shallow checkout has one synthetic commit holding the entire repo, and DataHub's
19,009-file entry alone produced about half the uncapped pair total on the first pass.

```
p50   6 files      p90   55      max 2796
p75  16            p95  126
                   p99  308
```

**50 lands almost exactly on p90** — it keeps 89.8% of pair-bearing commits. Not arbitrary,
whatever its provenance.

**The quadratic case for *a* cap is overwhelming** — the last 10% of commits carry **98.8% of all
pairs**:

| cap | commits kept | pairs | % of pairs |
|---|---|---|---|
| 25 | 81.9% | 28,175 | 0.4% |
| **50** | **89.8%** | **85,835** | **1.2%** |
| 100 | 93.4% | 188,436 | 2.6% |
| 500 | 99.6% | 1,810,139 | 25.1% |
| none | 100% | 7,201,804 | 100% |

### The finding that matters: it is a cost control, not a quality control

Pairs are not the output — components are. Varying the cap and re-running `coupling.propose`:

| cap | egeria | egeria-python | egeria-workspaces |
|---|---|---|---|
| 25 | 703 | 52 | 72 |
| **50** | **728** | **61** | **82** |
| 100 | 743 (+15, −0) | 64 (+3, −0) | 96 (+14, −0) |
| 500 | 820 (+92, −0) | 82 (+21, −0) | 121 (+39, −0) |

**Raising the cap is purely additive — `−0` at every level.** Nothing proposed at 50 disappears at
500. So it is not separating signal from noise, as "skip the huge refactor commits" implies; it is
a volume limit. Across a **20× range** of cap, egeria's components move 703 → 820 (±13%) while
pairs move 4,151 → 597,225 (**144×**).

- **Raising it makes readability worse, not better.** egeria is already at 728 components against a
  clustering target of ~10 per blueprint.
- **The cost argument is weaker than it looks** at these sizes — even cap 500 on egeria runs in
  1.2s. What the cap buys is bounded *pair* growth for the quadratic tail, not wall-clock.

**Verdict: keep 50.** It sits on p90, it is monotone-subtractive so it cannot hide a boundary a
higher cap would reveal *differently* (only *additionally*), and component count is nearly
insensitive to it. What was genuinely unvalidated was the *reason* — the comment implies it filters
noisy commits, and it bounds volume instead.

**Honest limit:** four repos, all Egeria-family, and per-repo variance is large — at cap 50 egeria
drops 32% of its commits while egeria-workspaces drops 2%. A single global cap treats those very
differently. If anyone revisits this, a per-repo cap (that repo's own p90) is the shape to test, on
a corpus that is not four repos from one family.

#### MEDIUM — the analysis-card Run gives no prompt and no progress for slow work

*(Opened 2026-08-30, live-reported: "pressing the architecture survey button does seem to start the
task but it doesn't bring up the pop-up that asks if we should run this in the background so it's
easy to miss the toast".)*

Two different run paths exist and the analysis card has the weaker one:

| path | behaviour |
|---|---|
| **Survey Definition** (`showSurveyDefRunModal`) | modal with elapsed-time progress, backgrounds the run, polls the activity entry, relabels its button `Close — keeps running in background →`, and toasts *"can take a while — check 📋 Activity if you navigate away"* |
| **Analysis card** (`_runAnalysisCatalogCard`) | fires the POST, shows one `running` toast, and **blocks for the whole run** — no modal, no progress, no activity handle |

A contributing cause is a catalog value that is measurably wrong and **deliberately not changed** —
see the entry below.

That fix does not close this entry. The analysis-card path still has no backgrounding for anything
tagged `minutes`/`async`, and `POST /analyses/{id}/run` blocks rather than returning an
`activity_id` the way `/survey-definitions/{type}/{slug}/run` does. The work is to give the
analysis-card path the survey-definition path's shape — which is a route change plus a modal, not a
toast tweak.

#### MEDIUM — a compiled answer should be able to POINT at a view, not only describe it

*(Opened 2026-08-30. Dan: "there is no reason why, in some cases, it can't provide a link to an
architecture view elsewhere as well as providing a textual description.")*

Not a UI affordance — a change to **what a `Section` can resolve to**. Today every section resolves
to text that gets packed against a character budget (`trellis_context`'s `Candidate` carries
`{Rung: str}`), so the only way for an architecture question to reach the architecture view is for
the compiler to *describe* it in prose and hope the reader goes looking.

A section that resolves to a **pointer** — resource, analysis, perspective, and the scope to focus —
is different in three ways worth designing rather than bolting on:

- **It costs almost no budget.** A link is tens of characters where the prose summary of egeria's
  deployment architecture is hundreds. §9's packer currently trades detail against budget; a pointer
  section changes that trade, since the expensive thing lives at the other end of the link.
- **It stays correct as the data changes.** Packed prose is a snapshot; a pointer resolves against
  whatever the view shows now. That cuts both ways — it breaks the §10/§14 replayability guarantee
  (`same spec + same as_of + same materialized state -> same context`) unless the pointer carries
  `as_of` too, which is the interesting design question here.
- **It needs the target to exist and be addressable.** The architecture card now has perspective
  tabs, so "the deployment view of egeria_git" is a real thing to point at — it was not before
  today. Deep-linking to a perspective/scope is the prerequisite work.

Both halves are wanted: prose for the model to reason over, link for the human to go and look.
Likely shape is one section carrying both rungs — a short description at FULL, and the pointer as a
sibling field rather than a competing candidate — but that is a guess and the packer's contract
should decide it.

Related: `context-compilation-design.md` §23 (what this looks like in RE and EA) and §20 (resolvers
are mostly not RAG — a pointer resolver is about as far from RAG as a resolver gets).

**Status, 2026-08-30: the compiler half is built** (`trellis_context.packer.Pointer`,
`tests/test_packer.py::TestPointer`). Resolved as guessed above — pointer as a sibling field on
`Candidate`/`PackedSection`, never a competing candidate, and it does reach both halves: its
rendered form (`resource=… view=… as_of=…`) is appended to the packed text for the model, and the
structured `Pointer` travels on `PackedSection.pointer` / the manifest's `packed[].pointer` for a
UI to render as a real link. Sized at a small constant cost per candidate (added at every rung, so
it counts against the ceiling but never changes which rung is chosen — `_size()` in `packer.py`).
`as_of` is set from the pointing analysis's own `surveyed_at`, not compile time — same fact-vs-read
split `_provenance` already draws.

Wired for exactly one analysis so far (`context_compile.py`'s `_POINTABLE_VIEWS = {
"architecture_recovery": "architecture"}`), because it is the only one with a real view to point
at today. **What's still open, and it's the harder half:** RE's UI has no deep-linking at all — no
hash routing, no way to open the architecture card at a given perspective/scope from a URL. The
compiler now emits `{resource_slug, view, perspective, scope, as_of}` in a stable shape; turning
that into a clickable link is UI work in `index.html`, not `trellis_context`.

#### MEDIUM — presenting architecture recovery: a curator sees 20 of 1035 components

*(Opened 2026-08-30. Evidence and three costed options in
`architecture-recovery-presentation-findings.md` — findings only, no design chosen.)*

`egeria_git`: 1035 components recovered, 451 after depth projection, **20 rendered**, chosen
alphabetically by `path`. Four findings, in the order they are worth fixing:

1. **The `structural` flag is computed and ignored.** `_architecture_recovery_results` marks
   grouping nodes explicitly *so a consumer can render them as grouping rather than as a recovered
   component* — and no consumer reads it. They render as `untyped · 0%`, identical to a component
   we know nothing about, and because rows sort by `path` the **top line of Egeria's architecture is
   a placeholder for the repo root**. 75 of 451 rows. Two-line fix that still needs a visual
   decision, which is why it was not made in passing.
2. **Ordering is alphabetical**, so the clean 8-component deployment reading is in the payload and
   invisible behind 341 logical rows.
3. **Perspective is neither shown nor filtered on**, though §4.1 is emphatic the four are not
   interchangeable. Recommendation in the doc: perspective tabs defaulting to the smallest non-empty
   perspective — a comparison, not a threshold.
4. **Stale rows render identically to live ones** — resolved by tombstoning steps 1–3 for future
   runs, but the UI still has to choose between hiding a withdrawn component and showing it marked,
   and those are different answers for auditing history versus reading current state.

Deliberately measured and not designed: presentation is a product decision, and raising the row cap
treats a symptom when the problem is that they are the wrong 20.

#### MEDIUM — tombstoning step 4: backfill the orphans no run can ever withdraw

*(Opened 2026-08-30. Steps 1–3 are built; see `architecture-recovery-scope-tombstoning.md`.)*

R2 forbids withdrawing rows that no step is recorded as having written, and **every existing orphan
predates `run_label`** — measured, `_scopes_last_written_by` returns 0 scopes for `egeria_git`
today. So ordinary runs can never clear them:

```
egeria_git, all perspectives    870 live   165 orphaned  (15%)
egeria_git, deployment only       8 live    27 orphaned  (77%)
egeria_workspaces_git, deployment 69 live    2 orphaned  ( 3%)
```

A curator opening Egeria's deployment architecture still sees 35 components where 8 are real.

The backfill is **weaker evidence than a withdrawal from a real run** — it is a human asserting a
scope is vacated, not a step observing it — and must say so: `cause: unclaimed`, plus a detail
recording that it came from a dated backfill rather than a survey. A backfill writing rows
indistinguishable from earned ones would launder an assertion into an observation.

Last of the four steps deliberately, because it is the only one that touches already-published data
and cannot be undone by re-running a survey.

#### MEDIUM — borrow reflexion models' three-way vocabulary for curator verdicts

*(Opened 2026-08-30, from a literature pass cross-reading this file against the academic/commercial
record — feeds the "take architecture results into Curate" item above.)*

Murphy, Notkin & Sullivan's reflexion models (IEEE TSE 2001, building on the 1995 SIGSOFT paper)
name three outcomes when an extracted model meets a hypothesized high-level one: **convergence**,
**divergence**, **absence**. That is a ready-made vocabulary for the undesigned axis in the item
above (accept/reject/retype a proposed component) — a curator note *converges* with a detector's
finding, *diverges* from it, or names something the detector found nothing for (absence). Cheaper
to adopt their names than invent new ones, and their process is worth the same treatment: reflexion
is explicitly iterative, recomputed each time the human's model changes, not a one-shot verdict.

**Open question the paper does not answer.** Reflexion models are computed against *one*
hypothesized model at a time — the technique is silent on whether "architecture" is absolute or
perspective-specific. Architecture recovery already has four perspectives (Logical/Deployment/etc.,
design doc §4.1) where the same component can read differently depending which view is asked.
Nothing in the 2001 paper or its 1997 case-study followup addresses running reflexion per-
perspective and reconciling the results — a component might converge under Deployment and diverge
under Logical simultaneously. That reconciliation is genuinely new design work, not something to
borrow.

#### MEDIUM — separate "correct" from "useful right now": confidence and utility are different axes

*(Opened 2026-08-30. Dan: "the goal isn't just architecture recovery — its recovery and
understanding of useful artifacts... the threshold for useful isn't static — so at one end of the
scale it might be everything, at the other it might be that we don't publish any of the artifacts
we discover.")*

CleanGraph's pattern (arXiv:2405.03932 — confidence/source/extractor metadata per edge, low-
confidence routed to a human queue) is the wrong borrow if read as confidence routing alone.
**Confidence** — is this component real? — and **usefulness** — is it worth a curator's attention
*right now*, out of everything else competing for it? — are orthogonal. A component can be detected
with high confidence and still not be interesting at the current threshold (a leaf utility module);
a low-confidence guess can be exactly what a curator needs to see because it's the one thing
standing between them and understanding a subsystem that matters.

The 1035→451→20 collapse (`architecture-recovery-presentation-findings.md`) is already implicitly
answering this question by discarding most of the graph — but as a fixed row cap, which is the
wrong shape for a threshold that needs to slide from "show everything" to "publish nothing found."
Worth designing as an explicit, adjustable utility score — a field separate from Confidence, not
folded into it and not a hard-coded cap. Related: the presentation-findings item above already
names the row-cap symptom; this names what the missing control actually is.

#### MEDIUM — the replayability guarantee is only as strong as the resolver behind it

*(Opened 2026-08-30. Dan, re: RAGdeterm's structured-retrieval determinism: "isn't it also
dependent on mechanism too?")*

Yes — and this sharpens `context-compilation-design.md` §9's untested claim rather than settling
it. RAGdeterm (ScienceDirect, 2026) gets determinism by grounding retrieval in an explicit
structured representation instead of similarity search — the same move the packer makes (resolvers
over Egeria's materialized state, not a vector search). But "structured query" does not imply
deterministic: an unordered `SELECT`, a paginated cursor, or a resolver that calls an LLM
mid-resolution are all "structured" and still non-replayable. This file's own telemetry item
(top of this section) already flags that a survey step can be LLM-based and non-deterministic —
this is the same fact one layer up: **the replayability contract needs to be a property the
compiler can check per-resolver**, not an assumption that holds because the store is structured.
Worth a `deterministic: bool` tag on the resolver registry, mirroring the `run_time`/cost tags
CLAUDE.md rule 17 already requires.

#### LOW — Collibra's status lifecycle, checked

*(Opened 2026-08-30, the promised follow-up on the item below.)*

Collibra's Business Term lifecycle is **Candidate → Under Review → Accepted**, with **Rejected** a
terminal state reachable from Candidate (an Onboarding Workflow moves a term out of Candidate;
ineligible terms go to Rejected instead). Close to a 1:1 match for the ContentStatus ladder nothing
here walks yet.

The more useful thing to borrow isn't the four names — it's that Collibra implements statuses and
the transitions between them as **configuration, not code**: a "Workflow Definition" declares which
status transitions are legal, separate from the status values themselves. Worth copying regardless
of what the final state names are, since it means a fifth ContentStatus later doesn't mean finding
every place a transition is hard-coded. Could not verify Collibra's edge-case handling (what
happens to relationships when a term is rejected; whether Rejected can re-enter Candidate) from
public docs — that needs a live instance or their admin guide, not marketplace/product-resource
pages.

#### HIGH — Egeria already has this: `Memento` is architecture recovery's tombstone, native

*(Opened 2026-08-30. Dan: "Egeria itself also implements tombstones (called mementos) in order to
preserve lineage graphs over time. But sounds like there is more to learn here.")*

Confirmed against the local Egeria checkout
(`open-metadata-types/.../OpenMetadataTypesArchive2_6.java`, `addMementoClassification`) and
egeria-project.org: `Memento` is a classification attachable to any `OpenMetadataRoot` entity,
carrying `archiveDate`/`archiveUser`/`archiveProcess`/`archiveService`/`archiveMethod`/
`archiveProperties`. Its stated purpose: *"indicates that an element is logically deleted because
it is no longer describing all or part of a real-world digital resource... retained to support
lineage graph queries."* **Memento elements are excluded from normal queries and only returned when
the caller passes `forLineage`.**

That is this project's tombstoning design, already built, natively, in the platform it is
Egeria-first about. `WITHDRAWN_LABEL` (steps 1–3, `architecture-recovery-scope-tombstoning.md`)
reimplements the same shape locally: mark-not-delete, retained for history, hidden from normal
reads. Two things worth checking before step 4 (the backfill, above) goes further:

- Does the local tombstone need to keep existing once a component is actually projected to Egeria
  (Phase 2, still unbuilt — the item at the top of this file), or should local withdrawal just set
  `Memento` on the published element and let Egeria's own `forLineage` filtering do the hiding?
- If both are going to exist for a while (local proposals aren't published, so have nothing to put
  `Memento` on), the *fields* are worth matching now rather than reconciling later —
  `archiveProcess`/`archiveMethod` map onto exactly the "which step withdrew this, and how"
  provenance `cause: unclaimed` (the backfill item above) is already trying to express by hand.

Not "redone from scratch was wasted work" — the local version had to exist before anything reached
Egeria, and still does for proposals that never get published. But it's now clear there's a real
convergence point once Phase 2 lands, and designing step 4's backfill without checking `Memento`'s
shape risks diverging further from a mechanism that already solves the identical problem one layer
up.

#### Note — is the eight-intent/curation model more complex than anything proven to need it?

*(Opened 2026-08-30. Dan: "I wonder if our model is too complex and unnatural — something to keep
in mind.")*

Not a task — a caution worth keeping attached to future design work rather than resolving. Two data
points from this session's research feed the worry directly: **no commercial catalog surveyed**
(Amundsen, DataHub, Atlas, Collibra, Alation, Purview, Dataplex) **implements more than a two-tier
automated/human split** — nothing resembling eight named intents exists in production elsewhere.
And Egeria itself shipped `Memento` — a working tombstone — years before this project built its own
(the entry above). Neither is proof the model is over-built: eight intents may be doing real work
seven vendors happen not to need, the same way architecture recovery's multi-perspective view does
work Reflexion Models never had to (the vocabulary entry above). But "nobody else needed this many
moving parts" and "we rebuilt something that already existed one layer down" are both the kind of
signal that's easy to miss from inside the project, and worth someone periodically asking from
outside it rather than only from the momentum of the backlog that's accumulated.

#### LOW — coupling's decision trace is 250 copies of one line

*(Opened 2026-08-30, surfaced by persisting the trace — invisible while it was `log.info`-only.)*

First real measurement of `architecture_decisions` on `egeria_git`:

| step | notes | shape |
|---|---|---|
| `detect` | 4 | all high-signal — distillation arithmetic, platform consolidation, the variant drop |
| `coupling` | **263** (200 kept, 63 truncated) | **250+ are one templated line**: `.: adopted unproposed subtree X (nothing else claims it)` |

A trace dominated by one repeated message crowds out the notes a reader wants. Whether those should
collapse into one summary note (`adopted 250 unproposed subtrees`) or are genuinely per-decision is
a judgement about coupling's own semantics — hence LOW and not fixed in passing. The cap already
reports the overflow rather than hiding it, so nothing is silently lost meanwhile.

#### LOW — the decision-trace lookup is linear in run count

*(Opened 2026-08-30.)* `_withdraw_vacated` reads the kind's whole finding history on every persist —
**10,135 rows / 93ms for `egeria_git`**. Fine inside a survey that takes seconds, but history is
append-only and never pruned, so this grows with every run. Measured and recorded rather than
pre-optimised; the narrower two-query form (find the step's latest `surveyed_at`, then select only
those rows) is available if it ever matters. Likeliest trigger for the telemetry item above.

#### HIGH — architecture recovery: coverage closed on 2026-08-28; precision is now the whole entry

**The first version of this entry said "3 of 46, 6% coverage". That was wrong, and wrong in the
way this project keeps being wrong: the query was `query_findings(slug, kind)`, which defaults to
`scope_locator=''` — whole-resource. Architecture recovery writes one finding set **per component
scope**, so a default-scope query sees a repo only if it has a single root-scoped component. It
found `docling_parse` (1 component) and missed `milvus` (202).** Corrected with
`query_finding_scopes()`:

```
repos the gate approves for recovery          46
repos WITH architecture_recovery results      16   (15 of them gate=run)
```

**Superseded 2026-08-28 — coverage is no longer the blocker.** A batch landed after the
measurement above: the findings histogram runs 1 → 5 → 10 → 31 → 42 resources across
2026-08-21..26. Re-measured live on 2026-08-28: **46 of 60 registered repos now carry
architecture_recovery results**, against 16 when this was written. The 14 without are
largely gate-excluded (a docs site, an awesome-list, an unindexed new repo).

A separate session measured the gate-eligible slice specifically and reports 45 gate=run
resources fully accounted for — 41 with results, 3 with a *verified* real zero
(`outcome_known_positive=true`, `no_components_detected`), and 1 (`unitycatalog_rs`)
genuinely unverified because it is 100% Rust and the marker languages are Go, Java and
Python. **Those figures are theirs, not reproduced here**: I verified the headline
independently and got a different denominator (all repos, not gate=run), which is enough
to retire "a third of the corpus" but not enough to restate their breakdown as mine. See
`docs/task-list-2026-08-28.md` for that measurement.

So the remaining work in this entry is **precision, not coverage**. The note below about
the measuring instrument still stands and is why the original number was wrong twice.

Fifth instance of the measuring instrument being the broken part, after findings 73, 79, 90 and
the `resolve_doc_locations`/`build_report` timing confusion. The standing prior holds: **when a
number about this system looks wrong, suspect the query before the subsystem.**

The whole stack exists and is tested — detectors, import graph, coupling, `interfaces.propose()`
for ports and wires, the deterministic distiller, the LLM adjudicator, identity-aware scoring, 98
recorded findings. The gate now correctly identifies which 46 repos are worth running it on
(finding 97, corpus re-measured at 46 run / 8 skip / 6 none). It has been *run* on three.

**This is capability without coverage, and it is the largest single unclaimed benefit in the
project.** Everything downstream — the Egeria Solution Blueprint projection, the deployment
topology view, anything that needs more than one repo's architecture to be interesting — is
waiting on data that nothing is blocking.

**Cost, from `STEP_REGISTRY.requires_resources`:**

```
repo_arch_detect     {'zipball_root': 'local_path'}                        download, no clone
repo_arch_coupling   {'zipball_root': ..., 'git_clone_root': 'history_path'}   download AND clone
```

So `repo_arch_detect` across 46 repos is 46 zipball downloads — feasible unattended. Coupling is
materially more expensive and should be a separate decision made after detect has run.

**PILOT RUN 2026-08-24 — 5 repos, detect only, 0 errors, 4.4s–54.8s each.** Chosen to test the
three "unprioritisable" language defects rather than for speed. It reprioritised all three:

```
milvus                 26.5s   202 component scopes   ground truth says 8
docling_java            4.4s     8 component scopes
egeria_workspaces_git  38.6s    72 component scopes
docling_parse          54.8s     1 component scope
genaicomps             16.9s   311 component scopes
```

- **"Java marker components are all named `src`" does not reproduce.** `docling_java` yields
  `docling-bom`, `docling-core`, `docling-serve-api`, `docling-serve-client`,
  `docling-testcontainers`, `docling-version-tests`, `test-report-aggregation`, `docs` — real
  Maven module names, zero scopes ending in `src`. The defect was observed on Kafka (Gradle) and
  is either Gradle-specific or was fixed by the Gradle module expansion work. **Downgrade; re-test
  on Kafka before spending anything on it.**
- **The `cmd/X` + `pkg/X` merge is not the live Go problem.** Milvus has **one** `cmd` scope and
  **145** `internal/*` scopes. There is almost nothing to merge. **Downgrade.**
- **Precision is the live problem, and it is severe.** Milvus proposes **202 components against a
  published ground truth of 8** ("five core components and three third-party dependencies", the
  Milvus authors' own words). `genaicomps` proposes 311. Every `internal/*` package becomes a
  candidate component. This is the same precision gap the spike measured on Kubernetes (3303 →
  358 deterministic → 93 adjudicated) — **the distiller exists and is not in the product path.**

**So the ranking inverts.** Running detect across the remaining 31 repos would produce thousands of
component findings at roughly 25:1 over-proposal, which is not coverage, it is noise at scale.
**Port the distillation and ranking stack into the product path first** (`scripts/arch-spike/`
`distill.py`, `rank.py`, and optionally `adjudicate.py`), re-run the pilot 5, and only then decide
on the full corpus. Cost is bounded and known: detect averages ~28s/repo with no clone.

---

#### Architecture recovery — the PORTED implementation has never been scored

Phase 1's declared numbers (13 of 13 components, 97% coverage, ARI 0.969 —
`docs/architecture-recovery-phase1-findings.md`) were measured on the **throwaway spike** in
`scripts/arch-spike/`. What shipped into `resource_explorer/surveyors/arch_recovery/` is a *port*,
and it has at least one known behavioural difference: the spike merged agreeing proposals at IR
level and boosted confidence on agreement, while the port discovers agreement at read time by
grouping on `scope_locator` and does not boost. There may be others; nobody has checked.

**Do not assume the port reproduces the spike's numbers.** Run `score.py` against the ported
pipeline's output and the pre-registered fixtures, and record the result. If it differs, that is a
finding either way — the port is wrong, or the merge mattered less than assumed.

This is the same class of error the spike hit three times (README findings 15, 30, 37): assuming a
property of the code when it was actually a property of how the code was being measured. A port
that passes its unit tests can still partition differently.

Cheap: `score.py` and the fixtures already exist; only the plumbing from the ported pipeline's
output to the scorer is new.

---

#### Architecture recovery — re-check the Phase 1 measurements once there are more samples

**Not a doubt about the current numbers; a limit on what two repos can establish.** Phase 1's
measurement goals were declared met on 2026-08-20 (`docs/architecture-recovery-phase1-findings.md`)
— 13 of 13 components, 97% file coverage, ARI 0.969 on trellis, T1 recall held at 18/27, 5.3s per
repo. Every criterion in the plan's §5 was cleared, several by a wide margin.

Re-run the whole evaluation, and expect to revise, when there is materially more experience:
**roughly 8–10 surveyed repos of varied shape**, or the first time a real user disagrees with a
partition RE published.

What only more samples can settle:

- **n=2, and they are not independent.** trellis is a well-factored Python monorepo — close to the
  best case for import cohesion — and `egeria-workspaces` is a flat app. Both are ours, both are
  Python, both were partly written by the people writing the detectors.
- **`COHESIVE_BAR` and `DISPERSION_BAR` are unvalidated.** They were set by inspection on one
  repo. The Phase 1 plan's own preferred answer (Newman modularity as a null-model threshold) was
  tried and failed — `Q > 0` admitted 15 of 16 candidates (README finding 33) — so the current
  bars are a placeholder, not a result.
- **The residue rule is a known trade, not a solution.** Adopting unproposed subtrees took
  `Utility scripts` to exact and `Core` from exact to 0.51, because the two ground-truth entries
  disagree about residue ownership *deliberately* (finding 44). More repos will show which reading
  is the common one — or that it is genuinely per-repo and belongs to a human.
- **T2's ground truth is not a clean pre-registration.** The trellis component count was reported
  to the maintainer before the fixture was written. Contamination runs the safe way — the fixture
  contradicts the detector rather than echoing it — but it is a caveat on T2's numbers that a
  fresh repo would not carry.
- **T1 precision is 0.31 and is not really understood.** It is dominated by add-on granularity
  (finding 12), where the maintainer names a 9-container bundle as one component. Whether that is
  a fixture inconsistency or the normal way people think about add-ons needs more than one
  example.
- **Python only.** `imports.py` extracts Python; `egeria` has zero tracked `.py` files, so the
  obvious adversarial target cannot be scored at all and "does this generalise beyond Python?"
  is currently unanswerable.

**Cheap to redo, which is the point.** `score.py`, `coupling.py` and the pre-registered fixtures
already exist, so re-running is hours, not a phase — provided new targets get **pre-registered
ground truth written before the detectors run on them** (`tests/fixtures/architecture-ground-truth/README.md`).
Writing that fixture is the actual cost, and it is what makes the re-check meaningful rather than
a re-confirmation.

Related: `docs/approach-portfolio-model.md` §4 proposes recording approach outcomes against repo
characteristics — if that is built, this re-check becomes a query rather than an exercise.

---

#### Phase 5 distillation — what the ranking experiment settled (finding 77)

`scripts/arch-spike/rank.py` measures recall@N over ranked candidates. Conclusions, all measured:

* **An adjudicator needs hundreds of candidates, not thousands** — N≈25 / 100 / 250 for Prometheus /
  Milvus / Kubernetes under the `typed` strategy. 250 evidence-carrying candidates is a tractable LLM
  input; 3303 is not.
* **Do not rank by the emitted confidence.** Worst strategy at every N on every target (1/11 at N=25
  on Prometheus vs 9/11 for `typed`). §3.3b confidence describes *how identity was established*, not
  *how likely this is a component*.
* **`rollup` ties `typed`** — negative result; the extra machinery is unjustified by current evidence.
* **The remaining gap is structural, not a ranking problem.** A declared component's minimal cover is
  2–3 nodes (`kube-controller-manager` = `cmd/kube-controller-manager` + `pkg/controller`), and *all*
  of them must be in the window. Until something merges the `cmd/X` and `pkg/X` arms into one
  candidate — which is what the ground truth declares — each such component costs 2–3 slots instead
  of 1.

**Note on gap-list item 3 (finding 89):** it was reported closed when `interfaces.propose()` was
committed, but its only caller was the spike harness — the survey step never computed ports and
`persist_ir` never stored them. Now genuinely wired: `arch_recovery_detect` computes them and
`persist_ir` writes an `architecture_interfaces` finding kind. "Committed and regression-tested" is
not "reachable".

**Attempted and does not work by import evidence (finding 78).** Strict-majority dominance from entry
point to package finds the right partner 6 times out of 7 (`pkg/scheduler` share 1.00,
`pkg/controller` 0.97, `pkg/proxy` 0.97, `pkg/kubelet` 0.83) **and over-reaches every time**, pulling
in 3–44 extras such as `pkg/util/iptables` and `pkg/apis/*`. No merged set equals the ground truth.
The distinction between "`pkg/proxy` **is** kube-proxy's implementation" and "`pkg/util/iptables` is a
utility it **uses**" is not encoded in the import graph — both are imports dominated by one binary.

The pairing *is* recoverable by name (`kube-scheduler`↔`scheduler` after prefix-stripping; Milvus's
`internal/proxy` + `internal/distributed/proxy`), but **that is fitting to the two repos measured** and
would be believed only after validating on a repo nobody here has looked at. Left open deliberately
rather than shipped.

**A real fix did come out of it:** entry points are packages declaring `package main`, not
directories containing a file called `main.go` — Kubernetes's are `scheduler.go`, `kubelet.go`,
`proxy.go`. Closes the `has_main` type-inference weakness; Prometheus no longer mistypes `promql`,
`util` and `documentation` as `Console Command`.

---

#### Location-valued artifacts: 31% are NOT in the repo — the corpus number

Measured 2026-08-24, first full run of `repo_classification` across all 60 registered repos
(26.7 min, 0 failures, on the post-`fd2e5a7` path). Recorded here because it answers a question
the architecture-recovery design could previously only answer from five hand-picked projects,
and because that session asked for it explicitly and has since ended.

```
artifacts located              140
located ELSEWHERE               43   (31% of located)
repos with >= 1 elsewhere       25   of 60
max elsewhere in one repo        3
```

**A boolean "does this repo document its architecture?" would answer *no* for 43 artifacts
that exist and were found.** §5.5b's location-valued design (`in-repo` / `sibling-repo` /
`doc-site` / `not-found`, only the last an absence) is therefore paying for itself on a corpus
nobody selected to flatter it — the point being that the spread is unglamorous and even
(polaris 1, docling_eval 1, docling_java 3, docling_mcp 1) rather than concentrated in the
famous Kubernetes case. A steady third across 25 repos is a stronger argument than one
spectacular example.

Corpus shape, first time this has run everywhere:

```
roles  samples 16 · application 13 · documentation 11 · library 6 · tutorial 5 · middleware 2 · tool 1 · none 6
gates  run 47 · skip 7 · none 6      <- superseded, see the re-measurement below: 46 · 8 · 6
timing min 7.2s · median 25.5s · max 58.6s
```

Two things worth someone's attention:

- ~~**The gate lets 87% through** (47 run, 7 skip of 54 classified)~~ — **CHECKED, and the
  ratio is roughly right.** The architecture-recovery session measured it rather than
  re-running anything (every gate decision persists its own reason string with the signals
  named): of 32 repos carrying a non-architectural role, 25 were overridden, and
  `package-manifest` was present in 19 of those but **decisive alone in only 3**. Dropping it
  entirely moves 7 skips to 10 — 87% to 81%. The gate has containment semantics precisely so a
  samples repo with compose files still runs, and on a corpus that is mostly real software,
  that is what happens.

  **Both of us had guessed the wrong mechanism from the right aggregate.** `package-manifest`
  looked weak because a Python samples repo has a `pyproject.toml`; the aggregate did not
  contain that story. Reading the n=3 decisive cases *by name* found the actual defect:
  `OpenLineage/openlineage-site` is 71% doc-shaped with a `docusaurus.config.js`, no Dockerfile
  or compose — and a `package.json`, **because Docusaurus is a Node program**. So the manifest
  is not a weak signal; it is the only structural signal a documentation site can produce by
  itself. Fixed by making the generator config its own `doc-site-generator` signal and
  discounting `package-manifest` when it is present.

  Recorded because it is the third time the pattern has appeared: aggregate read correctly,
  mechanism guessed wrongly, small-n cases read by name giving the answer. "25 overrides" is a
  number; "`openlineage-site` is a Docusaurus site" is what tells you what to change.

- ~~**The 47/7 above is a snapshot, and one repo of it is already known to move.**~~
  **RE-MEASURED 2026-08-24** — `repo_classification` re-run across all 60 repos after the
  `doc-site-generator` fix: **25.5 min, 0 failures, 46 run · 8 skip · 6 none.** Exactly one
  repo moved (`openlineage_site`, run → skip, generator-owned package manifest) and the other
  53 are unchanged, which is what a narrow fix should produce.

  **47/7 was correct when taken; 46/8 is correct now.** The prediction was deliberately NOT
  written in as a measurement while it was still a prediction — that decision is what this
  re-run discharges, and the practice is the transferable part: a prediction in the slot where
  a measurement belongs is the substitution this file exists to avoid, and the cost of holding
  the line was one 25-minute run. Full breakdown and the named skips in
  `docs/archive/arch-recovery-handoff-2026-08-24.md`.
- **The 6 repos with no role have no file inventory** — never ingested, so nothing to classify.
  Correct behaviour, and the card now says which kind of nothing it is rather than showing a
  blank.

---

#### Repo classification — what the repo *represents*, before what its architecture is

**Maintainer direction, 2026-08-22; design §5.5b.** Classify a repo (or each member of a repo family)
as library / application / middleware / tutorial / samples / documentation / tooling, **because the
classification decides which analyses and which questions are relevant.** Recovering a blueprint from
a tutorial repo is not a weak result — it is the wrong question, and spike finding 58's `workshops`
false positives were settled exactly this way, by a human reading a README that stated the repo's
intent.

Cheapest possible funnel gate (rule 17): it rules out whole *categories* of analysis rather than
individual steps. Every signal it needs is already collected — README intent statements, whether
published architecture docs exist at all, manifest declarations, absence of deployment artifacts,
test/example/notebook ratios, and dependency direction.

Open on purpose: **do not invent a closed vocabulary** before checking Egeria's existing types
(`SoftwareCapability` subtypes, `plannedDeployedImplementationType`) — §3.1's 13-value
`SolutionComponentType` turned out to already exist rather than needing invention. Also open: whether
a monorepo gets one classification or one per workspace member (`trellis` alone holds an application,
two libraries and a spike).

**It is a gate, not a weighting** (maintainer, same session): on a tutorial/samples/documentation
repo, architecture recovery **does not run**, saving the whole tier rather than filtering after the
expensive work.

**Needs the owner of `step_outcome.py`.** None of the five labels fits a skip-because-irrelevant.
`no_signal` requires `known_positive=True` (proof the detector works) and nothing ran; `unverified`
means "could not run", but here we *could* have and chose not to — a success of the funnel, not a
failure. The distinction that must survive: **"didn't run because it would have been the wrong
question" vs "ran and found nothing"**. Conflating them makes the funnel's biggest win look like its
most common failure. Do not add a sixth label unilaterally.

**Second axis — project topology, not just repo role** (maintainer, same session). How a project
distributes concerns across repos is a matter of style and trend, and it decides *where to look for
what*. RE already models this (`projects.parent_slug`, `group_slug`, `homepage_url`, `docs_url`);
nothing asks the question. Five topologies are already measured (finding 68): **four of five projects
put documentation in a sibling repo** — `milvus-docs`, `kubernetes/website`, `egeria-docs`,
`prometheus/docs` — with only `egeria-workspaces` keeping it in-tree mixed with code and tutorials.

**Expectation sets, location-valued.** From the role, derive what a mature project of that kind
should have, then find it. **Each expected artifact resolves to `in-repo` / `sibling repo` /
`doc site` / `not found`, not to a boolean** — finding 68 is the cautionary tale, since "where are
the docs" answered naively against `kubernetes/kubernetes` returns "nothing, stale 1400 days" when
the truth is "in `kubernetes/website`, updated today". **Requires §5.5a(a)'s outward hop as a hard
prerequisite.**

Absence cuts both ways and must not be conflated: no deployment artifacts in an *application* is a
maturity finding; in a *library* it is confirmation of the classification (`trellis.md` records
exactly this). Same guardrail as §5.5a(c): report locations as dated evidence, **do not rank on the
count** — a small stable library documents lightly on purpose.

**Offer to widen the scope to sibling repos** (maintainer, same session). When the expected artifacts
for a role are not in the repo the user named, ask whether to include other repos of the project. The
location-valued lookup already produces the candidate list, so the question is "shall I include
`kubernetes/website`?", not "which repo?".

* **Ask, never auto-add** — silent scope expansion causes unrequested fetches and results that cannot
  be compared with the previous run. Precedent: the maintainer's "present the user with a file tree
  with checkboxes" answer on ambiguous partitions.
* **Record the in-scope repo set with the result** — it changes every coverage denominator, the same
  reason `trellis.md` carries a `Scope:` line (whole-repo coverage 15% vs in-scope 48%), and the same
  argument §6.2 makes for `analyzerVersion`.
* **Classification first** — "missing" is only defined relative to role; a library is *expected* to
  have no deployment artifacts.
* **Reuse RFA and `projects.parent_slug`/`group_slug`** — a new question, not new plumbing.

**Built and verified: `resource_explorer/github/doc_locations.py`.** Resolution + location-valued
lookup, checked live against all five measured topologies — Kubernetes `docs/` correctly reported as
a **tombstone** with docs resolving to sibling `kubernetes/website`, Prometheus showing **both**
in-repo `documentation/` and sibling `prometheus/docs`. The two lookups that encode the bug both
pass: `find_artifact("architecture")` returns `in-repo` (`documentation/internal_architecture.md`)
for Prometheus and **`sibling-repo`, not `not-found`,** for Kubernetes. 28 hermetic offline tests.

*Known limitation, documented in the module:* a bare `website`/`docs` sibling is the project's own
only when the org ≈ the project. `kubernetes/website` matches correctly; `odpi/website` is the
foundation's site and is returned for both `odpi/egeria` and `odpi/egeria-workspaces`, belonging to
neither. Deliberately unfixed — dropping bare `website` would break the Kubernetes case this module
exists for. **The evidence already discriminates**: `odpi/website` was last pushed **2019-11-07**
while `kubernetes/website`, `prometheus/docs` and `odpi/egeria-docs` were all pushed within two days
(verified 2026-08-23). A consumer reading the date can discount it without the module deciding —
suppressing it here would *be* the ranking judgement §5.5a(c) forbids. And §5.5b asks before
including a sibling, so an extra dated candidate is a checkbox, not a wrong answer.

**Role classifier built** (`resource_explorer/github/repo_role.py`, 46 hermetic tests). Seven roles,
multi-valued with a primary, every role carrying the evidence that produced it. Live-verified:
`kubernetes/website` and `odpi/egeria-docs` → `documentation`; `milvus-io/milvus` and
`prometheus/prometheus` → `application`; `odpi/egeria-workspaces` → `tutorial`+`application`+`library`.

**Gate correction (design §5.5b).** `egeria-workspaces` ranks `tutorial` primary and is *also* target
T1, from which architecture recovery scored 18/27. A gate keyed on the primary role would skip it.
**Trigger the skip on containment, not primacy:** skip when a tutorial/samples/documentation role is
present AND no deployment/structural artifacts were found. Primacy still drives the expectation set.

**Known limitation, evidenced not tuned:** the README-intent matcher requires an *is-a* phrasing
(`X is a tutorial`) and misses *purpose* phrasing — `egeria-workspaces`'s "designed for learning" is
an explicit statement of intent that §5.2 step 0 says should outrank inference, and it does not fire.
The role was recovered from notebook presence instead. Broadening the pattern should be validated
against a repo not yet looked at, not tuned on this one.

**Expectation sets built** (`resource_explorer/github/expectations.py`, 14 tests). Role → expected
artifacts → each resolved to a location by `doc_locations.find_artifact`, with four states kept
separate — `found`, `missing`, `confirmations` (not expected AND absent, which *supports* the role),
`unexpected`. **No count, percentage or grade is exposed**, and a test asserts none leaks in.

Live gate results: `odpi/egeria-workspaces` → **RUN** (tutorial primary, but deployment artifacts
present — the case that would have been wrong under a primacy gate); `odpi/egeria-docs` → **SKIP**;
Prometheus and Milvus → RUN with all four expected artifacts located.

**Two limitations found live, recorded not tuned:**

1. **The gate over-runs on documentation repos with their own build tooling.** `kubernetes/website`
   returns RUN, because its Hugo/npm build supplies `package-manifest` and `deployment-artifacts`
   signals — build tooling for the docs, not a product architecture. Mechanically separating
   "tooling that builds the docs" from "the thing the repo is about" is not obviously possible from
   these signals. **The direction of the error is the safe one**: a false RUN wastes a tier, a false
   SKIP loses real work, so the gate is deliberately left conservative. Revisit only with a signal
   that distinguishes them.
2. **`find_artifact("readme")` prefers a nested README over the root one** — it returns
   `documentation/prometheus-mixin/README.md` for Prometheus and `docs/README.md` for Milvus, when
   the root `README.md` is plainly the right answer. Doc directories are searched before the repo
   root. Small, real, and worth fixing in `doc_locations` (root should win for `readme`).

**Companion item, deferred by the maintainer to a separate discussion: capturing the user's intent.**
What the repo *is* and what the user *wants from it* are two different filters on which analyses
matter; conflating them would be a mistake.

---

#### Documentation as source, as dated source, and as signal (design §5.5a)

Three implementable items came out of the Milvus ground-truth exercise (spike README findings 65–67).
All three are Discovery-tier by rule 17's test — cheap, and they gate the expensive tiers.

**1. Step 0 needs an outward hop to the project's doc site.** §5.2 step 0 reads in-repo docs only, and
Milvus proves that insufficient: the authoritative logical architecture is at `milvus.io`, while
`milvus-io/milvus`'s own `docs/` has a README, `design-docs/`, `agent_guides/` and `archive/` but not
the front-door architecture page. Resolve the doc site from README links, repository metadata, or the
package manifest homepage, and treat a published architecture page as a first-class distillation
input. One fetch, once. Open question: how to recognise *which* published page is the architecture
page without hand-curation — a per-project hint in the fixture is fine to start.

**2. Path-dating, to put a vintage on any prose architecture.** `GET
/repos/{o}/{r}/commits?path={p}&per_page=1` dates any path; for a path that no longer exists that is
effectively its removal date. Vintage is bounded above by the newest dead path a description cites;
blind spot is bounded below by the churn of live paths it omits. Verified on Milvus — four calls
dated a stale description at ~17 months old without reading any Go. Should run on **any** prose
architecture we consume *and on our own recovered blueprints*, with the dates carried in §5.4
evidence. Cheap to build; the only real design choice is where unresolvable paths surface, and the
answer is probably "as their own outcome", never silently as detector misses.

**2a. Resolving where the docs live is a PREREQUISITE for item 3, not a sibling of it.** Measured
over twelve repos (spike finding 68), five of five checked keep documentation in a *separate,
actively-maintained repo*. `kubernetes/kubernetes/docs/` holds only `.gitignore` and `OWNERS` — a
tombstone — so the naive doc-lag metric scores Kubernetes at 1412 days of abandoned documentation
while `kubernetes/website` was pushed the same day. Resolve the docs location first (item 1), then
measure (item 3). Detect the tombstone pattern explicitly: a docs directory holding only
`OWNERS`/`.gitignore`/README stubs means deliberate relocation, which is a *positive* curation signal
of the same class as Milvus's maintained `docs/archive/` and Egeria's `saved/`.

Useful consequence: because the docs repo is a git repo, item 2's path-dating applies to the document
itself as well as to the paths it cites — two independent dates that cross-check, no heuristics.

**3. Doc-health as a reported signal.** Not what the docs say — whether they exist and are kept
current. Compare commit recency of doc paths against code paths; note whether stale docs are archived
(Milvus maintains `docs/archive/`, which is a stronger marker than merely having docs) or left in
place. Milvus's lag is one day. This is the measurable half of the triage judgement finding 58 needed
a human for. **Report as dated evidence, do not rank on it** — a maintained doc site can coexist with
rotting in-repo docs, and a small stable library may document lightly on purpose. A naive `docs/` mtime
is also too coarse on its own (one typo fix moves it); prefer a distribution over doc paths, and
per-component lag where §6.0 scope locators make that possible.

**4. Ground-truth candidates the scan surfaced**, in the order they should be attempted — this feeds
the pending 8–10 repo measurement re-check:

| candidate | why | caveat |
|---|---|---|
| `prometheus/prometheus` | `documentation/internal_architecture.md` is **in-repo**; 281 MB | **DONE** — pre-registered `9039f9a`, scored **0/11**, see below |
| `milvus-io/milvus` | 8 architecture pages in `milvus-io/milvus-docs`, current within a day | Go/C++ — **blocked on Go support**, see below |
| `kubernetes/kubernetes` | canonical component names map cleanly onto `cmd/` | large; doubles as a scale test |
| `odpi/egeria` (T3) | — | **negative result:** of 15 architecture hits in `odpi/egeria-docs`, most are under `saved/` (archived) or are dojo-tutorial SVGs. No current authoritative logical-architecture page. Our flagship target is the corpus's *weakest* ground-truth source — worth knowing before a poor T3 score is read as a detector failure. |

---

#### Learning from user feedback (design §5.5c)

Maintainer direction: continuously take user feedback to refine weights, scoring and algorithms,
possibly dynamically. Necessary — every §5.5b table is provisional. Sequenced deliberately:

1. **Capture feedback as labelled examples**, with author, date and repo — not as weight deltas. RE
   already has the surfaces (`curate.py`'s `resource_feedback`/`resource_curator_notes`, RFA, the
   activity log), so this is a new *question*, not new plumbing. Build this first; it is the half
   with no downside.
2. **Make weights explicit, versioned, and recorded with every result** — §6.2's `analyzerVersion`
   argument applies verbatim: a number that moves between runs is ambiguous unless you can say which
   weights produced it.
3. **Keep a frozen holdout, and never let the pre-registered fixtures into the training loop.**
   Rule 3 exists because a partition fitted to the code it is scored against measures nothing; a
   weight fitted to make `prometheus.md` read 11/11 makes that 11/11 meaningless.
4. **Only then consider dynamic adjustment.** You cannot safely auto-tune without a regression
   detector, and ours is the pre-registered corpus under strict containment — which works only while
   it stays outside the loop.

Failure mode to guard against explicitly: a system tuned on recent feedback gets better at *agreeing
with recent users* rather than at being right, and degrades invisibly because the same feedback that
moves the weights also shapes what anyone thinks to check.

---

### Egeria & governance

#### Step outcomes and the Egeria governance model — what landed 2026-08-21, and what was deferred

**Landed:** `resource_explorer/step_outcome.py` — the five-label vocabulary from
`docs/approach-portfolio-model.md` §3 (`recovered` / `partial` / `no_signal` / `unverified` /
`regression`), with §3's rule enforced in the constructor: an approach with no known-positive
check cannot report `no_signal`, only `unverified`. `repo_website_ingestion` is the first
adopter. Recording only — nothing routes on these labels.

**Established while investigating, all verified against the live server rather than read:**

- Guards already round-trip in RE today. `scripts/generate_repo_survey_definition.py` emits
  `### Guard / Any` on every `Link Next Process Step`; Dr.Egeria's command accepts `Guard` and
  `Mandatory Guard`; a live read of Analysis Survey returns `guard: 'Any'`, `mandatoryGuard:
  False` on all 9 links. The reader receives them and discards them.
- `NextGovernanceActionProcessStepProperties` carries exactly `guard: Optional[str]` and
  `mandatory_guard: Optional[bool]`. A flat token, no structured payload — which is *why*
  outcome and cause are separate fields, not a stylistic choice.
- RE consults no Egeria specification at all. `STEP_REGISTRY` is a specification living in
  Python. `SpecificationProperties` is the pyegeria client for the real thing.

**Deferred, with the reason:**

1. **Guard-based branching.** Deferred by decision 2026-08-21 — recorded outcomes are useful
   without routing, and branching is real work in `survey_definition_reader` (a documented v1
   boundary, see `docs/survey-definitions.md`). Authored links stay `guard: Any` until wanted.
2. **Whether a locally-produced guard can be recorded against the process at all**, given RE
   acts as its own engine host. Untested. If it turns out to be engine-action-only, then for
   RE-executed surveys this vocabulary is a *recording* mechanism and only a *routing* one
   under Egeria coordination — a real difference, worth knowing before building on it.
3. **Generating the Egeria specification from the enforced local contract.** Direction agreed
   (master in Egeria, cached locally), and the shape agreed with the arch-recovery session:
   keep `ResourceProvider.provides` / `requires_views` / `validate_resource_views()` as the
   *enforced* contract and generate the published spec from it, so the two cannot drift. One
   property to honour: generation must fail loudly if the enforced contract has no expressible
   form in the spec, rather than emitting a lossy one — otherwise the drift returns through the
   generator.
4. **`Produced Request Parameters` as the carrier if a cause ever needs to reach a *later*
   step** rather than only be recorded. Read in the docs, **not exercised** — do not build on
   it as verified.
5. ~~**Adopting the vocabulary in the other 23 steps.**~~ **PARTLY RESOLVED 2026-08-22 — the
   file-inventory readers are done.** `step_outcome.from_upstream_table()` is the shared
   three-way derivation for a step that reads a table an earlier step was meant to fill:
   empty table → `unverified`, rows present but nothing matched → `no_signal` (**the non-empty
   table is the known-positive**), otherwise `recovered`. It never returns `partial` — whether
   a non-zero result is *complete* is knowledge only the calling step has.

   Adopted in `repo_file_size`, `repo_data_profiling`, `repo_documentation`,
   `repo_sub_resource_survey`, `repo_file_classification`, `repo_file_structure` and
   `repo_security`. Three things fell out of doing it that were not visible beforehand:

   - **`SecurityHygieneSurveyor` was reading the wrong table entirely.** It looked for
     SECURITY.md / CI config / LICENSE in `project_code_symbols`, which by construction holds
     only `.py/.js/.java/.go` files — so the first two checks failed for *every repo, always*,
     and raised RFAs at confidence 90/85 telling people to add files they already had.
     Confirmed against live data before changing (docling: SECURITY.md + 13 workflow files in
     the inventory, zero of either in code symbols). `documentation.py` had already been moved
     to the inventory for this exact reason and left a comment saying why; this step was missed.
     Now reads the inventory, and emits **no** gap RFAs when the inventory is empty.
   - **`DocumentationSurveyor` was issuing a verdict on unread repos.** Half its score comes
     from the inventory, so an empty one produced "Documentation quality: Minimal" — and
     persisted `label="Minimal"` into the trend, which outlives the run. Now `Unverified` in
     both places.
   - **Three `StepInfo` comments named the wrong source table.** `repo_file_structure` and
     `repo_language` do not read the inventory at all (project_stats / project_code_symbols),
     and `repo_security` did not until this change. Corrected — the comments encode ordering
     prerequisites, so a wrong one is a wrong dependency.

   Two contracts were deliberately reversed and their tests rewritten rather than patched:
   `test_no_inventory_persists_nothing` (a run that found nothing now leaves a labelled zero —
   a gap in a trend is unreadable) and `test_no_signals_yields_minimal_quality`. Both carry a
   note saying what changed and why. New coverage: `tests/test_inventory_reader_outcomes.py`.

   **`repo_api_structure` followed on the same day.** It reads `project_code_symbols` rather
   than the inventory, but the shape is identical and the live case was the strongest of the
   set: measured across the registry, **13 of 20 repos had a populated file inventory and zero
   symbols** (docling 1,653 files/0 symbols, trellis 1,078/0). For all thirteen the step
   returned an empty annotation list — the one output indistinguishable from never having run.
   It now emits a labelled annotation and a zero metric, and distinguishes an empty table
   (`unverified`) from a scope that excluded every symbol (`no_signal`, via an unscoped
   `COUNT(*)`). `test_no_symbols_persists_nothing` reversed with a note, same as
   `test_no_inventory_persists_nothing`.

   **`repo_dependency` followed, and has the sharpest known-positive of the set.** It does not
   fall back on "the upstream table has rows": it checks the file inventory for a **dependency
   manifest**. A manifest present with zero extracted dependencies is demonstrably wrong
   (`unverified`); no manifest, with an inventory to prove it, is a real answer (`no_signal`);
   an empty inventory can prove neither, so it degrades to `unverified` — the first draft
   returned `no_signal` there, which was the same unearned confidence this vocabulary exists
   to prevent, one level up. Manifests match at any depth, or every monorepo reads as a
   provable zero.

   **Still open:** the remaining ~14 steps.

---

#### ~~Re-parent / persist ancestors to make depth control work~~ — BUILT, MEASURED, AND IT DOES NOT DELIVER THE COLLAPSE

**Live re-survey of milvus, 2026-08-24 (`repo_arch_detect`, 24.5s):**

```
before:  204 components, 0 structural, projection identical at every depth
after:   204 components, 2 structural, 1 of 206 rows has a resolved parent
         depth 0 -> 205    depth None -> 206
```

Structural nodes were built exactly as specified (separate row kind, no type, no
confidence) and they work for what they target — genuinely referenced ancestors now
resolve, 0 -> 1. **They do not produce the grouping this entry predicted, and the
prediction was wrong for a reason worth recording.**

`internal/distributed/{datanode,mixcoord,proxy,querynode,streamingnode,…}` carry
`parent_slug=''`. They reference **no parent at all**, so persisting referenced
ancestors can never synthesise `internal/distributed`. The earlier "would absorb 6"
figure in this entry was computed by string-splitting component slugs into
*hypothetical* parents and was then presented as what persisting referenced ancestors
would deliver. Those are different mechanisms. Path-prefix grouping is not the stored
parent hierarchy.

The cause is upstream and by design: `build_hierarchy` makes a directory a candidate
only if it holds **>=2 first-party files directly**. A pure container directory like
`internal/distributed` holds only subdirectories, so it is never a candidate, is never
linked to, and cannot be recovered from the reference graph.

**Path-prefix grouping was then measured as the alternative, and also does not solve it:**

```
milvus      by 1st path segment: 37 groups   by 2: 93 groups   (from 204)
genaicomps  by 1st path segment: 290 groups  by 2: 294 groups  (from 311)
```

Real reduction for milvus, useless for genaicomps — whose components are compose
service names, not paths, exactly as predicted.

**What this settles.** Depth/grouping over stored structure cannot make architecture
recovery interpretable, for either repo. The remaining lever is the one already
recorded elsewhere: distillation and the unported adjudicator (spike: Kubernetes
3303 -> 358 deterministically, then 358 -> 93 only with the LLM, which is where 6/6
held). Interpretability here is a precision problem, not a presentation one.

**Kept anyway, deliberately:** the structural-node code is correct, tested, invents no
evidence, and is what a denser hierarchy would need. It is not load-bearing for
anything today. `STAGE_PROJECTION_DEPTH` remains unwired and still meaningless.

**Original entry, which the measurement above corrects, follows.**

#### Re-parent components to the nearest SURVIVING ancestor — this is what makes depth control work

Measured 2026-08-24 while prototyping a depth control, and the reason that control
is withheld rather than built.

`arch_recovery/projection.py` works — given resolvable parents it collapses a nested
input (`tests/test_arch_projection_liveness.py`). It has never been given one:

```
milvus      depth 0/1/2/3/None -> 204 components every time
genaicomps  depth 0/1/2/3/None -> 311 components every time
```

**The gap is between generation and persistence, and each half is individually
correct.** `code_markers.build_hierarchy()` links every candidate subtree to *"the
nearest ancestor directory that is ALSO a candidate"* — right, and matches `ir.py`'s
documented contract. But persistence writes a **filtered subset** of candidates: 16
of milvus's 213 persisted slugs are `code::` namespaced. Parent links still point at
the pre-filter candidate set, so milvus references 6 parents of which **0 are
persisted**. Every node reads as root-attached and `project_rows` becomes an identity
function.

**Two ways to close it:**

1. **Re-parent at persist time** — walk up to the nearest ancestor that actually
   survives into the persisted set, and rewrite `parent_slug` to that. Keeps the
   persisted set as-is. Cheaper, and preserves whatever filtering exists for good
   reasons.
2. **Persist the referenced ancestors** — emit the intermediate candidates so the
   links resolve. Truer to "store the hierarchy, project a level"
   (`approach-portfolio-model.md` §2a), but grows the stored set.

**Investigated 2026-08-24 — and the answer reverses that. (1) recovers nothing; (2) is
the only option that works.**

First, the candidates are not *filtered*. `code_markers` emits a Component per subtree
in `by_subtree` — subtrees with **marker-rule hits** — while `parent_slug` is read from
`hierarchy`, which holds **every** candidate subtree (any dir with >=2 first-party
files). Different sets, and nothing reconciles them. An intermediate directory like
`internal/distributed` has no markers *of its own* — its children do — so it never
becomes a Component while its children point at it. Nobody dropped it; it was never a
candidate for emission in the first place.

That makes the persisted set a **flat frontier with no internal nodes**, which is fatal
for (1). Measured on milvus's 16 persisted `code::` components:

```
ancestor/descendant pairs WITHIN the persisted set: 0
```

Not "few" — **zero**. No persisted component is an ancestor of any other, so
re-parenting to the nearest surviving ancestor rewrites every link to "" and collapses
nothing. Projection needs internal nodes and (1) cannot create them.

(2) does, and the shape it produces is the interesting part:

```
code::internal::distributed        would absorb 6 components
code::internal                     would absorb 2
code::internal::querycoordv2       would absorb 2
```

`internal/distributed` absorbing 6 is precisely the milvus ground-truth grouping —
`datanode`, `mixcoord`, `proxy`, `querynode`, `streamingnode` are 5 of the 8 published
components, currently emitted as 5 unrelated siblings with no parent. So persisting
intermediate candidates is not just what makes projection function; it is what makes
the coarse level correspond to the answer a human already published.

**Cost and caution:** these ancestors have no marker evidence of their own, so they must
be persisted as structural nodes, not as typed/scored components — with an honest
confidence and type, or none. Emitting them as ordinary components would invent
evidence, which is the failure mode the whole `no metric, no number` rule exists to
prevent (design §5). Structural-node-only is the constraint to design against.

**Why this is worth doing before any Purpose→depth work:** depth-as-presentation is
the cheap version of everything in the entry above — one run, re-rendered at several
levels, no re-survey. It is currently untestable because there is no hierarchy to
project. Until this lands, "sufficiency is a presentation rule" cannot even be
evaluated, and the only alternative left standing is the expensive one (depth as a
generation-time stopping rule).

**Related and unwired:** `STAGE_PROJECTION_DEPTH` in the same module declares the
level each stage wants (`discovery` 0, `assessment` 1, `analysis` unprojected) and is
read by nothing. It becomes meaningful the moment projection has real input.

---

#### Purpose sets required DEPTH, not just which analyses run — unwritten, and it reframes precision

Raised by Dan 2026-08-24, and not in any design doc. Both `investigation-framing-design.md`
and `architecture-recovery-design.md` were checked: nothing ties depth or completeness to
purpose. §3 of the framing design says the opposite for the neighbouring axis — *"changing
perspective changes how much you see but never what gets run."*

**The claim:** an investigation exists to meet its own objectives. Architecture recovery is
one analysis among many and is *often not relevant at all*. Where it is relevant, **how much
recovery, and to what completeness, is itself a function of the purpose.** The same is true
of every other analysis with a depth dial — documentation, dependencies, security, profiling.

**Why this matters more than it first sounds.** The current framing splits the problem as:
framing decides *which surveys run* and *what a result means to this engagement*, but does
nothing about *how many candidates a surveyor emits* — that being a separate precision
problem. **That split is wrong, or at least too absolute.** If purpose sets the required
depth, then purpose is a *stopping criterion*, and a stopping criterion changes the output
size. Concretely: 154 components against a ground truth of 8 (Milvus, finding 99) is a
useless answer for `Select` — "is there an architecture here, roughly what shape" — while
possibly a fine one for `Learn` or `Explore`. The number is not wrong in the abstract; it is
wrong *for a purpose nobody declared*.

**What already exists to build on:**

* **Completeness is already expressible.** Egeria's base annotation type carries
  `sampleSize` / `samplePercent` / `samplingMethod` — *"how much did we look at"*
  (`architecture-recovery-design.md` §6.1, which says to reuse them and populate them
  honestly when a component is only partially analysed). The vocabulary for *reporting*
  depth exists; nothing *decides* the depth required.
* **The one measured selection mechanism is a gate, not a weighting.**
  `expectations.recovery_gate` discriminates across all 60 repos (46 run / 8 skip / 6 none)
  by keying on evidence containment rather than on a label — the property Perspective was
  measured to lack. But it is **binary**: run or skip. The natural extension of this entry is
  a graduated gate — run *to what depth* — rather than a second taxonomy.

**Open questions, none answered yet:**

1. What is the depth dial per analysis? For arch recovery it is plausibly a component-count
   or granularity target; for others it may be sample percentage, or which sub-checks run.
2. Does depth-by-purpose belong in the analysis catalog (declared per analysis), on the
   investigation (declared once), or negotiated at dispatch?
3. Is "sufficient for this purpose" a *stopping* rule during the run, or a *presentation*
   rule over a full run? Cheaper is stopping; more reusable is presenting.

**Do not conflate this with ranking.** Purpose ranking questions/analyses (§3) and Purpose
gating RFA emission (§4) are both established. This is a third role — setting the depth
contract for a run — and it is the one that touches surveyor output size.

---

#### Build the Investigation tab — nothing tracks this, and the design assumes it

**The goal, in the design's own words** (`docs/investigation-framing-design.md` §Context, §1):

> RE today has no concept of *the piece of work you are currently doing*. You land on a
> resource and start surveying it. The eight intents describe **what kind of work is happening
> to one resource**; Perspectives describe **whose concerns filter what is shown**. Nothing
> captures **why this set of work exists at all** — and because nothing does, RE cannot decide
> what to show first, what to run by default, or whether a finding is merely evidence or
> actually somebody's problem.

An **Investigation** is one body of work — "the thing the new tab creates and the context
everything else runs inside". It is a framing step *ahead of* Scouting: declare the body of
work, its purposes and its membership, and everything downstream (which resources are visible,
which analyses are proposed, whether a failed check raises an RFA) derives from that
declaration.

**Why this entry exists:** the design was written, measured and committed (`958ac74`), and the
tab it assumes was never given a work item. The framing entry below lists eight deferred
pieces; building the tab is not among them, so the central deliverable is the one thing
nothing tracks. Confirmed 2026-08-24: zero occurrences of `Investigation` in
`web/static/index.html`, no local investigation table, no routes.

**What already exists** — and is search/bind only, by explicit decision:
`entity_egeria_project_context` (registry) + `web/routes/project_context.py`
(`/search/candidates`, GET/POST per entity), from Part 5 of
`docs/discovery-automate-project-context-plan.md`. `surveyors/egeria_project_finder.py` wraps
`ProjectManager.find_projects`.

**What is missing, in dependency order:**

1. **The local investigation table** — one row per investigation with a *nullable*
   `egeria_project_guid`. §1 calls this the single most important structural decision: it makes
   promotion to Egeria a fill-in rather than a migration. Shape the membership table like the
   target `ResourceList` relationships from day one for the same reason.
2. **The create-a-new-Egeria-Project path** — net-new, and the blocker for deferred item 1
   below (promote a local investigation). Part 5 explicitly did not build it.
3. **The tab itself** — create/select an investigation, declare Purpose(s), manage membership.
   Note Purpose **ranks, never excludes** (measured; see the framing entry), so this is
   ordering, not filtering.

**Sequencing:** 1 is standalone and unblocks everything. 3 is only worth building once 1
exists, since the tab with no table is a form with nowhere to write. 2 can lag — a local
investigation is useful before it is promotable.

**Two constraints that are easy to specify wrongly:**

* **Perspective cannot drive dispatch** (§3, measured 2026-08-24). Two incompatible
  vocabularies — 12 Title-Case names on questions, 5 snake_case on analyses — and zero
  discrimination: no perspective reaches an analysis another does not also reach. It is a
  secondary ranking axis only. A tab offering "filter analyses by Perspective" would specify
  something the catalog cannot support.
* **Purpose tagging is NOT a blocker — it is done.** `341d2f5` tagged all 41 questions;
  verified 2026-08-24 in the CSV source of truth (`docs/dr-egeria/resource_questions.csv`,
  41/41 `Purposes` filled), not just the generated YAML. The check-granularity join is built
  and guarded too (`852955f`). What remains is populating checks per question — see the
  framing entry below.

§8 of the design already lists **`Investigation record + tab`** as net-new work, alongside
"Create a new Egeria Project — net-new (Part 5 built search/bind only)". The intent was
tracked in the design; only the backlog entry was missing.

**Do not start here:** §7's two renames (`Project` → `Repo`/`Resource`,
`ProjectGroup` → `Owner`) are a separate entry with a live cross-schema tripwire — Egeria
Advisor reads RE's tables by hardcoded string in six places. Adding an Investigation concept
while `Project` still means three things is what makes the rename harder later, but it does
not block this work.

---

#### Investigation framing — the six items deferred out of the 2026-08-24 design

Full design: `docs/investigation-framing-design.md` (design only, nothing built). These are the
pieces that design deliberately left out of its own first pass.

1. **Promote a local investigation to an Egeria Project.** Create the `Project` (+ `ProjectCharter`),
   then replay each local membership row as a `ResourceList` relationship carrying its `resourceUse`.
   Design the local membership table shaped like the target relationships from day one so this stays
   a replay rather than a migration. Requires the "create a new Egeria Project" path, which Part 5
   of `docs/discovery-automate-project-context-plan.md` explicitly did not build (search/bind only).

2. **Unbind / rebind an investigation from its Egeria Project.** Falls out of the nullable
   `egeria_project_guid` model but has no answer yet for what happens to relationships already
   published under the old binding.

3. **Perspective: two vocabularies that cannot be joined, and zero dispatch discrimination.**
   Questions carry the 12 Title-Case Glossary names; analyses carry 5 snake_case values (`all`,
   `security`, `steward`, `data_scientist`, `dba`). `data_scientist`/`dba` don't exist in the question
   vocabulary; `Architecture` and `Admin` (25 questions each) have no analysis counterpart. Worse,
   measured 2026-08-24: **not one of the twelve perspectives reaches a single analysis another
   perspective doesn't also reach** — the sets are strictly nested, and `Privacy` reaches none at all.
   Perspective filters *how much* you see, never *what runs*. Fine for its actual job (display
   filtering, which is what the tags were assigned for); unusable for dispatch. See
   `docs/investigation-framing-design.md` §3, which was rewritten around this.

4. **Upstream: a `CertificationType` → checklist relationship.** Egeria has no way to say what checks
   a certification is composed of. `OpenMetadataTypesArchive5_3.java:736-772` set the precedent with
   `DataStructureDefinition` (`CertificationType` → `DataStructure`, *"the specification used to
   certify data"*); the scorecard analogue would point at `GovernanceRule`/`Requirement` definitions.
   Purely additive, changes no existing semantics — which is why it stands a chance upstream, unlike
   adding a verdict field to the `Certification` relationship (considered and rejected; see the
   design doc §4). Not a blocker: nothing in the failure path needs it.

5. **Two undeclared scores.** `documentation.py:151-167` (`score = len(present) + len(found)`, then
   hardcoded thresholds to a quality label) and `health.py:118-159` ("Overall health score: X/100")
   both emit numbers RE authored, with no `GovernanceMetric` behind them. Under the rule agreed
   2026-08-24 — *no metric, no number* — each needs either a declared `GovernanceMetric` with
   `measurement`/`target` (following the Portal's Governance Metrics pattern) or removal.
   `sql_analyzer.py:145-153`'s `complexity_score` needs the same check.

6. **~~Tag Purpose, and add the check-granularity join~~ — BOTH DONE; entry was stale.**
   `341d2f5` tagged all 41 questions with Purpose (not the ~10-question pilot this entry
   proposed — the pilot was skipped and the full set measured directly). `852955f` built the
   check-granularity join: `configdata/check_registry.yaml` declares the per-check vocabulary
   for 8 analyses, `question_catalog_reader.py` validates against it, and
   `tests/test_check_registry.py` guards it (10 tests). The join's own trap is documented in
   that file's header — three analyses write findings under a different `kind` than their
   catalog id (`security_scan`→`security_hygiene`, `documentation_coverage`→`documentation`,
   `sub_resource_survey`→`repo_sub_resource_survey`).

   **What the measurement settled, and still holds:** Purpose fails the exclusivity bar (0/8)
   exactly as Perspective did — but that bar is unachievable by construction and encodes a false
   premise, since purposes genuinely overlap. On the fair metric Purpose is the better axis:
   mean pairwise overlap 0.22 vs Perspective's 0.37, nested pairs 6 vs 18. Purpose **ranks**,
   never excludes.

   **What is actually open — the vocabulary is declared, the data is not populated.** Measured
   2026-08-24: of the questions whose `answering.kind` is `analysis`, only **one of five**
   carries an explicit check (`license_classification:license_risk_tier`); the rest have
   `checks: []` and still join at analysis granularity. `repo_conventions` bundling five checks
   (`ingestion/repo_conventions_parser.py:97-179`) is the case the join was built for and is
   not yet expressed. Populating it is data entry against a guarded schema, not new mechanism.

   Note the earlier "16 analysis-answerable questions" figure in this entry no longer matches
   the file: today's `answering.kind` vocabulary is `analysis` 5, `mixed` 6, `direct` 11,
   `gap` 8, `human` 7, `chart` 1, `unknown` 3. The vocabulary changed after that measurement;
   the ratio it reported was not re-derived. Re-measure before quoting it.

   Generation path unchanged: `question_catalog.yaml` is generated from
   `docs/dr-egeria/resource_questions.csv` via `scripts/csv_to_question_catalog_yaml.py` —
   don't hand-edit the YAML.

7. **`ResearchQuestion` (0430) for per-investigation open questions.** Complementary to the existing
   `GlossaryTerm` + `Question` catalog, not a replacement — no migration. Gives an investigation
   somewhere to record the questions it exists to answer, scoped via `GovernanceDefinitionScope` to
   the Project. Unmatched ones are the observed growth path for the standing catalog.

8. **Move `scheduler.py` subscriptions onto `watchResource`.** `ResourceList` (0019) already carries
   `watchResource` — *"whether the parent entity should receive notification about changes to the
   supporting resource"* — which is exactly what `notification_subscriptions` is doing locally. Once
   investigations are Egeria-bound, the subscription flag belongs on the relationship. Related to
   Automate's local-first decision and `docs/automate-notification-manager-pyegeria-spec.md`.

---

#### Egeria ↔ RE sync/divergence reconciliation — DETECTION BUILT 2026-08-20, resolution partly open

**Built:** `resource_explorer/egeria_linkage.py` detects "that GUID does not exist here"
at the point of use and, instead of the opaque `SERVER_ERROR_500` that reached the UI
verbatim, records the divergence in the new `egeria_linkage_status` table, raises an RFA,
and throws a named error that says what happened and what the three choices are.

**Corrected 2026-08-20 by testing against live Egeria with a deliberately bad GUID** — the
first version guarded five paths on the assumption all five consume a cached GUID. Only
three do:

| path | cached GUID | by-name fallback | guarded |
|---|---|---|---|
| repo publish | yes | **none** — a stale GUID is fatal | yes |
| filesystem `publish_step_annotations` | yes (`guid or _find_element_guid(...)`) | yes | yes |
| database `catalog_and_survey` | yes (as the *server* element) | yes | yes |
| filesystem `catalog_and_survey` | no | yes | no |
| database `publish_step_annotations` | no | yes | no |

The two unguarded ones resolve their element by name every time, so a stale cached GUID
cannot break them — and a guard there could only misattribute an unrelated lookup failure
to a GUID that was never used. Tests assert the placement in *both* directions, plus that
the classification still matches what the code does, so the table above cannot quietly rot.

**The real defect that live testing exposed:** in database `catalog_and_survey`, the stale
GUID does produce exactly the error the detector recognises — at
`_initiate_survey("PostgreSQL Server", server_guid)` — but the surrounding
`except Exception: log.warning(...non-fatal...)` swallowed it, and the method returned
success with `server_survey_guid=''`. The wrapping guard never saw it because the exception
never escaped. Since the cataloging work genuinely does succeed there, this stays non-fatal,
but it now records the divergence and raises the RFA: "non-fatal" must not mean "invisible",
or every later run skips the server survey the same silent way.

The detector was validated against this deployment's live Egeria rather than against a
paraphrase — asking for a GUID that cannot exist returns `OMAG-REPOSITORY-HANDLER-404-007`
wrapping `OMRS-REPOSITORY-404-002`, and that verbatim message is now a test fixture. Two
things that probe corrected: the outer code is `OMAG-REPOSITORY-HANDLER-404-007`, not the
`OMRS-REPOSITORY-404-007` recorded here from the original report; and the response labels
itself `CLIENT_ERROR_400` while `relatedHTTPCode` is 404, which is why detection keys on
Egeria's message codes and not on HTTP status.

**Held to "detect, don't auto-resolve" as decided:** the cached GUID is deliberately *not*
cleared on detection. It is kept so a human can see what RE had and so republish can report
what it is replacing.

`GET /api/egeria/linkage/stale` lists divergences; `POST /api/egeria/linkage/{type}/{slug}/resolve`
takes `republish` | `resurvey` | `discard`. All three clear the unusable GUID and the
divergence record — that is what unblocks the resource, and is common to every choice.

**Still open:**
- **republish/resurvey run the follow-up work for repos only.** For databases and
  filesystems the link is cleared and the caller is told which existing action to run.
  Re-publishing those from cached local data needs per-type orchestration — a database
  publish reconstructs `schema_info` and fires Egeria's native survey — which is the real
  reason it is not built here.

  **Correction (2026-08-20):** the commit that added this said there was "no registered
  database or filesystem in this deployment". That was wrong and was never checked — only
  filesystems were. There are two registered databases, `localhost_docker_coco_ods` and
  `localhost_docker_coco_pharma`; filesystems are genuinely zero. Neither database carries
  an `egeria_asset_guid`, so neither can exhibit this divergence today — a stale link needs
  a cached GUID first. So the path is testable in principle, but only after cataloging one
  of them in Egeria, which is a real write to the live catalog and a deliberate choice
  rather than a side effect of verification.
- **`discard` clears the Egeria linkage; it does not purge RE's local survey data**, which
  is the stronger reading in the original note above. Deleting a user's survey history is
  hard to reverse and should not happen behind a single API call — it needs its own
  confirmation path before being built.
- **Detection is reactive only** (open question 1). A proactive GUID-existence sweep would
  have to decide how often to re-check every cataloged entity; the failure is rare and now
  loud, so this was not worth paying for yet.
- **Open question 3, partly answered 2026-08-20.** The by-name fallback works: with
  `coco_ods` cataloged, `_find_element_guid("coco_ods")` returns the same GUID as the cache
  (`c2e8bb6c-…`), so a registry that has lost its GUID can recover it. Two of the five paths
  above rely on that route exclusively and are therefore immune to the forward case. Still
  unverified end to end against a genuinely reset RE database.
- ~~**No UI for resolve.**~~ **BUILT 2026-08-20.** Admin ▸ 🔗 Egeria Links lists every
  divergence with Republish / Re-survey / Discard, and an affected repo shows the same three
  actions as a banner on its Scouting card — placed directly above the "☁ Published to
  Egeria" badge, which is actively misleading while the link is broken since it reports a
  catalog entry RE can no longer reach. Both call one shared button-builder so the wording of
  a destructive-sounding choice cannot differ between them.

  Found while verifying: `discard` reported "RE's local survey results are untouched" while
  also deleting `project_egeria_surveys` — the record of past publishes. Those GUIDs point
  into the repository that no longer has the asset, and the publish history itself remains in
  the activity log, so nothing of value was preserved by keeping them; but the sentence was
  not true, and the one action a user might fear is the wrong place to be imprecise. It now
  names the count it removes and what survives.

---

#### RFAs should become real Egeria actions, not just descriptive annotations — needs a deeper dive

Every `RequestForActionAnnotation` RE produces today (repo security/doc gaps, the new filesystem inaccessible/unclassified/profiling-failure RFAs added 2026-07-13 — see the filesystem analytics item below) is purely descriptive: it's an `Annotation` attached to a `SurveyReport`, published via `EgeriaPublisher`'s `RequestForActionProperties` mapping (`egeria_publisher.py`). Nobody is notified, nothing is assigned, there's no due date or lifecycle status. A human has to know to go look at the survey report to ever see it.

**Confirmed so far (2026-07-13, quick pass through pyegeria, not yet a full design):** Egeria has a separate, genuinely actionable mechanism — a `ToDo`/"person action" element, distinct from a survey Annotation. `pyegeria/omvs/my_profile.py::create_my_todo`/`_async_create_my_todo`, backed by the general-purpose `pyegeria/omvs/asset_maker.py::_async_create_action` (`ActionRequestBody`), supports: `assignToActorGUID` (assign to any actor, not just the calling user — the `my_profile.py` wrapper is just a "my" convenience, the underlying call is not actor-scoped), `actionSponsorGUID`, `originatorGUID`, `newActionTargets` (linking the action to specific elements — e.g. the actual offending file/table, not just prose), and a full lifecycle (`activityStatus`: REQUESTED/APPROVED/WAITING/IN_PROGRESS/COMPLETED/FAILED/CANCELLED/etc. — see `pyegeria/core/_globals.py::ACTIVITY_STATUS`, `dueTime`, `priority`, `lastReviewTime`). The docstring itself notes a `ToDo` is one of several "person action" kinds — "Meeting, ToDo, Notification, Review" — so there's a whole small taxonomy here, not just one element type.

Also spotted, not yet chased down: a distinct `steward`/`stewardTypeName`/`stewardPropertyName` property pattern that shows up on collection-membership and classification relationships (`pyegeria/omvs/collection_manager.py`, `classification_explorer.py`) — "who validated this" rather than "who needs to act on this." These look related but are probably not the same concept as ToDo assignment, and it's not yet clear how (or whether) they're meant to compose — e.g. does a steward get auto-assigned the ToDo for things in their stewardship scope?

**Deliberately not designed yet — this needs its own research pass, not a bolt-on:** two unexplored pyegeria OMVS modules that are very likely load-bearing for this — `actor_manager.py` (actor/role model — who can be assigned, how roles relate to stewardship) and `community_matters_omvs.py` (ties into the existing, also-unresolved "journaling discoveries as blog-style entries visible to particular communities" open question in the A2A item below — notification/audience may be a community concept, not just a 1:1 assignment). Also needs: which RFAs should actually become assignable `ToDo`s vs. staying descriptive-only (probably not every annotation warrants interrupting a human), who the default assignee/sponsor is when RE has no obvious human to name (survey run by an unattended schedule vs. a logged-in user), and whether this should be built as a generic `EgeriaPublisher`/executor-level capability (any `RequestForActionAnnotation` optionally promotable to a `ToDo`) rather than something each resource type's publish path reimplements.

Related/overlapping open items: the A2A item's "Rendezvous for results" open point (notification mechanism, journaling, comments as candidates alongside the activity log) and the "unify survey launching" item's unified-dashboard goal — a real ToDo/action queue could end up being part of that unified view rather than a separate concept.

---

#### Egeria ↔ Resource Explorer A2A collaboration (bidirectional)

RE currently only calls *into* Egeria (triggering native surveys via `AutomatedCuration`/`initiate_postgres_*_survey`, publishing annotations via `EgeriaPublisher`). There is no path for Egeria's own automation (governance action processes, engine actions) to call *into* RE — e.g. to dispatch one of RE's Python surveyors as part of an Egeria-orchestrated workflow.

Direction agreed: RE should expose itself as an **A2A-callable surface** (extending the existing `agentstack_server.py` per-agent pattern) that Egeria can invoke as if it were any other governance/survey action service. Two reasons A2A over a bespoke REST contract: (1) A2A's task-state model (`input_required`, streaming, polling) already matches the async-survey-result problem RE works around manually today in `HybridDatabaseSurveyor`; (2) it's protocol RE already speaks, so other orchestrators (not just Egeria) get the same capability for free.

**Deferred pending:** input from Mandy (owner of Egeria's core Java / connector frameworks) on what the Egeria-side connector shape should be — likely does not require a new OCF connector *type*, but the specifics should follow her judgment on precedent in the existing wide range of Egeria connectors.

**Known open design points once picked up:**
- New per-capability A2A agent (own port, per the one-agent-per-`Server` rule) using structured `DataPart` payloads (asset GUID, resource type, surveyor/analysis name, options) rather than the natural-language `TextPart` pattern the existing chat agents use.
- Auth: `agentstack_server.py` currently has no caller authentication — fine for an internal chat agent, not sufficient for a surface Egeria automation is meant to trust. **Resolved:** use Egeria's existing bearer-token approach and security services directly; no separate RE auth namespace/scheme needed.
- Rendezvous for results: the existing `activity_log`/RFA schema (see `docs/survey-activity-design.md` D3, D8) is RE's own operational record, but it's not the only channel results should flow through — Egeria's notification mechanism, journaling discoveries as blog-style entries visible to particular communities, comments, and formal reports are all candidates depending on audience, and these aren't mutually exclusive with the activity log.

Full context: `docs/egeria-collaboration-and-survey-model.md`, section 2.

---

#### Survey/Analysis model conformance to Egeria Area 6

RE's survey model (fixed pipeline of sub-surveyors, one `SurveyResult` per run) doesn't yet reflect Egeria's actual Area 6 mechanics — composable `AnalysisStep` phases within a survey, embeddable survey-pipeline connectors, declarative annotation-type catalogs, standard completion guards, and (critically) no existing built-in notion of different survey "kinds" (shallow sweep vs. deep focused, persona-tailored presentation). RE will likely need to grow more variety of survey/analysis "kinds" faster than Egeria's own connector catalog does — that's fine as long as Egeria stays the system of record — but RE's internal model should still speak Egeria's vocabulary where a precedent exists.

Full context, grounded in the actual Egeria Java source: `docs/egeria-collaboration-and-survey-model.md`, section 3.

---

#### Coherent selective-cataloging model

No coherent model today for *what* to catalog and how to catalog things in groups (e.g. repo file-type checkboxes exist, but nothing like "file type AND touched in the last N months"; no selectivity at all for database or filesystem surveys). Need a general flow: Discover → Survey (broad) → Analyze/Question/Select → Survey (deep, often on the selected subset) → Catalog (side effect of deep survey or an explicit action) — with surveys triggerable by a human, on a schedule, or by Egeria automation.

Egeria has no direct precedent for "survey broadly across not-yet-cataloged resources, then selectively catalog a subset" — current Area 6 surveys always run against an asset that's already cataloged. This is genuinely new territory for RE to define, composed from existing Egeria primitives (`RequestForAction` annotations + completion guards + `GovernanceActionProcess` chaining), and possibly worth proposing back into Egeria core once proven.

Full context: `docs/egeria-collaboration-and-survey-model.md`, section 4.

---

#### Dr.Egeria as the authoring format for Survey Definitions

Direction agreed and now grounded: Dr.Egeria (RE's markdown DSL, already used via MCP and in Egeria Advisor) is the authoring format for Survey Definitions — not as a runtime trigger mechanism (MCP/Dr.Egeria command round-trips are likely too inefficient for that; A2A stays the trigger path, see the item above), but as a design-time spec format, authored in Egeria Advisor's existing plan editor. **Grounded finding: no new Dr.Egeria commands needed.** Egeria has no dedicated "SurveyActionType" open-metadata type — the closest real, catalogable element is `GovernanceActionType`, and Dr.Egeria's existing "Action Author" family already covers authoring a Survey Definition's composition end to end: each step is a `Create Governance Action Process Step` (not the more generic `Create Governance Action Type`, which is for standalone action templates never chained into a process), the survey as a whole is a `Create Governance Action Process`, and `Link First/Next Process Step` sequences them. RE-specific info (execution location, target technology type, which RE sub-surveyor a step maps to) is proposed to live in the `Additional Properties` dictionary attribute that already exists on every element in this chain — a documented key convention (`executes_at`, `supported_technology_type`, `re_analysis_step`), not a schema change.

**Conditional execution, partially resolved:** `Link Next Process Step`'s existing `Guard`/`Mandatory Guard` attributes already give real step-to-step branching (a step produces a guard, different `Link Next Process Step` commands route to different next steps based on it) — no new syntax needed for that. Still open: whether conditional logic is ever needed *within* one step's own parameters (not just branching between steps) — needs a requirements pass with concrete example Survey Definitions to answer.

`executes_at` is deliberately an open, extensible value (not a two-value enum) — `egeria` and `resource-explorer` are the first two, but other execution engines (Airflow, most obviously) should be nameable here too without a schema change, since it's a free-text dictionary value.

**RE's read/execute side is now implemented** (see the "RE locally executing Survey Definitions" item above) — the reader/executor have been exercised structurally (graph parsing, branching/cycle rejection, dispatch logic all unit-tested against canned fixtures), though authoring a real Survey Definition via Dr.Egeria and running it against a live server hasn't been validated yet.

**Not yet solved:** an `executes_at: resource-explorer` tag on a step is just catalogable metadata — nothing makes Egeria's engine host dispatch to RE *without RE itself initiating the run*. That specific case depends on the A2A item landing first. RE executing its own steps on its own initiative does not have this dependency — see the "RE locally executing Survey Definitions" item above, now implemented.

Full context: `docs/egeria-collaboration-and-survey-model.md`, section 6, and open questions A6–A9, A12.

---

### Analysis & surveyors

#### DONE 2026-08-31 — Survey Results dashboards covered only 14 of 29 analyses; now covers all 25 findings-producing ones

*(Opened 2026-08-31, from a results audit against `docs/dr-egeria/resource_questions.csv` — see
the companion entry below on stage/intent mismatches, found in the same pass.)*

`SURVEY_RESULT_DASHBOARDS` (`repo_survey_definition_adapter.py`) is 6 hand-authored dashboards,
unchanged since `docs/survey-results-dashboard-plan.md` introduced it — which says so itself:
*"Framework is the point of this pass — six real dashboards prove it end-to-end; more are a
one-entry addition afterward, not a new mechanism."* That follow-through never happened. The
catalog it was written against had 15 analyses; it now has 29, and the dashboard count never
moved.

**Measured:** 15 of 29 analyses have no dashboard. 4 are legitimate non-candidates — actions
without findings, not surveys (`egeria_publish`, `rag_ingestion`, `website_ingestion`,
`repo_profile_refresh`). **11 are real, findings-producing analyses with nowhere to show up in
any Results tab:**

- Assessment: `chaoss_metrics`, `cii_badge`, `community_support`, `cve_scan`, `foss_scorecard`
- Discovery/Analysis: `architecture_doc_lens`, `architecture_recovery`, `architecture_summary`,
  `interface_surface`, `repo_classification`, `manifest_parse`

Confirmed this is *not* a stage-tagging bug: `get_dashboard_stages()` correctly derives a
dashboard's stage(s) from `analysis_catalog.yaml`'s `intent` field (matching what the Survey tab
routes by), not from the questions CSV — so Survey and Results already agree with each other on
placement. The gap is purely dashboard **membership**: these 11 ids were never added to a
dashboard, one-entry-at-a-time, the way the plan doc said they would be.

This is very likely the concrete shape of "the Results tab doesn't show results from all the
surveys" (live-reported 2026-08-31) — the mental model of "card = summary, Results tab =
in-depth" is the intended design, just an unfinished rollout rather than a different design.

**Status: 3 of the 11 closed 2026-08-31**, folded into one new dashboard. Added `architecture_overview`
(`architecture_recovery` + `architecture_summary` + `architecture_doc_lens`) as a
`render="grouped_cards"` dashboard — no new frontend code, same pattern
`documentation_conventions` already proved out. Confirmed the pattern generalizes cleanly, but it
also exposed a real, separate bug in `_results_have_data` (`web/routes/projects.py`): a never-run
result shaped `{"state": "never_run", "message": "..."}` (not wrapped in `_status`) read as "has
data" because the explanatory `message` string is non-empty, and `architecture_recovery`'s own
decorative `documentation` field (documentation-SITE ingestion status, unrelated to its own
findings) did the same. Both fixed and pinned with regression tests
(`test_security_features_visibility.py`) — latent since result_status.py's vocabulary was
adopted, just never triggered because none of the three analyses had reached a dashboard's
`has_results` check before.

**Remaining 8 closed 2026-08-31.** Folded rather than each given its own card, per the plan doc's
own precedent that a dashboard can be a single item (`dependencies` already was one):

- `cve_scan`, `foss_scorecard`, `cii_badge` → into `security_overview` (same "is this
  trustworthy" question, asked from outside the repo instead of inside it)
- `community_support`, `chaoss_metrics` → into `health_maturity` (community/activity signal,
  same topic `repository_health` already reports a cruder version of)
- `interface_surface` → into `code_structure` (same "what does this expose" surface
  `api_structure` already reports, from declared dependencies rather than parsed source)
- `repo_classification`, `manifest_parse` → each a new single-item dashboard — neither fit an
  existing theme (classification is its own question; `manifest_parse` is a refresh operation,
  not a topic), so forcing them into one would have been worse than a dashboard of one.

**Closed 2026-08-31:** `security_overview`'s custom scorecard renderer now has dedicated tiles for
the three new ids. Sourced from a new `headline` field added to the Tier-2 `/survey-results`
payload alongside `results` (each analysis's existing `headline_reader` — the same one the Tier-1
stat tiles already use — rather than re-deriving a summary from raw findings in JS, which would
have duplicated that logic and let the two summaries drift). `headline_reader`'s tone vocabulary
(`good`/`bad`/`neutral`/…) differs from the tile helper's (`ok`/`warn`/`gap`/…) — mapped, not
unified, since both exist independently elsewhere in this codebase already.

Locked in with a new ratchet test (`test_every_findings_producing_analysis_has_a_dashboard`,
`test_survey_results_routes.py`) — a future analysis added to the catalog with no dashboard now
fails loudly instead of sitting invisible until the next hand audit.

#### MEDIUM — 27 stage/intent mismatches between the questions CSV and the analysis catalog; one question is unreachable

*(Opened 2026-08-31, from the same results audit.)*

`docs/dr-egeria/resource_questions.csv`'s "Funnel Stage" column and `analysis_catalog.yaml`'s
`intent` field are two different axes **by deliberate design** — stage is "when a user would
naturally ask this," intent is "which cost tier the analysis belongs to" (CLAUDE.md rule 17).
Measured cross-check (`question_catalog_reader.get_questions()` against
`analysis_catalog_reader.get_analyses()`, no dangling references found — that invariant holds):

**27 of ~49 questions are filed under one stage while the analysis answering them carries a
different `intent`.** Concentrated (20 of 27) in "Analysis"-stage questions answered by
Discovery- or Assessment-tagged analyses — e.g. "Is there a current, published, security
analysis?" is filed under Analysis but answered by `security_scan`/`cve_scan`/`foss_scorecard`/
`cii_badge`/`security_features`, all `intent: assessment`. The split is intentional and the
Results dashboards correctly key off `intent`, not stage (see `get_dashboard_stages()`'s own
docstring) — but nothing in the UI tells a user standing in one stage's Questions tab that the
evidence for a question actually lives under a different stage's Survey/Results tabs. Worth a UI
affordance (a link from a Questions-tab answer to the stage that actually holds its evidence)
more than a re-tagging pass — re-tagging would fight the Discovery-tier cost-tier logic rule 17
already argues for.

**One question is orphaned entirely:** a CSV row tagged stage=`Automate` ("How much has changed
since the last time this was surveyed — is it worth re-running now?"), but `automate` is not in
`index.html`'s `_QUESTION_PHASES` list and Automate's own subnav never offers a Questions tab —
so this authored question has no reachable home in the UI today.

#### `DependencyParser` covers 4 ecosystems; `_MANIFESTS` claims 12

Found 2026-08-23 while checking whether the repos reporting zero dependencies genuinely had
none. Nine of thirteen did. **Four did not**, and they cluster by build system:

| repo | manifest present | parser support |
|---|---|---|
| `egeria_git` (6,016 files) | `build.gradle` | none |
| `docling_java` | `build.gradle.kts` | none |
| `ol_diff` | `build.gradle` | none |
| `unitycatalog_rs` | `Cargo.toml` | none |

`DependencyParser.parse()` globs for exactly `pyproject.toml`, `requirements*.txt`,
`setup.py`, `package.json`, `go.mod` and `pom.xml` — Python, Node, Go, Maven. But
`sub_surveyors/dependency.py`'s `_MANIFESTS` — the *known-positive* set that decides whether a
zero is provable — also lists `build.gradle`, `build.gradle.kts`, `Cargo.toml`, `Gemfile`,
`composer.json`, `setup.cfg` and `Pipfile`. So a Gradle or Rust repo ships a manifest the
surveyor recognises and the parser cannot read.

**The vocabulary is already handling this correctly, which is why it is a backlog item rather
than an incident.** Those four report `unverified` ("a manifest is here and nothing was
parsed"), not `no_signal` ("this repo declares no dependencies"). Without that distinction
Egeria's own repo would read as having zero dependencies.

Two ways to close it, and they are not equivalent:

1. **Add Gradle and Cargo parsers.** The honest fix — `build.gradle`/`build.gradle.kts` and
   `Cargo.toml` are the two that actually occur in this corpus. Gemfile/composer.json have no
   instances here yet.
2. **Narrow `_MANIFESTS` to what the parser supports.** Cheaper and *wrong*: a Gradle repo
   would then claim a **provable** zero, which is worse than the current admission of
   ignorance. Do not do this without also removing the ecosystems from the surveyor's remit.

---

#### Advanced SQLGlot view analytics
We can extend our SQL View static analyzer (`sql_analyzer.py`) with further advanced metadata analytics:
1. **Dialect Compatibility Matrix**: Check query compatibility across target warehouses (e.g. Snowflake, BigQuery, Athena, Redshift) by transpiling view SQL and report compatibility scores.
2. **Nesting Depth & Cycles**: Warn stewards about excessively nested views (e.g. view on top of view, on top of view) that degrade database query performance, and detect circular dependency loops.
3. **Query Optimization Advice**: Use `sqlglot.optimizer` to analyze query syntax in views and suggest simplified rewrites (e.g. redundant joins, dead subqueries, qualifying column expressions).
4. **Access & Join Heatmaps**: Parse views and query logs to discover which tables/columns are most frequently joined or filtered, recommending candidates for indexing or physical layout updates.

---

#### Analysis-step inventory and registration

Authoring a Survey Definition (item above, and the Dr.Egeria item below) requires knowing which analysis steps already exist to compose from — a real, unsolved gap with two halves: (1) finding Egeria's existing analysis steps (discoverable via the same technology-type/governance-definition search referenced in `docs/survey-activity-design.md` D4/D6, not yet exercised for this purpose), and (2) publishing RE's own sub-surveyors as catalogable `GovernanceActionType` elements — nothing does this today, so an author can't reference `re_analysis_step: schema_inventory` until something has created that catalogable element in the first place. Likely shape: a one-time/per-addition publish step (an extension of `EgeriaPublisher`, or its own Dr.Egeria plan) plus a local inventory RE itself can consult.

The local-executor item above is now implemented and gives this a concrete, real dispatch point to extend or replace: each resource type's adapter module (`*/survey_definition_adapter.py`) has a `re_analysis_steps` dict — today a small hardcoded Python mapping, not yet a catalogable/extensible registry. This item is about making that mapping itself discoverable/extensible in Egeria terms, rather than requiring a code change to add a recognized step.

Full context: `docs/egeria-collaboration-and-survey-model.md`, section 6.1 and open question A12.

---

#### RFA emission belongs in the orchestrator, not in each surveyor

Every surveyor that finds a gap builds its own `RequestForActionAnnotation` inline —
`security_hygiene.py:151-160` (missing SECURITY.md), `:196-205` (missing CI config), `:233-242`
(missing LICENSE), each a near-identical copy inside a hand-written if/else block
(`security_hygiene.py:131-250`). Two problems: adding a check means copy-pasting a fourth block, and
the RFA fires regardless of *why* anyone is looking.

An RFA asserts someone must act, which is only true when you own the resource. Evaluating a
candidate you haven't adopted should produce evidence, not work — otherwise the RFA drawer fills with
items about repos the user was merely browsing. Surveyors should emit findings; the orchestrator
should decide what becomes an RFA, gated on the investigation's purpose
(`docs/investigation-framing-design.md` §4). Worth doing even if framing never lands — the
copy-paste problem is real on its own.

---

#### DONE (finding 73) — the scorer can now express a partial component match

Reported, not counted: strict containment stays the headline, partial cover (`0 < coverage < 1`,
no invented threshold) prints beneath it, and overclaiming nodes are named separately.

**Still open, surfaced by the first run:** `trellis.md`'s `Web front-end` is unmatchable by
construction — its three missing files are `web/static/vendor/*.min.js`, which `exclusion.py`
removes as vendored, so no detector can ever claim them. Needs a note in `trellis-revised.md`
(rule 3 forbids editing the fixture). `Web backend` misses exactly one real file, `web/app.py` —
a chaseable detector gap, not a component-wide failure.

---

#### DONE (spike only) — Go support: the component-proposing stack is Python/Java/npm-only

**Resolved in the spike, finding 70: Prometheus 0/11 → 11/11, ARI 0.9936.** Four changes —
`rules-imports/import-go.yml`, Go resolution in `imports.py`, a `go_subsystems()` proposer in
`detectors.py`, and a name-collision fix in `score.py` that had been silently discarding 30 of 173
components. Regression-checked: `trellis` 8/11 and `egeria-workspaces` 18/27 both unchanged.

**Still open, and now the binding constraints:**

* ~~**Port it.**~~ **DONE (finding 71).** Applied as edits, not file copies, so the package's own
  divergence survived. The ported implementation was then scored for the first time — 173 components,
  **11/11**, ARI 0.9936, identical to the spike on every measure. Nine regression tests added; full
  suite 1678 passed. The `score.py` name-collision bug was scorer-only: `arch_recovery/` already keys
  by slug throughout.
* **Precision, not recall — now the only thing that matters.** Recall across three owner-published
  fixtures is 11/11 (Prometheus), 3/5 plus two at 99.8% (Milvus) and 6/6 (Kubernetes). Against that,
  the proposer emits **173, 608 and 3270 components** for **11, 5 and 6** declared ones — the
  coupling proposer contributing 146, 409 and 2482 untyped entries. Detection is solved; **nothing
  about "3270 components" is usable by a human.** Distillation (§5.2, Phase 5) is the only remaining
  obstacle to an answer. Scale is *not* the problem: Kubernetes' 31300 files and 93046 imports run in
  ~16s end to end.
* **Go type inference.** `has_main` types `promql`, `util` and `documentation` as `Console Command`
  because some `main.go` sits beneath them.
* **Go cohesion needs recursive rollup subtrees.** Files in one Go package never import each other,
  so `coupling.py`'s `import_cohesion` is structurally ~0 at package granularity.

---

### Corpus, signals & testing

#### The test suite reaches the live GitHub API — a token raises the limit, it does not fix it

Found 2026-08-25 when PR #14's CI failed on odpi. The job has no `GITHUB_TOKEN`,
so an unauthenticated client hits GitHub's 60-requests/hour limit, `urllib3`
retries with backoff sleeps, and the 30-minute job dies having produced nothing.
It passes locally only because a developer has a token — the classic
works-on-my-machine shape, and it hid until the suite ran somewhere without one.

The reached path is `repo_survey_definition_adapter`'s zipball **resource
provider** (`client.get_repo(project.github_url)` via `resolve_resources`).
**Mocking a surveyor does not mock the resource it declares** — that is the
actual lesson, and it will recur for every `requires_resources` step.

`GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}` is now set in CI, which unblocks it
at 1000 req/hr. That is a mitigation: the suite can still reach the network, so
it is still slow, still non-deterministic, and still fails differently depending
on who runs it.

**The fix** is an autouse fixture that fails any test reaching `GitHubClient`
without an explicit opt-in marker — the same shape as `requires_pgvector`, but
inverted: network access becomes something a test must ask for rather than
something it gets by default. Worth doing before the next `requires_resources`
step lands, since each one adds another way in.

---

#### Testing strategy — four silent-failure classes, one built, three open

Eight faults found on 2026-08-20 shared one shape: **the code ran, reported success, and did
nothing.** None threw. Each was found by hand, late, after the capability had been "done" for
a while, and every one of them passed its own module's tests. What they had in common was a
gap *between* two components, invisible from inside either.

**BUILT — `tests/test_reachability_audit.py`.** Structural comparison of every registry
against the surface meant to expose it: steps vs. survey types, analysis kinds vs. catalog
entries vs. dispatch, generated documents vs. the batch manifest, intents vs. rule 17's
canonical eight. Verified against the real historical faults rather than assumed — replaying
`repo_website_ingestion`'s orphan state, the 4-of-7 batch manifest, and a typo'd intent each
fails it. Deliberately asserts only that things are wired together, never that they work;
behaviour is each capability's own job, and these bugs all passed those tests.

Note it excludes the `*` (Full Survey) sentinel on purpose. That bundle is generated *from*
STEP_REGISTRY, so it can never be missing anything, and counting it would have declared
`repo_website_ingestion` reachable on the day it was reachable from nothing.

---

#### Open — grow the repo corpus substantially, as a bug-finding strategy

37 repos registered, 9 with a derived homepage, 5 groups. That small corpus has already been
the single most productive source of real defects: of the handful of repos with homepages,
three exhibited distinct, unanticipated shapes — `sqlglot.com` is a 138-byte pdoc
meta-refresh stub (ingest reported success having embedded nothing), `kedro_plugins` declares
its own GitHub URL as its homepage (would have ingested forge chrome as documentation), and
`docs.unitycatalog.com` no longer resolves. Versioned-vs-unversioned sitemaps and
site-built-from-an-ingested-repo came from the same handful.

That is a very high defect rate per repo, and it argues the corpus is the limiting factor on
finding the next class of bug rather than the test suite is. RE already has the machinery to
act on this — org import and the Discovery search/list sources — so this is a matter of
deliberately importing breadth (several foundations, several languages, monorepos, archived
and fork-heavy orgs, repos with no docs at all) and then running the full survey set across
it looking for steps that report success having done nothing. Worth planning as its own
exercise, including what "success having done nothing" looks like per step, since that is the
shape none of these tests catch on their own.

---

#### `cnf_certification` is a tombstone repo — RE has no signal for "moved"

`cncf/cnf-certification` has a one-file inventory (`README.md`), and that is **correct**, not a
truncated download — confirmed against the GitHub API 2026-08-23: `size: 4`, 5 stars, last
pushed 2026-03-09, and a description reading "CNF Certification is now part of the Cloud
Native Telcom Initiative's test catalog focus area @ https://github.com/lfn-cnti/certification".
The project moved; the repo is a signpost.

Two separate things follow, worth not conflating:

- **Immediate:** it is a disposition decision for a human — `abandoned` with the successor URL
  as the reason, and probably register `lfn-cnti/certification` instead. No code needed.
- **Worth designing:** RE has no way to *notice* this. A repo whose entire content is a README
  pointing at another repository is a recognisable shape — near-empty inventory, recent-ish
  last-push, a URL to a different repo in the description or README body — and it currently
  surveys as a perfectly healthy, extremely small project. Every zero it produces is a true
  zero, so no outcome label is wrong; the labels just cannot say "this is not where the
  project lives any more". That is a genuinely new signal, not a bug in an existing one.

It also cost real time: this repo is where the 58-repo refresh stalled for ~15 minutes, since
`clone_timeout_seconds: 300` with 3 retries is a poor shape for a batch run — 15 minutes of
silence per bad repo. Worth revisiting alongside any bulk-refresh work.

---

#### No database or filesystem questions — the Questions checklist is repo-only, and fails silently

`question_catalog.yaml` has exactly one top-level key, `repo_questions` (41 entries). There is no
`database_questions` or `filesystem_questions`, and the source CSV `docs/dr-egeria/resource_questions.csv`
is entirely repo-shaped ("Is this repository actively maintained?", …). Meanwhile the analysis catalog
*does* cover both: `database_analyses` has 4 (`schema_inventory`, `row_count_snapshot`, `privilege_audit`,
`egeria_db_survey`) and `filesystem_analyses` has 1 (`filesystem_inventory`) — so there are analyses no
question can ever reach.

**It fails silently, which is the part worth fixing first.** `question_catalog_reader.py:83-85` builds its
result dict with `"repo"` hardcoded as the only key, so `get_questions("database")` returns `[]` — the same
value as "no questions matched your filter". A user on a database's Questions tab sees an empty checklist
and cannot tell whether nothing applies or nothing exists. Either return an explicit not-authored signal or
render one in the UI; an empty list should not be the representation of two different states.

Consequences beyond the empty tab:
- Purpose-driven dispatch (`docs/investigation-framing-design.md` §3) works for repos only. An investigation
  scoped to databases has no questions to select over, so nothing dispatches.
- The `stage` skew is repo-derived (Analysis 20 / Discovery 8 / Scouting 4 / Assessment 3 / Automate 1) and
  shouldn't be assumed to hold for other resource types.

Sequencing note: write these **after** the Purpose subset measurement (item 6 above), not before. If Purpose
turns out not to discriminate, the CSV schema changes — and authoring two new question sets against a schema
that is about to change is the expensive order to do this in.

---

#### A curated field allowlist silently drops anything added upstream — three instances in one day

Found 2026-08-25 while auditing ingestion (`docs/ingestion-pipeline-audit.md`): `_note`'s prop
filter dropped a newly-added `ingested_by` field with no error, no log line, and no visible
symptom beyond attribution coming back empty. The same session hit the identical shape twice
more the same day, in unrelated code: `arch_recovery/persist.py` silently dropping
`operationCount`, and a `detail` field before either of those. Each instance is individually
defensible — a hand-written allowlist is a normal way to control what a serialized shape
exposes — but three unrelated instances of "add a field upstream, watch it vanish downstream
with nothing to say why" in one day is the same shape this project's silent-failure testing
strategy (see "four silent-failure classes" above) was built to catch, just not this
particular one.

**Not yet scoped as a fix — this entry is the "notice it, track it" step**, filed rather than
guessed at further:
- Find every hand-maintained field allowlist/filter of this shape (props filters, persisted
  payload shapes, cross-schema readers like `advisor/re_code_symbol_reader.py`'s aliasing) and
  check whether each is still correct against its current source shape, not just its shape when
  written.
- Decide whether the general fix is procedural (a code-review checklist item: "does this
  allowlist need a matching entry for that new field?") or structural (a passthrough/explicit-
  exclude default instead of an explicit-include default, or a test asserting the allowlist's
  keys are a superset of what upstream actually produces) — that choice needs whoever owns
  each call site, not a blanket answer here.
- Out of scope for `docs/ingestion-pipeline-audit.md` itself, since it's a codebase-wide pattern
  rather than an RE-vs-EA ingestion-pipeline-duplication finding — that doc points here.

#### `security_features` results reader has a fourth state its own test doesn't know about

*(Found 2026-08-30, from a live-corpus test failure during routine integration —
`test_security_features_visibility.py::test_no_repo_in_the_corpus_renders_a_bare_empty_card`.)*

`_security_features_results` (`repo_survey_definition_adapter.py`) documents exactly three
states — `measured` (findings exist), `skipped_by_design` (stats exist, GitHub hid the data),
`never_run` (no stats at all) — and the test asserts every repo in the corpus lands in one of
them, never a bare `{"findings": []}` with no stated cause.

`egeria_workspaces_git` hits a fourth, undocumented case: it has **real, visible**
`security_and_analysis` data (`dependabot_security_updates: enabled`, several others disabled —
confirmed admin-visible, not GitHub's third-party redaction), yet **zero rows** in
`project_analysis_findings` for `security_features`. The reader's last branch ("visible and
genuinely nothing enabled — a real, final answer") is written for a repo where the data was
checked and truly nothing is on; it cannot distinguish that from what this repo actually is —
data that says something *is* enabled, but the `security_features` survey step itself has
apparently never run to turn that into a finding row. The reader currently can't tell "ran,
concluded nothing's on" from "never ran, but some other fetch happened to populate the stats
JSON anyway."

**Not yet fixed; not yet root-caused past this point.** Likely fix shape: the reader needs a way
to know whether the `security_features` step itself has ever executed for this repo (a
`last_run` marker, same shape `get_analysis_last_run` already tracks elsewhere) rather than
inferring "ran" from "stats happen to be visible" — but confirm that's actually the gap before
building it; the survey step's own write path hasn't been checked yet for whether it should have
produced a finding for `dependabot_security_updates: enabled` and silently didn't.

---

### Platform & orchestration

#### Gradle versions come from the BOM, so CVE scanning still cannot answer for Egeria

Follow-on from the entry below, which is now fixed: Gradle *is* parsed (2026-08-31), and
`egeria_git` went from 0 dependency rows to 85. But **84 of those 85 have no version**, because
Egeria resolves them through a BOM (`bom/build.gradle`) rather than inline. Measured, not assumed.

`cve_scan` handles that honestly — an empty version lands in `unqueryable` with "no pinned version
to query", never as clean — so the summary is now 8 of 8 inputs where the eighth says *cannot
answer*. That is a better state than "never ran", and it is not CVE coverage.

To get real advisories for a BOM-based project, something has to resolve `group:artifact` to a
version. Options, roughly by cost:

1. **Parse the BOM file itself.** Egeria's `bom/build.gradle` carries the versions, many as
   `${jacksonVersion}`-style variables defined in the same file or in `gradle.properties`. A
   two-pass read — collect variable definitions, then substitute — would resolve most of them
   without running anything. Cheapest, and covers the common single-BOM case.
2. **Version catalogs** (`gradle/libs.versions.toml`) are a data format and would parse directly.
   Egeria does not use one, but many modern Gradle projects do.
3. **Run `gradle dependencies`.** Complete and correct, needs a JVM and a working build per repo,
   and is far outside what a survey step should do.

Option 1 is the one that matches this codebase's existing shape — the same "cheap structural signal,
not full understanding" the manifest and convention parsers already are.

**Whatever is built, the reporting rule from the Gradle entry still applies:** a version resolved by
substitution should be distinguishable from one declared inline, because a wrong substitution
produces a *confident* CVE answer about the wrong version — which is worse than the current
"cannot answer".

#### No Gradle support in the dependency parser — Egeria itself has zero dependency data, so CVE scanning cannot run on it

Found 2026-08-31 while trying to take `egeria_git`'s security summary from 7 of 8 inputs to 8.

`ingestion/dependency_parser.py` globs for six manifest kinds: `pyproject.toml`,
`requirements*.txt`, `setup.py`, `package.json`, `go.mod`, `pom.xml`. **Gradle is not among them** —
no `build.gradle`, no `build.gradle.kts`.

Measured on the live registry:

    egeria_git manifests in project_file_inventory:  build.gradle x239, and nothing else
    egeria_git rows in project_dependencies:         0

So `manifest_parse` runs, completes, publishes 4 annotations and 0 errors, and produces no
dependency rows — because there is nothing it can read. Everything downstream of dependency data
is then unreachable for the project this tool is built around:

- `dependency_analysis` has nothing to report.
- **`cve_scan` can never run**, because it scans dependencies already parsed.
- `security_summary` is permanently capped at 7 of 8 inputs for any Gradle repo.

**The vocabulary behaved correctly and that is the point.** `cve_scan` did not claim "no CVEs" — it
declined to report, exactly as its own comment intends ("No dependencies RECORDED is not no
dependencies"). The step is right. The gap is coverage, and the risk is one layer up: for a Java
project the answer is *always* "not assessed", and any surface that renders that beside a genuine
"assessed, nothing found" turns a whole ecosystem's blind spot into an apparent clean bill of
health. `security_summary` names `cve_scan` in its missing list specifically so this cannot happen
silently there.

Scope worth checking before estimating: Gradle is Java/Kotlin/Android's dominant build tool, so this
is not one project's quirk. `repo_conventions_parser` already recognises `build.gradle` and
`build.gradle.kts` for its `automated_build` check, so the *filenames* are known to the codebase —
only dependency extraction is missing.

Harder than the other five parsers, and the estimate should say so: `build.gradle` is Groovy (or
Kotlin) **code**, not a data format, so `dependencies { implementation 'g:a:v' }` can be built from
variables, version catalogs (`libs.versions.toml`), `ext` properties or plugins. Options range from
a regex over literal coordinate strings (cheap, partial, and honest if it reports what it skipped)
to invoking `gradle dependencies` (complete, needs a JVM and a working build). A partial parser is
defensible **only** if what it could not resolve is reported rather than dropped — a dependency list
silently missing its version-catalog entries is worse than none, because it looks complete.

#### `--reload` and the source cache cannot both be right — a survey of any large repo cannot finish

Found 2026-08-31 while trying to get `cve_scan` onto `egeria_git`.

`SourceCache.DEFAULT_CACHE_DIR` is `Path("data/source-cache")` — **relative**, so it resolves
against the process cwd. The server runs from the repo root, so every acquired zipball and
treeless clone extracts *inside the directory uvicorn watches*. Extracting Egeria's zipball
produced, in the server's own log:

    INFO watchfiles.main: 485 changes detected
    INFO watchfiles.main:  92 changes detected
    INFO watchfiles.main:  17 changes detected

Each one restarts the server and kills the in-flight survey. `manifest_parse` on `egeria_git`
ran for **ten minutes and wrote zero dependency rows** — no error, no timeout, just repeatedly
killed and restarted. It completed normally on a server started without `--reload`.

**Neither side is careless, which is why this survived.** The cache location is a considered
choice, and its comment says so: under `data/` beside the registry databases, so a checkout
stays self-contained and `rm -rf data/source-cache` is a complete, safe reset. Auto-reload on
save is equally reasonable for development. The two are individually right and jointly fatal.

**It is silent from every angle a person would look.**

- The run endpoint returns `{"status":"started"}` and the activity log gets its entry, so the
  caller sees a successful launch.
- `data/` is gitignored, so 44 MB of extracted source never appears in `git status`.
- `watchfiles` does **not** read `.gitignore` for its exclusions, so being ignored buys nothing.
- The only visible trace is `watchfiles.main` at INFO — which was **discarded entirely** before
  logging was wired earlier the same day. This was findable for the first time this morning.

**Directly upstream of the entry below.** That one fixed the *symptom* of a restart mid-survey
(an `activity_log` row stuck at `running` forever) and treats restarts as an occasional event —
"restarting the web server to pick up a git pull". This makes them routine and self-inflicted:
every large survey triggers its own.

Options, none chosen:

1. **Absolute cache dir outside the tree** (`~/.cache/resource-explorer/source-cache`, or
   `$RE_SOURCE_CACHE_DIR`). Fixes it everywhere, and costs the self-contained-checkout property
   the current comment is defending.
2. **`--reload-exclude data/*`** on the `uvicorn.run()` call in `cli/main.py`. Keeps both
   properties; only helps the one entry point, and anyone running uvicorn directly still hits it.
3. **Do not pass `--reload` while surveying.** Free, and relies on remembering — the kind of rule
   that gets routed around because nothing enforces it.

Whichever is chosen, the silence deserves its own fix: a survey killed mid-flight should be
distinguishable from one that ran and found nothing, which is this codebase's most-repeated bug
class and is exactly what the entry below already built the machinery for.

#### FIXED — a server restart mid-survey left activity_log rows stuck at 'running' forever

Confirmed live 2026-08-26: restarting the web server to pick up a git pull killed two
in-flight Survey Definition runs (`RepoFullSurvey` and `RepoArchitectureDiscovery` on
`deep_causality`) mid-flight. Each survey's individual steps had genuinely completed and
published to Egeria — visible as their own `ok` activity_log rows — but the *outer wrapper*
row each survey run creates up front (`status='running'`, written by `survey_definitions.py`'s
`run_survey_definition_route`, `projects.py`'s scouting-scan route, and the equivalent
database/filesystem routes) is only ever marked terminal by one line at the very end of the
background `daemon=True` thread doing the work. Kill the process, and that line never runs —
nothing on startup reconciled it, so the row read "running" indefinitely, with no way to tell
"still going" from "died and nobody noticed."

**Fixed independently, twice, same day — the ownership-based version won.** This session's
first pass added `ProjectRegistry.reconcile_orphaned_running_activity()`: a blanket "every
`running` row is orphaned on any startup" reconciler. **That was wrong** — multiple RE
processes routinely share one database during development (confirmed live: this session's
server and the user's, running concurrently against the same rows), so a blanket sweep on
*any* process's startup would falsely resolve a peer's genuinely-still-running survey out from
under it, mid-write.

**What actually shipped** (`4e91ba2`, "Runs that stopped stop claiming to be running"):
`resource_explorer/run_reconciler.py`, wired into `web/app.py`'s `_lifespan()`. Reconciles by
**ownership**, not blanket sweep or age — a running row records the pid and process start time
of whoever owns it, and is resolved only when that exact process is provably gone. Age (six
hours) is the fallback only for rows with no owner recorded, an order of magnitude past the
longest measured real survey (~16 minutes). Marks resolved rows `interrupted`, not `error` —
"we know it stopped, not that it failed." Fails safe throughout: an owner that can't be
verified is left alone (`left_alone` in the return value), because "I can't tell if this is
alive" must never resolve to "it's dead" — a real timezone bug in an early version did exactly
that (silently routed every row to `left_alone` and resolved nothing, for three days, while
reporting success). The blanket version and its tests were removed during the merge that
brought this branch and `main` together (2026-08-26) rather than kept alongside the real fix.

---

#### Distributed survey orchestration via a flow tool (Prefect) — verified live and default-on (2026-08-26)

#### DONE 2026-08-27 — Retire the ISSUE-50 workaround in `egeria_delegated_step.py`

`EgeriaDelegatedStepSurveyor` routes through `initiate_gov_action_type()` because
`initiate_engine_action()` used to 404: it posted to a URL missing the governance engine's name
and had no parameter to supply one (logged as ISSUE-50, 2026-08-17). The workaround needs a
**pre-authored `GovernanceActionType` per delegated step**, which is real authoring overhead for
every step RE wants to delegate.

**Measured 2026-08-26: fixed in the installed pyegeria 6.0.18.4.** The method now takes
`governance_engine_name` and builds
`.../governance-engines/{name}/engine-actions/initiate` — the shape the Java route
(`AutomatedCurationResource.java`) actually expects. `initiate_and_wait()` already exists in
that module, kept for exactly this moment.

Work: switch the primary trigger path to `initiate_and_wait()`, live-verify against a real
delegated step, and drop the per-step `GovernanceActionType` requirement (and its probe doc) if
verification holds. The module's comment saying the direct path is "kept for when ISSUE-50 is
fixed" is stale and should go with it.

**Done 2026-08-27.** `initiate_and_wait()` now takes `governance_engine_name`
and passes it through; the surveyor requires it alongside `request_type` and says so, rather than
letting the omission surface as a bare 404. Live-verified: a real engine action on the
Stewardship engine (`write-to-audit-log`) reached `COMPLETED` with a real completion message
through the direct path, needing no pre-authored `GovernanceActionType`.

`initiate_action_type_and_wait()` is kept — it is not a workaround any more, just the other valid
path, and the better one when a `GovernanceActionType` already exists since the engine is then
resolved server-side from its executor link.


#### Distributed survey orchestration via a flow tool (Prefect) — early prototype, not yet integrated

RE's only execution model today is either synchronous in-process (`SurveyOrchestrator`) or the `scheduler.py` daemon-thread poller (see the "Periodic / triggered survey scheduling" item below). Neither can run survey work *near* a protected asset (a database inside a VPC, a filesystem edge agent) without deploying RE itself there, and neither gives retries/backoff/task-level telemetry for free.

**Design notes (2026-07-14):** `docs/distributed-survey-orchestration.md` proposes Prefect (over Dagster/Airflow — see its §3 comparison table) as a task runner slotted in via the existing `executes_at` routing convention already used by Survey Definitions (`executes_at: prefect`, alongside today's `egeria`/`resource-explorer`), so this is additive to the local-executor work above, not a replacement. `docs/distributed-survey-best-practices.md` grounds this against how DataHub/OpenMetadata handle distributed estate-wide ingestion, and proposes a broader progressive intake funnel (Scouting → Staging Registry → Enrichment Gate/ToDo → Deep Assessment → Egeria Certified Catalog) that reframes "coherent selective-cataloging model" (item below) in terms of Prefect-driven phases.

**Shipped so far (uncommitted, prototype-stage):** `resource_explorer/prefect/flows.py` (`@flow`/`@task` wrappers) and `resource_explorer/surveyors/prefect_adapter.py` (dispatches a step to the Prefect REST API or runs it locally via `nest_asyncio`), plus `tests/test_prefect_integration.py`. `prefect` added to `pyproject.toml` dependencies. **CRITICAL FINDING 2026-08-20 — the Prefect API path had never executed.**
`run_prefect_step` opened with `asyncio.get_running_loop()`, while a redundant
`import asyncio` further down the same function made `asyncio` a closure cell (the lambda
captures it). That first line therefore did a LOAD_DEREF on a cell nothing had stored and
raised `UnboundLocalError`; the broad `except` read it as "API unreachable", logged
"Prefect API dispatch failed", and ran the flow in-process. So every Prefect step has always
run locally, `_run_prefect_step_api` was dead code, and the log line was indistinguishable
from a genuinely unreachable server. Fixed (inner import removed), and the fallback now logs
the exception type and traceback so a bug here can no longer masquerade as a connection
problem. **This matters for the design decision below: whatever the flow-engine dependency
has been bought so far, distributed execution is not it — nothing has ever been dispatched.**

**Routing fixed at the same time.** `prefect.enabled` re-routed every step declaring
`executes_at: resource-explorer`, overriding what a definition explicitly asked for —
`executes_at` is documented as naming the execution engine and as open-ended precisely so
engines can be chosen per step, so a global override removed the only way to say "run this
one here" and made `executes_at: prefect` redundant. Now gated on a separate, off-by-default
`PREFECT_ROUTE_LOCAL_STEPS`: routing RE's own steps through Prefect for retries/telemetry is
a legitimate deployment choice, it just has to be asked for by name.

**Not yet done:** ~~`executes_at: prefect` is not wired into `survey_definition_executor.py`'s dispatch loop~~ **(CORRECTED 2026-08-19, verified against this tree: it IS wired — `_use_prefect` at `survey_definition_executor.py:162-167`. Note `:167` — when `config.prefect.enabled` is true, *every* step marked `executes_at: resource-explorer` is rerouted to Prefect, so a global flag overrides what a definition explicitly asked for. Open question whether that is intended.)**; no staged-candidate registry states in `registry.py`; no deployment/worker actually configured or run against. This needs review as a real design decision (own dependency on a flow engine is a significant infra commitment) before the prototype code is treated as a real feature — not yet reflected as its own line item, currently living only in these two design docs.

Related/overlapping: "Periodic / triggered survey scheduling" below (this may be the eventual replacement for the daemon thread it says is only a short-term fix), "Coherent selective-cataloging model" below (the staging-registry funnel is a concrete proposal for it), and "Unify survey launching" above once a launcher needs to route to a third execution engine, not just two.

**VERIFIED LIVE 2026-08-26 — the "needs review as a real design decision" above is answered:
real dispatch works end-to-end**, tested against a local `prefect server` + a deployed
`re_survey_flow` + a running worker, not just code review. Three more bugs found and fixed in
the process, none caught by the earlier code-only review:

- `prefect deploy` (the CLI command) itself failed — `.deploy(work_pool_name=...)` alone
  requires an image or remote storage location; fixed to `.from_source(source=<this
  checkout>, entrypoint=...)`, correct for a `process`-type work pool running on the same
  machine as the caller.
- `_run_prefect_step_api` fetched the completed flow run's result via
  `client.resolve_value(state.data)`, which doesn't exist on `PrefectClient` in Prefect 3.x —
  every completed API-dispatched run raised `AttributeError`, was caught by the same broad
  `except` the 2026-08-20 finding above already flagged, and silently ran the step's work a
  **second time** via local fallback. Fixed to `state.result(raise_on_failure=True)`, and
  `re_survey_flow` now declares `persist_result=True` (Prefect 3.x doesn't persist results by
  default, and a state fetched back via `read_flow_run` from a different process than the one
  that ran the flow has nothing to fall back to without it).
- **Cancelling a flow run silently didn't stop the work.** Found testing the new cancel
  endpoint (see below): `state.is_cancelled()` correctly raised, but that exception was caught
  by the *same* broad `except` as "server unreachable," so a cancelled run fell back to running
  the step again locally — cancel had no actual effect. Fixed with a dedicated
  `PrefectFlowRunCancelled` exception that `run_prefect_step` re-raises instead of falling back
  from; everything else (a real connection failure, a bug) still falls back as before.

**Default flipped:** `PrefectConfig.enabled` now defaults `True` (was `False`) — safe with no
server running, confirmed by the fallback behavior above; adds per-step connection-attempt
overhead for `executes_at: prefect` steps only, until a server exists. `route_local_steps`
stays `False` by default — routing every plain step through Prefect multiplies overhead by
however many steps a survey has, unproven at volume; left for a later pass once the admin
panel below makes it observable. `.env.example` and CLAUDE.md's External Services list now
document the required local setup (`prefect server start`, `resource-explorer prefect deploy`,
`resource-explorer prefect worker`) — previously undocumented anywhere.

**One step opted in so far:** `repo_arch_coupling` (the real `git log` history clone,
long-running/thrash-prone in a way the cheaper steps aren't) now declares
`executes_at: prefect` in `scripts/generate_repo_survey_definition.py`'s `PREFECT_ROUTED_STEPS`
— a deliberate, narrow opt-in, not a blanket switch. **This is a mechanism, not yet a live
change** — the corresponding Egeria-side Survey Definition step is published via a one-time
Dr.Egeria markdown run (`dr_egeria_survey_publisher.py`), which needs a live Egeria instance
and human-in-the-loop execution; not done as part of this pass.

**New: an Admin "⚡ Prefect" panel** (`web/routes/prefect_status.py`,
`loadAdminPrefectPanel()`/`renderAdminPrefectPanel()` in `index.html`) — flow-run status
grouped by resource (slug/step tags added to `create_flow_run_from_deployment`), a real Cancel
button (`POST /api/prefect/flow-runs/{id}/cancel`, verified live to actually stop a running
step, not just mark it), and a link out to Prefect's own UI for full per-task logs. Degrades
gracefully (a status flag, not a 500) when no server is reachable.

**Scope boundary, worth restating here too:** all of the above is about **locally-dispatched**
survey steps. `executes_at: egeria` steps are coordinated by Egeria itself — none of this gives
RE any more visibility into those. See "Some surveys are coordinated by Egeria, not RE" below.

**Bare-host only for now, deliberately (2026-08-26):** `scripts/prefect_up.sh`/`prefect_down.sh`
(`make prefect-up`/`prefect-down`) bring the server/work pool/deployment/worker up idempotently
on this machine, but nothing containerizes them — no launchd/systemd unit either. Trellis isn't
ready for containerization yet (explicit user call), so this stays a bare-host convenience
script rather than becoming a container prematurely.

**A Prefect container already exists — in `egeria-workspaces-fs`, not Trellis — and isn't
started.** `egeria-workspaces-fs/compose-configs/optional-associated-runtimes/prefect/
docker-compose.yaml` defines `prefect-server` (`prefecthq/prefect:3-python3.12`, matches the
3.x this integration was verified against) and `prefect-worker`, both on `egeria_network`.
Reviewed, not modified — three concrete gaps to close whenever Trellis containerization
actually happens, so they aren't rediscovered from scratch:

1. **Work pool name mismatch.** The container's worker runs `prefect worker start --pool
   egeria-pool`; RE's own default (`PrefectConfig.work_pool` in `config.py`) is
   `default-agent-pool`. As configured today, RE would deploy to a pool this worker never
   polls — every step would sit `SCHEDULED` forever, silently, no error. Either the container's
   pool name or RE's default needs to change to match (or `PREFECT_WORK_POOL` set explicitly in
   whichever environment talks to this container).
2. **The worker container has no access to RE's code.** It builds from
   `../../../runtime-volumes/prefect/user_code` — a generic flow-code mount, not
   `resource_explorer`. `re_survey_flow` imports `resource_explorer.surveyors.
   survey_definition_executor` and `resource_explorer.registry` directly; nothing in the
   compose file installs the `resource-explorer` package or mounts the RE checkout into that
   container, so the worker would fail on import the moment it tried to run RE's flow for
   real. Needs either the package installed into a custom image (a new Dockerfile, not the
   generic `user_code` one) or an equivalent volume mount plus dependency install.
3. **Separate `prefect` Postgres database, unconfirmed whether it's provisioned.** The server
   points at `postgresql+asyncpg://prefect_user:user4prefect@egeria-shared-postgres:5442/
   prefect` — a distinct database/role from the `egeria_advisor` database RE and EA already
   share. Not verified from a Trellis checkout whether that role/database already exists on
   the shared Postgres instance or still needs creating, the way RE's own `resource_explorer`
   schema did (see root README's "Databases" section).

None of these are hard blockers, but (2) in particular is real integration work, not a config
tweak — worth sizing before assuming this container is a quick swap-in for `prefect_up.sh`.

---

#### Some surveys are coordinated by Egeria, not RE — a separate visibility question, deliberately deferred

Raised 2026-08-26 alongside the Prefect work above, and explicitly scoped out of it by the
user: `executes_at: egeria` survey steps are coordinated by Egeria itself, not by RE's local
executor or Prefect. RE has no more visibility into those than it had before this pass (no
flow-run, no local thread, no activity_log row updated mid-run) — the "are my surveys making
progress / how do I cancel one / where's the log" questions this whole thread started from have
a real, currently-unanswered version for this category specifically. Needs its own design pass:
what does Egeria itself expose for a running `GovernanceActionProcess` (status, cancellation,
logs), and how would RE surface that the same way `web/routes/prefect_status.py` now does for
the local/Prefect case. Not investigated yet — flagged so it isn't assumed solved by the
Prefect work above.

---

#### Periodic / triggered survey scheduling

Egeria has no native cron/interval scheduling for survey action services (the only interval-based mechanism found anywhere in the framework, `IntegrationConnectorProvider.refreshTimeInterval`, belongs to a different framework — integration connectors, not surveys). RE already has rudimentary scheduling of its own (`resource_explorer/scheduler.py` — a daemon thread polling the `resource_schedules` table every 15 minutes, per D9 in `docs/survey-activity-design.md`), so this is easily fixed short-term if a gap shows up. The longer-term expectation, though, is that recurring scheduling lands in Egeria core, or is reached via a connector to a dedicated scheduling service, rather than RE's daemon-thread approach becoming permanent infrastructure. Revisit once the selective-cataloging flow above has a shape, since "survey on a schedule" and "survey a previously-selected subset again" are closely related.

---

#### HIGH — Unify survey launching (retire old Re-survey buttons, no unified dashboard yet)

Two uncoordinated ways to start a survey on the same resource exist side by side today:
1. The new Survey Definitions panel (`docs/Backlog.md`'s "RE locally executing Survey Definitions" item below) — Egeria-authored, browses real candidates with step detail.
2. Old per-resource-type buttons still in `resource_explorer/web/static/index.html` (e.g. the database detail panel's "📊 Re-survey" → `showSurveyDbModal()` and "☁ Re-survey in Egeria" → `showPublishDbModal()`, ~~around index.html:3641-3675~~ **now `index.html:7351` / `:7377` / `:7389`, verified against this tree**) that predate the Survey Definitions work and don't go through it at all.

**CORRECTED 2026-08-19 — this is not just a UI unification.** The two paths diverge on five axes: step selection (editing a Survey Definition in Egeria has *zero* effect on the legacy path), Egeria target (the legacy modals collect per-call URL/server/user overrides, so the two paths can write to *different Egeria servers in one session*), publish shape (narrow `publish_step_annotations` vs. full `EgeriaPublisher.publish` with cataloging side effects), result storage (only the legacy path writes history rows and drives the charts), and scheduling (`scheduler.py` calls the orchestrators directly — Survey Definitions are unreachable from a schedule). Retiring the legacy path means porting history storage and scheduling first. Detail, and a third option (legacy becomes a thin caller of the new path), in `docs/survey-and-analysis-current-state-2026-08-19.md` §1.2 and §5.1 — **but re-verify the specifics against this tree; `run_batch` postdates that analysis and likely bears on it.**

Neither the old buttons nor the Survey Definitions panel is quite right as the long-term answer — Survey Definitions is Egeria-authored/candidate-driven, which is correct for "what can run here," but launching a survey is a cross-cutting action needed from multiple places (resource detail panel, discovery results, scheduled/recurring runs), not just one tab. Likely direction: a generic survey-launcher component/modal that any view can invoke (given entity_type + slug), backed by the Survey Definitions candidates API, replacing the old per-type modals rather than living alongside them.

Related, not yet built: polling Egeria for survey results so completed native (`executes_at: egeria`) runs surface somewhere unified instead of only showing an engine-action GUID with "check Egeria's Asset Catalog" (see `resource_explorer/web/routes/survey_definitions.py` run endpoint and its frontend handling in index.html around line 2881). Today there is no unified "survey results dashboard" — results are scattered across the Survey Definitions run modal, the database/filesystem detail panels' own survey history, and Egeria's own catalog for anything async. A poller (or the A2A rendezvous from the item below) is the likely fix, feeding one dashboard view regardless of which launcher/engine started the run.

Full context for the Survey Definitions side: `docs/egeria-collaboration-and-survey-model.md` section 6; the A2A item below covers the async-notification half of "unified dashboard."

**RE-VERIFIED 2026-08-30 against this tree — the picture above is stale, and better than it says.**
Significant unification already shipped without this entry being updated:
- **Repo's legacy run path is gone.** `runSurveyFromSidebar`, `runScoutingScan`,
  `publishScoutingRegistration`, `runProfileScan`, `publishProfileFindings` are all deleted
  (confirmed by grep — zero hits). The Survey Definitions candidate panel is the only way to
  launch a repo survey now (`docs/survey-tab-unification-plan.md` D1–D5, landed since the
  2026-08-19 doc was written, despite that doc calling itself "not yet committed").
- **Publish is unified for repo** — one route (`POST /api/egeria/{slug}/publish`), used by both
  the Survey Definitions panel's generic `☁ Publish` (D4) and the repo detail page's own
  "Publish survey →" button.
- **The scheduler already dispatches Survey-Definition-typed schedules** for both repo and
  database (`_run_scheduled_survey()` → `run_survey_definition()`).

**What's still genuinely open:** filesystem has none of this — `showSurveyFsModal`/
`submitSurveyFs` is the only way to survey one, and `scheduler.py`'s `_execute()` has no
filesystem branch at all (repo/database only), so a filesystem schedule can never fire even if
one were somehow created. Database's legacy `showSurveyDbModal`/`showPublishDbModal` also still
exist alongside the Survey Definitions panel — not yet confirmed whether they're now a safe
duplicate (like repo's were) or still do something the panel can't.

**Direction from Dan (2026-08-30): database and filesystem should route through Egeria's own
EXISTING native surveys, not through newly-authored RE-side Dr.Egeria Survey Definitions.**
This changes what "closing this item" means for those two resource types — it is not "author a
`database-survey-definition-*.md` / `filesystem-survey-definition-*.md` the way repo's eight
were authored." Both adapters already carry the mechanism this points at:
`other_engine_handlers={"egeria": _trigger_egeria_native_survey}` in both
`database/survey_definition_adapter.py` and `filesystem/survey_definition_adapter.py` — a step
tagged `executes_at="egeria"` actively triggers Egeria's own native survey rather than being
skipped. The gap is not "build the trigger," it's "prove the trigger, end to end, and get its
results back."

**Testing gap, explicitly called out as open work (2026-08-30, Dan) — keep on the backlog:**
`filesystem/survey_definition_adapter.py`'s own module docstring already says the native-trigger
path is "not yet exercised end-to-end, since this environment has no cataloged filesystem to
test against." Database's equivalent (`_trigger_egeria_native_survey` in
`database/survey_definition_adapter.py`) has more surrounding coverage but its own live,
end-to-end exercise (cataloged resource → triggered native survey → result actually lands
somewhere RE reads it back from) has not been separately confirmed either. Both need a real
pass: a cataloged filesystem and database resource, a live Egeria trigger, and confirmation of
where the native survey's results actually surface (ties into the "results dashboard" gap two
paragraphs up — an `executes_at: egeria` step today only returns an engine-action GUID with
"check Egeria's Asset Catalog," which is not itself a tested read-back path).

**Also blocked on the same gap: Automate's own 📋 Surveys sub-tab (put a whole Survey Definition
on a cadence) is hardcoded to repo end to end** — the frontend requires a selected repo before
rendering anything, and `_saveSurveySchedule` posts to `/api/schedules/repo/...` unconditionally.
`list_definitions()`'s `resource_type` field was fixed 2026-08-30 to be genuinely read per
document instead of hardcoded `"repo"`, so the backend is ready — but there is nothing for it to
show beyond repo until database/filesystem Survey Definitions exist (by the native-survey route
above) *and* the tab's resource selector is generalized to match. Two separate small pieces once
the native-survey path is proven, not one.

---

#### MEDIUM (was HIGH) — Filesystem local survey: silent-failure causes fixed, true "hang" UX still open

Originally: filling out the local filesystem survey pop-up and clicking Run appeared to hang — no progress, no response to further clicks — while the server was actually alive and grinding through a very long synchronous scan, dumping a wall of `Could not profile schema for ...` warnings and pandas/openpyxl noise to the server console that the user never saw (2026-07-13 report, full console dump captured in chat).

**Implemented (2026-07-13), per `docs/filesystem-survey-analytics-plan.md`:**
- `IGNORE_DIRS` now skips bare `venv` as well as `.venv` — this was the concrete cause of the multi-minute scan across dozens of stray venvs (`tzdata`/`pytz` zoneinfo files) in the original report.
- `LocalFileSystemSurveyor` (`resource_explorer/surveyors/filesystem/local_filesystem_surveyor.py`) is now split internally into a metadata-only structure pass and a separate profiling pass. Per-file profiling failures and inaccessible files/directories are collected into `survey_data["profiling_errors"]`/`["inaccessible_files"]` instead of only `log.warning`, and — for the Survey Definitions run path — surfaced as real `RequestForActionAnnotation`s (`egeria_filesystem_surveyor.py::publish_step_annotations`) so a run that hits malformed CSVs/legacy `.xls` files reads as "completed with warnings," not silence. Verified against reproductions of the exact original error strings; covered by `tests/test_filesystem_survey_definition_adapter.py`.
- Kept as **one** Survey Definition step rather than two, per follow-up direction (if you're already asking the OS for one file's `stat()`, there's no benefit to walking the tree twice for the rest of it) — also matches Egeria's own native survey, which turns out to be a single un-decomposed step itself.

**Still open — this is why the item isn't fully closed:** the pre-existing `/api/filesystems/{slug}/survey` route (`web/routes/filesystems.py::survey_filesystem`, the original "📊 Run Survey" button in the Filesystem tab, distinct from the newer Survey Definitions tab — see the "unify survey launching" item below) still calls `LocalFileSystemSurveyor.run()` synchronously with no progress reporting, streaming, timeout, or cancellation. It benefits from the `IGNORE_DIRS` fix and no longer silently drops errors internally, but the browser's `fetch()` still just waits on the full run with nothing to show in the meantime on a large/broad root — the "feels like a hang" UX itself is unfixed there. No file-count/size cap or confirmation step before scanning a large/broad root path either. Likely resolves naturally once "unify survey launching" retires this route in favor of the Survey Definitions path, rather than needing its own fix.

---

#### LOW — Orphaned temp-dir cleanup on hard crash

Every repo download (full ingest, incremental refresh, Coarse Profile's `refresh_profile()`, symbol-only extraction, single-collection re-embed — confirmed all 5 call sites 2026-08-10) already downloads into a `tempfile.TemporaryDirectory()`, self-cleaning on the `with` block's exit — success, error, or exception. No local clone persists anywhere by design; disk usage from a repo download is transient, existing only for the duration of that one run. The one non-`TemporaryDirectory` temp file (notebook parsing, `NamedTemporaryFile(delete=False)`) is explicitly `os.unlink()`'d in a `finally` block.

The one real gap: a hard process kill (`kill -9`, crash, power loss) mid-download skips the `with` block's cleanup entirely, potentially leaving an orphaned temp dir (partial zipball) in the OS temp directory. Rare, self-limiting (each leftover is at most one repo's zip; the OS's own temp-dir conventions eventually reclaim it), and not actively guarded against today. A small startup sweep clearing stale resource-explorer-tagged temp dirs from a previous crash would close it — not worth building unless actual `/tmp` bloat shows up in practice.

---

#### Clustering: propose candidate blueprints, starting with the deployment perspective

Design: `docs/architecture-recovery-clustering.md` (2026-08-29). Promoted from "parallel workstream"
to **prerequisite for the curator review surface**, because rendering the corpus showed more than a
quarter of repos produce a proposal no curator could read and depth alone does not fix it.

Measured, and it makes the first step cheap: every component already carries a §4.1 perspective
(logical 1747 / deployment 1300 / physical 168 across 3,215 components), and `blueprint` is empty on
**all** of them, so clustering has never run. Applying the existing `scope_hierarchy.derive()`
grouping *within one perspective* already reaches the ~10-component goal for **deployment** on most
repos — genaiexamples 546 -> 8, genaicomps 289 -> 4, milvus 31 -> 5. The **logical** perspective does
not (egeria_git 924 -> 279), and that is precisely the perspective §4.1 says "needs inference or a
human", so the automation boundary and the design's own prediction agree.

Build order in the doc: deployment-perspective clustering first (cheapest real result, and it makes
the renderer's blueprint grouping meaningful for the first time); perspective carried in the survey
definition so a proposal records the context it was clustered for; wire density as the second signal
against the logical perspective; RFA the cases that will not cluster rather than emitting a
low-confidence grouping.

**Deployment-perspective clustering (signal 1) — DONE, since before this entry was last read.**
`arch_recovery/clustering.py` (`propose`/`_build`/`rollup`/`assign`), wired into `persist.py`'s
`_cluster()` and running on every survey. Affinity promotion (Collection -> composed component via
import-cohesion) landed alongside it. Tested: `test_arch_clustering.py`, 29 cases. This paragraph was
stale — recorded here so the next reader doesn't re-derive "has clustering run yet" from scratch.

**Wire density (signal 2) — DONE 2026-08-30, same session.** Tried only as a fallback, once every
declared boundary (deployment context, scope hierarchy) is exhausted and a group is still over the
~10 goal — not blended with those signals or given a vote alongside them. Built as greedy
agglomerative merging over the wire graph (`interfaces.propose`'s own `wires` list, the same one
`mermaid.render` draws from and `persist_ir` was already threading through as an unused parameter):
repeatedly merge whichever two groups have the strongest total wire weight between them, bounded by
`target_size`, stopping when no beneficial merge remains. Pairwise weights are computed once and
updated incrementally per merge (a merged group's weight to a third group is the sum of its two
parents' — wires are additive) rather than rescanned every iteration, since this runs on a survey's
hot path; a size backstop (`_MAX_WIRE_DENSITY_MEMBERS = 200`, unmeasured, revisit if it's ever what's
silencing a real group's wire signal) sits on top of that as insurance, not a substitute for it.
"No signal, no cluster" applies here too — a member set with zero wires between any of them returns
no split, same as `_subdivide`'s existing contract, rather than one bucket covering everyone.
Resulting clusters carry `signal: "wire-density"` so a curator can tell a measured graph from a
declared boundary. Wire endpoints resolve by slug-or-name (mirroring `mermaid._resolve_endpoint`'s
existing handling of the same ambiguity — a compose wire is attributed by service name, a port by
slug), kept as its own small copy rather than a shared import, same reasoning as
`ComponentMaterializer._find_element_guid` duplicating `EgeriaPublisher`'s.

**Shared interface (signal 3) — DONE 2026-08-30, same session, following directly from the
interface-extraction work above (item A's OpenAPI/FastAPI reuse, item B's language-binding
evidence).** The LAST fallback in the chain — tried only once deployment context, scope hierarchy,
AND wire density have all found nothing further — because it needs an IDL/OpenAPI document per
component, rarer input than a wire between two components that simply call each other. `interfaces.py`
was extended first, to capture a structured *name* rather than just a count: `_openapi_info()`
(renamed from `_count_openapi_operations`) now returns `info.title` alongside the operation count,
`_count_proto_rpcs()` returns the joined, sorted, unique proto/gRPC service names, and both (plus
Thrift) pass an `interface_name` into `_port_dict()`, stored in `additionalProperties["interfaceName"]`
— the same sanctioned extension point `operationCount` already uses. GraphQL deliberately does NOT
get one: its root type names (`Query`/`Mutation`/`Subscription`) are the same across almost every
GraphQL service, so treating them as a shared-identity signal would cluster unrelated services that
merely both speak GraphQL.

`clustering.py` gained `_interface_names(components, ports)` (`{slug: {declared name, ...}}`,
resolved slug-or-name the same way `_wire_density_split` resolves wire endpoints) and
`_shared_interface_split(member_scopes, by_scope, interface_names)` — an exact partition by shared
name, not a size-bounded weighted merge like wire-density: a name two or more scopes present together
is the whole signal, so there is no `target_size` to respect the way wire-density has one. A scope
presenting more than one interface name goes to whichever shared group is largest (deterministic
tie-break by name), and a name only ONE scope presents contributes nothing — "no signal, no cluster"
again, same as `_subdivide`/`_wire_density_split`'s existing contract. `_build()` and `propose()` got
a new `interface_names`/`ports` parameter threaded exactly like `wire_weights`/`wires` was for signal
2 (including through `persist.py`'s `_cluster()`, which already received `ports` as an unused-for-
clustering parameter). Resulting clusters carry `signal: "shared-interface"`.

Confirmed by test that wire-density strictly wins when both signals would apply to literally the same
subset (a densely-wired group that also shares an interface name clusters as `"wire-density"`, never
`"shared-interface"`) and that shared-interface still gets its turn where wire-density genuinely finds
nothing (an interface-only context group with no wires among its own members).

**Found and fixed alongside it — a live, untested bug in `_build`'s recursive `_subdivide` branch:**
the call `_build(sub_name, sub_scopes, by_scope, perspective, target_size, depth_left - 1)` passed 6
positional args to a 7-parameter function (missing `by_scope_components`), so every value after it
landed in the wrong slot and `depth_left` got none at all — a `TypeError` on any call. Unreached by
all 29 pre-existing tests: the oversized-cluster tests use flat scope locators (`flat::s{i}`)
specifically so `scope_hierarchy.derive` finds nothing to subdivide, which is exactly what kept this
branch from ever running; real corpus runs likely never hit it either, since an oversized group needs
a deployment-context split to be genuinely unavailable (not just single-valued) AND a further scope
hierarchy to exist below it. Two new regression tests exercise `_build` directly (bypassing
`propose()`'s own first pass, which finds the finest qualifying split in one shot for realistic path
hierarchies and so never naturally reaches this branch either) to prove the recursive call no longer
raises and the second-level split is real.

Suite: `test_arch_clustering.py` grew from 29 to 50 cases (the bug-fix regression, ten
`TestWireDensitySignal` cases, seven `TestSharedInterfaceSignal` cases, and two end-to-end tests
proving `persist_ir` actually threads `wires`/`ports` through `_cluster()` into
`clustering.propose()` — a unit test of `propose(wires=..., ports=...)` alone would not have caught
a broken wire-up in between). `test_arch_interfaces_idl.py` +6 (`TestInterfaceNameIsAStructuredIdentity`
— OpenAPI title capture, proto/Thrift service-name capture, GraphQL exclusion, absent-title case).
Broader arch/clustering/interfaces/mermaid suite: 507 passed, 9 skipped.

---

#### RE has no login at all, and its identity is inconsistent across 26 sites

Dan, 2026-08-29: *"If RE doesn't have a login, it should"*, and *"both EA and RE will need
(ultimately) to support multi-user."*

`/api/egeria/whoami` returns `get_config().egeria.user_id` and the comment above it says it is
*"deliberately NOT a login mechanism"* — so the header's "Connected as: erinoverview" is cosmetic.
Identity is read from `os.getenv("EGERIA_USER", …)` at **26 sites**, each building its own pyegeria
client, with four different fallbacks (4x `_DEFAULT_USER`, 3x `"steward"`, 3x `"erinoverview"`,
1x `""`), so **which identity an RE operation acts as depends on which module built the client**.

Full reasoning and the recommendation to extract `trellis-auth` rather than build a second login:
`docs/trellis-auth-extraction.md` at the Trellis root. Four parts, and the package is the smallest:
the extraction; a login UI in RE's SPA (it has never had one); collapsing the 26 sites onto the
authenticated identity; and **the design question that should be settled first** — what RE does when
nobody is logged in, since surveys and schedulers run unattended and a scheduled survey has no user.
That needs a declared service identity, which is a legitimate configured account and NOT the same as
the silent fallback EA's SS-4 decision removes.

---

#### HIGH — extract a shared query cache into a Trellis package; it fixes a live bug in Egeria Advisor

Full detail: `docs/re-ea-consolidation-audit.md` item 1.

RE's `query_cache.py` (124 lines) is genuine LRU (`OrderedDict` + `move_to_end()` on access) with
TTL and an optional Redis backend. EA's `query_cache.py` (169 lines) is named and documented as
LRU throughout but **is not** — plain `dict`, no reordering on access, just FIFO eviction of the
oldest insertion. EA does have hit/miss/`most_popular` telemetry RE lacks.

**Proposed:** a shared `trellis-`package `QueryCache` built from RE's TTL/Redis/invalidation
design as the base, with EA's stats/`most_popular` reporting layered on top — same shape as
`trellis-vectorstore`'s extraction (each app keeps a thin adapter over the shared class). Fixes
EA's eviction bug as a side effect of the extraction, not as separate work.

---

#### HIGH — extract the BeeAI agent base/runner shared by RE and EA

Full detail: `docs/re-ea-consolidation-audit.md` item 2.

RE's `resource_explorer/agents/base.py` (`BaseExplorerAgent`, 200 lines) and EA's
`advisor/agents/base.py` (`BaseAdvisorAgent`, 83 lines) both hand-roll the same BeeAI
`RequirementAgent` construction and the same "sync caller in an async context → spawn a thread
with a fresh event loop" workaround, down to matching inline comments explaining why BeeAI needs
a fresh event loop in a thread. This is copy-pasted logic, not two teams converging on the same
idiom independently — same tier of confidence as `trellis-microflow`'s extraction.

**Proposed:** a shared `BeeAIAgentRunner`/`BaseAgent` mixin covering `_build_agent()`/
`_run_agent()`. RE's slug-inference/clarification helpers and EA's separate (apparently dead)
"legacy... not using BeeAI" `BaseAgent` scaffolding stay app-specific — check whether that
second EA class is still referenced anywhere before or alongside this extraction.

---

#### MEDIUM — EA should adopt RE's dual-backend registry connection-management pattern

Full detail: `docs/re-ea-consolidation-audit.md` item 3.

RE's `registry.py` has a mature `ConnectionWrapper` + SQLAlchemy dual-engine abstraction
(SQLite↔Postgres placeholder/DDL translation, pooling, same-transaction column introspection
working around a real Postgres visibility bug) that RE already reuses across `registry.py`,
`observability/metrics_collector.py`, and `feedback_store.py`. EA's `db_consolidated.py`
(`ConsolidatedDBManager`, 283 lines) reinvents a narrower, Postgres-only version of the same
idea — same shape as the Java-symbol-extraction finding in the ingestion audit: one app's
implementation is simply more mature, and the other never adopted it.

**Proposed:** the schemas stay separate (project/resource state vs. metrics/audit/symbol
tables are genuinely different data) — only the connection-management primitive moves, with EA
adopting it. Not urgent while EA's Postgres-only assumption holds, but worth doing before EA
needs a SQLite fallback path RE has already solved.

---

### Data model & naming

#### `Project` means three different things in `registry.py` (four counting EA's tables)

A single registered repo (`Project`, `projects` — `registry.py:35-58`, `:441-464`), a grouping of
repos (`ProjectGroup`, `group_slug`, `project_groups` — `:26-31`, `:482-488`), and an intra-repo
subdivision (`subproject_path`/`parent_slug` — `:52-53`, a genuinely different concept that must not
be swept up in a rename). The existing workaround is the standing rule to *always* write "Egeria
Project" and never bare "Project" (`docs/discovery-automate-project-context-plan.md:215-220`).

Proposed: `Project` → `Repo`/`Resource`, `ProjectGroup` → **`Owner`** (not `Org` — GitHub's model is
an owner of type `User | Organization`, and plenty of repos live under a person). Scope, cost and the
API-path fix are in `docs/investigation-framing-design.md` §7.

**Tripwire, before anyone runs a regex sweep:** the registry is shared PostgreSQL
(`config.py:242-248`), not the SQLite `data/registry.db` suggests (0 bytes, stale), and Egeria
Advisor reads RE's tables cross-schema by hardcoded string — `advisor/re_code_symbol_reader.py:22`,
`advisor/agents/code_intel_agent.py:34-35`, `advisor/rag_retrieval.py:272-273`,
`advisor/analytics.py:237`, `advisor/re_code_scope.py`, `advisor/agents/tools.py:90`, all naming
`resource_explorer.project_code_symbols` / `project_code_relationships`. Renaming those tables leaves
EA compiling cleanly and failing at runtime. Either leave them alone or fix all six call sites in the
same commit.

---

## Closed

Kept rather than deleted: a recorded negative — *we checked, and it genuinely isn't there* — is what stops the next person re-investigating. Three entries were re-derived from scratch on 2026-08-24 because nobody could tell a closed question from an unasked one. Entries here are fully closed; anything still carrying live work stayed above, however its heading reads.

#### ~~`project_dependencies` has no survey-step writer~~ — RESOLVED 2026-08-23

Closed by the `repo_manifest_parse` step (`sub_surveyors/manifest_parse.py`), which writes
`project_dependencies` from DependencyParser/CiWorkflowParser/RepoConventionsParser.

---

#### ~~`repo_classification` declares `fetch_cost="none"` and calls the GitHub API~~ — RESOLVED 2026-08-24

The feature was right, the declaration wrong. Cost is now declared from measurement, not the
dataclass default — see the comment on the `repo_classification` `StepInfo` in
`surveyors/repo_survey_definition_adapter.py`. `step_cost_observer.py` is what caught it and
is what stops the next one.

---

#### BUILT 2026-08-20 — a "no silent success" ratchet

`tests/test_no_silent_success.py`. Covers one of the four silent-failure classes above.

---

#### BUILT 2026-08-20 — live smoke tier + pinned error payloads

`tests/test_egeria_live_smoke.py`.

---

#### ~~HIGH — filesystem annotations never reach Egeria~~ — FIXED 2026-08-20

Suspected in `docs/survey-and-analysis-current-state-2026-08-19.md`, confirmed and closed.

---

#### ~~Automate had never notified anyone~~ — FIXED 2026-08-20

Two independent faults, both closed. Detection in `notification_detector.py`, delivery via
`scheduler.py`'s `_check_subscriptions()`.

---

#### ~~RFAs written by `log_rfa()` never reached the RFA drawer~~ — FIXED 2026-08-20

The drawer reads them via `GET /api/activity/rfas`; see `web/routes/activity.py`.

---

#### RE locally executing Survey Definitions — IMPLEMENTED 2026-07-07

`surveyors/survey_definition_executor.py` + the per-resource-type adapters.

---

#### ~~HIGH — populate `IR.ports` and `IR.wires`~~ — **BUILT 2026-08-23, entry was stale**

`surveyors/arch_recovery/interfaces.py` extracts them from Dockerfile `EXPOSE`, compose
`ports:`/`expose:`/`depends_on:` and OpenAPI documents. `propose()` is called from the product path
(`sub_surveyors/arch_recovery_detect.py`), `arch_recovery/persist.py` writes both as findings with
wires attributed to the **source** component, and `_renderDeploymentInterfaces()` renders them.
Egeria's `SolutionPortDirection`/`SolutionLinkingWire` vocabulary was checked first, as design §5.5f
asked — the third time that check was the right first move.

`ir.py`'s fields carried a `# not in this slice` comment for three weeks after that stopped being
true; corrected in place.

**This entry stayed marked HIGH after the work shipped**, which is worse than a missing entry — a
stale HIGH sends the next person to build something that exists. It is a class, not an incident:
finding 89 ("committed and regression-tested is not reachable"), finding 98 (merged, pushed and
live-verified is *also* not reachable), `recovery_gate`'s docstring citing `kubernetes/website` as
a repo it skips when it runs, and `repo_classification`'s declared cost. **The label is not the
evidence.**

**What is genuinely still open here is coverage and precision, not capability** — see the
architecture-recovery entry below. Ports and wires exist for the 16 repos recovery has actually
been run on, of the 46 the gate approves.

> Verified empty, and **nothing anywhere populates them**: both fields carry `# not in this slice`,
> §5.2's distillation steps 4 and 5 are unbuilt, and §3.2's `SolutionPortDirection` has never been
> written. `ApiStructureSurveyor` does not cover it — it counts symbols and module structure, which is
> internal shape rather than exposed surface.
>
> **Why it is the biggest gap:** everything black-box we have built reads metadata *about* a resource
> (README, docs, manifests, deployment artifacts), not the interface *of* it. The system can say "an
> application with deployment artifacts" but not "serves these endpoints, consumes this topic, needs
> these ports" — and the second is what "does it fit our infrastructure" means.
>
> **Why it is cheap:** interface evidence is largely black-box observable and often in artifacts
> already fetched — OpenAPI/Swagger, `.proto`, GraphQL schemas, compose `ports:`/`expose:`, Dockerfile
> `EXPOSE`, k8s `Service` manifests, declared entry points, configured topic names. Mostly no source
> parsing, so **Discovery tier by rule 17's own test**.
>
> Check Egeria's existing vocabulary first — `SolutionPortDirection` and `SolutionLinkingWire`'s
> `protocol`/`integrationStyle`/`frequency`/`dataExchanged`/`oneWay` already exist. Third time this
> check has been the right first move, after `SolutionComponentType` and `ResourceUse`.
>

---


---

### HIGH — interface extraction answers "does it expose something", not "can I use it"

**The driving question, from Dan 2026-08-24:** *"if we want to see if a repo is something we can
use during runtime, we need to know how to interface to it — what kind of API it has, maybe
language bindings, the number of commands. We don't need the names of every request and their
payloads/signatures — until we want to actually try to use it."*

That is a **suitability** question, and it wants a coarse answer.

**Items 1 and 2 below are DONE (`b1488be`, "RE: Milvus is gRPC-first and we could not see it")** —
recorded here so the next reader doesn't re-derive it, since this entry sat stale describing them
as open after they'd already landed. `interfaces.py` now recognises `.proto`/GraphQL SDL/Thrift IDL
alongside OpenAPI (`_PROTO_EXT`/`_GRAPHQL_EXTS`/`_THRIFT_EXT`), and `operation_count` (OpenAPI
`paths` × methods, `.proto` `service`/`rpc` counts) rides in each port's `additionalProperties`.
Milvus's gRPC surface — the case that motivated this — is no longer invisible.

**What genuinely remains open, sharpened by Dan 2026-08-30:**

**A. OpenAPI/REST/Swagger detection needs a second path — DONE for FastAPI, 2026-08-30, same
session.** `_OPENAPI_NAMES` only ever saw a *committed* spec file (`openapi.json`, `swagger.yaml`,
…); a FastAPI service generates its spec at runtime from its own route decorators and ships none —
this codebase's own web app was exactly that case, recording nothing.

Built as reuse, not a second detection: `code_markers.py`'s `fastapi-route-registration` rule
already matches individual `@app.get`/`.post`/`.put`/`.delete`/`.patch`/`.websocket` decorators —
one match per route, collected per-file for *component* classification
(`arch_recovery/rules/fastapi-route.yml`) — but the count was discarded once converted into a
component. `code_markers.propose()` now returns it as a 4th value, `{component slug: route count}`
(`OPERATION_MARKERS`, a named subset of rule IDs that are genuinely per-operation, not per-file),
threaded through `detectors.build_components()` → `arch_recovery_detect.py` →
`interfaces.propose()`'s new `code_marker_operations` keyword. `interfaces.py` emits an `HTTP/REST`
port from it for any component with a nonzero count **that has no port already from a static
document** — a checked-in OpenAPI file is stronger, filename-attributable evidence than a decorator
count, and both existing would report one REST interface as two, so the static-document reading
wins where both exist.

**Confirmed NOT free for Spring/Go, as flagged** — `OPERATION_MARKERS` has exactly one entry.
Spring's marker (`java-spring-service.yml`) matches `@RestController`/`@Controller` at the class
level, and Go's (`go-http-server.yml`, `go-grpc-server.yml`) match server *construction* — neither
is a per-endpoint marker, so adding their rule IDs to `OPERATION_MARKERS` would count "1" regardless
of how many routes exist. Getting the same countable granularity for Spring needs a new rule on
`@GetMapping`/`@PostMapping`/`@RequestMapping`-family method annotations; for Go it needs rules on
whichever router's per-route registration call (`mux.HandleFunc`, gin's `.GET`, echo's `.GET`, …) a
given service actually uses. Left as a clearly-scoped follow-on, not attempted here.

Suite: `test_arch_interfaces_idl.py` +5 (the reuse, the static-document precedence, the no-owner
skip, the zero-count skip, and backward compatibility with no `code_marker_operations` passed),
`test_arch_recovery_detectors.py` +2 (the count itself, and that a subtree with no route decorators
is absent rather than zero). 214 passed across the directly affected files; 503 passed across the
broader arch/interface/marker test surface.

**B. Language bindings — Dan's steer narrows this from the original proposal, doesn't confirm it.**
The entry as written proposed conventional directories (`clients/<lang>`, `sdk/<lang>`,
`bindings/`) as the signal, and called it "weakest evidence of the three; do it last." Dan, 2026-08-30:
*"Not sure about language bindings unless they are exported as a specific library — eg. pyegeria."*
That rules the directory-convention approach out rather than deferring it — a folder named
`clients/python` is not evidence a real, usable client library exists at that path, and the
codebase's own `_deployment_context_of`-style principle (read a declared boundary, don't infer
intent from a name) argues the same way here.

What Dan's example asks for instead: recognise a **named, published package that IS a client
library for this project** — `pyegeria` is a real PyPI package, with its own name and description,
that exists specifically to bind to Egeria. That is verifiable evidence a directory name is not.

**DONE, first cut, 2026-08-30, same session — Python and Node only.** Not `manifest_parse.py`/
`DependencyParser` in the end (that pipeline belongs to a different survey step, `ManifestParseSurveyor`
via `IngestionPipeline`, which `architecture_recovery` doesn't depend on and shouldn't couple to) but
the *same kind* of parsing the entry anticipated, on the surface that was already free:
`detectors.python_manifests()`/`node_manifests()` already read `pyproject.toml`'s `[project]` table
and `package.json` wholesale for `classify()`'s "installable, no entry point ⇒ Software Library"
signal — `description` was sitting in the already-parsed structure, unread. One field added to
each, no new file walk, no new parse.

**Deliberately NOT a classifier.** `build_components()` now attaches a second Evidence entry to any
component `classify()` already calls `"Software Library"` (installable, no entry point — exactly
pyegeria's shape) that has a non-empty `description`: the description, verbatim, up to 200 chars,
assertion `"publishes a {ecosystem} package — possible language binding"`. Nothing here decides
*whether* it's a binding — pyegeria's own description ("A python client for the Egeria metadata
management system") needs no inference to read as one, and that restraint is the same one `protocol`
already exercises by staying empty rather than guessed from a port number. A package with no
description, or with an entry point (a CLI, not installable-as-a-library), gets no binding evidence
at all — nothing invented to fill the gap.

**Directory-convention detection (`clients/<lang>`, `sdk/<lang>`, `bindings/`) was NOT built**, per
Dan's steer ruling it out rather than deferring it.

**Real scope limits, stated rather than discovered later:**
- **Java (Maven/Gradle) and Go are not covered.** `python_manifests`/`node_manifests` are the two
  existing readers with a clean `name`/`description` shape to extend; `pom.xml` isn't parsed into a
  dict at all today and Gradle's `settings.gradle` module list has no description field to read.
  Real follow-on work, not attempted here.
- **Single-repo only, and this is the sharper limit.** `pyegeria` is Egeria's binding but lives in a
  *different* repository (`egeria-python`) from Egeria's own server code. Analysing the Egeria server
  repo alone will never surface pyegeria as evidence — this only finds a binding a repo publishes
  *of itself*, e.g. running this against `egeria-python` would find pyegeria's own self-description.
  Cross-repo binding discovery (recognising that some OTHER analysed repo is a stated dependency of
  and/or names the analysed one) is a different, larger question, not scoped here.
- **Not yet surfaced in the curator-facing card.** The evidence is persisted and readable
  (`_architecture_recovery_results`'s per-component `evidence` list already carries it, same generic
  path every other Evidence record takes through `persist.py`), but `_archRow`'s summary line shows
  only `proposed_by` (detector labels), not evidence text — a curator has to look past the summary to
  see the description. A presentation follow-up, not a detection gap.

Suite: `test_arch_recovery_detectors.py` +4 (an installable package with a description gets binding
evidence; a console-command package does not; a bare name with no description does not; Node
packages are covered too). 207 passed across the directly affected files.

**Do NOT** extend either A or B into reading request/response schemas or binding call signatures.
That is stage two, a different cost tier, and the driving question explicitly excludes it.

---

### HIGH — summarising microflows: the mechanism is Egeria's, and RE discards it

**The gap** (finding 101a, and the reason both open precision problems look unsolvable): *nothing
owns summarising up*. Every microflow emits at its own natural granularity and no step collapses it
to the depth the question asked for. Milvus yields 154 components where its own authors say eight,
and 296 rpcs where the number a reader wants is `proxy.proto`'s 18.

Dan's framing: *"we can certainly create microflows that aggregate, summarize and transform
information collected from established results — and include them where needed, or standalone."*

**The correction that matters, and it is the whole point of this entry.** The first version of this
proposal invented a new `requires_results` declaration to sit alongside `requires_resources`, on the
claim that "nothing declares a data dependency between steps." **That claim is false**, and the
proposal would have been a third vocabulary for something Egeria already models. From
`0462-Governance-Action-Processes`:

```
GovernanceActionExecutor         requestType, requestParameters,
                                 requestParameterFilter, requestParameterMap,
                                 actionTargetFilter, actionTargetMap
GovernanceActionProcessFlow      guard, requestParameters
NextGovernanceActionProcessStep  guard, mandatoryGuard
TargetForGovernanceAction        actionTargetName
```

A completing governance service *"optionally supplies one or more guards **and a list of action
targets** for the subsequent governance action(s) to process"* (concepts/governance-action-process).
So step-to-step data flow is modelled, **named** (`actionTargetName`), **filterable**
(`actionTargetFilter`, `requestParameterFilter`) and **rebindable** (`actionTargetMap`,
`requestParameterMap`). Not merely passed — bound.

**So a summarising microflow is not a new kind of step.** It is an ordinary step whose **action
targets are the findings of prior steps**, with `requestParameters` carrying the depth or
summarisation level. That also gives Purpose (investigation-framing §3) a real home: depth of
response is a request parameter on the flow, not another new concept.

**What is genuinely missing is RE-side: it parses the model and throws it away.**

| Mechanism | State in RE |
|---|---|
| Additional Properties (`executes_at`, `re_analysis_step`, …) | *"parsed but not interpreted here"* — `survey_definition_reader.py:18` |
| `guard` / `mandatoryGuard` | round-trip on every link; a live read returns `guard: 'Any'` on all 9 links of Analysis Survey — **"the reader receives them and discards them"** |
| Branching | `UnsupportedSurveyDefinitionError` — *"v1 only supports linear step sequences"*, deferred by decision 2026-08-21 |
| Action targets / request parameters | not read at all; `SurveyStep` has no field for either |
| The specification itself | *"RE consults no Egeria specification at all. `STEP_REGISTRY` is a specification living in Python."* |

`requires_resources` is RE's parallel invention for a *different* problem — sharing an expensive
external resource (a zipball, a clone) across steps in one run, which is what `trellis-microflow`'s
`resolve_resources` solves. It is not a data dependency and should not be extended into one.

**Proposed work:**

1. **Read what is already received.** Add action targets and request parameters to `SurveyStep`,
   and stop discarding guards. No new vocabulary — these are attributes the reader already fetches
   and drops on the floor. Smallest possible first step, and it makes the rest measurable.
2. **One summarising microflow, as an ordinary step**, whose action targets are the
   `architecture_recovery` findings of a prior step and whose request parameter is the depth. Prove
   the shape on the case that motivated it: 154 components → "N subsystems, M services, one gRPC
   surface".
3. **Then decide about branching**, which is the deferred v1 boundary and the real work.

**Two constraints, both from failures already recorded here:**

- **A summariser whose inputs are absent must not emit an empty summary.** It must produce
  `not_established` / `SKIPPED_BY_DESIGN` with the reason, exactly as `recovery_gate`'s skip does.
  A confident summary of nothing is the absence-looks-like-zero shape (findings 63, 90, 97, 99, 100)
  promoted to the composition level, where it is *harder* to see because the output looks like a
  real answer.
- **Check the Egeria model before inventing a local one.** This entry exists because that check was
  skipped once here, having paid off three times and produced one useful negative (`ResourceUse`,
  §5.5d-i) the same day. The pattern of the miss is worth more than the miss: the vocabulary check
  was performed for the *port count* an hour earlier and not for *step composition*, because the
  answer there had already been assumed to be local.

---

### Doc-site located but unreadable → offer to ingest it, and ask while a human is there

**Dan, 2026-08-25:** *"there is an opportunity to ask the user if they want to ingest the
documentation web site (or portions of it) into the vector store to support deeper analysis — this
would likely fall into the understanding stage and might surface as a RECOMMENDATION for future
analysis... Remember that we have the chat interface to design with, and that supports us asking
questions (as long as we aren't doing a scheduled survey). We shouldn't be too chatty but we do want
to take advantage of interactive sessions."*

**The capability already exists; the connection does not.** `repo_website_ingestion` ingests a
project's documentation site into pgvector "so Chat and Understanding can answer from the project's
own documentation rather than only its source tree" — keyed on the site's host so several repos in
one project share one collection, and skipping sites the repo builds itself. That is precisely the
proposal. What is missing is that **nothing ever suggests running it**, and measured:

```
repos with website_ingestion findings          0 of 60
repos where repo_arch_lens found a doc-site     2   (sqlglot, unitycatalog)
   ...both with an empty `homepage`, so the step could not run today anyway
```

So there are three distinct gaps stacked, and only the first is new work:

1. **No recommendation link.** `repo_arch_lens` produces `doc-site` — located, and explicitly *not
   readable from here*. That is the single most actionable negative result in the chain: we know a
   document exists, we know where, and we know we cannot use it. It should surface as a
   **suggested action** (`github/suggested_action.py`) pointing at `repo_website_ingestion`, not as
   a note in a JSON blob.
2. **`homepage` is empty** on both doc-site repos, so `repo_website_ingestion` has nothing to
   resolve. Whether that is a `repo_homepage` gap or genuinely absent upstream metadata is
   unmeasured.
3. ~~**The step has never run anywhere.** Zero of sixty.~~ **WRONG, corrected 2026-08-25.** It has
   run, on 6 of 60. It writes **metrics and never findings**, and the claim came from a
   findings-only query:

   ```
   website_ingestion   findings: 0 of 60      <- what was measured
                       metrics:  6 of 60      <- what exists
   ```

   The real defect was different and larger, found by the presentation session: on the other 54 the
   results reader returned `chunks/pages_fetched/pages_found/pages_failed` as 0, and `metrics`
   render mode lays every key out as a labelled row — so 54 cards read *"we scanned the site and
   found nothing"* about a site nobody had ever looked at. `result_status.NEVER_RUN` already
   describes the correct behaviour and nothing was emitting it. Fixed in `eeb5363`, along with a
   second instance the same guard immediately found in `rag_ingestion`.

   **The transferable error is mine and it is now three-for-three.** `query_findings(slug, kind)`
   defaults to `scope_locator=""`, and a step may write metrics rather than findings. So a bare
   findings query establishes *"nothing at whole-resource scope in the findings table"* — never
   *"this never ran"*. It has produced a wrong published number three times in two days:
   architecture recovery read as 3 of 46 when it was 16; this entry read as 0 of 60 when it was 6;
   and the verification script written to check *this very correction* reported
   `architecture_doc_lens` findings as 0 while 36 labels sat in it, scope-keyed.

   **A count is not an absence unless the query covers every shape the answer could take.**

**The interactive-question point is the reusable part, and it is a design constraint we have not
written down anywhere.** RE has a chat interface, so an interactive session *can* ask. A scheduled
survey cannot: there is nobody there, and a step that blocks on an answer would hang a cadence.
Both must be true of the same step. The shape that satisfies both:

- **Interactive** → ask, once, at the point the evidence appears ("this project's architecture
  documentation is at `<url>` and I cannot read it from here — ingest it?"). One question, at the
  moment it is answerable, is not chatty; a checklist of them is.
- **Scheduled / unattended** → emit the recommendation and move on. RFA already exists for exactly
  this, and `suggested_action`'s `next_step` field already distinguishes `rfa` from `subscription`.
- **Never** → block, retry, or ask again on the next run. An unanswered recommendation is a
  standing offer, not an open question.

That distinction is worth stating in the design docs independently of this feature, since every
future step that would benefit from a human answer meets it. **Understanding is the right stage**
(Dan's read): the ingested site serves Chat and cross-resource questions, which is what Understanding
is for — not Discovery, where it would look like another survey step.

**Not started.** Sized as small-but-not-trivial: item 1 is a link between two existing subsystems,
item 2 needs a measurement first, item 3 is a live-verification pass on a step nobody has run.

---

### Stage and profile a documentation site before deciding how to ingest it

**Dan, 2026-08-25:** *"what are your assumptions as you make an ingestion? Do we need to do some
pre-analysis first, and perhaps internally stage the content and then profile it before we decide
how to ingest it?"*

Asked after three ingestion defects in one session. The honest answer is that ingestion currently
**fetches, chunks and embeds in one pass with no decision point**, and every assumption below is
made implicitly — none is checked, and none is visible in the result.

**What `repo_website_ingestion` assumes today, read out of the code:**

| # | Assumption | Where | Observed failing |
|---|---|---|---|
| 1 | The homepage URL is the documentation site | `repo_homepage` fallback to manifest/README | badges, registries, another project's docs — 10 of 60 (finding 108) |
| 2 | A sitemap (or the landing page) identifies the right pages | `discover_pages` | milvus: 400 sitemap URLs, **every fetch failed** |
| 3 | The pages can be fetched by a plain HTTP client | `self._fetch` | milvus.io 302-loops without a browser-like client |
| 4 | Tag-stripping yields useful text | `_extract_text` | untested against JS-rendered sites; a client-rendered page yields an empty string, indistinguishable from a page with no content |
| 5 | One chunk size fits all of it | `web_docs` type: 384/48, fixed | an API reference and a narrative guide are not the same shape; `api_reference` exists as a separate type and is never selected for a website |
| 6 | Every discovered page is worth embedding | no relevance filter | the sibling-website case: navigation, marketing and blog pages embedded as documentation |
| 7 | The site is one version | none | versioned docs sites embed N copies of the same page, splitting retrieval across them |
| 8 | The content is not already held | `self_published` check only | that check catches a repo building its own site; it does not catch overlap with another repo's already-ingested content |

**Assumptions 2–4 are the same failure**, and it is the expensive one: 685 seconds spent on milvus
producing nothing, discovered only afterwards. **Nothing in the current design can fail early**,
because there is no point between "we have a URL" and "we have embedded it" at which anything is
inspected.

**What a stage-and-profile step would answer**, in the order the cost rises:

1. **Is it reachable at all, and by us?** One fetch of the landing page. Would have ended the milvus
   run in under a second instead of 685.
2. **Does text come out?** Extract from a handful of pages and measure. A site that yields 40
   characters a page is client-rendered and needs a different fetcher — or is honestly out of scope,
   which is a fine answer if it is *stated*.
3. **What kind of documentation is it?** API reference, narrative guide, blog, marketing. This
   selects the chunking profile, and the collection types for it already exist and are never chosen.
4. **How much of it is boilerplate?** Nav, footers and sidebars repeat on every page; measuring the
   repeated fraction before embedding says whether the ingest is mostly chrome.
5. **Is it versioned, and is anything already held?** Both are duplication, and both split retrieval
   rather than improving it.

Only then decide **whether** and **how** to ingest — rather than ingesting and finding out.

**Why this is worth building rather than adding more guards.** Finding 108's guards fixed the
*input* (is this URL plausibly this project's docs). Everything above is about the *content*, which
no URL check can reach. And the pattern is one this codebase already trusts: architecture recovery
is exactly stage-then-decide — cheap classification gates the expensive tier — while ingestion has
no gate at all.

**Design constraints, from what already went wrong:**

- **Staged content must be inspectable before it is committed.** The value is the decision point,
  not the caching.
- **A profile that says "do not ingest" is a result, not a failure** — with its reason, renderable
  the way `skipped_by_design` is. Three of today's defects were a system being right and recording
  it in a way that read as being wrong.
- **Do not add a boolean beside the outcome.** `detail["ingested"]` was hardcoded `True` while the
  `StepOutcome` next to it correctly said the site was never read, and downstream code read the
  boolean. A profile with a `usable: true` flag would repeat that exactly.

---

## Export findings/metrics for use outside RE

**Raised 2026-09-01**, after a Committed Secrets run reported 48,581 matches and the drawer took
minutes to render an incomplete list. Dan: *"there should probably be a separate report that is
downloadable - maybe a csv that contains all these details. They aren't useable in the raw in
Results."* Agreed as worth doing, deliberately **not** built the same day, because fixing the
scan's own defect (`docs/` — the ruleset's per-rule entropy/allowlist/stopword gates were never
read) took that repo from 48,581 rows to 5, which removed the urgency and changed what the
feature is for.

**Build it once, on the two generic tables — not per survey.** `project_analysis_findings` and
`project_analysis_metrics` already reduce every analysis kind to two shapes, so an export hung
off those means each current *and future* kind gets it from its `AnalysisKind` registration.
The alternative — an export per analysis — is ten places to drift, the same argument that
produced the registry in the first place.

**The requirement that makes this non-trivial: an export must not be able to lie more
confidently than the screen it replaces.** A file reads as complete; there is no scrollbar to
suggest otherwise, and it travels — into a ticket, a spreadsheet, someone else's inbox — long
after the run that produced it. Two specific hazards, both of which this codebase has already
been bitten by in other forms:

- **Truncation must be self-evident.** A 200-row export of a 48,581-row result is worse than a
  truncated page. The row count as the *source* reports it, and any applied filter, belong in
  the artifact.
- **Provenance must travel with the rows.** Analysis id, `surveyed_at`, provider name and
  version (ruleset commit, tool version), the coverage denominator (files scanned vs excluded),
  outcome status and self-test result. The 2026-09-01 episode is the argument: the count was
  wrong by four orders of magnitude *and the provenance line was impeccable*. Stripping that
  metadata into a bare CSV is how a careful finding becomes a confident spreadsheet.

**CSV and JSONL, and the reason is honesty rather than choice.** Findings carry a nested
`detail_json`; flattening it to CSV loses information, so CSV-only is the same
"looks complete, isn't" problem one layer down. CSV for the columns people actually paste into
a spreadsheet; JSONL when they need everything.

**Two things this is explicitly not:**

- **Not a substitute for a render cap.** The 48,581-row page was the bug; an export does not fix
  it. A user must never be able to get an incomplete screen that does not say so. That is a
  separate, smaller change and stands on its own merits.
- **Not the same as publishing to Egeria.** RE already has that path, and it serves the catalog.
  Export serves humans and external tools — a ticket, a review, a vulnerability tracker. Naming
  the distinction here so the item is not later closed as "we already have publish".

**Trigger for picking it up:** a second analysis with a real external workflow. `secret_scan`
post-fix yields 5 rows on egeria-python and makes no case by itself; `dependency_analysis`
produces ~880 rows on amundsen and feeds license/SBOM review, which does. If that is the
trigger, it argues for the generic build from the start rather than a one-off.

---

## Outbox: unbounded enqueue, and no way to cancel queued work

**Both found 2026-09-01**, when a pre-fix Committed Secrets run queued ~48,500
Egeria writes and the console filled with 409s. The 409 itself is fixed (a
duplicate `qualifiedName` now means "already created", not "failed" — see
`egeria_outbox.apply_element`). These two are not.

### 1. One Egeria element per finding, with no cap

`enqueue_annotations` writes one outbox row — and therefore one catalog
element — per annotation. The secret scan produced **48,583 findings in a
single run**, so 48,583 elements were queued for one repo. Two runs of it left
**48,113 rows pending**, and **9,164 had already been written into Egeria**
before the drain was stopped.

The ruleset fix takes egeria-python from 48,581 matches to 7, so this does not
bite today. It is still unbounded: a genuinely noisy repository, or a rule
regression like the one that caused this, floods the catalog with no limit and
no warning. Nothing in the enqueue path knows how large a batch is.

Worth considering together, not separately:

- **A cap with a stated remainder**, the same discipline `_FINDING_LINE_CAP`
  already uses: publish N, and say plainly that M were not published. A
  silently truncated catalog is worse than a capped one.
- **Summary-plus-evidence rather than one element per match.** The
  `AnnotationExtension` linking shipped in Phase 2 is exactly this shape — one
  aggregate annotation with per-item evidence beneath it — and a scan whose
  output is inherently list-shaped is its natural second consumer.
- **A size check before enqueue, not after.** By the time 48,000 rows exist,
  the decision has already been made.

### 2. No purge path for queued work

`registry.purge_outbox_completed()` deletes `done` rows past a retention
window, and deliberately nothing else: *"'dead' rows are the ones a human still
has to look at, and failed/pending rows are live work."* That reasoning holds
for one stuck row and fails for a batch queued in error.

Cancelling the 48,113 rows needed a hand-written `DELETE` against
`egeria_outbox`, reviewed statement-by-statement, with the count printed first
— and that mattered: the first statement matched **39,603 of 48,113**, because
two buggy runs were queued rather than one. Printing the count is the only
reason 8,510 bogus annotations were not left to publish on the next restart.

What is missing is a supported way to say "cancel this batch": a
`cancel_outbox_batch(run_id=...)` or `(entity_slug, before=...)`, which
reports what it matched before doing anything, and marks rows `cancelled`
rather than deleting them so the record of the mistake survives. `run_id`
already exists on the table and is already used by `claim_due_outbox_elements`
— the identifier for "this batch" is there and unused for this purpose.

**Why this is worth building rather than repeating by hand.** Queued work that
turns out to be wrong is not exotic: it is the normal consequence of finding a
bug in something that already ran. Twice in one day (this, and the 48,581-row
render) the answer to unbounded output was a hand-written statement against
live data. That is the part to fix.
