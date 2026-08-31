# Airflow 3.x and OpenLineage Integration

## Overview

This document covers Airflow 3.x compatibility and OpenLineage integration for data lineage tracking in the Egeria Advisor system.

## Airflow 3.x Compatibility

### Key Changes in Airflow 3.x

1. **Task API**: New `@task` decorator replaces `PythonOperator`
2. **TaskFlow API**: Native support for XCom passing
3. **Dataset-aware scheduling**: Trigger DAGs based on dataset updates
4. **Improved typing**: Better type hints throughout
5. **Async operators**: Native async/await support
6. **Simplified configuration**: Streamlined settings

### Migration Strategy

#### Old Style (Airflow 2.x)
```python
from airflow.operators.python import PythonOperator

def my_function(**context):
    result = do_work()
    context['task_instance'].xcom_push(key='result', value=result)
    return result

task = PythonOperator(
    task_id='my_task',
    python_callable=my_function,
    dag=dag
)
```

#### New Style (Airflow 3.x)
```python
from airflow.decorators import task

@task
def my_function():
    result = do_work()
    return result  # Automatically pushed to XCom

result = my_function()
```

### Updated DAG Structure for Airflow 3.x

```python
from datetime import datetime, timedelta
from airflow.decorators import dag, task
from airflow.datasets import Dataset

# Define datasets for lineage tracking
egeria_python_repo = Dataset("git://github.com/odpi/egeria-python")
pyegeria_collection = Dataset("milvus://localhost:19530/pyegeria")

@dag(
    dag_id='egeria_incremental_update_v3',
    start_date=datetime(2024, 1, 1),
    schedule=[egeria_python_repo],  # Trigger on dataset update
    catchup=False,
    tags=['egeria', 'incremental', 'v3'],
    default_args={
        'owner': 'egeria-advisor',
        'retries': 2,
        'retry_delay': timedelta(minutes=5)
    }
)
def egeria_incremental_update():
    """Incremental update DAG using Airflow 3.x TaskFlow API."""
    
    @task(outlets=[egeria_python_repo])
    def sync_repositories():
        """Sync git repositories."""
        import subprocess
        from loguru import logger
        
        repos = {
            'egeria-python': '/path/to/egeria-python',
            'egeria': '/path/to/egeria',
        }
        
        results = {}
        for name, path in repos.items():
            subprocess.run(['git', '-C', path, 'pull'], check=True)
            results[name] = {'updated': True}
        
        return results
    
    @task
    def detect_changes(sync_results: dict):
        """Detect file changes."""
        from advisor.incremental_indexer import IncrementalIndexer
        from advisor.collection_config import get_enabled_collections
        
        changes = {}
        for collection in get_enabled_collections():
            indexer = IncrementalIndexer(
                collection_name=collection.name,
                source_paths=get_source_paths(collection),
                file_patterns=get_file_patterns(collection)
            )
            changeset = indexer.detect_changes()
            changes[collection.name] = {
                'total_changes': changeset.total_changes,
                'has_changes': changeset.has_changes
            }
        
        return changes
    
    @task(outlets=[pyegeria_collection])
    def apply_updates(changes: dict):
        """Apply incremental updates."""
        from advisor.incremental_indexer import IncrementalIndexer
        
        results = {}
        for collection_name, change_info in changes.items():
            if change_info['has_changes']:
                indexer = IncrementalIndexer(collection_name=collection_name, ...)
                result = indexer.apply_updates(changeset)
                results[collection_name] = {
                    'success': result.success,
                    'chunks_added': result.chunks_added
                }
        
        return results
    
    @task
    def verify_updates(update_results: dict):
        """Verify updates."""
        from pymilvus import connections, Collection
        
        verification = {}
        for collection_name in update_results.keys():
            collection = Collection(collection_name)
            verification[collection_name] = {
                'entity_count': collection.num_entities
            }
        
        return verification
    
    # Define task dependencies using TaskFlow API
    sync_results = sync_repositories()
    changes = detect_changes(sync_results)
    updates = apply_updates(changes)
    verification = verify_updates(updates)

# Instantiate the DAG
dag_instance = egeria_incremental_update()
```

## OpenLineage Integration

### What is OpenLineage?

OpenLineage is an open standard for data lineage collection and analysis. It provides:
- **Standardized events**: Common format for lineage data
- **Automatic collection**: Integrates with Airflow, Spark, dbt, etc.
- **Lineage graph**: Track data flow across systems
- **Impact analysis**: Understand downstream effects of changes

