# CLI Command Agent Design

**Date:** 2026-03-07  
**Purpose:** Design a specialized agent to answer questions about hey_egeria and dr_egeria CLI commands

## Overview

Users need to query information about:
1. **hey_egeria commands** - Interactive CLI commands for Egeria operations
2. **dr_egeria commands** - Markdown-based documentation processing commands

This requires a specialized agent that can extract, index, and query CLI command metadata.

## Current State Analysis

### hey_egeria Commands
**Location:** `data/repos/egeria-python/pyproject.toml` (lines 47-168)

**Structure:**
```toml
[project.scripts]
    command_name = "module.path:function_name"
```

**Examples:**
- `hey_egeria = "commands.cli.egeria:cli"` - Main CLI entry point
- `list_assets = "commands.cat.list_assets:main"`
- `create_glossary = "commands.cat.glossary_actions:create_glossary"`
- `monitor_platform_status = "commands.ops.monitor_platform_status:main"`

**Command Categories:**
1. **Catalog (cat)** - Asset, glossary, collection, project management
2. **Operations (ops)** - Server monitoring, daemon management, archives
3. **My** - User profile, roles, todos
4. **Tech** - Technical metadata, types, relationships
5. **CLI** - Interactive TUI interfaces

**Documentation Sources:**
1. **Click decorators** in Python files - `@click.command()`, `@click.option()`
2. **Docstrings** in command functions
3. **TUI interface** - `commands/cli/egeria.py` uses Trogon for interactive help

### dr_egeria Commands
**Location:** `data/repos/egeria-python/md_processing/`

**Structure:**
- Markdown-based command system
- Commands embedded in markdown files with `# CommandName` headers
- Dispatcher pattern: `md_processing/command_mapping.py`
- Command handlers in `md_processing/md_commands/`

**Command Types:**
1. **Glossary commands** - Create/update/delete terms, categories
2. **Project commands** - Project management
3. **Governance officer commands** - Governance actions
4. **Data designer commands** - Data structures
5. **Solution architect commands** - Architecture elements
6. **Feedback commands** - User feedback
7. **View commands** - Display operations

**Documentation Sources:**
1. **Command handler classes** - Pydantic models with field descriptions
2. **Docstrings** in handler methods
3. **Template files** - Example markdown with command syntax

## Proposed Solution

### Phase 1: CLI Command Extractor (2-3 hours)

Create `advisor/data_prep/cli_parser.py`:

```python
class CLICommandExtractor:
    """Extract CLI command metadata from pyegeria repository."""
    
    def extract_hey_egeria_commands(self, pyproject_path: str) -> List[Dict]:
        """
        Parse pyproject.toml to extract command definitions.
        
        Returns:
            List of command metadata:
            - command_name: str
            - module_path: str
            - function_name: str
            - category: str (cat/ops/my/tech/cli)
        """
        
    def extract_command_details(self, module_path: str, function_name: str) -> Dict:
        """
        Parse Python file to extract:
        - Click decorators (@click.command, @click.option)
        - Docstrings
        - Parameter descriptions
        - Help text
        """
        
    def extract_dr_egeria_commands(self, md_processing_path: str) -> List[Dict]:
        """
        Parse md_processing directory to extract:
        - Command names from dispatcher
        - Handler classes
        - Pydantic model schemas
        - Field descriptions
        """
```

### Phase 2: CLI Command Indexer (1-2 hours)

Extend `advisor/data_prep/pipeline.py`:

```python
def index_cli_commands(self):
    """
    Index CLI commands into vector store.
    
    Creates documents with:
    - Command name and aliases
    - Description
    - Parameters and options
    - Usage examples
    - Category/type
    """
```

**Metadata Structure:**
```json
{
  "command_name": "create_glossary",
  "type": "hey_egeria",
  "category": "catalog",
  "description": "Create a new glossary in Egeria",
  "parameters": [
    {
      "name": "--name",
      "type": "str",
      "required": true,
      "description": "Name of the glossary"
    }
  ],
  "usage_example": "create_glossary --name 'My Glossary'",
  "module": "commands.cat.glossary_actions",
  "function": "create_glossary"
}
```

### Phase 3: CLI Command Agent (2-3 hours)

Create `advisor/agents/cli_command_agent.py`:

