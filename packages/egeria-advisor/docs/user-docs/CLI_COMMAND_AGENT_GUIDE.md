# CLI Command Agent User Guide

**Version:** 1.0  
**Date:** 2026-03-07  
**Status:** Production Ready

## Overview

The CLI Command Agent is a specialized AI agent that answers questions about Egeria CLI commands. It provides intelligent, context-aware responses about:

- **hey_egeria commands** - Interactive CLI commands for Egeria operations
- **dr_egeria commands** - Markdown-based documentation processing

## Features

### 🎯 Intelligent Query Understanding
The agent automatically classifies your question and provides the most relevant response format:

- **List Queries**: "What commands are available?"
- **Usage Queries**: "How do I create a glossary?"
- **Parameter Queries**: "What parameters does list_assets take?"
- **General Queries**: Any other CLI-related questions

### 🔍 Semantic Search
Uses vector embeddings to find relevant commands even when you don't know the exact command name:

```
Query: "How do I make a new glossary?"
→ Finds: create_glossary command

Query: "Show me monitoring tools"
→ Finds: monitor_platform_status, monitor_server_status, etc.
```

### 📚 Comprehensive Information
For each command, the agent provides:
- Description and purpose
- Complete usage examples
- Required and optional parameters
- Parameter types and defaults
- Related commands

## Usage Examples

### Example 1: Finding Commands

**Query:**
```
What commands are available for managing glossaries?
```

**Response:**
```markdown
# Available Commands

## CAT Commands
- **create_glossary**: Create a new Glossary
- **delete_glossary**: Delete the glossary specified
- **list_glossaries**: List all glossaries
- **create_term**: Create a new term
- **delete_term**: Delete a glossary term
- **list_terms**: List glossary terms
...
```

### Example 2: Learning Command Usage

**Query:**
```
How do I create a glossary?
```

**Response:**
```markdown
# create_glossary

**Type:** hey_egeria
**Category:** cat

## Description
Create a new Glossary

## Usage
```bash
create_glossary --name "MyGlossary" --server view-server --url https://localhost:9443
```

## Parameters

### Required:
- **--name** (str): Name of Glossary

### Optional:
- **--language** (str) [default: English]: Language of Glossary
- **--description** (str) [default: A description goes here]: Description of Glossary
- **--usage** (str) [default: Definitions]: Purpose of glossary
- **--server** (str): Egeria view server to use
- **--url** (str): URL of view server to connect to
- **--userid** (str) [default: EGERIA_USER]: Egeria user
- **--password** (str) [default: EGERIA_USER_PASSWORD]: Egeria user password

## Related Commands
- **delete_glossary**: Delete the glossary specified
- **list_glossaries**: List all glossaries
```

### Example 3: Parameter Information

**Query:**
```
What parameters does monitor_platform_status take?
```

**Response:**
```markdown
# Parameters for monitor_platform_status

## Required Parameters
(None)

## Optional Parameters

**--server** (str) [default: active-metadata-store]
  Egeria metadata store to work with

**--url** (str) [default: https://localhost:9443]
  URL of Egeria metadata store platform to connect to

**--userid** (str) [default: erinoverview]
  Egeria user

**--timeout** (str) [default: 60]
  Number of seconds to wait
```

### Example 4: dr_egeria Commands

**Query:**
```
How do I use dr_egeria?
```

**Response:**
```markdown
# dr_egeria_md

**Type:** hey_egeria
**Category:** cat

## Description
Process a markdown file by parsing and executing Dr. Egeria commands

## Usage
```bash
# In markdown file:
# CreateGlossary
name: MyGlossary
description: A glossary for my project
---

# Process with:
dr_egeria_md --input-file my_doc.md --directive process
```

## Parameters
- **--input-file**: Markdown file to process
- **--output-folder**: Output folder
- **--directive**: How to process (display/validate/process)
- **--server**: Egeria view server
- **--url**: Platform URL
```

## Query Patterns

### Effective Queries

✅ **Good:**
- "How do I create a glossary?"
- "What monitoring commands are available?"
- "Show me all catalog commands"
- "What parameters does list_assets take?"
- "How do I delete a term?"

✅ **Also Good:**
- "Commands for managing glossaries"
- "Monitoring tools"
- "Asset listing options"
- "Glossary creation"

### Less Effective Queries

❌ **Too Vague:**
- "Help" (too general)
- "Commands" (too broad)

