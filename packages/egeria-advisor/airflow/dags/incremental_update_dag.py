"""
Airflow DAG for automated incremental updates of Egeria collections.

This DAG runs every 6 hours to:
1. Sync git repositories
2. Detect file changes
3. Apply incremental updates
4. Verify updates
5. Record metrics
6. Send notifications
"""

from datetime import datetime, timedelta
from pathlib import Path
import sys

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from airflow.utils.dates import days_ago

# Add advisor to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# Default arguments
default_args = {
    'owner': 'egeria-advisor',
    'depends_on_past': False,
    'start_date': days_ago(1),
    'email': ['admin@example.com'],
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(hours=2)
}


def sync_repositories(**context):
    """
    Sync git repositories to get latest changes.
    
    Returns:
        Dict with sync results per repository
    """
    import subprocess
    from loguru import logger
    
    # Get repository paths from Airflow variables
    from airflow.models import Variable
    repo_dir = Variable.get("EGERIA_REPO_DIR", "/path/to/repos")
    
    repos = {
        'egeria-python': f'{repo_dir}/egeria-python',
        'egeria': f'{repo_dir}/egeria',
        'egeria-docs': f'{repo_dir}/egeria-docs'
    }
    
    results = {}
    for name, path in repos.items():
        try:
            # Git fetch
            subprocess.run(
                ['git', '-C', path, 'fetch'],
                check=True,
                capture_output=True,
                text=True
            )
            
            # Check if updates available
            result = subprocess.run(
                ['git', '-C', path, 'rev-list', 'HEAD...origin/main', '--count'],
                capture_output=True,
                text=True,
                check=True
            )
            commits_behind = int(result.stdout.strip())
            
            if commits_behind > 0:
                # Pull updates
                subprocess.run(
                    ['git', '-C', path, 'pull'],
                    check=True,
                    capture_output=True,
                    text=True
                )
                logger.info(f"Updated {name}: {commits_behind} new commits")
                results[name] = {'updated': True, 'commits': commits_behind}
            else:
                logger.info(f"No updates for {name}")
                results[name] = {'updated': False, 'commits': 0}
        
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to sync {name}: {e}")
            results[name] = {'updated': False, 'error': str(e)}
    
    # Push results to XCom
    context['task_instance'].xcom_push(key='sync_results', value=results)
    return results


def detect_changes(**context):
    """
    Detect file changes for each collection.
    
    Returns:
        Dict with changes per collection
    """
    from advisor.incremental_indexer import IncrementalIndexer
    from advisor.collection_config import get_enabled_collections, get_collection
    from loguru import logger
    
    # Get sync results
    sync_results = context['task_instance'].xcom_pull(
        task_ids='sync_repositories',
        key='sync_results'
    )
    
    # Check if any repos were updated
    any_updates = any(r.get('updated', False) for r in sync_results.values())
    
    if not any_updates:
        logger.info("No repository updates, skipping change detection")
        context['task_instance'].xcom_push(key='changes', value={})
        return {}
    
    changes_by_collection = {}
    
    for collection_meta in get_enabled_collections():
        try:
            # Get source paths for collection
            from scripts.ingest_collections import (
                get_collection_source_paths,
                get_file_patterns
            )
            
            source_paths = get_collection_source_paths(collection_meta)
            file_patterns = get_file_patterns(collection_meta)
            
            if not source_paths:
                logger.warning(f"No source paths for {collection_meta.name}")
                continue
            
            # Create indexer
            indexer = IncrementalIndexer(
                collection_name=collection_meta.name,
                source_paths=source_paths,
                file_patterns=file_patterns
            )
            
            # Detect changes
            changeset = indexer.detect_changes()
            
            logger.info(
                f"{collection_meta.name}: {changeset.total_changes} changes "
                f"({len(changeset.new_files)} new, {len(changeset.modified_files)} modified, "
                f"{len(changeset.deleted_files)} deleted)"
            )
            
            # Store changeset info (not the objects themselves)
            changes_by_collection[collection_meta.name] = {
                'new_files': [str(f) for f in changeset.new_files],
                'modified_files': [str(f) for f in changeset.modified_files],
                'deleted_files': [str(f) for f in changeset.deleted_files],
                'total_changes': changeset.total_changes,
                'has_changes': changeset.has_changes
            }
        
        except Exception as e:
            logger.error(f"Failed to detect changes for {collection_meta.name}: {e}")
            changes_by_collection[collection_meta.name] = {
                'error': str(e),
                'has_changes': False
            }
    
    # Push to XCom
    context['task_instance'].xcom_push(key='changes', value=changes_by_collection)
    return changes_by_collection