### OpenLineage Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Airflow DAG                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  Sync Repos  │→ │Detect Changes│→ │Apply Updates │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│         │                  │                  │             │
│         ▼                  ▼                  ▼             │
│    OpenLineage        OpenLineage        OpenLineage       │
│       Events             Events             Events          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  OpenLineage Backend                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Marquez    │  │   Egeria     │  │   Custom     │     │
│  │  (default)   │  │  Connector   │  │   Backend    │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Lineage Graph                             │
│                                                              │
│  Git Repo → File Changes → Vector Store → Query Results    │
│     ↓            ↓              ↓              ↓            │
│  Commits    Embeddings      Collections    User Queries    │
└─────────────────────────────────────────────────────────────┘
```

### OpenLineage Configuration

#### Install OpenLineage
```bash
pip install openlineage-airflow
pip install openlineage-python
```

#### Configure Airflow for OpenLineage
```python
# airflow.cfg or environment variables
[openlineage]
transport = http
url = http://localhost:5000/api/v1/lineage
namespace = egeria-advisor
disabled_for_operators = 

# Or via environment variables
export OPENLINEAGE_URL=http://localhost:5000/api/v1/lineage
export OPENLINEAGE_NAMESPACE=egeria-advisor
```

### OpenLineage Event Structure

#### Dataset Definition
```python
from openlineage.client.facet import (
    DatasetFacet,
    SchemaDatasetFacet,
    SchemaField
)

# Define Milvus collection as dataset
collection_dataset = {
    "namespace": "milvus://localhost:19530",
    "name": "pyegeria",
    "facets": {
        "schema": SchemaDatasetFacet(
            fields=[
                SchemaField(name="id", type="int64"),
                SchemaField(name="embedding", type="float_vector", description="384-dim embedding"),
                SchemaField(name="text", type="varchar"),
                SchemaField(name="metadata", type="json")
            ]
        ),
        "dataSource": DatasetFacet(
            name="Milvus",
            uri="milvus://localhost:19530"
        )
    }
}

# Define git repository as dataset
repo_dataset = {
    "namespace": "git://github.com/odpi",
    "name": "egeria-python",
    "facets": {
        "dataSource": DatasetFacet(
            name="GitHub",
            uri="https://github.com/odpi/egeria-python"
        )
    }
}
```

#### Custom OpenLineage Emitter

```python
from openlineage.client import OpenLineageClient
from openlineage.client.run import RunEvent, RunState, Run, Job
from openlineage.client.facet import (
    JobFacet,
    RunFacet,
    DatasetFacet,
    ParentRunFacet
)
from datetime import datetime
import uuid

class EgeriaLineageEmitter:
    """Emit OpenLineage events for Egeria operations."""
    
    def __init__(self, url: str = "http://localhost:5000/api/v1/lineage"):
        self.client = OpenLineageClient(url=url)
        self.namespace = "egeria-advisor"
    
    def emit_incremental_update(
        self,
        collection_name: str,
        source_files: list,
        chunks_added: int,
        chunks_removed: int,
        run_id: str = None
    ):
        """
        Emit lineage event for incremental update.
        
        Args:
            collection_name: Name of Milvus collection
            source_files: List of source file paths
            chunks_added: Number of chunks added
            chunks_removed: Number of chunks removed
            run_id: Optional run ID (generated if not provided)
        """
        run_id = run_id or str(uuid.uuid4())
        
        # Define job
        job = Job(
            namespace=self.namespace,
            name=f"incremental_update_{collection_name}",
            facets={
                "documentation": JobFacet(
                    description=f"Incremental update of {collection_name} collection"
                )
            }
        )
        
        # Define run
        run = Run(
            runId=run_id,
            facets={
                "parent": ParentRunFacet(
                    run={"runId": run_id},
                    job={"namespace": self.namespace, "name": "egeria_incremental_update"}
                )
            }
        )
        
        # Define input datasets (source files)
        inputs = [
            {
                "namespace": "file://",
                "name": str(file_path),
                "facets": {
                    "dataSource": DatasetFacet(
                        name="LocalFileSystem",
                        uri=f"file://{file_path}"
                    )
                }
            }
            for file_path in source_files
        ]
        
        # Define output dataset (Milvus collection)
        outputs = [{
            "namespace": "milvus://localhost:19530",
            "name": collection_name,
            "facets": {
                "dataSource": DatasetFacet(
                    name="Milvus",
                    uri="milvus://localhost:19530"
                ),
                "stats": DatasetFacet(
                    rowCount=chunks_added - chunks_removed,
                    size=chunks_added * 384 * 4  # Approximate size in bytes
                )
            },
            "outputFacets": {
                "outputStatistics": {
                    "rowCount": chunks_added,
                    "size": chunks_added * 384 * 4
                }
            }
        }]
        
        # Emit START event
        self.client.emit(
            RunEvent(
                eventType=RunState.START,
                eventTime=datetime.now().isoformat(),
                run=run,
                job=job,
                inputs=inputs,
                outputs=outputs,
                producer="egeria-advisor/1.0"
            )
        )
        
        # Emit COMPLETE event
        self.client.emit(
            RunEvent(
                eventType=RunState.COMPLETE,
                eventTime=datetime.now().isoformat(),
                run=run,
                job=job,
                inputs=inputs,
                outputs=outputs,
                producer="egeria-advisor/1.0"
            )
        )
