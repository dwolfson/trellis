# Dataset/Collection Tracking and Analytics Enhancement

**Date**: 2026-03-07  
**Status**: Analysis and Recommendations

## Current State Analysis

### What's Currently Tracked

#### 1. User Feedback (feedback_collector.py)
**Stored in**: `data/feedback/user_feedback.jsonl`  
**Logged to MLflow**: Yes (via `log_feedback_to_mlflow()`)

**Current Fields**:
- ✅ `timestamp` - When feedback was given
- ✅ `query` - User's query text
- ✅ `query_type` - Detected query type (CODE, CONCEPT, etc.)
- ✅ `collections_searched` - List of collections searched
- ✅ `response_length` - Length of response
- ✅ `rating` - positive/negative/neutral
- ✅ `feedback_text` - Free-text comment
- ✅ `suggested_collection` - User's collection suggestion
- ✅ `session_id` - Session identifier
- ✅ `star_rating` - 1-5 star rating (Phase 1)
- ✅ `category` - accuracy/completeness/clarity/relevance

**Statistics Tracked**:
- Total feedback count
- Positive/negative/neutral counts
- By query type
- **By collection** ✅ (but not displayed in dashboard)
- Routing corrections
- Star ratings and averages
- Category-specific ratings

#### 2. Query Metrics (metrics_collector.py)
**Stored in**: `data/metrics.db` (SQLite)

**Current Fields**:
- ✅ `timestamp`
- ✅ `query_text`
- ✅ `collection_name` - Single collection (not multi-collection aware)
- ✅ `latency_ms`
- ✅ `cache_hit`
- ✅ `success`
- ✅ `query_type`
- ✅ `result_count`
- ✅ `embedding_time_ms`
- ✅ `search_time_ms`
- ✅ `llm_time_ms`
- ✅ `avg_relevance_score`
- ✅ `sources_json` - JSON string of source metadata

#### 3. MLflow Tracking (mlflow_tracking.py)
**Tracked in MLflow**:
- ✅ Resource metrics (CPU, memory, GPU)
- ✅ Accuracy metrics (feedback, relevance, confidence)
- ✅ Operation duration
- ✅ Query lifecycle metrics (via `track_query_lifecycle()`)

**Query Lifecycle Includes**:
- Query ID, text, classification
- Collection metrics (per-collection)
- Assembly metrics
- LLM metrics (time, tokens)
- Total latency
- Cache hit status
- User feedback score
- Hallucination detection

---

## Problems Identified

### 1. ❌ Collections Not Visible in Dashboard
**Issue**: Collection usage data exists but isn't displayed in dashboards

**Root Cause**:
- Feedback collector tracks `collections_searched` ✅
- Metrics collector has `collection_name` field ✅
- Dashboard doesn't query or display this data ❌

**Impact**: Can't see which collections are being used or how often

### 2. ❌ Multi-Collection Queries Not Fully Tracked
**Issue**: When multiple collections are searched, only partial tracking

**Current State**:
- Feedback: Tracks list of collections ✅
- Metrics: Only tracks single `collection_name` ❌
- MLflow: Has `collection_metrics` list ✅

**Impact**: Incomplete picture of multi-collection query patterns

### 3. ❌ No Collection Performance Comparison
**Issue**: Can't compare performance across collections

**Missing Metrics**:
- Per-collection search time
- Per-collection result quality
- Per-collection cache hit rates
- Per-collection user satisfaction

### 4. ❌ User Feedback Not Fully Integrated with MLflow
**Issue**: Feedback is logged but not easily queryable

**Current State**:
- Feedback stored in JSONL file ✅
- `log_feedback_to_mlflow()` method exists ✅
- But method implementation not visible in code shown ❌

---

## Recommended Enhancements

### Phase 1: Collection Visibility (High Priority)

#### A. Enhance Metrics Collection

**File**: `advisor/metrics_collector.py`

**Changes Needed**:
1. Add `collections_searched` field (list) to `QueryMetric`
2. Add per-collection breakdown:
   ```python
   collection_search_times: Optional[Dict[str, float]] = None
   collection_result_counts: Optional[Dict[str, int]] = None
   collection_relevance_scores: Optional[Dict[str, float]] = None
   ```

