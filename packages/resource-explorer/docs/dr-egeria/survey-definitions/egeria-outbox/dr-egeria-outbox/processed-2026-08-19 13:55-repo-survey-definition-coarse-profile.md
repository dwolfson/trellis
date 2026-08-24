
## Update Governance Action Process Step

### Governance Action Process Step Name 

Coarse Profile Survey — Repo Language

### Category
None

### Description
Primary/secondary language and coarse project-type classification.

### Display Name
Coarse Profile Survey — Repo Language

### GUID
7ca3d129-4e94-43ad-91f2-4e3ea8bf935b

### Legal
None

### Qualified Name
GovActionProcessStep::RepoCoarseProfile::repo_language

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

Coarse Profile Survey — Repo File Classification

### Category
None

### Description
Classifies every file by type using filename/extension mapping (Egeria-enrichable).

### Display Name
Coarse Profile Survey — Repo File Classification

### GUID
7b35e9b3-8f14-416f-b086-a936aefcd424

### Legal
None

### Qualified Name
GovActionProcessStep::RepoCoarseProfile::repo_file_classification

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

Coarse Profile Survey — Repo File Structure

### Category
None

### Description
File counts, per-language breakdown, and top-level directory structure.

### Display Name
Coarse Profile Survey — Repo File Structure

### GUID
220605d9-0cd4-45cc-9e6e-ab1b99fabf54

### Legal
None

### Qualified Name
GovActionProcessStep::RepoCoarseProfile::repo_file_structure

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

Coarse Profile Survey — Repo Data Profiling

### Category
None

### Description
Inventories data files and profiles their schema (rows/columns/dtypes/nulls).

### Display Name
Coarse Profile Survey — Repo Data Profiling

### GUID
fe7bca6e-f48c-4d86-ada5-93b6f57d4c88

### Legal
None

### Qualified Name
GovActionProcessStep::RepoCoarseProfile::repo_data_profiling

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

Coarse Profile Survey

### Category
None

### Description
Download the repo''s zipball once and profile what''s actually in it — file types, sizes, language shape, and any data-file schemas. Replaces the old bespoke ''Refresh coarse profile'' button/route (docs/survey-tab-unification-plan.md D2/D3) — this is now an ordinary Survey Definition candidate like every other survey type, dispatched through the same batched executor path (D1) that downloads the zipball once for the whole group instead of once per step.

### Display Name
Coarse Profile Survey

### GUID
a795a743-b721-467d-9342-a1d226136459

### Legal
None

### Qualified Name
GovActionProcess::RepoCoarseProfile

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

Linked 7ca3d129-4e94-43ad-91f2-4e3ea8bf935b as first process step of a795a743-b721-467d-9342-a1d226136459
___



## Link Next Process Step

Linked 7b35e9b3-8f14-416f-b086-a936aefcd424 as next process step after 7ca3d129-4e94-43ad-91f2-4e3ea8bf935b
___



## Link Next Process Step

Linked 220605d9-0cd4-45cc-9e6e-ab1b99fabf54 as next process step after 7b35e9b3-8f14-416f-b086-a936aefcd424
___



## Link Next Process Step

Linked fe7bca6e-f48c-4d86-ada5-93b6f57d4c88 as next process step after 220605d9-0cd4-45cc-9e6e-ab1b99fabf54
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




## Provenance:
 
- Derived from processing file repo-survey-definition-coarse-profile.md on 2026-08-19 13:55
