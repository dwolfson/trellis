"""
Collection router for intelligent query routing across multiple collections.

This module determines which collection(s) to search based on query content,
domain terms, and collection metadata.
"""

from typing import List, Dict, Any, Optional, Tuple
from loguru import logger

from advisor.collection_config import (
    CollectionMetadata,
    get_enabled_collections,
    get_collections_by_priority,
    get_collection
)
from advisor.query_patterns import get_domain_terms


class CollectionRouter:
    """Routes queries to appropriate collections."""

    # Collections that contain action/command templates — not suitable for
    # informational "how do I find / what is / explain" queries.
    _ACTION_ONLY_COLLECTIONS = {"egeria_templates"}

    # Patterns that signal an informational (non-action) query.
    _INFORMATIONAL_PATTERNS = (
        "how do i find", "how do i get", "how do i list", "how do i search",
        "how do i retrieve", "how do i view", "how do i access", "how do i query",
        "how to find", "how to get", "how to list", "how to search",
        "how to retrieve", "how to view", "how to query",
        "what is", "what are", "explain", "describe", "tell me about",
        "show me examples", "give me examples", "show me an example",
    )

    def __init__(self):
        """Initialize collection router."""
        self.collections = get_enabled_collections()
        self.domain_terms = get_domain_terms()
        logger.info(f"Initialized collection router with {len(self.collections)} enabled collections")
    
    def route_query(
        self,
        query: str,
        query_terms: Optional[List[str]] = None,
        max_collections: int = 3,
        intent: Optional[str] = None,
        boosted_collections: Optional[List[str]] = None,
        feedback_adjustments: Optional[Dict[str, float]] = None
    ) -> List[str]:
        """
        Route a query to appropriate collection(s).
        
        Args:
            query: User query string
            query_terms: Optional pre-extracted query terms
            max_collections: Maximum number of collections to search
            intent: Optional resolved intent string
            boosted_collections: Optional list of collections/types to boost
            feedback_adjustments: Optional feedback-based multipliers
            
        Returns:
            List of collection names to search, ordered by priority
        """
        query_lower = query.lower()
        query_terms = query_terms or self._extract_terms(query_lower)
        
        # Find matching collections
        matches = self._find_matching_collections(
            query_lower,
            query_terms,
            intent=intent,
            boosted_collections=boosted_collections,
            feedback_adjustments=feedback_adjustments
        )
        
        if not matches:
            # No specific matches, use default strategy
            matches = self._get_default_collections()
            logger.info(f"No specific matches, using default collections: {matches}")
        else:
            logger.info(f"Matched collections for query: {matches}")
        
        # Limit to max_collections
        return matches[:max_collections]
    
    def _extract_terms(self, query_lower: str) -> List[str]:
        """Extract key terms from query."""
        # Simple word extraction (can be enhanced)
        words = query_lower.split()
        # Filter out common stop words
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'in', 'on', 'at', 'to', 'for'}
        return [w for w in words if w not in stop_words and len(w) > 2]
    
    def _find_matching_collections(
        self,
        query_lower: str,
        query_terms: List[str],
        intent: Optional[str] = None,
        boosted_collections: Optional[List[str]] = None,
        feedback_adjustments: Optional[Dict[str, float]] = None
    ) -> List[str]:
        """
        Find collections that match the query.
        
        Args:
            query_lower: Lowercase query string
            query_terms: Extracted query terms
            intent: Resolved query intent
            boosted_collections: Collections to boost
            feedback_adjustments: Boost adjustment multipliers
            
        Returns:
            List of matching collection names, ordered by priority
        """
        matches: List[Tuple[str, int, int, float]] = []  # (name, priority, match_count, intent_boost)

        # Informational queries (how do I find, what is, explain…) should not route
        # to action-only collections like egeria_templates — those are command templates,
        # not API documentation.
        is_informational = any(p in query_lower for p in self._INFORMATIONAL_PATTERNS)

        # Detect query intent for boosting
        intent_keywords = {
            "documentation": ["documentation", "docs", "guide", "tutorial", "manual", "reference"],
            "code": ["code", "implementation", "source", "class", "function", "method"],
            "example": ["example", "sample", "demo", "notebook", "workspace"],
            "cli": ["cli", "command", "terminal", "hey-egeria", "hey_egeria"],
        }
        
        detected_intent = None
        for intent_kw, keywords in intent_keywords.items():
            if any(kw in query_lower for kw in keywords):
                detected_intent = intent_kw
                break
        
        for collection in self.collections:
            # Skip action-only collections for informational queries
            if is_informational and collection.name in self._ACTION_ONLY_COLLECTIONS:
                continue

            match_count = 0
            intent_boost = 0.0

            # 1. Apply policy-defined boosted_collections
            if boosted_collections:
                for boosted in boosted_collections:
                    boosted_lower = boosted.lower()
                    if (collection.name.lower() == boosted_lower or
                        collection.content_type.value == boosted_lower or
                        collection.language.value == boosted_lower or
                        (boosted_lower == "code_elements" and collection.content_type.value == "code")):
                        intent_boost = 12.0
                        match_count += 2
                        break

            # 2. Check for explicit collection name mention (highest priority)
            collection_name_variants = [
                collection.name.lower(),
                collection.name.lower().replace("_", " "),
                collection.name.lower().replace("_", "-"),
            ]
            for variant in collection_name_variants:
                # Check if variant appears as a complete word/phrase
                import re
                # Create pattern that matches the variant with word boundaries
                pattern = r'\b' + re.escape(variant) + r'\b'
                if re.search(pattern, query_lower):
                    match_count += 10  # Very high match count for explicit collection name
                    intent_boost = 15.0  # Maximum boost
                    break
            
            # 3. Check if collection matches query via domain terms
            for domain_term in collection.domain_terms:
                term_lower = domain_term.lower()
                
                # Exact match in query
                if term_lower in query_lower:
                    match_count += 2
                
                # Match in query terms
                if term_lower in [t.lower() for t in query_terms]:
                    match_count += 1
            
            # Apply general intent-based boosting (only if not already boosted by policy or name match)
            if intent_boost == 0.0:
                if detected_intent == "documentation" and collection.content_type.value == "documentation":
                    intent_boost = 10.0  # Very strong boost for docs when "documentation" mentioned
                elif detected_intent == "example" and collection.content_type.value == "examples":
                    intent_boost = 8.0
                elif detected_intent == "cli" and "cli" in collection.name:
                    intent_boost = 8.0
                elif detected_intent == "code" and collection.content_type.value == "code":
                    intent_boost = 3.0  # Moderate boost for code
            
            # 4. Apply feedback adjustments
            if feedback_adjustments and collection.name in feedback_adjustments:
                adjustment = feedback_adjustments[collection.name]
                if adjustment < 1.0:
                    intent_boost *= adjustment
                    match_count = int(match_count * adjustment)
                else:
                    intent_boost = max(intent_boost * adjustment, 5.0)
                    match_count = int(match_count * adjustment) + 1
            
            if match_count > 0:
                matches.append((collection.name, collection.priority, match_count, intent_boost))
        
        # Sort by: intent_boost (desc), match_count (desc), priority (desc)
        matches.sort(key=lambda x: (x[3], x[2], x[1]), reverse=True)
        
        return [name for name, _, _, _ in matches]
    
    def _get_default_collections(self) -> List[str]:
        """
        Get default collections when no specific matches found.
        
        Returns:
            List of default collection names
        """
        # Default strategy: search Python collections first, then docs
        defaults = []
        
        # Add enabled Python collections by priority
        for collection in get_collections_by_priority():
            if collection.language.value == "python":
                defaults.append(collection.name)
        
        # Add docs collection if enabled
        docs_collection = get_collection("egeria_docs")
        if docs_collection and docs_collection.enabled:
            defaults.append("egeria_docs")
        
        return defaults if defaults else [c.name for c in get_collections_by_priority()[:2]]
    
    def get_related_collections(self, collection_name: str) -> List[str]:
        """
        Get related collections for a given collection.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            List of related collection names that are enabled
        """
        collection = get_collection(collection_name)
        if not collection:
            return []
        
        # Filter to only enabled collections
        enabled_names = {c.name for c in self.collections}
        return [name for name in collection.related_collections if name in enabled_names]
    
    def expand_search(
        self,
        initial_collections: List[str],
        max_total: int = 5
    ) -> List[str]:
        """
        Expand search to include related collections.
        
        Args:
            initial_collections: Initial collection names
            max_total: Maximum total collections to return
            
        Returns:
            Expanded list of collection names
        """
        expanded = list(initial_collections)
        
        for collection_name in initial_collections:
            if len(expanded) >= max_total:
                break
            
            related = self.get_related_collections(collection_name)
            for related_name in related:
                if related_name not in expanded and len(expanded) < max_total:
                    expanded.append(related_name)
        
        return expanded
    
    def route_with_fallback(
        self,
        query: str,
        query_terms: Optional[List[str]] = None,
        min_results_threshold: int = 3,
        max_collections: int = 5
    ) -> Dict[str, Any]:
        """
        Route query with fallback strategy.
        
        If initial collections don't yield enough results, expand to related collections.
        
        Args:
            query: User query string
            query_terms: Optional pre-extracted query terms
            min_results_threshold: Minimum results before expanding
            max_collections: Maximum total collections
            
        Returns:
            Dict with routing strategy:
            {
                "primary": [collection_names],
                "fallback": [collection_names],
                "strategy": "targeted" | "expanded" | "default"
            }
        """
        query_lower = query.lower()
        query_terms = query_terms or self._extract_terms(query_lower)
        
        # Get primary collections
        primary = self.route_query(query, query_terms, max_collections=3)
        
        # Determine strategy
        if primary and len(primary) > 0:
            # Check if we matched specific collections
            matches = self._find_matching_collections(query_lower, query_terms)
            if matches:
                strategy = "targeted"
                # Get related collections as fallback
                fallback = self.expand_search(primary, max_total=max_collections)
                fallback = [c for c in fallback if c not in primary]
            else:
                strategy = "default"
                fallback = []
        else:
            strategy = "default"
            primary = self._get_default_collections()
            fallback = []
        
        return {
            "primary": primary,
            "fallback": fallback,
            "strategy": strategy,
            "max_collections": max_collections
        }
    
    def get_collection_info(self, collection_name: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a collection.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            Dict with collection info or None if not found
        """
        collection = get_collection(collection_name)
        if not collection:
            return None
        
        return {
            "name": collection.name,
            "description": collection.description,
            "content_type": collection.content_type.value,
            "language": collection.language.value,
            "priority": collection.priority,
            "enabled": collection.enabled,
            "domain_terms": collection.domain_terms,
            "related_collections": collection.related_collections
        }
    
    def get_routing_summary(self) -> Dict[str, Any]:
        """Get summary of routing configuration."""
        # domain_terms is a dict, get its keys
        domain_categories = list(self.domain_terms.keys()) if isinstance(self.domain_terms, dict) else []
        
        return {
            "total_collections": len(self.collections),
            "enabled_collections": [c.name for c in self.collections],
            "collections_by_priority": [c.name for c in get_collections_by_priority()],
            "domain_categories": domain_categories
        }


# Singleton instance
_router_instance: Optional[CollectionRouter] = None


def get_collection_router() -> CollectionRouter:
    """Get singleton collection router instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = CollectionRouter()
    return _router_instance


def route_query(query: str, max_collections: int = 3) -> List[str]:
    """
    Convenience function to route a query.
    
    Args:
        query: User query string
        max_collections: Maximum collections to return
        
    Returns:
        List of collection names to search
    """
    router = get_collection_router()
    return router.route_query(query, max_collections=max_collections)