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
Analysis Survey — Repo Homepage

### Qualified Name
GovActionProcessStep::RepoAnalysisSurvey::repo_homepage

### Description
Finds the project's external website — GitHub's declared homepage first, falling back to pyproject.toml [project.urls], package.json or the README when that is empty (measured: 11 of 24 registered repos have no declared homepage). Surfaced in Scouting as a clickable link and published to Egeria as an ExternalReference linked to the repo.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_homepage |

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

## Create Governance Action Process Step
### Display Name
Analysis Survey — Repo Website Ingestion

### Qualified Name
GovActionProcessStep::RepoAnalysisSurvey::repo_website_ingestion

### Description
Ingests the project's documentation site into pgvector as web_docs_{host}, so Chat and Understanding can answer from the project's own documentation rather than only its source tree. Keyed on the site's host, not the repo slug — several repos in one project share one site and therefore one collection. Uses the site repo_homepage derived, collapsing versioned docs to the current release; skips entirely when the repo builds that site itself, since the source is already ingested in a better form.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_website_ingestion |

___

## Create Governance Action Process Step
### Display Name
Analysis Survey — Repo Chaoss Metrics

### Qualified Name
GovActionProcessStep::RepoAnalysisSurvey::repo_chaoss_metrics

### Description
CHAOSS community-health metrics over recorded commits — chiefly the elephant factor, the fewest contributors accounting for half the commits. Contributor COUNT calls deep_causality a five-person project; the distribution says one person wrote 98% of it.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_chaoss_metrics |

___

## Create Governance Action Process
### Display Name
Analysis Survey

### Qualified Name
GovActionProcess::RepoAnalysisSurvey

### Description
Everything Analysis extracts: dependencies, API/symbol structure, data-file profiles, sub-resource recommendations, and the two ingestion passes Chat and Understanding query — the repository's own source, and the project's documentation site. Prefixed by three prerequisite refresh steps: repo_git_statistics and repo_file_inventory for the same reason Assessment Survey needs them, plus repo_homepage, which is the only step that writes projects.homepage_url — without it repo_website_ingestion would ingest whatever site an earlier, unrelated run happened to derive, or none at all. This is deliberately the expensive tier: repo_rag_ingestion is compute_cost=high, repo_website_ingestion, repo_data_profiling and repo_symbol_extraction are medium, and the two ingestion steps both fetch. Because the cost filter exists, that is not binding — run with max_compute_cost='medium' for a structural pass that skips re-embedding, or max_fetch_cost='api' to skip both ingests.

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
GovActionProcessStep::RepoAnalysisSurvey::repo_homepage

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_homepage

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

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_rag_ingestion

### Next Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_website_ingestion

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_website_ingestion

### Next Governance Action Process Step
GovActionProcessStep::RepoAnalysisSurvey::repo_chaoss_metrics

### Guard
Any

___

## Link Element To Scope
### Target Element
Analysis Survey

### Scope Reference
What dependencies does this require?

___

## Link Element To Scope
### Target Element
Analysis Survey

### Scope Reference
What APIs and code symbols does it expose to callers?

___

## Link Element To Scope
### Target Element
Analysis Survey

### Scope Reference
What data files does it ship, and what shape are they?

___

## Link Element To Scope
### Target Element
Analysis Survey

### Scope Reference
Who maintains this repository?

___

## Link Element To Scope
### Target Element
Analysis Survey

### Scope Reference
How widely adopted and active is the community around this repository?

___

## Link Element To Scope
### Target Element
Analysis Survey

### Scope Reference
Is there a current, published, security analysis?

___

## Link Element To Scope
### Target Element
Analysis Survey

### Scope Reference
How concentrated is authorship — would the project survive losing its top contributors?

