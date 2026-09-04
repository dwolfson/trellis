# MLflow Experiment Tracking Guide for Egeria Advisor

## Overview

This guide details how MLflow will be used to track experiments, tune models, and monitor quality metrics for the Egeria Advisor system.

## MLflow Setup

### Connection Details
- **Tracking URI**: http://localhost:5025
- **Container**: Running in Docker
- **Backend Store**: SQLite (default) or PostgreSQL (recommended for production)
- **Artifact Store**: Local filesystem or S3

### Configuration

```python
# advisor/observability/mlflow_config.py
import mlflow
from typing import Optional

class MLflowConfig:
    def __init__(
        self,
        tracking_uri: str = "http://localhost:5025",
        experiment_name: str = "egeria-advisor",
        enable_autolog: bool = True
    ):
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experiment_name)
        
        if enable_autolog:
            mlflow.autolog()
    
    @staticmethod
    def get_or_create_experiment(name: str) -> str:
        """Get or create an MLflow experiment"""
        experiment = mlflow.get_experiment_by_name(name)
        if experiment is None:
            experiment_id = mlflow.create_experiment(name)
        else:
            experiment_id = experiment.experiment_id
        return experiment_id
```

## Experiment Categories

### 1. Embedding Model Experiments

**Experiment Name**: `embedding-model-tuning`

**Purpose**: Compare different embedding models for semantic search quality

**Parameters to Track**:
```python
params = {
    "model_name": "text-embedding-ada-002",  # or "text-embedding-3-small", etc.
    "embedding_dimension": 1536,
    "chunk_size": 512,
    "chunk_overlap": 50,
    "normalization": "l2"
}
```

**Metrics to Track**:
```python
metrics = {
    "retrieval_precision_at_5": 0.85,
    "retrieval_recall_at_5": 0.72,
    "mrr": 0.78,  # Mean Reciprocal Rank
    "ndcg": 0.82,  # Normalized Discounted Cumulative Gain
    "avg_embedding_time": 0.15,  # seconds
    "cost_per_1k_tokens": 0.0001
}
```

**Example Code**:
```python
with mlflow.start_run(experiment_id=experiment_id, run_name="ada-002-baseline"):
    mlflow.log_params(params)
    
    # Run evaluation
    results = evaluate_embedding_model(model_name, test_queries)
    
    mlflow.log_metrics(results)
    mlflow.log_artifact("embedding_comparison.png")
```

---

### 2. Retrieval Strategy Experiments

**Experiment Name**: `retrieval-optimization`

**Purpose**: Test different retrieval strategies and parameters

**Parameters to Track**:
```python
params = {
    "strategy": "hybrid",  # semantic, keyword, hybrid
    "top_k": 5,
    "similarity_threshold": 0.7,
    "reranking_enabled": True,
    "reranking_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "query_expansion": True,
    "filter_by_type": ["code", "example"]
}
```

**Metrics to Track**:
```python
metrics = {
    "precision_at_k": 0.88,
    "recall_at_k": 0.75,
    "f1_score": 0.81,
    "avg_retrieval_time": 0.25,
    "cache_hit_rate": 0.65,
    "relevance_score": 0.82
}
```

---

### 3. Prompt Engineering Experiments

**Experiment Name**: `prompt-optimization`

**Purpose**: A/B test different prompt templates and strategies

**Parameters to Track**:
```python
params = {
    "prompt_template": "v2_with_examples",
    "system_prompt_version": "v1.2",
    "temperature": 0.7,
    "max_tokens": 1000,
    "include_citations": True,
    "include_code_examples": True,
    "context_window": 5
}
```

**Metrics to Track**:
```python
metrics = {
    "response_quality": 4.2,  # 1-5 scale
    "code_validity_rate": 0.95,
    "citation_accuracy": 0.88,
    "user_satisfaction": 4.1,
    "avg_generation_time": 1.2,
    "tokens_used": 850,
    "cost_per_query": 0.015
}
```

**Prompt Versioning**:
```python
# Log prompt templates as artifacts
with mlflow.start_run():
    mlflow.log_param("prompt_version", "v2.0")
    mlflow.log_artifact("prompts/query_prompt_v2.txt")
    mlflow.log_artifact("prompts/system_prompt_v2.txt")
```

---

### 4. Agent Performance Experiments

**Experiment Name**: `agent-performance`

**Purpose**: Compare different agent implementations and configurations

**Parameters to Track**:
```python
params = {
    "agent_type": "query_agent",  # query, code, conversation, maintenance
    "framework": "bee-ai",
    "llm_model": "gpt-4",
    "max_iterations": 5,
    "tool_selection_strategy": "auto",
    "memory_enabled": True,
    "memory_window": 10
}
```

**Metrics to Track**:
```python
metrics = {
    "task_success_rate": 0.92,
    "avg_iterations": 2.3,
    "avg_response_time": 3.5,
    "tool_usage_efficiency": 0.85,
    "context_retention": 0.78,
    "user_satisfaction": 4.3
}
```

---

### 5. End-to-End Quality Experiments

