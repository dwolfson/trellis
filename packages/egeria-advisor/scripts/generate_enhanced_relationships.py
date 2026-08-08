#!/usr/bin/env python3
"""
Generate enhanced relationship graph using AST-based analysis.

This script performs deep code analysis to extract:
- Function call chains
- Import dependencies
- Module relationships
- Class inheritance hierarchies
- Method call patterns
"""

import ast
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple
from collections import defaultdict

from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.config import settings


class EnhancedASTAnalyzer(ast.NodeVisitor):
    """Enhanced AST visitor for extracting relationships."""
    
    def __init__(self, file_path: Path, module_name: str):
        self.file_path = file_path
        self.module_name = module_name
        
        # Relationships
        self.imports: List[Dict[str, Any]] = []
        self.classes: List[Dict[str, Any]] = []
        self.functions: List[Dict[str, Any]] = []
        self.calls: List[Dict[str, Any]] = []
        
        # Context tracking
        self.current_class = None
        self.current_function = None
        self.scope_stack = []
        
    def visit_Import(self, node: ast.Import):
        """Track import statements."""
        for alias in node.names:
            self.imports.append({
                'type': 'import',
                'module': alias.name,
                'alias': alias.asname,
                'line': node.lineno
            })
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Track from...import statements."""
        module = node.module or ''
        for alias in node.names:
            self.imports.append({
                'type': 'from_import',
                'module': module,
                'name': alias.name,
                'alias': alias.asname,
                'line': node.lineno,
                'level': node.level  # For relative imports
            })
        self.generic_visit(node)
    
    def visit_ClassDef(self, node: ast.ClassDef):
        """Track class definitions and inheritance."""
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(self._get_full_name(base))
        
        class_info = {
            'name': node.name,
            'bases': bases,
            'line': node.lineno,
            'methods': [],
            'decorators': [self._get_decorator_name(d) for d in node.decorator_list]
        }
        
        # Visit methods
        old_class = self.current_class
        self.current_class = node.name
        self.scope_stack.append(('class', node.name))
        
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method_info = self._extract_function_info(item, is_method=True)
                class_info['methods'].append(method_info)
        
        self.classes.append(class_info)
        
        self.scope_stack.pop()
        self.current_class = old_class
        self.generic_visit(node)
    
    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Track function definitions."""
        # Skip if this is a method (handled in visit_ClassDef)
        if self.current_class is None:
            func_info = self._extract_function_info(node, is_method=False)
            self.functions.append(func_info)
        
        # Visit function body for calls
        old_function = self.current_function
        self.current_function = node.name
        self.scope_stack.append(('function', node.name))
        
        self.generic_visit(node)
        
        self.scope_stack.pop()
        self.current_function = old_function
    
    def visit_Call(self, node: ast.Call):
        """Track function/method calls."""
        caller = self._get_current_scope()
        callee = self._get_call_name(node.func)
        
        if callee:
            self.calls.append({
                'caller': caller,
                'callee': callee,
                'line': node.lineno,
                'args_count': len(node.args),
                'kwargs_count': len(node.keywords)
            })
        
        self.generic_visit(node)
    
    def _extract_function_info(self, node: ast.FunctionDef, is_method: bool) -> Dict[str, Any]:
        """Extract function/method information."""
        return {
            'name': node.name,
            'line': node.lineno,
            'args': [arg.arg for arg in node.args.args],
            'decorators': [self._get_decorator_name(d) for d in node.decorator_list],
            'is_async': isinstance(node, ast.AsyncFunctionDef),
            'is_method': is_method
        }
    
    def _get_current_scope(self) -> str:
        """Get current scope identifier."""
        if not self.scope_stack:
            return self.module_name
        
        parts = [self.module_name]
        for scope_type, scope_name in self.scope_stack:
            parts.append(scope_name)
        return '.'.join(parts)
    
    def _get_call_name(self, node: ast.expr) -> str:
        """Extract the name of a called function/method."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return self._get_full_name(node)
        return None
    
    def _get_full_name(self, node: ast.Attribute) -> str:
        """Get full dotted name from Attribute node."""
        parts = []
        current = node
        
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        
        if isinstance(current, ast.Name):
            parts.append(current.id)
        
        return '.'.join(reversed(parts))
    
    def _get_decorator_name(self, node: ast.expr) -> str:
        """Extract decorator name."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return self._get_full_name(node)
        elif isinstance(node, ast.Call):
            return self._get_call_name(node.func)
        return str(node)


