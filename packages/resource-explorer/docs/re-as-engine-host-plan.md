# RE as an Egeria Engine Host — execution model, reachability dimension, required pyegeria work

**Status: design pass complete (2026-08-17), not yet built.**

**Supersedes §4 ("Step-implementation mapping") of `microflow-embedded-process-plan.md`** — that section split step-implementation between `EmbeddedProcess` (RE-local/Prefect steps) and `Link Action to Action Executor` (Egeria-engine steps). This doc replaces both halves of that split with one unified, fully-native mechanism: RE itself becomes a registered Governance Engine and claims `GovernanceActionExecutor`-wired steps like any other engine. No `EmbeddedProcess` authoring is needed for RE-hosted steps under this model — `PYEGERIA_ISSUES.md` ISSUE-48 (the `EmbeddedProcess` authoring gap) is downgraded accordingly, see "PYEGERIA_ISSUES filing" below.

## Origin

Overnight idea, not something considered in the original Survey Type design pass: model RE as (at least partially) an Egeria Engine Host, with RE surveys becoming real `GovernanceActionProcess`/`GovernanceActionProcessStep` graphs whose implementation is a `GovernanceRequestType` mapped onto a `GovernanceService` — where that service, for RE-hosted steps, is RE's own microflow rather than a Java connector. If it works, RE inherits process history, guard-driven chaining, and graph visualization natively instead of RE inventing its own parallel versions of all three (which is roughly what the earlier `additionalProperties.executes_at` convention and `EmbeddedProcess` plan were both, independently, reinventing).

Verified via direct read of the local Egeria Java source (Governance Action Framework: `open-metadata-implementation/frameworks/open-governance-framework`, `open-metadata-implementation/engine-services/{governance-action,survey-action}`, `open-metadata-implementation/governance-server-services/engine-host-services`, `open-metadata-implementation/access-services/gaf-metadata-management`) and pyegeria's existing client surface, not assumed.

## The four execution permutations, and why they collapse to two real choices

| # | Initiates | Orchestrates (owns process state) | Steps execute | Net new work |
|---|---|---|---|---|
| **1** | RE (`initiate_gov_action_process`) | Egeria (native) | Egeria (native, all steps) | **None** — `initiate_gov_action_process()` already exists in pyegeria (`automated_curation.py`, wraps `POST .../governance-action-processes/initiate`); RE just needs a route calling it + reading results back |
| **2** | RE (`initiate_gov_action_process`) | Egeria (native) | Mixed — some native, some RE | RE becomes a claiming engine: poll/claim/complete loop + engine/service registration (scoped below) |
| **3** | RE (`SurveyOrchestrator.run()`) | RE | RE | — this is today's architecture, unchanged |
| **4** | RE (`SurveyOrchestrator.run()`) | RE | Mixed — some RE, some Egeria via `initiate_engine_action` | Thin step-runner wrapping already-existing `initiate_engine_action` + a completion poll |

**Case 1 is real but has no current target.** For case 1 to apply, *every* step of a Survey Definition needs a working Java governance/survey-action connector already. None of RE's own analyses do (`repo_health`/`repo_language`/etc. all run via RE's local Python dispatch today) — porting them to Java to satisfy case 1 would be strictly more expensive than case 2 for the same steps, since case 2 gets the identical native process-orchestration benefit while leaving RE's Python steps as Python. Case 1 only has a real target where Egeria already ships full native coverage end-to-end — Postgres and filesystem surveys — and there RE has no execution-side work to do at all, just trigger + read-back.

**Case 2 is the real capability to build.** It's not "case 1 minus some steps" — every RE-specific survey needs case 2's investment (or stays case 3) to ever become a genuine native `GovernanceActionProcess`, because RE's bespoke logic (GitHub API calls, tree-sitter extraction, license classification) has no Java equivalent and building one would be pure duplicated effort with no benefit over letting RE claim the step itself.

**Case 4 is real and nearly free right now** — see "Case 4" below.

**Case 3 stays the permanent default**, not a stepping-stone to be phased out — see "Why case 3 doesn't go away" below.

## The reachability dimension (orthogonal to all four permutations)

RE and Egeria's engine host(s) don't necessarily have the same network reach. RE may be able to reach resources Egeria's engine host can't (a different network segment, VPN, on-prem system), and vice versa; a future Airflow-backed engine may have broader reach than either. This means **"Egeria already has a native connector for X" is not sufficient reason to always prefer it** — a specific deployment may need RE's own implementation of a step precisely because RE (not Egeria) can reach the target resource.

This doesn't require new mechanism — it composes with what's already there. `GovernanceActionExecutor` wires *one specific engine* to a step via its `requestType`; which engine a given step's executor actually points at is a per-Survey-Definition-authoring (i.e., per-deployment) decision, not something GAF auto-resolves at runtime. So:

