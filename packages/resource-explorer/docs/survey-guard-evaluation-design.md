# Survey guard evaluation: what's verified, what exists, what's missing

2026-09-01. Scoped to `survey_definition_executor.py` honouring Egeria's guard
semantics on `NextGovernanceActionProcessStep` links. Written before any code
change, per instruction.

## 0. Summary

Egeria's guard semantics are **verified against the Java source** in §1 below —
they match what was reported, including the mandatory-guard join. But guard
*evaluation* already exists in this codebase, for the Prefect whole-definition
path (`prefect/flows.py`), built 2026-08-26 per
`docs/survey-model-and-engine-host-design.md` §4.5. What does **not** exist:

1. The **local fallback loop** in `SurveyDefinitionExecutor.run()` — the path
   that must keep working "indefinitely" per §4.6 whenever Prefect is off or
   unreachable — ignores the step graph entirely and walks the flat step list.
   This is the concrete, uncontested gap this task closes.
2. **No RE step runner emits a guard.** Every adapter's step function returns
   `{"annotations": [...]}` (or similar) with no `"guard"` key, so even the
   already-built Prefect guard-checker has nothing to evaluate against for any
   step that exists today, including `repo_refresh_plan`. Closing this needs
   per-adapter changes, and `repo_survey_definition_adapter.py` — the adapter
   `repo_refresh_plan` lives in — is off-limits (contended). **Not implemented
   here; recorded as the reason guards remain inert in practice even after
   this change.**
3. **`mandatory_guard` (the join) is dropped on the floor.** `build_plan()`
   reads `link.guard` but never `link.mandatory_guard`; nothing in RE
   implements "wait for every mandatory guard to arrive." A test named
   `test_a_join_waits_for_both_upstreams` exists but tests plain dependency
   ordering (two unconditional predecessors), not guard-mandatory join —
   verified by reading it (§3.3). **Not implemented here** — no live
   definition uses `mandatory_guard=true` yet (see §3.4), so this is a real
   but currently-dormant gap, named rather than fixed.

What I implemented: the local loop now plans via `survey_execution_plan.build_plan()`
and evaluates `guarded_by` the same way the Prefect path already does (§3.2's
divergence from true per-link semantics included, for consistency between the
two paths rather than fixing one and not the other). An unsatisfied guard
produces a `SKIPPED_BY_DESIGN`-shaped `steps_report` entry via
`result_status.skipped()`, not silence. See §4.

## 1. Egeria's guard semantics — VERIFIED against the Java source

Read directly:
`/Users/dwolfson/localGit/egeria-sandbox/egeria/open-metadata-implementation/common-services/generic-handlers/src/main/java/org/odpi/openmetadata/commonservices/generichandlers/EngineActionHandler.java`

**Which links fire — `initiateNextEngineActions`, lines 1905–1993.** For each
`NextGovernanceActionProcessStep` relationship from the step that just
completed:

```java
boolean validNextAction = (guard == null);
if ((guard != null) && (outputGuards != null)) {
    for (String outputGuard : outputGuards) {
        if (outputGuard != null && outputGuard.equals(guard)) {
            validNextAction = true;
        }
    }
}
if (validNextAction) { this.prepareEngineActionFromProcessStep(...); }
```

Matches the report exactly: a link with no guard always fires; a link with a
guard fires only if that guard is in the *previous step's own*
`outputGuards` (passed in as a parameter to this method, sourced from
`recordCompletionStatus`, lines ~1649–1748). **Every matching link fires
independently** — this loop does not require all guarded links out of one
step to agree; `validNextAction` is decided per-relationship, in the loop
body, and `prepareEngineActionFromProcessStep` is called once per match.

**The join — `mandatoryGuard`, lines 2019–2075 (`getMandatoryGuards`) and
440–521 (`runEngineActionIfReady`).** `getMandatoryGuards` collects, from
every `NextGovernanceActionProcessStep` link **incoming to a given step**,
the `guard` values where `mandatoryGuard == true` — this is gathered
per-target-step, across all its predecessors, not per-link. `runEngineActionIfReady`
then only calls `approveEngineAction` when:

```java
(mandatoryGuards == null) || mandatoryGuards.isEmpty()
    || new HashSet<>(receivedGuards).containsAll(mandatoryGuards)
```

