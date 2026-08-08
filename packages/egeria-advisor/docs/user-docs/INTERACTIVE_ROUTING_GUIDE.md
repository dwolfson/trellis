# Interactive Query Routing Guide

**Version:** 1.0  
**Last Updated:** 2026-03-10 (mechanism still current as of 2026-07-11 —
`advisor/interactive_response.py` still implements confidence-tiered responses as described
below)

> For the full current routing pipeline (pattern matching, LLM intent classification,
> role-aware routing, pipeline dispatch, and the 8 intent buttons), see the
> [Query Routing Guide](QUERY_ROUTING_GUIDE.md). This document focuses specifically on the
> confidence-based clarification behavior.

## Overview

Egeria Advisor now features **intelligent interactive routing** that:
- ✅ Asks for clarification when uncertain
- ✅ Provides succinct answers with follow-up options
- ✅ Suggests clear trigger words for better queries
- ✅ Adapts responses based on confidence levels

## How It Works

### 1. Confidence-Based Responses

The system evaluates routing confidence and adapts its response:

| Confidence | Behavior | Example |
|------------|----------|---------|
| **High (>75%)** | Direct answer + follow-up options | "Here's how to create a glossary. Would you like to see: 1) Code example 2) Related commands?" |
| **Medium (50-75%)** | Answer with clarification offer | "I found information in multiple areas. Which would help most?" |
| **Low (<50%)** | Request clarification first | "I'm not sure what you're looking for. Could you clarify?" |

### 2. Succinct Answer Format

For clear queries, you get:

```
## Quick Answer
[Brief 2-3 sentence answer]

## What would you like to know more about?
1. See a code example
2. View related commands
3. Read the full documentation
4. Understand the parameters

Just let me know the number or describe what you'd like!
```

### 3. Clarification Requests

For ambiguous queries, the system asks:

```
I found information about "glossary" in multiple areas. 
To give you the best answer, could you clarify what you're looking for?

1. **Documentation** - Conceptual explanation and architecture
2. **Code Examples** - Working Python/Java code
3. **CLI Commands** - Command-line usage
4. **Tutorials** - Step-by-step guides

Which would be most helpful? (Choose a number or describe your need)
```

## Query Examples

### Example 1: Clear Query (High Confidence)

**Query:** "Show me the documentation for create_glossary"

**Response:**
```
## Quick Answer
The create_glossary command creates a new glossary in Egeria. 
It requires a name parameter and accepts an optional description.

## What would you like to know more about?
1. Would you like to see a code example?
2. Do you want to see related commands?
3. Should I show you the command options?
4. Would you like to see common use cases?

Just let me know the number or describe what you'd like!
```

**Follow-up:** User can respond with "1" or "show me a code example"

---

### Example 2: Ambiguous Query (Low Confidence)

**Query:** "Tell me about glossary"

**Response:**
```
I found information about "glossary" in multiple areas. 
To give you the best answer, could you clarify what you're looking for?

1. **Documentation** - Conceptual explanation and architecture
2. **Code Examples** - Working Python/Java code
3. **CLI Commands** - Command-line usage
4. **Tutorials** - Step-by-step guides

Which would be most helpful? (Choose a number or describe your need)
```

**Follow-up:** User responds with "2" or "show me code examples"

---

### Example 3: Multiple Matches (Medium Confidence)

**Query:** "How do I use OMAS?"

**Response:**
```
I found information about "OMAS" in multiple areas. 
To give you the best answer, could you clarify what you're looking for?

1. **Documentation** - Conceptual explanation and architecture
2. **Code Examples** - Working Python/Java code
3. **CLI Commands** - Command-line usage

Which would be most helpful?
```

## Trigger Words for Better Queries

Use these trigger words to get more precise routing:

### For Documentation
**Keywords:** `documentation`, `docs`, `guide`, `tutorial`, `explain`, `what is`

**Example:**
```
✅ "Show me the documentation for create_glossary"
✅ "Explain what a glossary is"
✅ "Guide to using glossaries"
```

### For Code Examples
**Keywords:** `code`, `implementation`, `example`, `show me`, `how to`

**Example:**
```
✅ "Show me code for creating a glossary"
✅ "Give me a Python example of glossary creation"
✅ "How to implement glossary management"
```

### For CLI Commands
**Keywords:** `command`, `cli`, `hey-egeria`, `terminal`

**Example:**
```
✅ "What are the hey-egeria commands for glossaries?"
✅ "Show me CLI commands for glossary management"
✅ "Terminal commands for creating glossaries"
```

### For Examples/Demos
**Keywords:** `example`, `demo`, `sample`, `notebook`, `workspace`

**Example:**
```
✅ "Show me an example of using glossaries"
✅ "Give me a demo of glossary creation"
✅ "Jupyter notebook for glossaries"
```

## Follow-Up Options by Query Type

Different query types get different follow-up suggestions:

### Concept Queries
- Would you like to see a code example?
- Do you want to see how this is implemented?
- Should I show you related concepts?
- Would you like to see the type definition?

### Code Queries
- Would you like to see more examples?
- Do you want to see the full implementation?
- Should I explain how this works?
- Would you like to see related methods?

### Example Queries
- Would you like to see another example?
- Do you want to see a more complex use case?
- Should I explain the code in detail?
- Would you like to see related examples?

