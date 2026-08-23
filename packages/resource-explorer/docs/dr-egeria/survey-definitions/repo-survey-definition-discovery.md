## Create Governance Action Process Step
### Display Name
Repo Discovery Survey — Repo Classification

### Qualified Name
GovActionProcessStep::RepoDiscoverySurvey::repo_classification

### Description
What the repo represents (7 roles, ranked, multi-valued), where each artifact its role implies actually lives, and whether architecture recovery is worth running at all (design §5.5b).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_classification |

___

## Create Governance Action Process Step
### Display Name
Repo Discovery Survey — Repo License Classification

### Qualified Name
GovActionProcessStep::RepoDiscoverySurvey::repo_license_classification

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
Repo Discovery Survey — Repo Maturity

### Qualified Name
GovActionProcessStep::RepoDiscoverySurvey::repo_maturity

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
Repo Discovery Survey — Repo Conventions

### Qualified Name
GovActionProcessStep::RepoDiscoverySurvey::repo_conventions

### Description
Discovery-tier repo conventions: security policy content, build automation, deployment/Docker evidence, catalog self-description (Backstage-style), documentation breadth.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | Git Repository |
| re_analysis_step | repo_conventions |

___

## Create Governance Action Process
### Display Name
Repo Discovery Survey

### Qualified Name
GovActionProcess::RepoDiscoverySurvey

### Description
Early-headlights signals for deciding whether to pursue this repo further — from data already collected by Scouting/Profile, zero new fetch. Grown by Part 2 (docs/discovery-automate-project-context-plan.md) with maturity/lifecycle-stage and repo-convention signals (security policy, build automation, deployment/Docker evidence, catalog self-description, documentation breadth).

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| supported_technology_type | Git Repository |
| survey_kind | discovery |

___

## Link First Process Step
### Governance Action Process
GovActionProcess::RepoDiscoverySurvey

### Governance Action Process Step
GovActionProcessStep::RepoDiscoverySurvey::repo_classification

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoDiscoverySurvey::repo_classification

### Next Governance Action Process Step
GovActionProcessStep::RepoDiscoverySurvey::repo_license_classification

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoDiscoverySurvey::repo_license_classification

### Next Governance Action Process Step
GovActionProcessStep::RepoDiscoverySurvey::repo_maturity

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::RepoDiscoverySurvey::repo_maturity

### Next Governance Action Process Step
GovActionProcessStep::RepoDiscoverySurvey::repo_conventions

### Guard
Any

___

## Link Element To Scope
### Target Element
Repo Discovery Survey

### Scope Reference
What explicit license does the repository use, and are there non-standard or copyleft terms?

___

## Link Element To Scope
### Target Element
Repo Discovery Survey

### Scope Reference
How mature is it?

___

## Link Element To Scope
### Target Element
Repo Discovery Survey

### Scope Reference
What deployment styles does this support?

___

## Link Element To Scope
### Target Element
Repo Discovery Survey

### Scope Reference
Is there a validation / deployment test for it?

___

## Link Element To Scope
### Target Element
Repo Discovery Survey

### Scope Reference
How well documented is it?

___

## Link Element To Scope
### Target Element
Repo Discovery Survey

### Scope Reference
Is there a current, published, security analysis?

___

## Link Element To Scope
### Target Element
Repo Discovery Survey

### Scope Reference
Does the repository publish a clear process for reporting security vulnerabilities?

___

## Link Element To Scope
### Target Element
Repo Discovery Survey

### Scope Reference
Does the repository have automated build tooling in place?

___

## Link Element To Scope
### Target Element
Repo Discovery Survey

### Scope Reference
Is this repository already self-described for an enterprise catalog (e.g. Backstage catalog-info.yaml)?

