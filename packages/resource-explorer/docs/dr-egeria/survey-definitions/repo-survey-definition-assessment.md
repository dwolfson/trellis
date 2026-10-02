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
Assessment Survey — Repo Secret Scan

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_secret_scan

### Description
Committed-credential scan over HEAD content, using a VENDORED gitleaks ruleset (222 rules, MIT, provenance recorded). Reports what it matched AND which ruleset version it matched with — never 'no secrets', only 'no matches against this ruleset in HEAD'.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | prefect |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_secret_scan |

___

## Create Governance Action Process Step
### Display Name
Assessment Survey — Repo Telemetry Scan

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_telemetry_scan

### Description
Telemetry / phone-home indicators: known SDK imports and literal outbound endpoints, paired with whether the project discloses them. Never labels an ordinary API client as telemetry.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_telemetry_scan |

___

## Create Governance Action Process Step
### Display Name
Assessment Survey — Repo Contribution Provenance

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_contribution_provenance

### Description
CLA/DCO provenance, kept as two separate questions: whether sign-off is STATED, and whether it is ENFORCED. Config presence alone is reported `partial`, never `pass`.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_contribution_provenance |

___

## Create Governance Action Process Step
### Display Name
Assessment Survey — Repo Sla Content

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_sla_content

### Description
Whether the project publishes support or service-level commitments. Deliberately NEUTRAL (present/absent, not pass/gap): most repositories legitimately publish none, and absence alone never raises an action.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_sla_content |

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

## Create Governance Action Process Step
### Display Name
Assessment Survey — Repo Security Summary

### Qualified Name
GovActionProcessStep::RepoAssessmentSurvey::repo_security_summary

### Description
Reduces the security family's stored findings to one topic summary. Measures nothing itself — it reads what the other security steps wrote, so it belongs LAST in any survey that runs them. Reports coverage and the age of its oldest input alongside the verdict, and refuses a verdict at all below four inputs.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_security_summary |

___

## Create Governance Action Process
### Display Name
Assessment Survey

### Qualified Name
GovActionProcess::RepoAssessmentSurvey

### Description
Everything Assessment evaluates: documentation coverage, security-policy hygiene, GitHub's native security-feature toggles, CI quality, dependency advisories, and the four compliance and disclosure analyses — committed secrets, telemetry/phone-home, CLA/DCO contribution provenance and published SLA/support content (added 2026-10-02 on the project owner's decision, so a repo that is assessed gets them rather than only a repo someone separately ran the Compliance Survey on). Prefixed by the two prerequisite refresh steps — every step here reads project_stats and documentation also reads project_file_inventory, and the four compliance steps each declare has_file_inventory and read the SAME zipball repo_file_inventory already downloads (one download per run, shared), so they add no new fetch, no clone and no new credential — without the prefix the run scores whatever an earlier, unrelated survey left behind. The four sit after repo_cve_scan and before the two reducers (repo_foss_scorecard, repo_security_summary), which stay at the end. No longer cheap: repo_secret_scan is compute_cost='high' (222 regex rules over every tracked file; 277.3s measured on egeria_git, 330.8s median in docs/funnel-cost-measured.md) and Prefect-routed, repo_telemetry_scan is medium (24.1s median, n=3), repo_sla_content measured 20.2s (n=3) and repo_contribution_provenance is declared low and unmeasured. Run with max_compute_cost='medium' to leave out the secret scan, or max_fetch_cost='none' to score against stored data instead.

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
GovActionProcessStep::RepoAssessmentSurvey::repo_secret_scan

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_secret_scan

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_telemetry_scan

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_telemetry_scan

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_contribution_provenance

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_contribution_provenance

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_sla_content

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_sla_content

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

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_cii_badge

### Next Governance Action Process Step
GovActionProcessStep::RepoAssessmentSurvey::repo_security_summary

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
Does the repository publish a clear process for reporting security vulnerabilities?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
Is there a validation / deployment test for it?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
Does the repository have automated build tooling in place?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
Are there outstanding CVEs?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
How does the repository handle secrets, credentials, and sensitive configurations?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
Does the software contain telemetry, phone-home mechanisms, or external metrics tracking?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
Is intellectual property (IP) provenance managed via CLA or DCO?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
Is this repository actively maintained?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
How does it score against OpenSSF Scorecard-style criteria?

___

## Link Element To Scope
### Target Element
Assessment Survey

### Scope Reference
Does it hold an OpenSSF Best Practices (CII) badge, and how current is the self-assessment behind it?

