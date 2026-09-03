# Quality Improvement Guide for Egeria Advisor

**This is a historical issues-analysis snapshot from early 2026, not a current guide.** The
issues catalogued below were addressed in later phases — e.g. routing accuracy went from
~60% to 100% on the test suite in Phase 7 (see `docs/PROJECT_SUMMARY.md`), and hallucination
rate fell from ~80% to ~27% after the Phase 7b collection split and parameter tuning. Kept
for reference on root-cause analysis; do not treat the issue list as current status.

## 🔍 Current Issues Analysis

Based on testing, we've identified several critical quality issues:

### Issue 1: Inconsistent Query Results
**Problem**: Similar queries produce different results
**Root Causes**:
1. Query type detection ambiguity (66% accuracy)
2. No query normalization consistency
3. Vector search randomness without fixed seed
4. LLM temperature settings causing variation

### Issue 2: Scope Filtering Not Working
**Problem**: "Number of classes in pyegeria folder" returns repo-wide stats
**Root Cause**: Analytics module doesn't parse or filter by scope/path
- Line 138-221 in `advisor/analytics.py` - no path filtering
- Query processor extracts context but doesn't pass it to analytics
- Statistics are pre-computed for entire repo only

### Issue 3: MLflow Metrics Not Showing
**Problem**: Resource monitoring and accuracy tracking not visible in dashboard
**Root Causes**:
1. Enhanced tracking requires explicit activation
2. Metrics logged but not with resource/accuracy tracking enabled
3. Need to verify MLflow UI is showing correct experiment

### Issue 4: Related to Open Query Issues
**Yes** - The 34% test failure rate directly impacts production quality:
- 8 query type detection failures
- 2 context extraction failures
- 1 relationship query failure

---

## 📊 Answer to Your Questions

### 1. How to Report Issues to MLflow

#### Current State
The system logs basic metrics but NOT the enhanced tracking. Here's what's happening:

**In `rag_system.py` line 58-74:**
```python
with self.mlflow_tracker.track_operation(
    operation_name="rag_query",
    params={"query_length": len(user_query)}
) as tracker:
    result = self._process_query(user_query, include_context)
    tracker.log_metrics({
        "response_length": len(result["response"]),
        "num_sources": result.get("num_sources", 0),
        # ... basic metrics only
    })
```

**Missing:** Resource monitoring and accuracy tracking are NOT enabled!

#### Solution: Enable Enhanced Tracking

**Step 1: Modify RAG System Initialization**
```python
# In advisor/rag_system.py line 28
self.mlflow_tracker = get_mlflow_tracker(
    enable_resource_monitoring=True,  # ADD THIS
    enable_accuracy_tracking=True      # ADD THIS
)
```

**Step 2: Add Tracking to Query Processing**
```python
# In advisor/rag_system.py, modify _process_query
with self.mlflow_tracker.track_operation(
    operation_name="rag_query",
    params={
        "query": user_query,
        "query_type": query_analysis['query_type'],
        "include_context": include_context
    },
    track_resources=True,    # ADD THIS
    track_accuracy=True      # ADD THIS
) as tracker:
    result = self._process_query(user_query, include_context)
    
    # Add relevance scores
    if sources:
        for source in sources:
            tracker.add_relevance(source.score)
    
    # Log all metrics
    tracker.log_metrics({
        "response_length": len(result["response"]),
        "num_sources": result.get("num_sources", 0),
        # ... existing metrics
    })
```

**Step 3: Add User Feedback Mechanism**
```python
# After getting response, allow user to rate it
def rate_response(self, run_id: str, rating: float):
    """
    Rate a response quality (1-5 scale).
    
    Args:
        run_id: MLflow run ID
        rating: User rating 1-5
    """
    with mlflow.start_run(run_id=run_id):
        mlflow.log_metric("user_feedback", rating)
```

**Step 4: View in MLflow UI**
```bash
# Access MLflow at http://localhost:5025
# Navigate to: Experiments > egeria-advisor > Select a run
# You'll now see:
# - Metrics: cpu_percent, memory_mb, duration_seconds
# - Metrics: avg_relevance, avg_confidence, avg_feedback
# - Params: query, query_type, etc.
```

### 2. Are Issues Related to Open Query Problems?

**YES - Directly Related**

The 11 failing tests (34%) cause production issues:

| Test Failure | Production Impact |
|--------------|-------------------|
| Query type detection (8 failures) | Wrong handler used → incorrect results |
| Context extraction (2 failures) | Missing scope/module info → can't filter |
| Relationship query (1 failure) | Relationship queries fail |

**Example Flow:**
```
User: "How many classes in pyegeria folder?"
↓
QueryProcessor detects: QUANTITATIVE ✓
↓
Context extraction: NO PATH DETECTED ✗
↓
Analytics: Returns ENTIRE REPO stats ✗
↓
Result: Wrong answer
```

### 3. Why Performance Stats Not Showing

**Root Cause:** Enhanced tracking not activated in production code.

