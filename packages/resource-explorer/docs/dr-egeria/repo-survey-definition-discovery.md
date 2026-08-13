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

## Create Governance Action Process
### Display Name
Repo Discovery Survey

### Qualified Name
GovActionProcess::RepoDiscoverySurvey

### Description
Early-headlights signals for deciding whether to pursue this repo further — from data already collected by Scouting/Profile, zero new fetch. Deliberately minimal today; grows as new Discovery-tier analyses are built (see docs/discovery-automate-project-context-plan.md Part 2).

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
GovActionProcessStep::RepoDiscoverySurvey::repo_license_classification

