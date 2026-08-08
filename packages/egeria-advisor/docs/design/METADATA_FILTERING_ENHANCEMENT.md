# Metadata Filtering Enhancement for Agents

## Overview
Enhance PyEgeria and CLI Command agents to leverage structured metadata fields for more precise and efficient queries.

## Current State
- **PyEgeria Collection**: 8,582 code elements with metadata (class_name, method_name, element_type, etc.)
- **CLI Commands Collection**: 139 commands with metadata (main_command, subcommand, options, flags, etc.)
- **Agents**: Currently use only semantic search, not metadata filtering

## Metadata Fields Available

### PyEgeria Collection
```python
{
    "element_type": "method",      # function, class, method
    "class_name": "ProjectManager",
    "method_name": "create_project",
    "parent_class": "ProjectManager",
    "signature": "create_project(self, name: str) -> dict",
    "parameters": "self,name",
    "return_type": "dict",
    "is_async": False,
    "is_private": False,
    "decorators": "",
    "complexity": 5,
    "module_path": "pyegeria.project_manager"
}
```

### CLI Commands Collection
```python
{
    "main_command": "hey_egeria",
    "subcommand": "platform status",
    "full_command": "hey_egeria platform status",
    "options": "--url,--timeout",
    "flags": "--verbose,--json",
    "required_options": "--url"
}
```

## Enhancement Strategy

### Phase 1: PyEgeria Agent Enhancements

#### 1.1 Add Metadata-Based Query Classification
```python
def classify_query_with_metadata(self, query: str) -> Dict[str, Any]:
    """
    Enhanced classification that extracts metadata filters.
    
    Returns:
        {
            'query_type': 'class' | 'method' | 'module',
            'filters': {
                'class_name': 'ProjectManager',
                'element_type': 'method',
                'method_name': 'create_project'
            }
        }
    """
```

**Examples:**
- "What methods does ProjectManager have?" → `{'class_name': 'ProjectManager', 'element_type': 'method'}`
- "Show me async methods in GlossaryManager" → `{'class_name': 'GlossaryManager', 'is_async': True}`
- "Find private methods" → `{'is_private': True}`

#### 1.2 Enhanced Search with Metadata Filtering
```python
def search_pyegeria_with_filters(
    self,
    query: str,
    filters: Optional[Dict[str, Any]] = None,
    top_k: int = 10
) -> List[Dict[str, Any]]:
    """
    Search with metadata filters for O(1) precision.
    
    Two-stage approach:
    1. Apply metadata filters (O(1) lookup)
    2. Semantic search within filtered results
    """
```

**Benefits:**
- **Precision**: Filter to exact class before semantic search
- **Speed**: Reduce search space from 8,582 to ~50-100 elements
- **Accuracy**: Eliminate false positives from other classes

#### 1.3 Smart Filter Extraction
```python
def extract_filters_from_query(self, query: str) -> Dict[str, Any]:
    """
    Extract metadata filters from natural language query.
    
    Patterns:
    - Class names: "ProjectManager", "GlossaryManager" → class_name
    - Method names: "create_project", "get_glossary" → method_name
    - Keywords: "async" → is_async=True, "private" → is_private=True
    - Module paths: "pyegeria.admin" → module_path
    """
```

### Phase 2: CLI Command Agent Enhancements

#### 2.1 Command-Specific Filtering
```python
def search_commands_with_filters(
    self,
    query: str,
    filters: Optional[Dict[str, Any]] = None,
    top_k: int = 5
) -> List[SearchResult]:
    """
    Search CLI commands with metadata filters.
    
    Filters:
    - main_command: "hey_egeria" | "dr_egeria"
    - subcommand: "platform", "glossary", "asset"
    - has_option: "--url", "--server"
    - required_options: "--url"
    """
```

**Examples:**
- "Show me platform commands" → `{'subcommand': 'platform'}`
- "Commands that require --url" → `{'required_options': '--url'}`
- "All glossary commands" → `{'subcommand': 'glossary'}`

