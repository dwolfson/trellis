# Airflow Integration Design

## Overview

Create Apache Airflow DAGs to automate routine maintenance tasks for the Egeria Advisor system, including incremental indexing, health checks, and monitoring.

## Airflow DAGs

### 1. Incremental Update DAG
**Purpose**: Automatically update vector store with new/modified content

**Schedule**: Every 6 hours (configurable)

**Tasks**:
1. **sync_repositories**: Pull latest changes from git repos
2. **detect_changes**: Run incremental indexer change detection
3. **apply_updates**: Apply incremental updates to collections
4. **verify_updates**: Verify update success
5. **update_metrics**: Record update metrics in MLflow
6. **send_notification**: Send success/failure notification

**Dependencies**:
```
sync_repositories → detect_changes → apply_updates → verify_updates → update_metrics → send_notification
```

### 2. Health Check DAG
**Purpose**: Monitor collection and system health

**Schedule**: Every hour

**Tasks**:
1. **check_milvus_connection**: Verify Milvus connectivity
2. **check_collections**: Verify all collections are accessible
3. **check_entity_counts**: Verify entity counts are stable
4. **check_ollama**: Verify Ollama service is running
5. **check_mlflow**: Verify MLflow tracking server
6. **check_system_resources**: Monitor CPU, memory, disk
7. **record_health_metrics**: Store health metrics
8. **alert_on_issues**: Send alerts if issues detected

**Dependencies**:
```
[check_milvus_connection, check_ollama, check_mlflow, check_system_resources]
    ↓
check_collections → check_entity_counts
    ↓
record_health_metrics → alert_on_issues
```

### 3. Metrics Aggregation DAG
**Purpose**: Aggregate and report metrics

**Schedule**: Daily at midnight

**Tasks**:
1. **aggregate_query_metrics**: Summarize daily query stats
2. **aggregate_performance_metrics**: Summarize performance data
3. **generate_daily_report**: Create daily report
4. **cleanup_old_metrics**: Remove metrics older than retention period
5. **export_to_mlflow**: Export aggregated metrics to MLflow
6. **send_daily_report**: Email daily report

**Dependencies**:
```
[aggregate_query_metrics, aggregate_performance_metrics]
    ↓
generate_daily_report → export_to_mlflow → send_daily_report
    ↓
cleanup_old_metrics
```

### 4. Full Re-index DAG
**Purpose**: Perform full re-indexing (manual trigger)

**Schedule**: Manual trigger only

**Tasks**:
1. **backup_collections**: Backup existing collections
2. **drop_collections**: Drop existing collections
3. **recreate_collections**: Create fresh collections
4. **ingest_all_data**: Full data ingestion
5. **verify_ingestion**: Verify entity counts
6. **update_tracking_db**: Update incremental indexing tracking
7. **send_completion_notification**: Notify completion

**Dependencies**:
```
backup_collections → drop_collections → recreate_collections → ingest_all_data
    ↓
verify_ingestion → update_tracking_db → send_completion_notification
```

### 5. Repository Sync DAG
**Purpose**: Keep git repositories up to date

**Schedule**: Every 4 hours

**Tasks**:
1. **fetch_repo_updates**: Git fetch for all repos
2. **check_for_changes**: Check if updates available
3. **pull_updates**: Git pull if changes detected
4. **trigger_incremental_update**: Trigger incremental update DAG if changes
5. **record_sync_metrics**: Log sync metrics

**Dependencies**:
```
fetch_repo_updates → check_for_changes → pull_updates → trigger_incremental_update → record_sync_metrics
```

## Directory Structure

```
egeria-advisor/
├── airflow/
│   ├── dags/
│   │   ├── incremental_update_dag.py
│   │   ├── health_check_dag.py
│   │   ├── metrics_aggregation_dag.py
│   │   ├── full_reindex_dag.py
│   │   └── repository_sync_dag.py
│   ├── operators/
│   │   ├── egeria_operators.py
│   │   └── notification_operators.py
│   ├── sensors/
│   │   └── collection_sensors.py
│   ├── config/
│   │   └── airflow_config.yaml
│   └── plugins/
│       └── egeria_plugin.py
```