3. Update database schema:
   ```sql
   ALTER TABLE query_metrics ADD COLUMN collections_searched TEXT;
   ALTER TABLE query_metrics ADD COLUMN collection_metrics_json TEXT;
   ```

#### B. Enhance Dashboard Display

**File**: `advisor/dashboard/streamlit_dashboard.py`

**Add New Sections**:
1. **Collection Usage Statistics**
   - Total queries per collection
   - Queries over time per collection
   - Collection usage percentage pie chart

2. **Collection Performance Comparison**
   - Average latency per collection
   - Cache hit rate per collection
   - Average relevance score per collection

3. **Collection User Satisfaction**
   - Feedback ratings per collection
   - Star ratings per collection
   - User comments per collection

#### C. Enhance MLflow Integration

**File**: `advisor/feedback_collector.py`

**Implement `log_feedback_to_mlflow()`**:
```python
def log_feedback_to_mlflow(self, entry: FeedbackEntry):
    """Log feedback entry to MLflow."""
    try:
        import mlflow
        
        # Log as metrics
        mlflow.log_metrics({
            "feedback_rating_normalized": entry.get_normalized_rating(),
            "feedback_star_rating": entry.star_rating or 0,
            "feedback_response_length": entry.response_length
        })
        
        # Log as parameters
        mlflow.log_params({
            "feedback_query_type": entry.query_type,
            "feedback_collections": ",".join(entry.collections_searched),
            "feedback_category": entry.category or "none"
        })
        
        # Log as artifact
        mlflow.log_dict(entry.to_dict(), f"feedback_{entry.timestamp}.json")
        
    except Exception as e:
        logger.warning(f"Failed to log feedback to MLflow: {e}")
```

---

### Phase 2: Advanced Analytics (Medium Priority)

#### Additional Useful Parameters to Capture

**1. Query Context**:
- `user_id` - Track per-user patterns
- `session_duration` - How long user has been active
- `query_sequence_number` - Position in conversation
- `previous_query` - For context understanding
- `refinement_of_query_id` - If query is a refinement

**2. Collection Selection**:
- `collections_considered` - All collections evaluated
- `collection_selection_reason` - Why collections were chosen
- `collection_confidence_scores` - Routing confidence per collection
- `collections_excluded` - Collections explicitly not searched

**3. Result Quality**:
- `result_diversity_score` - How diverse are results
- `cross_collection_overlap` - Duplicate results across collections
- `result_freshness` - Age of retrieved documents
- `source_file_paths` - Actual files retrieved from

**4. User Behavior**:
- `time_to_feedback` - How long until user gave feedback
- `query_reformulation_count` - How many times query was refined
- `follow_up_query` - If user asked follow-up
- `session_satisfaction_trend` - Satisfaction over session

**5. System Performance**:
- `collection_load_time` - Time to load collection
- `index_freshness` - When collection was last updated
- `concurrent_queries` - Number of simultaneous queries
- `queue_wait_time` - Time spent waiting in queue

**6. Content Analysis**:
- `query_complexity_score` - Estimated query difficulty
- `response_completeness_score` - How complete the answer is
- `code_snippet_count` - Number of code examples in response
- `documentation_link_count` - Number of doc links provided

---

### Phase 3: Real-time Dashboard (Medium Priority)

#### Dashboard Enhancements Needed

**File**: `advisor/dashboard/streamlit_dashboard.py`

**New Visualizations**:

1. **Collection Heatmap**
   - X-axis: Time periods (hourly/daily)
   - Y-axis: Collections
   - Color: Query volume
   - Shows usage patterns over time

2. **Collection Performance Matrix**
   ```
   Collection    | Queries | Avg Latency | Cache Hit % | Satisfaction
   --------------|---------|-------------|-------------|-------------
   pyegeria      | 1,234   | 145ms       | 67%         | 4.2/5
   egeria_docs   | 892     | 98ms        | 82%         | 4.5/5
   egeria_java   | 456     | 203ms       | 45%         | 3.8/5
   ```