class EnhancedRelationshipExtractor:
    """Extract enhanced relationships from codebase."""
    
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.modules: Dict[str, Dict[str, Any]] = {}
        self.import_graph: Dict[str, Set[str]] = defaultdict(set)
        self.call_graph: Dict[str, Set[str]] = defaultdict(set)
        
    def analyze_file(self, file_path: Path) -> Dict[str, Any]:
        """Analyze a single Python file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            
            # Parse AST
            tree = ast.parse(code, filename=str(file_path))
            
            # Get module name
            rel_path = file_path.relative_to(self.repo_path)
            module_name = str(rel_path).replace('/', '.').replace('.py', '')
            
            # Analyze
            analyzer = EnhancedASTAnalyzer(file_path, module_name)
            analyzer.visit(tree)
            
            return {
                'module': module_name,
                'file': str(rel_path),
                'imports': analyzer.imports,
                'classes': analyzer.classes,
                'functions': analyzer.functions,
                'calls': analyzer.calls
            }
            
        except Exception as e:
            logger.debug(f"Failed to analyze {file_path}: {e}")
            return None
    
    def build_graphs(self, modules: List[Dict[str, Any]]):
        """Build import and call graphs from module data."""
        # Build import graph
        for module_data in modules:
            module = module_data['module']
            
            for imp in module_data['imports']:
                if imp['type'] == 'import':
                    self.import_graph[module].add(imp['module'])
                elif imp['type'] == 'from_import':
                    self.import_graph[module].add(imp['module'])
        
        # Build call graph
        for module_data in modules:
            for call in module_data['calls']:
                caller = call['caller']
                callee = call['callee']
                self.call_graph[caller].add(callee)
    
    def find_circular_imports(self) -> List[List[str]]:
        """Find circular import dependencies."""
        cycles = []
        visited = set()
        rec_stack = set()
        
        def dfs(node: str, path: List[str]):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self.import_graph.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, path.copy())
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    if cycle not in cycles:
                        cycles.append(cycle)
            
            rec_stack.remove(node)
        
        for module in self.import_graph.keys():
            if module not in visited:
                dfs(module, [])
        
        return cycles
    
    def calculate_metrics(self, modules: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate relationship metrics."""
        total_imports = sum(len(m['imports']) for m in modules)
        total_classes = sum(len(m['classes']) for m in modules)
        total_functions = sum(len(m['functions']) for m in modules)
        total_calls = sum(len(m['calls']) for m in modules)
        
        # Module dependencies
        module_deps = {m['module']: len(m['imports']) for m in modules}
        most_dependent = sorted(module_deps.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # Circular imports
        circular = self.find_circular_imports()
        
        return {
            'total_modules': len(modules),
            'total_imports': total_imports,
            'total_classes': total_classes,
            'total_functions': total_functions,
            'total_calls': total_calls,
            'avg_imports_per_module': total_imports / len(modules) if modules else 0,
            'most_dependent_modules': most_dependent,
            'circular_imports': circular,
            'circular_import_count': len(circular)
        }


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Enhanced Relationship Analysis")
    logger.info("=" * 60)
    
    # Get repo path
    repo_path = settings.advisor_data_path
    logger.info(f"Repository path: {repo_path}")
    
    # Find Python files
    skip_dirs = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'build', 'dist'}
    python_files = []
    for py_file in repo_path.rglob("*.py"):
        if any(part in skip_dirs for part in py_file.parts):
            continue
        python_files.append(py_file)
    
    logger.info(f"Found {len(python_files)} Python files")
    
    # Analyze files
    extractor = EnhancedRelationshipExtractor(repo_path)
    modules = []
    
    for i, file_path in enumerate(python_files, 1):
        if i % 50 == 0:
            logger.info(f"Analyzed {i}/{len(python_files)} files...")
        
        module_data = extractor.analyze_file(file_path)
        if module_data:
            modules.append(module_data)
    
    logger.success(f"Analyzed {len(modules)} modules")
    
    # Build graphs
    logger.info("Building relationship graphs...")
    extractor.build_graphs(modules)
    
    # Calculate metrics
    logger.info("Calculating metrics...")
    metrics = extractor.calculate_metrics(modules)
    
    # Save results
    cache_dir = settings.advisor_cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = cache_dir / "enhanced_relationships.json"
    logger.info(f"Saving relationships to {output_file}")
    
    output_data = {
        'modules': modules,
        'import_graph': {k: list(v) for k, v in extractor.import_graph.items()},
        'call_graph': {k: list(v) for k, v in extractor.call_graph.items()},
        'metrics': metrics
    }
    
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("RELATIONSHIP METRICS")
    logger.info("=" * 60)
    logger.info(f"Total modules: {metrics['total_modules']}")
    logger.info(f"Total imports: {metrics['total_imports']}")
    logger.info(f"Total classes: {metrics['total_classes']}")
    logger.info(f"Total functions: {metrics['total_functions']}")
    logger.info(f"Total function calls: {metrics['total_calls']}")
    logger.info(f"Avg imports per module: {metrics['avg_imports_per_module']:.1f}")
    logger.info(f"Circular imports found: {metrics['circular_import_count']}")
    
    if metrics['most_dependent_modules']:
        logger.info("\nMost dependent modules:")
        for module, count in metrics['most_dependent_modules'][:5]:
            logger.info(f"  {module}: {count} imports")
    
    if metrics['circular_imports']:
        logger.warning(f"\n⚠ Found {len(metrics['circular_imports'])} circular import chains")
        for i, cycle in enumerate(metrics['circular_imports'][:3], 1):
            logger.warning(f"  Cycle {i}: {' -> '.join(cycle)}")
    
    logger.success(f"\n✓ Enhanced relationships saved to {output_file}")


if __name__ == "__main__":
    main()