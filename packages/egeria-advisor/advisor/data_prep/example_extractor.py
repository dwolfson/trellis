"""Extract code examples from test files and example directories."""
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from loguru import logger
import ast
import re


@dataclass
class CodeExample:
    """Represents a code example extracted from tests or examples."""
    
    name: str
    description: str
    code: str
    file_path: str
    line_number: int
    end_line_number: int
    example_type: str  # test, example, usage, snippet
    language: str = "python"
    related_apis: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    setup_code: Optional[str] = None
    teardown_code: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "name": self.name,
            "description": self.description,
            "code": self.code,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "end_line_number": self.end_line_number,
            "example_type": self.example_type,
            "language": self.language,
            "related_apis": self.related_apis,
            "imports": self.imports,
            "setup_code": self.setup_code,
            "teardown_code": self.teardown_code,
            "tags": self.tags,
        }
    
    @property
    def full_code(self) -> str:
        """Get full code including setup and teardown."""
        parts = []
        if self.imports:
            parts.append('\n'.join(self.imports))
        if self.setup_code:
            parts.append(self.setup_code)
        parts.append(self.code)
        if self.teardown_code:
            parts.append(self.teardown_code)
        return '\n\n'.join(parts)


class ExampleExtractor:
    """Extract code examples from test files and example directories."""
    
    def __init__(self):
        """Initialize the example extractor."""
        self.extracted_examples: List[CodeExample] = []
        self.errors: List[Dict[str, Any]] = []
    
    def extract_from_file(self, file_path: Path) -> List[CodeExample]:
        """
        Extract examples from a Python file.
        
        Parameters
        ----------
        file_path : Path
            Path to the Python file
        
        Returns
        -------
        List[CodeExample]
            List of extracted examples
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            self.errors.append({"file": str(file_path), "error": str(e), "stage": "read"})
            return []
        
        examples = []
        
        # Determine file type
        if 'test_' in file_path.name or file_path.parent.name == 'tests':
            examples.extend(self._extract_from_test_file(content, file_path))
        elif 'example' in file_path.name.lower() or file_path.parent.name == 'examples':
            examples.extend(self._extract_from_example_file(content, file_path))
        else:
            # Try to extract any docstring examples
            examples.extend(self._extract_docstring_examples(content, file_path))
        
        self.extracted_examples.extend(examples)
        logger.info(f"Extracted {len(examples)} examples from {file_path}")
        
        return examples
    
    def _extract_from_test_file(self, content: str, file_path: Path) -> List[CodeExample]:
        """Extract examples from test files."""
        examples = []
        
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {e}")
            return examples
        
        # Extract imports
        imports = self._extract_imports(tree)
        
        # Find test functions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name.startswith('test_'):
                    example = self._create_example_from_function(
                        node, file_path, "test", imports
                    )
                    if example:
                        examples.append(example)
        
        return examples
    
    def _extract_from_example_file(self, content: str, file_path: Path) -> List[CodeExample]:
        """Extract examples from example files."""
        examples = []
        
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {e}")
            return examples
        
        # Extract imports
        imports = self._extract_imports(tree)
        
        # Find example functions (main, demo, example_*, etc.)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if (node.name == 'main' or 
                    node.name.startswith('example_') or
                    node.name.startswith('demo_')):
                    example = self._create_example_from_function(
                        node, file_path, "example", imports
                    )
                    if example:
                        examples.append(example)
        
        # Also extract module-level code if it's a script
        if self._is_script(tree):
            example = self._extract_script_example(tree, file_path, imports)
            if example:
                examples.append(example)
        
        return examples
    
    def _extract_docstring_examples(self, content: str, file_path: Path) -> List[CodeExample]:
        """Extract code examples from docstrings."""
        examples = []
        
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return examples
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                docstring = ast.get_docstring(node)
                if docstring:
                    # Look for code blocks in docstring
                    code_blocks = self._extract_code_from_docstring(docstring)
                    for i, code_block in enumerate(code_blocks):
                        example = CodeExample(
                            name=f"{node.name}_docstring_example_{i+1}",
                            description=f"Example from {node.name} docstring",
                            code=code_block,
                            file_path=str(file_path),
                            line_number=node.lineno,
                            end_line_number=node.end_lineno or node.lineno,
                            example_type="docstring",
                            related_apis=[node.name],
                        )
                        examples.append(example)
        
        return examples
    
    def _create_example_from_function(
        self,
        node: ast.FunctionDef,
        file_path: Path,
        example_type: str,
        imports: List[str]
    ) -> Optional[CodeExample]:
        """Create a CodeExample from a function node."""
        try:
            # Get docstring for description
            docstring = ast.get_docstring(node) or f"Example from {node.name}"
            
            # Extract related APIs from function body
            related_apis = self._extract_api_calls(node)
            
            # Get function code
            code = ast.unparse(node)
            
            # Extract tags from function name and docstring
            tags = self._extract_tags(node.name, docstring)
            
            return CodeExample(
                name=node.name,
                description=docstring,
                code=code,
                file_path=str(file_path),
                line_number=node.lineno,
                end_line_number=node.end_lineno or node.lineno,
                example_type=example_type,
                related_apis=related_apis,
                imports=imports,
                tags=tags,
            )
        except Exception as e:
            logger.warning(f"Error creating example from {node.name}: {e}")
            return None
    
    def _extract_imports(self, tree: ast.AST) -> List[str]:
        """Extract import statements from AST."""
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = ", ".join(alias.name for alias in node.names)
                imports.append(f"from {module} import {names}")
        
        return imports
    
    def _extract_api_calls(self, node: ast.FunctionDef) -> List[str]:
        """Extract API calls from function body."""
        api_calls = set()
        
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute):
                    # Method call like obj.method()
                    api_calls.add(child.func.attr)
                elif isinstance(child.func, ast.Name):
                    # Function call like function()
                    api_calls.add(child.func.id)
        
        return list(api_calls)
    
    def _extract_tags(self, name: str, docstring: str) -> List[str]:
        """Extract tags from function name and docstring."""
        tags = []
        
        # Extract from name
        if 'create' in name.lower():
            tags.append('create')
        if 'delete' in name.lower():
            tags.append('delete')
        if 'update' in name.lower():
            tags.append('update')
        if 'find' in name.lower() or 'search' in name.lower():
            tags.append('search')
        if 'list' in name.lower():
            tags.append('list')
        
        # Extract from docstring
        if 'glossary' in docstring.lower():
            tags.append('glossary')
        if 'asset' in docstring.lower():
            tags.append('asset')
        if 'collection' in docstring.lower():
            tags.append('collection')
        if 'project' in docstring.lower():
            tags.append('project')
        
        return list(set(tags))
    
    def _extract_code_from_docstring(self, docstring: str) -> List[str]:
        """Extract code blocks from docstring."""
        code_blocks = []
        
        # Look for code blocks in various formats
        # Format 1: >>> python code
        pattern1 = r'>>>(.+?)(?=>>>|\Z)'
        matches1 = re.findall(pattern1, docstring, re.DOTALL)
        code_blocks.extend([m.strip() for m in matches1])
        
        # Format 2: Indented code blocks
        lines = docstring.split('\n')
        current_block = []
        in_code_block = False
        
        for line in lines:
            if line.strip().startswith('```python') or line.strip().startswith('.. code-block::'):
                in_code_block = True
                continue
            elif line.strip().startswith('```') and in_code_block:
                if current_block:
                    code_blocks.append('\n'.join(current_block))
                    current_block = []
                in_code_block = False
            elif in_code_block:
                current_block.append(line)
        
        return code_blocks
    
    def _is_script(self, tree: ast.AST) -> bool:
        """Check if the module is a script (has if __name__ == '__main__')."""
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                if isinstance(node.test, ast.Compare):
                    if (isinstance(node.test.left, ast.Name) and 
                        node.test.left.id == '__name__'):
                        return True
        return False
    
    def _extract_script_example(
        self,
        tree: ast.AST,
        file_path: Path,
        imports: List[str]
    ) -> Optional[CodeExample]:
        """Extract example from script's main block."""
        try:
            # Find the if __name__ == '__main__' block
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    if isinstance(node.test, ast.Compare):
                        if (isinstance(node.test.left, ast.Name) and 
                            node.test.left.id == '__name__'):
                            # Extract code from the main block
                            code = '\n'.join(ast.unparse(stmt) for stmt in node.body)
                            
                            return CodeExample(
                                name=f"{file_path.stem}_main",
                                description=f"Main script example from {file_path.name}",
                                code=code,
                                file_path=str(file_path),
                                line_number=node.lineno,
                                end_line_number=node.end_lineno or node.lineno,
                                example_type="script",
                                imports=imports,
                            )
        except Exception as e:
            logger.warning(f"Error extracting script example: {e}")
        
        return None
    
    def extract_from_directory(
        self,
        directory: Path,
        recursive: bool = True,
        include_tests: bool = True,
        include_examples: bool = True,
        exclude_patterns: Optional[List[str]] = None
    ) -> List[CodeExample]:
        """
        Extract examples from all Python files in a directory.
        
        Parameters
        ----------
        directory : Path
            Directory to extract from
        recursive : bool, default True
            Whether to recursively process subdirectories
        include_tests : bool, default True
            Whether to include test files
        include_examples : bool, default True
            Whether to include example files
        exclude_patterns : List[str], optional
            Patterns to exclude
        
        Returns
        -------
        List[CodeExample]
            All extracted examples
        """
        all_examples = []
        
        if recursive:
            pattern = "**/*.py"
        else:
            pattern = "*.py"
        
        python_files = list(directory.glob(pattern))
        logger.info(f"Found {len(python_files)} Python files in {directory}")
        
        for file_path in python_files:
            # Check exclusions
            if exclude_patterns:
                if any(file_path.match(p) for p in exclude_patterns):
                    logger.debug(f"Skipping excluded file: {file_path}")
                    continue
            
            # Check if we should process this file
            is_test = 'test_' in file_path.name or file_path.parent.name == 'tests'
            is_example = 'example' in file_path.name.lower() or file_path.parent.name == 'examples'
            
            if (is_test and not include_tests) or (is_example and not include_examples):
                continue
            
            examples = self.extract_from_file(file_path)
            all_examples.extend(examples)
        
        logger.info(f"Extracted {len(all_examples)} examples from {directory}")
        
        return all_examples
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get extraction statistics."""
        type_counts = {}
        for example in self.extracted_examples:
            type_counts[example.example_type] = type_counts.get(example.example_type, 0) + 1
        
        return {
            "total_examples": len(self.extracted_examples),
            "by_type": type_counts,
            "errors": len(self.errors),
            "error_details": self.errors,
        }


if __name__ == "__main__":
    # Test the extractor
    import sys
    from advisor.config import settings

    if len(sys.argv) > 1:
        test_path = Path(sys.argv[1])
    else:
        test_path = settings.advisor_data_path
    
    extractor = ExampleExtractor()
    
    if test_path.is_file():
        examples = extractor.extract_from_file(test_path)
        print(f"\nExtracted {len(examples)} examples from {test_path}")
    else:
        examples = extractor.extract_from_directory(
            test_path,
            recursive=True,
            exclude_patterns=["**/__pycache__/**", "**/deprecated/**"]
        )
        print(f"\nExtracted {len(examples)} examples from {test_path}")
    
    # Print first 10 examples
    for example in examples[:10]:
        print(f"\n- {example.name} ({example.example_type})")
        print(f"  File: {example.file_path}:{example.line_number}")
        print(f"  Description: {example.description[:80]}...")
        if example.related_apis:
            print(f"  APIs: {', '.join(example.related_apis[:5])}")
        if example.tags:
            print(f"  Tags: {', '.join(example.tags)}")
    
    # Print statistics
    stats = extractor.get_statistics()
    print(f"\nStatistics:")
    print(f"  Total examples: {stats['total_examples']}")
    print(f"  By type: {stats['by_type']}")
    print(f"  Errors: {stats['errors']}")