- A `requestType` can legitimately have candidate implementations registered on more than one engine (Egeria-native, RE, eventually Airflow).
- Which one a given deployment's Survey Definition actually wires a step to is chosen explicitly at authoring time, based on that deployment's known reachability — not decided automatically, and not something this plan builds auto-selection logic for.
- This is exactly how a future Airflow engine slots in later with zero new design: register it as a third engine, point specific steps' `GovernanceActionExecutor` at it where its reach is what's needed.

**Not built now, explicitly deferred:** any tooling to help an author decide *which* engine to pick per step (a reachability probe, a recommendation). Noted here so the extension point is on record.

## Native mechanism recap (grounded in direct source verification)

Confirmed chain: `GovernanceActionProcess` → (`GovernanceActionProcessFlow`) → first `GovernanceActionProcessStep` → (`NextGovernanceActionProcessStep`, guard-gated) → next step; each step → (`GovernanceActionExecutor{requestType}`) → `GovernanceEngine` → (`SupportedGovernanceService{requestType, serviceRequestType}`) → `GovernanceService` → (Connection/ConnectorType) → Java connector class.

**Confirmed: nothing in the runtime requires the claimer of an engine action to be a JVM, or the registered engine it claims for.** `EngineActionHandler.claimEngineAction`'s only gate is `status == APPROVED && processingEngineUserId == null` (`common-services/generic-handlers/.../EngineActionHandler.java`) — no verification that the caller matches a configured Engine Host's `engineUserId`. Completion (`recordCompletionStatus`, same file) requires only that the completing `userId` matches whoever claimed it, then calls `initiateNextEngineActions` server-side — this is what walks `NextGovernanceActionProcessStep` and evaluates guards, giving process chaining "for free" to whoever completed the step, regardless of what kind of process claimed it.

The full engine-facing protocol is REST-exposed under `/servers/{server}/open-metadata/access-services/governance-context-service/users/{userId}` (`gaf-metadata-management/gaf-metadata-spring/.../GovernanceContextResource.java`):
- `GET /governance-engines/{governanceEngineGUID}/active-engine-actions` — list this engine's claimable actions
- `POST /engine-actions/{engineActionGUID}/claim`
- `POST /engine-actions/{engineActionGUID}/status/update`
- `POST /engine-actions/action-targets/update`
- `POST /engine-actions/{governanceActionGUID}/completion-status`

The Java `GovernanceContextClientBase` is a pure URL-template wrapper over exactly these five — directly reimplementable as a Python client.

## Gaps — what pyegeria is actually missing

**Requester side — already covered, confirmed by direct grep:**
- `initiate_gov_action_process()` (`automated_curation.py`) — full-process trigger (case 1/2)
- `initiate_engine_action()` (`automated_curation.py`) — single-service trigger (case 4)
- `get_engine_actions`, `get_active_engine_actions`, `find_engine_actions`, `cancel_engine_action` (`automated_curation.py`) — status/polling