**Experiment Name**: `e2e-quality-evaluation`

**Purpose**: Track overall system quality metrics

**Parameters to Track**:
```python
params = {
    "system_version": "v0.1.0",
    "test_dataset": "query_set_v1",
    "num_queries": 100,
    "evaluation_date": "2026-02-13"
}
```

**Metrics to Track**:
```python
metrics = {
    # Accuracy Metrics
    "overall_accuracy": 0.87,
    "factual_accuracy": 0.92,
    "code_accuracy": 0.89,
    
    # Performance Metrics
    "avg_response_time": 2.1,
    "p95_response_time": 4.5,
    "p99_response_time": 7.2,
    
    # Quality Metrics
    "relevance_score": 0.85,
    "completeness_score": 0.83,
    "clarity_score": 0.88,
    
    # User Experience
    "user_satisfaction": 4.2,
    "task_completion_rate": 0.91,
    
    # Cost Metrics
    "avg_cost_per_query": 0.018,
    "total_tokens_used": 85000
}
```

---

## Continuous Monitoring

### Real-time Query Metrics

Track every query in production:

```python
# advisor/observability/query_logger.py
import mlflow
from datetime import datetime

class QueryLogger:
    def __init__(self, experiment_name: str = "production-queries"):
        self.experiment_id = mlflow.get_experiment_by_name(experiment_name).experiment_id
    
    def log_query(
        self,
        query: str,
        agent_type: str,
        response_time: float,
        tokens_used: int,
        user_feedback: Optional[int] = None
    ):
        """Log individual query metrics"""
        with mlflow.start_run(experiment_id=self.experiment_id):
            mlflow.log_params({
                "query_hash": hash(query),
                "agent_type": agent_type,
                "timestamp": datetime.now().isoformat()
            })
            
            mlflow.log_metrics({
                "response_time": response_time,
                "tokens_used": tokens_used,
                "user_feedback": user_feedback or 0
            })
            
            # Log query text as artifact for analysis
            with open("query.txt", "w") as f:
                f.write(query)
            mlflow.log_artifact("query.txt")
```

### Daily Aggregated Metrics

```python
# advisor/observability/daily_metrics.py
def log_daily_metrics():
    """Aggregate and log daily metrics"""
    with mlflow.start_run(experiment_id=daily_experiment_id):
        mlflow.log_params({
            "date": datetime.now().date().isoformat(),
            "total_queries": daily_query_count
        })
        
        mlflow.log_metrics({
            "avg_response_time": daily_avg_response_time,
            "avg_user_satisfaction": daily_avg_satisfaction,
            "error_rate": daily_error_rate,
            "cache_hit_rate": daily_cache_hit_rate,
            "total_cost": daily_total_cost
        })
```

---

## Model Registry

Use MLflow Model Registry to version and manage models:

```python
# Register embedding model
mlflow.register_model(
    model_uri=f"runs:/{run_id}/embedding_model",
    name="egeria-embedding-model"
)

# Transition to production
client = mlflow.tracking.MlflowClient()
client.transition_model_version_stage(
    name="egeria-embedding-model",
    version=2,
    stage="Production"
)
```

---

## Dashboards and Visualization

### Key Dashboards to Create

1. **Experiment Comparison Dashboard**
   - Compare different embedding models
   - Compare retrieval strategies
   - Compare prompt versions

2. **Production Monitoring Dashboard**
   - Real-time query metrics
   - Error rates and alerts
   - Cost tracking
   - User satisfaction trends

3. **Quality Metrics Dashboard**
   - Accuracy trends over time
   - Response quality distribution
   - Code validity rates
   - Citation accuracy

### Example: Creating a Custom Dashboard

```python
# advisor/observability/dashboards.py
import mlflow
import pandas as pd
import plotly.express as px

def create_experiment_comparison_dashboard(experiment_ids: list):
    """Create comparison dashboard for multiple experiments"""
    runs_data = []
    
    for exp_id in experiment_ids:
        runs = mlflow.search_runs(experiment_ids=[exp_id])
        runs_data.append(runs)
    
    df = pd.concat(runs_data)
    
    # Create visualizations
    fig = px.scatter(
        df,
        x="metrics.avg_response_time",
        y="metrics.accuracy",
        color="params.model_name",
        size="metrics.cost_per_query",
        hover_data=["params.temperature", "metrics.user_satisfaction"]
    )
    
    fig.write_html("experiment_comparison.html")
    mlflow.log_artifact("experiment_comparison.html")
```

---

## Best Practices

### 1. Consistent Naming Conventions

```python
# Experiment names
EMBEDDING_EXPERIMENTS = "embedding-model-tuning"
RETRIEVAL_EXPERIMENTS = "retrieval-optimization"
PROMPT_EXPERIMENTS = "prompt-optimization"
AGENT_EXPERIMENTS = "agent-performance"
PRODUCTION_MONITORING = "production-queries"

# Run names
run_name = f"{model_name}_{timestamp}_{description}"
```

### 2. Comprehensive Logging

Always log:
- All hyperparameters
- All metrics
- Model artifacts
- Configuration files
- Sample outputs
- Error logs (if any)

