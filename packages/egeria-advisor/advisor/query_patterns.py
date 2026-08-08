"""
Query pattern definitions for query type detection.

This module provides a centralized, extensible configuration for query patterns.
Patterns are organized by query type and priority for easy maintenance and extension.

Configuration can be loaded from YAML file (config/routing.yaml) or use defaults.
"""

from typing import Dict, List, Optional, Any
from enum import Enum
from pathlib import Path
import yaml
from loguru import logger


class QueryType(Enum):
    """Types of queries the system can handle."""
    CODE_SEARCH = "code_search" # Deprecated/legacy
    CODE_HELP = "code_help"
    CODE_INTEL = "code_intel"
    EXPLANATION = "explanation"
    EXAMPLE = "example"
    COMPARISON = "comparison"
    BEST_PRACTICE = "best_practice"
    DEBUGGING = "debugging"
    QUANTITATIVE = "quantitative"
    RELATIONSHIP = "relationship"
    REPORT = "report"    # MCP report generation
    COMMAND = "command"  # MCP command execution
    PLAN = "plan"        # Multi-step governance plan document generation
    GENERAL = "general"


class PatternPriority(Enum):
    """Priority levels for pattern matching."""
    CRITICAL = 1    # Must match first (very specific)
    HIGH = 2        # High priority (specific multi-word)
    MEDIUM = 3      # Medium priority (action-oriented)
    LOW = 4         # Low priority (general patterns)
    FALLBACK = 5    # Last resort (catch-all)


# Pattern definitions organized by priority and query type
QUERY_PATTERNS = {
    # CRITICAL PRIORITY - Most specific patterns that must match first
    PatternPriority.CRITICAL: {
        QueryType.QUANTITATIVE: [
            "how many lines of code",
            "lines of code",
            "what is the average",
            "what's the average",
        ],
        QueryType.DEBUGGING: [
            "why isn't this working",
            "why isn't my",
            "i'm getting an error when",
            "getting an error when",
        ],
        QueryType.BEST_PRACTICE: [
            "what is the best practice",
            "what are the best practices",
            "recommended approach for",
        ],
        QueryType.COMPARISON: [
            "how does x differ from",
            "how does x compare to",
            "differ from",
        ],
    },
    
    # HIGH PRIORITY - Specific multi-word patterns
    PatternPriority.HIGH: {
        QueryType.REPORT: [
            # Explicit report commands
            "generate report", "create report", "run report", "show report",
            "report on", "get report", "produce report", "make report",
            "list reports", "available reports", "what reports",
            # Live Egeria data listing queries — must appear before MEDIUM CODE_SEARCH patterns
            "show me available", "show me all", "list available", "list all",
            "show available", "display all", "view all",
            "show glossaries", "list glossaries", "view glossaries",
            "show collections", "list collections", "view collections",
            "show assets", "list assets", "view assets",
            "show zones", "list zones", "view zones",
            "available glossaries", "available collections", "available assets",
            "what glossaries", "what collections", "what assets",
            "what data assets", "what governance zones",
        ],
        QueryType.COMMAND: [
            "run command", "execute command", "invoke", "call",
            "run the", "execute the", "perform", "do"
        ],
        QueryType.QUANTITATIVE: [
            "how many", "how much", "number of", "count",
            "total", "statistics", "metrics", "size",
            "summary", "overview", "average"
        ],
        QueryType.BEST_PRACTICE: [
            "best practice", "best way", "recommended", "should i",
            "proper way", "correct way", "standard"
        ],
        QueryType.COMPARISON: [
            "difference between", "compare", "versus", "vs",
            "differ from", "better", "which", "choose between"
        ],
        QueryType.DEBUGGING: [
            "why isn't", "isn't working", "not working",
            "getting an error", "how do i fix", "troubleshoot",
            "fix", "debug"
        ],
    },
    
    # MEDIUM PRIORITY - Action-oriented patterns
    PatternPriority.MEDIUM: {
        QueryType.CODE_HELP: [
            "show me how to", "give me an example of", "how do i",
            "how to use", "find examples", "example code for",
            "sample python code", "how do i call", "example of using"
        ],
        QueryType.CODE_INTEL: [
            "what class is", "where is", "defined in",
            "does class", "inherit from", "class hierarchy",
            "inheritance", "list methods of", "methods of class",
            "what is the superclass of", "what is the subclass of",
            "what method", "method defined in", "what classes",
            "list classes", "classes in", "classes of", "what are the classes"
        ],
        QueryType.CODE_SEARCH: [
            "show me how", "give me an example of", "how do i",
            "how to", "find examples", "find", "search",
            "locate", "where is", "get", "retrieve", "fetch"
        ],
        QueryType.EXAMPLE: [
            "show me examples", "give me examples", "show examples",
            "give me example", "examples of", "example of",
            "sample", "demo", "some examples"
        ],
        QueryType.RELATIONSHIP: [
            "what functions", "show me the", "what does",
            "what calls", "what imports", "what uses",
            "what are the dependencies", "related to",
            "relationship", "connected", "belong to",
            "methods of", "inherits", "extends", "depends on",
            "class hierarchy", "inheritance"
        ],
        QueryType.EXPLANATION: [
            "how does", "explain", "describe",
            "what is a", "what is the"
        ],
    },
    
    # LOW PRIORITY - General patterns
    PatternPriority.LOW: {
        QueryType.GENERAL: [
            "tell me about", "what is", "what are"
        ],
    },
}


