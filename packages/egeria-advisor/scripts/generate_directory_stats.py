#!/usr/bin/env python3
"""
Generate per-directory statistics for scoped queries.

This script analyzes code elements and generates statistics grouped by
top-level directory, enabling queries like "How many classes in pyegeria?"
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, Set

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger


def generate_directory_stats(
    code_elements_file: Path,
    output_file: Path
) -> Dict[str, Any]:
    """
    Generate statistics grouped by directory.
    
    Args:
        code_elements_file: Path to code_elements.json
        output_file: Path to save directory_stats.json
        
    Returns:
        Dictionary of directory statistics
    """
    logger.info(f"Loading code elements from {code_elements_file}")
    
    if not code_elements_file.exists():
        logger.error(f"Code elements file not found: {code_elements_file}")
        return {}
    
    with open(code_elements_file, 'r') as f:
        elements = json.load(f)
    
    logger.info(f"Loaded {len(elements)} code elements")
    
    # Group by directory
    dir_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        'classes': 0,
        'functions': 0,
        'methods': 0,
        'files': set(),
        'total_elements': 0,
        'public_elements': 0,
        'with_docstrings': 0,
        'total_lines': 0
    })
    
    # Also track repo-wide stats for validation
    repo_stats = {
        'classes': 0,
        'functions': 0,
        'methods': 0,
        'files': set(),
        'total_elements': 0
    }
    
    for element in elements:
        file_path = element.get('file_path', '')
        element_type = element.get('type', '')
        is_public = not element.get('is_private', True)
        has_docstring = bool(element.get('docstring'))
        lines = element.get('end_line_number', 0) - element.get('line_number', 0) + 1
        
        # Convert absolute path to relative if it contains any of our known repos
        for repo in ['egeria-python', 'egeria', 'egeria-docs', 'egeria-workspaces']:
            if f'{repo}/' in file_path:
                file_path = file_path.split(f'{repo}/', 1)[1]
                break
        
        # Get top-level directory (first path component)
        # If the file is at the root of a repo, the parts will be just the filename
        parts = [p for p in file_path.split('/') if p]
        if not parts:
            continue
            
        directory = parts[0]
        
        # Update directory stats
        dir_stats[directory]['total_elements'] += 1
        dir_stats[directory]['files'].add(file_path)
        dir_stats[directory]['total_lines'] += lines
        
        if is_public:
            dir_stats[directory]['public_elements'] += 1
        if has_docstring:
            dir_stats[directory]['with_docstrings'] += 1
        
        if element_type == 'class':
            dir_stats[directory]['classes'] += 1
        elif element_type == 'function':
            dir_stats[directory]['functions'] += 1
        elif element_type == 'method':
            dir_stats[directory]['methods'] += 1
        
        # Update repo stats for validation
        repo_stats['total_elements'] += 1
        repo_stats['files'].add(file_path)
        if element_type == 'class':
            repo_stats['classes'] += 1
        elif element_type == 'function':
            repo_stats['functions'] += 1
        elif element_type == 'method':
            repo_stats['methods'] += 1
    
    # Convert sets to counts and calculate percentages
    result = {}
    for directory, stats in dir_stats.items():
        file_count = len(stats['files'])
        total = stats['total_elements']
        
        result[directory] = {
            'classes': stats['classes'],
            'functions': stats['functions'],
            'methods': stats['methods'],
            'files': file_count,
            'total_elements': total,
            'public_elements': stats['public_elements'],
            'with_docstrings': stats['with_docstrings'],
            'total_lines': stats['total_lines'],
            'public_percentage': round(stats['public_elements'] / total * 100, 1) if total > 0 else 0,
            'docstring_percentage': round(stats['with_docstrings'] / total * 100, 1) if total > 0 else 0,
            'avg_lines_per_element': round(stats['total_lines'] / total, 1) if total > 0 else 0
        }
    
    # Add repo-wide totals for reference
    result['_total'] = {
        'classes': repo_stats['classes'],
        'functions': repo_stats['functions'],
        'methods': repo_stats['methods'],
        'files': len(repo_stats['files']),
        'total_elements': repo_stats['total_elements'],
        'directories': len(result) - 1  # Exclude _total itself
    }
    
    # Save results
    logger.info(f"Saving directory statistics to {output_file}")
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    # Print summary
    print("\n" + "="*80)
    print("DIRECTORY STATISTICS GENERATED")
    print("="*80)
    print(f"\nTotal directories analyzed: {len(result) - 1}")
    print(f"Total code elements: {repo_stats['total_elements']:,}")
    print(f"Total files: {len(repo_stats['files']):,}")
    print(f"\nTop directories by element count:")
    
    # Sort directories by element count
    sorted_dirs = sorted(
        [(d, s['total_elements']) for d, s in result.items() if d != '_total'],
        key=lambda x: x[1],
        reverse=True
    )
    
    for i, (directory, count) in enumerate(sorted_dirs[:10], 1):
        stats = result[directory]
        print(f"  {i:2d}. {directory:20s} - {count:5,} elements "
              f"({stats['classes']:3d} classes, {stats['functions']:3d} functions, "
              f"{stats['methods']:3d} methods)")
    
    print("\n" + "="*80)
    print(f"Statistics saved to: {output_file}")
    print("="*80 + "\n")
    
    return result


def validate_statistics(
    directory_stats: Dict[str, Any],
    pipeline_summary_file: Path
) -> bool:
    """
    Validate generated statistics against pipeline summary.
    
    Args:
        directory_stats: Generated directory statistics
        pipeline_summary_file: Path to pipeline_summary.json
        
    Returns:
        True if validation passes
    """
    if not pipeline_summary_file.exists():
        logger.warning(f"Pipeline summary not found: {pipeline_summary_file}")
        return False
    
    with open(pipeline_summary_file, 'r') as f:
        summary = json.load(f)
    
    pipeline_stats = summary.get('statistics', {}).get('code', {})
    
    # Compare totals
    dir_total = directory_stats.get('_total', {})
    pipeline_total = pipeline_stats.get('total', 0)
    
    if dir_total.get('total_elements') != pipeline_total:
        logger.warning(
            f"Total mismatch: directory={dir_total.get('total_elements')}, "
            f"pipeline={pipeline_total}"
        )
        return False
    
    # Compare by type
    dir_classes = dir_total.get('classes', 0)
    pipeline_classes = pipeline_stats.get('by_type', {}).get('class', 0)
    
    if dir_classes != pipeline_classes:
        logger.warning(
            f"Class count mismatch: directory={dir_classes}, "
            f"pipeline={pipeline_classes}"
        )
        return False
    
    logger.info("✓ Statistics validation passed")
    return True


def main():
    """Main entry point."""
    # Determine cache directory
    cache_dir = Path(__file__).parent.parent / "data" / "cache"
    
    if not cache_dir.exists():
        logger.error(f"Cache directory not found: {cache_dir}")
        logger.info("Please run the data preparation pipeline first")
        return 1
    
    code_elements_file = cache_dir / "code_elements.json"
    output_file = cache_dir / "directory_stats.json"
    pipeline_summary_file = cache_dir / "pipeline_summary.json"
    
    # Generate statistics
    directory_stats = generate_directory_stats(code_elements_file, output_file)
    
    if not directory_stats:
        logger.error("Failed to generate directory statistics")
        return 1
    
    # Validate against pipeline summary
    if validate_statistics(directory_stats, pipeline_summary_file):
        logger.info("✓ Directory statistics generated and validated successfully")
        return 0
    else:
        logger.warning("⚠ Statistics generated but validation failed")
        return 0  # Still return success since stats were generated


if __name__ == "__main__":
    sys.exit(main())