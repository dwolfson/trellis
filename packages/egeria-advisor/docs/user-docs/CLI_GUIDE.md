# Phase 6: CLI Interface - User Guide

**Status: live user documentation.** Moved out of `docs/history/` on 2026-09-03. It was filed there as `PHASE6_CLI_GUIDE`, but the CLI it documents still exists (`egeria-advisor = advisor.cli.main:cli`) and `--interactive` is still its real entry point. `CLI_COMMAND_AGENT_GUIDE.md` covers a different feature and never mentions this one. **`docs/history/` is gitignored, so until this move nobody cloning the repository could read it.**

## Overview

The Egeria Advisor CLI provides an easy-to-use command-line interface for querying the advisor system. It supports both direct queries and an interactive REPL mode.

## Installation

### 1. Install CLI Dependencies

```bash
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
source .venv/bin/activate

# Install with CLI dependencies
pip install -e ".[dev]"
```

### 2. Verify Installation

```bash
# Test CLI components
python scripts/test_cli.py

# Check CLI is available
egeria-advisor --help
```

## Usage

### Direct Queries

Ask a single question and get an immediate response:

```bash
# Basic query
egeria-advisor "How do I create a glossary?"

# With context
egeria-advisor "Show me examples" --context=glossary

# JSON output
egeria-advisor "What is a collection?" --format=json

# Markdown output
egeria-advisor "Explain assets" --format=markdown

# Without citations
egeria-advisor "What is OMVS?" --no-citations

# Verbose mode
egeria-advisor "How do I find assets?" --verbose
```

### Interactive Mode

Start an interactive session for multi-turn conversations:

```bash
# Start interactive mode
egeria-advisor --interactive
# or
egeria-advisor -i
```

#### Interactive Commands

Once in interactive mode, you can use these special commands:

- `/help` - Show help message
- `/clear` - Clear conversation context
- `/history` - Show query history
- `/verbose` - Toggle verbose mode
- `/citations` - Toggle citation display
- `/exit` or `/quit` - Exit interactive mode
- `Ctrl+D` - Exit interactive mode

#### Interactive Features

- **Command History**: Use ↑/↓ arrow keys to navigate previous queries
- **Auto-suggestions**: Get suggestions based on history
- **Context Preservation**: Conversation context is maintained across queries
- **Tab Completion**: Common words and commands are auto-completed

### Examples

#### Example 1: Getting Started

```bash
$ egeria-advisor "What is a glossary in Egeria?"

╭─────────────────────────────────────────────────────────╮
│ Query: What is a glossary in Egeria?                    │
╰─────────────────────────────────────────────────────────╯

Answer:
A glossary in Egeria is a collection of terms and their definitions...

Sources:
  • pyegeria/glossary_manager.py: GlossaryManager
  • docs/glossary-guide.md: Glossary Documentation

───────────────────────────────────────────────────────────
Response time: 1.23s | Sources: 2
```

#### Example 2: Code Examples

```bash
$ egeria-advisor "Show me how to create a glossary"

╭─────────────────────────────────────────────────────────╮
│ Query: Show me how to create a glossary                 │
╰─────────────────────────────────────────────────────────╯

Answer:
To create a glossary, use the GlossaryManager class...

Code Example:
┌─────────────────────────────────────────────────────────┐
│ 1 │ from pyegeria import GlossaryManager                │
│ 2 │                                                      │
│ 3 │ glossary_mgr = GlossaryManager(                     │
│ 4 │     server_name="view-server",                      │
│ 5 │     platform_url="https://localhost:9443",          │
│ 6 │     user_id="garygeeke"                             │
│ 7 │ )                                                    │
│ 8 │                                                      │
│ 9 │ glossary = glossary_mgr.create_glossary(            │
│10 │     display_name="My Glossary",                     │
│11 │     description="A sample glossary"                 │
│12 │ )                                                    │
└─────────────────────────────────────────────────────────┘
```

#### Example 3: Interactive Session

```bash
$ egeria-advisor --interactive

╭─────────────────────────────────────────────────────────╮
│ Egeria Advisor - Interactive Mode                       │
│                                                          │
│ Ask questions about Egeria concepts, get code examples, │
│ and receive guidance.                                    │
│                                                          │
│ Commands:                                                │
│   /help     - Show help                                  │
│   /clear    - Clear conversation context                 │
│   /history  - Show query history                         │
│   /exit     - Exit (or Ctrl+D)                          │
│                                                          │
│ Type your question and press Enter                       │
╰─────────────────────────────────────────────────────────╯

✓ All systems ready

egeria> What is a glossary?
[Response displayed...]

egeria> How do I create one?
[Response uses context from previous question...]

egeria> /history
Query History:

  1. What is a glossary?
  2. How do I create one?

egeria> /exit
Goodbye!
```

## Command-Line Options

### Global Options

