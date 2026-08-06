#!/usr/bin/env python3
"""
Diagnose retrieval issues - check if data is in pgvector and if search works.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table

console = Console()


def check_vector_store_connection():
    """Check if pgvector is accessible."""
    console.print("\n[bold cyan]1. Checking pgvector Connection...[/bold cyan]")
    try:
        from advisor.vector_store import get_vector_store
        store = get_vector_store()
        store.connect()
        console.print(f"  [green]✓[/green] Connected to pgvector ({store.host}:{store.port}/{store.dbname})")
        return store
    except Exception as e:
        console.print(f"  [red]✗[/red] Failed to connect: {e}")
        return None


def check_collections(store):
    """Check what collection tables exist."""
    console.print("\n[bold cyan]2. Checking Collections...[/bold cyan]")
    from advisor.collection_config import get_enabled_collections

    existing = []
    conn = store._get_conn()
    try:
        with conn.cursor() as cur:
            for coll_meta in get_enabled_collections():
                table = store._table(coll_meta.name)
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
                    (table,),
                )
                if cur.fetchone()[0]:
                    existing.append(coll_meta.name)
    except Exception as e:
        console.print(f"  [red]✗[/red] Error: {e}")
        return []
    finally:
        store._put_conn(conn)

    console.print(f"  Found {len(existing)} collections:")
    for coll in existing:
        console.print(f"    • {coll}")
    return existing


def check_collection_data(store, collection_name: str):
    """Check if a collection has data."""
    console.print(f"\n[bold cyan]3. Checking '{collection_name}' Collection...[/bold cyan]")
    try:
        table = store._table(collection_name)
        conn = store._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f'SELECT count(*) FROM "{table}"')
                num_entities = cur.fetchone()[0]
        finally:
            store._put_conn(conn)

        console.print(f"  Total entities: [cyan]{num_entities}[/cyan]")

        if num_entities == 0:
            console.print("  [yellow]⚠[/yellow] Collection is empty!")
            return False
        return True

    except Exception as e:
        console.print(f"  [red]✗[/red] Error: {e}")
        return False


def test_vector_search(collection_name: str = "pyegeria"):
    """Test actual vector search with embeddings."""
    console.print("\n[bold cyan]4. Testing Vector Search with Real Embeddings...[/bold cyan]")
    try:
        from advisor.embeddings import get_embedding_generator
        from advisor.vector_store import get_vector_store

        # Generate embedding for "glossary"
        emb_gen = get_embedding_generator()
        query_embedding = emb_gen.generate_embedding("glossary")
        console.print(f"  Generated embedding: {len(query_embedding)} dimensions")

        # Search
        vs = get_vector_store()
        results = vs.search(
            collection_name=collection_name,
            query_embedding=query_embedding,
            top_k=5
        )

        console.print(f"\n  Search results for 'glossary' in '{collection_name}':")
        if results:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("#", style="dim")
            table.add_column("Score", justify="right")
            table.add_column("Name")
            table.add_column("File")

            for i, r in enumerate(results, 1):
                table.add_row(
                    str(i),
                    f"{r.score:.3f}",
                    r.metadata.get("name", "Unknown")[:40],
                    r.metadata.get("file_path", "Unknown")[:50]
                )

            console.print(table)
            return True
        else:
            console.print("  [yellow]⚠[/yellow] No results found!")
            return False

    except Exception as e:
        console.print(f"  [red]✗[/red] Error: {e}")
        import traceback
        console.print(traceback.format_exc())
        return False


def main():
    """Run all diagnostics."""
    console.print("\n" + "=" * 60)
    console.print("[bold cyan]Egeria Advisor - Retrieval Diagnostics[/bold cyan]")
    console.print("=" * 60)

    # Check connection
    store = check_vector_store_connection()
    if store is None:
        console.print("\n[red]✗ Cannot connect to pgvector. Is Postgres running?[/red]")
        console.print("  Check: psql -h localhost -p 5442 -U egeria_advisor -d egeria_advisor -c 'SELECT 1;'")
        return 1

    # Check collections
    collections = check_collections(store)
    if not collections:
        console.print("\n[red]✗ No collections found. Data needs to be ingested.[/red]")
        console.print("  Run: scripts/full_reset.sh  (or) python scripts/ingest_collections.py --phase all --force")
        return 1

    # Check main collection
    if "pyegeria" in collections:
        if not check_collection_data(store, "pyegeria"):
            console.print("\n[yellow]⚠ Collection exists but is empty or has issues.[/yellow]")
    else:
        console.print("\n[yellow]⚠ 'pyegeria' collection not found.[/yellow]")
        console.print("  Available collections:", collections)

    # Test actual search
    if not test_vector_search():
        console.print("\n[red]✗ Vector search is not working properly.[/red]")
        return 1

    # Summary
    console.print("\n" + "=" * 60)
    console.print("[bold green]✓ Diagnostics Complete[/bold green]")
    console.print("=" * 60)
    console.print("\nIf search is working but queries fail, the issue is likely:")
    console.print("  1. Retrieval threshold too high (min_score in config)")
    console.print("  2. Query embedding mismatch")
    console.print("  3. Metadata filtering issues")

    return 0


if __name__ == "__main__":
    sys.exit(main())
