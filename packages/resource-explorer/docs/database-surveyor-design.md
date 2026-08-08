# Database Surveyor Design

## Overview

This document outlines the design for extending Project Explorer's surveyor framework to support database surveys, starting with PostgreSQL. The design follows a hybrid approach that leverages Egeria's native capabilities while providing custom surveyor options when needed.

## Goals

1. **Extend surveyor framework** to support non-GitHub entities (databases, APIs, file systems)
2. **Integrate with Egeria** to leverage existing PostgreSQL governance processes
3. **Provide custom surveyors** for scenarios where Egeria can't access the database directly
4. **Maintain consistency** with existing GitHub surveyor patterns
5. **Enable CLI operations** for database registration and survey management

## Architecture

### High-Level Flow

```
User Command (CLI)
    ↓
Registry (track databases)
    ↓
Survey Orchestrator
    ↓
    ├─→ Check Egeria for existing surveys
    │   ├─→ Found: Display results
    │   └─→ Not found: Continue
    ↓
    ├─→ Try Egeria native survey (preferred)
    │   ├─→ Success: Monitor & retrieve results
    │   └─→ Fail: Fall back to custom
    ↓
    └─→ Custom Database Surveyor
        ├─→ Connect to database
        ├─→ Run surveys (schema, data quality, etc.)
        ├─→ Publish to Egeria
        └─→ Store in local registry
```

## Component Design

### 1. Database Entity Model

Extend the registry to support database entities alongside GitHub repositories.

```python
# explorer/registry.py additions

class DatabaseEntity:
    """Represents a database in the registry."""
    
    slug: str  # Unique identifier (e.g., "local-postgres-1")
    db_type: str  # "postgresql", "mysql", "oracle", etc.
    host: str
    port: int
    database_name: str
    description: str
    registered_at: datetime
    last_surveyed: Optional[datetime]
    egeria_asset_guid: Optional[str]
    
    # Connection details (encrypted or reference to secrets)
    connection_ref: str  # Reference to secrets store or connection config

# Registry methods to add:
def register_database(self, entity: DatabaseEntity) -> str:
    """Register a database in the local registry."""
    
def get_database(self, slug: str) -> Optional[DatabaseEntity]:
    """Retrieve database entity by slug."""
    
def list_databases(self, db_type: Optional[str] = None) -> list[DatabaseEntity]:
    """List all registered databases, optionally filtered by type."""
```

### 2. Database Connection Abstraction

Create a connection manager that handles different database types.

```python
# explorer/surveyors/database/connection.py

from abc import ABC, abstractmethod
from typing import Any, Optional
import psycopg2
from contextlib import contextmanager

class DatabaseConnection(ABC):
    """Abstract base class for database connections."""
    
    @abstractmethod
    def connect(self) -> Any:
        """Establish connection to the database."""
        pass
    
    @abstractmethod
    def execute_query(self, query: str) -> list[dict]:
        """Execute a query and return results."""
        pass
    
    @abstractmethod
    def get_schema_info(self) -> dict:
        """Get database schema information."""
        pass
    
    @abstractmethod
    def close(self):
        """Close the connection."""
        pass

class PostgreSQLConnection(DatabaseConnection):
    """PostgreSQL-specific connection implementation."""
    
    def __init__(self, host: str, port: int, database: str, 
                 user: str, password: str):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self._conn = None
    
    def connect(self):
        self._conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            database=self.database,
            user=self.user,
            password=self.password
        )
        return self._conn
    
    def execute_query(self, query: str) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(query)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    
    def get_schema_info(self) -> dict:
        """Get PostgreSQL schema information."""
        # Query information_schema for tables, columns, constraints
        schemas_query = """
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
        """
        schemas = self.execute_query(schemas_query)
        
        result = {"schemas": []}
        for schema in schemas:
            schema_name = schema["schema_name"]
            tables = self._get_tables_for_schema(schema_name)
            result["schemas"].append({
                "name": schema_name,
                "tables": tables
            })
        
        return result
    
    def _get_tables_for_schema(self, schema_name: str) -> list[dict]:
        """Get tables and columns for a schema."""
        query = """
            SELECT 
                t.table_name,
                t.table_type,
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default
            FROM information_schema.tables t
            LEFT JOIN information_schema.columns c 
                ON t.table_name = c.table_name 
                AND t.table_schema = c.table_schema
            WHERE t.table_schema = %s
            ORDER BY t.table_name, c.ordinal_position
        """
        rows = self.execute_query(query)
        
        # Group by table
        tables = {}
        for row in rows:
            table_name = row["table_name"]
            if table_name not in tables:
                tables[table_name] = {
                    "name": table_name,
                    "type": row["table_type"],
                    "columns": []
                }
            if row["column_name"]:
                tables[table_name]["columns"].append({
                    "name": row["column_name"],
                    "type": row["data_type"],
                    "nullable": row["is_nullable"] == "YES",
                    "default": row["column_default"]
                })
        
        return list(tables.values())
    
    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

@contextmanager
def database_connection(db_entity: DatabaseEntity, credentials: dict):
    """Context manager for database connections."""
    if db_entity.db_type == "postgresql":
        conn = PostgreSQLConnection(
            host=db_entity.host,
            port=db_entity.port,
            database=db_entity.database_name,
            user=credentials["user"],
            password=credentials["password"]
        )
    else:
        raise ValueError(f"Unsupported database type: {db_entity.db_type}")
    
    try:
        conn.connect()
        yield conn
    finally:
        conn.close()
```