**Current State:**
- `mlflow_tracking.py` has ResourceMonitor and AccuracyTracker ✓
- Tests use them and pass ✓
- **BUT** `rag_system.py` doesn't enable them ✗

**Evidence:**
```python
# advisor/rag_system.py line 28
self.mlflow_tracker = get_mlflow_tracker()  # No parameters!

# Should be:
self.mlflow_tracker = get_mlflow_tracker(
    enable_resource_monitoring=True,
    enable_accuracy_tracking=True
)
```

**Verification Steps:**
```bash
# 1. Check MLflow UI
open http://localhost:5025

# 2. Run a query
egeria-advisor query "How many classes?"

# 3. Check latest run in MLflow
# Look for these metrics:
# - cpu_percent (should be present if enabled)
# - memory_mb (should be present if enabled)
# - duration_seconds (should be present if enabled)
```

### 4. Process to Improve Quality

#### Phase 1: Enable Full Tracking (Immediate - 1 hour)

**Goal:** Capture all query data for analysis

**Tasks:**
1. ✅ Enable resource monitoring in RAG system
2. ✅ Enable accuracy tracking in RAG system
3. ✅ Add user feedback mechanism
4. ✅ Verify metrics appear in MLflow UI

**Files to Modify:**
- `advisor/rag_system.py` - Enable tracking
- `advisor/cli/main.py` - Add feedback prompts

#### Phase 2: Fix Scope Filtering (High Priority - 4 hours)

**Goal:** Support path-scoped queries

**Tasks:**
1. ✅ Enhance query processor to extract path/scope
2. ✅ Add path filtering to analytics module
3. ✅ Generate per-directory statistics
4. ✅ Test with scoped queries

**Implementation:**
```python
# In advisor/analytics.py
def get_classes_in_path(self, path_filter: str) -> int:
    """Get classes in specific path."""
    # Filter statistics by path
    # Return count for that path only
    
# In advisor/query_processor.py
def extract_context(self, query: str) -> Dict[str, Any]:
    # Add path extraction
    path_patterns = [
        r'in (?:the )?([a-zA-Z0-9_/]+) (?:folder|directory|module)',
        r'(?:folder|directory|module) ([a-zA-Z0-9_/]+)',
    ]
    # Extract and return path
```

#### Phase 3: Improve Query Detection (Medium Priority - 6 hours)

**Goal:** Increase test pass rate from 66% to 90%+

**Tasks:**
1. ✅ Add confidence scores to detection
2. ✅ Implement pattern exclusions
3. ✅ Add context-aware detection
4. ✅ Re-run tests and validate

**Strategy:**
```python
# Return confidence with type
def detect_query_type(self, query: str) -> Tuple[QueryType, float]:
    """Return type and confidence score."""
    
# Use confidence for ambiguous cases
if confidence < 0.7:
    # Fall back to vector search + LLM
    # Log low-confidence detection to MLflow
```

#### Phase 4: Collect Real Usage Data (Ongoing - 2 weeks)

**Goal:** Understand actual usage patterns

**Process:**
1. ✅ Deploy with full tracking enabled
2. ✅ Collect 100+ real queries
3. ✅ Analyze in MLflow:
   - Common query patterns
   - Low-confidence detections
   - User feedback scores
   - Performance bottlenecks
4. ✅ Identify improvement opportunities

**Analysis Queries:**
```python
# In MLflow UI or via API
import mlflow

# Get all runs
runs = mlflow.search_runs(experiment_names=["egeria-advisor"])

# Find low-confidence queries
low_conf = runs[runs["metrics.confidence"] < 0.7]

# Find slow queries
slow = runs[runs["metrics.duration_seconds"] > 5.0]

# Find low-rated responses
poor = runs[runs["metrics.user_feedback"] < 3.0]
```

#### Phase 5: Iterative Refinement (Ongoing)

**Goal:** Continuous improvement based on data

**Weekly Process:**
1. Review MLflow metrics
2. Identify top 3 issues
3. Implement fixes
4. Deploy and monitor
5. Repeat

---

## 🚀 Quick Start: Enable Tracking Now

### Step 1: Update RAG System (5 minutes)

```bash
cd ../egeria-v6/egeria-advisor
```

Edit `advisor/rag_system.py`:
```python
# Line 28, change from:
self.mlflow_tracker = get_mlflow_tracker()

# To:
self.mlflow_tracker = get_mlflow_tracker(
    enable_resource_monitoring=True,
    enable_accuracy_tracking=True
)
```

### Step 2: Update Query Method (10 minutes)

In `advisor/rag_system.py`, modify `_process_query` method:

