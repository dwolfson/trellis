## Create Governance Action Process Step
### Display Name
Scouting Survey — Repo Git Statistics

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_git_statistics

### Description
Refreshes project_stats (stars, forks, contributors, commit activity, releases, security config, deployments) from the GitHub API — the table eight other steps read. Replaces five independent StatsFetcher calls that each refreshed it separately in the same run.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_git_statistics |

___

## Create Governance Action Process Step
### Display Name
Scouting Survey — Repo File Inventory

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_file_inventory

### Description
Refreshes project_file_inventory from a fresh zipball — the table every file-shape step reads. Closes the gap where the inventory was written only by RAG ingestion/refresh_profile and never by a survey step, so a survey reported whatever an earlier, unrelated run had left behind.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_file_inventory |

___

## Create Governance Action Process Step
### Display Name
Scouting Survey — Repo Health

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_health

### Description
Activity, community, release-cadence, and freshness scoring from GitHub stats.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_health |

___

## Create Governance Action Process Step
### Display Name
Scouting Survey — Repo Language

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_language

### Description
Primary/secondary language and coarse project-type classification.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_language |

___

## Create Governance Action Process Step
### Display Name
Scouting Survey — Repo File Classification

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_file_classification

### Description
Classifies every file by type using filename/extension mapping (Egeria-enrichable).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_file_classification |

___

## Create Governance Action Process Step
### Display Name
Scouting Survey — Repo File Structure

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_file_structure

### Description
File counts, per-language breakdown, and top-level directory structure.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_file_structure |

___

## Create Governance Action Process Step
### Display Name
Scouting Survey — Repo Data Profiling

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_data_profiling

### Description
Inventories data files and profiles their schema (rows/columns/dtypes/nulls).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_data_profiling |

___

## Create Governance Action Process Step
### Display Name
Scouting Survey — Repo Homepage

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_homepage

### Description
Finds the project's external website — GitHub's declared homepage first, falling back to pyproject.toml [project.urls], package.json or the README when that is empty (measured: 11 of 24 registered repos have no declared homepage). Surfaced in Scouting as a clickable link and published to Egeria as an ExternalReference linked to the repo.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_homepage |

___

## Create Governance Action Process
### Display Name
Scouting Survey

### Qualified Name
GovActionProcess::RepoScoutingSurvey

### Description
Everything Scouting does, in one run: refresh git statistics and the file inventory, then score health, language shape, file classification and structure, data-file profiles and the project's external website. The union of Git Statistics Survey and Coarse Profile Survey, which remain available separately for the narrower/faster cases. Scouting-tier by construction — every step here belongs to Scouting, unlike the automate_full bundle which runs all 20 steps including Assessment- and Analysis-tier ones.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| supported_technology_type | Git Repository |
| survey_kind | scouting |

___

## Link First Process Step
### Governance Action Process
GovActionProcess::RepoScoutingSurvey

### Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_git_statistics

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_git_statistics

### Next Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_file_inventory

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_file_inventory

### Next Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_health

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_health

### Next Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_language

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_language

### Next Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_file_classification

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_file_classification

### Next Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_file_structure

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_file_structure

### Next Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_data_profiling

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_data_profiling

### Next Governance Action Process Step
GovActionProcessStep::RepoScoutingSurvey::repo_homepage

### Guard
Any

___

## Link Element To Scope
### Target Element
Scouting Survey

### Scope Reference
Is this repository actively maintained?

___

## Link Element To Scope
### Target Element
Scouting Survey

### Scope Reference
Who maintains this repository?

___

## Link Element To Scope
### Target Element
Scouting Survey

### Scope Reference
How widely adopted and active is the community around this repository?

___

## Link Element To Scope
### Target Element
Scouting Survey

### Scope Reference
How is it supported?

