"""Python code parser using AST for extracting code elements."""
import ast
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class CodeElement:
    """Represents a parsed code element (function, class, method)."""
    
    type: str  # function, class, method
    name: str
    file_path: str
    line_number: int
    end_line_number: int
    docstring: Optional[str]
    signature: str
    body: str
    parent_class: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    parameters: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    is_async: bool = False
    is_private: bool = False
    complexity: int = 0
    bases: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "type": self.type,
            "name": self.name,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "end_line_number": self.end_line_number,
            "docstring": self.docstring,
            "signature": self.signature,
            "body": self.body,
            "parent_class": self.parent_class,
            "decorators": self.decorators,
            "parameters": self.parameters,
            "return_type": self.return_type,
            "is_async": self.is_async,
            "is_private": self.is_private,
            "complexity": self.complexity,
            "bases": self.bases,
        }
    
    @property
    def full_name(self) -> str:
        """Get fully qualified name."""
        if self.parent_class:
            return f"{self.parent_class}.{self.name}"
        return self.name
    
    @property
    def is_public(self) -> bool:
        """Check if element is public (not private)."""
        return not self.is_private


class CodeParser:
    """Parse Python code files using AST to extract code elements."""
    
    def __init__(self):
        """Initialize the code parser."""
        self.parsed_files: List[Path] = []
        self.errors: List[Dict[str, Any]] = []
    
    def parse_file(self, file_path: Path) -> List[CodeElement]:
        """
        Parse a Python file and extract code elements.
        
        Parameters
        ----------
        file_path : Path
            Path to the Python file to parse
        
        Returns
        -------
        List[CodeElement]
            List of extracted code elements
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            self.errors.append({"file": str(file_path), "error": str(e), "stage": "read"})
            return []
        
        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {e}")
            self.errors.append({"file": str(file_path), "error": str(e), "stage": "parse"})
            return []
        
        elements = []

        # Map each method node to its owning class first, so the main walk below
        # visits every FunctionDef/AsyncFunctionDef exactly once. Previously methods
        # were parsed twice — once here as a bare "function" (via ast.walk hitting the
        # node directly) and again via an explicit second loop over the class body —
        # producing two elements with the same `name::line_number` id. That collided
        # in the pgvector upsert ("ON CONFLICT DO UPDATE command cannot affect row a
        # second time") and silently dropped the *entire file's* chunks on error.
        parent_class_of: Dict[ast.AST, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        parent_class_of[item] = node.name

        # Walk the AST and extract elements
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                element = self._parse_function(node, file_path, parent_class=parent_class_of.get(node))
                if element:
                    elements.append(element)
            elif isinstance(node, ast.ClassDef):
                element = self._parse_class(node, file_path)
                if element:
                    elements.append(element)
        
        self.parsed_files.append(file_path)
        logger.info(f"Parsed {file_path}: found {len(elements)} code elements")
        
        return elements
    
    def _parse_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        file_path: Path,
        parent_class: Optional[str] = None
    ) -> Optional[CodeElement]:
        """
        Parse a function or method definition.
        
        Parameters
        ----------
        node : ast.FunctionDef | ast.AsyncFunctionDef
            AST node representing the function
        file_path : Path
            Path to the file containing the function
        parent_class : str, optional
            Name of parent class if this is a method
        
        Returns
        -------
        CodeElement, optional
            Parsed code element or None if parsing fails
        """
        try:
            element_type = "method" if parent_class else "function"
            is_async = isinstance(node, ast.AsyncFunctionDef)
            is_private = node.name.startswith('_') and not node.name.startswith('__')
            
            # Extract decorators
            decorators = [self._get_decorator_name(d) for d in node.decorator_list]
            
            # Extract parameters
            parameters = self._extract_parameters(node.args)
            
            # Extract return type
            return_type = None
            if node.returns:
                try:
                    return_type = ast.unparse(node.returns)
                except:
                    return_type = None
            
            # Calculate complexity (simple metric: count decision points)
            complexity = self._calculate_complexity(node)
            
            return CodeElement(
                type=element_type,
                name=node.name,
                file_path=str(file_path),
                line_number=node.lineno,
                end_line_number=node.end_lineno or node.lineno,
                docstring=ast.get_docstring(node),
                signature=self._get_signature(node),
                body=ast.unparse(node),
                parent_class=parent_class,
                decorators=decorators,
                parameters=parameters,
                return_type=return_type,
                is_async=is_async,
                is_private=is_private,
                complexity=complexity,
            )
        except Exception as e:
            logger.warning(f"Error parsing function {node.name} in {file_path}: {e}")
            return None
    
    def _parse_class(self, node: ast.ClassDef, file_path: Path) -> Optional[CodeElement]:
        """
        Parse a class definition.
        
        Parameters
        ----------
        node : ast.ClassDef
            AST node representing the class
        file_path : Path
            Path to the file containing the class
        
        Returns
        -------
        CodeElement, optional
            Parsed code element or None if parsing fails
        """
        try:
            is_private = node.name.startswith('_') and not node.name.startswith('__')
            
            # Extract decorators
            decorators = [self._get_decorator_name(d) for d in node.decorator_list]
            
            # Extract base classes
            bases = [ast.unparse(base) for base in node.bases]
            
            return CodeElement(
                type="class",
                name=node.name,
                file_path=str(file_path),
                line_number=node.lineno,
                end_line_number=node.end_lineno or node.lineno,
                docstring=ast.get_docstring(node),
                signature=f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}",
                body=ast.unparse(node),
                decorators=decorators,
                is_private=is_private,
                bases=bases,
            )
        except Exception as e:
            logger.warning(f"Error parsing class {node.name} in {file_path}: {e}")
            return None
    
    def _get_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Extract function signature."""
        try:
            # Get parameter names
            args = []
            for arg in node.args.args:
                arg_str = arg.arg
                if arg.annotation:
                    try:
                        arg_str += f": {ast.unparse(arg.annotation)}"
                    except:
                        pass
                args.append(arg_str)
            
            # Add return type if present
            return_annotation = ""
            if node.returns:
                try:
                    return_annotation = f" -> {ast.unparse(node.returns)}"
                except:
                    pass
            
            async_prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            return f"{async_prefix}def {node.name}({', '.join(args)}){return_annotation}"
        except Exception as e:
            logger.warning(f"Error extracting signature for {node.name}: {e}")
            return f"def {node.name}(...)"
    
    def _extract_parameters(self, args: ast.arguments) -> List[str]:
        """Extract parameter names from function arguments."""
        params = []
        for arg in args.args:
            params.append(arg.arg)
        return params
    
    def _get_decorator_name(self, decorator: ast.expr) -> str:
        """Extract decorator name."""
        try:
            if isinstance(decorator, ast.Name):
                return decorator.id
            elif isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Name):
                    return decorator.func.id
                return ast.unparse(decorator.func)
            return ast.unparse(decorator)
        except:
            return "unknown"
    
    def _calculate_complexity(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        """
        Calculate cyclomatic complexity (simplified).
        
        Counts decision points: if, for, while, except, and, or
        """
        complexity = 1  # Base complexity
        
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, (ast.And, ast.Or)):
                complexity += 1
        
        return complexity
    
    def parse_directory(
        self,
        directory: Path,
        recursive: bool = True,
        exclude_patterns: Optional[List[str]] = None
    ) -> List[CodeElement]:
        """
        Parse all Python files in a directory.
        
        Parameters
        ----------
        directory : Path
            Directory to parse
        recursive : bool, default True
            Whether to recursively parse subdirectories
        exclude_patterns : List[str], optional
            Patterns to exclude (e.g., ['**/test_*.py', '**/__pycache__/**'])
        
        Returns
        -------
        List[CodeElement]
            All extracted code elements
        """
        all_elements = []
        
        if recursive:
            pattern = "**/*.py"
        else:
            pattern = "*.py"
        
        python_files = list(directory.glob(pattern))
        logger.info(f"Found {len(python_files)} Python files in {directory}")
        
        for file_path in python_files:
            # Check exclusions
            if exclude_patterns:
                if any(file_path.match(pattern) for pattern in exclude_patterns):
                    logger.debug(f"Skipping excluded file: {file_path}")
                    continue
            
            elements = self.parse_file(file_path)
            all_elements.extend(elements)
        
        logger.info(f"Parsed {len(self.parsed_files)} files, extracted {len(all_elements)} elements")
        
        return all_elements
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get parsing statistics."""
        return {
            "files_parsed": len(self.parsed_files),
            "errors": len(self.errors),
            "error_details": self.errors,
        }