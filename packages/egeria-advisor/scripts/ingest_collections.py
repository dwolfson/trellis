#!/usr/bin/env python3
"""
Ingest code from git repositories into pgvector collections.

This script processes cloned repositories and ingests code into
appropriate pgvector collections based on collection configuration.
"""

import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import fnmatch

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.collection_config import (
    CollectionMetadata,
    get_collection,
    get_enabled_collections,
    get_phase1_collections,
    get_phase2_collections
)
from advisor.vector_store import get_vector_store
from advisor.embeddings import get_embedding_generator
from advisor.ingest import CodeIngester
from loguru import logger


def get_repos_dir() -> Path:
    """Get the data/repos directory path."""
    script_dir = Path(__file__).parent
    repos_dir = script_dir.parent / "data" / "repos"
    return repos_dir


def get_collection_source_paths(collection: CollectionMetadata) -> List[Path]:
    """
    Get source paths for a collection.
    
    Args:
        collection: Collection metadata
        
    Returns:
        List of absolute paths to source directories
    """
    repos_dir = get_repos_dir()
    
    # Extract repo name from source_repo URL
    # e.g., "https://github.com/odpi/egeria-python.git" -> "egeria-python"
    repo_name = collection.source_repo.split("/")[-1].replace(".git", "")
    repo_path = repos_dir / repo_name
    
    if not repo_path.exists():
        logger.warning(f"Repository not found: {repo_path}")
        return []
    
    # Build full paths
    source_paths = []
    for rel_path in collection.source_paths:
        full_path = repo_path / rel_path
        if full_path.exists():
            source_paths.append(full_path)
        else:
            logger.warning(f"Source path not found: {full_path}")
    
    return source_paths


def get_file_patterns(collection: CollectionMetadata) -> List[str]:
    """
    Get file patterns for a collection based on language.
    
    Args:
        collection: Collection metadata
        
    Returns:
        List of file patterns (e.g., ["*.py", "*.md"])
    """
    from advisor.collection_config import Language
    
    patterns = {
        Language.PYTHON: ["*.py"],
        Language.JAVA: ["*.java"],
        Language.MARKDOWN: ["*.md"],
        Language.MIXED: ["*.py", "*.java", "*.md", "*.yaml", "*.yml", "*.json"]
    }
    
    return patterns.get(collection.language, ["*.py", "*.md"])


def count_files(paths: List[Path], patterns: List[str]) -> int:
    """
    Count files matching patterns in paths.
    
    Args:
        paths: List of directory paths
        patterns: List of file patterns
        
    Returns:
        Total file count
    """
    count = 0
    for path in paths:
        if path.is_file():
            for pattern in patterns:
                if fnmatch.fnmatch(path.name, pattern):
                    count += 1
                    break
        elif path.is_dir():
            for pattern in patterns:
                try:
                    count += len(list(path.rglob(pattern)))
                except (PermissionError, OSError) as e:
                    logger.warning(f"Skipping inaccessible path {path}: {e}")
                    continue
    return count


def ingest_collection(
    collection: CollectionMetadata,
    force: bool = False,
    dry_run: bool = False
) -> Tuple[int, int]:
    """
    Ingest a single collection.
    
    Args:
        collection: Collection metadata
        force: Force re-ingestion even if collection exists
        dry_run: Don't actually ingest, just show what would be done
        
    Returns:
        Tuple of (files_processed, chunks_created)
    """
    logger.info("=" * 60)
    logger.info(f"Ingesting Collection: {collection.name}")
    logger.info("=" * 60)
    
    # Get source paths
    source_paths = get_collection_source_paths(collection)
    if not source_paths:
        logger.error(f"No valid source paths found for {collection.name}")
        return 0, 0
    
    # Get file patterns
    patterns = get_file_patterns(collection)
    
    # Count files
    file_count = count_files(source_paths, patterns)
    logger.info(f"Source paths: {len(source_paths)}")
    logger.info(f"File patterns: {patterns}")
    logger.info(f"Estimated files: {file_count}")
    
    if dry_run:
        logger.info("DRY RUN - No ingestion performed")
        return 0, 0
    
    # Check if collection exists
    vector_store = get_vector_store()
    vector_store.connect()  # Ensure connected
    
    if collection.name in vector_store.list_collections():
        if not force:
            logger.warning(f"Collection {collection.name} already exists. Use --force to re-ingest.")
            return 0, 0
        else:
            logger.info(f"Dropping existing collection: {collection.name}")
            vector_store.delete_collection(collection.name)
    
    # Create collection
    logger.info(f"Creating collection: {collection.name}")
    vector_store.create_collection(
        collection_name=collection.name,
        description=collection.description,
        drop_if_exists=False
    )

    # Clear the code-symbol table once per collection, before the source-path loop
    # below. ingest_directory() no longer clears it per-call — collections like
    # 'pyegeria' have multiple source directories, and clearing per-call wiped out
    # each earlier directory's symbols as soon as the next one was ingested.
    try:
        from advisor.code_symbol_store import get_symbol_store
        get_symbol_store().clear_collection(collection.name)
    except Exception as exc:
        logger.warning(f"CodeSymbolStore clear failed: {exc}")

    # Create ingester
    ingester = CodeIngester(
        collection_name=collection.name,
        chunk_size=1000,
        chunk_overlap=200
    )
    
    # Ingest each source path
    total_files = 0
    total_chunks = 0
    
    for source_path in source_paths:
        logger.info(f"Processing: {source_path}")
        
        if source_path.is_file():
            # Single file
            files, chunks = ingester.ingest_file(source_path)
            total_files += files
            total_chunks += chunks
        else:
            # Directory
            for pattern in patterns:
                files, chunks = ingester.ingest_directory(
                    source_path,
                    file_pattern=pattern,
                    recursive=True
                )
                total_files += files
                total_chunks += chunks
    
    # Create index after ingestion
    if total_chunks > 0:
        logger.info(f"Creating index for {collection.name}...")
        vector_store.create_index(
            collection_name=collection.name,
            index_type="IVF_FLAT",
            metric_type="L2"
        )
    
    logger.info(f"✓ Ingested {total_files} files, {total_chunks} chunks into {collection.name}")

    # Record completion time so the admin page can show "last indexed"
    if total_chunks > 0 and not dry_run:
        try:
            from advisor.web.admin import record_ingest_time
            record_ingest_time(collection.name, files=total_files, chunks=total_chunks, source="ingest_script")
        except Exception:
            pass

    return total_files, total_chunks


