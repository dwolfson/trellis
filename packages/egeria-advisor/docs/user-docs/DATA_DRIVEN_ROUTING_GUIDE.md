# Data-Driven Query Routing Configuration Guide

**Version:** 1.0  
**Last Updated:** 2026-03-10 (mechanism still current as of 2026-07-11 — `config/routing.yaml`
still has `collection_domain_terms`, `intent_keywords`, and `special_rules` sections as
described below)

> For the full current routing pipeline (pattern matching, LLM intent classification,
> role-aware routing, pipeline dispatch, and the 8 intent buttons), see the
> [Query Routing Guide](QUERY_ROUTING_GUIDE.md). This document focuses specifically on how
> to customize `config/routing.yaml` without touching Python code.

## Overview

Egeria Advisor now supports **data-driven query routing configuration** through YAML files. This allows you to customize routing behavior without modifying Python code.

## What's Configurable?

### 1. Query Patterns
Define patterns that determine query types (code search, explanation, example, etc.)

### 2. Domain Terms
Specify terms that route queries to specific collections

### 3. Collection Domain Terms
Override domain terms for individual collections

### 4. Intent Keywords
Define keywords that boost collection priority based on query intent

### 5. Special Rules
Create custom rules for edge cases

## Configuration File

**Location:** `config/routing.yaml`

The system automatically loads this file on startup. If the file doesn't exist, it falls back to hardcoded defaults.

## Configuration Structure

```yaml
# Query patterns organized by priority and query type
query_patterns:
  critical:      # Highest priority - most specific patterns
    quantitative:
      - "how many lines of code"
      - "lines of code"
    debugging:
      - "why isn't this working"
  
  high:          # High priority - specific multi-word patterns
    report:
      - "generate report"
      - "create report"
    code_search:
      - "show me how"
      - "how do i"
  
  medium:        # Medium priority - action-oriented
    example:
      - "show me examples"
      - "give me examples"
  
  low:           # Low priority - general patterns
    general:
      - "tell me about"
      - "what is"

# Domain-specific terms for context-aware detection
domain_terms:
  egeria_concepts:
    - "glossary"
    - "collection"
    - "asset"
  
  pyegeria_code:
    - "pyegeria"
    - "python-client"
    - "rest-client"
  
  deployment:
    - "docker"
    - "kubernetes"
    - "helm"

# Collection-specific domain terms (override defaults)
collection_domain_terms:
  pyegeria:
    - "pyegeria"
    - "python-client"
    - "async-client"
  
  pyegeria_cli:
    - "hey-egeria"
    - "cli"
    - "command"
  
  egeria_java:
    - "java"
    - "omas"
    - "omag"

# Intent-based routing keywords
intent_keywords:
  documentation:
    - "documentation"
    - "docs"
    - "guide"
  code:
    - "code"
    - "implementation"
    - "source"
  example:
    - "example"
    - "sample"
    - "demo"

# Special rules for edge cases
special_rules:
  how_does_differ:
    pattern: "how does"
    check_terms:
      - "differ"
      - "compare"
    if_match: "comparison"
    if_no_match: null
```

## How to Customize

### Adding New Query Patterns

1. Open `config/routing.yaml`
2. Find the appropriate priority level
3. Add your pattern under the correct query type:

```yaml
query_patterns:
  high:
    code_search:
      - "show me how"
      - "find code for"      # NEW PATTERN
      - "locate implementation"  # NEW PATTERN
```

### Adding Domain Terms

Add terms to route queries to specific content types:

```yaml
domain_terms:
  egeria_concepts:
    - "glossary"
    - "metadata-lake"  # NEW TERM
    - "data-catalog"   # NEW TERM
```

### Customizing Collection Routing

Override domain terms for specific collections:

```yaml
collection_domain_terms:
  pyegeria:
    - "pyegeria"
    - "python-egeria"  # NEW TERM
    - "egeria-py"      # NEW TERM
```

### Adding Intent Keywords

Define keywords that boost collection priority:

```yaml
intent_keywords:
  api:  # NEW INTENT
    - "api"
    - "rest"
    - "endpoint"
```

## Priority Levels Explained

### Critical (1)
- **Most specific patterns**
- Checked first
- Use for: Multi-word phrases that must match exactly
- Example: "how many lines of code"

### High (2)
- **Specific multi-word patterns**
- Checked second
- Use for: Action-oriented phrases
- Example: "generate report", "show me how"

### Medium (3)
- **Action-oriented patterns**
- Checked third
- Use for: Common query structures
- Example: "how to", "find", "explain"

### Low (4)
- **General patterns**
- Checked fourth
- Use for: Broad query types
- Example: "tell me about", "what is"

### Fallback (5)
- **Catch-all patterns**
- Checked last
- Use for: Default behavior

## Query Types

Available query types:
- `code_search` - Finding code examples
- `explanation` - Understanding concepts
- `example` - Getting examples
- `comparison` - Comparing options
- `best_practice` - Best practices
- `debugging` - Troubleshooting
- `quantitative` - Metrics and counts
- `relationship` - Code relationships
- `report` - Report generation
- `command` - Command execution
- `general` - General queries