### 3. Database Surveyor

Custom surveyor for databases when Egeria can't access them directly.

```python
# explorer/surveyors/database/database_surveyor.py

from explorer.surveyors.base_surveyor import BaseSurveyor
from explorer.surveyors.survey_report import SurveyResult
from .connection import database_connection, DatabaseEntity

class DatabaseSurveyor(BaseSurveyor):
    """Custom surveyor for databases."""
    
    def __init__(self, db_entity: DatabaseEntity, credentials: dict):
        self.db_entity = db_entity
        self.credentials = credentials
    
    def survey(self) -> SurveyResult:
        """Run comprehensive database survey."""
        with database_connection(self.db_entity, self.credentials) as conn:
            # Run sub-surveyors
            schema_info = self._survey_schema(conn)
            stats_info = self._survey_statistics(conn)
            quality_info = self._survey_data_quality(conn)
            
            return SurveyResult(
                entity_id=self.db_entity.slug,
                entity_type="database",
                surveyed_at=datetime.now(),
                findings={
                    "schema": schema_info,
                    "statistics": stats_info,
                    "data_quality": quality_info
                }
            )
    
    def _survey_schema(self, conn) -> dict:
        """Survey database schema structure."""
        schema_info = conn.get_schema_info()
        
        # Calculate metrics
        total_tables = sum(len(s["tables"]) for s in schema_info["schemas"])
        total_columns = sum(
            len(t["columns"]) 
            for s in schema_info["schemas"] 
            for t in s["tables"]
        )
        
        return {
            "schema_count": len(schema_info["schemas"]),
            "table_count": total_tables,
            "column_count": total_columns,
            "schemas": schema_info["schemas"]
        }
    
    def _survey_statistics(self, conn) -> dict:
        """Survey database statistics (row counts, sizes, etc.)."""
        # Query pg_stat_user_tables for PostgreSQL
        query = """
            SELECT 
                schemaname,
                tablename,
                n_live_tup as row_count,
                n_dead_tup as dead_rows,
                last_vacuum,
                last_analyze
            FROM pg_stat_user_tables
            ORDER BY n_live_tup DESC
        """
        stats = conn.execute_query(query)
        
        return {
            "table_statistics": stats,
            "total_rows": sum(s["row_count"] for s in stats)
        }
    
    def _survey_data_quality(self, conn) -> dict:
        """Survey data quality (nulls, duplicates, etc.)."""
        # This would be more sophisticated in practice
        # For now, just check for tables with high null percentages
        
        quality_issues = []
        schema_info = conn.get_schema_info()
        
        for schema in schema_info["schemas"]:
            for table in schema["tables"]:
                # Check null percentages for each column
                for column in table["columns"]:
                    if column["nullable"]:
                        null_check_query = f"""
                            SELECT 
                                COUNT(*) as total,
                                COUNT({column["name"]}) as non_null
                            FROM {schema["name"]}.{table["name"]}
                        """
                        result = conn.execute_query(null_check_query)
                        if result:
                            total = result[0]["total"]
                            non_null = result[0]["non_null"]
                            if total > 0:
                                null_pct = (total - non_null) / total * 100
                                if null_pct > 50:  # More than 50% nulls
                                    quality_issues.append({
                                        "table": f"{schema['name']}.{table['name']}",
                                        "column": column["name"],
                                        "issue": "high_null_percentage",
                                        "null_percentage": null_pct
                                    })
        
        return {
            "quality_issues": quality_issues,
            "issue_count": len(quality_issues)
        }
```

