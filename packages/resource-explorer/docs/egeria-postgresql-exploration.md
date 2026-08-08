# Egeria PostgreSQL Exploration

## Overview
This document captures our exploration of Egeria's PostgreSQL support and how to integrate it with Resource Explorer's surveyor framework.

## Key Findings

### 1. PostgreSQL Technology Types in Egeria

Egeria has **7 PostgreSQL technology types** defined as "Valid Metadata Values":

| Display Name | Description | Purpose |
|-------------|-------------|---------|
| PostgreSQL Relational Database | A database hosted on a PostgreSQL server | Represents a database instance |
| PostgreSQL Server | PostgreSQL is an advanced open source relational database | Represents the server software |
| PostgreSQL Tabular Data Set Collection | A database schema with tabular data sets | Represents a schema |
| PostgreSQL database manager (RDBMS) | The PostgreSQL capability that manages collections of data | Represents the DBMS capability |
| PostgreSQL Server | A database server running the PostgreSQL software | Represents the server instance |
| PostgreSQL Tabular Data Set | A database table with tabular data sets | Represents a table |

**Key Insight**: These are metadata value definitions that describe what PostgreSQL assets look like in Egeria's catalog.

### 2. Technology Type Structure

```json
{
  "technologyTypeGUID": "ff56fc56-c4a1-469e-8040-472e8fe54694",
  "qualifiedName": "Egeria:ValidMetadataValue:RelationalDatabase:deployedImplementationType-(PostgreSQL Relational Database)",
  "displayName": "PostgreSQL Relational Database",
  "description": "A database hosted on a PostgreSQL server.",
  "category": "Valid Metadata Values"
}
```

**Important**: Technology types do NOT contain nested governance processes or catalog templates. These are separate entities that must be queried independently.

### 3. Egeria's AutomatedCuration API

The `AutomatedCuration` OMVS provides methods for:
- Finding technology types: `find_technology_types()`
- Finding assets: `find_assets()` (via AssetMaker)
- Finding survey reports: `find_survey_reports()` (via DataDiscovery)

**Key Methods**:
- `find_elements_by_property_value()` - Find governance processes by name
- `initiate_gov_action_process()` - Trigger a governance process
- `get_governance_process_graph()` - Visualize process steps

### 4. PostgreSQL Governance Action Processes

Egeria provides **8 pre-built governance processes** for PostgreSQL (loaded via `PostgresContentPack.omarchive`):

| Process Name | Description |
|-------------|-------------|
| `PostgreSQLDatabase:DeleteAssetWithTemplateGovernanceActionProcess` | Delete PostgreSQL database asset and all anchored metadata |
| `PostgreSQLDatabase:CreateAndSurveyGovernanceActionProcess` | Create database, run survey, print report |
| `PostgreSQLServer::CreateAsCatalogTargetGovernanceActionProcess` | Create server and configure integration connector to catalog contents |
| `PostgreSQLServer:DeleteAssetWithTemplateGovernanceActionProcess` | Delete PostgreSQL server asset and all anchored metadata |
| `PostgreSQLDatabaseSchema::CreateAsCatalogTargetGovernanceActionProcess` | Create schema and configure integration connector to catalog contents |
| `PostgreSQLDatabaseSchema:DeleteAssetWithTemplateGovernanceActionProcess` | Delete PostgreSQL schema asset and all anchored metadata |
| `PostgreSQLServer:CreateAndSurveyGovernanceActionProcess` | Create server, run survey, print report |
| `PostgreSQLDatabase::CreateAsCatalogTargetGovernanceActionProcess` | Create database and configure integration connector to catalog contents |

**Key Process: `PostgreSQLServer:CreateAndSurveyGovernanceActionProcess`**

This process has 3 steps:
1. **Create the PostgreSQLServer entity** - Creates the asset in the catalog
2. **Run the survey** - Executes the survey action
3. **Print the survey report** - Outputs results to `/distribution-hub/surveys`

### 5. How to Trigger a PostgreSQL Survey

```python
from pyegeria import AutomatedCuration

automated_curation = AutomatedCuration(view_server, url, user_id, user_pwd)
token = automated_curation.create_egeria_bearer_token()

# Define request parameters
requestParameters = {
    "serverName": "LocalPostgreSQL1",
    "hostIdentifier": "localhost",
    "portNumber": "5432",
    "secretsStorePathName": "loading-bay/secrets/integration.omsecrets",
    "secretsCollectionName": "PostgreSQL Server:LocalPostgreSQL1",
    "versionIdentifier": "1.0",
    "description": "PostgreSQL database in egeria-workspaces."
}

# Initiate the governance process
process_name = "PostgreSQLServer:CreateAndSurveyGovernanceActionProcess"
engine_action_guid = automated_curation.initiate_gov_action_process(
    process_name, None, None, None, requestParameters, None, None
)
```

**Important Parameters**:
- `serverName` - Unique name for this PostgreSQL server
- `hostIdentifier` - Hostname or IP address
- `portNumber` - PostgreSQL port (default 5432)
- `secretsStorePathName` - Path to secrets file containing credentials
- `secretsCollectionName` - Name of the secrets collection for this server

### 6. Workflow for Surveying a PostgreSQL Database

Based on the Egeria documentation and examples, the workflow should be:

```
1. Check if PostgreSQL technology type exists
   ↓
2. Check if target database is already cataloged
   ↓ (if not cataloged)
3. Create asset from template OR use governance process
   ↓
4. Check if surveys exist for this asset
   ↓ (if no surveys or need new survey)
5. Trigger survey (via governance process OR custom surveyor)
   ↓
6. Monitor survey execution
   ↓
7. Retrieve survey results
```

