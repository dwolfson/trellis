# Egeria-Advisor-Pro — a specialist-agent product track

**Status: UNBUILT.** Split out of `RUNTIME_AND_HARDWARE.md` on
2026-09-03 and moved to `future/`, because none of it exists: `advisor/tools/`
holds different files entirely, and `advisor/agents/pro/` was never created.

Checked 2026-09-03 — every artefact this plan names is absent:
`code_generation_tool.py`, `test_generation_tool.py`, `refactoring_tool.py`,
`dependency_tool.py`, `base_specialist.py`, `orchestrator.py`.

It shared a document with the ONNX migration, which *was* built. Keeping the two
together meant a 9-week unstarted product plan sat under the same heading as
completed infrastructure work, and the document's own status line could only be
right about one of them.

---

## Track B: Egeria-Advisor-Pro (9 weeks)

### Phase 1: Enhanced Tool Ecosystem (3 weeks)

#### Week 4: Code Generation Tool

**Objective**: Enable AI-powered code generation for Egeria

**Tasks**:
1. Design code generation prompt templates
2. Implement `CodeGenerationTool` with BeeAI
3. Add code validation and syntax checking
4. Create examples and tests

**Implementation**:
```python
# advisor/tools/code_generation_tool.py
class CodeGenerationTool(Tool):
    """Generate Python/Java code for Egeria operations."""
    
    def run(self, description: str, language: str = "python") -> JSONToolOutput:
        """
        Generate code from natural language description.
        
        Examples:
        - "Create a function to get all assets from a glossary"
        - "Generate a class to manage server connections"
        """
        # Use RAG to find similar code examples
        # Use LLM to generate new code based on examples
        # Validate syntax
        # Return formatted code with explanation
```

**Test Cases**:
- Generate asset retrieval function
- Generate glossary term creation code
- Generate server connection manager class
- Validate generated code compiles/runs

**Success Criteria**:
- ✓ Generated code is syntactically correct (>95%)
- ✓ Generated code follows Egeria patterns
- ✓ Includes proper error handling and docstrings
- ✓ User satisfaction >80%

#### Week 5: Test Generation Tool

**Objective**: Automatically generate unit tests for code

**Tasks**:
1. Implement `TestGenerationTool`
2. Support pytest and JUnit test generation
3. Generate test fixtures and mocks
4. Add coverage analysis

**Implementation**:
```python
# advisor/tools/test_generation_tool.py
class TestGenerationTool(Tool):
    """Generate unit tests for Egeria code."""
    
    def run(self, code: str, framework: str = "pytest") -> JSONToolOutput:
        """
        Generate comprehensive unit tests.
        
        Generates:
        - Happy path tests
        - Error handling tests
        - Edge case tests
        - Mock fixtures
        """
```

**Test Cases**:
- Generate tests for asset manager class
- Generate tests for API client
- Generate tests with mocks for external services
- Validate tests run and pass

**Success Criteria**:
- ✓ Generated tests are valid (>90%)
- ✓ Tests achieve >80% code coverage
- ✓ Tests include edge cases and error handling
- ✓ User satisfaction >75%

#### Week 6: Refactoring & Dependency Tools

**Objective**: Code improvement and analysis tools

**Tasks**:
1. Implement `RefactoringTool` (suggest improvements)
2. Implement `DependencyAnalysisTool` (map relationships)
3. Add code quality metrics
4. Create visualization for dependencies

**Tools**:
```python
# advisor/tools/refactoring_tool.py
class RefactoringTool(Tool):
    """Suggest code improvements and refactorings."""
    
    def run(self, code: str) -> JSONToolOutput:
        """
        Analyze code and suggest improvements:
        - Extract methods
        - Reduce complexity
        - Improve naming
        - Add type hints
        """

# advisor/tools/dependency_tool.py
class DependencyAnalysisTool(Tool):
    """Analyze code dependencies and relationships."""
    
    def run(self, element_name: str) -> JSONToolOutput:
        """
        Map dependencies:
        - What uses this element
        - What this element uses
        - Dependency graph
        - Impact analysis
        """
```

**Success Criteria**:
- ✓ Refactoring suggestions are valid (>85%)
- ✓ Dependency analysis is accurate (>90%)
- ✓ Visualizations are clear and useful
- ✓ User satisfaction >70%

### Phase 2: Multi-Agent System (6 weeks)

#### Week 7-8: Specialist Agents

**Objective**: Create focused agents for different tasks

**Agents to Implement**:

1. **CodeAgent** (`advisor/agents/pro/code_agent.py`)
   - Specializes in code generation and analysis
   - Uses CodeGenerationTool, RefactoringTool
   - Trained on code patterns

2. **DocsAgent** (`advisor/agents/pro/docs_agent.py`)
   - Expert in Egeria concepts and documentation
   - Uses DocumentationLookupTool
   - Provides conceptual explanations

3. **TestAgent** (`advisor/agents/pro/test_agent.py`)
   - Specializes in test generation and coverage
   - Uses TestGenerationTool
   - Ensures code quality