**Engine (claimer) side — entirely missing, needed for case 2:**
- `get_active_engine_actions_for_engine(governance_engine_guid, ...)` — the per-engine claimable-actions listing (`GovernanceContextResource`'s `.../active-engine-actions`, distinct from the requester-side general listing already covered above)
- `claim_engine_action(engine_action_guid)`
- `update_engine_action_status(engine_action_guid, status)`
- `update_action_target_status(...)`
- `record_completion_status(engine_action_guid, completion_status, output_guards, new_action_targets, ...)`

**Registration — a genuine server-side gap, not just a pyegeria gap:** `GovernanceEngineConfigurationHandler.registerGovernanceServiceWithEngine(...)` exists server-side but is wired to no REST endpoint at all (`GovernanceConfigurationResource` is read-only). Egeria itself only does this via content-pack archive writers (`GovernanceArchiveHelper.addGovernanceEngine`/`addSupportedGovernanceService`). The workaround — the generic `create_metadata_element`/`create_related_elements` endpoint — is the same rough, easy-to-misuse route already flagged in ISSUE-48's investigation (verbose typed body shape, no structural validation).

**Unverified, flag before relying on it:** whether a `SurveyReport` (as opposed to a bare `Annotation`) can be authored purely over REST for a case-2 RE-hosted survey step — `create_annotation` exists in `data_discovery.py`, no `create_survey_report` equivalent was found. Needs a direct check before case 2 is built for survey-shaped (not generic governance-action-shaped) steps.

## Case 4 — delegate a step from RE's local orchestration to Egeria

Cheapest real slice, and the right one to build first: a new step-runner in RE's step registry that wraps the already-existing `initiate_engine_action()` + a completion poll (`get_engine_action(guid)` until terminal status), folding the result into RE's existing `AnalysisKindResults` shape. Composes directly with `SurveyOrchestrator.run(steps=[...])` — one step in a local sequence becomes "call out to Egeria and wait" instead of "call a local sub-surveyor." No new pyegeria client work; the missing half is entirely RE-side wiring. Good candidate to prove the pattern live before committing to case 2's bigger investment.

## Case 1 — trigger a fully-native Egeria survey from RE

A new RE route ("Run as native Egeria Survey," distinct from today's local scouting-scan/analysis-run buttons — a deliberate choice, not automatic, per the reachability note above) calling `initiate_gov_action_process(process_qualified_name)` against a Survey Definition that's *already* fully native (Postgres/filesystem, not a repo-analysis one), then reading results back via the existing survey-report reading path. No new pyegeria work needed. Low priority — RE has no fully-native-covered resource type today — but cheap enough to build opportunistically once a real target shows up (e.g. if RE ever surfaces Egeria's native database survey results directly rather than via RE's own `HybridDatabaseSurveyor`).

## Case 2 — RE as a claiming engine (the real investment)

New RE-side component, a sibling to `scheduler.py`, not a route handler — a background poll loop:

1. Poll `get_active_engine_actions_for_engine(re_engine_guid)`.
2. Filter to `APPROVED` actions whose `requestType` RE's step registry actually supports.
3. `claim_engine_action(guid)`.
4. Dispatch to RE's local step-registry (the same `AnalysisKind`-keyed runners `SurveyOrchestrator` already has, reused rather than duplicated).
5. `record_completion_status(guid, status, output_guards, new_action_targets)` — Egeria's own server-side logic handles process chaining from here.

**Mutual exclusion is mandatory, not advisory**: RE's registered `GovernanceEngine` must appear in **zero** Java Engine Host config documents (`governanceEnginesConfig`), or a real Java host racing to claim the same action can win and then fail to resolve a connector that was never meant to exist. This needs to be a documented deployment rule, not just an assumption.

**Registration** (`GovernanceEngine` + `GovernanceService` + `SupportedGovernanceService` per supported `requestType`) happens once per deployment, via the generic metadata-element route until/unless ISSUE-49 (below) gets a real registration endpoint. The registered `GovernanceService`'s `connectorProviderClassName` is partly decorative under this model — RE dispatches on `requestType` internally, never resolving that class — worth being explicit about in the catalog rather than letting it look like real, resolvable Java.

## Sequencing

1. **Case 4** — no new pyegeria client work, smallest slice, validates the requester-and-poll pattern against a live server.
2. **Case 1** — also no new pyegeria work, but no current target; build opportunistically, not scheduled.
3. **Case 2** — the real investment: file ISSUE-49 (below), build the 5 engine-side client methods (or however many land), the registration path, the background claim-loop service, and the mutual-exclusion deployment rule. Sequenced after case 4 has proven the live requester/poll pattern works, since case 2 is strictly more machinery for the same underlying protocol.

## PYEGERIA_ISSUES filing

**ISSUE-49** (new, to file): the case-2 engine-side gap — 5 missing client methods (claim/status-update/action-target-update/completion + the per-engine active-actions listing) plus the unwired `registerGovernanceServiceWithEngine` REST endpoint. This is the priority item; **ISSUE-48** (`EmbeddedProcess` authoring) should be re-flagged as lower priority / possibly unnecessary — under this model, RE-hosted steps use the same native `GovernanceActionExecutor`/`SupportedGovernanceService` mechanism as every other engine, with no `EmbeddedProcess` element needed at all. ISSUE-48 stays open only as a legitimate, independent design-time-authoring gap (something else might still want to declare a persistent non-transient process definition outside the engine-action-executor pattern) — not as a blocker for anything in this doc.

## Verification (for whenever build starts)

- Case 4: live end-to-end — RE-local survey delegates one step to a real `initiate_engine_action` call, polls to completion, folds the result into its own step-result shape; confirm behavior when the delegated action fails/times out.
- Case 2: live end-to-end against a real server — register a `GovernanceEngine`+`GovernanceService`+`SupportedGovernanceService`, author a `GovernanceActionProcess` with at least one step wired to RE's engine and one to a native Egeria connector in the *same* process, trigger via `initiate_gov_action_process`, confirm RE's poll loop claims and completes its step, confirm Egeria's own server-side chaining correctly proceeds to the native step next, confirm the process graph/history renders correctly showing both engines' contributions.
- Explicit negative test: run a real Java Engine Host configured for a *different* engine at the same time as RE's poll loop, confirm no cross-claiming happens for unrelated request types (sanity check on the mutual-exclusion rule, not a substitute for it).