# Domain-specific terms for context-aware detection
DOMAIN_TERMS = {
    "egeria_concepts": [
        "glossary", "collection", "asset", "governance zone",
        "lineage", "connection", "term", "category",
        "classification", "entity", "relationship",
        "catalog", "governance", "type", "property", "attribute",
        "connector", "integration", "server", "platform", "cohort",
        "repository", "archive"
    ],
    "egeria_code": [
        "egeria-core", "egeria-server", "egeria-ui", "egeria-connectors",
        "open-metadata", "omas", "omag", "omrs", "ocf", "oif",
        "access-service", "view-service", "integration-service",
        "governance-server", "metadata-server", "repository-proxy"
    ],
    "pyegeria_code": [
        "pyegeria", "python-client", "egeria-python", "py-egeria",
        "python-api", "python-sdk", "egeria-client", "rest-client",
        "async-client", "widget", "jupyter", "notebook"
    ],
    "egeria_workspaces": [
        "egeria-workspaces", "workspace", "project-workspace",
        "developer-workspace", "admin-workspace", "user-workspace",
        "collaboration-space", "team-workspace"
    ],
    "use_cases": [
        "use-case", "scenario", "example", "tutorial", "guide",
        "walkthrough", "demonstration", "sample", "template",
        "pattern", "best-practice", "reference-implementation"
    ],
    "deployment": [
        "deployment", "installation", "setup", "configuration",
        "docker", "kubernetes", "helm", "container", "pod",
        "service", "ingress", "volume", "secret", "configmap",
        "cloud", "aws", "azure", "gcp", "on-premise"
    ],
    "technical_concepts": [
        "class", "function", "method", "module", "package",
        "api", "endpoint", "service", "client", "import",
        "variable", "parameter", "return", "exception", "error",
        "request", "response", "configuration"
    ],
    "general_terms": [
        "system", "platform", "framework", "architecture",
        "design", "implementation", "testing", "documentation",
        "performance", "security", "authentication", "authorization"
    ]
}


# Special case rules for edge cases
SPECIAL_RULES = {
    "how_does_differ": {
        "pattern": "how does",
        "check_terms": ["differ", "compare"],
        "if_match": QueryType.COMPARISON,
        "if_no_match": None  # Continue to next rule
    },
    "tell_me_about_domain": {
        "pattern": "tell me about",
        "check_terms": DOMAIN_TERMS["egeria_concepts"],
        "if_match": QueryType.EXPLANATION,
        "if_no_match": QueryType.GENERAL
    },
    "how_does_system": {
        "pattern": "how does",
        "check_terms": DOMAIN_TERMS["general_terms"],
        "if_match": QueryType.GENERAL,
        "if_no_match": QueryType.EXPLANATION
    }
}


# Configuration loading
_config_cache: Optional[Dict[str, Any]] = None
_config_file_path = Path(__file__).parent / "configdata" / "routing.yaml"


