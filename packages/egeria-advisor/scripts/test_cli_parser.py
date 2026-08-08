#!/usr/bin/env python3
"""
Test script for CLI command parser.

Tests extraction of hey_egeria and dr_egeria commands from pyegeria repository.
"""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.data_prep.cli_parser import CLICommandExtractor
from loguru import logger

def main():
    """Test CLI command extraction."""
    
    # Path to pyegeria repository
    pyegeria_root = Path("data/repos/egeria-python")
    
    if not pyegeria_root.exists():
        logger.error(f"pyegeria repository not found at {pyegeria_root}")
        logger.info("Please ensure the repository is cloned to data/repos/egeria-python")
        return 1
    
    logger.info(f"Testing CLI parser with pyegeria at: {pyegeria_root}")
    
    # Create extractor
    extractor = CLICommandExtractor(pyegeria_root)
    
    # Extract all commands
    logger.info("Extracting commands...")
    commands = extractor.extract_all_commands()
    
    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info(f"Extraction complete!")
    logger.info(f"{'='*60}\n")
    
    # Generate and print summary
    summary = extractor.generate_command_summary()
    print(summary)
    
    # Save to JSON
    output_file = Path("cache/cli_commands.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump(commands, f, indent=2)
    
    logger.info(f"\nCommands saved to: {output_file}")
    
    # Show some example commands
    logger.info("\n" + "="*60)
    logger.info("Example Commands:")
    logger.info("="*60 + "\n")
    
    # Show a few hey_egeria commands
    hey_egeria_cmds = [cmd for cmd in commands.values() if cmd['type'] == 'hey_egeria']
    if hey_egeria_cmds:
        example = hey_egeria_cmds[0]
        logger.info(f"hey_egeria example: {example['command_name']}")
        logger.info(f"  Category: {example.get('category', 'N/A')}")
        logger.info(f"  Description: {example.get('description', 'N/A')}")
        logger.info(f"  Parameters: {len(example.get('parameters', []))}")
        if example.get('parameters'):
            for param in example['parameters'][:3]:  # Show first 3
                logger.info(f"    - {param.get('name', 'N/A')}: {param.get('help', 'N/A')}")
    
    # Show a few dr_egeria commands
    dr_egeria_cmds = [cmd for cmd in commands.values() if cmd['type'] == 'dr_egeria']
    if dr_egeria_cmds:
        example = dr_egeria_cmds[0]
        logger.info(f"\ndr_egeria example: {example['command_name']}")
        logger.info(f"  Description: {example.get('description', 'N/A')}")
        logger.info(f"  Usage: {example.get('usage', 'N/A')}")
    
    logger.info("\n" + "="*60)
    logger.info("Test complete!")
    logger.info("="*60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())