4. **DebugAgent** (`advisor/agents/pro/debug_agent.py`)
   - Troubleshooting and error analysis
   - Uses DependencyAnalysisTool
   - Provides debugging guidance

**Architecture**:
```python
# advisor/agents/pro/base_specialist.py
class SpecialistAgent(BaseAgent):
    """Base class for specialist agents."""
    
    def __init__(self, specialty: str, tools: List[Tool]):
        self.specialty = specialty
        self.tools = tools
        self.memory = TokenMemory(max_tokens=8000)
        self.cache = SlidingCache(size=100)
    
    async def handle_query(self, query: str) -> Dict[str, Any]:
        """Handle query within specialty."""
        # Check if query matches specialty
        # Use appropriate tools
        # Generate specialized response
```

**Success Criteria**:
- ✓ Each agent performs better in its specialty (>20% improvement)
- ✓ Agents have distinct personalities and approaches
- ✓ Memory and caching work correctly
- ✓ All agents integrate with monitoring

#### Week 9-10: Agent Orchestration

**Objective**: Master agent that routes to specialists

**Implementation**:
```python
# advisor/agents/pro/orchestrator.py
class OrchestratorAgent:
    """Master agent that routes queries to specialists."""
    
    def __init__(self):
        self.specialists = {
            "code": CodeAgent(),
            "docs": DocsAgent(),
            "test": TestAgent(),
            "debug": DebugAgent()
        }
        self.router = QueryRouter()  # Intelligent routing
    
    async def process_query(self, query: str) -> Dict[str, Any]:
        """
        Route query to appropriate specialist(s).
        
        Routing logic:
        1. Analyze query complexity
        2. Determine required specialists
        3. Execute in parallel or sequence
        4. Combine results
        """
        # Simple query -> Use current system (fast path)
        if self.router.is_simple(query):
            return await self.simple_agent.run(query)
        
        # Complex query -> Route to specialists
        specialists_needed = self.router.select_specialists(query)
        
        # Execute specialists
        results = await self._execute_specialists(
            query, specialists_needed
        )
        
        # Combine and synthesize
        return await self._synthesize_results(query, results)
```

**Routing Strategies**:
- **Simple**: Single specialist (e.g., "What is an Asset?" → DocsAgent)
- **Sequential**: Chain specialists (e.g., "Generate code and tests" → CodeAgent → TestAgent)
- **Parallel**: Multiple specialists (e.g., "Analyze this code" → CodeAgent + DebugAgent)
- **Iterative**: Multi-round refinement (e.g., "Generate, review, improve")

**Success Criteria**:
- ✓ Routing accuracy >85%
- ✓ Complex queries handled correctly (>80% success)
- ✓ Response time <30s for multi-agent queries
- ✓ User satisfaction >75%

#### Week 11-12: Workflows & Integration

**Objective**: Pre-built workflows for common tasks

**Workflows to Implement**:

1. **Code Review Workflow** (`advisor/workflows/code_review.py`)
   ```python
   async def code_review_workflow(code: str) -> Dict[str, Any]:
       """
       Automated code review:
       1. CodeAgent: Analyze code quality
       2. TestAgent: Check test coverage
       3. DebugAgent: Find potential issues
       4. Generate review report
       """
   ```

2. **Feature Scaffold Workflow** (`advisor/workflows/feature_scaffold.py`)
   ```python
   async def feature_scaffold_workflow(description: str) -> Dict[str, Any]:
       """
       Generate complete feature:
       1. DocsAgent: Understand requirements
       2. CodeAgent: Generate implementation
       3. TestAgent: Generate tests
       4. Package as PR-ready code
       """
   ```

3. **Migration Workflow** (`advisor/workflows/migration.py`)
   ```python
   async def migration_workflow(old_api: str, new_api: str) -> Dict[str, Any]:
       """
       API migration assistance:
       1. Find all usages of old API
       2. Generate replacement code
       3. Generate tests for new code
       4. Create migration guide
       """
   ```

**CLI Integration**:
```bash
# Use pro mode
egeria-advisor --mode pro "Generate a feature to export glossary terms to CSV"

# Use specific workflow
egeria-advisor --workflow code-review --file my_code.py

# Use specific agent
egeria-advisor --agent code "Generate an asset manager class"
```

**Success Criteria**:
- ✓ Workflows complete successfully (>80%)
- ✓ Generated artifacts are production-ready (>70%)
- ✓ Workflows save significant time (>50% reduction)
- ✓ User satisfaction >80%

---

## Project Structure