def _load_config() -> Dict[str, Any]:
    """Load routing configuration from YAML file."""
    global _config_cache
    
    if _config_cache is not None:
        return _config_cache
    
    if not _config_file_path.exists():
        logger.warning(f"Routing config not found at {_config_file_path}, using defaults")
        _config_cache = {}
        return _config_cache
    
    try:
        with open(_config_file_path, 'r') as f:
            config = yaml.safe_load(f)
            _config_cache = config or {}
            logger.info(f"Loaded routing configuration from {_config_file_path}")
            return _config_cache
    except Exception as e:
        logger.error(f"Error loading routing config: {e}, using defaults")
        _config_cache = {}
        return _config_cache


def reload_config() -> bool:
    """
    Reload configuration from file.
    
    Returns:
        True if reload successful, False otherwise
    """
    global _config_cache, QUERY_PATTERNS, DOMAIN_TERMS, SPECIAL_RULES
    
    _config_cache = None
    config = _load_config()
    
    if not config:
        return False
    
    try:
        # Reload query patterns
        if 'query_patterns' in config:
            _load_query_patterns_from_config(config['query_patterns'])
        
        # Reload domain terms
        if 'domain_terms' in config:
            _load_domain_terms_from_config(config['domain_terms'])
        
        # Reload special rules
        if 'special_rules' in config:
            _load_special_rules_from_config(config['special_rules'])
        
        logger.info("Configuration reloaded successfully")
        return True
    except Exception as e:
        logger.error(f"Error reloading configuration: {e}")
        return False


def _load_query_patterns_from_config(patterns_config: Dict[str, Any]) -> None:
    """Load query patterns from config into QUERY_PATTERNS."""
    global QUERY_PATTERNS
    
    priority_map = {
        'critical': PatternPriority.CRITICAL,
        'high': PatternPriority.HIGH,
        'medium': PatternPriority.MEDIUM,
        'low': PatternPriority.LOW,
        'fallback': PatternPriority.FALLBACK
    }
    
    query_type_map = {
        'code_search': QueryType.CODE_SEARCH,
        'code_help': QueryType.CODE_HELP,
        'code_intel': QueryType.CODE_INTEL,
        'explanation': QueryType.EXPLANATION,
        'example': QueryType.EXAMPLE,
        'comparison': QueryType.COMPARISON,
        'best_practice': QueryType.BEST_PRACTICE,
        'debugging': QueryType.DEBUGGING,
        'quantitative': QueryType.QUANTITATIVE,
        'relationship': QueryType.RELATIONSHIP,
        'report': QueryType.REPORT,
        'command': QueryType.COMMAND,
        'plan': QueryType.PLAN,
        'general': QueryType.GENERAL
    }
    
    for priority_str, types_dict in patterns_config.items():
        priority = priority_map.get(priority_str)
        if not priority:
            logger.warning(f"Unknown priority level: {priority_str}")
            continue
        
        if priority not in QUERY_PATTERNS:
            QUERY_PATTERNS[priority] = {}
        
        for type_str, patterns in types_dict.items():
            query_type = query_type_map.get(type_str)
            if not query_type:
                logger.warning(f"Unknown query type: {type_str}")
                continue
            
            QUERY_PATTERNS[priority][query_type] = patterns


def _load_domain_terms_from_config(terms_config: Dict[str, List[str]]) -> None:
    """Load domain terms from config into DOMAIN_TERMS."""
    global DOMAIN_TERMS
    
    for category, terms in terms_config.items():
        DOMAIN_TERMS[category] = terms


def _load_special_rules_from_config(rules_config: Dict[str, Any]) -> None:
    """Load special rules from config into SPECIAL_RULES."""
    global SPECIAL_RULES
    
    query_type_map = {
        'comparison': QueryType.COMPARISON,
        'explanation': QueryType.EXPLANATION,
        'general': QueryType.GENERAL
    }
    
    for rule_name, rule_data in rules_config.items():
        if 'if_match' in rule_data and isinstance(rule_data['if_match'], str):
            rule_data['if_match'] = query_type_map.get(rule_data['if_match'])
        if 'if_no_match' in rule_data and isinstance(rule_data['if_no_match'], str):
            rule_data['if_no_match'] = query_type_map.get(rule_data['if_no_match'])
        
        # Resolve domain category to actual terms list if present
        if 'check_domain_category' in rule_data:
            category = rule_data['check_domain_category']
            rule_data['check_terms'] = DOMAIN_TERMS.get(category, [])
            
        SPECIAL_RULES[rule_name] = rule_data


