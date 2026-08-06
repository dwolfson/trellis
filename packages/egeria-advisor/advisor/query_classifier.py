"""
Query classification module for categorizing user queries by type and topic.

This module automatically classifies queries to enable:
- Type-specific routing and parameter selection
- Topic-based collection filtering
- Quality analysis by query category
- Performance optimization per query type
"""

import re
from enum import Enum
from typing import List, Tuple, Dict, Set, Any, Optional
from dataclasses import dataclass
from loguru import logger

from advisor.query_patterns import get_domain_terms


class QueryType(Enum):
    """Types of user queries."""
    CONCEPT = "concept"           # "What is X?" - definitions
    TYPE = "type"                 # "What properties does X have?" - type system
    CODE = "code"                 # "Show me code for X" - implementation
    EXAMPLE = "example"           # "Give me an example of X" - usage examples
    TUTORIAL = "tutorial"         # "How do I X?" - step-by-step guides
    TROUBLESHOOTING = "troubleshooting"  # "Why doesn't X work?" - debugging
    COMPARISON = "comparison"     # "What's the difference between X and Y?"
    GENERAL = "general"           # General questions


class QueryTopic(Enum):
    """Domain topics in queries."""
    GLOSSARY = "glossary"
    ASSET = "asset"
    METADATA = "metadata"
    GOVERNANCE = "governance"
    LINEAGE = "lineage"
    INTEGRATION = "integration"
    CONNECTOR = "connector"
    SERVER = "server"
    PLATFORM = "platform"
    API = "api"
    CLI = "cli"
    CONFIGURATION = "configuration"
    SECURITY = "security"
    REPOSITORY = "repository"
    CATALOG = "catalog"
    UNKNOWN = "unknown"


@dataclass
class QueryClassification:
    """Result of query classification."""
    query_type: QueryType
    topics: List[QueryTopic]
    confidence: float
    matched_patterns: List[str]
    matched_terms: Dict[QueryTopic, List[str]]


