#!/usr/bin/env python3
"""
Parse PyEgeria source code and index it with structured metadata.

Uses the existing AST-based code parser to extract classes, methods, and functions
with full metadata, then indexes them into the pyegeria collection with scalar fields
for fast metadata filtering.
"""

import sys
from pathlib import Path
from loguru import logger
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.data_prep.code_parser import CodeParser, CodeElement
from advisor.vector_store import VectorStoreManager
from advisor.config import settings


def find_pyegeria_repo() -> Path:
    """Find the PyEgeria repository path."""
    # Check common locations
    possible_paths = [
        Path("data/repos/egeria-python"),
        Path("../egeria-python"),
        Path.home() / "localGit" / "egeria-python",
    ]
    
    for path in possible_paths:
        if path.exists() and (path / "pyegeria").exists():
            logger.info(f"Found PyEgeria repository at {path}")
            return path
    
    logger.error("Could not find PyEgeria repository")
    logger.error("Checked locations:")
    for path in possible_paths:
        logger.error(f"  - {path}")
    raise FileNotFoundError("PyEgeria repository not found")


def prepare_metadata_for_indexing(element: CodeElement) -> Dict[str, Any]:
    """
    Prepare metadata from CodeElement for indexing with scalar fields.
    
    Returns metadata dict with both scalar fields and full metadata.
    """
    # Determine element_type for the vector store schema
    element_type = element.type  # 'class', 'method', 'function'
    
    # Extract module path from file path
    file_path = Path(element.file_path)
    try:
        # Get relative path from pyegeria package
        if 'pyegeria' in file_path.parts:
            idx = file_path.parts.index('pyegeria')
            module_parts = file_path.parts[idx:-1]  # Exclude filename
            module_path = '.'.join(module_parts)
        else:
            module_path = str(file_path.parent).replace('/', '.')
    except:
        module_path = ""
    
    # Prepare metadata with scalar fields
    metadata = {
        # Scalar fields for filtering
        "element_type": element_type,
        "class_name": element.parent_class or "",
        "method_name": element.name if element_type in ['method', 'function'] else "",
        "module_path": module_path,
        "is_async": element.is_async,
        "is_private": element.is_private,
        
        # Full metadata (stored in JSON field)
        "name": element.name,
        "file_path": element.file_path,
        "line_number": element.line_number,
        "end_line_number": element.end_line_number,
        "signature": element.signature,
        "docstring": element.docstring or "",
        "decorators": element.decorators,
        "parameters": element.parameters,
        "return_type": element.return_type or "",
        "complexity": element.complexity,
        "full_name": element.full_name,
    }
    
    return metadata


def create_text_for_embedding(element: CodeElement) -> str:
    """
    Create text representation for embedding generation.
    
    Combines signature, docstring, and key metadata for semantic search.
    """
    parts = []
    
    # Add element type and name
    if element.parent_class:
        parts.append(f"{element.type}: {element.parent_class}.{element.name}")
    else:
        parts.append(f"{element.type}: {element.name}")
    
    # Add signature
    parts.append(f"Signature: {element.signature}")
    
    # Add docstring if available
    if element.docstring:
        parts.append(f"Documentation: {element.docstring}")
    
    # Add decorators if any
    if element.decorators:
        parts.append(f"Decorators: {', '.join(element.decorators)}")
    
    # Add async/private flags
    flags = []
    if element.is_async:
        flags.append("async")
    if element.is_private:
        flags.append("private")
    if flags:
        parts.append(f"Flags: {', '.join(flags)}")
    
    return "\n".join(parts)


def main():
    """Main execution."""
    logger.info("=" * 80)
    logger.info("PARSING AND INDEXING PYEGERIA SOURCE CODE")
    logger.info("=" * 80)
    
    # Find PyEgeria repository
    try:
        repo_path = find_pyegeria_repo()
    except FileNotFoundError:
        return 1
    
    # Initialize parser
    logger.info("\nInitializing code parser...")
    parser = CodeParser()
    
    # Find all Python files in pyegeria package
    pyegeria_path = repo_path / "pyegeria"
    python_files = list(pyegeria_path.rglob("*.py"))
    logger.info(f"Found {len(python_files)} Python files in {pyegeria_path}")
    
    # Parse all files
    logger.info("\nParsing Python files...")
    all_elements: List[CodeElement] = []
    
    for py_file in python_files:
        # Skip __pycache__ and other unwanted files
        if '__pycache__' in str(py_file) or py_file.name.startswith('.'):
            continue
        
        elements = parser.parse_file(py_file)
        all_elements.extend(elements)
    
    logger.info(f"\n✓ Parsed {len(all_elements)} code elements from {len(parser.parsed_files)} files")
    
    # Show statistics
    element_types = {}
    for elem in all_elements:
        element_types[elem.type] = element_types.get(elem.type, 0) + 1
    
    logger.info("\nElement breakdown:")
    for elem_type, count in sorted(element_types.items()):
        logger.info(f"  {elem_type}: {count}")
    
    # Prepare data for indexing
    logger.info("\nPreparing data for indexing...")
    texts = []
    ids = []
    metadata_list = []
    
    for i, element in enumerate(all_elements):
        # Create unique ID
        elem_id = f"pyegeria_{element.type}_{i}"
        ids.append(elem_id)
        
        # Create text for embedding
        text = create_text_for_embedding(element)
        texts.append(text)
        
        # Prepare metadata
        metadata = prepare_metadata_for_indexing(element)
        metadata_list.append(metadata)
    
    # Initialize vector store
    logger.info("\nInitializing vector store...")
    vs = VectorStoreManager()
    vs.connect()
    
    # Create collection with scalar fields
    collection_name = "pyegeria"
    logger.info(f"\nCreating {collection_name} collection with scalar fields...")
    vs.create_collection(collection_name, drop_if_exists=True)
    vs.create_index(collection_name)
    
    # Insert data
    logger.info(f"\nIndexing {len(texts)} elements...")
    num_inserted = vs.insert_data(
        collection_name=collection_name,
        texts=texts,
        ids=ids,
        metadata=metadata_list,
        batch_size=500
    )
    
    logger.info(f"\n{'=' * 80}")
    logger.info(f"✓ SUCCESS!")
    logger.info(f"{'=' * 80}")
    logger.info(f"Indexed {num_inserted} PyEgeria code elements")
    logger.info(f"Collection: {collection_name}")
    logger.info(f"Scalar fields enabled for fast metadata filtering")
    logger.info(f"\nYou can now:")
    logger.info(f"  1. Enable metadata filtering in PyEgeria Agent")
    logger.info(f"  2. Test queries like 'what methods are in CollectionManager?'")
    logger.info(f"  3. Expect 10-100x performance improvement on filtered queries")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())