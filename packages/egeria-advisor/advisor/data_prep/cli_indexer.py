"""
CLI Command Indexer for indexing command metadata into vector store.

This module takes extracted CLI commands and creates searchable documents
with embeddings for the vector store.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from loguru import logger

from advisor.embeddings import EmbeddingGenerator
from advisor.vector_store import VectorStoreManager, SearchResult, get_vector_store
from advisor.config import settings


class CLICommandIndexer:
    """Index CLI commands into vector store for semantic search."""
    
    def __init__(
        self,
        vector_store: Optional[VectorStoreManager] = None,
        embedding_generator: Optional[EmbeddingGenerator] = None,
        collection_name: str = "cli_commands"
    ):
        """
        Initialize CLI command indexer.
        
        Args:
            vector_store: Vector store manager instance
            embedding_generator: Embedding generator instance
            collection_name: Name of collection to store commands
        """
        self.vector_store = vector_store or get_vector_store()
        self.embedding_generator = embedding_generator or EmbeddingGenerator()
        self.collection_name = collection_name
        
    def index_commands(
        self,
        commands: Dict[str, Dict[str, Any]],
        batch_size: int = 50
    ) -> Dict[str, Any]:
        """
        Index CLI commands into vector store.
        
        Args:
            commands: Dictionary of command metadata
            batch_size: Number of commands to index per batch
            
        Returns:
            Dictionary with indexing statistics
        """
        logger.info(f"Indexing {len(commands)} CLI commands into {self.collection_name}")
        
        # Ensure collection exists
        self._ensure_collection()
        
        # Convert commands to documents
        documents = self._commands_to_documents(commands)
        logger.info(f"Created {len(documents)} documents from commands")
        
        # Index in batches
        total_indexed = 0
        failed = 0
        
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            try:
                self._index_batch(batch)
                total_indexed += len(batch)
                logger.info(f"Indexed batch {i//batch_size + 1}: {len(batch)} documents")
            except Exception as e:
                logger.error(f"Failed to index batch {i//batch_size + 1}: {e}")
                failed += len(batch)
        
        stats = {
            'total_commands': len(commands),
            'total_documents': len(documents),
            'indexed': total_indexed,
            'failed': failed,
            'collection': self.collection_name
        }
        
        logger.info(f"Indexing complete: {stats}")
        return stats
    
    def _ensure_collection(self):
        """Ensure the CLI commands collection exists."""
        try:
            # Connect to vector store
            self.vector_store.connect()
            
            # Create collection (will skip if exists)
            self.vector_store.create_collection(
                collection_name=self.collection_name,
                description="CLI command metadata for semantic search"
            )
            
            # Create index for fast search
            self.vector_store.create_index(
                collection_name=self.collection_name,
                index_type="IVF_FLAT",
                metric_type="L2"
            )
            
            logger.info(f"Collection {self.collection_name} ready")
                
        except Exception as e:
            logger.error(f"Error ensuring collection: {e}")
            raise
    
    def _commands_to_documents(
        self,
        commands: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Convert command metadata to searchable documents.
        
        Args:
            commands: Dictionary of command metadata
            
        Returns:
            List of document dictionaries
        """
        documents = []
        
        for cmd_name, cmd_data in commands.items():
            # Create main command document
            doc = self._create_command_document(cmd_name, cmd_data)
            documents.append(doc)
            
            # Create parameter documents for commands with many parameters
            if len(cmd_data.get('parameters', [])) > 5:
                param_docs = self._create_parameter_documents(cmd_name, cmd_data)
                documents.extend(param_docs)
        
        return documents
    
    def _create_command_document(
        self,
        cmd_name: str,
        cmd_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a searchable document for a command.
        
        Args:
            cmd_name: Command name
            cmd_data: Command metadata
            
        Returns:
            Document dictionary
        """
        # Build searchable text
        text_parts = [
            f"Command: {cmd_name}",
            f"Type: {cmd_data.get('type', 'unknown')}",
            f"Category: {cmd_data.get('category', 'unknown')}"
        ]
        
        # Add description
        description = cmd_data.get('description', '')
        if description:
            text_parts.append(f"Description: {description}")
        
        # Add docstring if different from description
        docstring = cmd_data.get('docstring', '')
        if docstring and docstring != description:
            text_parts.append(f"Details: {docstring}")
        
        # Add help text
        help_text = cmd_data.get('help_text', '')
        if help_text and help_text not in [description, docstring]:
            text_parts.append(f"Help: {help_text}")
        
        # Add parameter summary
        parameters = cmd_data.get('parameters', [])
        if parameters:
            param_names = [p.get('name', '') for p in parameters]
            text_parts.append(f"Parameters: {', '.join(param_names)}")
            
            # Add required parameters
            required = [p.get('name', '') for p in parameters if p.get('required')]
            if required:
                text_parts.append(f"Required: {', '.join(required)}")
        
        # Add usage example for dr_egeria commands
        usage = cmd_data.get('usage', '')
        if usage:
            text_parts.append(f"Usage: {usage}")
        
        searchable_text = "\n".join(text_parts)
        
        # Extract command structure for better filtering
        # Parse command name to get main command and subcommand
        parts = cmd_name.split()
        main_command = parts[0] if parts else cmd_name
        subcommand = ' '.join(parts[1:]) if len(parts) > 1 else ''
        
        # Get options and flags from parameters
        options = []
        flags = []
        required_options = []
        
        for param in parameters:
            param_name = param.get('name', '')
            if param.get('is_flag', False):
                flags.append(param_name)
            else:
                options.append(param_name)
                if param.get('required', False):
                    required_options.append(param_name)
        
        # Create document with enhanced metadata
        document = {
            'text': searchable_text,
            'metadata': {
                # Basic identification
                'command_name': cmd_name,
                'command_type': cmd_data.get('type', 'unknown'),
                'category': cmd_data.get('category', 'unknown'),
                'description': description,
                
                # Command structure (NEW - matches design)
                'main_command': main_command,  # e.g., "hey_egeria" or "dr_egeria"
                'subcommand': subcommand,  # e.g., "platform status"
                'full_command': cmd_name,  # Full command string
                
                # Parameters (NEW - structured lists)
                'options': ','.join(options),  # Comma-separated options
                'flags': ','.join(flags),  # Comma-separated flags
                'required_options': ','.join(required_options),  # Required options
                
                # Code location
                'module_path': cmd_data.get('module_path', ''),
                'function_name': cmd_data.get('function_name', ''),
                'entry_point': cmd_data.get('entry_point', ''),
                
                # Statistics
                'parameter_count': len(parameters),
                'has_required_params': any(p.get('required') for p in parameters),
                
                # Document type
                'doc_type': 'command_overview',
                'collection': 'cli_commands'
            }
        }
        
        # Add full command data as JSON for retrieval
        document['metadata']['command_data'] = json.dumps(cmd_data)
        
        return document
    
    def _create_parameter_documents(
        self,
        cmd_name: str,
        cmd_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Create separate documents for command parameters.
        
        For commands with many parameters, create focused documents
        for better parameter-specific search.
        
        Args:
            cmd_name: Command name
            cmd_data: Command metadata
            
        Returns:
            List of parameter documents
        """
        documents = []
        parameters = cmd_data.get('parameters', [])
        
        # Group parameters by type/purpose
        param_groups = self._group_parameters(parameters)
        
        for group_name, group_params in param_groups.items():
            text_parts = [
                f"Command: {cmd_name}",
                f"Parameter Group: {group_name}"
            ]
            
            for param in group_params:
                param_text = f"Parameter: {param.get('name', '')}"
                if param.get('help'):
                    param_text += f" - {param['help']}"
                if param.get('type'):
                    param_text += f" (type: {param['type']})"
                if param.get('default') is not None:
                    param_text += f" (default: {param['default']})"
                if param.get('required'):
                    param_text += " [REQUIRED]"
                
                text_parts.append(param_text)
            
            document = {
                'text': "\n".join(text_parts),
                'metadata': {
                    'command_name': cmd_name,
                    'type': cmd_data.get('type', 'unknown'),
                    'category': cmd_data.get('category', 'unknown'),
                    'parameter_group': group_name,
                    'parameter_count': len(group_params),
                    'doc_type': 'command_parameters',
                    '_collection': 'cli_commands'
                }
            }
            
            documents.append(document)
        
        return documents
    
    def _group_parameters(
        self,
        parameters: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group parameters by type/purpose for better organization.
        
        Args:
            parameters: List of parameter dictionaries
            
        Returns:
            Dictionary of parameter groups
        """
        groups = {
            'required': [],
            'connection': [],
            'optional': []
        }
        
        for param in parameters:
            param_name = param.get('name', '').lower()
            
            if param.get('required'):
                groups['required'].append(param)
            elif any(keyword in param_name for keyword in ['server', 'url', 'userid', 'password', 'timeout']):
                groups['connection'].append(param)
            else:
                groups['optional'].append(param)
        
        # Remove empty groups
        return {k: v for k, v in groups.items() if v}
    
    def _index_batch(self, documents: List[Dict[str, Any]]):
        """
        Index a batch of documents.
        
        Args:
            documents: List of document dictionaries
        """
        # Extract texts and metadata
        texts = [doc['text'] for doc in documents]
        metadata_list = [doc['metadata'] for doc in documents]
        
        # Generate IDs
        ids = [f"cli_cmd_{i}_{doc['metadata'].get('command_name', 'unknown')}"
               for i, doc in enumerate(documents)]
        
        # Insert using vector store's insert_data method
        # This will automatically generate embeddings
        self.vector_store.insert_data(
            collection_name=self.collection_name,
            texts=texts,
            ids=ids,
            metadata=metadata_list
        )
    
    def search_commands(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        filter_expr: Optional[str] = None
    ) -> List[SearchResult]:
        """
        Search for commands using semantic search with optional metadata filtering.
        
        Args:
            query: Search query
            top_k: Number of results to return
            filters: Optional metadata filters (dict) - deprecated, use filter_expr
            filter_expr: Optional filter expression string
            
        Returns:
            List of SearchResult objects with matching commands
        """
        # Search using vector store's search method
        results = self.vector_store.search(
            collection_name=self.collection_name,
            query_text=query,
            top_k=top_k,
            filters=filters,
            filter_expr=filter_expr
        )
        
        return results


def index_cli_commands_from_file(
    commands_file: Path,
    collection_name: str = "cli_commands"
) -> Dict[str, Any]:
    """
    Convenience function to index commands from JSON file.
    
    Args:
        commands_file: Path to CLI commands JSON file
        collection_name: Name of collection to create
        
    Returns:
        Indexing statistics
    """
    logger.info(f"Loading commands from {commands_file}")
    
    with open(commands_file, 'r') as f:
        commands = json.load(f)
    
    indexer = CLICommandIndexer(collection_name=collection_name)
    stats = indexer.index_commands(commands)
    
    return stats