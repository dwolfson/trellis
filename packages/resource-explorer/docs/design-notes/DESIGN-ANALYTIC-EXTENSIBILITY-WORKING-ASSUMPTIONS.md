# DESIGN — Analytic extensibility across Trellis and the Egeria Portal: working assumptions (2026-10-02)

**Status: brainstorm captured, nothing decided, nothing built.** From the
design session with the project owner, 2026-10-02. The owner's framing:
*users are going to want to add and modify their own analytic steps within
surveys; we need to run them, generate annotations from them, answer
questions about the results, and display results*, some through the Egeria
Portal's local dashboards, which use the report-spec mechanism, Dr.Egeria
and user-written analytics routines that are *also not properly
architected yet*. This note states the pieces, the working assumptions and
the requirements to fill in, so the inventory and the paper walkthroughs
that follow have something to check against. Assumptions may change; they
are explicit so the change is visible.

Related: `docs/Architecture.md` (the survey and query layers, the six table
families), `project_egeria_resource_explorer_redesign` (2026-08-06: shared
analytics materialised, not live-called), EA's report-spec redesign,
`DESIGN-FIND-AND-INTEGRATE-PURPOSES-AND-THE-DATA-LENS.md`.

## 1. Eight points, in two groups

A user-added analytic step touches eight things. Today RE wires most of
them by hand, per analysis.

**About the step itself**

| # | point | today in RE | the gap |
|---|---|---|---|
| 1 | **Declaration**: id, resource kinds, intent tier, prerequisites, cost, availability, what it produces | `analysis_catalog.yaml`; `executes_at`, `native_process_ref`, `requires_input` | the most complete part; not shared with EA or the Portal |
| 2 | **Execution**: where the code runs, who owns the process | three executors chosen per step: RE-local Python, Prefect, Egeria's engine host (Java) | no plugin protocol; adding a step means editing `surveyors/` |
| 3 | **Results contract**: what comes back | per-analysis shapes in `_store_results`; per-analysis readers in `facts.py` | the gap everything else falls into: absence versus zero is re-decided per reader |
| 4 | **Binding**: which questions a result answers, how a state is derived | `resource_questions.csv` → `analysis_ids` by hand | a new step needs a hand edit to be askable |
| 5 | **Presentation**: headlines, boards, charts, dashboards | /next per stage, Classic, EA report specs, Portal dashboards, each separately | four renderers, no shared data shape |

**About what happens to results**

| # | point | today | the gap |
|---|---|---|---|
| 6 | **Storage**: what is kept locally and for how long | registry rows per analysis; `board_summary` materialised; `survey_data` TEXT blobs | an ODS in effect, not by design |
| 7 | **Publication**: how results go back to Egeria as annotations | `EgeriaPublisher`, outbox with proof rows | per-analysis annotation construction; one-way by ruling |
| 8 | **Curation**: what a person may conclude or act on from a result | E3's observation states (proposed, confirmed, overridden, survey-now-disagrees); verdicts | nothing a user step can declare about its own proposals |

The second group is where the honesty rules live: storage decides whether
absence survives, publication decides what Egeria believes, curation
decides what a person may conclude. Keeping them out of the step keeps a
user-written step from deciding any of them.

## 2. Working assumptions

Each is stated so it can be argued with. A changed assumption gets a dated
line here, not a silent edit.

**A1. Python is the language of analytic and survey steps.** A SQL body is
allowed for database steps, because much database analysis is a query and
a SQL step can be reviewed as data. Java only for steps that must run
inside Egeria's engine host as survey action services. Dr.Egeria markdown
for declarations, never for logic. No fourth choice is in view.

**A2. Every step's output is typed annotations** in the Egeria annotation
vocabulary, which the Egeria leads are extending for the needs this work
uncovers. RE's requirement of the extension is small: a required
**envelope** on every annotation that distinguishes *measured*, *not
established* with a reason, and *not applicable*, plus a reference to the
run that produced it. Everything else in a type is domain-specific. RE's
Admin annotation-type registry becomes a cache of Egeria's types, not a
second list.