### 4. Egeria Integration Layer

Wrapper to interact with Egeria's PostgreSQL governance processes.

```python
# explorer/surveyors/database/egeria_database_client.py

from pyegeria import AutomatedCuration, AssetMaker
from pyegeria.omvs.data_discovery import DataDiscovery
from typing import Optional

class EgeriaDatabaseClient:
    """Client for Egeria database operations."""
    
    def __init__(self, platform_url: str, view_server: str, 
                 user_id: str, user_pwd: str):
        self.platform_url = platform_url
        self.view_server = view_server
        self.user_id = user_id
        self.user_pwd = user_pwd
        
        self._automated_curation = None
        self._asset_maker = None
        self._discovery = None
    
    def connect(self):
        """Establish connections to Egeria."""
        self._automated_curation = AutomatedCuration(
            self.view_server, self.platform_url, 
            self.user_id, self.user_pwd
        )
        self._automated_curation.create_egeria_bearer_token(
            self.user_id, self.user_pwd
        )
        
        self._asset_maker = AssetMaker(
            self.view_server, self.platform_url,
            self.user_id, self.user_pwd
        )
        self._asset_maker.create_egeria_bearer_token(
            self.user_id, self.user_pwd
        )
        
        self._discovery = DataDiscovery(
            self.view_server, self.platform_url,
            self.user_id, self.user_pwd
        )
        self._discovery.create_egeria_bearer_token(
            self.user_id, self.user_pwd
        )
    
    def trigger_postgresql_survey(self, db_entity: DatabaseEntity, 
                                  secrets_path: str) -> str:
        """Trigger Egeria's native PostgreSQL survey process."""
        request_params = {
            "serverName": db_entity.slug,
            "hostIdentifier": db_entity.host,
            "portNumber": str(db_entity.port),
            "secretsStorePathName": secrets_path,
            "secretsCollectionName": f"PostgreSQL Server:{db_entity.slug}",
            "versionIdentifier": "1.0",
            "description": db_entity.description
        }
        
        process_name = "PostgreSQLServer:CreateAndSurveyGovernanceActionProcess"
        engine_action_guid = self._automated_curation.initiate_gov_action_process(
            process_name, None, None, None, request_params, None, None
        )
        
        return engine_action_guid
    
    def find_survey_reports(self, db_slug: str) -> list[dict]:
        """Find survey reports for a database."""
        search_prefix = f"SurveyReport::PostgreSQL::{db_slug}::"
        
        reports = self._asset_maker.find_assets(
            search_string=search_prefix,
            starts_with=True,
            ignore_case=False,
            output_format="JSON"
        )
        
        if not isinstance(reports, list):
            return []
        
        return reports
    
    def get_survey_annotations(self, db_slug: str, 
                              surveyed_at: str) -> list[dict]:
        """Get annotations for a specific survey."""
        search_prefix = f"Annotation::PostgreSQL::{db_slug}::{surveyed_at}::"
        
        annotations = self._discovery.find_annotations(
            search_string=search_prefix,
            starts_with=True,
            ignore_case=False,
            output_format="JSON",
            page_size=500
        )
        
        if not isinstance(annotations, list):
            return []
        
        return annotations
```

### 5. CLI Commands

Add database-specific commands to the CLI.

