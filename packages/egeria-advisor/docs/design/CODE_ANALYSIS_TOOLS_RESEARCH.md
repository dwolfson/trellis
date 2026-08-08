# Code Analysis Tools Research for Egeria Advisor

**Date:** 2026-02-17  
**Purpose:** Evaluate tools to enhance quantitative and relationship query accuracy

## Current Implementation Issues

### Quantitative Queries
- Basic AST parsing for counting classes, functions, methods
- Simple line counting (includes comments, blank lines)
- No complexity metrics beyond basic cyclomatic complexity
- No maintainability or quality metrics

### Relationship Queries
- Basic pattern matching in code bodies
- Limited call graph accuracy
- No module dependency analysis
- Missing inheritance chain analysis

## Recommended Tools

### 1. **Radon** - Code Metrics
**Purpose:** Comprehensive code quality metrics  
**PyPI:** `radon`  
**Features:**
- **Cyclomatic Complexity (CC)**: More accurate than our AST-based approach
- **Maintainability Index (MI)**: 0-100 score for code maintainability
- **Halstead Metrics**: Volume, difficulty, effort, bugs estimate
- **Raw Metrics**: LOC, LLOC, SLOC, comments, multi-line strings
- **Per-function, per-class, per-module analysis**

**Usage:**
```python
from radon.complexity import cc_visit
from radon.metrics import mi_visit, h_visit
from radon.raw import analyze

# Cyclomatic complexity
cc_results = cc_visit(code)  # Returns list of ComplexityVisitor objects

# Maintainability index
mi_score = mi_visit(code, multi=True)

# Halstead metrics
h_metrics = h_visit(code)

# Raw metrics (LOC, SLOC, comments)
raw = analyze(code)
```

**Benefits:**
- Industry-standard metrics
- Fast and reliable
- Well-maintained library
- Integrates easily with our AST parsing

### 2. **CLOC** - Line Counting
**Purpose:** Accurate line counting across languages  
**Tool:** Command-line tool (not Python library)  
**Features:**
- Distinguishes code, comments, blank lines
- Supports 500+ languages
- Fast (written in Perl)
- JSON output for easy parsing

**Usage:**
```bash
cloc /path/to/code --json --by-file
```

**Alternative:** Use `pygount` (Python library with similar functionality)
```python
from pygount import SourceAnalysis

analysis = SourceAnalysis.from_file(file_path, "python")
print(f"Code lines: {analysis.code_count}")
print(f"Comment lines: {analysis.documentation_count}")
print(f"Empty lines: {analysis.empty_count}")
```

**Benefits:**
- More accurate than simple line counting
- Handles edge cases (multi-line strings, docstrings)
- Industry standard

### 3. **Pyan** - Call Graph Analysis
**Purpose:** Static call graph generation  
**PyPI:** `pyan3`  
**Features:**
- Generates call graphs from Python code
- Identifies function/method calls
- Supports class inheritance
- Can export to GraphViz, JSON

**Usage:**
```python
from pyan.analyzer import CallGraphVisitor
from pyan.visgraph import VisualGraph

# Analyze code
visitor = CallGraphVisitor(filenames)
visitor.analyze()

# Get call graph
graph = VisualGraph.from_visitor(visitor)
```

**Benefits:**
- More accurate than regex-based call detection
- Handles complex cases (decorators, lambdas)
- Can visualize relationships

### 4. **Vulture** - Dead Code Detection
**Purpose:** Find unused code  
**PyPI:** `vulture`  
**Features:**
- Detects unused functions, classes, variables
- Confidence scores for findings
- Helps identify code quality issues

**Usage:**
```python
from vulture import Vulture

v = Vulture()
v.scavenge(['/path/to/code'])
unused_code = v.get_unused_code()
```

**Benefits:**
- Identifies code that can be removed
- Improves codebase understanding
- Quality metric

### 5. **Prospector** - Multi-Tool Aggregator
**Purpose:** Runs multiple analysis tools  
**PyPI:** `prospector`  
**Features:**
- Aggregates: pylint, pyflakes, mccabe, pep8, pep257
- Single command for comprehensive analysis
- JSON output

**Usage:**
```bash
prospector /path/to/code --output-format json
```

**Benefits:**
- One tool to rule them all
- Comprehensive quality metrics
- Easy integration

### 6. **AST-based Tools** (Built-in)
**Purpose:** Deep code structure analysis  
**Library:** Python's `ast` module  
**Features:**
- Parse Python syntax trees
- Extract imports, calls, definitions
- Analyze decorators, type hints