**A3. Declarations live in Egeria; code lives in versioned packages; results
live in the ODS.** Survey definitions, governance action types and
annotation types are Egeria elements already, and RE discovers native
surveys from there. Steps ship as Python packages exposing their steps
through entry points with a manifest; Java services as connectors. A user
adds a step by installing a package and registering its declaration; RE,
EA and the Portal see it through Egeria, not through each other's files.

**A4. The registry is an operational data store, by design.** Egeria holds
current state and lineage; the ODS holds every run so trending and
cross-resource analysis stay cheap; nothing is computed from Egeria's graph
that the ODS can answer. The ODS schema follows the annotation envelope,
one table family per annotation type, which is what the queued reader
consolidation wants anyway. EA and the Portal read the same Postgres.

**A5. Git holds declarations, code and dashboard definitions, never
results.** Steps as packages, report specs and Dr.Egeria documents as
markdown, dashboards as files: versioned, reviewable, deployable. One
further use: provenance. A result records the commit of the step that
produced it, so a changed step cannot silently reinterpret an old
measurement.

**A6. Steps run under an executor RE chooses, never inline in the web
process.** User code runs in the Prefect worker's environment, which is
the sandbox boundary; Egeria-hosted services run in the engine host.
Availability stays a declared field, not a derivation from cost.

**A7. Publication is one-way and idempotent** until the
source-of-truth-by-topology rule is decided (owner, 2026-10-01: local in
dev, Egeria possibly in production, RE when disconnected). Reads from Egeria
inform display with a provenance mark; they never overwrite local rows.

**A8. Curation actions are proposed from measured annotations only, never
from judgements, and a person confirms them.** A step may declare which of
its annotations are *proposable* and for which observation field; it may
not set a disposition, a classification or a verdict. The E3 observation
states are the model for every proposal.

*Amended 2026-10-02 (owner):* a curation action may also be proposed from a
**signed judgement** made at Enrichment. The rule above is about what a
*survey* may propose; a person's judgement is already a person's, so an
action that follows from it (sensitivity = PII proposes a confidentiality
classification, a governance zone, a retention rule) is a proposal with
clear provenance, "proposed from your sensitivity judgement · *date*", and
a person confirms it as with any other. A proposal may combine the two
sources, measured PII columns plus a confirmed sensitivity, and names both.
What stays out: a survey inferring the judgement itself, then proposing
from it.

**A10. There are two kinds of analytic function, and they need two names.**
A **step** measures a resource: it needs a credential and an executor, runs
asynchronously under RE's control, and emits annotations into the ODS. A
**routine** computes over data already collected, the ODS or Egeria, for a
presentation: it runs where the presentation runs, synchronously or near
it, and returns a result set or a figure, not annotations. "Analysis" is
not used for either, because RE's catalogue already means steps by it.
Steps may call routines; routines never call steps. A routine declared once
serves EA's report specs, the Portal's dashboard tiles and RE's boards.

**A11. The execution environment for both is a library, not a service.** One
shared Python runtime (a Trellis shared library) provides the data access,
reading the ODS, reading Egeria through pyegeria, reading annotations by
type, and the envelope types. It imports the same way from a plain Python
script, the Portal's apps and Trellis. Steps add the executor harness
(Prefect, the engine host) on top; routines need only the library. Which
means a routine written against a script today runs unchanged in a Portal
tile tomorrow, and the proof is that one routine is tested from all three.

**A12. Derived values are steps whose inputs are annotations, and their
envelope is inherited.** The owner's grey area (2026-10-02): scorecards and
other values derived from several steps or several surveys, and the ad hoc
questions people ask in chat. A scorecard is a **step** with no resource
fetch: its inputs are prior annotations, it is catalogued, repeatable and
stored, and it emits an annotation like any other. RE already has this
tier (the Discovery-tier zero-fetch analyses, `preliminary_fit`, the
licence classification), so the rule is a generalisation, not a new kind.
Three properties make a derived step honest:

