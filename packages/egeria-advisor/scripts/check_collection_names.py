#!/usr/bin/env python3
"""Check what's stored in collection_name field."""

import sqlite3
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

db_path = Path("data/metrics.db")

if not db_path.exists():
    print(f"Database not found: {db_path}")
    sys.exit(1)

with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("""
        SELECT collection_name, query_text, timestamp
        FROM query_metrics
        ORDER BY timestamp DESC
        LIMIT 10
    """)
    
    print("Recent queries and their collection_name values:")
    print("-" * 100)
    
    for row in cursor.fetchall():
        print(f"Collection: {row['collection_name']}")
        print(f"Query: {row['query_text'][:80]}...")
        print("-" * 100)