### 3. Tagging

Use tags for better organization:

```python
mlflow.set_tags({
    "team": "egeria-advisor",
    "purpose": "baseline",
    "priority": "high",
    "status": "completed"
})
```

### 4. Artifact Organization

```
artifacts/
├── models/
│   ├── embedding_model.pkl
│   └── reranker_model.pkl
├── configs/
│   ├── retrieval_config.yaml
│   └── prompt_config.yaml
├── visualizations/
│   ├── confusion_matrix.png
│   └── performance_chart.png
└── logs/
    ├── error_log.txt
    └── query_samples.json
```

---

## Integration with CI/CD

### Automated Experiment Runs

```yaml
# .github/workflows/run-experiments.yml
name: Run MLflow Experiments

on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM
  workflow_dispatch:

jobs:
  run-experiments:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Run experiments
        env:
          MLFLOW_TRACKING_URI: ${{ secrets.MLFLOW_TRACKING_URI }}
        run: python scripts/run_daily_experiments.py
```

---

## Alerting and Monitoring

### Set up alerts for key metrics:

```python
# advisor/observability/alerts.py
def check_metrics_and_alert():
    """Check metrics and send alerts if thresholds are breached"""
    recent_runs = mlflow.search_runs(
        experiment_ids=[production_experiment_id],
        filter_string="metrics.error_rate > 0.05"
    )
    
    if len(recent_runs) > 0:
        send_alert(
            title="High Error Rate Detected",
            message=f"Error rate: {recent_runs['metrics.error_rate'].mean():.2%}"
        )
```

---

## Example: Complete Experiment Workflow

```python
# scripts/run_embedding_experiment.py
import mlflow
from advisor.data_prep import prepare_test_data
from advisor.vector_store import get_vector_store
from advisor.evaluation import evaluate_retrieval

def run_embedding_experiment(model_name: str, params: dict):
    """Run a complete embedding model experiment"""
    
    # Set up experiment
    experiment_id = mlflow.set_experiment("embedding-model-tuning")
    
    with mlflow.start_run(run_name=f"{model_name}_{datetime.now().strftime('%Y%m%d')}"):
        # Log parameters
        mlflow.log_params(params)
        mlflow.log_param("model_name", model_name)
        
        # Prepare data
        test_queries, ground_truth = prepare_test_data()
        
        # Generate embeddings
        start_time = time.time()
        embeddings = generate_embeddings(test_queries, model_name)
        embedding_time = time.time() - start_time
        
        # Store in the configured vector store backend (pgvector)
        vector_store = get_vector_store()
        vector_store.insert_data("pyegeria", texts=test_queries, ids=None, metadata=None)
        
        # Evaluate retrieval
        results = evaluate_retrieval(test_queries, ground_truth, vector_store)
        
        # Log metrics
        mlflow.log_metrics({
            "precision_at_5": results['precision'],
            "recall_at_5": results['recall'],
            "mrr": results['mrr'],
            "avg_embedding_time": embedding_time / len(test_queries)
        })
        
        # Log artifacts
        mlflow.log_artifact("evaluation_report.html")
        mlflow.log_artifact("confusion_matrix.png")
        
        # Register model if it's the best so far
        if results['mrr'] > 0.85:
            mlflow.register_model(
                model_uri=f"runs:/{mlflow.active_run().info.run_id}/model",
                name="egeria-embedding-model"
            )
        
        return results

if __name__ == "__main__":
    models_to_test = [
        "text-embedding-ada-002",
        "text-embedding-3-small",
        "text-embedding-3-large"
    ]
    
    for model in models_to_test:
        run_embedding_experiment(model, {"chunk_size": 512, "overlap": 50})
```

---

## Phoenix Arize Integration (Advanced)

When MLflow metrics aren't sufficient, use Phoenix Arize for:

### 1. Detailed Tracing

```python
from phoenix.trace import trace

@trace
def process_query(query: str) -> Response:
    """Trace entire query processing pipeline"""
    # Phoenix automatically captures:
    # - Function inputs/outputs
    # - Execution time
    # - LLM calls
    # - Embeddings
    # - Errors
    pass
```

### 2. LLM Observability

```python
from phoenix.trace.langchain import LangChainInstrumentor

# Auto-instrument LangChain
LangChainInstrumentor().instrument()

# All LangChain calls are now traced
```

### 3. Embedding Drift Detection

Phoenix can detect when embeddings drift from training distribution, indicating potential quality issues.

### 4. Real-time Monitoring

Phoenix provides real-time dashboards for:
- LLM call latency
- Token usage
- Error rates
- Embedding quality

---

## Summary

This MLflow setup provides:

1. **Experiment Tracking**: Compare models, prompts, and strategies
2. **Quality Monitoring**: Track accuracy and user satisfaction
3. **Performance Metrics**: Monitor response times and costs
4. **Model Registry**: Version and deploy models
5. **Continuous Improvement**: Data-driven optimization

All experiments and metrics are centralized in MLflow at http://localhost:5025, making it easy to compare approaches and track progress over time.