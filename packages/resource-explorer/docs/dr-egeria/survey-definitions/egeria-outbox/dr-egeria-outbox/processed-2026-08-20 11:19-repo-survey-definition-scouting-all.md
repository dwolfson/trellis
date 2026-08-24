
## Update Governance Action Process Step

### Governance Action Process Step Name 

Scouting Survey — Repo Git Statistics

### Category
None

### Description
Refreshes project_stats (stars, forks, contributors, commit activity, releases, security config, deployments) from the GitHub API — the table eight other steps read. Replaces five independent StatsFetcher calls that each refreshed it separately in the same run.

### Display Name
Scouting Survey — Repo Git Statistics

### GUID
4793191e-79ab-482d-810e-fa77e54eef58

### Legal
None

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_git_statistics

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

Scouting Survey — Repo File Inventory

### Category
None

### Description
Refreshes project_file_inventory from a fresh zipball — the table every file-shape step reads. Closes the gap where the inventory was written only by RAG ingestion/refresh_profile and never by a survey step, so a survey reported whatever an earlier, unrelated run had left behind.

### Display Name
Scouting Survey — Repo File Inventory

### GUID
da23bebd-8b0b-4c81-8078-e4fe784031db

### Legal
None

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_file_inventory

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

Scouting Survey — Repo Health

### Category
None

### Description
Activity, community, release-cadence, and freshness scoring from GitHub stats.

### Display Name
Scouting Survey — Repo Health

### GUID
fa128de6-ea55-460f-9043-fb2e3a06e646

### Legal
None

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_health

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

Scouting Survey — Repo Language

### Category
None

### Description
Primary/secondary language and coarse project-type classification.

### Display Name
Scouting Survey — Repo Language

### GUID
6817c8db-11d1-413f-86e7-fb8a004b2a0d

### Legal
None

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_language

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

Scouting Survey — Repo File Classification

### Category
None

### Description
Classifies every file by type using filename/extension mapping (Egeria-enrichable).

### Display Name
Scouting Survey — Repo File Classification

### GUID
3e4accff-e607-4488-a463-22b04bd0a5ca

### Legal
None

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_file_classification

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

Scouting Survey — Repo File Structure

### Category
None

### Description
File counts, per-language breakdown, and top-level directory structure.

### Display Name
Scouting Survey — Repo File Structure

### GUID
9859516e-bc4b-4cae-a20a-c6e5d402598b

### Legal
None

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_file_structure

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

Scouting Survey — Repo Data Profiling

### Category
None

### Description
Inventories data files and profiles their schema (rows/columns/dtypes/nulls).

### Display Name
Scouting Survey — Repo Data Profiling

### GUID
82ef409a-d43c-4461-bca3-1559e1dbc976

### Legal
None

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_data_profiling

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

Scouting Survey — Repo Homepage

### Category
None

### Description
Finds the project's external website — GitHub's declared homepage first, falling back to pyproject.toml [project.urls], package.json or the README when that is empty (measured: 11 of 24 registered repos have no declared homepage). Surfaced in Scouting as a clickable link and published to Egeria as an ExternalReference linked to the repo.

### Display Name
Scouting Survey — Repo Homepage

### GUID
bfa402a5-4e8b-4d11-a1bd-f2f116595cc4

### Legal
None

### Qualified Name
GovActionProcessStep::RepoScoutingSurvey::repo_homepage

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

Scouting Survey

### Category
None

### Description
Everything Scouting does, in one run: refresh git statistics and the file inventory, then score health, language shape, file classification and structure, data-file profiles and the project's external website. The union of Git Statistics Survey and Coarse Profile Survey, which remain available separately for the narrower/faster cases. Scouting-tier by construction — every step here belongs to Scouting, unlike the automate_full bundle which runs all 20 steps including Assessment- and Analysis-tier ones.

### Display Name
Scouting Survey

### GUID
bd8ff06e-1074-4654-a460-d064bcf1f855

### Legal
None

### Qualified Name
GovActionProcess::RepoScoutingSurvey

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

Linked 4793191e-79ab-482d-810e-fa77e54eef58 as first process step of bd8ff06e-1074-4654-a460-d064bcf1f855
___



## Link Next Process Step

Linked da23bebd-8b0b-4c81-8078-e4fe784031db as next process step after 4793191e-79ab-482d-810e-fa77e54eef58. Relationship GUID: e324a7d8-42d0-42c8-9569-554738d7e76a
___



## Link Next Process Step

Linked fa128de6-ea55-460f-9043-fb2e3a06e646 as next process step after da23bebd-8b0b-4c81-8078-e4fe784031db. Relationship GUID: 7a65c38a-0f99-4111-bbdf-444082a746db
___



## Link Next Process Step

Linked 6817c8db-11d1-413f-86e7-fb8a004b2a0d as next process step after fa128de6-ea55-460f-9043-fb2e3a06e646. Relationship GUID: 0b9a267a-5f61-49d1-9218-9fa1446f1682
___



## Link Next Process Step

Linked 3e4accff-e607-4488-a463-22b04bd0a5ca as next process step after 6817c8db-11d1-413f-86e7-fb8a004b2a0d. Relationship GUID: cc5ca4d7-4107-4e58-b4fd-ffc1b8cb9e41
___



## Link Next Process Step

Linked 9859516e-bc4b-4cae-a20a-c6e5d402598b as next process step after 3e4accff-e607-4488-a463-22b04bd0a5ca. Relationship GUID: 8aff6d7e-ab87-4024-bf75-6a3f81ba2ab3
___



## Link Next Process Step

Linked 82ef409a-d43c-4461-bca3-1559e1dbc976 as next process step after 9859516e-bc4b-4cae-a20a-c6e5d402598b. Relationship GUID: d92c2d47-b783-426b-a626-a7bfff02229a
___



## Link Next Process Step

Linked bfa402a5-4e8b-4d11-a1bd-f2f116595cc4 as next process step after 82ef409a-d43c-4461-bca3-1559e1dbc976. Relationship GUID: e41639d9-a542-45ac-9694-9017f137b674
___



## Link Element To Scope

Linked bd8ff06e-1074-4654-a460-d064bcf1f855 (ScopedBy).
___



## Link Element To Scope

Linked bd8ff06e-1074-4654-a460-d064bcf1f855 (ScopedBy).
___



## Link Element To Scope

Linked bd8ff06e-1074-4654-a460-d064bcf1f855 (ScopedBy).
___



## Link Element To Scope

Linked bd8ff06e-1074-4654-a460-d064bcf1f855 (ScopedBy).



## Provenance:
 
- Derived from processing file repo-survey-definition-scouting-all.md on 2026-08-20 11:19
