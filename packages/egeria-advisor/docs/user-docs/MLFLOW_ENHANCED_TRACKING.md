# Enhanced MLflow Tracking for Egeria Advisor

## Overview

The Egeria Advisor now includes enhanced MLflow tracking capabilities that monitor:
1. **Resource Consumption** - CPU, memory, and GPU usage
2. **Query Accuracy** - User feedback, relevance scores, and confidence metrics

## Features

### 1. Resource Monitoring

Automatically tracks system resource consumption during operations:

- **CPU Usage** - Percentage of CPU utilized
- **Memory Usage** - Memory consumption in MB
- **Memory Delta** - Change in memory usage during operation
- **GPU Metrics** (if available):
  - GPU memory allocated
  - GPU memory reserved
  - GPU utilization percentage

### 2. Accuracy Tracking

Tracks query accuracy through multiple metrics:

- **User Feedback** - Direct user ratings (0-1 or 1-5 scale, normalized to 0-1)
- **Relevance Scores** - How relevant retrieved results are (0-1)
- **Confidence Scores** - Model confidence in responses (0-1)

## Usage

### Basic Usage

```python
from advisor.mlflow_tracking import get_mlflow_tracker

tracker = get_mlflow_tracker()

# Track an operation with resource and accuracy monitoring
with tracker.track_operation(
    operation_name="query_processing",
    params={"query": "How do I create a glossary?"},
    tags={"query_type": "code_search"}
) as op:
    # Your operation code here
    result = process_query(query)
    
    # Add accuracy metrics
    op.add_relevance(0.85)  # Relevance score from vector search
    op.add_confidence(0.92)  # Model confidence
    
    # Optionally add user feedback later
    # op.add_feedback(4.0)  # User rating (1-5 scale)
```

### Disable Specific Monitoring

```python
# Disable resource monitoring
with tracker.track_operation(
    operation_name="lightweight_operation",
    track_resources=False
) as op:
    # Operation code
    pass

# Disable accuracy tracking
with tracker.track_operation(
    operation_name="system_operation",
    track_accuracy=False
) as op:
    # Operation code
    pass
```

### Initialize with Custom Settings

```python
from advisor.mlflow_tracking import MLflowTracker

tracker = MLflowTracker(
    tracking_uri="http://localhost:5025",
    experiment_name="egeria-advisor-enhanced",
    enable_resource_monitoring=True,
    enable_accuracy_tracking=True
)
```

## Metrics Logged

### Resource Metrics

| Metric | Description | Unit |
|--------|-------------|------|
| `resource_duration_seconds` | Operation duration | seconds |
| `resource_cpu_percent` | CPU utilization | percentage |
| `resource_memory_mb` | Current memory usage | MB |
| `resource_memory_delta_mb` | Memory change during operation | MB |
| `resource_gpu_memory_allocated_mb` | GPU memory allocated | MB |
| `resource_gpu_memory_reserved_mb` | GPU memory reserved | MB |
| `resource_gpu_utilization_percent` | GPU utilization | percentage |

### Accuracy Metrics

| Metric | Description | Range |
|--------|-------------|-------|
| `accuracy_feedback_avg` | Average user feedback score | 0-1 |
| `accuracy_feedback_count` | Number of feedback scores | count |
| `accuracy_relevance_avg` | Average relevance score | 0-1 |
| `accuracy_relevance_count` | Number of relevance scores | count |
| `accuracy_confidence_avg` | Average confidence score | 0-1 |
| `accuracy_confidence_count` | Number of confidence scores | count |

## Integration with RAG System

The enhanced tracking is automatically integrated with the RAG system. Each query logs:

1. **Resource consumption** during:
   - Query processing
   - Vector search
   - LLM generation
   
2. **Accuracy metrics** from:
   - Vector search relevance scores
   - LLM confidence scores
   - User feedback (when provided)

## Viewing Metrics in MLflow UI

1. Start MLflow UI:
   ```bash
   mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5025
   ```

2. Navigate to http://localhost:5025

3. View metrics:
   - **Runs** tab shows all tracked operations
   - **Metrics** tab shows resource and accuracy trends
   - **Compare** feature allows comparing different runs

## Example: Complete Query Tracking

```python
from advisor.rag_system import get_rag_system

rag = get_rag_system()

# Query with automatic tracking
response = rag.query("How do I create a glossary?")

# The system automatically logs:
# - Resource consumption (CPU, memory, GPU)
# - Query processing time
# - Vector search relevance scores
# - LLM generation confidence
# - Response quality metrics
```

## Best Practices

1. **Enable tracking in production** to monitor system performance
2. **Collect user feedback** to improve accuracy metrics
3. **Monitor resource trends** to identify performance bottlenecks
4. **Compare experiments** to evaluate system improvements
5. **Set up alerts** for resource thresholds or accuracy drops

## Configuration

Configure tracking in `.env`:

```bash
# Enable/disable MLflow tracking
MLFLOW_ENABLE_TRACKING=true

# MLflow server URI
MLFLOW_TRACKING_URI=http://localhost:5025

# Experiment name
MLFLOW_EXPERIMENT_NAME=egeria-advisor
```

## Troubleshooting

### GPU Metrics Not Showing

- Ensure PyTorch is installed with CUDA support
- Verify GPU is available: `torch.cuda.is_available()`
- Check ROCm installation for AMD GPUs

### High Memory Usage

- Monitor `resource_memory_delta_mb` to identify memory leaks
- Check for large objects not being garbage collected
- Consider batch processing for large operations

### Low Accuracy Scores

- Review `accuracy_relevance_avg` to check vector search quality
- Check `accuracy_confidence_avg` for LLM confidence issues
- Collect more user feedback to validate metrics

## Future Enhancements

Planned improvements:
- Network I/O monitoring
- Disk usage tracking
- Query latency percentiles (p50, p95, p99)
- Automatic anomaly detection
- Real-time alerting
- A/B testing support