class QueryClassifier:
    """Classify queries by type and topic."""
    
    # Query type patterns (ordered by specificity)
    TYPE_PATTERNS = {
        QueryType.CONCEPT: [
            r'\bwhat\s+is\b',
            r'\bdefine\b',
            r'\bexplain\b',
            r'\bmeaning\s+of\b',
            r'\bdefinition\b',
            r'\bdescribe\b',
            r'\btell\s+me\s+about\b',
        ],
        QueryType.TYPE: [
            r'\btype\b',
            r'\bproperty\b',
            r'\bproperties\b',
            r'\battribute\b',
            r'\battributes\b',
            r'\bfield\b',
            r'\bfields\b',
            r'\bschema\b',
            r'\bstructure\b',
            r'\bwhat\s+properties\b',
            r'\bwhat\s+attributes\b',
        ],
        QueryType.CODE: [
            r'\bcode\b',
            r'\bimplementation\b',
            r'\bimplement\b',
            r'\bimplemented\b',
            r'\bfunction\b',
            r'\bclass\b',
            r'\bmethod\b',
            r'\bshow\s+me\b',
            r'\bhow\s+to\s+implement\b',
            r'\bsource\s+code\b',
            r'\bpython\s+code\b',
            r'\bjava\s+code\b',
        ],
        QueryType.EXAMPLE: [
            r'\bexample\b',
            r'\bexamples\b',
            r'\bsample\b',
            r'\bsamples\b',
            r'\bdemo\b',
            r'\bhow\s+to\s+use\b',
            r'\busage\b',
            r'\bshow\s+me\s+an?\s+example\b',
            r'\bgive\s+me\s+an?\s+example\b',
        ],
        QueryType.TUTORIAL: [
            r'\bhow\s+do\s+i\b',
            r'\bhow\s+can\s+i\b',
            r'\btutorial\b',
            r'\bguide\b',
            r'\bstep\s+by\s+step\b',
            r'\bwalkthrough\b',
            r'\bget\s+started\b',
            r'\bquick\s+start\b',
        ],
        QueryType.TROUBLESHOOTING: [
            r'\berror\b',
            r'\bdoesn\'?t(?:\s+\w+){0,3}\s+work\b',
            r'\bnot\s+working\b',
            r'\bproblem\b',
            r'\bissue\b',
            r'\bfix\b',
            r'\bdebug\b',
            r'\bfailing\b',
            r'\bfailed\b',
            r'\bwhy\s+is\b',
            r'\bwhy\s+does\b',
        ],
        QueryType.COMPARISON: [
            r'\bdifference\b',
            r'\bdifferences\b',
            r'\bcompare\b',
            r'\bcomparison\b',
            r'\bversus\b',
            r'\bvs\.?\b',
            r'\bbetter\b',
            r'\bwhich\s+(?:one|should)\b',
            r'\bwhen\s+to\s+use\b',
        ],
    }
    
    # Topic keywords (from domain terms)
    TOPIC_KEYWORDS = {
        QueryTopic.GLOSSARY: [
            'glossary', 'term', 'category', 'semantic', 'meaning'
        ],
        QueryTopic.ASSET: [
            'asset', 'data asset', 'resource', 'artifact'
        ],
        QueryTopic.METADATA: [
            'metadata', 'meta data', 'data about data', 'annotation'
        ],
        QueryTopic.GOVERNANCE: [
            'governance', 'policy', 'compliance', 'steward', 'owner'
        ],
        QueryTopic.LINEAGE: [
            'lineage', 'provenance', 'data flow', 'upstream', 'downstream'
        ],
        QueryTopic.INTEGRATION: [
            'integration', 'integrate', 'connector', 'connection'
        ],
        QueryTopic.CONNECTOR: [
            'connector', 'connection', 'integration connector'
        ],
        QueryTopic.SERVER: [
            'server', 'omag server', 'platform', 'service'
        ],
        QueryTopic.PLATFORM: [
            'platform', 'omag platform', 'deployment'
        ],
        QueryTopic.API: [
            'api', 'rest', 'endpoint', 'request', 'response'
        ],
        QueryTopic.CLI: [
            'cli', 'command line', 'hey-egeria', 'hey_egeria', 'terminal'
        ],
        QueryTopic.CONFIGURATION: [
            'configuration', 'config', 'setup', 'settings'
        ],
        QueryTopic.SECURITY: [
            'security', 'authentication', 'authorization', 'access control'
        ],
        QueryTopic.REPOSITORY: [
            'repository', 'repo', 'store', 'persistence'
        ],
        QueryTopic.CATALOG: [
            'catalog', 'catalogue', 'discovery', 'search'
        ],
    }
    
    def __init__(self):
        """Initialize query classifier."""
        # Compile regex patterns for efficiency
        self.compiled_patterns = {
            query_type: [re.compile(pattern, re.IGNORECASE) 
                        for pattern in patterns]
            for query_type, patterns in self.TYPE_PATTERNS.items()
        }
        
        logger.info("Initialized QueryClassifier")
    
    def classify(self, query: str) -> QueryClassification:
        """
        Classify query by type and topics.
        
        Args:
            query: User query string
            
        Returns:
            QueryClassification with type, topics, and confidence
        """
        query_lower = query.lower()
        
        # Classify query type
        query_type, type_confidence, matched_patterns = self._classify_type(query_lower)
        
        # Extract topics
        topics, matched_terms = self._extract_topics(query_lower)
        
        # Calculate overall confidence
        confidence = self._calculate_confidence(
            type_confidence,
            len(topics),
            len(matched_patterns)
        )
        
        classification = QueryClassification(
            query_type=query_type,
            topics=topics if topics else [QueryTopic.UNKNOWN],
            confidence=confidence,
            matched_patterns=matched_patterns,
            matched_terms=matched_terms
        )
        
        logger.debug(
            f"Classified query as {query_type.value} "
            f"(topics: {[t.value for t in topics]}, confidence: {confidence:.2f})"
        )
        
        return classification
    
    def _classify_type(self, query_lower: str) -> Tuple[QueryType, float, List[str]]:
        """
        Classify query type based on patterns.
        
        Args:
            query_lower: Lowercase query string
            
        Returns:
            (query_type, confidence, matched_patterns)
        """
        matches: Dict[QueryType, List[str]] = {}
        
        # Check each query type's patterns
        for query_type, patterns in self.compiled_patterns.items():
            matched = []
            for pattern in patterns:
                if pattern.search(query_lower):
                    matched.append(pattern.pattern)
            
            if matched:
                matches[query_type] = matched
        
        # Determine best match
        if not matches:
            return QueryType.GENERAL, 0.5, []
        
        # If multiple matches, prefer more specific types
        # Order of specificity (most to least specific)
        specificity_order = [
            QueryType.TROUBLESHOOTING,
            QueryType.COMPARISON,
            QueryType.TYPE,
            QueryType.EXAMPLE,
            QueryType.CODE,
            QueryType.TUTORIAL,
            QueryType.CONCEPT,
        ]
        
        for query_type in specificity_order:
            if query_type in matches:
                confidence = min(0.95, 0.7 + (len(matches[query_type]) * 0.1))
                return query_type, confidence, matches[query_type]
        
        # Fallback to first match
        query_type = list(matches.keys())[0]
        confidence = min(0.95, 0.7 + (len(matches[query_type]) * 0.1))
        return query_type, confidence, matches[query_type]
    
    def _extract_topics(self, query_lower: str) -> Tuple[List[QueryTopic], Dict[QueryTopic, List[str]]]:
        """
        Extract domain topics from query.
        
        Args:
            query_lower: Lowercase query string
            
        Returns:
            (list of topics, dict of matched terms per topic)
        """
        topics: Set[QueryTopic] = set()
        matched_terms: Dict[QueryTopic, List[str]] = {}
        
        # Check each topic's keywords
        for topic, keywords in self.TOPIC_KEYWORDS.items():
            matched = []
            for keyword in keywords:
                # Use word boundaries for better matching
                pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
                if re.search(pattern, query_lower):
                    matched.append(keyword)
            
            if matched:
                topics.add(topic)
                matched_terms[topic] = matched
        
        # Sort topics by number of matches (most relevant first)
        sorted_topics = sorted(
            topics,
            key=lambda t: len(matched_terms.get(t, [])),
            reverse=True
        )
        
        return sorted_topics, matched_terms
    
    def _calculate_confidence(
        self,
        type_confidence: float,
        num_topics: int,
        num_patterns: int
    ) -> float:
        """
        Calculate overall classification confidence.
        
        Args:
            type_confidence: Confidence in query type classification
            num_topics: Number of topics detected
            num_patterns: Number of patterns matched
            
        Returns:
            Overall confidence score (0-1)
        """
        # Base confidence from type classification
        confidence = type_confidence
        
        # Boost confidence if topics detected
        if num_topics > 0:
            topic_boost = min(0.15, num_topics * 0.05)
            confidence = min(1.0, confidence + topic_boost)
        
        # Boost confidence if multiple patterns matched
        if num_patterns > 1:
            pattern_boost = min(0.1, (num_patterns - 1) * 0.03)
            confidence = min(1.0, confidence + pattern_boost)
        
        return confidence
    
    def get_expected_collections(self, classification: QueryClassification) -> List[str]:
        """
        Get expected collections for a query classification.
        
        Args:
            classification: Query classification result
            
        Returns:
            List of expected collection names
        """
        query_type = classification.query_type
        
        # Map query types to expected collections
        type_to_collections = {
            QueryType.CONCEPT: ['egeria_concepts', 'egeria_types'],
            QueryType.TYPE: ['egeria_types', 'egeria_concepts'],
            QueryType.CODE: ['pyegeria', 'pyegeria_cli', 'egeria_java'],
            QueryType.EXAMPLE: ['egeria_workspaces', 'pyegeria'],
            QueryType.TUTORIAL: ['egeria_general', 'egeria_workspaces'],
            QueryType.TROUBLESHOOTING: ['egeria_general', 'pyegeria', 'egeria_workspaces'],
            QueryType.COMPARISON: ['egeria_concepts', 'egeria_types', 'egeria_general'],
            QueryType.GENERAL: ['pyegeria', 'egeria_general'],
        }
        
        expected = type_to_collections.get(query_type, [])
        
        # Add topic-specific collections
        for topic in classification.topics:
            if topic == QueryTopic.CLI:
                if 'pyegeria_cli' not in expected:
                    expected.append('pyegeria_cli')
            elif topic == QueryTopic.API:
                if 'pyegeria' not in expected:
                    expected.insert(0, 'pyegeria')
        
        return expected
    
    def get_expected_parameters(self, classification: QueryClassification) -> Dict[str, Any]:
        """
        Get expected retrieval parameters for a query classification.
        
        Args:
            classification: Query classification result
            
        Returns:
            Dict with expected parameters (chunk_size, min_score, top_k)
        """
        query_type = classification.query_type
        
        # Map query types to expected parameters
        type_to_params = {
            QueryType.CONCEPT: {
                'chunk_size': 768,
                'min_score': 0.45,
                'top_k': 5,
            },
            QueryType.TYPE: {
                'chunk_size': 1024,
                'min_score': 0.42,
                'top_k': 6,
            },
            QueryType.CODE: {
                'chunk_size': 512,
                'min_score': 0.35,
                'top_k': 10,
            },
            QueryType.EXAMPLE: {
                'chunk_size': 1536,
                'min_score': 0.38,
                'top_k': 8,
            },
            QueryType.TUTORIAL: {
                'chunk_size': 1536,
                'min_score': 0.38,
                'top_k': 8,
            },
            QueryType.TROUBLESHOOTING: {
                'chunk_size': 1024,
                'min_score': 0.35,
                'top_k': 10,
            },
            QueryType.COMPARISON: {
                'chunk_size': 1024,
                'min_score': 0.40,
                'top_k': 8,
            },
            QueryType.GENERAL: {
                'chunk_size': 768,
                'min_score': 0.35,
                'top_k': 8,
            },
        }
        
        return type_to_params.get(query_type, {
            'chunk_size': 768,
            'min_score': 0.35,
            'top_k': 8,
        })


# Global classifier instance
_classifier_instance: Optional[QueryClassifier] = None


def get_query_classifier() -> QueryClassifier:
    """Get singleton query classifier instance."""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = QueryClassifier()
    return _classifier_instance


def classify_query(query: str) -> QueryClassification:
    """
    Convenience function to classify a query.
    
    Args:
        query: User query string
        
    Returns:
        QueryClassification result
    """
    classifier = get_query_classifier()
    return classifier.classify(query)