#### 2.2 Option-Based Search
```python
def find_commands_by_option(self, option: str) -> List[SearchResult]:
    """
    Find all commands that support a specific option.
    
    Example: find_commands_by_option("--timeout")
    Returns: All commands with --timeout in options field
    """
```

### Phase 3: Implementation Details

#### 3.1 Milvus Filter Expression Syntax
```python
# Single filter
filter_expr = 'class_name == "ProjectManager"'

# Multiple filters (AND)
filter_expr = 'class_name == "ProjectManager" and element_type == "method"'

# OR conditions
filter_expr = 'class_name == "ProjectManager" or class_name == "GlossaryManager"'

# String contains (for comma-separated fields)
filter_expr = 'options like "%--url%"'

# Boolean filters
filter_expr = 'is_async == True'
```

#### 3.2 Helper Function for Filter Building
```python
def build_filter_expr(filters: Dict[str, Any]) -> str:
    """
    Build Milvus filter expression from dict.
    
    Args:
        filters: {'class_name': 'ProjectManager', 'is_async': True}
    
    Returns:
        'class_name == "ProjectManager" and is_async == True'
    """
    conditions = []
    for key, value in filters.items():
        if isinstance(value, str):
            conditions.append(f'{key} == "{value}"')
        elif isinstance(value, bool):
            conditions.append(f'{key} == {value}')
        elif isinstance(value, (int, float)):
            conditions.append(f'{key} == {value}')
    
    return ' and '.join(conditions)
```

### Phase 4: Testing Strategy

#### 4.1 PyEgeria Agent Tests
```python
# Test 1: Class-specific method search
query = "What methods does ProjectManager have?"
# Should filter: class_name == "ProjectManager" and element_type == "method"
# Expected: Only ProjectManager methods, not other classes

# Test 2: Async method search
query = "Show me async methods in GlossaryManager"
# Should filter: class_name == "GlossaryManager" and is_async == True
# Expected: Only async methods from GlossaryManager

# Test 3: Module search
query = "What's in pyegeria.admin?"
# Should filter: module_path like "pyegeria.admin%"
# Expected: All elements from admin module
```

#### 4.2 CLI Command Agent Tests
```python
# Test 1: Subcommand search
query = "Show me all platform commands"
# Should filter: subcommand like "%platform%"
# Expected: All platform-related commands

# Test 2: Option-based search
query = "Which commands require --url?"
# Should filter: required_options like "%--url%"
# Expected: Commands with --url as required

# Test 3: Main command filter
query = "List all hey_egeria commands"
# Should filter: main_command == "hey_egeria"
# Expected: Only hey_egeria commands, not dr_egeria
```

## Performance Impact

### Before (Semantic Search Only)
- Search space: 8,582 elements (PyEgeria) or 139 commands (CLI)
- Time: O(n) semantic similarity computation
- Precision: ~60-70% (many false positives)

### After (Metadata Filtering + Semantic Search)
- Search space: ~50-100 elements (after filtering)
- Time: O(1) metadata lookup + O(m) semantic search (m << n)
- Precision: ~90-95% (filtered to exact context)
- **Speedup**: 10-100x for filtered queries

## Implementation Order

1. ✅ Add metadata fields to collections (COMPLETED)
2. ✅ Re-index collections with metadata (COMPLETED)
3. **Add filter extraction logic to agents** (NEXT)
4. **Enhance search methods with filtering** (NEXT)
5. **Test and validate improvements** (NEXT)
6. **Document usage patterns** (NEXT)

## Next Steps

1. Implement `extract_filters_from_query()` in PyEgeriaAgent
2. Implement `build_filter_expr()` helper function
3. Update `search_pyegeria()` to use filters
4. Implement similar enhancements for CLICommandAgent
5. Create comprehensive test suite
6. Measure performance improvements
7. Update user documentation

## Success Metrics

- **Precision**: >90% for filtered queries
- **Speed**: 10-100x faster for class/command-specific queries
- **User Satisfaction**: Fewer irrelevant results
- **Coverage**: 80%+ of queries benefit from filtering