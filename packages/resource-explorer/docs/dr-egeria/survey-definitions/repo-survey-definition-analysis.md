## Create Governance Action Process Step
### Display Name
Analysis Survey — Repo Git Statistics

### Qualified Name
GovActionProcessStep::RepoAnalysisSurvey::repo_git_statistics

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
Analysis Survey — Repo File Inventory

### Qualified Name
GovActionProcessStep::RepoAnalysisSurvey::repo_file_inventory

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
Analysis Survey — Repo Dependency

### Qualified Name
GovActionProcessStep::RepoAnalysisSurvey::repo_dependency

### Description
Package dependencies per ecosystem (PyPI/npm/Maven).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_dependency |

___

## Create Governance Action Process Step
### Display Name
Analysis Survey — Repo Api Structure

### Qualified Name
GovActionProcessStep::RepoAnalysisSurvey::repo_api_structure

### Description
Public API surface (functions/classes/methods) per language.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_api_structure |

___

## Create Governance Action Process Step
### Display Name
Analysis Survey — Repo Data Profiling

### Qualified Name
GovActionProcessStep::RepoAnalysisSurvey::repo_data_profiling

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
Analysis Survey — Repo Symbol Extraction

### Qualified Name
GovActionProcessStep::RepoAnalysisSurvey::repo_symbol_extraction

### Description
Extracts class/function/method symbols (tree-sitter/ast) for every supported language, refreshing project_code_symbols/project_code_relationships — D5's self-contained microflow closing the bug where those tables were only ever populated by RAG ingestion, never by a survey step.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_symbol_extraction |

___

## Create Governance Action Process Step
### Display Name
Analysis Survey — Repo Sub Resource Survey

### Qualified Name
GovActionProcessStep::RepoAnalysisSurvey::repo_sub_resource_survey

### Description
Surveys file/folder characteristics to recommend which sub-resources are worthy of cataloging as their own Egeria assets (Assessment sub-resource cataloging plan) — survey only, does not catalog.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_sub_resource_survey |

___

## Create Governance Action Process Step
### Display Name
Analysis Survey — Repo Rag Ingestion

### Qualified Name
GovActionProcessStep::RepoAnalysisSurvey::repo_rag_ingestion

### Description
Refreshes the project's pgvector collections via IncrementalIndexer — the queryable representation Chat, the query router and every RAG-backed answer read, previously built only at registration, on webhook or from a bespoke route branch and never by a survey step. A no-op when the repository's last indexed commit is unchanged.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_rag_ingestion |

___

## Create Governance Action Process
### Display Name
Analysis Survey

### Qualified Name
GovActionProcess::RepoAnalysisSurvey

### Description
Everything Analysis extracts: dependencies, API/symbol structure, data-file profiles, sub-resource recommendations, and the pgvector re-embedding that Chat and Understanding query. Prefixed by the same two prerequisite refresh steps as Assessment Survey, for the same reason. This is deliberately the expensive tier — repo_rag_ingestion is compute_cost=high and repo_data_profiling/repo_symbol_extraction are medium — and it includes ingestion per the rag-ingestion plan's D6, which named an Analysis Survey as its natural home. Because the cost filter exists, that inclusion is not binding: run with max_compute_cost='medium' for a structural pass that skips re-embedding.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| supported_technology_type | Git Repository |
| survey_kind | analysis |

___

## Link First Process Step
### Governance Action Process
GovActionProcess::RepoAnalysisSurvey

### Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_git_statistics

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_git_statistics

### Next Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_file_inventory

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_file_inventory

### Next Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_dependency

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_dependency

### Next Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_api_structure

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_api_structure

### Next Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_data_profiling

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_data_profiling

### Next Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_symbol_extraction

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_symbol_extraction

### Next Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_sub_resource_survey

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_sub_resource_survey

### Next Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_rag_ingestion

### Guard
Any

___

## Link Element To Scope
### Target Element
Analysis Survey

### Scope Reference
What dependencies does this require?

