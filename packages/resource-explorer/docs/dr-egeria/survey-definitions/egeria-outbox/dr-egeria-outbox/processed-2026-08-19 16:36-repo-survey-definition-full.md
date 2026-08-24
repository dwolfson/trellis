
## Update Governance Action Process Step

### Governance Action Process Step Name 

Scouting - Full Survey — Repo File Inventory

### Category
None

### Description
Refreshes project_file_inventory from a fresh zipball — the table every file-shape step reads. Closes the gap where the inventory was written only by RAG ingestion/refresh_profile and never by a survey step, so a survey reported whatever an earlier, unrelated run had left behind.

### Display Name
Scouting - Full Survey — Repo File Inventory

### GUID
964a5140-ac43-4b23-a2cc-1ad2ba1611d6

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_file_inventory

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo File Structure

### Category
None

### Description
File counts, per-language breakdown, and top-level directory structure.

### Display Name
Scouting - Full Survey — Repo File Structure

### GUID
fa10261d-4c7b-4b34-a2bc-a9b54bde74a7

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_file_structure

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo File Size

### Category
None

### Description
Per-file sizes, total footprint, size-by-type, top-10 largest files.

### Display Name
Scouting - Full Survey — Repo File Size

### GUID
a665fecd-811d-4989-aa22-8a78c7bd31d0

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_file_size

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Language

### Category
None

### Description
Primary/secondary language and coarse project-type classification.

### Display Name
Scouting - Full Survey — Repo Language

### GUID
2f90d929-a8b4-4171-8bb6-b7fd6471fa34

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_language

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Health

### Category
None

### Description
Activity, community, release-cadence, and freshness scoring from GitHub stats.

### Display Name
Scouting - Full Survey — Repo Health

### GUID
9e7e8aa2-232f-4df6-af38-eb20f8380f73

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_health

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Dependency

### Category
None

### Description
Package dependencies per ecosystem (PyPI/npm/Maven).

### Display Name
Scouting - Full Survey — Repo Dependency

### GUID
53e049a6-bd50-4e58-97a2-626b2d4567c8

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_dependency

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Documentation

### Category
None

### Description
Presence of README/CHANGELOG/CONTRIBUTING/SECURITY and overall doc-quality label.

### Display Name
Scouting - Full Survey — Repo Documentation

### GUID
0a88a44c-44c7-41f7-956d-2a6d1586eaa6

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_documentation

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Security

### Category
None

### Description
Presence of SECURITY.md, CI config, LICENSE — flags gaps as RFAs.

### Display Name
Scouting - Full Survey — Repo Security

### GUID
265f6dce-8560-4aaa-8db7-d6901f3748c4

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_security

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo License Classification

### Category
None

### Description
Classifies the repo''s SPDX license id into a risk tier (permissive/weak copyleft/strong copyleft/source-available/unknown).

### Display Name
Scouting - Full Survey — Repo License Classification

### GUID
bbcc91e8-93ac-475b-ae37-414ddc9d4a6a

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_license_classification

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Security Features

### Category
None

### Description
GitHub''s native security feature toggles (Dependabot, secret scanning, etc.) — configuration state, not artifact presence.

### Display Name
Scouting - Full Survey — Repo Security Features

### GUID
8d131203-e724-43ce-a001-33e0f0c84935

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_security_features

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Ci Quality

### Category
None

### Description
Whether CI workflows actually run tests/lint/build, via a keyword scan of workflow content — not just whether a CI config exists.

### Display Name
Scouting - Full Survey — Repo Ci Quality

### GUID
ecd0ca34-15e3-4e8d-8272-bbe7c13f4363

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_ci_quality

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Maturity

### Category
None

### Description
Project age/lifecycle stage (nascent/emerging/established/mature), from repo_created_at — a CHAOSS-informed Discovery-tier signal.

### Display Name
Scouting - Full Survey — Repo Maturity

### GUID
84acb732-9bb6-4990-b826-e52c72f53405

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_maturity

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Conventions

### Category
None

