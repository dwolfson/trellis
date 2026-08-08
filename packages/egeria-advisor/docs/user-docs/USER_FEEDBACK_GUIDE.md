# User Feedback System Guide

**Version:** 1.0  
**Last Updated:** 2026-02-19

## Overview

The Egeria Advisor includes an automated feedback collection system that helps improve query routing and response quality over time. This guide explains how to use the feedback system and how it drives continuous improvement.

## How Feedback Works

### 1. Automatic Collection

Every query response includes metadata that can be used for feedback:
- Query text and type
- Collections searched
- Response length
- Timestamp and session ID

### 2. User Feedback Options

Users can provide feedback in three ways:

**👍 Positive Feedback** - "This answer was helpful"
- Indicates correct routing
- Confirms good response quality
- Reinforces current behavior

**👎 Negative Feedback** - "This answer wasn't helpful"
- Indicates potential routing issues
- Suggests response quality problems
- Triggers improvement analysis

**💬 Detailed Feedback** - Free-text comments
- Explain what was wrong
- Suggest better collections
- Request specific improvements

### 3. Feedback Storage

#### Storage Format: JSONL (JSON Lines)

Feedback is stored in **JSONL format** (newline-delimited JSON) at:
```
data/feedback/user_feedback.jsonl
```

**Why JSONL?**
- **Append-Only**: Fast writes, one entry per line
- **Human-Readable**: Easy to inspect with text tools
- **Streaming-Friendly**: Process large files line-by-line
- **Simple**: No database setup required
- **Git-Friendly**: Track changes line-by-line

**Example Storage** (each line is a complete JSON object):
```jsonl
{"timestamp": "2026-02-19T22:30:00.000Z", "query": "How do I create a glossary?", "query_type": "code_search", "collections_searched": ["pyegeria"], "response_length": 1250, "rating": "positive", "feedback_text": null, "user_comment": "Perfect!", "suggested_collection": null, "session_id": "abc123"}
{"timestamp": "2026-02-19T22:35:00.000Z", "query": "What is OMAS?", "query_type": "explanation", "collections_searched": ["egeria_docs"], "response_length": 800, "rating": "positive", "feedback_text": null, "user_comment": null, "suggested_collection": null, "session_id": "abc123"}
```

**Pretty-Printed Example**:
```json
{
  "timestamp": "2026-02-19T22:30:00.000Z",
  "query": "How do I create a glossary?",
  "query_type": "code_search",
  "collections_searched": ["pyegeria", "egeria_docs"],
  "response_length": 1250,
  "rating": "positive",
  "feedback_text": null,
  "user_comment": "Perfect example with all imports!",
  "suggested_collection": null,
  "session_id": "abc123"
}
```

#### Command-Line Tools

**View recent feedback**:
```bash
tail -n 10 data/feedback/user_feedback.jsonl | jq .
```

**Count total feedback**:
```bash
wc -l data/feedback/user_feedback.jsonl
```

**Filter positive feedback**:
```bash
grep '"rating": "positive"' data/feedback/user_feedback.jsonl | jq .
```

**Search for specific query**:
```bash
grep "glossary" data/feedback/user_feedback.jsonl | jq .
```

**Get today's feedback**:
```bash
grep "$(date +%Y-%m-%d)" data/feedback/user_feedback.jsonl | jq .
```

#### Storage Location

```
egeria-advisor/
├── data/
│   └── feedback/
│       ├── user_feedback.jsonl          # Main feedback file
│       ├── user_feedback_2026-02.jsonl  # Optional: Monthly archives
│       └── backups/                     # Optional: Daily backups
│           └── user_feedback_20260219.jsonl
```

#### Backup Strategy

```bash
# Daily backup
cp data/feedback/user_feedback.jsonl \
   data/feedback/backups/user_feedback_$(date +%Y%m%d).jsonl

# Keep last 30 days
find data/feedback/backups/ -name "*.jsonl" -mtime +30 -delete
```

#### Migration to Database (Future)

The JSONL format makes migration easy:

```python
# Migrate to SQLite
import sqlite3
import json

conn = sqlite3.connect('feedback.db')
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE feedback (
        timestamp TEXT,
        query TEXT,
        query_type TEXT,
        rating TEXT,
        user_comment TEXT,
        session_id TEXT
    )
''')

with open('../../data/feedback/user_feedback.jsonl', 'r') as f:
   for line in f:
      entry = json.loads(line)
      cursor.execute(
         'INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?)',
         (entry['timestamp'], entry['query'], entry['query_type'],
          entry['rating'], entry.get('user_comment'), entry.get('session_id'))
      )

conn.commit()
```

## Using the Feedback System

### In Python Code