```

### Integration with Airflow DAG

```python
from airflow.decorators import dag, task
from datetime import datetime

@dag(
    dag_id='egeria_with_lineage',
    start_date=datetime(2024, 1, 1),
    schedule_interval='0 */6 * * *',
    catchup=False
)
def egeria_with_lineage():
    """DAG with OpenLineage integration."""
    
    @task
    def apply_updates_with_lineage():
        """Apply updates and emit lineage events."""
        from advisor.incremental_indexer import IncrementalIndexer
        from airflow_openlineage_emitter import EgeriaLineageEmitter
        
        # Get Airflow run ID for lineage correlation
        from airflow.operators.python import get_current_context
        context = get_current_context()
        run_id = context['run_id']
        
        # Initialize lineage emitter
        emitter = EgeriaLineageEmitter()
        
        # Perform update
        indexer = IncrementalIndexer(collection_name="pyegeria", ...)
        changeset = indexer.detect_changes()
        result = indexer.apply_updates(changeset)
        
        # Emit lineage event
        emitter.emit_incremental_update(
            collection_name="pyegeria",
            source_files=[str(f) for f in changeset.new_files + changeset.modified_files],
            chunks_added=result.chunks_added,
            chunks_removed=result.chunks_removed,
            run_id=run_id
        )
        
        return result
    
    apply_updates_with_lineage()

dag_instance = egeria_with_lineage()
```

### OpenLineage Backends

#### 1. Marquez (Default)
```bash
# Run Marquez with Docker
docker run -p 5000:5000 -p 5001:5001 marquezproject/marquez:latest

# Configure Airflow
export OPENLINEAGE_URL=http://localhost:5000/api/v1/lineage
```

#### 2. Egeria Integration
```python
# Custom backend that sends to Egeria
class EgeriaOpenLineageBackend:
    """Send OpenLineage events to Egeria."""
    
    def __init__(self, egeria_url: str):
        self.egeria_url = egeria_url
    
    def emit(self, event: RunEvent):
        """Convert OpenLineage event to Egeria format and send."""
        # Convert to Egeria Asset/Lineage format
        # POST to Egeria REST API
        pass
```

#### 3. Custom Backend
```python
# Store in local database for analysis
class CustomLineageBackend:
    """Store lineage in SQLite for local analysis."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
    
    def emit(self, event: RunEvent):
        """Store event in database."""
        # Parse event
        # Store in SQLite
        pass
```

### Lineage Query Examples

```python
# Query lineage for a collection
def get_collection_lineage(collection_name: str):
    """Get lineage for a Milvus collection."""
    from openlineage.client import OpenLineageClient
    
    client = OpenLineageClient(url="http://localhost:5000")
    
    # Query upstream (what created this collection)
    upstream = client.get_lineage(
        namespace="milvus://localhost:19530",
        name=collection_name,
        depth=5,
        direction="upstream"
    )
    
    # Query downstream (what uses this collection)
    downstream = client.get_lineage(
        namespace="milvus://localhost:19530",
        name=collection_name,
        depth=5,
        direction="downstream"
    )
    
    return {
        'upstream': upstream,
        'downstream': downstream
    }

# Find impact of file change
def find_impact(file_path: str):
    """Find what collections are affected by a file change."""
    client = OpenLineageClient(url="http://localhost:5000")
    
    lineage = client.get_lineage(
        namespace="file://",
        name=file_path,
        depth=10,
        direction="downstream"
    )
    
    # Extract affected collections
    collections = [
        node['name'] 
        for node in lineage['nodes'] 
        if node['namespace'].startswith('milvus://')
    ]
    
    return collections
```

## Benefits of OpenLineage Integration

### 1. Data Lineage Tracking
- Track data flow from git repos → files → embeddings → collections
- Understand dependencies between datasets
- Impact analysis for changes

### 2. Compliance & Auditing
- Complete audit trail of data transformations
- Track data provenance
- Meet regulatory requirements

### 3. Debugging & Troubleshooting
- Trace data quality issues to source
- Understand transformation pipeline
- Identify bottlenecks

### 4. Optimization
- Identify redundant transformations
- Optimize data pipelines
- Resource usage analysis

## Implementation Checklist

- [x] Design Airflow 3.x compatible DAGs
- [x] Define OpenLineage event structure
- [x] Create custom lineage emitter
- [ ] Implement lineage in incremental indexer
- [ ] Configure OpenLineage backend (Marquez/Egeria)
- [ ] Add lineage to all DAGs
- [ ] Create lineage visualization dashboard
- [ ] Document lineage query patterns
- [ ] Test end-to-end lineage tracking

## Next Steps

1. **Deploy Marquez**: Set up OpenLineage backend
2. **Update DAGs**: Migrate to Airflow 3.x TaskFlow API
3. **Emit Events**: Add lineage emission to all operations
4. **Visualize**: Create lineage graph visualization
5. **Integrate with Egeria**: Connect to Egeria metadata repository