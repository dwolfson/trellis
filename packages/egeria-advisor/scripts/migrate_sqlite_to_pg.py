#!/usr/bin/env python3
"""
Migration script to transfer query metrics, symbol store, change tracking, and ingest logs
from SQLite databases to Consolidated PostgreSQL.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from loguru import logger
import psycopg2

# Adjust path to import advisor modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.db_consolidated import get_db_manager
from advisor.config import get_full_config

# Resolve SQLite database paths
config = get_full_config()
data_dir = Path(config.get("data_dir", "data"))

SQLITE_DBS = {
    "metrics": data_dir / "metrics.db",
    "code_symbols": data_dir / "code_symbols.db",
    "index_state": data_dir / "index_state.db",
    "admin_state": data_dir / "admin_state.db",
}


def migrate_query_metrics(sqlite_conn, pg_conn) -> int:
    """Migrate query_metrics table."""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM query_metrics")
    rows = cursor.fetchall()
    if not rows:
        return 0

    count = 0
    with pg_conn.cursor() as pg_cur:
        # Clear existing to prevent duplicate IDs or conflicts on import
        pg_cur.execute("TRUNCATE TABLE query_metrics CASCADE")
        
        insert_sql = """
            INSERT INTO query_metrics (
                id, timestamp, query_text, collection_name, latency_ms, cache_hit, success,
                query_type, error_message, result_count, embedding_time_ms, search_time_ms,
                llm_time_ms, avg_relevance_score, sources_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        for r in rows:
            d = dict(r)
            pg_cur.execute(insert_sql, (
                d.get("id"), d.get("timestamp"), d.get("query_text"), d.get("collection_name"), d.get("latency_ms"),
                bool(d.get("cache_hit")), bool(d.get("success")), d.get("query_type"), d.get("error_message"), d.get("result_count"),
                d.get("embedding_time_ms"), d.get("search_time_ms"), d.get("llm_time_ms"), d.get("avg_relevance_score"),
                d.get("sources_json")
            ))
            count += 1
    pg_conn.commit()
    return count


def migrate_collection_health(sqlite_conn, pg_conn) -> int:
    """Migrate collection_health table."""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM collection_health")
    rows = cursor.fetchall()
    if not rows:
        return 0

    count = 0
    with pg_conn.cursor() as pg_cur:
        pg_cur.execute("TRUNCATE TABLE collection_health CASCADE")
        insert_sql = """
            INSERT INTO collection_health (
                collection_name, last_check, entity_count, health_score, storage_size_mb,
                last_update, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        for r in rows:
            d = dict(r)
            pg_cur.execute(insert_sql, (
                d.get("collection_name"), d.get("last_check"), d.get("entity_count"), d.get("health_score"),
                d.get("storage_size_mb"), d.get("last_update"), d.get("status")
            ))
            count += 1
    pg_conn.commit()
    return count


def migrate_system_metrics(sqlite_conn, pg_conn) -> int:
    """Migrate system_metrics table."""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM system_metrics")
    rows = cursor.fetchall()
    if not rows:
        return 0

    count = 0
    with pg_conn.cursor() as pg_cur:
        pg_cur.execute("TRUNCATE TABLE system_metrics CASCADE")
        insert_sql = """
            INSERT INTO system_metrics (
                timestamp, cpu_percent, memory_percent, gpu_percent, disk_io_read_mb,
                disk_io_write_mb, network_sent_mb, network_recv_mb
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        for r in rows:
            d = dict(r)
            pg_cur.execute(insert_sql, (
                d.get("timestamp"), d.get("cpu_percent"), d.get("memory_percent"), d.get("gpu_percent"),
                d.get("disk_io_read_mb"), d.get("disk_io_write_mb"), d.get("network_sent_mb"), d.get("network_recv_mb")
            ))
            count += 1
    pg_conn.commit()
    return count


def migrate_error_log(sqlite_conn, pg_conn) -> int:
    """Migrate error_log table."""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM error_log")
    rows = cursor.fetchall()
    if not rows:
        return 0

    count = 0
    with pg_conn.cursor() as pg_cur:
        pg_cur.execute("TRUNCATE TABLE error_log CASCADE")
        insert_sql = """
            INSERT INTO error_log (
                id, timestamp, error_type, error_message, stack_trace, context
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """
        for r in rows:
            d = dict(r)
            pg_cur.execute(insert_sql, (
                d.get("id"), d.get("timestamp"), d.get("error_type"), d.get("error_message"), d.get("stack_trace"), d.get("context")
            ))
            count += 1
    pg_conn.commit()
    return count


def migrate_plan_events(sqlite_conn, pg_conn) -> int:
    """Migrate plan_events table."""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM plan_events")
    rows = cursor.fetchall()
    if not rows:
        return 0

    count = 0
    with pg_conn.cursor() as pg_cur:
        pg_cur.execute("TRUNCATE TABLE plan_events CASCADE")
        insert_sql = """
            INSERT INTO plan_events (
                id, timestamp, doc_id, event_type, title, command_families, outcome_status, perspective
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        for r in rows:
            d = dict(r)
            pg_cur.execute(insert_sql, (
                d.get("id"), d.get("timestamp"), d.get("doc_id"), d.get("event_type"), d.get("title"), d.get("command_families"),
                d.get("outcome_status"), d.get("perspective")
            ))
            count += 1
    pg_conn.commit()
    return count


def migrate_code_symbols(sqlite_conn, pg_conn) -> int:
    """Migrate code_symbols table."""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM code_symbols")
    rows = cursor.fetchall()
    if not rows:
        return 0

    count = 0
    with pg_conn.cursor() as pg_cur:
        pg_cur.execute("TRUNCATE TABLE code_symbols CASCADE")
        insert_sql = """
            INSERT INTO code_symbols (
                id, collection, file_path, language, kind, name, qualified_name,
                signature, docstring, parent_class, return_type, start_line, end_line,
                is_private, is_async, complexity
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        for r in rows:
            d = dict(r)
            pg_cur.execute(insert_sql, (
                d.get("id"), d.get("collection"), d.get("file_path"), d.get("language"), d.get("kind"), d.get("name"), d.get("qualified_name"),
                d.get("signature"), d.get("docstring"), d.get("parent_class"), d.get("return_type"), d.get("start_line"), d.get("end_line"),
                bool(d.get("is_private")), bool(d.get("is_async")), d.get("complexity")
            ))
            count += 1
    pg_conn.commit()
    return count


def migrate_indexed_files(sqlite_conn, pg_conn) -> int:
    """Migrate indexed_files and index_metadata tables."""
    cursor = sqlite_conn.cursor()
    
    # 1. indexed_files
    cursor.execute("SELECT * FROM indexed_files")
    rows = cursor.fetchall()
    files_count = 0
    if rows:
        with pg_conn.cursor() as pg_cur:
            pg_cur.execute("TRUNCATE TABLE indexed_files CASCADE")
            insert_sql = """
                INSERT INTO indexed_files (
                    file_path, collection_name, last_modified, content_hash,
                    last_indexed, chunk_count, entity_ids
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            for r in rows:
                d = dict(r)
                pg_cur.execute(insert_sql, (
                    d.get("file_path"), d.get("collection_name"), d.get("last_modified"), d.get("content_hash"),
                    d.get("last_indexed"), d.get("chunk_count"), d.get("entity_ids")
                ))
                files_count += 1
        pg_conn.commit()

    # 2. index_metadata
    cursor.execute("SELECT * FROM index_metadata")
    meta_rows = cursor.fetchall()
    meta_count = 0
    if meta_rows:
        with pg_conn.cursor() as pg_cur:
            pg_cur.execute("TRUNCATE TABLE index_metadata CASCADE")
            insert_sql = """
                INSERT INTO index_metadata (
                    collection_name, last_full_index, total_files, total_chunks
                ) VALUES (%s, %s, %s, %s)
            """
            for r in meta_rows:
                d = dict(r)
                pg_cur.execute(insert_sql, (
                    d.get("collection_name"), d.get("last_full_index"), d.get("total_files"), d.get("total_chunks")
                ))
                meta_count += 1
        pg_conn.commit()

    return files_count


def migrate_ingest_log(sqlite_conn, pg_conn) -> int:
    """Migrate ingest_log table from admin_state.db."""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM ingest_log")
    rows = cursor.fetchall()
    if not rows:
        return 0

    count = 0
    with pg_conn.cursor() as pg_cur:
        pg_cur.execute("TRUNCATE TABLE ingest_log CASCADE")
        insert_sql = """
            INSERT INTO ingest_log (
                collection_name, last_ingested, files_processed, chunks_created, source
            ) VALUES (%s, %s, %s, %s, %s)
        """
        for r in rows:
            d = dict(r)
            pg_cur.execute(insert_sql, (
                d.get("collection_name"), d.get("last_ingested"), d.get("files_processed"), d.get("chunks_created"), d.get("source")
            ))
            count += 1
    pg_conn.commit()
    return count


def main():
    logger.info("Starting SQLite to consolidated PostgreSQL database migration...")
    
    # Get Postgres connection
    db_mgr = get_db_manager()
    db_mgr.connect()
    pg_conn = db_mgr.get_connection()

    try:
        # 1. Migrate metrics.db
        db_path = SQLITE_DBS["metrics"]
        if db_path.exists():
            logger.info(f"Migrating metrics database: {db_path}")
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                qm = migrate_query_metrics(conn, pg_conn)
                ch = migrate_collection_health(conn, pg_conn)
                sm = migrate_system_metrics(conn, pg_conn)
                el = migrate_error_log(conn, pg_conn)
                pe = migrate_plan_events(conn, pg_conn)
                logger.info(f"✓ Metrics db migrated: {qm} queries, {ch} health records, {sm} system metrics, {el} errors, {pe} plan events.")
            finally:
                conn.close()
        else:
            logger.warning(f"Metrics DB not found at {db_path} - skipping.")

        # 2. Migrate code_symbols.db
        db_path = SQLITE_DBS["code_symbols"]
        if db_path.exists():
            logger.info(f"Migrating code symbols database: {db_path}")
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cs = migrate_code_symbols(conn, pg_conn)
                logger.info(f"✓ Code symbols db migrated: {cs} symbols.")
            finally:
                conn.close()
        else:
            logger.warning(f"Code symbols DB not found at {db_path} - skipping.")

        # 3. Migrate index_state.db
        db_path = SQLITE_DBS["index_state"]
        if db_path.exists():
            logger.info(f"Migrating indexing state database: {db_path}")
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                files = migrate_indexed_files(conn, pg_conn)
                logger.info(f"✓ Indexing state db migrated: {files} files tracked.")
            finally:
                conn.close()
        else:
            logger.warning(f"Indexing state DB not found at {db_path} - skipping.")

        # 4. Migrate admin_state.db
        db_path = SQLITE_DBS["admin_state"]
        if db_path.exists():
            logger.info(f"Migrating admin state database: {db_path}")
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                ingests = migrate_ingest_log(conn, pg_conn)
                logger.info(f"✓ Admin state db migrated: {ingests} ingestion log entries.")
            finally:
                conn.close()
        else:
            logger.warning(f"Admin state DB not found at {db_path} - skipping.")

        logger.info("★ Database migration successfully completed!")

        # 5. Sync sequences
        logger.info("Syncing PostgreSQL sequences...")
        tables = [
            ("query_metrics", "query_metrics_id_seq"),
            ("code_symbols", "code_symbols_id_seq"),
            ("code_relationships", "code_relationships_id_seq"),
            ("error_log", "error_log_id_seq"),
            ("plan_events", "plan_events_id_seq"),
        ]
        with pg_conn.cursor() as cur:
            for table, seq in tables:
                cur.execute(f"SELECT COALESCE(MAX(id), 0) as max_id FROM {table}")
                max_id = cur.fetchone()[0]
                cur.execute(f"SELECT setval('{seq}', %s, false)", (max_id + 1,))
                logger.info(f"✓ Synced sequence {seq} to {max_id + 1}")
        pg_conn.commit()

    except Exception as e:
        logger.error(f"Migration failed with error: {e}")
        sys.exit(1)
    finally:
        db_mgr.put_connection(pg_conn)
        db_mgr.disconnect()


if __name__ == "__main__":
    main()