```python
# explorer/cli/main.py additions

@cli.group()
def database():
    """Database survey commands."""
    pass

@database.command()
@click.option("--slug", required=True, help="Unique identifier for the database")
@click.option("--type", "db_type", required=True, 
              type=click.Choice(["postgresql", "mysql", "oracle"]))
@click.option("--host", required=True, help="Database host")
@click.option("--port", required=True, type=int, help="Database port")
@click.option("--database", required=True, help="Database name")
@click.option("--description", help="Description of the database")
def register(slug, db_type, host, port, database, description):
    """Register a database for surveying."""
    registry = ProjectRegistry()
    
    db_entity = DatabaseEntity(
        slug=slug,
        db_type=db_type,
        host=host,
        port=port,
        database_name=database,
        description=description or "",
        registered_at=datetime.now()
    )
    
    registry.register_database(db_entity)
    click.echo(f"✓ Registered database: {slug}")

@database.command()
@click.option("--slug", required=True, help="Database slug")
@click.option("--use-egeria/--no-egeria", default=True,
              help="Try Egeria native survey first")
@click.option("--secrets-path", help="Path to Egeria secrets file")
def survey(slug, use_egeria, secrets_path):
    """Survey a registered database."""
    registry = ProjectRegistry()
    db_entity = registry.get_database(slug)
    
    if not db_entity:
        click.echo(f"Error: Database '{slug}' not found", err=True)
        return
    
    # Check for existing surveys in Egeria
    if use_egeria:
        egeria_client = EgeriaDatabaseClient(...)
        egeria_client.connect()
        
        reports = egeria_client.find_survey_reports(slug)
        if reports:
            click.echo(f"Found {len(reports)} existing survey(s) in Egeria")
            # Display reports
            return
        
        # Try to trigger Egeria survey
        if secrets_path:
            try:
                engine_action_guid = egeria_client.trigger_postgresql_survey(
                    db_entity, secrets_path
                )
                click.echo(f"✓ Triggered Egeria survey: {engine_action_guid}")
                click.echo("Monitor progress in Egeria...")
                return
            except Exception as e:
                click.echo(f"Egeria survey failed: {e}")
                click.echo("Falling back to custom surveyor...")
    
    # Custom surveyor
    credentials = _get_credentials(slug)  # From config or prompt
    surveyor = DatabaseSurveyor(db_entity, credentials)
    
    with click.progressbar(length=100, label="Surveying database") as bar:
        result = surveyor.survey()
        bar.update(100)
    
    # Publish to Egeria if configured
    if use_egeria:
        publisher = EgeriaPublisher(...)
        publisher.publish_database_survey(result)
    
    click.echo(f"✓ Survey complete: {result.entity_id}")

@database.command()
def list():
    """List registered databases."""
    registry = ProjectRegistry()
    databases = registry.list_databases()
    
    if not databases:
        click.echo("No databases registered")
        return
    
    table = Table(title="Registered Databases")
    table.add_column("Slug", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Host", style="green")
    table.add_column("Database", style="blue")
    table.add_column("Last Surveyed", style="magenta")
    
    for db in databases:
        table.add_row(
            db.slug,
            db.db_type,
            f"{db.host}:{db.port}",
            db.database_name,
            db.last_surveyed.strftime("%Y-%m-%d") if db.last_surveyed else "Never"
        )
    
    console = Console()
    console.print(table)
```

## Implementation Plan

### Phase 1: Foundation (Current)
- [x] Research Egeria PostgreSQL capabilities
- [x] Understand survey retrieval patterns
- [ ] Design database entity model
- [ ] Design connection abstraction

### Phase 2: Core Implementation
- [ ] Implement DatabaseEntity in registry
- [ ] Implement PostgreSQLConnection
- [ ] Implement basic DatabaseSurveyor
- [ ] Add CLI commands (register, list)

### Phase 3: Egeria Integration
- [ ] Implement EgeriaDatabaseClient
- [ ] Add survey triggering
- [ ] Add survey result retrieval
- [ ] Integrate with existing EgeriaPublisher

### Phase 4: Advanced Features
- [ ] Add data quality surveyor
- [ ] Add query performance surveyor
- [ ] Add secrets management
- [ ] Add web UI for databases

### Phase 5: Testing & Documentation
- [ ] Test with local PostgreSQL
- [ ] Test Egeria integration
- [ ] Write user documentation
- [ ] Create example workflows

## Security Considerations

1. **Credentials Storage**
   - Never store passwords in plain text
   - Use environment variables or encrypted secrets
   - Support Egeria's secrets store format
   - Consider integration with system keychains

2. **Connection Security**
   - Support SSL/TLS connections
   - Validate certificates
   - Use connection pooling safely

3. **Query Safety**
   - Use parameterized queries
   - Limit query execution time
   - Restrict to read-only operations by default

## Testing Strategy

1. **Unit Tests**
   - Test connection classes with mock databases
   - Test surveyor logic independently
   - Test Egeria client methods

2. **Integration Tests**
   - Test with local PostgreSQL instance
   - Test Egeria integration (if available)
   - Test end-to-end workflows

3. **Manual Testing**
   - Test CLI commands
   - Test with various database schemas
   - Test error handling

## Future Enhancements

1. **Additional Database Types**
   - MySQL/MariaDB
   - Oracle
   - SQL Server
   - MongoDB (NoSQL)

2. **Advanced Surveys**
   - Query performance analysis
   - Index recommendations
   - Data lineage tracking
   - Compliance checking

3. **Automation**
   - Scheduled surveys
   - Change detection
   - Alerting on issues

4. **Visualization**
   - Schema diagrams
   - Data quality dashboards
   - Trend analysis