### Description
Discovery-tier repo conventions: security policy content, build automation, deployment/Docker evidence, catalog self-description (Backstage-style), documentation breadth.

### Display Name
Scouting - Full Survey — Repo Conventions

### GUID
38790c8c-ce41-4c4b-81d8-13e436888694

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_conventions

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Api Structure

### Category
None

### Description
Public API surface (functions/classes/methods) per language.

### Display Name
Scouting - Full Survey — Repo Api Structure

### GUID
2473d2cd-540c-4075-aaff-157d5d661b11

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_api_structure

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Data Profiling

### Category
None

### Description
Inventories data files and profiles their schema (rows/columns/dtypes/nulls).

### Display Name
Scouting - Full Survey — Repo Data Profiling

### GUID
042a1772-6de9-4cc0-8803-21a68fc14c66

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_data_profiling

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo File Classification

### Category
None

### Description
Classifies every file by type using filename/extension mapping (Egeria-enrichable).

### Display Name
Scouting - Full Survey — Repo File Classification

### GUID
f8e258e1-beeb-4fd0-b157-ec0775f040c3

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_file_classification

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Symbol Extraction

### Category
None

### Description
Extracts class/function/method symbols (tree-sitter/ast) for every supported language, refreshing project_code_symbols/project_code_relationships — D5''s self-contained microflow closing the bug where those tables were only ever populated by RAG ingestion, never by a survey step.

### Display Name
Scouting - Full Survey — Repo Symbol Extraction

### GUID
e92b5505-9ad0-4b3a-a070-285df6621b41

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_symbol_extraction

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey — Repo Sub Resource Survey

### Category
None

### Description
Surveys file/folder characteristics to recommend which sub-resources are worthy of cataloging as their own Egeria assets (Assessment sub-resource cataloging plan) — survey only, does not catalog.

### Display Name
Scouting - Full Survey — Repo Sub Resource Survey

### GUID
b017330d-ceba-42c1-8827-6736e8fd5065

### Legal
None

### Qualified Name
GovActionProcessStep::RepoFullSurvey::repo_sub_resource_survey

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Scouting - Full Survey

### Category
None

### Description
Every current Resource Explorer repo analysis step, chained into one Survey Definition — the comprehensive bundle for an already-tracked repo, not Discovery''s launch target. Regenerated by scripts/generate_repo_survey_definition.py from repo_survey_definition_adapter.py''s STEP_REGISTRY, the single source of truth for what RE can actually run against a Git repository. Renamed from ''Repo Full Survey'' (per direct request, following the ''Scouting - Full Survey'' naming convention) — qualified_name unchanged, in-place rename of the existing element.

### Display Name
Scouting - Full Survey

### GUID
fb996a26-1bd4-4306-9bb5-db4352fda61f

### Legal
None

### Qualified Name
GovActionProcess::RepoFullSurvey

### Url
None

### Version Identifier
1.0

### Authors
None

### Content Status
ACTIVE

### Domain Identifier
All Domains

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

Linked 964a5140-ac43-4b23-a2cc-1ad2ba1611d6 as first process step of fb996a26-1bd4-4306-9bb5-db4352fda61f
___



## Link Next Process Step

Linked fa10261d-4c7b-4b34-a2bc-a9b54bde74a7 as next process step after 964a5140-ac43-4b23-a2cc-1ad2ba1611d6. Relationship GUID: 5243ab37-bab8-4002-97bf-4e61c8cf0413
___



## Link Next Process Step

Linked a665fecd-811d-4989-aa22-8a78c7bd31d0 as next process step after fa10261d-4c7b-4b34-a2bc-a9b54bde74a7. Relationship GUID: df1fc007-8dcb-4ede-9e0f-1c7ecd80faf5
___



## Link Next Process Step

Linked 2f90d929-a8b4-4171-8bb6-b7fd6471fa34 as next process step after a665fecd-811d-4989-aa22-8a78c7bd31d0. Relationship GUID: d892d2e1-e6f6-475c-bd33-8d5844961e51
___



## Link Next Process Step

