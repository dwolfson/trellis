<!--
GENERATED from the manifest of 'database_staleness' (trellis-step-database-staleness 0.1.0) by
packages/resource-explorer/scripts/generate_external_step_entries.py. Do not hand-edit; regenerate.

PROVISIONAL: GovernanceActionType is the element type used here for a step that Egeria does not run.
Whether that is the right element is an open question for the Egeria leads (Mandy note, item 20).

Run this document to declare the step in Egeria; nothing runs it automatically. Retire the step by
setting Content Status to DEPRECATED, never by deleting the element.

The second block is for a Survey Definition author: paste it into the definition's document, replace
<SurveyDefinition>, and link it with Link Next Process Step. A user step joins a survey that way, not
through Resource Explorer's code.
-->

## Create Governance Action Type
### Display Name
Database Staleness

### Qualified Name
GovActionType::trellis-analytics::database_staleness

### Description
Rows changed per table since the last survey: compares the latest two row-count snapshots Resource Explorer stored for the database. Reads only what RE already stored; opens no connection to the database.

### Version Identifier
0.1.0

### Content Status
ACTIVE

### Category
Freshness

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| kind | step |
| source | ods |
| resource_types | database |
| annotation_type | ResourceMeasureAnnotation |
| questions | Q-0041 |
| purposes | Maintain |
| perspectives | Steward, Data Expert |
| credential_tier | none |
| inputs | ods |
| family | Freshness |
| executes_at | resource-explorer |
| re_analysis_step | database_staleness |
| function | database_staleness.step.run |
| package | trellis-step-database-staleness |
| entry_point | trellis.analytics:database_staleness |

___

## Create Governance Action Process Step
### Display Name
<Survey Definition> — Database Staleness

### Qualified Name
GovActionProcessStep::<SurveyDefinition>::database_staleness

### Description
Rows changed per table since the last survey: compares the latest two row-count snapshots Resource Explorer stored for the database. Reads only what RE already stored; opens no connection to the database.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| re_analysis_step | database_staleness |

___
