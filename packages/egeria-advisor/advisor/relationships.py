"""
Relationship extraction and graph building for code elements.

This module extracts and manages relationships between code elements:
- Inheritance (class A extends class B)
- Method ownership (method M belongs to class C)
- Import relationships (module A imports from module B)
- Call relationships (function A calls function B)
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
from collections import defaultdict

from loguru import logger

from advisor.config import settings


class RelationshipGraph:
    """Manages code element relationships as a graph structure."""
    
    def __init__(self):
        """Initialize empty relationship graph."""
        self.nodes: Dict[str, Dict[str, Any]] = {}  # node_id -> node_data
        self.edges: Dict[str, List[Tuple[str, str]]] = defaultdict(list)  # edge_type -> [(from, to)]
        self.reverse_edges: Dict[str, List[Tuple[str, str]]] = defaultdict(list)  # edge_type -> [(to, from)]
        
    def add_node(self, node_id: str, node_type: str, name: str, file_path: str, **kwargs):
        """Add a node to the graph."""
        self.nodes[node_id] = {
            "type": node_type,
            "name": name,
            "file_path": file_path,
            **kwargs
        }
        
    def add_edge(self, from_id: str, to_id: str, edge_type: str):
        """Add a directed edge to the graph."""
        self.edges[edge_type].append((from_id, to_id))
        self.reverse_edges[edge_type].append((to_id, from_id))
        
    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get node data by ID."""
        return self.nodes.get(node_id)
    
    def get_outgoing_edges(self, node_id: str, edge_type: Optional[str] = None) -> List[Tuple[str, str]]:
        """Get all outgoing edges from a node."""
        if edge_type:
            return [(f, t) for f, t in self.edges[edge_type] if f == node_id]
        else:
            result = []
            for edges in self.edges.values():
                result.extend([(f, t) for f, t in edges if f == node_id])
            return result
    
    def get_incoming_edges(self, node_id: str, edge_type: Optional[str] = None) -> List[Tuple[str, str]]:
        """Get all incoming edges to a node."""
        if edge_type:
            return [(t, f) for t, f in self.reverse_edges[edge_type] if t == node_id]
        else:
            result = []
            for edges in self.reverse_edges.values():
                result.extend([(t, f) for t, f in edges if t == node_id])
            return result
    
    def find_path(self, from_id: str, to_id: str, max_depth: int = 5) -> Optional[List[str]]:
        """Find shortest path between two nodes using BFS."""
        if from_id == to_id:
            return [from_id]
        
        visited = {from_id}
        queue = [(from_id, [from_id])]
        
        while queue:
            current, path = queue.pop(0)
            
            if len(path) > max_depth:
                continue
            
            # Get all outgoing edges
            for _, next_id in self.get_outgoing_edges(current):
                if next_id == to_id:
                    return path + [next_id]
                
                if next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, path + [next_id]))
        
        return None
    
    def get_related_nodes(self, node_id: str, max_depth: int = 2) -> Set[str]:
        """Get all nodes related to a given node within max_depth."""
        related = {node_id}
        current_level = {node_id}
        
        for _ in range(max_depth):
            next_level = set()
            for node in current_level:
                # Add nodes from outgoing edges
                for _, to_id in self.get_outgoing_edges(node):
                    if to_id not in related:
                        next_level.add(to_id)
                        related.add(to_id)
                
                # Add nodes from incoming edges
                for _, from_id in self.get_incoming_edges(node):
                    if from_id not in related:
                        next_level.add(from_id)
                        related.add(from_id)
            
            current_level = next_level
            if not current_level:
                break
        
        return related
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert graph to dictionary for serialization."""
        return {
            "nodes": self.nodes,
            "edges": {k: list(v) for k, v in self.edges.items()},
            "stats": {
                "total_nodes": len(self.nodes),
                "total_edges": sum(len(v) for v in self.edges.values()),
                "edge_types": list(self.edges.keys())
            }
        }


class RelationshipExtractor:
    """Extracts relationships from code elements."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize relationship extractor."""
        self.cache_dir = cache_dir or settings.advisor_cache_dir
        self.graph = RelationshipGraph()
        
    def _load_code_elements(self) -> List[Dict[str, Any]]:
        """Load code elements from cache."""
        code_file = self.cache_dir / "code_elements.json"
        if not code_file.exists():
            logger.error(f"Code elements file not found: {code_file}")
            return []
        
        logger.info(f"Loading code elements from {code_file}")
        with open(code_file, 'r') as f:
            elements = json.load(f)
        
        logger.info(f"Loaded {len(elements)} code elements")
        return elements
    
    def _extract_imports(self, body: str) -> List[str]:
        """Extract import statements from code body."""
        imports = []
        
        # Match: import module
        # Match: from module import ...
        import_pattern = r'(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))'
        
        for match in re.finditer(import_pattern, body):
            module = match.group(1) or match.group(2)
            if module:
                imports.append(module)
        
        return imports
    
    def _extract_function_calls(self, body: str) -> List[str]:
        """Extract function/method calls from code body."""
        calls = []
        
        # Match: function_name(
        # Match: object.method_name(
        call_pattern = r'(?:^|\s|=|\()([\w.]+)\s*\('
        
        for match in re.finditer(call_pattern, body):
            call = match.group(1)
            if call and not call.startswith('_'):  # Skip private
                calls.append(call)
        
        return calls
    
    def build_graph(self) -> RelationshipGraph:
        """Build relationship graph from code elements."""
        logger.info("Building relationship graph...")
        
        elements = self._load_code_elements()
        
        # First pass: Add all nodes
        logger.info("Adding nodes to graph...")
        for element in elements:
            node_id = f"{element['file_path']}::{element['name']}"
            self.graph.add_node(
                node_id=node_id,
                node_type=element['type'],
                name=element['name'],
                file_path=element['file_path'],
                line_number=element['line_number'],
                parent_class=element.get('parent_class')
            )
        
        logger.info(f"Added {len(self.graph.nodes)} nodes")
        
        # Second pass: Add edges
        logger.info("Adding edges to graph...")
        edge_count = 0
        
        for element in elements:
            node_id = f"{element['file_path']}::{element['name']}"
            
            # 1. Inheritance relationships (for classes)
            if element['type'] == 'class' and element.get('body'):
                # Extract base classes from class definition
                class_def_match = re.search(r'class\s+\w+\s*\((.*?)\):', element['signature'])
                if class_def_match:
                    bases = class_def_match.group(1).split(',')
                    for base in bases:
                        base = base.strip()
                        if base and base != 'object':
                            # Try to find the base class node
                            for other in elements:
                                if other['type'] == 'class' and other['name'] == base:
                                    base_id = f"{other['file_path']}::{other['name']}"
                                    self.graph.add_edge(node_id, base_id, "inherits")
                                    edge_count += 1
                                    break
            
            # 2. Method ownership (methods belong to classes)
            if element['type'] == 'method' and element.get('parent_class'):
                parent_class = element['parent_class']
                # Find parent class node
                for other in elements:
                    if other['type'] == 'class' and other['name'] == parent_class and other['file_path'] == element['file_path']:
                        parent_id = f"{other['file_path']}::{other['name']}"
                        self.graph.add_edge(node_id, parent_id, "belongs_to")
                        edge_count += 1
                        break
            
            # 3. Import relationships
            if element.get('body'):
                imports = self._extract_imports(element['body'])
                for imported_module in imports:
                    # Create a module node if it doesn't exist
                    module_id = f"module::{imported_module}"
                    if module_id not in self.graph.nodes:
                        self.graph.add_node(
                            node_id=module_id,
                            node_type="module",
                            name=imported_module,
                            file_path="external"
                        )
                    self.graph.add_edge(node_id, module_id, "imports")
                    edge_count += 1
            
            # 4. Function call relationships
            if element.get('body'):
                calls = self._extract_function_calls(element['body'])
                for called_func in calls:
                    # Try to find the called function
                    for other in elements:
                        if other['name'] == called_func or other['name'].endswith(f".{called_func}"):
                            called_id = f"{other['file_path']}::{other['name']}"
                            self.graph.add_edge(node_id, called_id, "calls")
                            edge_count += 1
                            break
        
        logger.info(f"Added {edge_count} edges")
        logger.success(f"Graph built: {len(self.graph.nodes)} nodes, {edge_count} edges")
        
        return self.graph
    
    def save_graph(self, output_file: Optional[Path] = None):
        """Save graph to JSON file."""
        if output_file is None:
            output_file = self.cache_dir / "relationships.json"
        
        logger.info(f"Saving relationship graph to {output_file}")
        
        with open(output_file, 'w') as f:
            json.dump(self.graph.to_dict(), f, indent=2)
        
        logger.success(f"Saved relationship graph to {output_file}")
    
    def load_graph(self, input_file: Optional[Path] = None) -> RelationshipGraph:
        """Load graph from JSON file."""
        if input_file is None:
            input_file = self.cache_dir / "relationships.json"
        
        if not input_file.exists():
            logger.warning(f"Relationship graph file not found: {input_file}")
            return self.graph
        
        logger.info(f"Loading relationship graph from {input_file}")
        
        with open(input_file, 'r') as f:
            data = json.load(f)
        
        # Reconstruct graph
        self.graph = RelationshipGraph()
        
        # Add nodes
        for node_id, node_data in data['nodes'].items():
            self.graph.nodes[node_id] = node_data
        
        # Add edges
        for edge_type, edges in data['edges'].items():
            for from_id, to_id in edges:
                self.graph.add_edge(from_id, to_id, edge_type)
        
        logger.success(f"Loaded relationship graph: {len(self.graph.nodes)} nodes, {data['stats']['total_edges']} edges")
        
        return self.graph