- **Provenance**: the annotation names every input annotation and its run,
  so "scored 7 of 10" can be opened to the measurements behind it.
- **Envelope propagation**: a derived value computed from an input that is
  *not established* is itself not established, with the input named; it
  never averages a silence into a number. Partial inputs make a partial
  output, marked.
- **Perishability**: the derived annotation records the inputs' run times,
  so a newer input run marks it "inputs changed since computed", the same
  mechanism as E1's evidence snapshot on judgements.

A **chat answer is a routine**: computed on demand over annotations, with
an LLM in the loop, returning an answer with the provenance of what it
read, and stored nowhere. The bridge between the two is a person's act:
**"save as a question"** promotes an ad hoc answer to a declared routine,
and, if it should recur and be kept, to a derived step with a schedule.
What is stored and published is always a step's output; what is shown on
demand is a routine's; nothing crosses without a person saving it.

**A13. Context compilation is the shared resolver, and it already encodes the
envelope.** RE's compiled-context path (`context_compile.py`,
`trellis-context`; `docs/context-compilation-design.md`) turns a question
into a spec: the question catalogue's analyses become *sections*, stored
results become *candidates* resolved through the fact layer, and the packer
fits a budget and returns a **manifest** (what was packed, dropped, and
*missing*, with "never ran" kept distinct from "ran and found nothing") and
a **derivation** (why each section is there). A compile never executes a
step to fill a gap. In the terms of this note:

- The compiler is a **routine** (A10): it computes over the ODS for a
  consumer, returns a pack with provenance, stores nothing, and runs in the
  caller's process, which is why `trellis-context` is already a shared
  package and the natural core of A11's one runtime.
- Its resolver registry **is** the generic reader registry of R7. Sections
  bind to annotation types; candidates are annotations with their envelope;
  the manifest's "missing" is the envelope's *not established* surfacing at
  the pack. A user-added step that emits typed annotations bound to a
  question is compilable with no compiler change. That is the strongest
  argument for A2.
- **One resolver, three callers.** The chat packs for an LLM; a derived
  step (A12) resolves the same sections deterministically and emits an
  annotation; a dashboard tile or board resolves them for presentation.
  Section resolution is written once, in the runtime, and the three callers
  differ only in what they do with the candidates.
- **Identity and staleness.** The compile cache is keyed on investigation,
  purpose, intent and as-of time, never on perspective (the design's
  invariant). A step's version (A5) joins the candidates' identity, so a
  changed step invalidates every pack that carried its annotations; a
  derived annotation's "inputs changed since computed" is the same test at
  the step.
- **Report specs and context specs are siblings.** EA's spec lifecycle and
  cache-key discipline were the parts the compiler design borrowed; a report
  spec declares what to fetch for a tile the way a context spec declares
  what to pack for an answer. R15's routine declaration should be one spec
  model with two consumers, not two spec languages.

**A9. EA's report specs, user analytics routines and Portal dashboard tiles
are the same eight points with a different input.** A report spec declares
what to fetch; a routine is an executor over catalogue metadata rather than
over a resource; a tile is a renderer. One analytic-unit model across the
apps lets a Portal dashboard show RE's annotations and RE's boards show a
routine's output.

## 3. Requirements to flush out

Each needs an owner and a yes/no before architecture. Blank where unknown.

- **R1 Authoring.** How a user writes a step: a Python package with a
  manifest; a single file dropped in a directory; a notebook; a Dr.Egeria
  document naming a package. Which, and which first.
- **R2 Registration.** How a step becomes known: installed package scanned
  at startup; explicit register command; Egeria element created by the
  package. How a removed step is retired without orphaning results.
- **R3 Versioning.** A step's version on every result; what happens to old
  results when a step changes; whether two versions may coexist.
- **R4 Inputs.** What a step may read: the resource (with which
  credential tier), prior annotations, the ODS, Egeria, the network. How
  prerequisites are declared and resolved (the existing resolver).