## Custom Operators

### EgeriaIncrementalUpdateOperator
```python
class EgeriaIncrementalUpdateOperator(BaseOperator):
    """Operator to run incremental updates."""
    
    def __init__(self, collection_name: str, **kwargs):
        super().__init__(**kwargs)
        self.collection_name = collection_name
    
    def execute(self, context):
        from advisor.incremental_indexer import IncrementalIndexer
        # Run incremental update
        # Return update statistics
```

### EgeriaHealthCheckOperator
```python
class EgeriaHealthCheckOperator(BaseOperator):
    """Operator to check system health."""
    
    def execute(self, context):
        from advisor.metrics_collector import get_metrics_collector
        # Check health
        # Return health status
```

### EgeriaNotificationOperator
```python
class EgeriaNotificationOperator(BaseOperator):
    """Operator to send notifications."""
    
    def __init__(self, notification_type: str, **kwargs):
        super().__init__(**kwargs)
        self.notification_type = notification_type
    
    def execute(self, context):
        # Send email/Slack notification
```

## Configuration

### Airflow Variables
```python
# Collection names
EGERIA_COLLECTIONS = ["pyegeria", "pyegeria_cli", "pyegeria_drE", 
                      "egeria_docs", "egeria_java", "egeria_ui"]

# Paths
EGERIA_REPO_DIR = "/path/to/repos"
EGERIA_DATA_DIR = "/path/to/data"

# Notification settings
NOTIFICATION_EMAIL = "admin@example.com"
SLACK_WEBHOOK_URL = "https://hooks.slack.com/..."

# Thresholds
HEALTH_CHECK_THRESHOLD = 0.8
QUERY_LATENCY_THRESHOLD_MS = 1000
ERROR_RATE_THRESHOLD = 0.05
```

### Airflow Connections
```python
# Milvus connection
milvus_default = {
    "conn_type": "http",
    "host": "localhost",
    "port": 19530
}

# MLflow connection
mlflow_default = {
    "conn_type": "http",
    "host": "localhost",
    "port": 5025
}

# Ollama connection
ollama_default = {
    "conn_type": "http",
    "host": "localhost",
    "port": 11434
}
```

## DAG Configuration

### Default Arguments
```python
default_args = {
    'owner': 'egeria-advisor',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email': ['admin@example.com'],
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(hours=2)
}
```

### DAG Schedules
```python
# Incremental updates: Every 6 hours
incremental_schedule = "0 */6 * * *"

# Health checks: Every hour
health_check_schedule = "0 * * * *"

# Metrics aggregation: Daily at midnight
metrics_schedule = "0 0 * * *"

# Repository sync: Every 4 hours
repo_sync_schedule = "0 */4 * * *"

# Full re-index: Manual only
reindex_schedule = None
```

## Monitoring & Alerting

### Success Metrics
- Update completion time
- Number of files updated
- Number of chunks added/removed
- Health check pass rate
- System resource utilization

### Alert Conditions
- Update failure
- Health check failure
- High error rate (>5%)
- High latency (>1000ms p95)
- Low cache hit rate (<70%)
- High resource usage (>90%)

### Notification Channels
1. **Email**: Critical failures and daily reports
2. **Slack**: Real-time alerts and status updates
3. **MLflow**: All metrics and run history
4. **Dashboard**: Real-time status display

## Example DAG: Incremental Update

