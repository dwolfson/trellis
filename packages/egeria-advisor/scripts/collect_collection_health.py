#!/usr/bin/env python3
"""
Collect and record collection health metrics.

This script checks the health of all pgvector collections and records
metrics to the metrics database for display in the dashboard.
"""

import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from advisor.vector_store import get_vector_store
from advisor.metrics_collector import get_metrics_collector, CollectionHealth
from advisor.collection_config import get_enabled_collections


def _table_exists(store, table: str) -> bool:
    conn = store._get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
                (table,),
            )
            return bool(cur.fetchone()[0])
    finally:
        store._put_conn(conn)


def _table_count(store, table: str) -> int:
    conn = store._get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT count(*) FROM "{table}"')
            return cur.fetchone()[0]
    finally:
        store._put_conn(conn)


def calculate_health_score(entity_count: int, expected_min: int = 100) -> float:
    """
    Calculate health score for a collection.
    
    Args:
        entity_count: Number of entities in collection
        expected_min: Minimum expected entities for healthy collection
        
    Returns:
        Health score between 0.0 and 1.0
    """
    if entity_count >= expected_min:
        return 1.0
    elif entity_count > 0:
        return entity_count / expected_min
    else:
        return 0.0


def determine_status(health_score: float) -> str:
    """
    Determine collection status from health score.
    
    Args:
        health_score: Health score between 0.0 and 1.0
        
    Returns:
        Status string: 'healthy', 'degraded', or 'critical'
    """
    if health_score >= 0.8:
        return 'healthy'
    elif health_score >= 0.3:
        return 'degraded'
    else:
        return 'critical'


def get_collection_size_mb(collection_name: str, entity_count: int) -> float:
    """
    Estimate collection storage size in MB.
    
    Args:
        collection_name: Name of the collection
        entity_count: Number of entities in collection
        
    Returns:
        Estimated size in MB
    """
    try:
        # Estimate based on entity count
        # Assume average of 1KB per entity (text + embedding + metadata)
        estimated_size_mb = (entity_count * 1024) / (1024 * 1024)
        
        return estimated_size_mb
    except Exception as e:
        logger.debug(f"Could not estimate size for {collection_name}: {e}")
        return 0.0


def collect_collection_health():
    """Collect health metrics for all collections."""
    logger.info("Collecting collection health metrics...")
    
    # Connect to vector store
    vector_store = get_vector_store()
    vector_store.connect()
    
    # Get metrics collector
    collector = get_metrics_collector()
    
    # Get enabled collections
    enabled_collections = get_enabled_collections()
    
    current_time = time.time()
    
    for collection_metadata in enabled_collections:
        collection_name = collection_metadata.name
        table_name = vector_store._table(collection_name)

        try:
            # Check if collection table exists
            if not _table_exists(vector_store, table_name):
                logger.warning(f"Collection {collection_name} does not exist")

                # Record as critical
                health = CollectionHealth(
                    collection_name=collection_name,
                    last_check=current_time,
                    entity_count=0,
                    health_score=0.0,
                    storage_size_mb=0.0,
                    last_update=current_time,
                    status='critical'
                )
                collector.record_collection_health(health)
                continue

            # Get entity count
            entity_count = _table_count(vector_store, table_name)
            
            # Calculate health score
            health_score = calculate_health_score(entity_count)
            
            # Determine status
            status = determine_status(health_score)
            
            # Get storage size
            storage_size_mb = get_collection_size_mb(collection_name, entity_count)
            
            # Create health record
            health = CollectionHealth(
                collection_name=collection_name,
                last_check=current_time,
                entity_count=entity_count,
                health_score=health_score,
                storage_size_mb=storage_size_mb,
                last_update=current_time,
                status=status
            )
            
            # Record health
            collector.record_collection_health(health)
            
            logger.info(
                f"✓ {collection_name}: {entity_count:,} entities, "
                f"health={health_score:.2f}, status={status}"
            )
            
        except Exception as e:
            logger.error(f"Failed to collect health for {collection_name}: {e}")
            
            # Record as critical with error
            health = CollectionHealth(
                collection_name=collection_name,
                last_check=current_time,
                entity_count=0,
                health_score=0.0,
                storage_size_mb=0.0,
                last_update=current_time,
                status='critical'
            )
            collector.record_collection_health(health)
    
    logger.info("Collection health metrics collected successfully")


def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Collect collection health metrics")
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run continuously, collecting metrics every 5 minutes"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Interval in seconds for continuous mode (default: 300)"
    )
    
    args = parser.parse_args()
    
    if args.continuous:
        logger.info(f"Running in continuous mode (interval: {args.interval}s)")
        logger.info("Press Ctrl+C to stop")
        
        try:
            while True:
                collect_collection_health()
                logger.info(f"Sleeping for {args.interval} seconds...")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("Stopped by user")
    else:
        collect_collection_health()


if __name__ == "__main__":
    main()