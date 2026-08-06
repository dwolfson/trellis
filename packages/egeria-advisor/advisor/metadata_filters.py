"""
Metadata Filter Utilities for Vector Store Queries.

Provides helper functions to build filter expressions from
natural language queries and structured filter dictionaries.
"""

import re
from typing import Dict, Any, List, Optional
from loguru import logger


def build_filter_expr(filters: Dict[str, Any]) -> str:
    """
    Build filter expression from dictionary.
    
    Args:
        filters: Dictionary of field->value mappings
        
    Returns:
        filter expression string
        
    Examples:
        >>> build_filter_expr({'class_name': 'ProjectManager'})
        'class_name == "ProjectManager"'
        
        >>> build_filter_expr({'class_name': 'ProjectManager', 'is_async': True})
        'class_name == "ProjectManager" and is_async == True'
    """
    if not filters:
        return ""
    
    conditions = []
    for key, value in filters.items():
        if isinstance(value, str):
            # String equality
            conditions.append(f'{key} == "{value}"')
        elif isinstance(value, bool):
            # Boolean equality
            conditions.append(f'{key} == {value}')
        elif isinstance(value, (int, float)):
            # Numeric equality
            conditions.append(f'{key} == {value}')
        elif isinstance(value, list):
            # IN clause for lists
            if all(isinstance(v, str) for v in value):
                values_str = ', '.join(f'"{v}"' for v in value)
                conditions.append(f'{key} in [{values_str}]')
            else:
                values_str = ', '.join(str(v) for v in value)
                conditions.append(f'{key} in [{values_str}]')
    
    return ' and '.join(conditions)


def extract_pyegeria_filters(query: str) -> Dict[str, Any]:
    """
    Extract metadata filters from PyEgeria query.
    
    Args:
        query: Natural language query
        
    Returns:
        Dictionary of metadata filters
        
    Examples:
        >>> extract_pyegeria_filters("What methods does ProjectManager have?")
        {'class_name': 'ProjectManager', 'element_type': 'method'}
        
        >>> extract_pyegeria_filters("Show me async methods in GlossaryManager")
        {'class_name': 'GlossaryManager', 'element_type': 'method', 'is_async': True}
    """
    filters = {}
    query_lower = query.lower()
    
    # Extract class names (CamelCase words)
    # Common PyEgeria class patterns - ordered from most specific to most general
    class_patterns = [
        r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)*Manager)\b',  # *Manager classes
        r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)*Client)\b',   # *Client classes
        r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)*Handler)\b',  # *Handler classes
        r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)*Service)\b',  # *Service classes
        r'\b(EgeriaClient|EgeriaTech|ServerOps)\b',   # Specific classes
        r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b',         # Any CamelCase word (2+ parts)
    ]
    
    for pattern in class_patterns:
        match = re.search(pattern, query)
        if match:
            filters['class_name'] = match.group(1)
            logger.debug(f"Extracted class_name: {filters['class_name']}")
            break
    
    # Extract element type from query intent
    if any(word in query_lower for word in ['method', 'methods', 'function', 'functions']):
        filters['element_type'] = 'method'
        logger.debug("Detected element_type: method")
    elif any(word in query_lower for word in ['class', 'classes']):
        filters['element_type'] = 'class'
        logger.debug("Detected element_type: class")
    
    # Extract boolean flags
    if 'async' in query_lower:
        filters['is_async'] = True
        logger.debug("Detected is_async: True")
    
    if 'private' in query_lower:
        filters['is_private'] = True
        logger.debug("Detected is_private: True")
    
    # Extract module path
    module_match = re.search(r'pyegeria\.([a-z_]+(?:\.[a-z_]+)*)', query_lower)
    if module_match:
        filters['module_path'] = f"pyegeria.{module_match.group(1)}"
        logger.debug(f"Extracted module_path: {filters['module_path']}")
    
    # Extract method names (snake_case)
    if 'element_type' in filters and filters['element_type'] == 'method':
        method_match = re.search(r'\b([a-z_]+_[a-z_]+)\b', query_lower)
        if method_match:
            filters['method_name'] = method_match.group(1)
            logger.debug(f"Extracted method_name: {filters['method_name']}")
    
    return filters


