## Create Governance Action Process Step
### Display Name
Coarse Profile Survey — Repo File Inventory

### Qualified Name
GovActionProcessStep::RepoCoarseProfile::repo_file_inventory

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
Coarse Profile Survey — Repo Manifest Parse

### Qualified Name
GovActionProcessStep::RepoCoarseProfile::repo_manifest_parse

### Description
Parses dependency manifests, CI workflow content, supply-chain signals and repo-convention signals from a freshly extracted zipball, refreshing project_dependencies and project_analysis_findings (kind="ci_quality"/"repo_conventions"/"supply_chain") — the three tables previously written only by full ingestion (and, for the latter two, refresh_profile), never by a survey step.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_manifest_parse |

___

## Create Governance Action Process Step
### Display Name
Coarse Profile Survey — Repo Language

### Qualified Name
GovActionProcessStep::RepoCoarseProfile::repo_language

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
Coarse Profile Survey — Repo File Classification

### Qualified Name
GovActionProcessStep::RepoCoarseProfile::repo_file_classification

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
Coarse Profile Survey — Repo File Structure

### Qualified Name
GovActionProcessStep::RepoCoarseProfile::repo_file_structure

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
Coarse Profile Survey — Repo Data Profiling

### Qualified Name
GovActionProcessStep::RepoCoarseProfile::repo_data_profiling

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
Coarse Profile Survey — Repo Homepage

### Qualified Name
GovActionProcessStep::RepoCoarseProfile::repo_homepage

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
Coarse Profile Survey

### Qualified Name
GovActionProcess::RepoCoarseProfile

### Description
Download the repo's zipball once and profile what's actually in it — file types, sizes, language shape, and any data-file schemas. Replaces the old bespoke 'Refresh coarse profile' button/route (docs/survey-tab-unification-plan.md D2/D3) — this is now an ordinary Survey Definition candidate like every other survey type, dispatched through the same batched executor path (D1) that downloads the zipball once for the whole group instead of once per step.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| supported_technology_type | Git Repository |
| survey_kind | scouting |

___

## Link First Process Step
### Governance Action Process
GovActionProcess::RepoCoarseProfile

### Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_file_inventory

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_file_inventory

### Next Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_manifest_parse

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_manifest_parse

### Next Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_language

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_language

### Next Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_file_classification

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_file_classification

### Next Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_file_structure

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_file_structure

### Next Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_data_profiling

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_data_profiling

### Next Governance Action Process Step
GovActionProcessStep::RepoCoarseProfile::repo_homepage

### Guard
Any

___

## Link Element To Scope
### Target Element
Coarse Profile Survey

### Scope Reference
What languages and file types make up this repository?

___

## Link Element To Scope
### Target Element
Coarse Profile Survey

### Scope Reference
How much code is there? How complex?

___

## Link Element To Scope
### Target Element
Coarse Profile Survey

### Scope Reference
What data files does it ship, and what shape are they?

___

## Link Element To Scope
### Target Element
Coarse Profile Survey

### Scope Reference
Is this repository actively maintained?

___

## Link Element To Scope
### Target Element
Coarse Profile Survey

### Scope Reference
What does this repository do?