`receivedGuards` (lines 471–512) comes from walking `NEXT_ENGINE_ACTION`
relationships already recorded *for this specific prepared engine action
instance* — i.e., guards already delivered to it by upstreams that already
ran. **Confirms the report precisely: `mandatoryGuard` is a join across a
step's incoming edges, evaluated on an already-*prepared* engine action, not
a branch condition on any single link.** A step can be *reachable* via a
plain (non-mandatory) guard match on one link while still being held from
*starting* until every one of its mandatory guards, which may come from
different upstream links, has actually arrived.

**Net semantics, restated precisely because the distinction matters for
implementation:**
- Per-link: `guard == None` → always fires. `guard != None` → fires iff that
  string is in the emitting step's own `outputGuards`. This is evaluated
  **per incoming link independently** (OR across links into the same step,
  when more than one link's guard is satisfied).
- Per-step (join): once at least one link has caused an engine action for
  that step to be *prepared*, it does not *start* until every mandatory guard
  declared on any of its incoming links has been received from its
  respective upstream. This can hold a step open across multiple upstream
  completions.

Verification method: direct read of the cited file/line ranges above, not
inference from Javadoc or comments. I did not find or read a second
implementation (e.g. a newer/OSS fork) — this is Egeria as checked out at
`egeria-sandbox/egeria`; I did not verify it is the exact version RE talks to
live, so treat the line numbers as "this checkout," not "all Egeria
versions." The mechanism (guard-string matching, mandatory-guard join) is
old and stable in this codebase's own governance-action-process model, so I
have moderate-to-high confidence it hasn't changed shape across versions,
but that is a belief, not something I verified.

## 2. What RE already has

### 2.1 `SurveyDefinitionReader` (`survey_definition_reader.py`)

Parses `processStepLinks[].guard` / `.mandatoryGuard` into `StepLink.guard`
/ `.mandatory_guard` (lines 780-790), and a step's own `producedGuards` into
`SurveyStep.produced_guards` (line 857) — the *authored declaration* of what
a step can emit, not an observation of what it did emit on a given run. Both
fields are read correctly; I did not change this file.

### 2.2 `survey_execution_plan.build_plan()` (`survey_execution_plan.py`)

Turns `SurveyDefinition.links` into a DAG (`ExecutionPlan`), with each
`PlannedStep.guarded_by: dict[upstream_step_key, required_guard]` built from
`link.guard` when it isn't `UNCONDITIONAL_GUARD` ("Any") — read at line 119.
**`link.mandatory_guard` is read from `StepLink` but never consulted here** —
confirmed by reading the whole function; there is no reference to
`mandatory_guard` anywhere in this module. So the plan the executor and
Prefect both work from structurally cannot express a join today — closing
this needs a schema change (`PlannedStep` would need e.g. a
`mandatory_guards_in: set[str]` computed per target step across all its
incoming links, not per upstream) beyond what this task's slice takes on.

### 2.3 `prefect/flows.py::run_planned_step_task` — the ALREADY-EVALUATED path

For a step with `guarded_by`, this task (lines 186–229) requires, **for
every** `upstream_key: required` pair, that the corresponding upstream's own
task output carried `{"guard": required}` — checked via
`(by_key.get(upstream_key) or {}).get("guard")`. If any one mismatches, the
whole step is reported `"status": "skipped"` with a reason.

**This is not per-link OR semantics — it's AND-across-every-guarded-incoming-edge.**
Per §1, Egeria fires a step if *any one* of its guarded incoming links is
satisfied (each link independently causes a prepared/reused engine action);
this code instead requires *all* of a step's guarded incoming edges to be
satisfied simultaneously, in one dict comparison. Confirmed by reading —
there is no per-link OR branch, just one loop that returns "skipped" on the
first mismatch. For every survey definition that exists today this makes no
observable difference, because (per `step_outcome.py`'s decision, 2026-08-21)
authored guards are held at `"Any"` — i.e., `guarded_by` is empty for every
live step — so the AND-vs-OR distinction has zero live cases to disagree on
yet. I did not change this file (it's not the contended one, but the fix
belongs with `build_plan`/`PlannedStep`'s data model, which both the local
loop and the Prefect flow read — see §5 for why I left it alone this round).

**`test_a_join_waits_for_both_upstreams`, `tests/test_prefect_survey_flow.py`
line 95** — read directly. It asserts `("join", ["b", "c"], {})` runs after
both `b` and `c`, with `guarded_by={}` on the join step (empty dict, third
plan-row element). That is a **plain dependency-ordering test** — Prefect
naturally waits for both `depends_on` futures before a task starts,
regardless of guards. It exercises none of `mandatoryGuard`'s actual
behaviour (holding a step that was already *prepared* by a non-mandatory
match). Its name is a false positive for join coverage — flagged here rather
than fixed, since renaming/refactoring that test file isn't this task's slice
and it isn't wrong, just mislabeled.

### 2.4 Guard *production* — the actual blocker

`repo_survey_definition_adapter._run_step` (line ~899, read only):

```python
def runner(project, registry, fast: bool = False, **_) -> dict:
    ...
    result = orch.run(project.slug, steps=[step_key], fast=fast)
    return {"annotations": result.annotations}
```

and `_run_batch` similarly returns `{"annotations": ..., "errors": ...}`.
**Neither ever sets a `"guard"` key.** `database/survey_definition_adapter.py`
and `filesystem/survey_definition_adapter.py`'s local-step runners are the
same shape (verified by reading both). So `run_planned_step_task`'s
`(output or {}).get("guard")` is `None` for literally every RE step that
exists in production today — including `repo_refresh_plan`
(`RefreshPlanSurveyor`, `sub_surveyors/refresh_plan.py`), whose own docstring
says it is "advisory" because "the executor runs every step regardless" —
true of the *local* loop (§2.5) but, after 2026-08-26, no longer the reason
on the Prefect path; the real reason on the Prefect path is that
`_run_step` never surfaces the plan's `refresh_needed`/per-target labels as
an output guard at all.

**This is squarely inside `repo_survey_definition_adapter.py`**, which I was
told is contended and must not touch. I confirmed the shape of the gap by
reading, and I am not fixing it. Wiring `repo_refresh_plan`'s finding into a
`"guard"` on its runner's return dict — and then authoring a real (non-"Any")
guard on the `repo_refresh_plan → repo_manifest_parse` (etc.) links in the
Survey Definition itself — is necessary before guards do anything observable
for repo surveys, and both are out of scope here (one needs the contended
file, the other needs an Egeria-side authoring change through
`dr-egeria-command-sync`/the reconciler, not this file at all).

### 2.5 The local loop in `SurveyDefinitionExecutor.run()` — the gap this task closes

Before this change: `pending_steps = survey_def.steps` (the reader's flat,
topologically-ordered-but-unbranched list — see `SurveyDefinition.steps`'s
own docstring: "an order to READ them in, not a sequence to run"), walked
`while i < n` with **zero reference to `.links`, `.guard`, or
`guarded_by`.** Every step in the definition runs, always, regardless of
what any upstream step produced. This is the literal behaviour the task
description names ("currently runs the WHOLE step graph").

It is reached whenever `_prefect_orchestration_enabled()` is false, or
`_run_via_prefect` returns `None` — Prefect unreachable, `build_plan` raised
`CyclicPlanError` (re-raised, not swallowed), or the flow import/call itself
raised (logged, swallowed, falls back). Per `docs/survey-model-and-engine-
host-design.md` §4.6, "RE must keep the local path indefinitely" for
offline/no-Prefect operation — so this is not a rare corner, it is the
documented permanent fallback, and until this change it silently ran a
branching definition in list order and reported every step as attempted.

## 3. Where the skip record goes

Per the task's own framing and `step_preconditions.py`'s docstring: preconditions
and guards "compose: a guard says a branch was not taken, a precondition says
a step had no input, and both must leave a trace rather than a silence."

`result_status.skipped(reason, gate=...)` is the existing, single vocabulary
for "a gate deliberately declined to run this step" (`SKIPPED_BY_DESIGN`).
`survey_orchestrator.py` reuses it for precondition skips by writing a
`ClassificationAnnotation` into the run's own `SurveyResult` (persisted to
the registry as a finding) *and* recording the key in
`result.skipped_steps`.

`SurveyDefinitionExecutor` has no equivalent persisted-finding channel of
its own — its "steps" are opaque adapter-runner calls (which, for repo,
happen to internally construct a `SurveyOrchestrator` and persist their own
findings, but the executor doesn't know that; for database/filesystem the
runner is a bare function with no `SurveyResult` at all). Building a new
generic persisted-finding path for the executor's own record of a guard skip
is a real design decision (what `kind`? what `project_slug`? does it need
`surveyed_at` reconciliation with the adapter's own persisted findings for
the same run?) that I am **not** taking on in this slice — inventing it
casually here is exactly the "parallel mechanism" the task said not to
build.

**What I did instead:** reuse `result_status.skipped()`'s *shape and
vocabulary* (state, cause/gate, hint/reason) inside the `steps_report` entry
the executor already returns and already writes into `log_survey`'s
`detail` JSON blob (`survey_definition_executor.py`'s existing
`log_survey(...)` call). This is visible in the run's activity-log record
and in the API/CLI result dict callers already read — not a new surface, and
not silent — but it is **not** a queryable finding row the way a
`survey_orchestrator` precondition skip is. Stated as a real, known
limitation, not smoothed over: a Results tab reading `query_findings` would
not see this skip; only the activity log / run result would. Closing that
gap fully needs the persisted-finding design named above, flagged as a
follow-up rather than invented under time pressure.

## 4. What Prefect orchestrates vs. what must run in Egeria

Per `docs/survey-model-and-engine-host-design.md` §4.4: `executes_at` is
RE's own "who runs this" tag today — `{"resource-explorer", "prefect",
"egeria", ...}`. That tag, not guard evaluation, is what decides the engine;
guards decide *whether* a step on the chosen engine's path runs at all, and
that decision has to be made by whoever is doing the sequencing.

**Prefect coordinates (via `survey_execution_plan.build_plan` +
`prefect/flows.py::re_survey_definition_flow`) whenever RE is the
coordinator** — which is every deployment today, since RE is not yet a
registered Egeria engine host (§4.1 says the mechanism exists in pyegeria,
but "what remains is RE-side work: register its steps as request types...
and run the find → claim → execute → report loop" — not built). Concretely,
Prefect sequences: every `executes_at="resource-explorer"` step (RE's own
Python surveyors — `FileInventorySurveyor`, `RefreshPlanSurveyor`,
`GitStatisticsSurveyor`, etc.) and every `executes_at="prefect"`/
`PREFECT_ONLY_STEPS` step (`soda_data_quality`,
`great_expectations_validation` — third-party libraries RE wraps as Prefect
tasks, per `prefect/flows.py`'s `run_soda_scan_task`/`run_gx_validation_task`).
These have real Python implementations inside RE/Prefect; there is nothing
Egeria-specific about *how* they execute, only about where their findings
get published afterward.

**Egeria must execute steps tagged `executes_at="egeria"`, and I concluded
these must stay there, not move to Prefect, because RE has no code to run
them at all.** Verified by reading both adapters that use this tag:

- `database/survey_definition_adapter.py`'s `other_engine_handlers={"egeria":
  _trigger_egeria_native_survey}` — its own docstring: "actively triggers
  Egeria's own native PostgreSQL survey (`EgeriaDatabaseSurveyor.trigger_survey_by_guid`)
  rather than being silently skipped." The actual profiling/schema work runs
  inside Egeria's PostgreSQL survey connector (Java/Egeria-side), not in RE
  or Prefect — RE only kicks it off and, per the same file, does not even
  auto-catalog on its behalf.
- `filesystem/survey_definition_adapter.py`, same pattern for Egeria's
  native filesystem survey.

**Why this can't just become a Prefect task:** Prefect can only orchestrate
work RE (or a library RE wraps, like Soda/Great Expectations) can execute.
An Egeria-native survey connector's code lives inside the Egeria platform's
own engine host process — RE has no Python entry point into it beyond
"trigger it and, today, do not even wait for or read back its result"
(confirmed: `_trigger_egeria_native_survey` triggers and returns; the
executor's `other_engine_handlers` branch reports `"status": "triggered"`,
not `"ok"` — it does not know the outcome). Moving orchestration to Prefect
doesn't change what can execute *inside* it; a step whose implementation is
Java code inside Egeria's engine host is not something Prefect (or RE) can
run "for" Egeria — the user's caveat in the task ("a given survey step may
really need to be executed in Egeria") is exactly this case, and it is
already correctly marked `executes_at="egeria"` in these two adapters. My
guard-evaluation change does not touch this branch's behaviour: a step
tagged `"egeria"` is unaffected by `guarded_by` either way (it's dispatched
by the `elif step.executes_at in adapter.other_engine_handlers` branch,
which sits after the `use_prefect`/`resource-explorer` branches and doesn't
consult the plan at all in the old code, and continues not to in the new
code — see §5).

**The longer-term fix — RE as a genuine Egeria engine host (§4.1–4.3)** would
let these steps be claimed and executed the same way any engine action is,
with `WAITING`/`IN_PROGRESS`/`COMPLETED` status RE could actually poll and
guard on, rather than fire-and-forget triggering. That's out of scope here —
it needs `link_supported_governance_service` registration and a
claim/execute/report loop, both unbuilt (§4.1's own closing line: "What
remains is RE-side work").

## 5. What I implemented

Small, and deliberately does not touch the contended file or invent a new
persisted-finding channel:

1. `survey_definition_executor.py`: the local (non-Prefect) loop now builds
   an `ExecutionPlan` via `survey_execution_plan.build_plan(survey_def)` and
   walks it in **plan order** (topological — dependencies before
   dependents) instead of `survey_def.steps`'s raw order. For every live
   definition (per §4.5's own verification note: "every live definition
   plans to exactly its current order") this is a no-op in practice, but it
   is now correct for a branching one instead of accidentally correct only
   because none exist yet.
2. Before dispatching a step, if its `PlannedStep.guarded_by` is non-empty,
   the executor checks each `{upstream_key: required_guard}` pair against
   the `"guard"` key (if any) on that upstream step's own recorded output —
   the *same* check `run_planned_step_task` already does on the Prefect
   path, kept consistent rather than diverging (§2.3's AND-across-edges
   simplification is therefore shared, not newly introduced, by this
   change — not fixed here, named as future work in §2.3/§2.2).
3. An unsatisfied guard produces a `steps_report` entry shaped from
   `result_status.skipped(reason, gate=...)` — `state: "skipped_by_design"`
   plus the reason (which upstream, which guard was required, what was
   produced instead, or "no guard was recorded" when the upstream emitted
   nothing at all, since — per §2.4 — that's the actual situation for every
   step today). It is **not** added to `errors` (a deliberate skip is not a
   failure) and **not** counted in the `ran` total used for the
   `log_survey` summary line, mirroring `survey_orchestrator`'s treatment of
   `skipped_steps`.
4. `mandatory_guard`/join semantics: **not implemented**, consistent with
   §2.2/§3.4 — `guarded_by` still can't express it, so there was nothing
   correct to build against. Left as a stated gap, not guessed at.
5. Steps tagged `executes_at="egeria"` are untouched by any of the above —
   they still bypass the plan/guard check entirely, per §4's conclusion that
   guard-gating a step whose actual execution and outcome RE cannot observe
   would be pretending to a precision the fire-and-forget trigger doesn't
   have.

### Known-negative test

`tests/test_survey_definition_executor.py::TestGuardEvaluationInTheLocalLoop`,
five cases, all forcing the local loop via
`patch.object(sde_module, "_prefect_orchestration_enabled", return_value=False)`
so they exercise this change deterministically regardless of whether a
Prefect server happens to be reachable on the machine running the suite:

- `test_an_unsatisfied_guard_skips_the_step_without_running_it` — mismatched
  guard; asserts `downstream_runner.assert_not_called()` (not just the report
  label — the actual regression the task named: a test that only reads the
  report dict passes even if the skip branch silently falls through and runs
  the step anyway), and that the skip is not counted in `errors`.
- `test_no_guard_emitted_at_all_also_skips_a_guarded_step` — today's real
  situation (§2.4): upstream ran and returned no `"guard"` key at all.
- `test_an_upstream_that_never_ran_reads_differently_from_one_that_ran_with_no_guard` —
  upstream raises; the skip reason distinguishes "produced None" (ran, said
  nothing) from "never recorded" (never ran at all) — two different facts,
  two different strings, not collapsed into one.
- `test_a_satisfied_guard_lets_the_step_run` — matching guard; asserts
  `downstream_runner.assert_called_once()`.
- `test_an_unconditional_link_is_unaffected` — `guard="Any"`, the state of
  every live definition today; confirms this change is a no-op for the
  common case, not just for the branching case it was built for.

### Full suite

`uv run pytest tests/ -q` — see the report for the actual result; this
section is written before running it, per the task's own ordering.
