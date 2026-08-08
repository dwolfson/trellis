"""
One-time migration: copy vector data for RE's registered projects out of
Milvus and into the new pgvector store (resource_explorer schema).

Reuses existing embeddings as-is — no re-embedding. Both Milvus and pgvector
stacks confirmed to use the same 384-dim all-MiniLM-L6-v2 model, so a
transplant is safe.

Scope: only the collections attached to projects currently in the registry
(registry.list_all()), not every stray collection Milvus happens to hold —
this Milvus instance also has leftover collections from other apps
(Egeria Advisor's own pre-migration collections, other repos no longer
registered) that are out of scope for this migration.

Idempotent/resumable: for each collection, compares the Milvus row count
against the pgvector table's row count and skips ones that already match —
safe to re-run after an interruption.

Usage (needs pymilvus, which is no longer a resource-explorer dependency —
install ephemerally for this one-time run):

    uv run --with "pymilvus[milvus-lite]>=2.4.0" --package resource-explorer \\
        python packages/resource-explorer/scripts/migrate_vectors_milvus_to_pg.py [--dry-run] [--collection NAME]
"""
from __future__ import annotations

import argparse
import json
import sys

MILVUS_URI = "http://localhost:19530"
MILVUS_TOKEN = ""
BATCH_SIZE = 2000


def get_milvus_client():
    from pymilvus import MilvusClient
    return MilvusClient(uri=MILVUS_URI, token=MILVUS_TOKEN or None)


def registered_collections() -> list[str]:
    """Union of every collection attached to a project currently in the registry."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    names: list[str] = []
    seen: set[str] = set()
    for project in registry.list_all():
        for c in project.collections or []:
            if c not in seen:
                seen.add(c)
                names.append(c)
    return names


def iter_milvus_rows(client, collection: str):
    """Yield every row from a Milvus collection via query_iterator — handles
    collections larger than a single query() call's implicit result cap."""
    iterator = client.query_iterator(
        collection_name=collection,
        filter="id >= 0",
        output_fields=["id", "vector", "text", "metadata_json"],
        batch_size=BATCH_SIZE,
    )
    while True:
        batch = iterator.next()
        if not batch:
            iterator.close()
            break
        yield from batch


def migrate_collection(client, pg, collection: str, dry_run: bool) -> tuple[int, int, bool]:
    """Returns (milvus_count, pg_count_after, migrated_this_run)."""
    if not client.has_collection(collection):
        print(f"  {collection}: not in Milvus (nothing to migrate) — skipping")
        return (0, 0, False)

    stats = client.get_collection_stats(collection)
    milvus_count = int(stats.get("row_count", 0))

    pg_count = 0
    if pg.collection_exists(collection):
        pg_count = int(pg.get_collection_stats(collection).get("num_entities", 0))

    if milvus_count == 0:
        print(f"  {collection}: empty in Milvus — skipping")
        return (0, pg_count, False)

    if pg_count >= milvus_count:
        print(f"  {collection}: already migrated ({pg_count}/{milvus_count} rows) — skipping")
        return (milvus_count, pg_count, False)

    print(f"  {collection}: {milvus_count} rows in Milvus, {pg_count} in pgvector — migrating...")
    if dry_run:
        return (milvus_count, pg_count, False)

    ids: list[str] = []
    embeddings: list[list[float]] = []
    texts: list[str] = []
    metadatas: list[dict] = []
    total = 0

    def flush():
        nonlocal total
        if not ids:
            return
        n = pg.insert_with_embeddings(collection, texts, embeddings, ids=ids, metadata=metadatas)
        total += n
        ids.clear(); embeddings.clear(); texts.clear(); metadatas.clear()

    for row in iter_milvus_rows(client, collection):
        ids.append(str(row["id"]))
        embeddings.append(list(row["vector"]))
        texts.append(row.get("text", "") or "")
        try:
            metadatas.append(json.loads(row.get("metadata_json") or "{}"))
        except Exception:
            metadatas.append({})
        if len(ids) >= BATCH_SIZE:
            flush()
    flush()

    final_count = int(pg.get_collection_stats(collection).get("num_entities", 0))
    status = "OK" if final_count == milvus_count else "MISMATCH"
    print(f"    -> inserted {total} rows; pgvector now has {final_count}/{milvus_count} [{status}]")
    return (milvus_count, final_count, True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report what would migrate, don't write")
    parser.add_argument("--collection", action="append", help="Restrict to specific collection(s); repeatable")
    args = parser.parse_args()

    from resource_explorer.vector_store_pg import PgVectorStore

    collections = args.collection or registered_collections()
    print(f"Migrating {len(collections)} collection(s){' (dry run)' if args.dry_run else ''}:")

    client = get_milvus_client()
    pg = PgVectorStore()
    pg.connect()

    mismatches = []
    grand_milvus = grand_pg = 0
    for collection in collections:
        milvus_n, pg_n, _ = migrate_collection(client, pg, collection, args.dry_run)
        grand_milvus += milvus_n
        grand_pg += pg_n
        if not args.dry_run and milvus_n and pg_n != milvus_n:
            mismatches.append(collection)

    print(f"\nTotals: {grand_pg}/{grand_milvus} rows across {len(collections)} collections.")
    if mismatches:
        print(f"MISMATCHES in: {', '.join(mismatches)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