## Reloading Configuration

### Programmatic Reload

```python
from advisor.query_patterns import reload_config

# Reload configuration from file
success = reload_config()
if success:
    print("Configuration reloaded!")
```

### Automatic Reload

The system automatically loads configuration on:
- Module import
- First use of routing functions

**Note:** Currently, you need to restart the application or call `reload_config()` to pick up changes.

## Testing Your Configuration

Use the test script to verify your configuration:

```bash
python scripts/test_routing_config.py
```

This will:
1. Load and display your configuration
2. Test pattern matching
3. Test domain term routing
4. Test collection routing
5. Verify configuration reload

## Examples

### Example 1: Adding Support for a New Technology

Add terms for Kafka integration:

```yaml
domain_terms:
  kafka_integration:
    - "kafka"
    - "event-streaming"
    - "message-broker"
    - "kafka-connector"

collection_domain_terms:
  egeria_java:
    - "java"
    - "kafka-integration"  # Link to new terms
```

### Example 2: Improving CLI Detection

Make CLI queries more specific:

```yaml
query_patterns:
  high:
    command:
      - "run command"
      - "execute command"
      - "cli command"       # NEW
      - "terminal command"  # NEW

collection_domain_terms:
  pyegeria_cli:
    - "hey-egeria"
    - "cli"
    - "command-line"
    - "egeria-cli"  # NEW
```

### Example 3: Adding Deployment Patterns

Improve deployment query routing:

```yaml
query_patterns:
  high:
    deployment:  # NEW QUERY TYPE
      - "deploy to"
      - "deployment guide"
      - "install on"

domain_terms:
  deployment:
    - "docker"
    - "kubernetes"
    - "openshift"  # NEW
    - "rancher"    # NEW
```

## Best Practices

### 1. Be Specific
Use multi-word phrases for better matching:
- ✅ "how to create"
- ❌ "create"

### 2. Use Lowercase
All patterns are matched case-insensitively, but use lowercase in config:
- ✅ "python-client"
- ❌ "Python-Client"

### 3. Include Variants
Add common variations:
```yaml
- "hey-egeria"
- "hey_egeria"
- "heyegeria"
```

### 4. Test Changes
Always test after modifying configuration:
```bash
python scripts/test_routing_config.py
```

### 5. Document Custom Terms
Add comments to explain custom additions:
```yaml
domain_terms:
  custom_integration:
    # Terms for our custom Salesforce integration
    - "salesforce"
    - "crm-connector"
```

## Fallback Behavior

If `config/routing.yaml` is not found or fails to load:
1. System logs a warning
2. Falls back to hardcoded defaults in Python code
3. Continues operating normally

## Migration from Hardcoded Configuration

If you have custom modifications in Python code:

1. **Identify your changes** in `advisor/query_patterns.py` or `advisor/collection_config.py`
2. **Copy patterns** to `config/routing.yaml`
3. **Test** with `scripts/test_routing_config.py`
4. **Verify** routing behavior matches expectations
5. **Remove** Python code modifications (optional)

## Troubleshooting

### Configuration Not Loading

**Problem:** Changes to `routing.yaml` not taking effect

**Solutions:**
1. Restart the application
2. Call `reload_config()` programmatically
3. Check file location: `config/routing.yaml` relative to project root
4. Check YAML syntax with a validator

### Patterns Not Matching

**Problem:** Queries not routing as expected

**Solutions:**
1. Run test script: `python scripts/test_routing_config.py`
2. Check pattern priority (higher priority = checked first)
3. Verify lowercase formatting
4. Test with exact query phrases

### Collection Not Found

**Problem:** Collection domain terms not working

**Solutions:**
1. Verify collection name matches exactly (case-sensitive)
2. Check that collection is enabled in `collection_config.py`
3. Ensure terms are in a list format

## Advanced Configuration

### Custom Special Rules

Define complex routing logic:

```yaml
special_rules:
  custom_rule:
    pattern: "how to use"
    check_domain_category: "pyegeria_code"
    if_match: "code_search"
    if_no_match: "explanation"
```

### Intent Boosting

Control collection priority based on intent:

```yaml
intent_keywords:
  api_documentation:
    - "api reference"
    - "api docs"
    - "rest api"
```

When these keywords appear, collections with matching content types get priority boost.

## Summary

**Key Benefits:**
- ✅ No code changes needed for routing customization
- ✅ Easy to add new patterns and terms
- ✅ Configuration can be version controlled
- ✅ Changes can be tested without recompiling
- ✅ Falls back to defaults if config missing

**Key Files:**
- `config/routing.yaml` - Main configuration file
- `advisor/query_patterns.py` - Pattern loading logic
- `advisor/collection_config.py` - Collection configuration
- `scripts/test_routing_config.py` - Test script

**Next Steps:**
1. Review current `config/routing.yaml`
2. Identify customization needs
3. Make changes to YAML file
4. Test with test script
5. Deploy and monitor

---

**Need Help?** Check the [Query Routing Guide](QUERY_ROUTING_GUIDE.md) for query phrasing strategies.