# Load configuration on module import
_initial_config = _load_config()
if _initial_config:
    if 'query_patterns' in _initial_config:
        _load_query_patterns_from_config(_initial_config['query_patterns'])
    if 'domain_terms' in _initial_config:
        _load_domain_terms_from_config(_initial_config['domain_terms'])
    if 'special_rules' in _initial_config:
        _load_special_rules_from_config(_initial_config['special_rules'])


def get_patterns_by_priority() -> Dict[PatternPriority, Dict[QueryType, List[str]]]:
    """
    Get all patterns organized by priority.
    
    Returns:
        Dictionary mapping priority levels to query type patterns
    """
    return QUERY_PATTERNS


def get_domain_terms(category: Optional[str] = None) -> List[str]:
    """
    Get domain-specific terms for context-aware detection.
    
    Args:
        category: Optional category filter (egeria_concepts, technical_concepts, general_terms)
        
    Returns:
        List of domain terms
    """
    if category:
        return DOMAIN_TERMS.get(category, [])
    
    # Return all terms if no category specified
    all_terms = []
    for terms in DOMAIN_TERMS.values():
        all_terms.extend(terms)
    return all_terms


def get_special_rules() -> Dict[str, Dict]:
    """
    Get special case rules for edge case handling.
    
    Returns:
        Dictionary of special rules
    """
    return SPECIAL_RULES


def add_pattern(query_type: QueryType, pattern: str, priority: PatternPriority = PatternPriority.MEDIUM):
    """
    Add a new pattern to the pattern database.
    
    Args:
        query_type: The query type this pattern should match
        pattern: The pattern string to match
        priority: Priority level for this pattern
    """
    if priority not in QUERY_PATTERNS:
        QUERY_PATTERNS[priority] = {}
    
    if query_type not in QUERY_PATTERNS[priority]:
        QUERY_PATTERNS[priority][query_type] = []
    
    if pattern not in QUERY_PATTERNS[priority][query_type]:
        QUERY_PATTERNS[priority][query_type].append(pattern)


def add_domain_term(term: str, category: str = "egeria_concepts"):
    """
    Add a new domain term for context-aware detection.
    
    Args:
        term: The domain term to add
        category: Category for the term (default: egeria_concepts)
    """
    if category not in DOMAIN_TERMS:
        DOMAIN_TERMS[category] = []
    
    if term not in DOMAIN_TERMS[category]:
        DOMAIN_TERMS[category].append(term)


def remove_pattern(query_type: QueryType, pattern: str, priority: Optional[PatternPriority] = None):
    """
    Remove a pattern from the pattern database.
    
    Args:
        query_type: The query type to remove pattern from
        pattern: The pattern string to remove
        priority: Optional priority level (if None, searches all priorities)
    """
    if priority:
        priorities = [priority]
    else:
        priorities = list(QUERY_PATTERNS.keys())
    
    for pri in priorities:
        if pri in QUERY_PATTERNS and query_type in QUERY_PATTERNS[pri]:
            if pattern in QUERY_PATTERNS[pri][query_type]:
                QUERY_PATTERNS[pri][query_type].remove(pattern)


def get_collection_domain_terms(collection_name: str) -> List[str]:
    """
    Get domain terms for a specific collection from config.
    
    Args:
        collection_name: Name of the collection
        
    Returns:
        List of domain terms for the collection
    """
    config = _load_config()
    if 'collection_domain_terms' in config:
        return config['collection_domain_terms'].get(collection_name, [])
    return []


def get_intent_keywords() -> Dict[str, List[str]]:
    """
    Get intent-based routing keywords from config.
    
    Returns:
        Dictionary mapping intent names to keyword lists
    """
    config = _load_config()
    return config.get('intent_keywords', {})