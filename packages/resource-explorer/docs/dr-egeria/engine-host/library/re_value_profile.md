<!--
GENERATED from the manifest of 're_value_profile' (trellis-step-re-value-profile 0.1.0) by
packages/resource-explorer/scripts/generate_engine_host_declaration.py. Do not hand-edit; regenerate.
Design: docs/design-notes/DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md §4.3 (engine host, step 3).

Declares the Analytic Library step 're_value_profile' as a service of Resource Explorer's engine, so Egeria can
dispatch it: initiating ResourceExplorerSurvey::re-spike-value-profile creates an engine action with request type re-spike-value-profile, which RE's engine host
claims, runs through its step host and completes with one of survey-completed, survey-invalid, survey-failed
(survey-completed when there is nothing to derive).

Run it with `resource-explorer dr-egeria run engine-host/library/re_value_profile.md`. RE's bootstrap never runs it.
Its pyegeria steps (re_value_profile.pyegeria-steps.json) run first, each find-or-create:
  - SurveyActionEngine `ResourceExplorerSurvey` (normally already there, from the engine's own document);
  - SurveyActionService `SurveyActionService::ResourceExplorerSurvey::re_value_profile`, linked to the engine by
    SupportedGovernanceService {requestType: "re-spike-value-profile", serviceRequestType: "re-spike-value-profile"}.
"Link Action to Action Executor" below is NOT safe to repeat; the runner refuses a second run of the same content
unless forced. Retire the step by setting Content Status to DEPRECATED, never by deleting the element.
-->

## Create Governance Action Type
### Display Name
Resource Explorer Survey — Value Profile (RE spike twin)

### Qualified Name
ResourceExplorerSurvey::re-spike-value-profile

### Description
What the columns of each table contain, from the latest value-profile batch Resource Explorer's quality survey stored: per table its state, row count and columns measured, and per column the value, distinct, null and filled counts. Opens no connection. A table or column that was not profiled is shown as "not measured" with the reason, never as having no values.

### Produced Guards
survey-completed, survey-invalid, survey-failed

### Content Status
ACTIVE

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| re_analysis_step | re_value_profile |
| engine_host | resource-explorer-worker |
| request_type | re-spike-value-profile |
| nothing_to_derive_guard | survey-completed |
| kind | step |
| source | ods |
| version | 0.1.0 |
| resource_types | database |
| annotation_type | ResourceMeasureAnnotation |
| questions | Q-0079 |
| purposes | Assess, Learn |
| perspectives | Steward, Data Expert |
| credential_tier | none |
| inputs | ods |
| measures | re_value_profile, re_value_profile_summary |
| family | Profile |
| function | re_value_profile.step.run |
| package | trellis-step-re-value-profile |
| entry_point | trellis.analytics:re_value_profile |

___

## Link Action to Action Executor
### Governance Action Type
ResourceExplorerSurvey::re-spike-value-profile

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-spike-value-profile

### Description
Egeria dispatches ResourceExplorerSurvey::re-spike-value-profile to Resource Explorer's engine, which claims it and runs Analytic Library step re_value_profile.

___
