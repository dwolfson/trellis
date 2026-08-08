# Egeria Lineage Capture and Invocation Guide

This document describes the types of lineage captured by the static SQL view analysis, how Egeria represents it, and how to invoke the survey using a Dr. Egeria plan.

---

## 1. Lineage Types Captured

When the `sql_analysis` step runs, it uses `sqlglot` to parse the view definitions and extract:

### A. Design Lineage (Column-to-Column Mapping)
*   **Source Fields**: The physical database columns within the base tables that supply the data.
*   **Target Fields**: The derived columns in the SQL View.
*   **Egeria Model**: Represented as `LineageMapping` relationships directly linking the source `DatabaseColumn` entities to the target `DatabaseColumn` entities.

### B. Process Lineage (Transformation Flow)
*   **View Derivation Process**: The SQL Query itself represents a data transformation process.
*   **Egeria Model**: A `Process` entity is created for the View. It is linked to the source tables/views via `DataFlow` input relationships, and to the view's output attributes via `DataFlow` output relationships.

---

## 2. Invocation via Dr. Egeria

To trigger Egeria's engine to execute the survey definition process we created, you can use the following Dr. Egeria plan.

```markdown
# Initiate SQL Analysis Survey Execution

This plan triggers Egeria's governance engine to instantiate and run the `EgeriaDbSurvey` process on the target PostgreSQL database asset.

---

## Initiate Governance Action Process
### Governance Action Process
GovActionProcess::EgeriaDbSurvey

### Target Asset
Asset::PostgreSQLDatabase::EgeriaCatalog

### Request Parameters
| Parameter Name | Parameter Value |
|---|---|
| db_user | egeria_user |
| db_pwd | secretsStore::egeria_db_password |
```

---

## 3. Invocation via CLI

Alternatively, you can run the Survey Definition directly via the Resource Explorer command-line interface, which walks the Egeria-defined process steps locally:

```bash
resource-explorer database survey-definition egeria-db \
    --survey-definition GovActionProcess::EgeriaDbSurvey \
    --user egeria_user \
    --password secret
```