**Enhanced Usage:**
```python
import ast

class CallGraphBuilder(ast.NodeVisitor):
    def __init__(self):
        self.calls = []
        self.imports = {}
        
    def visit_Call(self, node):
        # Extract function calls with context
        if isinstance(node.func, ast.Name):
            self.calls.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            self.calls.append(f"{node.func.value.id}.{node.func.attr}")
        self.generic_visit(node)
    
    def visit_Import(self, node):
        for alias in node.names:
            self.imports[alias.asname or alias.name] = alias.name
        self.generic_visit(node)
```

**Benefits:**
- No external dependencies
- Complete control
- Can extract any AST information

## Recommended Implementation Plan

### Phase 1: Enhanced Metrics (Immediate)
1. **Add Radon** for code metrics
   - Replace basic complexity with radon's CC
   - Add Maintainability Index
   - Add Halstead metrics
   - Add accurate LOC/SLOC/comments

2. **Add Pygount** for line counting
   - Replace simple line counting
   - Distinguish code vs comments vs blank

### Phase 2: Better Relationships (Next)
1. **Enhance AST-based call graph**
   - Use ast.NodeVisitor for accurate call detection
   - Track import aliases
   - Handle attribute access (obj.method)
   - Track decorators

2. **Add module dependency analysis**
   - Build import graph
   - Detect circular dependencies
   - Calculate coupling metrics

### Phase 3: Quality Metrics (Future)
1. **Add Vulture** for dead code detection
2. **Add Prospector** for comprehensive quality analysis
3. **Generate quality reports**

## Integration Strategy

### 1. Update `advisor/analytics.py`
```python
from radon.complexity import cc_visit
from radon.metrics import mi_visit, h_visit
from radon.raw import analyze
from pygount import SourceAnalysis

class EnhancedAnalyticsManager:
    def get_code_metrics(self, file_path):
        with open(file_path) as f:
            code = f.read()
        
        return {
            'complexity': cc_visit(code),
            'maintainability': mi_visit(code, multi=True),
            'halstead': h_visit(code),
            'raw': analyze(code),
            'lines': self._get_line_counts(file_path)
        }
    
    def _get_line_counts(self, file_path):
        analysis = SourceAnalysis.from_file(file_path, "python")
        return {
            'code': analysis.code_count,
            'comments': analysis.documentation_count,
            'blank': analysis.empty_count,
            'total': analysis.line_count
        }
```

### 2. Update `advisor/relationships.py`
```python
import ast

class EnhancedCallGraphBuilder(ast.NodeVisitor):
    def __init__(self):
        self.calls = []
        self.imports = {}
        self.current_class = None
        self.current_function = None
    
    def visit_ClassDef(self, node):
        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class
    
    def visit_FunctionDef(self, node):
        old_function = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old_function
    
    def visit_Call(self, node):
        call_info = self._extract_call_info(node)
        if call_info:
            self.calls.append({
                'caller': f"{self.current_class}.{self.current_function}" if self.current_class else self.current_function,
                'callee': call_info,
                'line': node.lineno
            })
        self.generic_visit(node)
```

## Dependencies to Add

```toml
# pyproject.toml
[project]
dependencies = [
    # ... existing ...
    "radon>=6.0.1",      # Code metrics
    "pygount>=1.6.1",    # Line counting
    "vulture>=2.10",     # Dead code detection
    # Optional:
    # "pyan3>=1.2.0",    # Call graph (if needed)
    # "prospector>=1.10", # Multi-tool analysis
]
```

## Expected Improvements

### Quantitative Queries
**Before:**
- "How many lines of code?" → Simple count (includes everything)
- "What's the complexity?" → Basic CC only

**After:**
- "How many lines of code?" → "2,590,706 total lines: 1,850,000 code, 450,000 comments, 290,706 blank"
- "What's the complexity?" → "Average CC: 3.2, Maintainability Index: 65/100, Halstead Volume: 125,000"
- "Show me code quality" → Comprehensive metrics with actionable insights

### Relationship Queries
**Before:**
- Basic regex matching
- Misses complex calls
- No import resolution

**After:**
- Accurate AST-based call detection
- Resolves imports and aliases
- Tracks method calls on objects
- Builds complete dependency graph

## Conclusion

**Recommended Approach:**
1. Start with **Radon** and **Pygount** (Phase 1) - Easy wins, big impact
2. Enhance AST-based relationship extraction (Phase 2) - Better accuracy
3. Add quality tools later (Phase 3) - Nice to have

**Estimated Effort:**
- Phase 1: 2-3 hours
- Phase 2: 3-4 hours
- Phase 3: 2-3 hours

**Total:** ~8-10 hours for comprehensive enhancement

Would you like me to proceed with Phase 1 implementation?