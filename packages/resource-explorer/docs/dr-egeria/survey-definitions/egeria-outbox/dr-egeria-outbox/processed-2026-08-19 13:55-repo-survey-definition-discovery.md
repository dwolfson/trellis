
## Update Governance Action Process Step

### Governance Action Process Step Name 

Repo Discovery Survey — Repo License Classification

### Category
None

### Description
Classifies the repo''s SPDX license id into a risk tier (permissive/weak copyleft/strong copyleft/source-available/unknown).

### Display Name
Repo Discovery Survey — Repo License Classification

### GUID
f3928830-654d-4dc4-ab47-a7b228a6ed88

### Legal
None

### Qualified Name
GovActionProcessStep::RepoDiscoverySurvey::repo_license_classification

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
ALL

### Implications
None

### Importance
None

### Outcomes
None

### Results
None

### Scope
None

### Summary
None

### Usage
None

### Implementation Description
None

### Produced Guards
None

### Wait Time
0

### Ignore Multiple Triggers
False


___


## Update Governance Action Process Step

### Governance Action Process Step Name 

Repo Discovery Survey — Repo Maturity

### Category
None

### Description
Project age/lifecycle stage (nascent/emerging/established/mature), from repo_created_at — a CHAOSS-informed Discovery-tier signal.

### Display Name
Repo Discovery Survey — Repo Maturity

### GUID
2b92ac46-28c8-4ce2-bfc1-836be6761018

### Legal
None

### Qualified Name
GovActionProcessStep::RepoDiscoverySurvey::repo_maturity

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
ALL

### Implications
None

### Importance
None

### Outcomes
None

### Results
None

### Scope
None

### Summary
None

### Usage
None

### Implementation Description
None

### Produced Guards
None

### Wait Time
0

### Ignore Multiple Triggers
False


___


## Update Governance Action Process Step

### Governance Action Process Step Name 

Repo Discovery Survey — Repo Conventions

### Category
None

### Description
Discovery-tier repo conventions: security policy content, build automation, deployment/Docker evidence, catalog self-description (Backstage-style), documentation breadth.

### Display Name
Repo Discovery Survey — Repo Conventions

### GUID
812ca92a-02e2-43f7-91ed-978ab3b91a6b

### Legal
None

### Qualified Name
GovActionProcessStep::RepoDiscoverySurvey::repo_conventions

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
ALL

### Implications
None

### Importance
None

### Outcomes
None

### Results
None

### Scope
None

### Summary
None

### Usage
None

### Implementation Description
None

### Produced Guards
None

### Wait Time
0

### Ignore Multiple Triggers
False


___


## Update Governance Action Process

### Governance Action Process Name 

Repo Discovery Survey

### Category
None

### Description
Early-headlights signals for deciding whether to pursue this repo further — from data already collected by Scouting/Profile, zero new fetch. Grown by Part 2 (docs/discovery-automate-project-context-plan.md) with maturity/lifecycle-stage and repo-convention signals (security policy, build automation, deployment/Docker evidence, catalog self-description, documentation breadth).

### Display Name
Repo Discovery Survey

### GUID
13d1a18f-d8b2-4f74-9b7a-6ea8292c8de3

### Legal
None

### Qualified Name
GovActionProcess::RepoDiscoverySurvey

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
ALL

### Implications
None

### Importance
None

### Outcomes
None

### Results
None

### Scope
None

### Summary
None

### Usage
None

### Implementation Description
None


___



## Link First Process Step

Linked f3928830-654d-4dc4-ab47-a7b228a6ed88 as first process step of 13d1a18f-d8b2-4f74-9b7a-6ea8292c8de3
___



## Link Next Process Step

Linked 2b92ac46-28c8-4ce2-bfc1-836be6761018 as next process step after f3928830-654d-4dc4-ab47-a7b228a6ed88
___



## Link Next Process Step

Linked 812ca92a-02e2-43f7-91ed-978ab3b91a6b as next process step after 2b92ac46-28c8-4ce2-bfc1-836be6761018
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




## Provenance:
 
- Derived from processing file repo-survey-definition-discovery.md on 2026-08-19 13:55
