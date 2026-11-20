## Create Governance Action Process Step
### Display Name
Filesystem Scouting Survey — Resource Reachability

### Qualified Name
GovActionProcessStep::FilesystemScoutingSurvey::resource_reachability

### Description
Check whether Egeria's Folder Survey or Resource Explorer's walk leads for this filesystem path.

### Produced Guards
survey-completed, survey-invalid, survey-failed, Any

### Ignore Multiple Triggers
true

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | File System Directory |
| re_analysis_step | resource_reachability |

___

## Create Governance Action Process Step
### Display Name
Filesystem Scouting Survey — Filesystem Inventory

### Qualified Name
GovActionProcessStep::FilesystemScoutingSurvey::filesystem_inventory

### Description
Walk the filesystem (counts, sizes, hidden/symlink/executable/writable flags, timestamps), flag inaccessible/unclassified files, and profile data file schemas.

### Produced Guards
survey-completed, survey-invalid, survey-failed, Any

### Ignore Multiple Triggers
true

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | File System Directory |
| re_analysis_step | filesystem_inventory |

___

## Create Governance Action Process Step
### Display Name
Filesystem Scouting Survey — File Profiles

### Qualified Name
GovActionProcessStep::FilesystemScoutingSurvey::file_profiles

### Description
Profile tabular data files (CSV, Excel, Parquet) for column schemas and types.

### Produced Guards
survey-completed, survey-invalid, survey-failed, Any

### Ignore Multiple Triggers
true

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | File System Directory |
| re_analysis_step | file_profiles |

___

## Create Governance Action Process
### Display Name
Filesystem Scouting Survey

### Qualified Name
GovActionProcess::FilesystemScoutingSurvey

### Description
The fast pass over a file system: reachability check (resource_reachability), walk (filesystem_inventory) to count files/folders and measure sizes, file_profiles for tabular data-file schema profiling. The reachability check decides whether Egeria's Folder Survey or Resource Explorer's walk leads.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| supported_technology_type | File System Directory |

___

## Link First Process Step
### Governance Action Process
GovActionProcess::FilesystemScoutingSurvey

### Governance Action Process Step
GovActionProcessStep::FilesystemScoutingSurvey::resource_reachability

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::FilesystemScoutingSurvey::resource_reachability

### Next Governance Action Process Step
GovActionProcessStep::FilesystemScoutingSurvey::filesystem_inventory

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::FilesystemScoutingSurvey::filesystem_inventory

### Next Governance Action Process Step
GovActionProcessStep::FilesystemScoutingSurvey::file_profiles

### Guard
Any

___

## Link Action to Action Executor
### Governance Action Type
GovActionProcessStep::FilesystemScoutingSurvey::resource_reachability

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-resource-reachability

### Description
Egeria dispatches GovActionProcessStep::FilesystemScoutingSurvey::resource_reachability to Resource Explorer's engine, which claims it and runs RE step resource_reachability.

___

## Link Action to Action Executor
### Governance Action Type
GovActionProcessStep::FilesystemScoutingSurvey::filesystem_inventory

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-filesystem-inventory

### Description
Egeria dispatches GovActionProcessStep::FilesystemScoutingSurvey::filesystem_inventory to Resource Explorer's engine, which claims it and runs RE step filesystem_inventory.

___

## Link Action to Action Executor
### Governance Action Type
GovActionProcessStep::FilesystemScoutingSurvey::file_profiles

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-file-profiles

### Description
Egeria dispatches GovActionProcessStep::FilesystemScoutingSurvey::file_profiles to Resource Explorer's engine, which claims it and runs RE step file_profiles.

___

## Link Element To Scope
### Target Element
Filesystem Scouting Survey

### Scope Reference
What kinds of files does this filesystem contain, and how much data is there?

___

## Link Element To Scope
### Target Element
Filesystem Scouting Survey

### Scope Reference
Does this filesystem contain recognizable tabular or structured data files, and what do their schemas look like?

___

## Link Element To Scope
### Target Element
Filesystem Scouting Survey

### Scope Reference
What is the shape of this file system: how deep, how wide, where does the bulk sit?

___

## Link Element To Scope
### Target Element
Filesystem Scouting Survey

### Scope Reference
Which tabular or structured files are here, with what columns and types?