💡 **Better:**
- "What commands are available?"
- "Show me all commands"

❌ **Non-CLI Questions:**
- "What is Egeria?" (use general agent)
- "Explain metadata" (use documentation agent)

💡 **Better:**
- "How do I list metadata using CLI?"
- "What commands work with metadata?"

## Command Categories

### CAT (Catalog) - 38 commands
Asset, glossary, collection, and project management
- `create_glossary`, `list_assets`, `get_asset_graph`
- `create_term`, `list_terms`, `export_terms_to_csv_file`
- `list_collections`, `list_projects`

### OPS (Operations) - 22 commands
Server monitoring, daemon management, archives
- `monitor_platform_status`, `monitor_server_status`
- `refresh_integration_daemon`, `restart_integration_daemon`
- `load_archive`, `list_archives`

### TECH (Technical) - 26 commands
Technical metadata, types, relationships
- `list_asset_types`, `list_relationship_types`
- `get_guid_info`, `get_tech_details`
- `list_elements`, `list_relationships`

### MY (Personal) - 8 commands
User profile, roles, todos
- `list_my_profile`, `list_my_roles`
- `create_todo`, `mark_todo_complete`

### CLI (Interface) - 3 commands
Interactive interfaces
- `hey_egeria`, `hey_egeria_ops`
- `egeria_login`

## Integration with Other Agents

The CLI Command Agent works alongside other specialized agents:

- **Query Agent**: General Egeria questions
- **Code Example Agent**: Code samples and implementations
- **Egeria Agent**: Conceptual explanations

The system automatically routes your question to the most appropriate agent.

## Tips for Best Results

1. **Be Specific**: Include the action you want to perform
   - Good: "How do I create a glossary?"
   - Better: "How do I create a glossary with custom language?"

2. **Use Keywords**: Include relevant terms
   - "command", "how do I", "parameters", "usage"

3. **Ask Follow-ups**: The agent maintains context
   - First: "How do I create a glossary?"
   - Then: "What about deleting it?"

4. **Explore Categories**: Browse by category
   - "Show me all monitoring commands"
   - "What catalog commands are available?"

## Troubleshooting

### No Results Found

If the agent can't find matching commands:

1. **Try different keywords**
   - Instead of: "make glossary"
   - Try: "create glossary"

2. **Check spelling**
   - Command names are case-sensitive in searches

3. **Browse by category**
   - "Show me all catalog commands"
   - Then find the specific command you need

4. **Use general terms**
   - "glossary commands"
   - "monitoring tools"

### Unexpected Results

If results don't match your expectation:

1. **Refine your query**
   - Add more context
   - Be more specific about what you want

2. **Check command type**
   - Specify "hey_egeria" or "dr_egeria" if needed

3. **Ask for clarification**
   - "What's the difference between list_assets and get_asset_graph?"

## Advanced Usage

### Combining with RAG

The CLI Command Agent can be used with the RAG system for comprehensive answers:

```python
from advisor.agents.cli_command_agent import CLICommandAgent

agent = CLICommandAgent()

# Get command information
response = agent.query("How do I create a glossary?")
print(response)

# Check if agent can handle a query
if agent.can_handle("What commands are available?"):
    response = agent.query("What commands are available?")
```

### Programmatic Access

```python
from advisor.data_prep.cli_indexer import CLICommandIndexer

indexer = CLICommandIndexer()

# Search for commands
results = indexer.search_commands(
    query="glossary management",
    top_k=5
)

for result in results:
    print(f"Command: {result.metadata['command_name']}")
    print(f"Score: {result.score}")
    print(f"Description: {result.metadata['description']}")
```

## Maintenance

### Updating Command Index

When new commands are added to pyegeria:

```bash
# 1. Extract commands
python scripts/test_cli_parser.py

# 2. Index commands
python scripts/index_cli_commands.py

# 3. Verify
python scripts/test_cli_agent.py
```

### Monitoring

The agent tracks:
- Query patterns
- Most-asked commands
- Search accuracy
- Response times

View metrics in the dashboard under "CLI Command Queries"

## Support

For issues or questions:
1. Check this guide
2. Review command examples
3. Try the test scripts
4. Check the design document: `docs/design/AGENTS_AND_CODE_ANALYSIS.md` (§1)

## Version History

### v1.0 (2026-03-07)
- Initial release
- 100 commands indexed (99 hey_egeria + 1 dr_egeria)
- Semantic search
- Multiple response formats
- LLM-powered general responses