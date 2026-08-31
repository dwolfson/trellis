# Follow-Up Query Routing Fix

**This is a historical bug-fix record (Mar 2026, CLI follow-up query context), not a living
guide** — the fix described here has been shipped. Kept for reference on the root cause and
fix approach. For current routing behavior, see the [Query Routing Guide](QUERY_ROUTING_GUIDE.md).

## Problem Summary

When users selected follow-up options (e.g., "1. See detailed method documentation"), the system was routing to semantic search instead of maintaining PyEgeria agent context, causing:
- Hallucinated method names
- Generic responses instead of specific PyEgeria information
- Loss of context between queries

## Root Causes

1. **Follow-up queries lacked PyEgeria context**: When CLI converted "1" to "Show me the documentation for CollectionManager", it didn't include PyEgeria-specific terms
2. **PyEgeria detection patterns too narrow**: "what does" wasn't in the detection patterns
3. **No agent type tracking**: System didn't remember which agent handled the previous query

## Fixes Applied

### 1. Agent Type Tracking (advisor/cli/agent_session.py)
```python
# Track which agent handled each query
self.last_agent_type: Optional[str] = None

# When follow-up detected and last agent was PyEgeria:
if is_follow_up and self.last_agent_type == "pyegeria":
    topic = self._extract_topic_from_query(self.last_query)
    if topic:
        # Add PyEgeria context to maintain routing
        query = f"{query} for PyEgeria {topic}"
```

### 2. Return Agent Type (advisor/agents/conversation_agent.py)
```python
return {
    "content": response_content,
    "sources": pyegeria_response.get('sources', []),
    "agent_type": "pyegeria",  # Top-level for CLI tracking
    "follow_up_options": pyegeria_response.get('follow_up_options', []),
    ...
}
```

### 3. Expanded Detection Patterns (advisor/agents/pyegeria_agent.py)
```python
class_query_patterns = [
    'what methods', 'methods does', 'methods in', 'methods of',
    'tell me about', 'what is', 'what does',  # Added "what does"
    'show me the', 'show me', 'documentation for',  # Added for follow-ups
    ...
]
```

## How to Use

### Correct CLI Usage

**Agent Mode (Interactive with Memory):**
```bash
# If installed via pip (recommended)
egeria-advisor -a
egeria-advisor --agent

# Or run as module
uv run --package egeria-advisor python -m advisor.cli.main --agent
uv run --package egeria-advisor python -m advisor.cli.main -a

# ❌ WRONG - treats "agent" as a query
egeria-advisor agent
uv run --package egeria-advisor python -m advisor.cli.main agent
```

**Interactive Mode (No Memory):**
```bash
egeria-advisor -i
egeria-advisor --interactive
```

**Direct Query:**
```bash
egeria-advisor "What does CollectionManager do?"
```

**Default Settings:**
- ✅ MLflow tracking: **ENABLED by default** (use `--no-track` to disable)
- ✅ User feedback: **ENABLED by default** (use `--no-feedback` to disable)
- ✅ Citations: **SHOWN by default** (use `--no-citations` to hide)

### Expected Behavior

**Initial Query:**
```
agent> What does CollectionManager do?

[Response with CollectionManager methods and description]

What would you like to know more about?
  1. See detailed method documentation
  2. View code examples
  3. Show related classes
  4. Explain async vs sync usage

Type the number or describe what you'd like!
```

**Follow-Up Selection:**
```
agent> 1

→ Interpreting as: Show me the documentation for CollectionManager
→ Maintaining PyEgeria context: Show me the documentation for PyEgeria CollectionManager

[Detailed PyEgeria documentation - NO hallucinations]
```

## Testing

### Test Script
```bash
python scripts/test_follow_up_routing.py
```

This tests:
1. Initial PyEgeria query routes correctly
2. Follow-up query maintains PyEgeria routing
3. Follow-up options are present

### Manual Testing
```bash
uv run --package egeria-advisor python -m advisor.cli.main --agent

# Then try:
agent> What does CollectionManager do?
agent> 1
agent> 2
```

## Technical Details

### Query Flow

**Before Fix:**
```
User: "What does CollectionManager do?"
→ Detects PyEgeria (has "Manager" + search score > 0.25)
→ Returns response with agent_type="pyegeria"

User selects "1"
→ CLI converts to: "Show me the documentation for CollectionManager"
→ Routes through conversation agent
→ "show me" matches EXAMPLE pattern
→ Routes to semantic search ❌
```

**After Fix:**
```
User: "What does CollectionManager do?"
→ Detects PyEgeria (has "what does" + "Manager")
→ Returns response with agent_type="pyegeria"
→ CLI stores last_agent_type="pyegeria"

User selects "1"
→ CLI converts to: "Show me the documentation for CollectionManager"
→ CLI detects follow-up + last_agent_type="pyegeria"
→ CLI adds context: "Show me the documentation for PyEgeria CollectionManager"
→ Routes through conversation agent
→ "PyEgeria" + "show me" matches PyEgeria patterns
→ Routes to PyEgeria agent ✓
```

### Key Components

1. **advisor/cli/agent_session.py**: Tracks agent type, adds context for follow-ups
2. **advisor/agents/conversation_agent.py**: Returns agent_type in response
3. **advisor/agents/pyegeria_agent.py**: Expanded detection patterns
4. **advisor/interactive_response.py**: Generates follow-up options

## Related Fixes

These fixes also address:
- ✅ Temperature = 0.0 (prevents hallucination)
- ✅ Stronger anti-hallucination prompts
- ✅ Follow-up options returned separately (not in LLM text)
- ✅ CLI waits for user input

## Troubleshooting

**Issue**: Follow-ups still route to wrong agent
- Check that `agent_type` is in response dict
- Verify `last_agent_type` is being set
- Check detection patterns match your query

**Issue**: No follow-up options shown
- Verify `follow_up_options` in response dict
- Check interactive_response.py is loaded
- Ensure use_interactive_format=True

**Issue**: CLI treats flag as query
- Use `--agent` not `agent`
- Use `-a` as shorthand
- Check `uv run --package egeria-advisor python -m advisor.cli.main --help`

## Future Improvements

1. **Persistent Context**: Store agent type across sessions
2. **Explicit Routing**: Allow users to force specific agent
3. **Context Window**: Maintain last N queries for better context
4. **Smart Routing**: Use ML to predict best agent based on history