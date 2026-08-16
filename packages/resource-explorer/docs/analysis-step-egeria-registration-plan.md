# RE analysis-step registration as Egeria elements + EA authoring link

**Status: investigation complete, plan drafted, not yet built.**

## Context

Prompted by Discovery going empty for repos (the "Repo Coarse Scout" `GovernanceActionProcess`
authored earlier this session was lost — almost certainly an Egeria database reset). The user's
question: *"is the Dr.Egeria survey-authoring tooling in Egeria Explorer, and should we link RE
to Egeria Advisor (EA) to use it — and we also need to register the analytic functions as
annotation types so they can be incorporated into surveys."*

Three background research passes (Egeria Explorer's PyegeriaWebHandler, pyegeria's real type
model, Egeria Advisor's plan-authoring code) ground everything below in source, not assumption.

## Findings

**1. Egeria Explorer has no Survey Definition authoring.** Its "Dr. Egeria" tab
(`type-explorer.html`, backed by `dr_egeria_commands_handler.py`) is a generic command
executor — it lists/executes whatever Dr.Egeria markdown templates exist on disk, and there is
no `Create Survey*`/`Create Governance Action Process*` template in the actual template set
(`exchange-quickstart/Templates/Dr-Egeria-Templates/`). Real Survey Definition `GovernanceActionProcess`
elements that DO exist in Egeria are out-of-box content, invoked (not authored) from Jupyter
notebooks — a separate path with no UI/API overlap with Egeria Explorer at all.

**2. Egeria Advisor (EA) is the tooling this session already agreed to use for this.**
`docs/egeria-collaboration-and-survey-model.md` §6 (written earlier, never revisited) already
concludes: *"Dr.Egeria... is the authoring format for Survey Definitions... authored in Egeria
Advisor's existing plan editor."* EA has real, working plan authoring + in-process execution
against live Egeria:
- `advisor/agents/governance_plan_agent.py::GovernancePlanAgent` — decomposes an intent into a
  command sequence, writes a Plan Document (`## Command Sequence` markdown), executes it.
- `advisor/agents/dr_egeria_agent.py::DrEgeriaActionAgent.execute(markdown, directive=...)` —
  the lower-level primitive: runs a raw Dr.Egeria markdown block synchronously, in-process,
  against a live `EgeriaTech` client. This is a plain Python function/singleton call, no
  FastAPI/MCP dependency at the boundary.
- Web UI: `advisor/web/static/index.html`'s "Plans" tab + Plan Canvas
  (`plan_canvas.js`/`plan_editor.js`), backed by `POST /api/plans/{doc_id}/execute` etc. in
  `advisor/web/app.py`.
- **Same uv workspace as RE** (`trellis/pyproject.toml`, `[tool.uv.workspace] members =
  ["packages/*"]`) — `dr_egeria_agent.execute()` is callable as a direct in-process Python call,
  no REST round-trip. **Currently zero wiring exists** — `resource-explorer`'s `pyproject.toml`
  doesn't depend on `egeria-advisor`, and no RE code imports `advisor.*`.
- EA has **zero** Survey/`GovernanceActionProcess`/`AnnotationType` concept of its own — its
  11-family action catalog (`advisor/configdata/dr_egeria_actions.yaml`) doesn't cover Action
  Author commands at all today. Linking gets you EA's authoring UX/versioning/audit trail, not
  new capability RE doesn't already have via its own `mcp__egeria` calls.

**3. "Annotation Type" is not a real, registerable Egeria entity.** Confirmed against the actual
open-metadata type archive: no `AnnotationType`/`SurveyActionType` catalogable type exists.
`Annotation` is a *result* entity (survey output), carrying a free-text `annotationType` property
— not something you register a function *as*. The real, closest catalogable "this is a callable
analysis step" entity is **`GovernanceActionType`** (and its chainable subtype
`GovernanceActionProcessStep`) — exactly what "Repo Coarse Scout" already used for `repo_health`/
`repo_language` via the pre-existing "Action Author" Dr.Egeria command family (`Create Governance
Action Process[/Step]`, `Link First/Next Process Step`) — confirmed no new commands are needed.

**4. The real gap is already named, scoped, and tracked — just unbuilt.** RE's own design doc,
open question **A12**: *"How does RE discover/register analysis steps as catalogable Egeria
elements — both finding Egeria's existing ones and publishing RE's own sub-surveyors the first
time they're used?... Still open."* `docs/Backlog.md` (search "GovernanceActionType"): *"publishing
RE's own sub-surveyors as catalogable `GovernanceActionType` elements — nothing does this today...
Likely shape: a one-time/per-addition publish step (an extension of `EgeriaPublisher`, or its own
Dr.Egeria plan) plus a local inventory RE itself can consult."*

