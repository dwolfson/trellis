<!--
GENERATED from DATABASE_STEP_REGISTRY by packages/resource-explorer/scripts/generate_engine_host_declaration.py.
Do not hand-edit; regenerate. Design: docs/design-notes/DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md §5.1 (E1).

The owner runs this document; RE never does (this folder is not a bootstrap batch).

NOT YET EXPRESSIBLE IN Dr.Egeria (pyegeria 6.2.3 has no command for these; author them another way FIRST,
or the executor link below cannot resolve its engine):
  - SurveyActionEngine `ResourceExplorerSurvey` (display name "Resource Explorer Survey Engine"). Its
    description should say the engine is hosted by Resource Explorer's worker, outside any Egeria engine
    host (Q-M4). No Java engine host configuration may list it, or a JVM host races RE for every claim.
  - SurveyActionService `SurveyActionService::ResourceExplorerSurvey::db_derived`, linked to the engine by
    SupportedGovernanceService {requestType: "re-db-derived", serviceRequestType: "re-db-derived"}
The commands below are the ones Dr.Egeria has: the GovernanceActionType a person or process initiates, and its
GovernanceActionExecutor link to the engine.
-->

## Create Governance Action Type
### Display Name
Resource Explorer Survey — db_derived

### Qualified Name
ResourceExplorerSurvey::re-db-derived

### Description
Zero-fetch derivation over already-stored rows.

### Produced Guards
survey-completed, survey-invalid, survey-failed

### Content Status
ACTIVE

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| re_analysis_step | db_derived |
| engine_host | resource-explorer-worker |

___

## Link Action to Action Executor
### Governance Action Type
ResourceExplorerSurvey::re-db-derived

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-db-derived

### Description
Egeria dispatches ResourceExplorerSurvey::re-db-derived to Resource Explorer's engine, which claims it and runs RE step db_derived.

___