class RelationshipQueryHandler:
    """Handles natural language queries about code relationships."""
    
    def __init__(self, extractor: Optional[RelationshipExtractor] = None):
        """Initialize relationship query handler."""
        self.extractor = extractor or get_relationship_extractor()
        self.graph = self.extractor.graph
    
    def _find_node_by_name(self, name: str) -> Optional[str]:
        """Find a node ID by name (case-insensitive partial match)."""
        name_lower = name.lower()
        
        # Try exact match first
        for node_id, node_data in self.graph.nodes.items():
            if node_data['name'].lower() == name_lower:
                return node_id
        
        # Try partial match
        for node_id, node_data in self.graph.nodes.items():
            if name_lower in node_data['name'].lower():
                return node_id
        
        return None
    
    def are_related(self, name1: str, name2: str) -> Dict[str, Any]:
        """Check if two code elements are related."""
        node1_id = self._find_node_by_name(name1)
        node2_id = self._find_node_by_name(name2)
        
        if not node1_id:
            return {
                "related": False,
                "reason": f"Could not find code element: {name1}"
            }
        
        if not node2_id:
            return {
                "related": False,
                "reason": f"Could not find code element: {name2}"
            }
        
        # Find path between nodes
        path = self.graph.find_path(node1_id, node2_id)
        
        if path:
            # Get node names for the path
            path_names = []
            for node_id in path:
                node = self.graph.get_node(node_id)
                if node:
                    path_names.append(node['name'])
            
            return {
                "related": True,
                "path": path_names,
                "distance": len(path) - 1,
                "node1": self.graph.get_node(node1_id),
                "node2": self.graph.get_node(node2_id)
            }
        else:
            return {
                "related": False,
                "reason": f"No relationship found between {name1} and {name2}",
                "node1": self.graph.get_node(node1_id),
                "node2": self.graph.get_node(node2_id)
            }
    
    def get_relationships(self, name: str, relationship_type: Optional[str] = None) -> Dict[str, Any]:
        """Get all relationships for a code element."""
        node_id = self._find_node_by_name(name)
        
        if not node_id:
            return {
                "found": False,
                "reason": f"Could not find code element: {name}"
            }
        
        node = self.graph.get_node(node_id)
        
        # Get outgoing edges
        outgoing = self.graph.get_outgoing_edges(node_id, relationship_type)
        outgoing_names = []
        for _, to_id in outgoing:
            to_node = self.graph.get_node(to_id)
            if to_node:
                outgoing_names.append({
                    "name": to_node['name'],
                    "type": to_node['type'],
                    "file": to_node['file_path']
                })
        
        # Get incoming edges
        incoming = self.graph.get_incoming_edges(node_id, relationship_type)
        incoming_names = []
        for _, from_id in incoming:
            from_node = self.graph.get_node(from_id)
            if from_node:
                incoming_names.append({
                    "name": from_node['name'],
                    "type": from_node['type'],
                    "file": from_node['file_path']
                })
        
        return {
            "found": True,
            "node": node,
            "outgoing": outgoing_names,
            "incoming": incoming_names,
            "total_outgoing": len(outgoing_names),
            "total_incoming": len(incoming_names)
        }
    
    def answer_relationship_query(self, query: str) -> str:
        """Answer a natural language query about relationships."""
        query_lower = query.lower()
        
        # Pattern: "is X related to Y"
        if "is" in query_lower and "related to" in query_lower:
            # Extract names
            parts = query_lower.split("related to")
            if len(parts) == 2:
                name1 = parts[0].replace("is", "").strip()
                name2 = parts[1].strip().rstrip("?")
                
                result = self.are_related(name1, name2)
                
                if result["related"]:
                    path_str = " → ".join(result["path"])
                    return f"**Yes**, {name1} and {name2} are related.\n\n**Relationship path:** {path_str}\n**Distance:** {result['distance']} steps"
                else:
                    return f"**No**, {name1} and {name2} are not directly related.\n\n{result.get('reason', '')}"
        
        # Pattern: "what does X call" or "what calls X"
        if "what does" in query_lower and "call" in query_lower:
            # Extract name
            name = query_lower.replace("what does", "").replace("call", "").strip().rstrip("?")
            result = self.get_relationships(name, "calls")
            
            if result["found"]:
                if result["total_outgoing"] > 0:
                    calls_list = "\n".join([f"  - {r['name']} ({r['type']})" for r in result["outgoing"][:10]])
                    return f"**{name}** calls {result['total_outgoing']} functions/methods:\n\n{calls_list}"
                else:
                    return f"**{name}** does not call any other functions/methods."
            else:
                return result.get("reason", f"Could not find {name}")
        
        if "what calls" in query_lower:
            # Extract name
            name = query_lower.replace("what calls", "").strip().rstrip("?")
            result = self.get_relationships(name, "calls")
            
            if result["found"]:
                if result["total_incoming"] > 0:
                    callers_list = "\n".join([f"  - {r['name']} ({r['type']})" for r in result["incoming"][:10]])
                    return f"**{name}** is called by {result['total_incoming']} functions/methods:\n\n{callers_list}"
                else:
                    return f"**{name}** is not called by any other functions/methods."
            else:
                return result.get("reason", f"Could not find {name}")
        
        # Pattern: "what imports X" or "what does X import"
        if "what imports" in query_lower:
            name = query_lower.replace("what imports", "").strip().rstrip("?")
            result = self.get_relationships(name, "imports")
            
            if result["found"]:
                if result["total_incoming"] > 0:
                    importers_list = "\n".join([f"  - {r['name']} ({r['type']})" for r in result["incoming"][:10]])
                    return f"**{name}** is imported by {result['total_incoming']} modules:\n\n{importers_list}"
                else:
                    return f"**{name}** is not imported by any modules."
            else:
                return result.get("reason", f"Could not find {name}")
        
        if "what does" in query_lower and "import" in query_lower:
            name = query_lower.replace("what does", "").replace("import", "").strip().rstrip("?")
            result = self.get_relationships(name, "imports")
            
            if result["found"]:
                if result["total_outgoing"] > 0:
                    imports_list = "\n".join([f"  - {r['name']}" for r in result["outgoing"][:10]])
                    return f"**{name}** imports {result['total_outgoing']} modules:\n\n{imports_list}"
                else:
                    return f"**{name}** does not import any modules."
            else:
                return result.get("reason", f"Could not find {name}")
        
        # Pattern: "what methods belong to X"
        if "what methods" in query_lower and "belong" in query_lower:
            name = query_lower.replace("what methods", "").replace("belong to", "").replace("belong", "").strip().rstrip("?")
            result = self.get_relationships(name, "belongs_to")
            
            if result["found"]:
                if result["total_incoming"] > 0:
                    methods_list = "\n".join([f"  - {r['name']}" for r in result["incoming"][:20]])
                    more = f"\n  ... and {result['total_incoming'] - 20} more" if result['total_incoming'] > 20 else ""
                    return f"**{name}** has {result['total_incoming']} methods:\n\n{methods_list}{more}"
                else:
                    return f"**{name}** has no methods."
            else:
                return result.get("reason", f"Could not find {name}")
        
        return "I don't understand that relationship query. Try asking:\n- 'Is X related to Y?'\n- 'What does X call?'\n- 'What calls X?'\n- 'What does X import?'\n- 'What methods belong to X?'"


# Singleton instances
_relationship_extractor: Optional[RelationshipExtractor] = None
_relationship_query_handler: Optional[RelationshipQueryHandler] = None


def get_relationship_extractor() -> RelationshipExtractor:
    """Get or create singleton relationship extractor."""
    global _relationship_extractor
    if _relationship_extractor is None:
        _relationship_extractor = RelationshipExtractor()
        # Try to load existing graph
        _relationship_extractor.load_graph()
    return _relationship_extractor


def get_relationship_query_handler() -> RelationshipQueryHandler:
    """Get or create singleton relationship query handler."""
    global _relationship_query_handler
    if _relationship_query_handler is None:
        _relationship_query_handler = RelationshipQueryHandler()
    return _relationship_query_handler


if __name__ == "__main__":
    # Build and save relationship graph
    extractor = RelationshipExtractor()
    graph = extractor.build_graph()
    extractor.save_graph()
    
    # Print statistics
    stats = graph.to_dict()['stats']
    print(f"\nRelationship Graph Statistics:")
    print(f"  Total nodes: {stats['total_nodes']}")
    print(f"  Total edges: {stats['total_edges']}")
    print(f"  Edge types: {', '.join(stats['edge_types'])}")