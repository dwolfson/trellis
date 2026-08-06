#!/usr/bin/env python3
"""Print the number of vectors in each collection of the active vector store backend."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.vector_store import get_vector_store
from advisor.collection_config import get_enabled_collections

store = get_vector_store()
store.connect()

print(f"{'Collection':<25} {'Vectors':>10}")
print("-" * 37)

total = 0
conn = store._get_conn()
try:
    with conn.cursor() as cur:
        for collection in get_enabled_collections():
            table = store._table(collection.name)
            try:
                cur.execute(f'SELECT count(*) FROM "{table}"')
                count = cur.fetchone()[0]
            except Exception:
                conn.rollback()
                print(f"{collection.name:<25} {'(not found)':>10}")
                continue
            total += count
            print(f"{collection.name:<25} {count:>10,}")
finally:
    store._put_conn(conn)

print("-" * 37)
print(f"{'TOTAL':<25} {total:>10,}")