def apply_updates(**context):
    """
    Apply incremental updates to collections with changes.
    
    Returns:
        Dict with update results per collection
    """
    from advisor.incremental_indexer import IncrementalIndexer
    from advisor.collection_config import get_collection
    from loguru import logger
    
    # Get detected changes
    changes = context['task_instance'].xcom_pull(
        task_ids='detect_changes',
        key='changes'
    )
    
    if not changes:
        logger.info("No changes detected, skipping updates")
        return {}
    
    results = {}
    
    for collection_name, change_info in changes.items():
        if not change_info.get('has_changes', False):
            logger.info(f"No changes for {collection_name}, skipping")
            continue
        
        try:
            # Recreate changeset from stored info
            from advisor.incremental_indexer import ChangeSet
            from pathlib import Path
            
            changeset = ChangeSet(
                new_files=[Path(f) for f in change_info['new_files']],
                modified_files=[Path(f) for f in change_info['modified_files']],
                deleted_files=[Path(f) for f in change_info['deleted_files']],
                unchanged_files=[]
            )
            
            # Get collection metadata
            collection_meta = get_collection(collection_name)
            from scripts.ingest_collections import (
                get_collection_source_paths,
                get_file_patterns
            )
            
            source_paths = get_collection_source_paths(collection_meta)
            file_patterns = get_file_patterns(collection_meta)
            
            # Create indexer
            indexer = IncrementalIndexer(
                collection_name=collection_name,
                source_paths=source_paths,
                file_patterns=file_patterns
            )
            
            # Apply updates
            result = indexer.apply_updates(changeset, dry_run=False)
            
            logger.info(
                f"{collection_name}: Updated {result.files_added + result.files_modified} files, "
                f"+{result.chunks_added} -{result.chunks_removed} chunks in {result.duration:.2f}s"
            )
            
            results[collection_name] = {
                'success': result.success,
                'files_added': result.files_added,
                'files_modified': result.files_modified,
                'files_deleted': result.files_deleted,
                'chunks_added': result.chunks_added,
                'chunks_removed': result.chunks_removed,
                'duration': result.duration,
                'error': result.error
            }
        
        except Exception as e:
            logger.error(f"Failed to update {collection_name}: {e}")
            results[collection_name] = {
                'success': False,
                'error': str(e)
            }
    
    # Push to XCom
    context['task_instance'].xcom_push(key='update_results', value=results)
    return results


def verify_updates(**context):
    """
    Verify that updates were successful.
    
    Returns:
        Dict with verification results
    """
    from pymilvus import connections, utility, Collection
    from advisor.config import get_full_config
    from loguru import logger
    
    # Get update results
    results = context['task_instance'].xcom_pull(
        task_ids='apply_updates',
        key='update_results'
    )
    
    if not results:
        logger.info("No updates to verify")
        return {'verified': True, 'collections': {}}
    
    # Connect to Milvus
    config = get_full_config()
    connections.connect(
        alias="default",
        host=config["vector_store"].host,
        port=config["vector_store"].port
    )
    
    verification = {}
    all_verified = True
    
    for collection_name, result in results.items():
        if not result.get('success', False):
            verification[collection_name] = {
                'verified': False,
                'reason': 'Update failed'
            }
            all_verified = False
            continue
        
        try:
            # Check collection exists
            if not utility.has_collection(collection_name):
                verification[collection_name] = {
                    'verified': False,
                    'reason': 'Collection not found'
                }
                all_verified = False
                continue
            
            # Get entity count
            collection = Collection(collection_name)
            collection.load()
            entity_count = collection.num_entities
            
            logger.info(f"{collection_name}: {entity_count} entities")
            
            verification[collection_name] = {
                'verified': True,
                'entity_count': entity_count
            }
        
        except Exception as e:
            logger.error(f"Failed to verify {collection_name}: {e}")
            verification[collection_name] = {
                'verified': False,
                'reason': str(e)
            }
            all_verified = False
    
    result = {
        'verified': all_verified,
        'collections': verification
    }
    
    context['task_instance'].xcom_push(key='verification', value=result)
    return result


