# SLICE — Engine host step 4: one mixed Egeria process, a native survey step chained to an RE step (2026-10-15)

From the design session for the PR/CI session's builder, on the owner's
word of 2026-10-15 ("start extensibility step 4"). Case 2 of
`DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md` (§4.1 "mixed processes", §5.4
"not in the slice"), in the style of its §5. Step 3 is proven: RE's
`re-database-staleness` on coco_pharma completed `survey-completed`,
report f21475b2, 266 annotations in Egeria matching RE's.

## Goal

The smallest proof that Egeria can run a process whose first step is a
native Java survey and whose second step is RE's, with Egeria evaluating
the guard between them and carrying the action targets, and RE reading
the two-step run back with no new read path for the native half.

**Not** the alternative of making RE's 127 existing
`GovActionProcessStep::*` dispatchable by Egeria. That would attach an
executor to every step of every survey definition and change who runs
RE's own surveys; it is case 3, a later slice. One new process touches
nothing that runs today.

## The process

`GovActionProcess::ResourceExplorer::PostgresSurveyThenDerived`, two steps:

| Step | Governance action type | Runs on | Produced guards used |
|---|---|---|---|
| 1 | the content pack's `PostgreSQLSurvey` type (the one RE's Run route already initiates through `EgeriaSurveyPort`) | Egeria's survey engine, Java | `survey-completed`, `survey-failed`, `survey-invalid` |
| 2 | `ResourceExplorerSurvey::re-database-staleness` (the step-3 type, already declared and proven) | RE's engine host | the same three |

Linked by one `NextGovernanceActionProcessStep` from step 1 to step 2
with `guard = survey-completed`, `mandatoryGuard = true`. No link for the
other guards: on `survey-failed` or `survey-invalid` the process ends
after step 1, which is Egeria's behaviour and the first negative case.

Why `re-database-staleness` and not `re-db-derived`: it is the step that
has run as an engine action live, and staleness is the natural second
step after a fresh native survey (it reads what the survey just
measured). `re-db-derived` follows in step 5 with the same wiring.

Type: the process is a plain `GovernanceActionProcess` for this slice.
ISSUE-150 records that Dr.Egeria's Create Governance Action Process
cannot create the `SurveyingActionProcess` subtype yet; the subtype is
one line to change when it can, and nothing in the slice depends on it.

## How targets and guards carry

What Egeria does (to be confirmed live by E2 below, read-only on an
existing native process run): the process's action targets are copied
to the first step's engine action; a survey action service records its
report as a new action target named `surveyReport` on completion; and
`NextGovernanceActionProcessStep` creates the next engine action with
the previous action's action targets, original and new, plus the
original request parameters, when the completion guard matches.

So step 2's engine action arrives with at least two action targets:

- the database asset the process was started on (the name the content
  pack uses for the survey's target, read in E2; the design assumes the
  survey's own target name, not a new one);
- `surveyReport`, the step-1 report's GUID, added by the native service.

RE's engine host reads both. The asset GUID maps to the entity slug as
step 3 does; the report GUID is passed to the step as `source_report`.
`re-database-staleness` reads that report's annotations back through the
existing `egeria_survey_reader.annotations_from_report` before deriving,
so the derivation is over the measurement that just happened and not
over an older stored inventory; the step records which report it read
in its own report's additionalProperties (`derived_from_report`).

If `surveyReport` is absent (the process was started at step 2, or the
native service did not add it), the step completes `survey-invalid` with
the sentence "no surveyReport action target; nothing to derive from",
never `survey-completed`.

## 5.1 Pieces

| # | Piece | Where | Write? |
|---|---|---|---|
| M1 | **Process declaration generator.** Extends `scripts/generate_engine_host_declaration.py` with `--mixed-process`: emits a Dr.Egeria document creating the process, its two steps (step 1 referencing the content pack's `PostgreSQLSurvey` type by qualified name, step 2 referencing `ResourceExplorerSurvey::re-database-staleness`), and the one next-step link with its guard. Under `docs/dr-egeria/engine-host/processes/postgres-survey-then-derived.md`. Test: the document's step types, guard and order equal a registry entry `MIXED_PROCESSES["postgres_survey_then_derived"]`. If Dr.Egeria's Link Action to Action Executor or next-step command is unverified (ISSUE-150), E2 verifies them live before M1 is trusted | RE `scripts/`, docs | No; the owner runs the document |
| M2 | **Read-only probe** of one existing native `PostgreSQLSurvey` engine action and, if any exists, one process instance: the action-target names and whether `surveyReport` is added on completion; what a next engine action carries. Saved as fixtures. This settles the target name the design assumes | gate venv | Read-only |
| M3 | **Target reading in the handler.** `engine_action` handler reads all action targets, maps the asset target to the slug and passes `source_report` when a `surveyReport` target is present; the step host passes it to the step; `re-database-staleness` accepts it and records `derived_from_report`. Absent target → `survey-invalid` with the sentence above | `run_queue.py`, `survey_step_host.py`, the library step | Egeria: claim, status, completion, the report, as step 3 |
| M4 | **Process grouping in Understanding.** A reader that groups engine actions by the process instance they belong to (the engine action's anchor or `GovernanceActionProcessInstance` relationship, confirmed in M2) and shows one run line: "Postgres survey then derived · step 1 PostgreSQLSurvey ✓ report a1b2 · step 2 re-database-staleness ✓ report c3d4 · started by <requester> 10-15". Each step's report opens as today. `derive_native_state` is unchanged for each action | `native_survey_run.py` reader, Understanding's survey history | Read-only |
| M5 | **Trigger.** The owner runs `initiate_gov_action_process("GovActionProcess::ResourceExplorer::PostgresSurveyThenDerived", action_targets=[coco_pharma database asset])` from Dr.Egeria, or RE's Run route gains the process as a choice beside `PostgreSQLSurvey` through `EgeriaSurveyPort` (same call shape) | Dr.Egeria or RE | Egeria write (the owner's) |

## 5.2 Tests that fail first

1. **Generated process equals registry.** Step types, order, guard and
   `mandatoryGuard` match `MIXED_PROCESSES[...]`; changing the guard fails.
2. **Targets carry.** Fake engine action for step 2 with two targets
   (asset, `surveyReport`): the handler maps the slug, passes
   `source_report`, the step reads the report through the existing
   reader (fake binds its real signature), and the step's report carries
   `derived_from_report` equal to the input GUID.
3. **Missing report target.** Same action without `surveyReport`: the
   step completes `survey-invalid` with the sentence; no report is
   published; no `survey-completed` call.
4. **Step 2 is claimed only as step 2.** An approved action of RE's type
   whose process instance's previous action is not `COMPLETED` with
   `survey-completed` is not claimed (Egeria should never create it, so
   the test pins RE's own refusal if it ever does); recorded once.
5. **Grouping reader.** Two engine actions sharing one process instance,
   one native and one RE, render one run line with two steps and two
   report links; a lone action renders as today; an action whose process
   instance cannot be read renders as today with "process unknown".
6. **Failure stops the chain, honestly.** Fixture: step 1 `survey-failed`,
   no step-2 action exists. Understanding shows "step 2 not started ·
   step 1 failed", never "pending".
7. **Same identity.** Step 2 runs as `Daemon(ENGINE_HOST,
   requested_by=<requesterUserId>)`, the requester copied from the
   step-2 action (Egeria copies it from the process start), `Ownership`
   on the report names the requester, as in step 3.
8. **Off means off** and **private target not claimed**, as step 3, re-run
   against the process-created action.

## 5.3 Gate (live, the owner's write round)

The owner runs M1's document, then M5 on coco_pharma. Then:

- Egeria shows a process instance with two engine actions in order; the
  first `COMPLETED` with `survey-completed` and a `surveyReport` target;
  the second claimed by RE's engine user, `COMPLETED` with
  `survey-completed`, its own `surveyReport` target, `requesterUserId`
  the owner.
- RE's step-2 report carries `derived_from_report` = the step-1 report
  GUID, and its annotation count equals the `step_runs` row's.
- Understanding shows the one run line with both steps and both reports,
  read through the existing readers.
- **Negative, live:** the same process on a database whose native survey
  fails (a wrong credential on a throwaway registration): step 1
  `survey-failed`, no step 2, Understanding says "step 2 not started ·
  step 1 failed".
- **Negative, live:** `initiate_gov_action_type` on step 2's type alone
  with only the asset target: `survey-invalid` with the sentence.

## 5.4 Not in the slice

- `re-db-derived` as step 2 (step 5, same wiring).
- The `SurveyingActionProcess` subtype (one line when Dr.Egeria can).
- RE's own survey definitions as Egeria-dispatchable processes (case 3).
- A guard other than the three standard ones (Q-M5: look for an existing
  valid-value set before inventing one).
- Request parameters beyond what the process start carries.
- Cancel of a process (Mandy: a cancel process is coming).

## Open points for the owner

- [ ] Does the Run route offer the mixed process beside `PostgreSQLSurvey`
      in this slice, or is Dr.Egeria the only trigger until the gate passes?
- [ ] On a `survey-invalid` from step 1 (nothing to survey), should the
      process still run step 2? The design says no: nothing was measured.