- **R5 The envelope.** The exact required fields of the annotation
  envelope, agreed with the Egeria leads; how "not applicable" is
  distinguished from "not established"; how partial (◐ within credential
  scope) is carried.
- **R6 Binding.** Whether a question binds to annotation types plus a
  predicate, to step ids, or both; who may add a question; how a user step
  gets a question without editing the CSV.
- **R7 Readers.** One generic reader per annotation type, with the state
  derived from the envelope; what a step may add beyond that (a headline
  template, a unit).
- **R8 Storage.** ODS retention; whether raw outputs are kept beside
  annotations; the TEXT→JSONB migration; what trending needs per type.
- **R9 Publication.** Which annotation types publish by default; what
  needs a person's confirmation first; how a user step's new annotation
  type reaches Egeria's type registry.
- **R10 Curation.** Which fields a step may propose to; the proposal
  envelope; whether a step may propose a relationship (semantic
  assignment) or only a value.
- **R11 Presentation.** A generic renderer per annotation type for
  /next boards and the Portal tiles; what a step may declare about
  presentation (a chart kind, an ordering) without owning a renderer.
- **R12 Security.** Who may install steps; what a step may not do (write
  to the resource, publish directly, read other tenants' ODS rows); how
  secrets reach a step (never in its declaration).
- **R13 Cross-app.** Which of this is shared code (trellis shared
  libraries), which is RE's, which is the Portal's; how EA's report-spec
  model maps onto points 1–5.
- **R15 Routine declaration.** How a routine is declared and found: the
  report-spec mechanism naming a routine with parameters, or the same
  manifest as steps with a `kind: routine`. What a routine returns (a
  table, a figure spec, both) and how a renderer reads it.
- **R16 One runtime, three hosts.** The shared library's surface, its
  dependency footprint (pyegeria, psycopg, nothing heavier by default), how
  it finds the ODS and Egeria from each host (env, config, the Portal's own
  settings), and how a routine proves it runs from a script, the Portal and
  RE.
- **R17 Derivation.** How a derived step declares its input annotation
  types and the envelope rule it applies; how the chat's "save as a
  question" is declared and where the saved routine lives; what a
  scorecard publishes (the score, its inputs, or both) and under which
  annotation type.
- **R18 The resolver as runtime core.** What `trellis-context`'s resolver
  needs from the envelope and the ODS to serve all three callers (chat,
  derived steps, tiles); whether sections bind to annotation types today or
  still to analysis ids; what the manifest must carry for a derived step's
  provenance; how a step's version enters the cache key.
- **R14 Testing.** What a step author must supply: a fixture resource, an
  expected annotation set, and the absence case (the step on a resource
  where the thing isn't there), so the envelope is exercised before the
  step is installed.

## 4. What happens next, in order

1. **Inventory**, read-only, same method as the Classic-versus-/next
   parity table: every extension point as it exists today across RE, EA,
   the Portal and Dr.Egeria. Where declarations live, how executors are
   chosen, every result shape, how each presenter finds its data, what
   publishes, what proposes. Output: a table per point, with "not checked"
   where not checked.
2. **The envelope**, agreed with the Egeria leads, as a short spec with
   examples for three existing annotation types and one new one.
3. **Two paper walkthroughs**, before any code: one user-added survey step
   end to end through the eight points (candidate: a HazMat-term detector
   over column names and comments, which also feeds Find), and one
   user-written Portal dashboard tile over its results.
4. Then architecture, as a design note with the designer's drawings for
   the authoring and registration surfaces.

## 5. Open questions

- The first concrete user step and the first concrete tile, named by the
  owner; everything above is checked against them.
- Whether a SQL-bodied database step is a step kind of its own or a
  Python step with a SQL helper.
- Whether the Portal's report-spec mechanism becomes the declaration form
  for routines, or routines get the same manifest as steps.
- How much of this is Egeria's to standardise (annotation types, step
  declarations as governance action types) and how much stays Trellis's.