def ingest_phase1(force: bool = False, dry_run: bool = False) -> Dict[str, Tuple[int, int]]:
    """
    Ingest Phase 1 (Python) collections.
    
    Args:
        force: Force re-ingestion
        dry_run: Don't actually ingest
        
    Returns:
        Dict mapping collection name to (files, chunks) tuple
    """
    logger.info("=" * 60)
    logger.info("Ingesting Phase 1 Collections (Python)")
    logger.info("=" * 60)
    
    results = {}
    collections = get_phase1_collections()
    
    for collection in collections:
        files, chunks = ingest_collection(collection, force=force, dry_run=dry_run)
        results[collection.name] = (files, chunks)
    
    return results


def ingest_phase2(force: bool = False, dry_run: bool = False) -> Dict[str, Tuple[int, int]]:
    """
    Ingest Phase 2 (Java/Docs/Workspaces) collections.
    
    Args:
        force: Force re-ingestion
        dry_run: Don't actually ingest
        
    Returns:
        Dict mapping collection name to (files, chunks) tuple
    """
    logger.info("=" * 60)
    logger.info("Ingesting Phase 2 Collections (Java/Docs/Workspaces)")
    logger.info("=" * 60)
    
    results = {}
    collections = get_phase2_collections()
    
    for collection in collections:
        files, chunks = ingest_collection(collection, force=force, dry_run=dry_run)
        results[collection.name] = (files, chunks)
    
    return results


def ingest_all(force: bool = False, dry_run: bool = False) -> Dict[str, Tuple[int, int]]:
    """
    Ingest all enabled collections.
    
    Args:
        force: Force re-ingestion
        dry_run: Don't actually ingest
        
    Returns:
        Dict mapping collection name to (files, chunks) tuple
    """
    logger.info("=" * 60)
    logger.info("Ingesting All Enabled Collections")
    logger.info("=" * 60)
    
    results = {}
    collections = get_enabled_collections()
    
    for collection in collections:
        files, chunks = ingest_collection(collection, force=force, dry_run=dry_run)
        results[collection.name] = (files, chunks)
    
    return results


def show_ingestion_summary(results: Dict[str, Tuple[int, int]]):
    """
    Show ingestion summary.
    
    Args:
        results: Dict mapping collection name to (files, chunks) tuple
    """
    logger.info("\n" + "=" * 60)
    logger.info("Ingestion Summary")
    logger.info("=" * 60)
    
    total_files = 0
    total_chunks = 0
    
    for collection_name, (files, chunks) in results.items():
        logger.info(f"{collection_name}:")
        logger.info(f"  Files: {files}")
        logger.info(f"  Chunks: {chunks}")
        total_files += files
        total_chunks += chunks
    
    logger.info("-" * 60)
    logger.info(f"Total Files: {total_files}")
    logger.info(f"Total Chunks: {total_chunks}")


def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Ingest code into pgvector collections")
    parser.add_argument(
        "--phase",
        choices=["1", "2", "all"],
        default="1",
        help="Which phase to ingest (default: 1)"
    )
    parser.add_argument(
        "--collection",
        help="Ingest specific collection only"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-ingestion (drop existing collection)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be ingested without actually doing it"
    )
    
    args = parser.parse_args()
    
    # Ingest collections
    if args.collection:
        # Single collection
        collection = get_collection(args.collection)
        if not collection:
            logger.error(f"Collection not found: {args.collection}")
            sys.exit(1)
        
        files, chunks = ingest_collection(
            collection,
            force=args.force,
            dry_run=args.dry_run
        )
        results = {collection.name: (files, chunks)}
    elif args.phase == "1":
        results = ingest_phase1(force=args.force, dry_run=args.dry_run)
    elif args.phase == "2":
        results = ingest_phase2(force=args.force, dry_run=args.dry_run)
    else:
        results = ingest_all(force=args.force, dry_run=args.dry_run)
    
    # Show summary
    show_ingestion_summary(results)
    
    # Check for failures
    if any(files == 0 for files, chunks in results.values()):
        logger.warning("Some collections had no files ingested")
        sys.exit(1)


if __name__ == "__main__":
    main()