### CLI Queries
- Would you like to see an example?
- Do you want to see related commands?
- Should I show you the command options?
- Would you like to see common use cases?

## Configuration

The interactive behavior is configured in `config/routing.yaml`:

```yaml
# Confidence thresholds
confidence_thresholds:
  high_confidence: 0.75      # Clear routing decision
  medium_confidence: 0.50    # Acceptable but could clarify
  low_confidence: 0.30       # Should ask for clarification

# Clarification settings
clarification:
  enabled: true
  ask_when_confidence_below: 0.50
  ask_when_multiple_routes: true
  max_route_options: 3
```

### Customizing Thresholds

Adjust when clarification is requested:

```yaml
clarification:
  enabled: true
  ask_when_confidence_below: 0.60  # More conservative (ask more often)
  # or
  ask_when_confidence_below: 0.40  # Less conservative (ask less often)
```

### Customizing Follow-Up Options

Add or modify follow-up templates:

```yaml
followup_templates:
  concept:
    - "Would you like to see a code example?"
    - "Do you want to see how this is implemented?"
    - "Your custom follow-up question here"
```

## Best Practices

### 1. Be Specific in Your Queries

❌ **Vague:** "Tell me about glossary"
✅ **Specific:** "Show me the documentation for create_glossary"

### 2. Use Trigger Words

❌ **Generic:** "How do I work with glossaries?"
✅ **With Trigger:** "Show me code examples for glossary management"

### 3. Respond to Follow-Ups

When offered options, you can:
- Choose by number: "2"
- Describe what you want: "show me a code example"
- Ask a new question: "how do I handle errors?"

### 4. Clarify When Asked

If the system asks for clarification:
- Choose an option number
- Or rephrase with more specific terms
- Or describe your exact need

## Interactive Flow Examples

### Flow 1: Direct Answer → Follow-Up

```
User: "What is the create_glossary command?"

System: 
## Quick Answer
The create_glossary command creates a new glossary in Egeria...

## What would you like to know more about?
1. See a code example
2. View related commands
3. Read the full documentation

User: "1"

System: [Provides code example]
```

### Flow 2: Clarification → Specific Answer

```
User: "Tell me about OMAS"

System:
I found information about "OMAS" in multiple areas...
1. Documentation
2. Code Examples
3. CLI Commands

User: "I want to see code examples"

System: [Provides Python/Java code examples]
```

### Flow 3: Progressive Disclosure

```
User: "How do I create a glossary?"

System: [Brief answer + options]

User: "Show me an example"

System: [Code example + more options]

User: "Explain the parameters"

System: [Parameter details + related topics]
```

## Testing Interactive Routing

Test the interactive features:

```bash
python scripts/test_interactive_routing.py
```

This will test:
1. High confidence queries
2. Low confidence queries
3. Multiple route queries
4. Follow-up options
5. Trigger word hints
6. Succinct formatting
7. Confidence thresholds

## Troubleshooting

### System Always Asks for Clarification

**Problem:** Every query triggers clarification

**Solutions:**
1. Use more specific trigger words
2. Lower the `ask_when_confidence_below` threshold
3. Check that collections are properly configured

### No Follow-Up Options Shown

**Problem:** Responses don't include follow-up options

**Solutions:**
1. Check `config/routing.yaml` has `followup_templates`
2. Verify confidence is above threshold
3. Ensure interactive handler is being used

### Wrong Follow-Up Options

**Problem:** Follow-up options don't match query type

**Solutions:**
1. Check query classification is correct
2. Verify `followup_templates` in config
3. Add custom templates for your query types

## Advanced Usage

### Programmatic Access

```python
from advisor.interactive_response import create_interactive_response
from advisor.query_classifier import classify_query

# Classify query
classification = classify_query("What is create_glossary?")

# Create interactive response
response = create_interactive_response(
    answer="Brief answer here",
    classification=classification,
    confidence=0.85,
    collections_searched=["pyegeria_cli"],
    topic="create_glossary"
)

# Check response mode
if response.clarification_needed:
    print("Need clarification")
else:
    print(response.answer)
    print("Follow-ups:", response.follow_up_options)
```

### Custom Response Formatting

```python
from advisor.interactive_response import get_interactive_handler

handler = get_interactive_handler()

# Format succinct response
formatted = handler.format_succinct_response(
    answer="Your answer here",
    follow_up_options=[
        "Option 1",
        "Option 2",
        "Option 3"
    ]
)
```

## Summary

**Key Features:**
- ✅ Confidence-based clarification
- ✅ Succinct answers with options
- ✅ Clear trigger word guidance
- ✅ Adaptive response formatting
- ✅ Progressive disclosure
- ✅ Fully configurable

**Benefits:**
- Faster answers for clear queries
- Better guidance for ambiguous queries
- Natural conversation flow
- Reduced frustration
- More efficient information discovery

**Configuration Files:**
- `config/routing.yaml` - Main configuration
- `advisor/interactive_response.py` - Response handler
- `advisor/prompt_templates.py` - Prompt formatting

---

**Related Guides:**
- [Query Routing Guide](QUERY_ROUTING_GUIDE.md) - Query phrasing strategies
- [Data-Driven Routing Guide](DATA_DRIVEN_ROUTING_GUIDE.md) - Configuration details