Linked 9e7e8aa2-232f-4df6-af38-eb20f8380f73 as next process step after 2f90d929-a8b4-4171-8bb6-b7fd6471fa34. Relationship GUID: 4b82ff6c-dd45-47e8-875d-435bb72efbce
___



## Link Next Process Step

Linked 53e049a6-bd50-4e58-97a2-626b2d4567c8 as next process step after 9e7e8aa2-232f-4df6-af38-eb20f8380f73. Relationship GUID: 37a41cb7-b375-4e72-928a-7bc63eb072c1
___



## Link Next Process Step

Linked 0a88a44c-44c7-41f7-956d-2a6d1586eaa6 as next process step after 53e049a6-bd50-4e58-97a2-626b2d4567c8. Relationship GUID: 613c6bec-8a03-4a8e-8879-7b83220df179
___



## Link Next Process Step

Linked 265f6dce-8560-4aaa-8db7-d6901f3748c4 as next process step after 0a88a44c-44c7-41f7-956d-2a6d1586eaa6. Relationship GUID: 579038a2-48c2-4dc6-851d-fc283b80bcbb
___



## Link Next Process Step

Linked bbcc91e8-93ac-475b-ae37-414ddc9d4a6a as next process step after 265f6dce-8560-4aaa-8db7-d6901f3748c4. Relationship GUID: 21d85e30-fda3-4cd9-ad52-fd4c62bb12a1
___



## Link Next Process Step

Linked 8d131203-e724-43ce-a001-33e0f0c84935 as next process step after bbcc91e8-93ac-475b-ae37-414ddc9d4a6a. Relationship GUID: e7f51498-c8c9-4523-9a9d-13fda08a91e4
___



## Link Next Process Step

Linked ecd0ca34-15e3-4e8d-8272-bbe7c13f4363 as next process step after 8d131203-e724-43ce-a001-33e0f0c84935. Relationship GUID: 029c0dc4-4f85-4027-95f3-772c49e9dae4
___



## Link Next Process Step

Linked 84acb732-9bb6-4990-b826-e52c72f53405 as next process step after ecd0ca34-15e3-4e8d-8272-bbe7c13f4363. Relationship GUID: 594af024-d58b-42f1-b209-a0abf505f0f2
___



## Link Next Process Step

Linked 38790c8c-ce41-4c4b-81d8-13e436888694 as next process step after 84acb732-9bb6-4990-b826-e52c72f53405. Relationship GUID: 530152e7-b099-4720-8bba-0c634c9d2cd3
___



## Link Next Process Step

Linked 2473d2cd-540c-4075-aaff-157d5d661b11 as next process step after 38790c8c-ce41-4c4b-81d8-13e436888694. Relationship GUID: 455d2119-5c59-4c55-93c2-c3f32479577c
___



## Link Next Process Step

Linked 042a1772-6de9-4cc0-8803-21a68fc14c66 as next process step after 2473d2cd-540c-4075-aaff-157d5d661b11. Relationship GUID: 5c4c3dd1-9a70-4ef0-b183-f8bbbce9ae65
___



## Link Next Process Step

Linked f8e258e1-beeb-4fd0-b157-ec0775f040c3 as next process step after 042a1772-6de9-4cc0-8803-21a68fc14c66. Relationship GUID: c6a7504b-1389-474a-bdc8-9491d8b0b107
___



## Link Next Process Step

Linked e92b5505-9ad0-4b3a-a070-285df6621b41 as next process step after f8e258e1-beeb-4fd0-b157-ec0775f040c3. Relationship GUID: 30e16cb5-2af6-4718-8f8d-90b30110754b
___



## Link Next Process Step

Linked b017330d-ceba-42c1-8827-6736e8fd5065 as next process step after e92b5505-9ad0-4b3a-a070-285df6621b41. Relationship GUID: 4432cdf4-2cf0-439f-b1fa-f76548078604
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).
___



## Link Element To Scope

Linked fb996a26-1bd4-4306-9bb5-db4352fda61f (ScopedBy).



## Provenance:
 
- Derived from processing file repo-survey-definition-full.md on 2026-08-19 16:36
