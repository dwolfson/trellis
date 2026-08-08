"""
CLI Command Parser for extracting command metadata from pyegeria.

This module extracts command information from:
1. pyproject.toml - Command definitions
2. Python files - Click decorators, docstrings, parameters
3. md_processing - dr_egeria command handlers
"""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from loguru import logger

# Handle tomli/tomllib compatibility (tomllib is built-in for Python 3.11+)
if sys.version_info >= (3, 11):
    import tomllib as tomli
else:
    try:
        import tomli
    except ImportError:
        logger.error("tomli package required for Python < 3.11. Install with: pip install tomli")
        raise


class CLICommandExtractor:
    """Extract CLI command metadata from pyegeria repository."""
    
    def __init__(self, pyegeria_root: Path):
        """
        Initialize the CLI command extractor.
        
        Args:
            pyegeria_root: Root path to pyegeria repository
        """
        self.pyegeria_root = Path(pyegeria_root)
        self.commands: Dict[str, Dict[str, Any]] = {}
        
    def extract_all_commands(self) -> Dict[str, Dict[str, Any]]:
        """
        Extract all CLI commands from pyegeria.
        
        Returns:
            Dictionary of command metadata keyed by command name
        """
        logger.info("Extracting CLI commands from pyegeria")
        
        # Extract hey_egeria commands
        hey_egeria_commands = self.extract_hey_egeria_commands()
        logger.info(f"Extracted {len(hey_egeria_commands)} hey_egeria commands")
        
        # Extract dr_egeria commands
        dr_egeria_commands = self.extract_dr_egeria_commands()
        logger.info(f"Extracted {len(dr_egeria_commands)} dr_egeria commands")
        
        # Combine all commands
        self.commands = {**hey_egeria_commands, **dr_egeria_commands}
        logger.info(f"Total commands extracted: {len(self.commands)}")
        
        return self.commands
    
    def extract_hey_egeria_commands(self) -> Dict[str, Dict[str, Any]]:
        """
        Extract hey_egeria commands from pyproject.toml.
        
        Returns:
            Dictionary of command metadata
        """
        commands = {}
        pyproject_path = self.pyegeria_root / "pyproject.toml"
        
        if not pyproject_path.exists():
            logger.warning(f"pyproject.toml not found at {pyproject_path}")
            return commands
        
        try:
            with open(pyproject_path, 'rb') as f:
                pyproject = tomli.load(f)
            
            scripts = pyproject.get('project', {}).get('scripts', {})
            
            for command_name, entry_point in scripts.items():
                # Parse entry point: "module.path:function_name"
                if ':' not in entry_point:
                    logger.warning(f"Invalid entry point for {command_name}: {entry_point}")
                    continue
                
                module_path, function_name = entry_point.split(':', 1)
                
                # Determine category from module path
                category = self._determine_category(module_path)
                
                # Extract command details from Python file
                command_details = self._extract_command_details(
                    module_path, function_name
                )
                
                commands[command_name] = {
                    'command_name': command_name,
                    'type': 'hey_egeria',
                    'category': category,
                    'module_path': module_path,
                    'function_name': function_name,
                    'entry_point': entry_point,
                    **command_details
                }
                
        except Exception as e:
            logger.error(f"Error extracting hey_egeria commands: {e}")
        
        return commands
    
    def _determine_category(self, module_path: str) -> str:
        """
        Determine command category from module path.
        
        Args:
            module_path: Python module path (e.g., "commands.cat.list_assets")
            
        Returns:
            Category name (cat/ops/my/tech/cli)
        """
        parts = module_path.split('.')
        if len(parts) >= 2 and parts[0] == 'commands':
            return parts[1]
        return 'other'
    
    def _extract_command_details(
        self, module_path: str, function_name: str
    ) -> Dict[str, Any]:
        """
        Extract command details from Python source file.
        
        Args:
            module_path: Python module path
            function_name: Function name to extract
            
        Returns:
            Dictionary with description, parameters, etc.
        """
        details = {
            'description': '',
            'parameters': [],
            'help_text': '',
            'docstring': ''
        }
        
        # Convert module path to file path
        file_path = self.pyegeria_root / (module_path.replace('.', '/') + '.py')
        
        if not file_path.exists():
            logger.debug(f"Source file not found: {file_path}")
            return details
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            
            # Parse the AST
            tree = ast.parse(source)
            
            # Find the function
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == function_name:
                    # Extract docstring
                    docstring = ast.get_docstring(node)
                    if docstring:
                        details['docstring'] = docstring
                        details['description'] = docstring.split('\n')[0]
                    
                    # Extract Click decorators
                    click_params = self._extract_click_decorators(node)
                    details['parameters'] = click_params
                    
                    # Extract help text from @click.command decorator
                    help_text = self._extract_help_text(node)
                    if help_text:
                        details['help_text'] = help_text
                        if not details['description']:
                            details['description'] = help_text
                    
                    break
                    
        except Exception as e:
            logger.debug(f"Error parsing {file_path}: {e}")
        
        return details
    
    def _extract_click_decorators(self, func_node: ast.FunctionDef) -> List[Dict[str, Any]]:
        """
        Extract Click decorator information from function node.
        
        Args:
            func_node: AST FunctionDef node
            
        Returns:
            List of parameter dictionaries
        """
        parameters = []
        
        for decorator in func_node.decorator_list:
            # Handle @click.option() and @click.argument()
            if isinstance(decorator, ast.Call):
                if self._is_click_decorator(decorator, ['option', 'argument']):
                    param = self._parse_click_decorator(decorator)
                    if param:
                        parameters.append(param)
        
        return parameters
    
    def _is_click_decorator(self, decorator: ast.Call, names: List[str]) -> bool:
        """Check if decorator is a Click decorator with given name."""
        if isinstance(decorator.func, ast.Attribute):
            if (isinstance(decorator.func.value, ast.Name) and 
                decorator.func.value.id == 'click' and
                decorator.func.attr in names):
                return True
        return False
    
    def _parse_click_decorator(self, decorator: ast.Call) -> Optional[Dict[str, Any]]:
        """
        Parse a Click decorator call to extract parameter info.
        
        Args:
            decorator: AST Call node for Click decorator
            
        Returns:
            Parameter dictionary or None
        """
        param = {
            'name': '',
            'type': 'str',
            'required': False,
            'default': None,
            'help': ''
        }
        
        # Get parameter name from first positional argument
        if decorator.args:
            arg = decorator.args[0]
            if isinstance(arg, ast.Constant):
                param['name'] = arg.value
        
        # Extract keyword arguments
        for keyword in decorator.keywords:
            key = keyword.arg
            value = keyword.value
            
            if key == 'default':
                param['default'] = self._extract_constant_value(value)
                param['required'] = False
            elif key == 'required':
                if isinstance(value, ast.Constant):
                    param['required'] = value.value
            elif key == 'help':
                param['help'] = self._extract_constant_value(value)
            elif key == 'type':
                param['type'] = self._extract_type_name(value)
            elif key == 'is_flag':
                if isinstance(value, ast.Constant) and value.value:
                    param['type'] = 'bool'
        
        return param if param['name'] else None
    
    def _extract_constant_value(self, node: ast.AST) -> Any:
        """Extract constant value from AST node."""
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Name):
            return node.id
        return None
    
    def _extract_type_name(self, node: ast.AST) -> str:
        """Extract type name from AST node."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return 'str'
    
    def _extract_help_text(self, func_node: ast.FunctionDef) -> str:
        """Extract help text from @click.command decorator."""
        for decorator in func_node.decorator_list:
            if isinstance(decorator, ast.Call):
                if self._is_click_decorator(decorator, ['command', 'group']):
                    for keyword in decorator.keywords:
                        if keyword.arg == 'help':
                            return self._extract_constant_value(keyword.value) or ''
        return ''
    
    def extract_dr_egeria_commands(self) -> Dict[str, Dict[str, Any]]:
        """
        Extract dr_egeria commands from md_processing directory.
        
        Returns:
            Dictionary of command metadata
        """
        commands = {}
        md_processing_path = self.pyegeria_root / "md_processing"
        
        if not md_processing_path.exists():
            logger.warning(f"md_processing directory not found at {md_processing_path}")
            return commands
        
        try:
            # Look for command_mapping.py to find command dispatcher
            mapping_file = md_processing_path / "command_mapping.py"
            if mapping_file.exists():
                commands.update(self._extract_from_command_mapping(mapping_file))
            
            # Also scan md_commands directory for command handlers
            md_commands_dir = md_processing_path / "md_commands"
            if md_commands_dir.exists():
                commands.update(self._extract_from_command_handlers(md_commands_dir))
                
        except Exception as e:
            logger.error(f"Error extracting dr_egeria commands: {e}")
        
        return commands
    
    def _extract_from_command_mapping(self, mapping_file: Path) -> Dict[str, Dict[str, Any]]:
        """Extract commands from command_mapping.py dispatcher."""
        commands = {}
        
        try:
            with open(mapping_file, 'r', encoding='utf-8') as f:
                source = f.read()
            
            # Look for command registrations in the dispatcher
            # Pattern: dispatcher.register("CommandName", handler)
            pattern = r'dispatcher\.register\(["\']([^"\']+)["\']'
            matches = re.findall(pattern, source)
            
            for command_name in matches:
                commands[f"dr_{command_name.lower()}"] = {
                    'command_name': command_name,
                    'type': 'dr_egeria',
                    'category': 'markdown',
                    'description': f'Dr. Egeria markdown command: {command_name}',
                    'parameters': [],
                    'usage': f'# {command_name}\n...\n---'
                }
                
        except Exception as e:
            logger.debug(f"Error parsing command_mapping.py: {e}")
        
        return commands
    
    def _extract_from_command_handlers(self, handlers_dir: Path) -> Dict[str, Dict[str, Any]]:
        """Extract commands from command handler files."""
        commands = {}
        
        for handler_file in handlers_dir.glob("*_commands.py"):
            try:
                with open(handler_file, 'r', encoding='utf-8') as f:
                    source = f.read()
                
                tree = ast.parse(source)
                
                # Look for Pydantic model classes (command schemas)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        # Check if it's a command class (has certain patterns)
                        if self._is_command_class(node):
                            command_info = self._extract_command_from_class(node)
                            if command_info:
                                cmd_name = f"dr_{command_info['command_name'].lower()}"
                                commands[cmd_name] = command_info
                                
            except Exception as e:
                logger.debug(f"Error parsing {handler_file}: {e}")
        
        return commands
    
    def _is_command_class(self, class_node: ast.ClassDef) -> bool:
        """Check if class is a command handler class."""
        # Look for BaseModel inheritance or specific naming patterns
        for base in class_node.bases:
            if isinstance(base, ast.Name) and base.id == 'BaseModel':
                return True
            if isinstance(base, ast.Attribute) and base.attr == 'BaseModel':
                return True
        
        # Check for command-like names
        if any(keyword in class_node.name.lower() 
               for keyword in ['command', 'request', 'action']):
            return True
        
        return False
    
    def _extract_command_from_class(self, class_node: ast.ClassDef) -> Optional[Dict[str, Any]]:
        """Extract command information from Pydantic model class."""
        command_name = class_node.name
        docstring = ast.get_docstring(class_node) or ''
        
        # Extract fields (parameters)
        parameters = []
        for node in class_node.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                param = {
                    'name': node.target.id,
                    'type': self._extract_type_annotation(node.annotation),
                    'required': True,
                    'help': ''
                }
                parameters.append(param)
        
        return {
            'command_name': command_name,
            'type': 'dr_egeria',
            'category': 'markdown',
            'description': docstring.split('\n')[0] if docstring else command_name,
            'docstring': docstring,
            'parameters': parameters,
            'usage': f'# {command_name}\n...\n---'
        }
    
    def _extract_type_annotation(self, annotation: ast.AST) -> str:
        """Extract type from annotation node."""
        if isinstance(annotation, ast.Name):
            return annotation.id
        elif isinstance(annotation, ast.Subscript):
            if isinstance(annotation.value, ast.Name):
                return annotation.value.id
        return 'str'
    
    def generate_command_summary(self) -> str:
        """
        Generate a human-readable summary of extracted commands.
        
        Returns:
            Formatted summary string
        """
        if not self.commands:
            return "No commands extracted yet. Run extract_all_commands() first."
        
        summary = ["# CLI Command Summary\n"]
        
        # Group by type
        hey_egeria = [cmd for cmd in self.commands.values() if cmd['type'] == 'hey_egeria']
        dr_egeria = [cmd for cmd in self.commands.values() if cmd['type'] == 'dr_egeria']
        
        summary.append(f"## hey_egeria Commands ({len(hey_egeria)})\n")
        
        # Group hey_egeria by category
        categories = {}
        for cmd in hey_egeria:
            cat = cmd.get('category', 'other')
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(cmd)
        
        for category, cmds in sorted(categories.items()):
            summary.append(f"### {category.upper()} ({len(cmds)})")
            for cmd in sorted(cmds, key=lambda x: x['command_name']):
                desc = cmd.get('description', 'No description')
                summary.append(f"- **{cmd['command_name']}**: {desc}")
            summary.append("")
        
        summary.append(f"## dr_egeria Commands ({len(dr_egeria)})\n")
        for cmd in sorted(dr_egeria, key=lambda x: x['command_name']):
            desc = cmd.get('description', 'No description')
            summary.append(f"- **{cmd['command_name']}**: {desc}")
        
        return "\n".join(summary)