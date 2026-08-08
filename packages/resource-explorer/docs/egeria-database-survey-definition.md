# Postgres SQL Analysis Survey Definition (Egeria Database)

This document contains a Dr. Egeria plan that authors a two-step Survey Definition for the `egeria` PostgreSQL database server. This plan registers the process in Egeria's catalog using standard Egeria Advisor commands.

---

## Create Governance Action Process Step
### Display Name
Egeria DB Survey Step 1 — Schema and Stats

### Qualified Name
GovActionProcessStep::EgeriaDbSurvey::SchemaAndStats

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | PostgreSQL Database |
| re_analysis_step | postgres_schema_and_stats |

___

## Create Governance Action Process Step
### Display Name
Egeria DB Survey Step 2 — SQL Analysis and Lineage

### Qualified Name
GovActionProcessStep::EgeriaDbSurvey::SqlAnalysis

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | PostgreSQL Database |
| re_analysis_step | sql_analysis |

___

## Create Governance Action Process
### Display Name
Egeria Database SQL Analysis Survey

### Qualified Name
GovActionProcess::EgeriaDbSurvey

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| supported_technology_type | PostgreSQL Database |

___

## Link First Process Step
### Governance Action Process
GovActionProcess::EgeriaDbSurvey

### Governance Action Process Step
GovActionProcessStep::EgeriaDbSurvey::SchemaAndStats

___

## Link Next Process Step
### Governance Action Process Step 
GovActionProcessStep::EgeriaDbSurvey::SchemaAndStats

### Next Governance Action Process Step 
GovActionProcessStep::EgeriaDbSurvey::SqlAnalysis

### Guard
Any
