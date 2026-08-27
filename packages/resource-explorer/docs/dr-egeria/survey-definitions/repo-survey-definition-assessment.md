## Create Governance Action Process Step
### Display Name
Assessment Survey — Repo Git Statistics

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_git_statistics

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
Assessment Survey — Repo File Inventory

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_file_inventory

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
Assessment Survey — Repo Documentation

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_documentation

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
Assessment Survey — Repo Security

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_security

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
Assessment Survey — Repo Security Features

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_security_features

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
Assessment Survey — Repo Ci Quality

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_ci_quality

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
Assessment Survey — Repo Cve Scan

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_cve_scan

### Description
Dependency advisories from OSV.dev, over dependencies the manifest parser already recorded. Reports coverage with the count: declared dependencies only, and only those with a pinned, parseable version.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_cve_scan |

___

## Create Governance Action Process Step
### Display Name
Assessment Survey — Repo Foss Scorecard

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_foss_scorecard

### Description
OpenSSF-Scorecard-shaped checks computed from data already held — an unevaluable check reports unknown and is excluded from the score, rather than scored zero as OpenSSF's own tool does.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_foss_scorecard |

___

## Create Governance Action Process Step
### Display Name
Assessment Survey — Repo Cii Badge

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_cii_badge

### Description
The real OpenSSF Best Practices (CII) badge, read from bestpractices.dev rather than estimated. Reports the level with the age of the self-assessment behind it, and keeps 'no badge' apart from 'could not ask'.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_cii_badge |

___

## Create Governance Action Process
### Display Name
Assessment Survey

### Qualified Name
GovActionProcess::RepoAssessmentSurvey

### Description
Everything Assessment evaluates: documentation coverage, security-policy hygiene, GitHub's native security-feature toggles and CI quality. Prefixed by the two prerequisite refresh steps — every step here reads project_stats and documentation also reads project_file_inventory, and neither table is written by an assessment-tier step, so without them the run scores whatever an earlier, unrelated survey left behind. Cheap apart from those prerequisites: the four evaluative steps are all zero-fetch/low-compute, so the survey's cost is almost entirely repo_git_statistics (api_heavy) and repo_file_inventory (download). Run with max_fetch_cost='none' to score against stored data instead.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| supported_technology_type | Git Repository |
| survey_kind | assessment |

___

## Link First Process Step
### Governance Action Process
GovActionProcess::RepoAssessmentSurvey

### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_git_statistics

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_git_statistics

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_file_inventory

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_file_inventory

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_documentation

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_documentation

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_security

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_security

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_security_features

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_security_features

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_ci_quality

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_ci_quality

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_cve_scan

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_cve_scan

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_foss_scorecard

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_foss_scorecard

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_cii_badge

### Guard
Any

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
How well documented is it?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
How is it supported?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
Does it fit into our security infrastructure?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
Is there a current, published, security analysis?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
Is there a validation / deployment test for it?