def record_metrics(**context):
    """
    Record update metrics in MLflow.
    
    Returns:
        Dict with recorded metrics
    """
    from advisor.mlflow_tracking import get_mlflow_tracker
    from loguru import logger
    
    # Get all results
    sync_results = context['task_instance'].xcom_pull(
        task_ids='sync_repositories',
        key='sync_results'
    )
    changes = context['task_instance'].xcom_pull(
        task_ids='detect_changes',
        key='changes'
    )
    update_results = context['task_instance'].xcom_pull(
        task_ids='apply_updates',
        key='update_results'
    )
    verification = context['task_instance'].xcom_pull(
        task_ids='verify_updates',
        key='verification'
    )
    
    try:
        tracker = get_mlflow_tracker()
        
        # Calculate totals
        total_changes = sum(c.get('total_changes', 0) for c in changes.values())
        total_files_updated = sum(
            r.get('files_added', 0) + r.get('files_modified', 0) 
            for r in update_results.values()
        )
        total_chunks_added = sum(r.get('chunks_added', 0) for r in update_results.values())
        total_chunks_removed = sum(r.get('chunks_removed', 0) for r in update_results.values())
        total_duration = sum(r.get('duration', 0) for r in update_results.values())
        
        # Log metrics
        with tracker.start_run(run_name="incremental_update_dag"):
            tracker.log_params({
                'dag_id': context['dag'].dag_id,
                'execution_date': str(context['execution_date']),
                'collections_updated': len(update_results)
            })
            
            tracker.log_metrics({
                'total_changes': total_changes,
                'files_updated': total_files_updated,
                'chunks_added': total_chunks_added,
                'chunks_removed': total_chunks_removed,
                'duration_seconds': total_duration,
                'verified': int(verification.get('verified', False))
            })
        
        logger.info(f"Recorded metrics: {total_files_updated} files, {total_chunks_added} chunks")
        
        return {
            'recorded': True,
            'total_changes': total_changes,
            'files_updated': total_files_updated
        }
    
    except Exception as e:
        logger.error(f"Failed to record metrics: {e}")
        return {'recorded': False, 'error': str(e)}


def send_notification(**context):
    """
    Send notification about update completion.
    
    Returns:
        Dict with notification status
    """
    from loguru import logger
    
    # Get results
    verification = context['task_instance'].xcom_pull(
        task_ids='verify_updates',
        key='verification'
    )
    update_results = context['task_instance'].xcom_pull(
        task_ids='apply_updates',
        key='update_results'
    )
    
    # Determine status
    success = verification.get('verified', False)
    
    # Build message
    if success:
        message = "✅ Incremental update completed successfully\n\n"
    else:
        message = "❌ Incremental update completed with errors\n\n"
    
    message += f"Execution Date: {context['execution_date']}\n"
    message += f"Collections Updated: {len(update_results)}\n\n"
    
    for collection_name, result in update_results.items():
        if result.get('success'):
            message += f"✓ {collection_name}: "
            message += f"+{result['files_added']} -{result['files_deleted']} files, "
            message += f"+{result['chunks_added']} -{result['chunks_removed']} chunks\n"
        else:
            message += f"✗ {collection_name}: {result.get('error', 'Unknown error')}\n"
    
    logger.info(f"Notification: {message}")
    
    # TODO: Send actual notification (email/Slack)
    # For now, just log
    
    return {'sent': True, 'message': message}


# Create DAG
dag = DAG(
    'egeria_incremental_update',
    default_args=default_args,
    description='Incremental update of Egeria collections',
    schedule_interval='0 */6 * * *',  # Every 6 hours
    catchup=False,
    tags=['egeria', 'incremental', 'update']
)

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

verify_task = PythonOperator(
    task_id='verify_updates',
    python_callable=verify_updates,
    dag=dag
)

metrics_task = PythonOperator(
    task_id='record_metrics',
    python_callable=record_metrics,
    dag=dag
)

notify_task = PythonOperator(
    task_id='send_notification',
    python_callable=send_notification,
    dag=dag
)

# Set dependencies
sync_task >> detect_task >> update_task >> verify_task >> metrics_task >> notify_task