**5. A genuinely useful adjacent pattern exists, but solves a different problem.** Egeria
Explorer's `GET /api/analytics` (`analytics_registry_handler.py`) catalogs locally-computed
Python functions (Report Spec `analytic_function`s) purely as documentation — zero Egeria element
required, `pyegeria.view.analytic_registry`-backed. This is the right model for "make RE's
analytics *browsable/documented*" but does **not** produce the `GovernanceActionType` elements
Discovery's candidate search actually queries — it's a complementary nice-to-have, not a
substitute for closing A12.

## Decisions

**D1 — Close A12: publish RE's repo sub-surveyors as real `GovernanceActionType` elements.**
Extend `EgeriaPublisher` (or a small standalone `resource_explorer/surveyors/step_publisher.py`)
with a `publish_analysis_steps()` method that, for each `STEP_REGISTRY` entry
(`repo_survey_definition_adapter.py`), issues a `Create Governance Action Process Step` via the
existing pyegeria `ActionAuthor` client (same mechanism `SurveyDefinitionReader`/executor already
use to *read* these elements) with `Additional Properties`:

| Key | Value | Source |
|---|---|---|
| `executes_at` | `resource-explorer` | constant |
| `supported_technology_type` | `Git Repository` | constant, repo adapter |
| `re_analysis_step` | e.g. `repo_license_classification` | `STEP_REGISTRY` key |

`Qualified Name` = `GovActionProcessStep::RepoAnalysis::{step_key}`, `Display Name`/`Description`
from the `StepInfo.description` field already present in `STEP_REGISTRY` — **zero new metadata
needed**, this just projects data RE already has. Idempotent: check-then-create (or `Merge
Update`, per this session's earlier confirmed in-place-update pattern) so re-running after a
reset is a clean recovery action, not a duplicate-creation risk.

**D2 — Author (or re-author) a richer Survey Definition chaining ALL current repo steps**, not
just the original two (`repo_health`, `repo_language`). Now that D1 makes every step (including
the 4 new B1–B4 additions — `repo_license_classification`, `repo_security_features`,
`repo_ci_quality`, and CODEOWNERS folded into `repo_documentation`) a real, referenceable
`GovernanceActionProcessStep`, Discovery's candidate list should reflect the repo's actual full
capability, not a stale 2-step subset. Decide during implementation whether this keeps the name
"Repo Coarse Scout" (misleading now — it'd no longer be "coarse") or becomes a new, more
accurately-named process (e.g. "Repo Full Survey" / "Repo Assessment Survey"), possibly alongside
a genuinely coarse 2-step one for Scouting's fast-path use case (`scouting-scan` route) — the two
have different callers with different speed/completeness needs.

**D3 — Save the authoring plan as a reproducible `.md` doc this time**, matching the Scouting
Questions precedent (`docs/dr-egeria/scouting-questions.md`) — this is the actual fix for
"Discovery goes empty on a reset," independent of D1/D2's mechanism. A committed markdown file
means recovery is "run this file again," not "someone remembers the exact command sequence."

**D4 — Defer the EA UI/in-process link itself.** Given finding 2 (EA has no capability RE's own
`mcp__egeria` path doesn't already have for this specific need), routing D1/D2's authoring through
EA's Plan Editor buys UX/versioning polish, not new function — recommend building D1–D3 first via
the same direct path already proven this session (`mcp__egeria` tools), get it live-verified and
working, *then* separately decide whether it's worth wiring `resource-explorer` → `egeria-advisor`
as a workspace dependency for a nicer authoring surface. Flagging this as its own, later, smaller
decision rather than a blocking prerequisite — D1–D3 don't need it to ship.

## Verification

- Unit tests: `publish_analysis_steps()` — idempotent re-run (no duplicate GUIDs), correct
  `Additional Properties` per step, one test per `STEP_REGISTRY` entry count (mirrors this
  session's existing step-count regression-guard pattern in `test_repo_survey_definition_adapter.py`).
- Live: run `publish_analysis_steps()` against the real `qs-view-server`, confirm each step
  appears as a `GovernanceActionType`/`GovernanceActionProcessStep` element via direct
  `find_governance_definitions` query (the same probe used to diagnose the original empty-Discovery
  report). Author the chained process (D2), confirm `GET /api/survey-definitions/repo/{slug}/candidates`
  now returns a real, non-empty candidate list. Confirm the saved `.md` doc (D3) reproduces the
  exact same state end-to-end after a manual delete-and-recreate.
- Full RE test suite green.
