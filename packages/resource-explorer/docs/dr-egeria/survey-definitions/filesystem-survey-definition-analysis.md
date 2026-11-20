## Create Governance Action Process Step
### Display Name
Filesystem Analysis Survey — Resource Reachability

### Qualified Name
GovActionProcessStep::FilesystemAnalysisSurvey::resource_reachability

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
Filesystem Analysis Survey — Filesystem Inventory

### Qualified Name
GovActionProcessStep::FilesystemAnalysisSurvey::filesystem_inventory

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
Filesystem Analysis Survey — File Profiles

### Qualified Name
GovActionProcessStep::FilesystemAnalysisSurvey::file_profiles

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

## Create Governance Action Process Step
### Display Name
Filesystem Analysis Survey — Narrative Docs

### Qualified Name
GovActionProcessStep::FilesystemAnalysisSurvey::narrative_docs

### Description
Read narrative files (README, docs) for content extraction.

### Produced Guards
survey-completed, survey-invalid, survey-failed, Any

### Ignore Multiple Triggers
true

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | File System Directory |
| re_analysis_step | narrative_docs |

___

## Create Governance Action Process Step
### Display Name
Filesystem Analysis Survey — File Data Class Match

### Qualified Name
GovActionProcessStep::FilesystemAnalysisSurvey::file_data_class_match

### Description
Match file columns to data classes from Egeria's catalog.

### Produced Guards
survey-completed, survey-invalid, survey-failed, Any

### Ignore Multiple Triggers
true

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| executes_at | resource-explorer |
| supported_technology_type | File System Directory |
| re_analysis_step | file_data_class_match |

___

## Create Governance Action Process
### Display Name
Filesystem Analysis Survey

### Qualified Name
GovActionProcess::FilesystemAnalysisSurvey

### Description
Every catalog-intent: analysis file system analyses — resource_reachability (check whether Egeria or RE leads), filesystem_inventory (walk the filesystem), file_profiles (tabular data-file schema profiling), narrative_docs (read narrative files for content), file_data_class_match (match columns to data classes). The reachability check decides whether Egeria's Folder Survey or Resource Explorer's walk leads.

### Additional Properties
| Parameter Name | Parameter Value |
|---|---|
| supported_technology_type | File System Directory |

___

## Link First Process Step
### Governance Action Process
GovActionProcess::FilesystemAnalysisSurvey

### Governance Action Process Step
GovActionProcessStep::FilesystemAnalysisSurvey::resource_reachability

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::FilesystemAnalysisSurvey::resource_reachability

### Next Governance Action Process Step
GovActionProcessStep::FilesystemAnalysisSurvey::filesystem_inventory

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::FilesystemAnalysisSurvey::filesystem_inventory

### Next Governance Action Process Step
GovActionProcessStep::FilesystemAnalysisSurvey::file_profiles

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::FilesystemAnalysisSurvey::file_profiles

### Next Governance Action Process Step
GovActionProcessStep::FilesystemAnalysisSurvey::narrative_docs

### Guard
Any

___

## Link Next Process Step
### Governance Action Process Step
GovActionProcessStep::FilesystemAnalysisSurvey::narrative_docs

### Next Governance Action Process Step
GovActionProcessStep::FilesystemAnalysisSurvey::file_data_class_match

### Guard
Any

___

## Link Action to Action Executor
### Governance Action Type
GovActionProcessStep::FilesystemAnalysisSurvey::resource_reachability

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-resource-reachability

### Description
Egeria dispatches GovActionProcessStep::FilesystemAnalysisSurvey::resource_reachability to Resource Explorer's engine, which claims it and runs RE step resource_reachability.

___

## Link Action to Action Executor
### Governance Action Type
GovActionProcessStep::FilesystemAnalysisSurvey::filesystem_inventory

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-filesystem-inventory

### Description
Egeria dispatches GovActionProcessStep::FilesystemAnalysisSurvey::filesystem_inventory to Resource Explorer's engine, which claims it and runs RE step filesystem_inventory.

___

## Link Action to Action Executor
### Governance Action Type
GovActionProcessStep::FilesystemAnalysisSurvey::file_profiles

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-file-profiles

### Description
Egeria dispatches GovActionProcessStep::FilesystemAnalysisSurvey::file_profiles to Resource Explorer's engine, which claims it and runs RE step file_profiles.

___

## Link Action to Action Executor
### Governance Action Type
GovActionProcessStep::FilesystemAnalysisSurvey::narrative_docs

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-narrative-docs

### Description
Egeria dispatches GovActionProcessStep::FilesystemAnalysisSurvey::narrative_docs to Resource Explorer's engine, which claims it and runs RE step narrative_docs.

___

## Link Action to Action Executor
### Governance Action Type
GovActionProcessStep::FilesystemAnalysisSurvey::file_data_class_match

### Governance Engine
ResourceExplorerSurvey

### Request Type
re-file-data-class-match

### Description
Egeria dispatches GovActionProcessStep::FilesystemAnalysisSurvey::file_data_class_match to Resource Explorer's engine, which claims it and runs RE step file_data_class_match.

___

## Link Element To Scope
### Target Element
Filesystem Analysis Survey

### Scope Reference
What kinds of files does this filesystem contain, and how much data is there?

___

## Link Element To Scope
### Target Element
Filesystem Analysis Survey

### Scope Reference
Does this filesystem contain recognizable tabular or structured data files, and what do their schemas look like?

___

## Link Element To Scope
### Target Element
Filesystem Analysis Survey

### Scope Reference
What is the shape of this file system: how deep, how wide, where does the bulk sit?

___

## Link Element To Scope
### Target Element
Filesystem Analysis Survey

### Scope Reference
Which tabular or structured files are here, with what columns and types?

___

## Link Element To Scope
### Target Element
Filesystem Analysis Survey

### Scope Reference
What do the narrative files inside it (README, INDEX, ABOUT, NOTES, a data dictionary, a codebook, LICENSE, CHANGELOG) say the contents are, folder by folder?

___

## Link Element To Scope
### Target Element
Filesystem Analysis Survey

### Scope Reference
Which columns conform to a known Data Class, with what confidence, and which look like a class we do not have yet?

___

## Link Element To Scope
### Target Element
Filesystem Analysis Survey

### Scope Reference
Which files or folders contain personal or sensitive data?