```
egeria-advisor [OPTIONS] [QUERY]

Options:
  -i, --interactive              Start interactive mode
  -c, --context TEXT             Provide context for the query
  -f, --format [text|json|markdown]  Output format (default: text)
  --no-citations                 Hide source citations
  --no-color                     Disable colored output
  -v, --verbose                  Show detailed information
  --track / --no-track           Enable/disable MLflow tracking (default: on)
  --version                      Show version and exit
  --help                         Show help message and exit
```

### Format Options

#### Text Format (Default)

Rich formatted output with colors, syntax highlighting, and panels.

```bash
egeria-advisor "query" --format=text
```

#### JSON Format

Machine-readable JSON output for programmatic use.

```bash
egeria-advisor "query" --format=json
```

Output structure:
```json
{
  "query": "What is a glossary?",
  "response": "A glossary is...",
  "code_examples": ["..."],
  "sources": [
    {
      "file_path": "pyegeria/glossary_manager.py",
      "name": "GlossaryManager",
      "score": 0.95
    }
  ],
  "metadata": {
    "response_time": 1.23,
    "num_sources": 2
  }
}
```

#### Markdown Format

Markdown output suitable for documentation.

```bash
egeria-advisor "query" --format=markdown
```

## Configuration

### Environment Variables

The CLI respects these environment variables:

```bash
# Disable colors
NO_COLOR=1 egeria-advisor "query"

# Set default format
EGERIA_ADVISOR_FORMAT=json egeria-advisor "query"
```

### Configuration File

CLI settings can be configured in `config/advisor.yaml`:

```yaml
cli:
  default_format: text
  show_citations: true
  use_color: true
  prompt: "egeria> "
  history_file: "~/.egeria_advisor_history"
  max_history: 1000
  max_context_turns: 5
  timeout: 30
```

## Troubleshooting

### CLI Not Found

```bash
# Reinstall package
pip install -e ".[dev]"

# Check installation
which egeria-advisor
```

### Import Errors

```bash
# Install missing dependencies
pip install click rich prompt-toolkit pygments

# Or reinstall all
pip install -e ".[dev]"
```

### Connection Errors

```bash
# Check services are running
systemctl status ollama
docker ps | grep -E "milvus|mlflow"

# Test RAG system
python -c "from advisor.rag_system import get_rag_system; print(get_rag_system().health_check())"
```

### Slow Responses

```bash
# Use verbose mode to see timing
egeria-advisor "query" --verbose

# Check system resources
htop

# Check GPU usage (if using AMD GPU)
rocm-smi
```

## Tips & Best Practices

### 1. Use Interactive Mode for Exploration

Interactive mode is best for:
- Learning about Egeria concepts
- Exploring related topics
- Multi-step workflows
- Iterative refinement of queries

### 2. Use Direct Queries for Automation

Direct queries are best for:
- Scripts and automation
- CI/CD pipelines
- Quick lookups
- JSON output for parsing

### 3. Provide Context

Use the `--context` flag to get more relevant results:

```bash
egeria-advisor "Show examples" --context=glossary
egeria-advisor "How do I search?" --context=assets
```

### 4. Save Output

```bash
# Save to file
egeria-advisor "query" > output.txt

# Save JSON for processing
egeria-advisor "query" --format=json > result.json

# Save markdown for docs
egeria-advisor "query" --format=markdown > docs/query-result.md
```

### 5. Use History

In interactive mode, use arrow keys to recall previous queries and modify them.

## Advanced Usage

### Scripting

```bash
#!/bin/bash
# Script to query advisor and process results

QUERY="How do I create a glossary?"
RESULT=$(egeria-advisor "$QUERY" --format=json --no-track)

# Parse JSON with jq
RESPONSE=$(echo "$RESULT" | jq -r '.response')
echo "Answer: $RESPONSE"
```

### Batch Queries

```bash
# Process multiple queries
cat queries.txt | while read query; do
    echo "Query: $query"
    egeria-advisor "$query" --no-color
    echo "---"
done
```

### Integration with Other Tools

```bash
# Pipe to less for paging
egeria-advisor "long query" | less

# Search in output
egeria-advisor "query" | grep "keyword"

# Copy to clipboard (Linux)
egeria-advisor "query" | xclip -selection clipboard
```

## Performance

### Expected Response Times

- Simple queries: 1-2 seconds
- Complex queries: 2-4 seconds
- Code generation: 3-5 seconds

### Optimization Tips

1. **Use GPU acceleration** (if available)
2. **Keep Milvus warm** (first query may be slower)
3. **Limit context** in interactive mode
4. **Disable tracking** for faster responses: `--no-track`

## Support

### Getting Help

```bash
# CLI help
egeria-advisor --help

# Interactive help
egeria-advisor -i
egeria> /help
```

### Reporting Issues

If you encounter issues:

1. Run with `--verbose` to see detailed errors
2. Check service health
3. Review logs
4. Report with full error message

## Next Steps

- Try the interactive mode: `egeria-advisor -i`
- Explore different output formats
- Integrate into your workflow
- Provide feedback for improvements

---

**Version**: 0.1.0  
**Last Updated**: 2026-02-16  
**Status**: Phase 6 Implementation Complete