```python
from advisor.feedback_collector import (
    record_positive_feedback,
    record_negative_feedback,
    get_feedback_collector
)

# Record positive feedback
record_positive_feedback(
    query="How do I create a glossary?",
    query_type="code_search",
    collections_searched=["pyegeria"],
    response_length=1250,
    feedback_text="Perfect example with all imports!",
    session_id="user_session_123"
)

# Record negative feedback with routing correction
record_negative_feedback(
    query="What is OMAS architecture?",
    query_type="explanation",
    collections_searched=["egeria_java"],
    response_length=800,
    feedback_text="Should have searched documentation instead",
    suggested_collection="egeria_docs",
    session_id="user_session_123"
)

# Get feedback statistics
collector = get_feedback_collector()
stats = collector.get_feedback_stats()
print(f"Satisfaction rate: {stats['satisfaction_rate']:.1%}")
print(f"Total feedback: {stats['total']}")
```

### In CLI (Interactive Mode)

After each response, the CLI can prompt for feedback:

```
Response: [Your answer here...]

Was this answer helpful? (y/n/skip): n
What was wrong? (optional): Should have searched documentation
Which collection should have been used? (optional): egeria_docs

Thank you for your feedback! This helps improve the system.
```

### Via REST API (Future)

```bash
POST /api/feedback
{
  "query_id": "abc123",
  "rating": "negative",
  "feedback_text": "Wrong collection",
  "suggested_collection": "egeria_docs"
}
```

## Feedback Analysis

### View Statistics

```python
from advisor.feedback_collector import get_feedback_collector

collector = get_feedback_collector()
stats = collector.get_feedback_stats()

print(f"""
Overall Statistics:
- Total feedback: {stats['total']}
- Positive: {stats['positive']} ({stats['positive']/stats['total']:.1%})
- Negative: {stats['negative']} ({stats['negative']/stats['total']:.1%})
- Satisfaction rate: {stats['satisfaction_rate']:.1%}

By Query Type:
""")
for query_type, data in stats['by_query_type'].items():
    satisfaction = data['positive'] / data['total'] if data['total'] > 0 else 0
    print(f"  {query_type}: {satisfaction:.1%} ({data['total']} queries)")

print("\nBy Collection:")
for collection, data in stats['by_collection'].items():
    satisfaction = data['positive'] / data['total'] if data['total'] > 0 else 0
    print(f"  {collection}: {satisfaction:.1%} ({data['total']} queries)")
```

### Get Improvement Suggestions

```python
from advisor.feedback_collector import get_feedback_collector

collector = get_feedback_collector()
improvements = collector.get_routing_improvements()

for improvement in improvements:
    print(f"\n{improvement['type']}:")
    print(f"  Action: {improvement['action']}")
    if 'query' in improvement:
        print(f"  Example query: {improvement['query']}")
```

### Export Feedback Data

```python
from advisor.feedback_collector import get_feedback_collector
from pathlib import Path

collector = get_feedback_collector()

# Export to JSON
collector.export_feedback(Path("feedback_export.json"))

# Export to CSV for analysis
collector.export_feedback(Path("feedback_export.csv"))
```

## Continuous Improvement Process

### 1. Weekly Review

Every week, review feedback statistics:

```bash
python scripts/analyze_feedback.py --period week
```

Output:
```
Weekly Feedback Report (2026-02-12 to 2026-02-19)
================================================

Overall Satisfaction: 87.5% (35/40 positive)

Top Issues:
1. egeria_java collection: 60% satisfaction (needs review)
2. comparison queries: 70% satisfaction (improve prompts)
3. 5 routing corrections suggested

Recommended Actions:
- Review prompt template for egeria_java
- Add domain terms for comparison queries
- Update routing weights based on corrections
```

### 2. Apply Improvements

Based on feedback analysis:

**Routing Corrections**:
```python
# If users consistently suggest different collections
# Update collection_config.py domain terms

# Example: Users say "OMAS architecture" should go to docs
EGERIA_DOCS_COLLECTION = CollectionMetadata(
    domain_terms=[
        # ... existing terms ...
        "omas architecture",  # Add based on feedback
        "omag architecture",
    ]
)
```

**Prompt Improvements**:
```python
# If collection has low satisfaction
# Update prompt_templates.py

# Example: Improve Java code prompt
"java_code": """You are an expert Java developer...
[Enhanced instructions based on feedback]
"""
```

**Query Type Adjustments**:
```python
# If query type has low satisfaction
# Update query_patterns.py

# Example: Add more patterns for comparison queries
QueryType.COMPARISON: [
    "difference between",
    "compare",
    "versus",
    "how does X differ from Y",  # Add based on feedback
]
```

### 3. A/B Testing (Future)

Test improvements with a subset of users:

```python
from advisor.feedback_collector import get_feedback_collector

# Enable A/B testing
collector = get_feedback_collector()
collector.enable_ab_testing(
    variant_a="current_prompts",
    variant_b="improved_prompts",
    split_ratio=0.5
)
```

### 4. Monitor Impact

After applying improvements, monitor changes:

```bash
python scripts/compare_feedback.py --before 2026-02-12 --after 2026-02-19
```

Output:
```
Feedback Comparison
===================

Before improvements (2026-02-12):
- Satisfaction: 75.0%
- egeria_java: 60.0%

After improvements (2026-02-19):
- Satisfaction: 87.5% (+12.5%)
- egeria_java: 85.0% (+25.0%)

✓ Improvements successful!
```

## Best Practices

### For Users

1. **Provide Specific Feedback**
   - ❌ "Bad answer"
   - ✅ "Should have searched documentation instead of code"

2. **Suggest Corrections**
   - Include which collection should have been used
   - Explain why the routing was wrong

3. **Be Constructive**
   - Focus on what would make the answer better
   - Provide examples of good responses

### For Developers

1. **Review Feedback Regularly**
   - Weekly reviews minimum
   - Monthly deep dives

2. **Act on Patterns**
   - Don't react to single feedback items
   - Look for consistent patterns (5+ similar feedback)

3. **Test Changes**
   - Use A/B testing for major changes
   - Monitor impact after improvements

4. **Document Changes**
   - Record what feedback led to what changes
   - Track improvement metrics

## Feedback-Driven Improvements

### Example 1: Routing Correction

**Feedback Pattern**:
- 10 users said "OMAS architecture" should go to docs
- Currently routes to egeria_java

**Action Taken**:
```python
# Added to egeria_docs domain terms
"omas architecture", "omag architecture", "omrs architecture"

# Removed from egeria_java (kept specific Java terms)
```

**Result**:
- Routing accuracy improved from 85% to 95%
- User satisfaction increased from 75% to 90%

### Example 2: Prompt Improvement

**Feedback Pattern**:
- Java code responses missing Spring Boot configuration
- Users want REST API examples

**Action Taken**:
```python
# Enhanced Java code prompt
"java_code": """...
- Show Spring Boot configuration when relevant
- Include REST API endpoints and connectors
- Reference specific packages and classes
..."""
```

**Result**:
- Java query satisfaction improved from 60% to 85%
- Fewer follow-up questions needed

### Example 3: New Query Type

**Feedback Pattern**:
- Users asking "how to debug" questions
- Current routing treats as general queries

**Action Taken**:
```python
# Added DEBUGGING query type
QueryType.DEBUGGING = "debugging"

# Added patterns
QUERY_PATTERNS[PatternPriority.HIGH][QueryType.DEBUGGING] = [
    "why isn't", "not working", "getting an error",
    "how do i fix", "troubleshoot", "debug"
]

# Added specialized prompt
"debugging": """Focus on problem-solving..."""
```

**Result**:
- Debugging queries now get targeted responses
- Satisfaction improved from 65% to 88%

## Privacy & Data Handling

### What We Collect

- Query text (anonymized if requested)
- Query metadata (type, collections, timing)
- Feedback ratings and comments
- Session IDs (for grouping, not user identification)

### What We Don't Collect

- User names or email addresses
- IP addresses
- Personal information
- Proprietary code or data

### Data Retention

- Feedback stored locally in `data/feedback/`
- Retained for 1 year by default
- Can be deleted on request
- Exported for analysis only

### Opt-Out

Users can disable feedback collection:

```python
from advisor.config import get_full_config

config = get_full_config()
config.feedback.enabled = False
```

## Troubleshooting

### Feedback Not Being Recorded

**Check file permissions**:
```bash
ls -la data/feedback/
# Should be writable
```

**Check disk space**:
```bash
df -h data/feedback/
```

**Check logs**:
```bash
tail -f logs/advisor.log | grep feedback
```

### Statistics Not Updating

**Verify feedback file exists**:
```bash
cat data/feedback/user_feedback.jsonl | wc -l
# Should show number of feedback entries
```

**Regenerate statistics**:
```python
from advisor.feedback_collector import get_feedback_collector

collector = get_feedback_collector()
stats = collector.get_feedback_stats()
# Forces recalculation
```

## Future Enhancements

1. **Real-time Dashboard**
   - Live feedback statistics
   - Trend visualization
   - Alert on low satisfaction

2. **Automated Improvements**
   - ML-based routing adjustments
   - Automatic prompt optimization
   - Self-healing system

3. **User Profiles**
   - Personalized routing
   - Custom prompt preferences
   - Learning from individual feedback

4. **Integration with MLflow**
   - Track feedback as metrics
   - A/B test experiments
   - Model performance correlation

## References

- [Phase 8 Improvements](docs/history/PHASE8_ROUTING_QUALITY_IMPROVEMENTS.md)
- [Query Routing Guide](docs/user-docs/QUERY_ROUTING_GUIDE.md)
- [System Architecture](docs/design/SYSTEM_ARCHITECTURE.md)

---

**Questions?** Check the [FAQ](FAQ.md) or open an issue on GitHub.