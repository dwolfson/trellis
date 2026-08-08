#!/usr/bin/env python3
"""
Index extracted hey_egeria CLI command metadata into pgvector.

Reads cache/cli_commands.json (produced by scripts/test_cli_parser.py) and
indexes it into the pyegeria_cli collection additively — alongside, not
replacing, the generic AST code chunks written by the main ingestion
pipeline (scripts/ingest_collections.py). This is what CLICommandAgent's
structured hey_egeria answers are grounded in; without it, CLICommandAgent
has no real command syntax to draw from. Run as step 4/4 of
scripts/full_reset.sh, after the main collection re-ingest (which must run
first — it drops and recreates the table).
"""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.data_prep.cli_indexer import index_cli_commands_from_file
from loguru import logger

def main():
    """Index CLI commands from the cached extraction into pgvector."""

    # Path to CLI commands JSON file
    commands_file = Path("cache/cli_commands.json")

    if not commands_file.exists():
        logger.error(f"CLI commands file not found at {commands_file}")
        logger.info("Please run scripts/test_cli_parser.py first to extract commands")
        return 1

    logger.info(f"Indexing CLI commands from: {commands_file}")
    logger.info("="*60)
    
    # Index commands
    try:
        stats = index_cli_commands_from_file(
            commands_file=commands_file,
            collection_name="cli_commands"
        )
        
        logger.info("\n" + "="*60)
        logger.info("Indexing Statistics:")
        logger.info("="*60)
        for key, value in stats.items():
            logger.info(f"  {key}: {value}")
        
        logger.info("\n" + "="*60)
        logger.info("Indexing complete!")
        logger.info("="*60)
        
        return 0
        
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())