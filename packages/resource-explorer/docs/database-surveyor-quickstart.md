# Database Surveyor Quick Start Guide

## Overview

The Database Surveyor extension allows Resource Explorer to survey and analyze database schemas, similar to how it surveys GitHub repositories. Currently supports PostgreSQL with plans for MySQL, Oracle, and other databases.

## Installation

The database surveyor is included in Resource Explorer. For PostgreSQL support, install the optional dependency:

```bash
pip install psycopg2-binary
```

## Basic Usage

### 1. Register a Database

Register a PostgreSQL database in the registry:

```bash
uv run python -m explorer.cli.main database register my-postgres \
  --type postgresql \
  --host localhost \
  --port 5432 \
  --database mydb \
  --name "My PostgreSQL Database" \
  --description "Development database"
```

**Parameters:**
- `slug` (required): Unique identifier (e.g., `my-postgres`)
- `--type`: Database type (`postgresql`, more coming soon)
- `--host`: Database host
- `--port`: Database port
- `--database`: Database name
- `--name`: Display name (optional, defaults to slug)
- `--description`: Description (optional)

### 2. List Registered Databases

View all registered databases:

```bash
uv run python -m explorer.cli.main database list
```

Filter by type:

```bash
uv run python -m explorer.cli.main database list --type postgresql
```

### 3. Survey a Database

Run a survey to analyze schema and gather statistics:

```bash
uv run python -m explorer.cli.main database survey my-postgres \
  --user admin \
  --password secret
```

**Note:** Credentials are only used during the survey and are not stored.

The survey will:
- Analyze all schemas (excluding system schemas)
- Catalog all tables and columns
- Gather size statistics
- Create Egeria-aligned annotations
- Store results in the registry

### 4. View Database Information

See detailed information and survey history:

```bash
uv run python -m explorer.cli.main database info my-postgres
```

This shows:
- Database connection details
- Registration date
- Last survey date
- Survey history (last 5 surveys)
- Schema/table/column counts

### 5. Remove a Database

Remove a database from the registry:

```bash
uv run python -m explorer.cli.main database remove my-postgres
```

Add `--yes` to skip confirmation:

```bash
uv run python -m explorer.cli.main database remove my-postgres --yes
```

## Programmatic Usage

### Using the Registry

```python
from explorer.registry import DatabaseEntity, ProjectRegistry

# Create registry
registry = ProjectRegistry()

# Register a database
db = DatabaseEntity(
    slug="my-db",
    display_name="My Database",
    db_type="postgresql",
    host="localhost",
    port=5432,
    database_name="mydb",
    description="Development database"
)
registry.register_database(db)

# List databases
databases = registry.list_databases()
for db in databases:
    print(f"{db.slug}: {db.display_name}")

# Get a specific database
db = registry.get_database("my-db")
print(f"Host: {db.host}:{db.port}")

# Check if exists
if registry.database_exists("my-db"):
    print("Database exists!")
```

### Running Surveys

```python
from explorer.registry import ProjectRegistry
from explorer.surveyors.database.database_surveyor import run_database_survey

# Run a survey
results = run_database_survey(
    db_slug="my-db",
    credentials={"user": "admin", "password": "secret"},
    registry=ProjectRegistry()
)

# Access results
schema_info = results["schema_info"]
print(f"Schemas: {len(schema_info['schemas'])}")
print(f"Tables: {schema_info['total_tables']}")
print(f"Columns: {schema_info['total_columns']}")

# Access annotations
for annotation in results["annotations"]:
    print(f"- {annotation.summary}")
```

### Using the Connection Layer

```python
from explorer.registry import DatabaseEntity, ProjectRegistry
from explorer.surveyors.database.connection import database_connection

# Get database entity
registry = ProjectRegistry()
db = registry.get_database("my-db")

# Use connection
credentials = {"user": "admin", "password": "secret"}
with database_connection(db, credentials) as conn:
    # Get schema information
    schema_info = conn.get_schema_info()
    print(f"Found {len(schema_info['schemas'])} schemas")
    
    # Get statistics
    stats = conn.get_statistics()
    print(f"Database size: {stats['database_size']['size_pretty']}")
    
    # Execute custom query
    results = conn.execute_query(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        ("public",)
    )
    for row in results:
        print(f"Table: {row['table_name']}")
```

## Survey Output

A database survey produces:

### Schema Information
- List of schemas (excluding system schemas)
- Tables per schema
- Columns per table with types and constraints
- Total counts (schemas, tables, columns)

### Statistics
- Database size (bytes and human-readable)
- Table sizes (top 5 largest tables)
- Row counts (if available)

### Annotations
The survey creates Egeria-aligned annotations:

1. **SchemaAnalysisAnnotation**: Overall schema summary
2. **SchemaAnalysisAnnotation**: Per-schema summaries
3. **SchemaAnalysisAnnotation**: Per-table summaries
4. **ResourceMeasureAnnotation**: Database size
5. **ResourceMeasureAnnotation**: Table sizes

All annotations are stored in the registry and can be retrieved later.

## Survey History

The registry maintains a complete history of surveys:

```python
from explorer.registry import ProjectRegistry

registry = ProjectRegistry()

# Get all surveys for a database
surveys = registry.get_database_surveys("my-db")
for survey in surveys:
    print(f"Survey on {survey['surveyed_at'][:10]}")
    print(f"  Schemas: {survey['schema_count']}")
    print(f"  Tables: {survey['table_count']}")
    print(f"  Columns: {survey['column_count']}")

# Get just the latest survey
latest = registry.get_latest_database_survey("my-db")
if latest:
    print(f"Last surveyed: {latest['surveyed_at']}")
```

## Security Best Practices

1. **Never store credentials**: Credentials are only used during surveys
2. **Use environment variables**: Store credentials in environment variables
3. **Use read-only accounts**: Survey only needs SELECT permissions
4. **Limit network access**: Use firewall rules to restrict database access
5. **Use SSL/TLS**: Enable encrypted connections when possible

### Example with Environment Variables

```bash
# Set credentials in environment
export DB_USER="readonly_user"
export DB_PASSWORD="secure_password"

# Use in survey
uv run python -m explorer.cli.main database survey my-postgres \
  --user "$DB_USER" \
  --password "$DB_PASSWORD"
```

## Troubleshooting

### "psycopg2 is required for PostgreSQL connections"

Install the PostgreSQL driver:
```bash
pip install psycopg2-binary
```

### "Database 'my-db' not found"

Register the database first:
```bash
uv run python -m explorer.cli.main database register my-db --type postgresql --host localhost --port 5432 --database mydb
```

### Connection timeout or refused

Check:
1. Database is running
2. Host and port are correct
3. Firewall allows connections
4. PostgreSQL accepts remote connections (check `pg_hba.conf`)

### Permission denied

Ensure the user has SELECT permissions on:
- `information_schema.schemata`
- `information_schema.tables`
- `information_schema.columns`
- `pg_database`
- `pg_tables`

## Next Steps

- **Phase 3**: Egeria integration (hybrid approach)
- **Future**: MySQL, Oracle, SQL Server support
- **Future**: Data quality surveys
- **Future**: Schema change detection
- **Future**: Scheduled surveys

## Related Documentation

- [Database Surveyor Design](database-surveyor-design.md) - Full architecture
- [Phase 2 Completion State](archive/PHASE2_COMPLETION_STATE.md) - Implementation details
- [Egeria PostgreSQL Exploration](egeria-postgresql-exploration.md) - Egeria capabilities

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the design documentation
3. Run the test script: `python3 scripts/test_database_registry.py`
4. Check the implementation in `explorer/surveyors/database/`