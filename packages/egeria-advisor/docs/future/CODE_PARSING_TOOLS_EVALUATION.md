# Code Parsing Tools Evaluation

## Current Implementation: Python AST

We currently use Python's built-in `ast` module for parsing Python code:
- **Location**: `advisor/data_prep/code_parser.py`
- **Status**: ✅ Working well, zero dependencies
- **Capabilities**:
  - Extracts classes, methods, functions
  - Captures signatures, docstrings, decorators
  - Identifies async/private methods
  - Calculates complexity metrics
  - Handles type annotations

## Alternative Tools for Future Enhancement

### 1. tree-sitter-python

**Description**: Incremental parsing library with Python grammar support

**Pros**:
- More robust error recovery (handles incomplete/malformed code)
- Incremental parsing (only re-parses changed sections)
- Uniform API across multiple languages
- Fast and memory-efficient
- Used by GitHub for code navigation

**Cons**:
- Additional dependency
- More complex API than AST
- Requires language-specific grammar files

**Use Cases**:
- Multi-language parsing (Java + Python + JavaScript)
- IDE-like features (syntax highlighting, code folding)
- Parsing incomplete code during editing
- Real-time code analysis

**Integration Effort**: Medium
- Install: `pip install tree-sitter tree-sitter-python`
- Adapt existing parser to tree-sitter API
- Handle language-specific grammars

**Recommendation**: Consider if we need to:
- Parse Java code with same infrastructure
- Handle malformed code gracefully
- Build real-time code analysis features

### 2. Jedi

**Description**: Python autocompletion and static analysis library

**Pros**:
- Resolves imports and cross-module references
- Type inference and type checking
- Go-to-definition, find-references
- Understands Python semantics, not just syntax
- Used by many Python IDEs

**Cons**:
- Slower than AST (needs to resolve imports)
- Requires Python environment setup
- More complex than simple parsing

**Use Cases**:
- Understanding code relationships and dependencies
- Type inference for better metadata
- Building IDE-like navigation features
- Analyzing import graphs

**Integration Effort**: Medium-High
- Install: `pip install jedi`
- Set up Python environment for analysis
- Handle import resolution
- Extract relationship data

**Recommendation**: Consider for:
- Enhanced relationship extraction
- Cross-module dependency analysis
- Type-aware code search

### 3. SeaGOAT (Semantic Grep)

**Description**: Semantic code search using embeddings and vector similarity

**Pros**:
- Semantic search (not just keyword matching)
- Uses embeddings like our system
- Handles natural language queries
- Open source and actively maintained

**Cons**:
- Overlaps with our existing functionality
- Another embedding model to manage
- May not integrate well with our architecture

**Use Cases**:
- Inspiration for our semantic search features
- Benchmark against our implementation
- Learn from their query understanding

**Integration Effort**: Low (for learning) / High (for integration)
- Study their approach to semantic code search
- Compare with our RAG system
- Potentially adopt their query parsing techniques

**Recommendation**: 
- Study as reference implementation
- Don't integrate directly (we have similar functionality)
- Learn from their query understanding and ranking

### 4. Cline (AI Coding Assistant)

**Description**: AI-powered coding assistant (not a parsing tool)

**Pros**:
- Can generate code based on natural language
- Understands context and intent
- Could complement our system

**Cons**:
- Not a parsing tool
- Separate AI agent
- May duplicate functionality

**Use Cases**:
- Code generation tasks
- Refactoring assistance
- Could be integrated as MCP server

**Integration Effort**: Medium
- Set up as MCP server
- Define tool interfaces
- Integrate with our agent system

**Recommendation**:
- Consider as MCP server for code generation
- Complement our code search with code generation
- Evaluate if it adds value beyond our agents

## Decision Matrix

| Tool | Parsing | Analysis | Multi-Lang | Complexity | Priority |
|------|---------|----------|------------|------------|----------|
| Python AST (current) | ✅ | ⚠️ | ❌ | Low | - |
| tree-sitter | ✅ | ⚠️ | ✅ | Medium | Medium |
| Jedi | ⚠️ | ✅ | ❌ | High | Low |
| SeaGOAT | ❌ | ✅ | ✅ | Medium | Low |
| Cline | ❌ | ❌ | ✅ | Medium | Low |

## Recommendations

### Short Term (Current Phase)
- ✅ **Keep Python AST**: It's working perfectly for our needs
- ✅ **Focus on metadata filtering**: Complete the current implementation
- ✅ **Measure performance**: Validate 10-100x improvement claims

### Medium Term (Next 3-6 months)
- 🔄 **Evaluate tree-sitter**: If we need Java code parsing
- 🔄 **Study SeaGOAT**: Learn from their semantic search approach
- 🔄 **Consider Jedi**: If we need cross-module analysis

### Long Term (6+ months)
- 🔮 **Multi-language support**: Use tree-sitter for Java + Python
- 🔮 **Enhanced relationships**: Use Jedi for import graph analysis
- 🔮 **Code generation**: Integrate Cline as MCP server

## Current Status

**What We Have**:
- ✅ Python AST parser extracting 5,023 code elements
- ✅ Metadata filtering infrastructure ready
- ✅ Vector store with scalar fields for fast filtering
- ⏳ Currently indexing PyEgeria code

**What We Need**:
- ⏳ Complete indexing (in progress)
- ⏳ Enable metadata filtering in agents
- ⏳ Test and measure performance improvements

**What We Don't Need Yet**:
- ❌ Multi-language parsing (only Python for now)
- ❌ Cross-module analysis (not required yet)
- ❌ Code generation (have other priorities)

## Conclusion

**Current approach is optimal** for our immediate needs. The Python AST parser is:
- Fast and reliable
- Zero dependencies
- Extracting all needed metadata
- Working perfectly with our vector store

**Future enhancements** should be driven by actual needs:
- Need Java parsing? → tree-sitter
- Need type inference? → Jedi
- Need code generation? → Cline as MCP server

**Don't over-engineer**: Add complexity only when there's a clear benefit.

---

*Last Updated: 2026-03-09*
*Status: Recommendation - Keep Python AST for now*