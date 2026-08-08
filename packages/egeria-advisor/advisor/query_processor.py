"""
Query processor for understanding and categorizing user queries.

This module analyzes user queries to determine intent and extract
relevant information for RAG retrieval.
"""

from typing import Dict, Any, Optional, List, Tuple
from loguru import logger
import re
import time

# Import from the new extensible pattern system
from advisor.query_patterns import (
    QueryType,
    PatternPriority,
    get_patterns_by_priority,
    get_domain_terms,
    get_special_rules,
    add_pattern,
    add_domain_term
)
from advisor.mlflow_tracking import get_mlflow_tracker
from advisor.metrics_collector import get_metrics_collector, QueryMetric


class QueryProcessor:
    """Processes and analyzes user queries."""
    
    def __init__(self):
        """Initialize query processor with extensible pattern system."""
        # Load patterns from centralized configuration
        self.pattern_priorities = get_patterns_by_priority()
        self.domain_terms = get_domain_terms()
        self.special_rules = get_special_rules()
        
        # Build flattened pattern dict for backward compatibility
        self.query_patterns = self._build_query_patterns()
        
        # Indicator lists for context-aware detection
        self.quantitative_indicators = [
            "how many", "how much", "count", "number of", "total",
            "average", "mean", "sum", "size", "amount"
        ]
        self.relationship_indicators = [
            "import", "depend", "use", "call", "inherit",
            "extend", "implement", "reference"
        ]
        self.debugging_indicators = [
            "error", "exception", "fail", "broken", "not working",
            "doesn't work", "isn't working", "bug", "issue"
        ]
        
        # Initialize monitoring
        self.mlflow_tracker = get_mlflow_tracker()
        self.metrics_collector = get_metrics_collector()
        
        logger.info("Initialized query processor with extensible pattern system")
    
    def _build_query_patterns(self) -> Dict[QueryType, List[str]]:
        """
        Build flattened pattern dictionary from priority-based configuration.
        
        This maintains backward compatibility while using the new extensible system.
        Patterns are organized by priority in the source configuration.
        """
        flattened = {}
        
        # Process patterns in priority order (CRITICAL -> FALLBACK)
        for priority in sorted(self.pattern_priorities.keys(), key=lambda p: p.value):
            for query_type, patterns in self.pattern_priorities[priority].items():
                if query_type not in flattened:
                    flattened[query_type] = []
                # Add patterns, maintaining priority order
                flattened[query_type].extend(patterns)
        
        return flattened
    
    def add_custom_pattern(self, query_type: QueryType, pattern: str, priority: PatternPriority = PatternPriority.MEDIUM):
        """
        Add a custom pattern at runtime.
        
        Args:
            query_type: The query type this pattern should match
            pattern: The pattern string to match
            priority: Priority level for this pattern (default: MEDIUM)
            
        Example:
            processor.add_custom_pattern(QueryType.CODE_SEARCH, "locate code for", PatternPriority.HIGH)
        """
        add_pattern(query_type, pattern, priority)
        # Rebuild pattern dictionary
        self.pattern_priorities = get_patterns_by_priority()
        self.query_patterns = self._build_query_patterns()
        logger.info(f"Added custom pattern '{pattern}' for {query_type.value} at {priority.name} priority")
    
    def add_custom_domain_term(self, term: str, category: str = "egeria_concepts"):
        """
        Add a custom domain term for context-aware detection.
        
        Args:
            term: The domain term to add
            category: Category for the term (default: egeria_concepts)
            
        Example:
            processor.add_custom_domain_term("repository", "egeria_concepts")
        """
        add_domain_term(term, category)
        self.domain_terms = get_domain_terms()
        logger.info(f"Added custom domain term '{term}' to category '{category}'")
    
    def process(self, query: str) -> Dict[str, Any]:
        """
        Process a user query.
        
        Args:
            query: User query string
            
        Returns:
            Dictionary with query analysis
        """
        start_time = time.time()
        query_lower = query.lower()
        
        # Track with MLflow
        with self.mlflow_tracker.track_operation(
            operation_name="query_processor_process",
            params={
                "query_length": len(query)
            },
            track_resources=False,  # Lightweight operation, skip resource tracking
            track_accuracy=False
        ) as tracker:
            # Detect query type
            query_type = self._detect_query_type(query_lower)
            
            # LLM semantic fallback for general queries
            if query_type == QueryType.GENERAL:
                try:
                    from advisor.llm_intent_classifier import get_intent_classifier
                    refined_str = get_intent_classifier().classify(query)
                    if refined_str != "general":
                        try:
                            query_type = QueryType(refined_str)
                            logger.info(f"QueryProcessor: LLM intent classifier refined 'general' -> '{refined_str}'")
                        except ValueError:
                            logger.warning(f"QueryProcessor: Refined intent '{refined_str}' is not a valid QueryType")
                except Exception as exc:
                    logger.warning(f"QueryProcessor: LLM intent classification failed: {exc}")
            
            # Extract keywords
            keywords = self._extract_keywords(query)
            
            # Extract path filter (for scoped queries)
            path_filter = self.extract_path(query)
            
            # Determine if query should prioritize documentation
            prioritize_docs = self._should_prioritize_docs(query_lower, query_type)
            
            # Determine search strategy
            search_strategy = self._determine_search_strategy(query_type)
            
            # Build result
            result = {
                "original_query": query,
                "query_type": query_type.value,
                "keywords": keywords,
                "path_filter": path_filter,  # NEW: for scoped queries
                "search_strategy": search_strategy,
                "enhanced_query": self._enhance_query(query, keywords),
                "prioritize_docs": prioritize_docs,  # NEW: documentation-first flag
                "offer_examples": prioritize_docs  # NEW: offer code examples after docs
            }
            
            # Log metrics
            processing_time_ms = (time.time() - start_time) * 1000
            tracker.log_metrics({
                "processing_time_ms": processing_time_ms,
                "num_keywords": len(keywords),
                "has_path_filter": 1.0 if path_filter else 0.0,
                "prioritize_docs": 1.0 if prioritize_docs else 0.0
            })
            
            log_msg = f"Processed query: type={query_type.value}, keywords={len(keywords)}, time={processing_time_ms:.1f}ms"
            if path_filter:
                log_msg += f", path_filter={path_filter}"
            if prioritize_docs:
                log_msg += ", prioritize_docs=True"
            logger.info(log_msg)
            
            return result
    
    def _should_prioritize_docs(self, query_lower: str, query_type: QueryType) -> bool:
        """
        Determine if query should prioritize documentation over code.
        
        Prioritizes docs for:
        - EXPLANATION queries (what is, how does, explain)
        - GENERAL queries (tell me about)
        - COMPARISON queries (difference between)
        - BEST_PRACTICE queries (unless asking for code)
        
        Does NOT prioritize docs for:
        - CODE_SEARCH queries (how do I, show me how)
        - EXAMPLE queries (give me examples)
        - Queries explicitly asking for code/implementation
        
        Args:
            query_lower: Lowercase query string
            query_type: Detected query type
            
        Returns:
            True if should prioritize documentation
        """
        # Don't prioritize docs if explicitly asking for code/examples
        code_indicators = [
            "code", "example", "implementation", "how do i", "how to",
            "show me how", "give me", "sample", "demo", "snippet"
        ]
        if any(indicator in query_lower for indicator in code_indicators):
            return False
        
        # Prioritize docs for conceptual/explanation queries
        doc_query_types = [
            QueryType.EXPLANATION,
            QueryType.GENERAL,
            QueryType.COMPARISON,
            QueryType.BEST_PRACTICE
        ]
        
        return query_type in doc_query_types
    
    def detect_query_type(self, query: str) -> QueryType:
        """
        Detect the type of query (public method for testing).
        
        Args:
            query: User query string
            
        Returns:
            QueryType enum value
        """
        return self._detect_query_type(query.lower())
    
    def _detect_query_type(self, query_lower: str) -> QueryType:
        """
        Detect the type of query using priority-based pattern matching.
        
        Uses the extensible pattern system with special rules for edge cases.
        Checks patterns in order of specificity (CRITICAL -> FALLBACK priority).
        """
        # Apply special rules first (edge cases)
        for rule_name, rule in self.special_rules.items():
            if rule["pattern"] in query_lower:
                # Check if any of the specified terms are present
                has_term = any(term in query_lower for term in rule["check_terms"])
                if has_term:
                    result = rule["if_match"]
                    if result is not None:
                        return result
                    # If None, continue to next rule
                else:
                    result = rule["if_no_match"]
                    if result is not None:
                        return result
                    # If None, continue to next rule
        
        # Process patterns by priority (CRITICAL -> FALLBACK)
        for priority in sorted(self.pattern_priorities.keys(), key=lambda p: p.value):
            priority_patterns = self.pattern_priorities[priority]
            
            # Gather all patterns at this priority level with their query type
            all_patterns = []
            for query_type, patterns in priority_patterns.items():
                for pattern in patterns:
                    all_patterns.append((pattern, query_type))
            
            # Sort all patterns at this priority by length descending (check longer patterns first)
            sorted_patterns = sorted(all_patterns, key=lambda x: len(x[0]), reverse=True)
            for pattern, query_type in sorted_patterns:
                if pattern in query_lower:
                    return query_type
        
        # Default to general if no patterns match
        return QueryType.GENERAL
    
    def detect_query_type_with_confidence(self, query: str) -> Tuple[QueryType, float]:
        """
        Detect query type with confidence score.
        
        Args:
            query: User query string
            
        Returns:
            Tuple of (QueryType, confidence_score)
            confidence_score is between 0.0 and 1.0
        """
        start_time = time.time()
        query_lower = query.lower()
        
        # Check for context-aware indicators first
        has_quantitative = any(ind in query_lower for ind in self.quantitative_indicators)
        has_relationship = any(ind in query_lower for ind in self.relationship_indicators)
        has_debugging = any(ind in query_lower for ind in self.debugging_indicators)
        
        # Detect base query type
        query_type = self._detect_query_type(query_lower)
        
        # Calculate confidence based on context
        confidence = self._calculate_confidence(
            query_lower,
            query_type,
            has_quantitative,
            has_relationship,
            has_debugging
        )
        
        # Override if strong indicators present
        if has_quantitative and query_type == QueryType.EXPLANATION:
            query_type = QueryType.QUANTITATIVE
            confidence = 0.85
        elif has_relationship and query_type == QueryType.EXPLANATION:
            query_type = QueryType.RELATIONSHIP
            confidence = 0.85
        elif has_debugging and query_type == QueryType.EXPLANATION:
            query_type = QueryType.DEBUGGING
            confidence = 0.85
        
        # Log classification metrics (lightweight, no MLflow tracking)
        processing_time_ms = (time.time() - start_time) * 1000
        logger.debug(f"Query type detection: {query_type.value} (confidence={confidence:.2f}, time={processing_time_ms:.1f}ms)")
        
        return query_type, confidence
    
    def _calculate_confidence(
        self,
        query_lower: str,
        query_type: QueryType,
        has_quantitative: bool,
        has_relationship: bool,
        has_debugging: bool
    ) -> float:
        """
        Calculate confidence score for query type detection.
        
        Args:
            query_lower: Normalized query string
            query_type: Detected query type
            has_quantitative: Whether query has quantitative indicators
            has_relationship: Whether query has relationship indicators
            has_debugging: Whether query has debugging indicators
            
        Returns:
            Confidence score between 0.0 and 1.0
        """
        # Base confidence from pattern matching
        patterns = self.query_patterns.get(query_type, [])
        
        # Find the longest matching pattern
        max_pattern_length = 0
        for pattern in patterns:
            if pattern in query_lower:
                max_pattern_length = max(max_pattern_length, len(pattern))
        
        # Longer patterns = higher confidence
        if max_pattern_length == 0:
            base_confidence = 0.3  # Default for GENERAL
        elif max_pattern_length > 15:
            base_confidence = 0.95  # Very specific pattern
        elif max_pattern_length > 10:
            base_confidence = 0.85  # Specific pattern
        elif max_pattern_length > 5:
            base_confidence = 0.75  # Moderate pattern
        else:
            base_confidence = 0.65  # Short pattern
        
        # Adjust confidence based on context indicators
        if query_type == QueryType.QUANTITATIVE and has_quantitative:
            base_confidence = min(1.0, base_confidence + 0.1)
        elif query_type == QueryType.RELATIONSHIP and has_relationship:
            base_confidence = min(1.0, base_confidence + 0.1)
        elif query_type == QueryType.DEBUGGING and has_debugging:
            base_confidence = min(1.0, base_confidence + 0.1)
        
        # Penalize conflicting indicators
        if query_type == QueryType.EXPLANATION:
            if has_quantitative or has_relationship or has_debugging:
                base_confidence = max(0.4, base_confidence - 0.2)
        
        return base_confidence
    
    def normalize_query(self, query: str) -> str:
        """
        Normalize query text (public method for testing).
        
        Args:
            query: User query string
            
        Returns:
            Normalized query string (lowercase, trimmed whitespace)
        """
        # Remove extra whitespace
        normalized = " ".join(query.split())
        # Strip leading/trailing whitespace
        normalized = normalized.strip()
        # Convert to lowercase for consistent matching
        normalized = normalized.lower()
        return normalized
    
    def extract_keywords(self, query: str) -> List[str]:
        """
        Extract important keywords from query (public method for testing).
        
        Args:
            query: User query string
            
        Returns:
            List of keywords
        """
        return self._extract_keywords(query)
    
    def extract_context(self, query: str) -> Dict[str, Any]:
        """
        Extract contextual information from query (public method for testing).
        
        Args:
            query: User query string
            
        Returns:
            Dictionary with context information including modules and operations
        """
        query_lower = query.lower()
        
        # Extract module/component names (common Egeria modules)
        modules = []
        module_keywords = [
            "glossary", "glossary_manager", "asset", "collection",
            "term", "category", "connection", "lineage", "governance"
        ]
        for keyword in module_keywords:
            if keyword in query_lower:
                modules.append(keyword)
        
        # Extract operations (CRUD operations)
        operations = []
        operation_keywords = [
            "create", "update", "delete", "read", "get", "set",
            "add", "remove", "modify", "retrieve", "fetch"
        ]
        for keyword in operation_keywords:
            if keyword in query_lower:
                operations.append(keyword)
        
        context = {
            "has_code_reference": any(word in query_lower for word in ["class", "function", "method", "def"]),
            "has_file_reference": any(word in query_lower for word in ["file", "module", "package"]),
            "has_error_reference": any(word in query_lower for word in ["error", "exception", "bug", "issue"]),
            "has_quantitative": any(word in query_lower for word in ["how many", "count", "total", "number"]),
            "has_relationship": any(word in query_lower for word in ["calls", "uses", "imports", "inherits"]),
            "modules": modules,
            "operations": operations
        }
        return context
    
    def extract_path(self, query: str) -> Optional[str]:
        """
        Extract path/directory reference from query.
        
        Supports patterns like:
        - "in the pyegeria folder"
        - "under src/utils"
        - "within the tests directory"
        - "from pyegeria/admin"
        
        Args:
            query: User query string
            
        Returns:
            Extracted path string or None if no path found
        """
        query_lower = query.lower()
        
        # Pattern 1: "in [the] X folder/directory/package/module"
        match = re.search(r'in (?:the )?([a-z0-9_/.-]+) (?:folder|directory|package|module)', query_lower)
        if match:
            return match.group(1)
        
        # Pattern 2: "under X" or "within X"
        match = re.search(r'(?:under|within) (?:the )?([a-z0-9_/.-]+)', query_lower)
        if match:
            return match.group(1)
        
        # Pattern 3: "from X" (when X looks like a path)
        match = re.search(r'from (?:the )?([a-z0-9_/.-]+)', query_lower)
        if match:
            path = match.group(1)
            # Only return if it looks like a path (has / or common directory names)
            if '/' in path or path in ['src', 'tests', 'pyegeria', 'admin', 'utils', 'core']:
                return path
        
        # Pattern 4: Direct path reference (contains /)
        match = re.search(r'\b([a-z0-9_]+/[a-z0-9_/.-]+)\b', query_lower)
        if match:
            return match.group(1)
        
        return None
    
    def process_query(self, query: str) -> Dict[str, Any]:
        """
        Process a query and return comprehensive analysis (public method for testing).
        
        Args:
            query: User query string
            
        Returns:
            Dictionary with complete query analysis
            
        Raises:
            ValueError: If query is empty or invalid
        """
        # Validate query
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")
        
        # Normalize the query
        normalized = self.normalize_query(query)
        
        # Detect query type
        query_type = self.detect_query_type(normalized)
        
        # Extract keywords
        keywords = self.extract_keywords(normalized)
        
        # Extract context
        context = self.extract_context(normalized)
        
        # Extract path filter (for scoped queries)
        path_filter = self.extract_path(query)
        
        # Determine search strategy
        search_strategy = self._determine_search_strategy(query_type)
        
        # Build result - return enum instead of string value
        result = {
            "original_query": query,
            "normalized_query": normalized,
            "query_type": query_type,  # Return enum, not .value
            "keywords": keywords,
            "context": context,
            "path_filter": path_filter,  # NEW: for scoped queries
            "search_strategy": search_strategy,
            "enhanced_query": self._enhance_query(normalized, keywords)
        }
        
        log_msg = f"Processed query: type={query_type.value}, keywords={len(keywords)}"
        if path_filter:
            log_msg += f", path_filter={path_filter}"
        logger.info(log_msg)
        
        return result
    
    def _extract_keywords(self, query: str) -> List[str]:
        """Extract important keywords from query."""
        # Simple keyword extraction
        # Remove common words
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at",
            "to", "for", "of", "with", "by", "from", "is", "are",
            "was", "were", "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "will", "would", "should", "could",
            "may", "might", "can", "i", "you", "he", "she", "it",
            "we", "they", "this", "that", "these", "those", "what",
            "which", "who", "when", "where", "why", "how", "me", "my"
        }
        
        # Split and filter
        words = query.lower().split()
        keywords = [
            word.strip(".,!?;:\"'()[]{}")
            for word in words
            if word.lower() not in stop_words and len(word) > 2
        ]
        
        return keywords
    
    def _determine_search_strategy(self, query_type: QueryType) -> Dict[str, Any]:
        """Determine search strategy based on query type."""
        strategies = {
            QueryType.CODE_SEARCH: {
                "top_k": 10,
                "min_score": 0.3,
                "format_style": "compact"
            },
            QueryType.CODE_HELP: {
                "top_k": 10,
                "min_score": 0.3,
                "format_style": "compact"
            },
            QueryType.CODE_INTEL: {
                "top_k": 10,
                "min_score": 0.3,
                "format_style": "compact"
            },
            QueryType.EXPLANATION: {
                "top_k": 10,
                "min_score": 0.3,
                "format_style": "detailed"
            },
            QueryType.EXAMPLE: {
                "top_k": 10,
                "min_score": 0.3,
                "format_style": "detailed"
            },
            QueryType.COMPARISON: {
                "top_k": 10,
                "min_score": 0.3,
                "format_style": "detailed"
            },
            QueryType.BEST_PRACTICE: {
                "top_k": 10,
                "min_score": 0.3,
                "format_style": "detailed"
            },
            QueryType.DEBUGGING: {
                "top_k": 10,
                "min_score": 0.3,
                "format_style": "detailed"
            },
            QueryType.GENERAL: {
                "top_k": 10,
                "min_score": 0.3,
                "format_style": "detailed"
            }
        }
        
        return strategies.get(query_type, strategies[QueryType.GENERAL])
    
    def _enhance_query(self, query: str, keywords: List[str]) -> str:
        """Enhance query for better retrieval."""
        # For now, just return the original query
        # Could add query expansion, synonym handling, etc.
        return query
    
    def suggest_filters(self, query: str) -> Optional[Dict[str, Any]]:
        """Suggest metadata filters based on query."""
        query_lower = query.lower()
        filters = {}
        
        # Detect file type mentions
        if "test" in query_lower:
            filters["file_path"] = {"$regex": "test"}
        
        # Detect element type mentions
        if "class" in query_lower:
            filters["element_type"] = "class"
        elif "function" in query_lower or "def" in query_lower:
            filters["element_type"] = "function"
        elif "method" in query_lower:
            filters["element_type"] = "method"
        
        return filters if filters else None


# Global processor instance
_query_processor: Optional[QueryProcessor] = None


def get_query_processor() -> QueryProcessor:
    """Get or create the global query processor instance."""
    global _query_processor
    
    if _query_processor is None:
        _query_processor = QueryProcessor()
    
    return _query_processor