3. **Collection Co-occurrence Graph**
   - Network graph showing which collections are searched together
   - Node size = query volume
   - Edge thickness = co-occurrence frequency

4. **User Feedback Timeline**
   - Timeline of feedback events
   - Color-coded by rating
   - Filterable by collection
   - Shows trends over time

5. **Collection Health Dashboard**
   - Entity count per collection
   - Last update timestamp
   - Index freshness indicator
   - Storage size
   - Health score (0-100)

---

## Implementation Priority

### Immediate (This Week)
1. ✅ **Implement `log_feedback_to_mlflow()`** - Connect feedback to MLflow
2. ✅ **Add collection metrics to dashboard** - Display existing data
3. ✅ **Create collection usage report** - Simple query statistics

### Short-term (Next 2 Weeks)
1. **Enhance QueryMetric dataclass** - Add multi-collection fields
2. **Update database schema** - Support collection lists
3. **Add collection performance charts** - Comparison visualizations
4. **Implement collection heatmap** - Usage over time

### Medium-term (1 Month)
1. **Add advanced parameters** - User context, behavior tracking
2. **Create collection co-occurrence graph** - Relationship visualization
3. **Implement real-time updates** - Live dashboard refresh
4. **Add collection health monitoring** - Proactive alerts

---

## Example Queries for Analysis

### Collection Usage Analysis
```sql
-- Most used collections
SELECT 
    collection_name,
    COUNT(*) as query_count,
    AVG(latency_ms) as avg_latency,
    AVG(avg_relevance_score) as avg_relevance
FROM query_metrics
WHERE timestamp > datetime('now', '-7 days')
GROUP BY collection_name
ORDER BY query_count DESC;
```

### Collection Performance Comparison
```sql
-- Performance by collection and query type
SELECT 
    collection_name,
    query_type,
    COUNT(*) as queries,
    AVG(latency_ms) as avg_latency,
    SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as cache_hit_rate
FROM query_metrics
GROUP BY collection_name, query_type
ORDER BY collection_name, queries DESC;
```

### User Satisfaction by Collection
```python
# From feedback stats
stats = feedback_collector.get_feedback_stats()
for collection, data in stats["by_collection"].items():
    satisfaction = data["positive"] / data["total"] if data["total"] > 0 else 0
    print(f"{collection}: {satisfaction:.1%} satisfaction ({data['total']} queries)")
```

---

## MLflow Dashboard Queries

### Collection Metrics in MLflow
```python
from mlflow.tracking import MlflowClient

client = MlflowClient()
runs = client.search_runs(experiment_ids=["0"])

# Extract collection usage
collection_usage = {}
for run in runs:
    collections = run.data.params.get("collections_searched", "").split(",")
    for collection in collections:
        if collection:
            collection_usage[collection] = collection_usage.get(collection, 0) + 1

# Sort by usage
sorted_collections = sorted(collection_usage.items(), key=lambda x: x[1], reverse=True)
for collection, count in sorted_collections:
    print(f"{collection}: {count} queries")
```

---

## Benefits of Enhanced Tracking

### For Users
- ✅ See which collections are most useful
- ✅ Understand query routing decisions
- ✅ Provide targeted feedback per collection
- ✅ Track satisfaction trends

### For Developers
- ✅ Identify underutilized collections
- ✅ Optimize slow collections
- ✅ Improve routing algorithms
- ✅ Detect collection quality issues

### For Operations
- ✅ Monitor collection health
- ✅ Plan capacity and scaling
- ✅ Identify performance bottlenecks
- ✅ Track system usage patterns

---

## Next Steps

1. **Review this document** with team
2. **Prioritize enhancements** based on immediate needs
3. **Implement Phase 1** (collection visibility)
4. **Test dashboard updates** with real data
5. **Gather user feedback** on new visualizations
6. **Plan Phase 2** based on learnings

---

**Document Owner**: Development Team  
**Last Updated**: 2026-03-07  
**Next Review**: After Phase 1 implementation