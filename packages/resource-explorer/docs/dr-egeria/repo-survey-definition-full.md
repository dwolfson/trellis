## Create Governance Action Process Step
### Display Name
Repo Full Survey — Repo File Structure

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_file_structure

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
Repo Full Survey — Repo File Size

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_file_size

### Description
Per-file sizes, total footprint, size-by-type, top-10 largest files.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_file_size |

___

## Create Governance Action Process Step
### Display Name
Repo Full Survey — Repo Language

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_language

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
Repo Full Survey — Repo Health

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_health

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
Repo Full Survey — Repo Dependency

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_dependency

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
Repo Full Survey — Repo Documentation

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_documentation

### Description
Presence of README/CHANGELOG/CONTRIBUTING/SECURITY and overall doc-quality label.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_documentation |

___

## Create Governance Action Process Step
### Display Name
Repo Full Survey — Repo Security

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_security

### Description
Presence of SECURITY.md, CI config, LICENSE — flags gaps as RFAs.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_security |

___

## Create Governance Action Process Step
### Display Name
Repo Full Survey — Repo License Classification

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_license_classification

### Description
Classifies the repo's SPDX license id into a risk tier (permissive/weak copyleft/strong copyleft/source-available/unknown).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_license_classification |

___

## Create Governance Action Process Step
### Display Name
Repo Full Survey — Repo Security Features

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_security_features

### Description
GitHub's native security feature toggles (Dependabot, secret scanning, etc.) — configuration state, not artifact presence.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_security_features |

___

## Create Governance Action Process Step
### Display Name
Repo Full Survey — Repo Ci Quality

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_ci_quality

### Description
Whether CI workflows actually run tests/lint/build, via a keyword scan of workflow content — not just whether a CI config exists.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_ci_quality |

___

## Create Governance Action Process Step
### Display Name
Repo Full Survey — Repo Maturity

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_maturity

### Description
Project age/lifecycle stage (nascent/emerging/established/mature), from repo_created_at — a CHAOSS-informed Discovery-tier signal.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_maturity |

___

## Create Governance Action Process Step
### Display Name
Repo Full Survey — Repo Conventions

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_conventions

### Description
Discovery-tier repo conventions: security policy content, build automation, deployment/Docker evidence, catalog self-description (Backstage-style), documentation breadth.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_conventions |

___

## Create Governance Action Process Step
### Display Name
Repo Full Survey — Repo Api Structure

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_api_structure

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
Repo Full Survey — Repo Data Profiling

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_data_profiling

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
Repo Full Survey — Repo File Classification

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_file_classification

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
Repo Full Survey — Repo Symbol Extraction

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_symbol_extraction

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
Repo Full Survey — Repo Sub Resource Survey

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_sub_resource_survey

### Description
Surveys file/folder characteristics to recommend which sub-resources are worthy of cataloging as their own Egeria assets (Assessment sub-resource cataloging plan) — survey only, does not catalog.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_sub_resource_survey |

___

## Create Governance Action Process
### Display Name
Repo Full Survey

### Qualified Name
GovActionProcess::RepoFullSurvey

### Description
Every current Resource Explorer repo analysis step, chained into one Survey Definition — the comprehensive bundle for an already-tracked repo, not Discovery's launch target. Regenerated by scripts/generate_repo_survey_definition.py from repo_survey_definition_adapter.py's STEP_REGISTRY, the single source of truth for what RE can actually run against a Git repository.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| supported_technology_type | Git Repository |
| survey_kind | automate_full |

___

## Link First Process Step
### Governance Action Process
GovActionProcess::RepoFullSurvey

### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_structure

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_structure

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_size

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_size

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_language

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_language

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_health

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_health

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_dependency

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_dependency

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_documentation

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_documentation

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_security

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_security

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_license_classification

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_license_classification

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_security_features

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_security_features

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_ci_quality

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_ci_quality

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_maturity

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_maturity

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_conventions

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_conventions

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_api_structure

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_api_structure

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_data_profiling

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_data_profiling

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_classification

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_file_classification

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_symbol_extraction

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_symbol_extraction

### Next Governance Action Process Step
GovActionProcessStep::RepoFullSurvey::repo_sub_resource_survey

### Guard
Any

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
Is this repository actively maintained?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
Who maintains this repository?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
How widely adopted and active is the community around this repository?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
How is it supported?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
What dependencies does this require?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
How well documented is it?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
Does it fit into our security infrastructure?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
Is there a current, published, security analysis?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
What explicit license does the repository use, and are there non-standard or copyleft terms?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
Is there a validation / deployment test for it?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
How mature is it?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
What deployment styles does this support?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
Does the repository publish a clear process for reporting security vulnerabilities?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
Does the repository have automated build tooling in place?

___

## Link Element To Scope
### Target Element
Repo Full Survey

### Scope Reference
Is this repository already self-described for an enterprise catalog (e.g. Backstage catalog-info.yaml)?

