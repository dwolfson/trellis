"""
PyEgeria Agent - Specialized agent for PyEgeria Python library queries.

This agent provides intelligent responses about PyEgeria classes, methods,
modules, and usage patterns by leveraging the pyegeria collection in the
vector store.

Enhanced with metadata filtering for precise, fast queries.
Enhanced with interactive response formatting for better UX.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from advisor.vector_store import VectorStoreManager, get_vector_store
from advisor.llm_client import OllamaClient, get_ollama_client
from advisor.config import settings
from advisor.metadata_filters import (
    extract_pyegeria_filters,
    build_combined_filter_expr
)
from advisor.query_classifier import classify_query as classify_query_type, QueryType
from advisor.interactive_response import get_interactive_handler
from advisor.prompt_templates import get_prompt_manager

logger = logging.getLogger(__name__)


@dataclass
class PyEgeriaQueryResult:
    """Result from PyEgeria query classification and search."""
    query_type: str  # 'class', 'method', 'module', 'usage', 'example', 'general'
    search_results: List[Dict[str, Any]]
    confidence: float
    

class PyEgeriaAgent:
    """
    Specialized agent for answering PyEgeria-related questions.
    
    Handles queries about:
    - PyEgeria classes (e.g., "What is GlossaryManager?")
    - Methods and functions (e.g., "How do I create a glossary?")
    - Modules and packages (e.g., "What's in pyegeria.admin?")
    - Usage patterns (e.g., "How to connect to OMAG server?")
    - Code examples (e.g., "Show me asset creation example")
    """
    
    def __init__(
        self,
        vector_store: Optional[VectorStoreManager] = None,
        llm_client: Optional[OllamaClient] = None
    ):
        """
        Initialize PyEgeria agent.
        
        Args:
            vector_store: Vector store manager for semantic search
            llm_client: LLM client for generating responses
        """
        self.vector_store = vector_store or get_vector_store()
        self.llm_client = llm_client or get_ollama_client()
        self.collection_name = "pyegeria"
        
        # Query type patterns
        self.query_patterns = {
            'class': [
                'class', 'what is', 'tell me about', 'explain',
                'manager', 'client', 'handler', 'widget'
            ],
            'method': [
                'how do i', 'how to', 'method', 'function',
                'create', 'get', 'update', 'delete', 'list',
                'connect', 'configure', 'setup'
            ],
            'module': [
                'module', 'package', 'what\'s in', 'contains',
                'pyegeria.', 'admin', 'glossary', 'asset'
            ],
            'usage': [
                'use', 'using', 'usage', 'work with',
                'integrate', 'implement'
            ],
            'example': [
                'example', 'sample', 'demo', 'show me',
                'code', 'snippet'
            ]
        }
        
        logger.info("PyEgeria Agent initialized")
    
    def classify_query(self, query: str) -> str:
        """
        Classify the type of PyEgeria query.
        
        Args:
            query: User's query
            
        Returns:
            Query type: 'class', 'method', 'module', 'usage', 'example', or 'general'
        """
        query_lower = query.lower()
        
        # Count pattern matches for each type
        scores = {}
        for query_type, patterns in self.query_patterns.items():
            score = sum(1 for pattern in patterns if pattern in query_lower)
            if score > 0:
                scores[query_type] = score
        
        # Return type with highest score, or 'general' if no matches
        if scores:
            return max(scores.items(), key=lambda x: x[1])[0]
        return 'general'
    
    def is_pyegeria_query(self, query: str) -> bool:
        """
        Determine if query is about PyEgeria.
        
        Uses a two-stage approach:
        1. Check for explicit PyEgeria indicators
        2. If asking about a class/methods, do a quick search to see if it's in pyegeria collection
        
        Args:
            query: User's query
            
        Returns:
            True if query is about PyEgeria
        """
        query_lower = query.lower()
        logger.info(f"PyEgeria detection for query: {query[:100]}")
        
        # Stage 1: Explicit PyEgeria indicators
        pyegeria_indicators = [
            'pyegeria', 'py-egeria', 'python client', 'python api',
            'python library', 'rest client', 'async client',
            'widget', 'egeria client', 'python sdk',
            # Common PyEgeria classes (lowercase for matching)
            'glossarymanager', 'assetmanager', 'egeriaclient',
            'egeriatech', 'serverops', 'platformservices',
            'projectmanager', 'communitymanager', 'validvaluesmanager',
            'collectionmanager', 'datamanager', 'governancemanager',
            # Common modules
            'pyegeria.admin', 'pyegeria.glossary', 'pyegeria.asset',
            'pyegeria.core', 'pyegeria.utils'
        ]
        
        if any(indicator in query_lower for indicator in pyegeria_indicators):
            logger.info(f"✓ Detected via explicit indicator")
            return True
        
        # Stage 2: Check if asking about a class/methods and if it exists in pyegeria
        class_query_patterns = [
            'what methods', 'methods does', 'methods in', 'methods of',
            'tell me about', 'what is', 'what does', 'how do i use',  # Added "what does"
            'list all', 'list the', 'show all', 'show the', 'get all',  # Added exhaustive patterns
            'show me the', 'show me', 'documentation for',  # Added for follow-ups
            'class', 'manager', 'officer', 'handler', 'service'
        ]
        
        matching_patterns = [p for p in class_query_patterns if p in query_lower]
        print(f"🔍 DETECTION: Query: '{query}'")
        print(f"🔍 DETECTION: Matching patterns: {matching_patterns}")
        if matching_patterns:
            logger.info(f"Query matches class patterns: {matching_patterns}")
            # Do a quick search in pyegeria collection
            try:
                logger.info(f"Searching pyegeria collection for: {query[:50]}")
                results = self.vector_store.search(
                    collection_name=self.collection_name,
                    query_text=query,
                    top_k=3
                )
                logger.info(f"Search returned {len(results)} results")
                if results and len(results) > 0:
                    logger.info(f"Top result score: {results[0].score:.3f}")
                    # If we get good results (score >= 0.25), it's likely a PyEgeria query
                    # Lowered threshold to catch edge cases like ProjectManager
                    if results[0].score >= 0.25:
                        logger.info(f"✓ Detected PyEgeria query via search (score: {results[0].score:.2f})")
                        return True
                    else:
                        logger.info(f"✗ Score too low ({results[0].score:.3f} < 0.25)")
            except Exception as e:
                logger.warning(f"Error in PyEgeria query detection search: {e}")
                import traceback
                logger.warning(traceback.format_exc())
        else:
            logger.info(f"No class query patterns matched")
        
        logger.info(f"✗ Not detected as PyEgeria query")
        return False
    
    def search_pyegeria(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.35,
        use_metadata_filters: bool = True  # Enabled - collection now has scalar fields!
    ) -> List[Dict[str, Any]]:
        """
        Search PyEgeria collection for relevant content with optional metadata filtering.
        
        Args:
            query: Search query
            top_k: Number of results to return
            min_score: Minimum similarity score
            use_metadata_filters: Whether to extract and apply metadata filters
            
        Returns:
            List of search results as dictionaries with metadata
        """
        try:
            # Extract metadata filters from query if enabled
            filter_expr = None
            if use_metadata_filters:
                filters = extract_pyegeria_filters(query)
                if filters:
                    filter_expr = build_combined_filter_expr(filters)
                    logger.info(f"Applying metadata filters: {filter_expr}")
            
            # Search with optional metadata filtering
            search_results = self.vector_store.search(
                collection_name=self.collection_name,
                query_text=query,
                top_k=top_k * 2,  # Get more results to filter by score
                filter_expr=filter_expr
            )
            
            # Convert SearchResult objects to dictionaries and filter by score
            results = []
            for result in search_results:
                if result.score >= min_score:
                    results.append({
                        'id': result.id,
                        'score': result.score,
                        'text': result.text,
                        'metadata': result.metadata
                    })
                    if len(results) >= top_k:
                        break
            
            logger.info(f"Found {len(results)} PyEgeria results for query: {query[:50]}...")
            if filter_expr:
                logger.info(f"  (filtered by: {filter_expr})")
            return results
            
        except Exception as e:
            logger.error(f"Error searching PyEgeria collection: {e}")
            return []
    
    def get_all_class_methods(self, class_name: str) -> List[Dict[str, Any]]:
        """
        Get ALL methods for a specific class using direct database query with metadata filters.
        
        This method uses O(1) metadata filtering instead of semantic search to ensure
        we get ALL methods, not just semantically similar ones.
        
        Args:
            class_name: Name of the class
            
        Returns:
            List of method dictionaries with name, docstring, signature, etc.
        """
        try:
            # Ensure connection exists
            self.vector_store.connect()

            filter_expr = f'class_name == "{class_name}"'
            logger.info(f"Querying all items for class {class_name} with filter: {filter_expr}")

            results = self.vector_store.query_by_filter(
                collection_name=self.collection_name,
                filter_expr=filter_expr,
                output_fields=['method_name', 'element_type', 'metadata'],
                limit=500,
            )
            
            logger.info(f"Direct query returned {len(results)} items for {class_name}")
            
            # Filter for methods only in Python, after the fetch (kept simple —
            # avoids building a compound filter_expr for this one extra condition)
            method_results = [r for r in results if r.get('element_type') == 'method']
            logger.info(f"Filtered to {len(method_results)} methods")
            
            # Convert to standardized format
            methods = []
            for result in method_results:
                metadata = result.get('metadata', {})
                methods.append({
                    'name': result.get('method_name', metadata.get('name', '')),
                    'docstring': metadata.get('docstring', ''),
                    'signature': metadata.get('signature', ''),
                    'file_path': metadata.get('file_path', ''),
                    'is_async': metadata.get('is_async', False),
                    'is_private': metadata.get('is_private', False),
                    'parameters': metadata.get('parameters', []),
                    'return_type': metadata.get('return_type', '')
                })
            
            # Sort by name for consistent ordering
            methods.sort(key=lambda x: x['name'])
            
            logger.info(f"✓ Found {len(methods)} methods for class {class_name}")
            return methods
            
        except Exception as e:
            logger.error(f"Error getting methods for class {class_name}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def is_exhaustive_query(self, query: str) -> bool:
        """
        Detect if query is asking for ALL items (exhaustive list) vs sample/relevant items.
        
        Examples of exhaustive queries:
        - "how many methods does X have?"
        - "what methods are in X?"
        - "list the methods in X"
        - "list all methods in X"
        - "show me all the methods"
        
        Args:
            query: User's query
            
        Returns:
            True if query wants exhaustive list, False if semantic search is appropriate
        """
        query_lower = query.lower()
        
        exhaustive_indicators = [
            'how many',
            'what methods are in',
            'what methods does',
            'list the methods',  # Added: "list the methods in X"
            'list methods',      # Added: "list methods in X"
            'list all',
            'show all',
            'show me all',
            'show the methods',  # Added: "show the methods in X"
            'show methods',      # Added: "show methods in X"
            'list every',
            'all methods',
            'all the methods',
            'complete list',
            'full list',
            'get all methods',   # Added: "get all methods"
            'get the methods'    # Added: "get the methods"
        ]
        
        return any(indicator in query_lower for indicator in exhaustive_indicators)
    
    def extract_class_info(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract class information from search results.
        
        Args:
            results: Search results
            
        Returns:
            Dictionary with class information
        """
        classes = {}
        
        for result in results:
            metadata = result.get('metadata', {})
            element_type = metadata.get('element_type', '')
            
            if element_type == 'class':
                class_name = metadata.get('name', '')
                if class_name and class_name not in classes:
                    classes[class_name] = {
                        'name': class_name,
                        'file_path': metadata.get('file_path', ''),
                        'docstring': metadata.get('docstring', ''),
                        'methods': [],
                        'score': result.get('score', 0.0)
                    }
            elif element_type == 'function' and 'class_name' in metadata:
                class_name = metadata.get('class_name', '')
                method_name = metadata.get('name', '')
                if class_name in classes:
                    classes[class_name]['methods'].append({
                        'name': method_name,
                        'docstring': metadata.get('docstring', ''),
                        'signature': metadata.get('signature', '')
                    })
        
        return classes
    
    def extract_module_info(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract module information from search results.
        
        Args:
            results: Search results
            
        Returns:
            Dictionary with module information
        """
        modules = {}
        
        for result in results:
            metadata = result.get('metadata', {})
            file_path = metadata.get('file_path', '')
            
            if file_path:
                # Extract module path from file path
                if 'pyegeria/' in file_path:
                    module_path = file_path.split('pyegeria/')[1].replace('.py', '').replace('/', '.')
                    module_path = f"pyegeria.{module_path}"
                    
                    if module_path not in modules:
                        modules[module_path] = {
                            'path': module_path,
                            'file_path': file_path,
                            'elements': [],
                            'score': result.get('score', 0.0)
                        }
                    
                    element_type = metadata.get('element_type', '')
                    element_name = metadata.get('name', '')
                    if element_name:
                        modules[module_path]['elements'].append({
                            'type': element_type,
                            'name': element_name,
                            'docstring': metadata.get('docstring', '')[:100]
                        })
        
        return modules
    
    def generate_response(
        self,
        query: str,
        query_result: PyEgeriaQueryResult,
        use_interactive_format: bool = False  # DISABLED - causing issues
    ) -> Dict[str, Any]:
        """
        Generate intelligent response based on query type and search results.
        
        Args:
            query: Original user query
            query_result: Classified query with search results
            use_interactive_format: Whether to use interactive response formatting (DISABLED)
            
        Returns:
            Response dictionary with answer and metadata
        """
        query_type = query_result.query_type
        results = query_result.search_results
        confidence = query_result.confidence
        
        # Interactive handler DISABLED - it was causing generic clarification messages
        # when search returned no results, hiding the real problem
        interactive_handler = None  # Disabled
        
        if not results:
            # No results - provide helpful message
            return {
                'answer': (
                    "I couldn't find specific information about that in the PyEgeria collection. "
                    "Could you rephrase your question or ask about a specific PyEgeria class, "
                    "method, or module?"
                ),
                'sources': [],
                'query_type': query_type,
                'confidence': 0.0
            }
        
        # Build context from search results
        context = self._build_context(results, query_type)
        
        # Generate response using LLM
        prompt = self._build_prompt(query, query_type, context)
        
        # Check if exhaustive query (needs more tokens)
        is_exhaustive = context.startswith('\nAll methods (')
        max_tokens = 3000 if is_exhaustive else 800
        
        print(f"🔍 Using max_tokens={max_tokens} (exhaustive={is_exhaustive})")
        
        try:
            response = self.llm_client.generate(
                prompt=prompt,
                temperature=0.0,  # Zero temperature for maximum factual accuracy
                max_tokens=max_tokens
            )
            
            # Extract sources
            sources = self._extract_sources(results)
            
            # Generate follow-up options if using interactive format
            follow_up_options = []
            if interactive_handler and use_interactive_format:
                # Map internal query_type to QueryType enum
                query_type_map = {
                    'class': QueryType.CONCEPT,
                    'method': QueryType.CODE,
                    'module': QueryType.CONCEPT,
                    'usage': QueryType.TUTORIAL,
                    'example': QueryType.EXAMPLE,
                    'general': QueryType.GENERAL
                }
                mapped_type = query_type_map.get(query_type, QueryType.GENERAL)
                follow_up_options = interactive_handler.get_follow_up_options(mapped_type)
            
            # Add helpful suggestions based on query type
            suggestions = self._generate_suggestions(query_type, results)
            
            # Combine follow-ups and suggestions
            all_options = follow_up_options + suggestions
            
            return {
                'answer': response,
                'sources': sources,
                'query_type': query_type,
                'confidence': confidence,
                'suggestions': suggestions,
                'follow_up_options': follow_up_options,
                'all_options': all_options[:4]  # Limit to 4 total options
            }
            
        except Exception as e:
            logger.error(f"Error generating PyEgeria response: {e}")
            return {
                'answer': f"Error generating response: {str(e)}",
                'sources': [],
                'query_type': query_type,
                'confidence': 0.0
            }
    
    def _build_context(self, results: List[Dict[str, Any]], query_type: str) -> str:
        """Build context string from search results based on query type."""
        context_parts = []
        
        # Check if this is an exhaustive query with many results (all methods for a class)
        if len(results) > 20 and all(r.get('score', 0) == 1.0 for r in results[:5]):
            # This is an exhaustive query - include ALL results
            print(f"🔍 Building context for exhaustive query with {len(results)} results")
            context_parts.append(f"\nAll methods ({len(results)} total):")
            for i, result in enumerate(results, 1):
                metadata = result.get('metadata', {})
                method_name = metadata.get('name', 'unknown')
                docstring = metadata.get('docstring', '')
                context_parts.append(f"{i}. {method_name}: {docstring[:80] if docstring else 'No description'}")
            return '\n'.join(context_parts)
        
        if query_type == 'class':
            classes = self.extract_class_info(results)
            for class_name, class_info in list(classes.items())[:3]:  # Top 3 classes
                context_parts.append(f"\nClass: {class_name}")
                context_parts.append(f"File: {class_info['file_path']}")
                if class_info['docstring']:
                    context_parts.append(f"Description: {class_info['docstring'][:200]}")
                
                # Get ALL methods for this class using comprehensive search
                all_methods = self.get_all_class_methods(class_name)
                if all_methods:
                    method_names = [m['name'] for m in all_methods]
                    context_parts.append(f"Methods ({len(method_names)}): {', '.join(method_names)}")
                    # Include details for top methods
                    for method in all_methods[:10]:  # Show details for first 10
                        if method.get('docstring'):
                            context_parts.append(f"  - {method['name']}: {method['docstring'][:100]}")
                elif class_info['methods']:
                    # Fallback to methods from initial search
                    methods = [m['name'] for m in class_info['methods'][:5]]
                    context_parts.append(f"Key methods: {', '.join(methods)}")
        
        elif query_type == 'module':
            modules = self.extract_module_info(results)
            for module_path, module_info in list(modules.items())[:3]:  # Top 3 modules
                context_parts.append(f"\nModule: {module_path}")
                context_parts.append(f"File: {module_info['file_path']}")
                if module_info['elements']:
                    elements = [f"{e['type']}: {e['name']}" for e in module_info['elements'][:5]]
                    context_parts.append(f"Contains: {', '.join(elements)}")
        
        else:
            # For other query types, include relevant code snippets and documentation
            for i, result in enumerate(results[:5], 1):
                metadata = result.get('metadata', {})
                context_parts.append(f"\n[Result {i}]")
                context_parts.append(f"Type: {metadata.get('element_type', 'unknown')}")
                context_parts.append(f"Name: {metadata.get('name', 'N/A')}")
                context_parts.append(f"File: {metadata.get('file_path', 'N/A')}")
                
                if metadata.get('docstring'):
                    context_parts.append(f"Documentation: {metadata['docstring'][:150]}")
                
                if metadata.get('code'):
                    context_parts.append(f"Code:\n{metadata['code'][:200]}")
        
        return '\n'.join(context_parts)
    
    def _build_prompt(self, query: str, query_type: str, context: str) -> str:
        """Build prompt for LLM based on query type with anti-hallucination safeguards."""
        
        # Check if this is an exhaustive query (context starts with "All methods")
        is_exhaustive = context.startswith('\nAll methods (')
        
        # Special instructions for exhaustive queries
        if is_exhaustive:
            print(f"🔍 Using exhaustive query prompt")
            base_prompt = f"""You are an expert on the PyEgeria Python library for Egeria.

User Query: {query}

Complete Method List:
{context}

CRITICAL ANTI-HALLUCINATION RULES:
1. ONLY use methods listed in the context above - NEVER invent or add methods
2. You MUST list ALL {context.split('(')[1].split(' ')[0]} methods shown above
3. Do NOT add methods from your training data or make assumptions
4. If a method is not in the list above, it does NOT exist in this class
5. Create a numbered list with EVERY method from the context
6. Format: "1. method_name: brief description from context"
7. After listing all methods, you may add 1-2 detailed examples ONLY using methods from the list

Answer with the COMPLETE list using ONLY the methods shown above:"""
            return base_prompt
        
        # Special instructions for class queries
        if query_type == 'class':
            base_prompt = f"""You are an expert on the PyEgeria Python library for Egeria.

User Query: {query}
Query Type: {query_type}

Relevant PyEgeria Information:
{context}

CRITICAL ANTI-HALLUCINATION RULES - READ CAREFULLY:
1. ONLY use information from the context above - NEVER add external knowledge
2. If a method is not explicitly listed in the context above, it does NOT exist - do NOT mention it
3. Do NOT invent method names, parameters, descriptions, or behaviors
4. Do NOT make assumptions about what methods might exist
5. ALWAYS cite the source: "From the context above..." or "According to the provided information..."
6. If information is missing, explicitly state: "This information is not in the provided context"
7. Every method you mention MUST be explicitly shown in the context above

Instructions for Class Method Queries:
1. FIRST: Explain what the class does (ONLY from context, 2-3 sentences)
2. THEN: Create a complete table listing ALL methods shown in the context above
   - Use markdown table format: | Method Name | Description |
   - List EVERY method mentioned in the "Methods" section
   - Keep descriptions brief (one line each from context)
   - Do NOT add methods not in the context
3. THEN: Provide detailed examples for 2-3 key methods (ONLY using context)
   - Show method signatures from context
   - Explain parameters from context
   - Include usage examples if provided in context
4. FINALLY: Note that PyEgeria provides both sync and async versions
   - Mention hey_egeria CLI and Dr. Egeria alternatives

Answer (provide ONLY the explanation and method table, NO follow-up questions):"""
        else:
            base_prompt = f"""You are an expert on the PyEgeria Python library for Egeria.

User Query: {query}
Query Type: {query_type}

Relevant PyEgeria Information:
{context}

CRITICAL ANTI-HALLUCINATION RULES - READ CAREFULLY:
1. ONLY use information from the context above - NEVER add external knowledge
2. If information is not in the context, explicitly state: "This is not covered in the provided context"
3. ALWAYS cite specific sources from the context
4. Do NOT make assumptions about features, APIs, or behaviors not mentioned
5. If you're uncertain, say so - never guess or fabricate
6. Every method, class, or feature you mention MUST be explicitly shown in the context above

Instructions:
- Provide a clear, accurate answer based ONLY on the PyEgeria information above
- Include specific class names, method names, and file paths when relevant
- If showing code, use proper Python syntax from the context
- Mention that PyEgeria provides both synchronous and asynchronous clients
- Note that operations may also be available via hey_egeria CLI or Dr. Egeria
- Be concise but complete

Answer (provide ONLY the answer, NO follow-up questions):"""
        
        return base_prompt
    
    def _extract_sources(self, results: List[Dict[str, Any]]) -> List[str]:
        """Extract unique source file paths from results."""
        sources = []
        seen = set()
        
        for result in results[:5]:  # Top 5 sources
            metadata = result.get('metadata', {})
            file_path = metadata.get('file_path', '')
            element_name = metadata.get('name', '')
            
            if file_path and file_path not in seen:
                source = file_path
                if element_name:
                    source = f"{file_path} ({element_name})"
                sources.append(source)
                seen.add(file_path)
        
        return sources
    
    def _generate_suggestions(self, query_type: str, results: List[Dict[str, Any]]) -> List[str]:
        """Generate helpful suggestions based on query type and results."""
        suggestions = []
        
        if query_type == 'class':
            classes = self.extract_class_info(results)
            if len(classes) > 1:
                other_classes = [name for name in list(classes.keys())[1:4]]
                if other_classes:
                    suggestions.append(f"Related classes: {', '.join(other_classes)}")
        
        elif query_type == 'method':
            suggestions.append("Would you like to see a complete code example?")
            suggestions.append("Ask about error handling or best practices")
        
        elif query_type == 'usage':
            suggestions.append("Would you like to see test examples from the tests/ directory?")
            suggestions.append("Ask about async vs sync client usage")
        
        elif query_type == 'example':
            suggestions.append("Check the tests/ directory for more examples")
            suggestions.append("Ask about specific use cases or scenarios")
        
        return suggestions
    
    def answer(self, query: str) -> Dict[str, Any]:
        """
        Answer a PyEgeria-related query.
        
        Args:
            query: User's question about PyEgeria
            
        Returns:
            Response dictionary with answer, sources, and metadata
        """
        print(f"🔍 PyEgeria Agent.answer() called with query: {query[:100]}...")
        logger.info(f"🔍 PyEgeria Agent.answer() called with query: {query[:100]}...")
        
        # Classify query type
        query_type = self.classify_query(query)
        print(f"📋 Classified as: {query_type}")
        logger.info(f"📋 Classified as: {query_type}")
        
        # Initialize variables (may be set in different code paths)
        results = []
        confidence = 0.0
        
        # Check if this is an exhaustive query (wants ALL items, not just relevant ones)
        is_exhaustive = self.is_exhaustive_query(query)
        print(f"🔎 Exhaustive query check: {is_exhaustive}")
        logger.info(f"🔎 Exhaustive query check: {is_exhaustive}")
        
        if is_exhaustive:
            print("✓ Detected exhaustive query - using direct database query")
            logger.info("Detected exhaustive query - using direct database query")
            
            # Extract class name from query
            from advisor.metadata_filters import extract_pyegeria_filters
            filters = extract_pyegeria_filters(query)
            class_name = filters.get('class_name')
            
            if class_name:
                # Get ALL methods for this class using direct database query
                print(f"🔍 Calling get_all_class_methods('{class_name}')...")
                all_methods = self.get_all_class_methods(class_name)
                print(f"🔍 get_all_class_methods() returned {len(all_methods) if all_methods else 0} methods")
                
                if all_methods:
                    # For exhaustive queries, format as simple numbered list
                    # (LLM times out with 45+ methods, and tables don't render well in Rich panels)
                    logger.info(f"Formatting {len(all_methods)} methods as list (bypassing LLM)")
                    
                    # Build simple numbered list
                    lines = [
                        f"All {len(all_methods)} Methods in {class_name}",
                        "=" * 60,
                        ""
                    ]
                    
                    for i, m in enumerate(all_methods, 1):
                        name = m.get('name', 'unknown')
                        doc = m.get('docstring', 'No description')
                        # Truncate long docstrings
                        if len(doc) > 70:
                            doc = doc[:67] + "..."
                        
                        # Format: number. method_name - description
                        lines.append(f"{i:2d}. {name}")
                        if doc and doc != 'No description':
                            lines.append(f"    {doc}")
                        lines.append("")  # Blank line between methods
                    
                    lines.extend([
                        "=" * 60,
                        "",
                        f"Complete list of all {len(all_methods)} methods in {class_name}.",
                        "Ask about any specific method for detailed documentation."
                    ])
                    
                    answer = '\n'.join(lines)
                    
                    logger.info(f"Returning formatted list with {len(answer)} characters, bypassing LLM completely")
                    
                    # Return formatted response directly
                    return {
                        'answer': answer,
                        'sources': [f"pyegeria.omvs.project_manager.{class_name}"],
                        'query_type': 'exhaustive',
                        'confidence': 1.0,
                        'suggestions': [
                            f"Ask about a specific method: 'How do I use {all_methods[0]['name']}?'",
                            "Request code examples for any method"
                        ]
                    }
                # If no methods found, fall through to semantic search below
            else:
                # Fallback to semantic search if we can't extract class name
                logger.warning("Could not extract class name from exhaustive query, falling back to semantic search")
                results = self.search_pyegeria(query, top_k=100)  # Higher top_k for exhaustive queries
                confidence = 0.5
        else:
            # Normal semantic search for non-exhaustive queries
            results = self.search_pyegeria(query)
            
            # Calculate confidence based on results
            confidence = 0.0
            if results:
                # Average of top 3 scores
                top_scores = [r.get('score', 0.0) for r in results[:3]]
                confidence = sum(top_scores) / len(top_scores) if top_scores else 0.0
        
        # Create query result
        query_result = PyEgeriaQueryResult(
            query_type=query_type,
            search_results=results,
            confidence=confidence
        )
        
        # Generate response
        response = self.generate_response(query, query_result)
        
        logger.info(f"Generated PyEgeria response with confidence: {confidence:.2f}")
        return response


# Singleton instance
_pyegeria_agent: Optional[PyEgeriaAgent] = None


def get_pyegeria_agent() -> PyEgeriaAgent:
    """Get or create singleton PyEgeria agent instance."""
    global _pyegeria_agent
    if _pyegeria_agent is None:
        _pyegeria_agent = PyEgeriaAgent()
    return _pyegeria_agent


def reset_pyegeria_agent() -> None:
    """Reset the singleton PyEgeria agent instance (for testing/debugging)."""
    global _pyegeria_agent
    _pyegeria_agent = None
    logger.info("PyEgeria agent singleton reset")