```python
def _process_query(self, user_query: str, include_context: bool) -> Dict[str, Any]:
    """Internal query processing with enhanced tracking."""
    
    # Start tracking
    with self.mlflow_tracker.track_operation(
        operation_name="query_processing",
        params={
            "query": user_query,
            "query_length": len(user_query),
            "include_context": include_context
        },
        track_resources=True,
        track_accuracy=True
    ) as tracker:
        
        # Process query
        query_analysis = self.query_processor.process(user_query)
        
        # Track query type confidence if available
        if "confidence" in query_analysis:
            tracker.add_confidence(query_analysis["confidence"])
        
        # ... rest of processing ...
        
        # Track relevance scores from sources
        if sources:
            for source in sources:
                if hasattr(source, 'score'):
                    tracker.add_relevance(source.score)
        
        # Return result
        return result
```

### Step 3: Test It (5 minutes)

```bash
# Run a query
egeria-advisor query "How many classes are there?"

# Check MLflow UI
open http://localhost:5025

# Look for new metrics:
# - cpu_percent
# - memory_mb  
# - memory_delta_mb
# - duration_seconds
# - avg_relevance (if sources found)
```

### Step 4: Add User Feedback (10 minutes)

Edit `advisor/cli/main.py` to add feedback after each response:

```python
def query_command(query: str):
    """Execute a query."""
    result = rag_system.query(query)
    
    # Display response
    console.print(result["response"])
    
    # Ask for feedback
    if Confirm.ask("Rate this response?"):
        rating = IntPrompt.ask(
            "Rating (1-5)",
            choices=["1", "2", "3", "4", "5"]
        )
        
        # Log feedback to MLflow
        run_id = result.get("mlflow_run_id")
        if run_id:
            with mlflow.start_run(run_id=run_id):
                mlflow.log_metric("user_feedback", float(rating))
```

---

## 📈 Success Metrics

Track these in MLflow to measure improvement:

### Quality Metrics
- **Query Type Accuracy**: Target 90%+ (currently 66%)
- **User Feedback Score**: Target 4.0+ / 5.0
- **Relevance Score**: Target 0.8+ (vector search quality)
- **Confidence Score**: Target 0.85+ (detection confidence)

### Performance Metrics
- **Query Latency p95**: Target < 3 seconds
- **Memory Usage**: Target < 500 MB per query
- **CPU Usage**: Target < 50% average

### Coverage Metrics
- **Scope Filtering**: Target 100% of path-scoped queries
- **Query Type Coverage**: All 9 types working
- **Test Pass Rate**: Target 95%+ (currently 66%)

---

## 🔧 Troubleshooting

### MLflow Metrics Not Appearing

**Check 1: Tracking Enabled?**
```python
# In advisor/rag_system.py
print(self.mlflow_tracker.resource_monitor)  # Should not be None
print(self.mlflow_tracker.accuracy_tracker)  # Should not be None
```

**Check 2: MLflow Server Running?**
```bash
ps aux | grep mlflow
# Should show: mlflow server --host 0.0.0.0 --port 5025
```

**Check 3: Correct Experiment?**
```bash
# Check experiment name
mlflow experiments list
# Should show: egeria-advisor
```

### Inconsistent Results

**Check 1: Query Normalization**
```python
# Test normalization
from advisor.query_processor import get_query_processor
qp = get_query_processor()
print(qp.normalize_query("How Many Classes?"))
# Should output: "how many classes?"
```

**Check 2: Vector Search Seed**
```python
# In advisor/config.py, add:
vector_search:
  random_seed: 42  # For reproducibility
```

**Check 3: LLM Temperature**
```python
# In advisor/config.py
generation:
  temperature: 0.1  # Lower = more consistent
```

---

## 📝 Next Steps

1. **Immediate** (Today):
   - Enable enhanced tracking
   - Verify metrics in MLflow
   - Test with sample queries

2. **This Week**:
   - Implement scope filtering
   - Fix query type detection
   - Collect 50+ real queries

3. **Next Week**:
   - Analyze collected data
   - Implement top 3 improvements
   - Re-test and validate

4. **Ongoing**:
   - Weekly metric reviews
   - Continuous refinement
   - User feedback integration

---

## 📚 Related Documentation

- `MLFLOW_ENHANCED_TRACKING.md` - Complete tracking guide
- `PHASE8_TESTING_PLAN.md` — testing strategy (archived out-of-repo 2026-09-03; `docs/history/` was gitignored and never in the repository)
- `RAG_TUNING_GUIDE.md` - RAG optimization tips
- `tests/unit/test_query_processor.py` - Test cases showing issues

---

## 🎯 Summary

**Current State:**
- ✅ Enhanced tracking implemented
- ✅ Tests created and running
- ❌ Tracking not enabled in production
- ❌ Scope filtering not implemented
- ❌ 34% test failure rate

**Target State:**
- ✅ Full tracking enabled and visible
- ✅ Scope filtering working
- ✅ 95%+ test pass rate
- ✅ Consistent, high-quality results
- ✅ Data-driven continuous improvement

**Path Forward:**
1. Enable tracking (30 minutes)
2. Implement scope filtering (4 hours)
3. Fix query detection (6 hours)
4. Collect real usage data (2 weeks)
5. Iterate based on data (ongoing)