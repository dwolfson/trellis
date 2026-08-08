"""DEPRECATED — code_symbols/code_relationships are no longer read by
anything (AST-ownership-transfer plan Phase 8; CodeIntelAgent/analytics.py/
rag_retrieval.py all migrated to Resource Explorer's equivalent tables in
Phases 6-7). Running this script still works (code_symbol_store.py's write
path is intentionally kept functional as a rollback safety net) but writes
to tables nothing consumes anymore — kept for that rollback scenario, not
for routine use.

Backfill the code_symbols table from already-ingested collections.

Run this once after upgrading to populate the symbol table for existing collections
without a full re-ingest into pgvector.  Handles both Python (AST) and Java
(tree-sitter) collections.

Usage:
    python scripts/backfill_code_symbols.py
    python scripts/backfill_code_symbols.py --collection pyegeria
    python scripts/backfill_code_symbols.py --collection egeria_java
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from advisor.code_symbol_store import get_symbol_store
from advisor.collection_config import get_enabled_collections, get_collection
from advisor.config import settings

_SKIP_DIRS = {"__pycache__", "deprecated", ".git", ".venv", "node_modules", "target", "build"}

# The advisor repo sits at <project_root>/egeria-advisor; the Java repo at <project_root>/egeria
_ADVISOR_ROOT = Path(__file__).parent.parent.resolve()
_PROJECT_ROOT = _ADVISOR_ROOT.parent

# Resolved source roots for known collections
_COLLECTION_SOURCE: dict[str, Path] = {
    "pyegeria":     Path(settings.advisor_data_path),
    "pyegeria_cli": Path(settings.advisor_data_path),
    "pyegeria_drE": Path(settings.advisor_data_path),
    "egeria_java":  _PROJECT_ROOT / "egeria",
}


def _source_root(collection_name: str) -> Path | None:
    """Find the source root for a collection."""
    candidate = _COLLECTION_SOURCE.get(collection_name)
    if candidate and candidate.exists():
        return candidate

    # Fall back to collection config source_paths
    meta = get_collection(collection_name)
    if not meta:
        return None
    for rel in (meta.source_paths or []):
        p = Path(settings.advisor_data_path) / rel
        if p.exists():
            return p
    return None


def _should_skip(path: Path) -> bool:
    return any(p in _SKIP_DIRS for p in path.parts)


def backfill_python(collection_name: str, root: Path) -> int:
    from advisor.data_prep.code_parser import CodeParser
    store = get_symbol_store()
    store.clear_collection(collection_name)
    parser = CodeParser()
    all_elements = []
    for py_file in root.rglob("*.py"):
        if _should_skip(py_file):
            continue
        all_elements.extend(parser.parse_file(py_file))
    count = store.upsert_symbols(collection_name, all_elements, language="python")
    logger.info(f"  → {count} symbols written for '{collection_name}'")
    return count


def backfill_java(collection_name: str, root: Path) -> int:
    from advisor.data_prep.java_symbol_extractor import JavaSymbolExtractor
    store = get_symbol_store()
    store.clear_collection(collection_name)
    extractor = JavaSymbolExtractor()
    all_symbols: list = []
    java_files = list(root.rglob("*.java"))
    logger.info(f"  Found {len(java_files)} Java files in {root}")
    for i, java_file in enumerate(java_files, 1):
        if _should_skip(java_file):
            continue
        all_symbols.extend(extractor.extract_file(java_file))
        if i % 500 == 0:
            logger.info(f"  Progress: {i}/{len(java_files)} files, {len(all_symbols)} symbols so far")
    count = store.upsert_symbols(collection_name, all_symbols, language="java")
    logger.info(f"  → {count} symbols written for '{collection_name}'")
    return count


def backfill(collection_name: str) -> int:
    root = _source_root(collection_name)
    if root is None:
        logger.warning(f"No source root found for '{collection_name}' — skipping")
        return 0

    meta = get_collection(collection_name)
    language = meta.language.value if meta else "python"

    logger.info(f"Backfilling '{collection_name}' ({language}) from {root}")

    if language == "java":
        return backfill_java(collection_name, root)
    else:
        return backfill_python(collection_name, root)


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill code_symbols table from source repos")
    ap.add_argument("--collection", default=None,
                    help="Single collection name (default: all Python + Java)")
    args = ap.parse_args()

    if args.collection:
        targets = [args.collection]
    else:
        all_cols = get_enabled_collections()
        targets = [c.name for c in all_cols
                   if c.language.value in ("python", "java")]

    total = 0
    for col in targets:
        total += backfill(col)

    logger.info(f"Done. {total} total symbols across {len(targets)} collection(s).")
    summary = get_symbol_store().collection_summary()
    for col, data in sorted(summary.items()):
        print(
            f"  {col}: {data.get('classes', 0):4d} classes · "
            f"{data.get('methods', 0):5d} methods · "
            f"{data.get('functions', 0):5d} functions"
        )


if __name__ == "__main__":
    main()
