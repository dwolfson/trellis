# MLflow Tracking for Conversation Agent

## Overview

The ConversationAgent now has comprehensive MLflow tracking integrated, capturing detailed metrics about agent performance, resource usage, and accuracy.

## Current MLflow Integration

### Agent Metrics Captured

When `enable_mlflow=True` (default), the agent tracks the following metrics for each query:

#### 1. **Operation Parameters** (logged at start)
```python
{
    "query_length": len(query),           # Length of user query
    "use_rag": use_rag,                   # Whether RAG is enabled
    "conversation_turn": turn_number,      # Current conversation turn
    "max_history": max_history            # Max history setting
}
```

#### 2. **Agent Performance Metrics**
```python
{
    "agent_response_length": int,          # Length of generated response
    "agent_num_sources": int,              # Number of RAG sources used
    "agent_rag_used": float,               # 1.0 if RAG used, 0.0 otherwise
    "agent_cache_hit": float,              # 1.0 if cache hit, 0.0 otherwise
    "agent_duration_seconds": float,       # Total query processing time
    "agent_conversation_length": int       # Current conversation history length
}
```

#### 3. **Resource Monitoring** (automatic)
```python
{
    "resource_duration_seconds": float,    # Operation duration
    "resource_cpu_percent": float,         # CPU usage percentage
    "resource_memory_mb": float,           # Memory usage in MB
    "resource_memory_delta_mb": float,     # Memory change during operation
    # GPU metrics (if available):
    "resource_gpu_memory_allocated_mb": float,
    "resource_gpu_memory_reserved_mb": float,
    "resource_gpu_utilization_percent": float
}
```

#### 4. **Accuracy Tracking** (automatic)
```python
{
    "accuracy_relevance_avg": float,       # Average relevance score from RAG
    "accuracy_relevance_count": int,       # Number of relevance scores
    # future: user feedback scores
    "accuracy_feedback_avg": float,
    "accuracy_feedback_count": int
}
```

### Comparison: Agent vs RAG System

| Metric Category | RAG System | Conversation Agent | Notes |
|----------------|------------|-------------------|-------|
| **Basic Metrics** | ✅ | ✅ | Query/response lengths, timing |
| **RAG Metrics** | ✅ | ✅ | Sources, relevance scores |
| **Resource Monitoring** | ✅ | ✅ | CPU, memory, GPU usage |
| **Accuracy Tracking** | ✅ | ✅ | Relevance scores |
| **Conversation Context** | ❌ | ✅ | Turn number, history length |
| **Cache Performance** | ❌ | ✅ | Cache hit/miss tracking |
| **Agent-Specific** | ❌ | ✅ | Agent behavior metrics |

## What's Being Tracked

### ✅ Currently Tracked

1. **Query Processing**
   - Query length
   - Response length
   - Processing duration
   - RAG usage (yes/no)
   - Number of sources retrieved

2. **Conversation State**
   - Current conversation turn
   - Conversation history length
   - Maximum history setting

3. **Performance**
   - Cache hit rate (1.0 = hit, 0.0 = miss)
   - Total processing time
   - Resource consumption (CPU, memory)

4. **Accuracy**
   - RAG relevance scores (average)
   - Number of relevant sources

### 🔄 Could Be Added

1. **User Feedback**
   - Thumbs up/down ratings
   - Explicit quality scores (1-5)
   - User corrections

2. **Conversation Quality**
   - Context coherence score
   - Follow-up question detection
   - Topic drift measurement

3. **LLM Metrics**
   - Token counts (input/output)
   - Model temperature used
   - Generation parameters

4. **Advanced Agent Metrics**
   - Tool usage frequency
   - Multi-turn conversation success rate
   - Average conversation length
   - Session duration

5. **Business Metrics**
   - Query categories/intents
   - User satisfaction scores
   - Task completion rates
   - Time to resolution

## Usage

### Enable MLflow Tracking (Default)
```python
from advisor.agents.conversation_agent import create_agent

# MLflow enabled by default
agent = create_agent(
    max_history=10,
    cache_size=100,
    enable_mlflow=True  # Default
)

# All queries are tracked
response = agent.run("How do I create a glossary?")
```

### Disable MLflow Tracking
```python
# Disable for testing or performance
agent = create_agent(
    max_history=10,
    cache_size=100,
    enable_mlflow=False
)

# No tracking overhead
response = agent.run("How do I create a glossary?")
```

### View Metrics in MLflow UI

```bash
# Start MLflow UI (if not already running)
mlflow ui --port 5025

# Open browser to:
http://localhost:5025

# Navigate to:
# Experiments → egeria-advisor → Runs → agent_query
```

## MLflow Run Example

```
Run ID: ca3df32206b54f4181feec06fded6f0e
Operation: agent_query

Parameters:
  query_length: 40
  use_rag: True
  conversation_turn: 1
  max_history: 10

Metrics:
  agent_response_length: 1804
  agent_num_sources: 5
  agent_rag_used: 1.0
  agent_cache_hit: 0.0
  agent_duration_seconds: 35.286
  agent_conversation_length: 0
  
  resource_duration_seconds: 35.286
  resource_cpu_percent: 45.2
  resource_memory_mb: 1024.5
  resource_memory_delta_mb: 12.3
  
  accuracy_relevance_avg: 0.451
  accuracy_relevance_count: 5
```

## Recommendations for Additional Tracking

### High Priority
1. **Token Counts**: Track input/output tokens for cost analysis
2. **User Feedback**: Add thumbs up/down or 1-5 rating system
3. **Query Intent**: Classify queries by type (how-to, what-is, troubleshooting)

### Medium Priority
4. **Conversation Metrics**: Track multi-turn success, topic coherence
5. **Error Tracking**: Log failures, timeouts, invalid responses
6. **A/B Testing**: Compare different prompts, models, parameters

### Low Priority
7. **Advanced Analytics**: Session clustering, user behavior patterns
8. **Cost Tracking**: Compute costs, API costs, storage costs
9. **Quality Scores**: Automated response quality assessment

## Integration with CLI

The CLI agent mode automatically uses MLflow tracking:

```bash
# Agent mode with MLflow tracking
python -m advisor.cli.main --agent --interactive

# All queries are tracked to MLflow
# View metrics at http://localhost:5025
```

## Benefits

1. **Performance Monitoring**: Track response times, cache effectiveness
2. **Quality Assurance**: Monitor relevance scores, user satisfaction
3. **Resource Optimization**: Identify memory/CPU bottlenecks
4. **Conversation Analysis**: Understand user interaction patterns
5. **A/B Testing**: Compare different configurations
6. **Debugging**: Trace issues with detailed metrics
7. **Cost Analysis**: Track resource usage for capacity planning

## Next Steps

1. ✅ **Basic tracking implemented** - Agent metrics, resources, accuracy
2. 🔄 **Add user feedback** - Thumbs up/down, ratings
3. 🔄 **Add token counting** - Track LLM token usage
4. 🔄 **Add query classification** - Categorize query types
5. 🔄 **Add conversation quality** - Multi-turn success metrics
6. 🔄 **Create dashboards** - Visualize metrics in MLflow or Grafana

## Conclusion

The ConversationAgent now has comprehensive MLflow tracking that captures:
- ✅ All agent-specific metrics (cache hits, conversation state)
- ✅ Performance metrics (timing, resource usage)
- ✅ Accuracy metrics (relevance scores)
- ✅ Automatic resource monitoring (CPU, memory, GPU)

This provides full observability into agent behavior and performance, enabling data-driven optimization and quality assurance.