```
egeria-advisor/
├── advisor/
│   ├── embeddings.py              # Updated with ONNX support
│   ├── embeddings_onnx.py         # NEW: ONNX implementation
│   ├── agents/
│   │   ├── conversation_agent.py  # Existing (keep)
│   │   └── pro/                   # NEW: Pro agents
│   │       ├── __init__.py
│   │       ├── base_specialist.py
│   │       ├── code_agent.py
│   │       ├── docs_agent.py
│   │       ├── test_agent.py
│   │       ├── debug_agent.py
│   │       └── orchestrator.py
│   ├── tools/
│   │   ├── beeai_tools.py         # Existing
│   │   ├── code_generation_tool.py # NEW
│   │   ├── test_generation_tool.py # NEW
│   │   ├── refactoring_tool.py     # NEW
│   │   └── dependency_tool.py      # NEW
│   ├── workflows/                  # NEW
│   │   ├── __init__.py
│   │   ├── code_review.py
│   │   ├── feature_scaffold.py
│   │   └── migration.py
│   └── cli/
│       ├── main.py                # Existing
│       └── pro_main.py            # NEW: Pro CLI
├── models/
│   └── all-MiniLM-L6-v2.onnx     # NEW: ONNX model
├── scripts/
│   ├── convert_to_onnx.py        # NEW
│   ├── benchmark_onnx.py         # NEW
│   └── migrate_to_onnx.py        # NEW
├── docs/
│   ├── design/
│   │   └── RUNTIME_AND_HARDWARE.md  # This file
│   └── user-docs/
│       ├── ONNX_MIGRATION_GUIDE.md               # NEW
│       └── PRO_MODE_GUIDE.md                     # NEW
└── tests/
    ├── unit/
    │   ├── test_onnx_embeddings.py               # NEW
    │   └── test_pro_agents.py                    # NEW
    └── integration/
        └── test_pro_workflows.py                 # NEW
```

---

## Dependencies to Add

```toml
[project]
dependencies = [
    # ... existing ...
    "onnxruntime>=1.16.0",
    "beeai-framework>=0.1.0",  # If not already present
]

[project.optional-dependencies]
gpu = [
    "onnxruntime-gpu>=1.16.0",
]

pro = [
    "tree-sitter>=0.20.0",      # Code parsing
    "black>=24.0.0",            # Code formatting
    "autopep8>=2.0.0",          # Code formatting
    "pylint>=3.0.0",            # Code analysis
    "networkx>=3.0",            # Dependency graphs
    "graphviz>=0.20",           # Visualization
]
```

---

## Risk Management

### ONNX Migration Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| ONNX model quality degradation | High | Low | Extensive validation, fallback to PyTorch |
| Platform compatibility issues | Medium | Medium | Test on all platforms, provide CPU fallback |
| Performance not as expected | Medium | Low | Benchmark early, adjust expectations |
| User migration friction | Low | Medium | Provide clear guide, make optional |

### Pro Track Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Agent quality below expectations | High | Medium | Extensive testing, user feedback loops |
| Complexity too high | Medium | Medium | Keep simple path (current system) available |
| Low adoption | Medium | High | Make opt-in, gather feedback, iterate |
| Maintenance burden | Medium | Medium | Good documentation, modular design |

---

## Success Metrics

### ONNX Migration
- **Performance**: 2-3x speedup, 50% memory reduction
- **Quality**: Hallucination rate ≤4% (no degradation)
- **Compatibility**: Works on NVIDIA, AMD, Apple, CPU
- **Adoption**: 100% of users (transparent migration)

### Pro Track
- **Adoption**: >20% of users try pro features
- **Satisfaction**: >75% positive feedback
- **Quality**: >80% success rate for complex tasks
- **Performance**: <30s for multi-agent workflows
- **Value**: >50% time savings for complex tasks

---

## Timeline Summary

| Week | Track A (ONNX) | Track B (Pro) |
|------|----------------|---------------|
| 1 | Model conversion & testing | - |
| 2 | Integration & compatibility | - |
| 3 | Production deployment | - |
| 4 | - | Code generation tool |
| 5 | - | Test generation tool |
| 6 | - | Refactoring & dependency tools |
| 7-8 | - | Specialist agents |
| 9-10 | - | Agent orchestration |
| 11-12 | - | Workflows & integration |

**Total**: 12 weeks (3 months)

---

## Next Steps

1. **Week 0 (Prep)**:
   - Get stakeholder approval
   - Assign developers (2 for ONNX, 2-3 for Pro)
   - Set up project tracking
   - Create detailed task breakdown

2. **Week 1 (Kickoff)**:
   - Start ONNX model conversion
   - Begin design docs for Pro agents
   - Set up monitoring for both tracks

3. **Weekly Reviews**:
   - Demo progress every Friday
   - Adjust plan based on learnings
   - Gather early user feedback

4. **Go/No-Go Decision Points**:
   - Week 3: ONNX migration quality check
   - Week 6: Pro tools adoption check
   - Week 10: Pro agents quality check

---

## Conclusion

This plan provides a structured approach to:
1. Improve performance and cross-platform support (ONNX)
2. Add advanced capabilities (Pro track)
3. Minimize risk (dual-track, fallbacks, validation)
4. Maximize learning (experimental pro features)

Both tracks are valuable independently and complementary together.