<!--
GENERATED from the manifest of 're_statistics_freshness' (trellis-step-re-statistics-freshness 0.1.0) by
packages/resource-explorer/scripts/generate_engine_host_declaration.py. Do not hand-edit; regenerate.
Design: docs/design-notes/DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md §4.3 (engine host, step 3).

Declares the Analytic Library step 're_statistics_freshness' as a service of Resource Explorer's engine, so Egeria can
dispatch it: initiating ResourceExplorerSurvey::re-spike-statistics-freshness creates an engine action with request type re-spike-statistics-freshness, which RE's engine host
claims, runs through its step host and completes with one of survey-completed, survey-invalid, survey-failed
(survey-completed when there is nothing to derive).

Run it with `resource-explorer dr-egeria run engine-host/library/re_statistics_freshness.md`. RE's bootstrap never runs it.
Its pyegeria steps (re_statistics_freshness.pyegeria-steps.json) run first, each find-or-create:
  - SurveyActionEngine `ResourceExplorerSurvey` (normally already there, from the engine's own document);
  - SurveyActionService `SurveyActionService::ResourceExplorerSurvey::re_statistics_freshness`, linked to the engine by
    SupportedGovernanceService {requestType: "re-spike-statistics-freshness", serviceRequestType: "re-spike-statistics-freshness"}.
"Link Action to Action Executor" below is NOT safe to repeat; the runner refuses a second run of the same content
unless forced. Retire the step by setting Content Status to DEPRECATED, never by deleting the element.
-->

## Create Governance Action Type
### Display Name
Resource Explorer Survey — Table Statistics Freshness (RE spike twin)

### Qualified Name
ResourceExplorerSurvey::re-spike-statistics-freshness

### Description
How old each table's planner statistics are: the age of the last ANALYZE and VACUUM, tables never analyzed, and tables changed past autovacuum's analyze trigger, as of the newest table activity snapshot Resource Explorer stored. Opens no connection to the database. A table whose statistics were not read, or a database with none stored, is shown as "not measured", never as fresh.

### Produced Guards
survey-completed, survey-invalid, survey-failed

### Content Status
ACTIVE

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| re_analysis_step | re_statistics_freshness |
| engine_host | resource-explorer-worker |
| request_type | re-spike-statistics-freshness |
| nothing_to_derive_guard | survey-completed |
| kind | step |
| source | ods |
| version | 0.1.0 |
| resource_types | database |
| annotation_type | ResourceMeasureAnnotation |
| questions | Q-0073, Q-0062 |
| purposes | Maintain |
| perspectives | Steward, Data Expert |
| credential_tier | none |
| inputs | ods |
| measures | re_statistics_freshness, re_statistics_freshness_summary |
| family | Freshness |
| function | re_statistics_freshness.step.run |
| package | trellis-step-re-statistics-freshness |
| entry_point | trellis.analytics:re_statistics_freshness |

___

## Link Action to Action Executor
### Governance Action Type
ResourceExplorerSurvey::re-spike-statistics-freshness

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-spike-statistics-freshness

### Description
Egeria dispatches ResourceExplorerSurvey::re-spike-statistics-freshness to Resource Explorer's engine, which claims it and runs Analytic Library step re_statistics_freshness.

___