def extract_cli_filters(query: str) -> Dict[str, Any]:
    """
    Extract metadata filters from CLI command query.
    
    Args:
        query: Natural language query
        
    Returns:
        Dictionary of metadata filters
        
    Examples:
        >>> extract_cli_filters("Show me platform commands")
        {'subcommand': 'platform'}
        
        >>> extract_cli_filters("Which commands require --url?")
        {'required_options': '--url'}
    """
    filters = {}
    query_lower = query.lower()
    
    # Extract main command
    if 'hey_egeria' in query_lower:
        filters['main_command'] = 'hey_egeria'
        logger.debug("Detected main_command: hey_egeria")
    elif 'dr_egeria' in query_lower or 'dr egeria' in query_lower:
        filters['main_command'] = 'dr_egeria'
        logger.debug("Detected main_command: dr_egeria")
    
    # Extract subcommand categories
    subcommand_keywords = {
        'platform': ['platform', 'server', 'status'],
        'glossary': ['glossary', 'term', 'category'],
        'asset': ['asset', 'catalog'],
        'collection': ['collection'],
        'project': ['project'],
        'community': ['community'],
    }
    
    for subcommand, keywords in subcommand_keywords.items():
        if any(keyword in query_lower for keyword in keywords):
            # Use LIKE for partial matching since subcommand might be "platform status"
            filters['subcommand_contains'] = subcommand
            logger.debug(f"Detected subcommand contains: {subcommand}")
            break
    
    # Extract option requirements
    option_match = re.search(r'--([a-z-]+)', query_lower)
    if option_match:
        option = f"--{option_match.group(1)}"
        
        if any(word in query_lower for word in ['require', 'required', 'need', 'needs']):
            filters['required_options_contains'] = option
            logger.debug(f"Detected required option: {option}")
        else:
            filters['options_contains'] = option
            logger.debug(f"Detected option: {option}")
    
    return filters


def build_like_filter(field: str, value: str) -> str:
    """
    Build a LIKE filter expression for partial string matching.
    
    Args:
        field: Field name
        value: Value to match (will be wrapped with %)
        
    Returns:
        LIKE filter expression
        
    Example:
        >>> build_like_filter('options', '--url')
        'options like "%--url%"'
    """
    return f'{field} like "%{value}%"'


def combine_filters(
    exact_filters: Optional[Dict[str, Any]] = None,
    like_filters: Optional[Dict[str, str]] = None
) -> str:
    """
    Combine exact and LIKE filters into single expression.
    
    Args:
        exact_filters: Dictionary of exact match filters
        like_filters: Dictionary of LIKE match filters (field -> value)
        
    Returns:
        Combined filter expression
        
    Example:
        >>> combine_filters(
        ...     exact_filters={'main_command': 'hey_egeria'},
        ...     like_filters={'subcommand': 'platform'}
        ... )
        'main_command == "hey_egeria" and subcommand like "%platform%"'
    """
    conditions = []
    
    # Add exact filters
    if exact_filters:
        exact_expr = build_filter_expr(exact_filters)
        if exact_expr:
            conditions.append(exact_expr)
    
    # Add LIKE filters
    if like_filters:
        for field, value in like_filters.items():
            conditions.append(build_like_filter(field, value))
    
    return ' and '.join(conditions) if conditions else ""


def parse_filter_dict(filters: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
    """
    Parse filter dictionary into exact and LIKE filters.
    
    Handles special suffixes:
    - '_contains': Convert to LIKE filter
    - No suffix: Exact match
    
    Args:
        filters: Raw filter dictionary
        
    Returns:
        Tuple of (exact_filters, like_filters)
        
    Example:
        >>> parse_filter_dict({
        ...     'main_command': 'hey_egeria',
        ...     'subcommand_contains': 'platform'
        ... })
        ({'main_command': 'hey_egeria'}, {'subcommand': 'platform'})
    """
    exact_filters = {}
    like_filters = {}
    
    for key, value in filters.items():
        if key.endswith('_contains'):
            # Remove _contains suffix for field name
            field = key[:-9]  # len('_contains') = 9
            like_filters[field] = value
        else:
            exact_filters[key] = value
    
    return exact_filters, like_filters


def build_combined_filter_expr(filters: Dict[str, Any]) -> str:
    """
    Build complete filter expression from mixed filter dictionary.
    
    Automatically handles both exact and LIKE filters based on key suffixes.
    
    Args:
        filters: Dictionary with mixed filter types
        
    Returns:
        Complete filter expression
        
    Example:
        >>> build_combined_filter_expr({
        ...     'class_name': 'ProjectManager',
        ...     'element_type': 'method',
        ...     'parameters_contains': 'name'
        ... })
        'class_name == "ProjectManager" and element_type == "method" and parameters like "%name%"'
    """
    exact_filters, like_filters = parse_filter_dict(filters)
    return combine_filters(exact_filters, like_filters)