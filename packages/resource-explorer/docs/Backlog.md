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

**1. Phase 2 — Egeria projection of recovered architecture.** The stated end goal, and the
only major piece unbuilt: **nothing from architecture recovery reaches Egeria.** Its one
remaining prerequisite is **outbox/retry publishing** (design §8.4) — a blueprint writes far
more elements per run than anything currently published, and the design is blunt that *"a
half-published blueprint is worse than none."* Its other prerequisite is now done: projection
has a hierarchy to collapse (finding 117, milvus 204-at-every-depth → 82/142/216/221).

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

#### HIGH — take architecture results into Curate and actually work with them

*(Opened 2026-08-30. Dan: "we're going to want to take these results and into Curate to start to
work with the information".)*

Everything so far **produces** an architecture reading and **displays** it. Nothing lets a person
*act* on it. Curate is where sustained human attention lives (tags, feedback, curator notes), and
the architecture card is now good enough to be worth curating rather than only reading:
`egeria_git` presents 8 deployment components instead of 451 mixed rows.

What "working with the information" plausibly means here, in rough order of value — **none of this
is designed yet, and the first task is deciding which of these is actually wanted:**

- **Accept / reject / retype a proposed component.** The whole pipeline is explicitly a *proposal*
  (§4.1a, `report-then-curate`), and a curator's verdict is the missing half. Note this is the
  Confidence/ContentStatus axis (§3.3b/§3.4), not a new vocabulary.
- **Correct a name.** Live example worth keeping: the disambiguator renamed Atlas' main
  distribution config to `distro` because six modules shared the token `atlas` — unique and
  truthful, but not what a curator would choose, and no rule can know which member of a collision
  deserves the shared name.
- **Curator notes against a component scope**, not just the whole resource. `resource_curator_notes`
  is whole-resource today; architecture recovery is scope-keyed throughout.
- **Promote a reviewed set toward publication** — the ContentStatus ladder that
  `report-then-curate` describes and nothing yet walks.

**Two things already in place that this should reuse rather than reinvent:** withdrawal
(`WITHDRAWN_LABEL`) already expresses "this is no longer proposed" durably and reversibly, and the
decision trace (`architecture_decisions`) already records why a component looks the way it does —
which is exactly the context a curator needs before overriding it.

**The constraint to hold:** a curator's verdict is *evidence of a different kind*, not a rewrite of
what the detectors said. §4.2's "map, never merge" and the doc-lens rule ("a document that disagrees
with the code is a finding, not a correction") both point the same way — the disagreement is the
valuable artifact and must stay legible.

#### HIGH — `architecture_recovery` is tagged `run_time: fast` and measures 100s+ — needs a ruling

*(Opened 2026-08-30. Measured, then deliberately left unchanged: fixing it re-opens a maintainer
ruling rather than being a data fix.)*

Measured via `POST /analyses/architecture_recovery/run`:

| repo | time |
|---|---|
| `egeria_git` | 89s |
| `egeria_python_git` | 100s |
| `docling_parse` (**one** component) | 321s cold / **111s warm** |

CLAUDE.md rule 17 justifies this analysis sitting in the Discovery tier on
`architecture-recovery-phase1-findings.md` §3's **"5.3s per repo"**. That figure was the *spike
toolchain*; this step additionally downloads a zipball and does a treeless clone per run. The warm
re-run isolates it: ~200s is fetch, and **111s of work remains** on the smallest repo in the corpus.

**Two consequences of the current `fast` value**, both live:

1. The card badges it *fast* and `_runAnalysisCatalogCard` neither prompts nor backgrounds, so 100s+
   of blocking work is announced only by a toast — the entry below.
2. `AnalysisCatalogEntry.availability` **derives** from `run_time` (`fast` → `inline`), so a context
   compile is told it may run this **on the hot path** — inside a packer whose §20 says in bold
   *"the packer must never trigger a survey."* Latent only because the compiler is unwired
   (task-list item 10), and it becomes real the moment it is not.

**Why it was not simply corrected.** Setting `run_time: minutes` is right on the measurement and
immediately fails
`test_no_fast_stage_question_is_answered_by_a_non_fast_survey_analysis`, because Discovery is a
fast-only stage and a Discovery question ("What is its internal architecture?") dispatches to it.
That test is correct and the failure is informative: it says the analysis no longer fits the tier it
was placed in on 2026-08-22 by maintainer ruling. The options are a maintainer's, not an
implementer's:

- **re-tier** the analysis out of Discovery (contradicts the 2026-08-22 ruling, and rule 17's
  "cheap enough to gate the expensive tiers" test now genuinely fails on measurement);
- **re-map** the Discovery question to something cheaper and let architecture recovery answer a
  slower-stage question;
- **make it actually fast** — the 111s warm figure has never been profiled, and a one-component repo
  taking that long suggests something pathological rather than inherent;
- **decouple `availability` from `run_time`**, which §20 explicitly argued against ("a second
  hand-maintained column would be one more thing to keep consistent with the first") but which the
  above shows is now carrying two loads that have come apart.

The measurement is annotated in `analysis_catalog.yaml` beside the value, so nobody reads `fast`
without seeing that it is known-questionable.

**Profile first.** 111s on a repo with one component is the number that would change the whole
entry, and nobody has looked at where it goes.

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

---

### Platform & orchestration

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

That is a **suitability** question, and it wants a coarse answer. Measured against what
`arch_recovery/interfaces.py` extracts today:

| The question | Answerable now? | Why |
|---|---|---|
| Does it expose an interface at all? | **yes** | Dockerfile `EXPOSE`, compose `ports:`/`expose:` |
| What kind of API? | **partly** | an OpenAPI filename ⇒ `HTTP/REST` |
| Is it gRPC? | **no** | `.proto` is not recognised. Nor GraphQL, nor Thrift |
| How many operations/commands? | **no** | the OpenAPI document is matched by **filename** and never opened |
| What language bindings ship with it? | **no** | nothing extracts them |

`propose()`'s own docstring says it works "from deployment artifacts only", and `_OPENAPI_NAMES`
is a six-entry filename tuple. So for **Milvus** — gRPC-first, SDKs in several languages — we
record that it exposes ports and miss its actual interface entirely.

**The general principle this exposes, and it is bigger than the gap.** A coarse answer often
requires a *deeper* analysis that is then summarised. "REST, ~40 operations, Python and Go
bindings" means opening the OpenAPI document and scanning for binding directories, then reporting
three facts rather than forty signatures. **Today we do neither half**: no deep read, and no
summarisation step. What we emit instead is the raw analysis at its own natural granularity —
154 components for Milvus (finding 99) — which is not a precision failure so much as a missing
summarisation level.

This reframes the two-stage funnel that already exists. *"First determine if it's suitable; if so,
later analyse the details to use it properly"* is Discovery → Analysis, and rule 17's
`fetch_cost`/`compute_cost` already draws the cost boundary. What is missing is that **no step owns
summarising up to the depth the question asked for.** Every surveyor emits at its own granularity
and nothing collapses it.

**It also enlarges Purpose's role (§3 of the investigation-framing design).** If Purpose sets the
required *depth of response*, it selects a summarisation level, not just a question ordering — and
the same underlying analysis then serves both stages. A summariser over 154 components ("3
subsystems, 8 services, one gRPC surface") answers the suitability question **without the component
list needing to be correct at 8**, which is a materially cheaper path than the unported adjudicator.

**Proposed work, cheap first:**

1. **Recognise `.proto`, GraphQL SDL and Thrift IDL** alongside OpenAPI. Filename/extension
   matching, same tier, no new fetch. Fixes the Milvus-shaped blind spot where the primary
   interface is invisible.
2. **Open the interface document and count.** OpenAPI `paths` × methods, `.proto` `service`/`rpc`
   declarations. A count is a summary, not a listing — the signatures stay unread until stage two,
   exactly as the driving question asks. Note the existing `_port_dict` has no field for it, so
   this needs one (`operation_count`, or a `SolutionPort` property if Egeria has one — **check the
   vocabulary first**, as §5.5f asked and as has paid off three times).
3. **Language bindings** — conventional directories (`clients/<lang>`, `sdk/<lang>`, `bindings/`)
   plus per-ecosystem manifests. Weakest evidence of the three; do it last and label it derived.

**Do NOT** extend this into reading request/response schemas. That is stage two, it is a different
cost tier, and the driving question explicitly excludes it.

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