```python
class CLICommandAgent(BaseAgent):
    """
    Specialized agent for CLI command queries.
    
    Handles questions like:
    - "How do I create a glossary?"
    - "What commands are available for monitoring?"
    - "Show me all dr_egeria commands"
    - "What parameters does list_assets take?"
    """
    
    def __init__(self, rag_system, llm_client):
        self.rag_system = rag_system
        self.llm_client = llm_client
        self.command_index = self._load_command_index()
        
    def query(self, user_query: str) -> str:
        """
        Process CLI command queries.
        
        Steps:
        1. Classify query type (command search, parameter info, usage)
        2. Search command index
        3. Retrieve relevant documentation
        4. Generate response with examples
        """
        
    def _search_commands(self, query: str) -> List[Dict]:
        """Search commands by name, category, or description."""
        
    def _get_command_details(self, command_name: str) -> Dict:
        """Get full details for a specific command."""
        
    def _generate_usage_example(self, command: Dict) -> str:
        """Generate usage example from command metadata."""
```

### Phase 4: Integration (1 hour)

1. **Add to query router** - Detect CLI command queries
2. **Update collections** - Add `cli_commands` collection
3. **Add to dashboard** - Show CLI command query metrics

## Implementation Strategy

### Step 1: Extract hey_egeria Commands
- Parse `pyproject.toml` for `[project.scripts]`
- For each command, parse the Python file
- Extract Click decorators and docstrings
- Store in `cache/cli_commands.json`

### Step 2: Extract dr_egeria Commands
- Parse `md_processing/command_mapping.py` for dispatcher
- For each command handler, extract Pydantic schema
- Parse docstrings and field descriptions
- Store in `cache/dr_egeria_commands.json`

### Step 3: Create Vector Embeddings
- Generate embeddings for command descriptions
- Index with metadata (category, parameters, type)
- Store in Milvus `cli_commands` collection

### Step 4: Build Agent
- Implement query classification
- Add command search logic
- Generate formatted responses with examples
- Integrate with existing RAG system

## Query Examples

### hey_egeria Queries
```
Q: "How do I list all glossaries?"
A: Use the `list_glossaries` command:
   
   list_glossaries --server view-server --url https://localhost:9443
   
   Options:
   --server: Egeria view server (default: view-server)
   --url: Platform URL (default: https://localhost:9443)
   --userid: User ID (default: erinoverview)

Q: "What monitoring commands are available?"
A: Available monitoring commands:
   - monitor_platform_status: Monitor platform health
   - monitor_server_status: Monitor server status
   - monitor_engine_activity: Monitor governance engine activity
   - monitor_daemon_status: Monitor integration daemon status
   ...
```

### dr_egeria Queries
```
Q: "How do I create a glossary with dr_egeria?"
A: Use the CreateGlossary command in markdown:
   
   # CreateGlossary
   name: My Glossary
   description: A glossary for my project
   ---
   
   Then process with:
   dr_egeria_md --input-file my_doc.md --directive process

Q: "What dr_egeria commands are available?"
A: Available dr_egeria commands:
   - CreateGlossary: Create a new glossary
   - CreateTerm: Create a glossary term
   - CreateProject: Create a project
   - AddFeedback: Add feedback to an element
   ...
```

## Benefits

1. **Improved Discoverability** - Users can easily find commands
2. **Better Documentation** - Structured command information
3. **Usage Examples** - Auto-generated examples from metadata
4. **Category Browsing** - Find commands by category
5. **Parameter Help** - Detailed parameter descriptions

## Estimated Effort

- **Phase 1 (Extractor):** 2-3 hours
- **Phase 2 (Indexer):** 1-2 hours  
- **Phase 3 (Agent):** 2-3 hours
- **Phase 4 (Integration):** 1 hour

**Total:** 6-9 hours

## Next Steps

1. Create `advisor/data_prep/cli_parser.py`
2. Implement hey_egeria command extraction
3. Implement dr_egeria command extraction
4. Add CLI command indexing to pipeline
5. Create CLI command agent
6. Add query routing for CLI queries
7. Test with sample queries
8. Document usage

## Alternative Approaches

### Option A: Static Documentation (Current)
- Manually maintain command documentation
- **Pros:** Simple, no code changes
- **Cons:** Outdated, incomplete, hard to search

### Option B: Dynamic Extraction (Proposed)
- Auto-extract from source code
- **Pros:** Always up-to-date, comprehensive, searchable
- **Cons:** Requires implementation effort

### Option C: Hybrid Approach
- Extract basic info from code
- Enhance with manual examples/tutorials
- **Pros:** Best of both worlds
- **Cons:** More maintenance

**Recommendation:** Option B (Dynamic Extraction) with Option C enhancements later.