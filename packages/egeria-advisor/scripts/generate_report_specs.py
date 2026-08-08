#!/usr/bin/env python3
"""
SPDX-License-Identifier: Apache-2.0
Copyright Contributors to the Egeria project.

Generate report_spec metadata from egeria-python for RAG system.

This script extracts information about all available report_specs (output format sets)
from the egeria-python library and creates a structured JSON file that can be used
by the RAG system to answer queries about available report formats.

Report specs define how data is formatted and displayed in egeria-python, including:
- What columns/attributes are included
- What output formats are supported (DICT, TABLE, JSON, MD, etc.)
- What actions/functions can be called
- Aliases and descriptions

Usage:
    python scripts/generate_report_specs.py

Output:
    data/cache/report_specs.json - Complete report spec metadata
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any
from loguru import logger

# Add egeria-python to path
EGERIA_PYTHON_PATH = Path(__file__).parent.parent.parent.parent / "egeria-python"
sys.path.insert(0, str(EGERIA_PYTHON_PATH))

try:
    from pyegeria.base_report_formats import report_specs
    from pyegeria._output_format_models import FormatSet
except ImportError as e:
    logger.error(f"Failed to import pyegeria modules: {e}")
    logger.error(f"Make sure egeria-python is available at: {EGERIA_PYTHON_PATH}")
    sys.exit(1)


def extract_column_info(format_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract column/attribute information from a format object."""
    columns = []
    
    # Try both 'attributes' (new) and 'columns' (legacy)
    attrs = format_obj.get('attributes') or format_obj.get('columns', [])
    
    for attr in attrs:
        if isinstance(attr, dict):
            columns.append({
                'name': attr.get('name', ''),
                'key': attr.get('key', ''),
                'format': attr.get('format', False)
            })
    
    return columns


def extract_action_info(action: Any) -> Dict[str, Any]:
    """Extract action information."""
    if action is None:
        return None
    
    if isinstance(action, dict):
        return {
            'function': action.get('function', ''),
            'required_params': action.get('required_params', action.get('user_params', [])),
            'optional_params': action.get('optional_params', []),
            'spec_params': action.get('spec_params', {})
        }
    
    return None


def extract_report_spec_metadata(name: str, format_set: FormatSet) -> Dict[str, Any]:
    """Extract metadata from a single report spec."""
    
    # Convert to dict for easier access
    fs_dict = format_set.dict() if hasattr(format_set, 'dict') else format_set
    
    # Extract format information
    formats_info = []
    for fmt in fs_dict.get('formats', []):
        format_info = {
            'types': fmt.get('types', []),
            'columns': extract_column_info(fmt)
        }
        formats_info.append(format_info)
    
    # Build metadata
    metadata = {
        'name': name,
        'heading': fs_dict.get('heading', ''),
        'description': fs_dict.get('description', ''),
        'target_type': fs_dict.get('target_type') or fs_dict.get('entity_type'),
        'family': fs_dict.get('family'),
        'aliases': fs_dict.get('aliases', []),
        'annotations': fs_dict.get('annotations', {}),
        'formats': formats_info,
        'action': extract_action_info(fs_dict.get('action')),
        'get_additional_props': extract_action_info(fs_dict.get('get_additional_props'))
    }
    
    # Add searchable text for RAG
    searchable_parts = [
        name,
        metadata['heading'],
        metadata['description'],
    ]
    
    if metadata['target_type']:
        searchable_parts.append(metadata['target_type'])
    
    if metadata['family']:
        searchable_parts.append(metadata['family'])
    
    searchable_parts.extend(metadata['aliases'])
    
    # Add column names
    for fmt in formats_info:
        for col in fmt['columns']:
            searchable_parts.append(col['name'])
            searchable_parts.append(col['key'])
    
    # Add output types
    for fmt in formats_info:
        searchable_parts.extend(fmt['types'])
    
    metadata['searchable_text'] = ' '.join(filter(None, searchable_parts))
    
    return metadata


def generate_report_specs_data() -> Dict[str, Any]:
    """Generate complete report specs metadata."""
    
    logger.info("Extracting report spec metadata from egeria-python...")
    
    specs_data = {
        'total_specs': 0,
        'families': {},
        'target_types': {},
        'output_types': set(),
        'specs': []
    }
    
    # Process each report spec
    for name, format_set in report_specs.items():
        try:
            metadata = extract_report_spec_metadata(name, format_set)
            specs_data['specs'].append(metadata)
            
            # Track families
            family = metadata.get('family')
            if family:
                if family not in specs_data['families']:
                    specs_data['families'][family] = []
                specs_data['families'][family].append(name)
            
            # Track target types
            target_type = metadata.get('target_type')
            if target_type:
                if target_type not in specs_data['target_types']:
                    specs_data['target_types'][target_type] = []
                specs_data['target_types'][target_type].append(name)
            
            # Track output types
            for fmt in metadata['formats']:
                specs_data['output_types'].update(fmt['types'])
            
        except Exception as e:
            logger.warning(f"Failed to extract metadata for {name}: {e}")
            continue
    
    specs_data['total_specs'] = len(specs_data['specs'])
    specs_data['output_types'] = sorted(list(specs_data['output_types']))
    
    logger.info(f"Extracted {specs_data['total_specs']} report specs")
    logger.info(f"Found {len(specs_data['families'])} families")
    logger.info(f"Found {len(specs_data['target_types'])} target types")
    logger.info(f"Found {len(specs_data['output_types'])} output types")
    
    return specs_data


def main():
    """Main execution function."""
    
    # Setup paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    cache_dir = project_dir / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = cache_dir / "report_specs.json"
    
    logger.info("=" * 60)
    logger.info("Report Spec Metadata Extraction")
    logger.info("=" * 60)
    logger.info(f"Egeria Python Path: {EGERIA_PYTHON_PATH}")
    logger.info(f"Output File: {output_file}")
    logger.info("")
    
    try:
        # Generate metadata
        specs_data = generate_report_specs_data()
        
        # Save to file
        logger.info(f"Saving report spec metadata to {output_file}...")
        with open(output_file, 'w') as f:
            json.dump(specs_data, f, indent=2)
        
        logger.success(f"✓ Report spec metadata saved successfully")
        logger.info("")
        logger.info("Summary:")
        logger.info(f"  Total Specs: {specs_data['total_specs']}")
        logger.info(f"  Families: {len(specs_data['families'])}")
        logger.info(f"  Target Types: {len(specs_data['target_types'])}")
        logger.info(f"  Output Types: {', '.join(specs_data['output_types'])}")
        logger.info("")
        
        # Show sample families
        if specs_data['families']:
            logger.info("Sample Families:")
            for family, specs in list(specs_data['families'].items())[:5]:
                logger.info(f"  {family}: {len(specs)} specs")
        
        logger.info("")
        logger.info("=" * 60)
        logger.success("Report Spec Extraction Complete!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Failed to generate report spec metadata: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()