```python
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator

default_args = {
    'owner': 'egeria-advisor',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': True,
    'retries': 2,
    'retry_delay': timedelta(minutes=5)
}

dag = DAG(
    'egeria_incremental_update',
    default_args=default_args,
    description='Incremental update of Egeria collections',
    schedule_interval='0 */6 * * *',  # Every 6 hours
    catchup=False
)

def sync_repositories(**context):
    """Sync git repositories."""
    import subprocess
    repos = [
        '/path/to/egeria-python',
        '/path/to/egeria',
        '/path/to/egeria-docs'
    ]
    for repo in repos:
        subprocess.run(['git', '-C', repo, 'pull'], check=True)

def detect_changes(**context):
    """Detect file changes."""
    from advisor.incremental_indexer import IncrementalIndexer
    from advisor.collection_config import get_enabled_collections
    
    changes_by_collection = {}
    for collection in get_enabled_collections():
        indexer = IncrementalIndexer(
            collection_name=collection.name,
            source_paths=get_source_paths(collection),
            file_patterns=get_file_patterns(collection)
        )
        changes = indexer.detect_changes()
        changes_by_collection[collection.name] = changes
    
    # Push to XCom
    context['task_instance'].xcom_push(
        key='changes',
        value=changes_by_collection
    )

def apply_updates(**context):
    """Apply incremental updates."""
    from advisor.incremental_indexer import IncrementalIndexer
    
    changes = context['task_instance'].xcom_pull(
        task_ids='detect_changes',
        key='changes'
    )
    
    results = {}
    for collection_name, changeset in changes.items():
        if changeset.has_changes:
            indexer = IncrementalIndexer(collection_name=collection_name, ...)
            result = indexer.apply_updates(changeset)
            results[collection_name] = result
    
    context['task_instance'].xcom_push(key='results', value=results)

# Define tasks
sync_task = PythonOperator(
    task_id='sync_repositories',
    python_callable=sync_repositories,
    dag=dag
)

detect_task = PythonOperator(
    task_id='detect_changes',
    python_callable=detect_changes,
    dag=dag
)

update_task = PythonOperator(
    task_id='apply_updates',
    python_callable=apply_updates,
    dag=dag
)

# Set dependencies
sync_task >> detect_task >> update_task
```

## Deployment

### Installation
```bash
# Install Airflow
pip install apache-airflow

# Initialize Airflow database
airflow db init

# Create admin user
airflow users create \
    --username admin \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email admin@example.com

# Start Airflow webserver
airflow webserver --port 8080

# Start Airflow scheduler
airflow scheduler
```

### Configuration
```bash
# Set Airflow home
export AIRFLOW_HOME=/path/to/egeria-advisor/airflow

# Copy DAGs
cp airflow/dags/*.py $AIRFLOW_HOME/dags/

# Set variables
airflow variables set EGERIA_COLLECTIONS '["pyegeria", "pyegeria_cli"]'
airflow variables set EGERIA_REPO_DIR '/path/to/repos'
```

### Testing
```bash
# Test DAG
airflow dags test egeria_incremental_update 2024-01-01

# Trigger DAG manually
airflow dags trigger egeria_incremental_update

# View DAG runs
airflow dags list-runs -d egeria_incremental_update
```

## Best Practices

### Error Handling
- Retry failed tasks with exponential backoff
- Send notifications on persistent failures
- Log all errors to MLflow
- Implement circuit breakers for external services

### Performance
- Use task parallelism where possible
- Implement task pools for resource-intensive operations
- Cache intermediate results
- Use XCom efficiently (avoid large data transfers)

### Monitoring
- Track DAG run duration
- Monitor task success rates
- Alert on SLA violations
- Dashboard for DAG status

### Security
- Use Airflow connections for credentials
- Encrypt sensitive variables
- Implement RBAC for DAG access
- Audit log all operations

## Success Criteria

1. ✅ Automated incremental updates every 6 hours
2. ✅ Health checks every hour with alerting
3. ✅ Daily metrics aggregation and reporting
4. ✅ Manual full re-index capability
5. ✅ Repository sync automation
6. ✅ Comprehensive error handling
7. ✅ MLflow integration for tracking
8. ✅ Notification system (email/Slack)

## Future Enhancements

1. **Dynamic Scheduling**: Adjust schedule based on change frequency
2. **Smart Triggers**: Trigger updates on git webhooks
3. **A/B Testing**: Test different indexing strategies
4. **Auto-scaling**: Scale resources based on workload
5. **Multi-region**: Deploy across multiple regions
6. **Disaster Recovery**: Automated backup and restore