## Integration Strategy for Resource Explorer

### Option 1: Leverage Egeria's Native Processes (Preferred)
- Use Egeria's pre-built governance processes for PostgreSQL
- Trigger surveys through Egeria's automation
- Retrieve and display results in Resource Explorer
- **Pros**: Leverages Egeria's expertise, standardized metadata
- **Cons**: Requires understanding Egeria's governance framework

### Option 2: Custom Surveyor with Egeria Publishing
- Build custom PostgreSQL surveyor in Resource Explorer
- Connect directly to PostgreSQL using JDBC/psycopg2
- Publish results to Egeria using existing `EgeriaPublisher`
- **Pros**: Full control, can add custom metrics
- **Cons**: Duplicates Egeria's work, non-standard metadata

### Option 3: Hybrid Approach (Recommended)
- Check Egeria first for existing surveys
- Use Egeria's native processes when available
- Fall back to custom surveyor when:
  - Network constraints prevent Egeria from accessing database
  - Need custom metrics not provided by Egeria
  - Rapid prototyping/development
- Always publish custom survey results to Egeria

## Next Steps

### Immediate (Understanding Phase)
1. ✅ Understand technology types structure
2. ⏳ Find how to query catalog templates
3. ⏳ Find how to query governance processes
4. ⏳ Understand how to trigger a survey programmatically
5. ⏳ Review existing PostgreSQL survey examples in pyegeria

### Short-term (Design Phase)
1. Create design document for database surveyor integration
2. Define the interface between Resource Explorer and Egeria
3. Identify which surveys to implement custom vs. leverage Egeria
4. Design the registry extension for database entities

### Medium-term (Implementation Phase)
1. Implement PostgreSQL connection abstraction
2. Create basic schema analyzer (custom surveyor)
3. Integrate with Egeria's survey retrieval
4. Add CLI commands for database registration
5. Test with local PostgreSQL instance

## Questions Resolved ✅

1. **How to find governance processes?** ✅
   - Use `find_elements_by_property_value()` with `metadata_element_type_name="GovernanceActionProcess"`
   - Search by property like `displayName` containing "PostgreSQL"

2. **How to trigger a survey?** ✅
   - Use `initiate_gov_action_process(processName, ..., requestParameters, ...)`
   - Pass connection details in `requestParameters` dict
   - Returns an engine action GUID for monitoring

3. **What's the relationship between entities?** ✅
   - **Technology Types** - Define valid metadata values (what PostgreSQL assets look like)
   - **Governance Action Processes** - Automated workflows (create + survey + report)
   - **Integration Connectors** - Runtime components that connect to PostgreSQL
   - **Catalog Templates** - Embedded in governance processes, used to create assets

4. **Where are survey results stored?** ✅
   - Survey reports are stored in Egeria's metadata repository
   - Summary reports written to `/distribution-hub/surveys`
   - Can be retrieved via `DataDiscovery` OMVS

## Remaining Questions

1. **How to retrieve survey results programmatically?** ✅ (Partially)
   - Use `DataDiscovery.find_annotations()` to search for annotations
   - Use `AssetMaker.find_assets()` to search for SurveyReport assets
   - Search by qualifiedName prefix (e.g., `SurveyReport::PostgreSQL::serverName::timestamp`)
   - **Still unclear**: How to get survey report by engine action GUID returned from `initiate_gov_action_process()`

2. **How to monitor governance process execution?**
   - Need to explore `GovernanceOfficer` or `EngineHost` APIs
   - How to check if process completed successfully?
   - How to get error messages if it failed?

3. **Secrets management:**
   - Egeria uses secrets files (`.omsecrets`) for credentials
   - Need to understand secrets file format
   - Can we pass credentials directly? (Probably not for security reasons)

## Survey Result Retrieval Pattern

Based on `EgeriaReader` implementation:

```python
from pyegeria import AssetMaker
from pyegeria.omvs.data_discovery import DataDiscovery

# 1. Find survey reports for an asset
asset_maker = AssetMaker(view_server, url, user_id, user_pwd)
asset_maker.create_egeria_bearer_token(user_id, user_pwd)

search_prefix = "SurveyReport::PostgreSQL::LocalPostgreSQL1::"
reports = asset_maker.find_assets(
    search_string=search_prefix,
    starts_with=True,
    ignore_case=False,
    output_format="JSON"
)

# 2. Get annotations for a specific survey
discovery = DataDiscovery(view_server, url, user_id, user_pwd)
discovery.create_egeria_bearer_token(user_id, user_pwd)

annotation_prefix = "Annotation::PostgreSQL::LocalPostgreSQL1::2024-01-01T12:00:00::"
annotations = discovery.find_annotations(
    search_string=annotation_prefix,
    starts_with=True,
    ignore_case=False,
    output_format="JSON",
    page_size=500
)
```

**Key Insight**: Survey reports and annotations use qualified names with predictable patterns, making them searchable without needing the engine action GUID.

## References

- Egeria AutomatedCuration OMVS: `/home/dwolfson/localGit/egeria-v6/egeria-python/pyegeria/omvs/automated_curation.py`
- PostgreSQL Survey Notebook: `/home/dwolfson/localGit/egeria-v6/egeria-workspaces/workbooks/cataloguing-and-surveys/postgres/survey-and-catalog-postgres.ipynb`
- Resource Explorer Egeria Integration: `explorer/surveyors/egeria_publisher.py`, `explorer/surveyors/egeria_reader.py`