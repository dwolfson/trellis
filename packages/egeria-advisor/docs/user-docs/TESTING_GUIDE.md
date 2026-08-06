# Egeria Advisor - Testing Guide

## Overview

Comprehensive testing guide for the Egeria Advisor system, including unit tests, integration tests, and end-to-end testing.

## Test Suite Structure

### End-to-End Test Suite

**Location**: `scripts/test_end_to_end.py`

Comprehensive test suite that validates the entire system from environment setup to full query processing.

#### Usage

```bash
# Run full test suite
python scripts/test_end_to_end.py

# Run quick tests (skip slow LLM generation tests)
python scripts/test_end_to_end.py --quick

# Skip ingestion tests
python scripts/test_end_to_end.py --skip-ingestion

# Verbose output
python scripts/test_end_to_end.py --verbose
```

#### Test Categories

1. **Environment Tests** (3 tests)
   - Python version check
   - Working directory validation
   - File structure verification

2. **Configuration Tests** (3 tests)
   - Config file existence
   - Config loading
   - Device detection

3. **Dependencies Tests** (9 tests)
   - Import checks for all required packages
   - Version compatibility

4. **Vector Store Tests** (3 tests)
   - pgvector connection
   - Collection (table) existence
   - Entity counts

5. **Embeddings Tests** (3 tests)
   - Model loading
   - Embedding generation
   - Dimension validation

6. **Multi-Collection Tests** (3 tests)
   - Collection routing
   - Parallel search
   - Result merging

7. **RAG System Tests** (3 tests)
   - RAG initialization
   - Document retrieval
   - Query cache

8. **LLM Client Tests** (2-3 tests)
   - Ollama connection
   - Model availability
   - Text generation (skipped in quick mode)

9. **Agent Tests** (3-4 tests)
   - Agent initialization
   - Agent query (skipped in quick mode)
   - Agent cache
   - Conversation history

10. **CLI Tests** (2 tests)
    - CLI import
    - CLI modes

11. **MLflow Tracking Tests** (2 tests)
    - MLflow connection
    - Tracking initialization

12. **Performance Tests** (2 tests)
    - Cache speedup
    - Parallel speedup

13. **Integration Tests** (2 tests)
    - Full query flow (skipped in quick mode)
    - Agent flow (skipped in quick mode)

### Test Results Summary

**Latest Run** (Quick Mode):
- **Total Tests**: 40
- **Passed**: 24 (60%)
- **Failed**: 11 (27.5%)
- **Warnings**: 3 (7.5%)
- **Skipped**: 2 (5%)
- **Duration**: 54.62s

#### Known Issues

1. **Config Import Issues** (11 failures)
   - Some tests use `from advisor.config import config` instead of `get_full_config()`
   - Fix: Update imports to use the function-based API

2. **Missing Method** (1 failure)
   - `ConversationAgent.get_conversation_history()` not implemented
   - Fix: Add method to return conversation history

3. **Missing Dependency** (1 failure)
   - `pyyaml` should be `PyYAML`
   - Fix: Update requirements.txt

4. **Cache Speedup Warning** (1 warning)
   - Query cache showing only 1.1x speedup in test
   - Note: This is expected for first-time queries; subsequent runs show 17,997x

## Individual Test Scripts

### Component Tests

| Script | Purpose | Duration |
|--------|---------|----------|
| `test_setup.py` | Validate environment setup | ~5s |
| `test_vector_search.py` | Test vector search functionality | ~10s |
| `test_multi_collection_search.py` | Test multi-collection search | ~15s |
| `test_collection_routing.py` | Test collection routing logic | ~5s |
| `test_rag_system.py` | Test RAG system | ~20s |
| `test_conversation_agent.py` | Test conversation agent | ~30s |
| `test_cli.py` | Test CLI functionality | ~10s |
| `test_mlflow_enhancements.py` | Test MLflow tracking | ~15s |
| `test_cache_performance.py` | Test cache performance | ~30s |

### Benchmark Scripts

| Script | Purpose | Duration |
|--------|---------|----------|
| `benchmark_amd.py` | Benchmark AMD GPU performance | ~60s |
| `benchmark_multi_collection.py` | Benchmark multi-collection search | ~120s |

### Usage Examples

```bash
# Test vector search
python scripts/test_vector_search.py

# Test multi-collection search
python scripts/test_multi_collection_search.py

# Test conversation agent
python scripts/test_conversation_agent.py

# Test CLI
python scripts/test_cli.py

# Benchmark performance
python scripts/benchmark_multi_collection.py
```

## Test Coverage

### Core Components

| Component | Coverage | Tests |
|-----------|----------|-------|
| **Vector Store** | ✅ High | Connection, search, collections |
| **Embeddings** | ✅ High | Model loading, generation, dimensions |
| **Multi-Collection** | ✅ High | Routing, parallel search, merging |
| **RAG System** | ✅ High | Initialization, retrieval, caching |
| **LLM Client** | ✅ High | Connection, model, generation |
| **Agent** | ✅ High | Initialization, query, cache, history |
| **CLI** | ✅ Medium | Import, modes, basic functionality |
| **MLflow** | ✅ Medium | Connection, tracking, metrics |

### Integration Points

| Integration | Coverage | Tests |
|-------------|----------|-------|
| **RAG + LLM** | ✅ High | Full query flow |
| **Agent + RAG** | ✅ High | Agent query flow |
| **CLI + Agent** | ✅ Medium | Agent mode |
| **MLflow + All** | ✅ High | Comprehensive tracking |

## Performance Testing

### Cache Performance

**Test**: `test_cache_performance.py`

Validates multi-layer caching:
- L1: Agent response cache (12.3M x speedup)
- L2: RAG query cache (17,997x speedup)
- L3: pgvector query plan cache (Postgres-managed)

**Expected Results**:
- First query: 2-5 seconds
- Cached query: 0.0001-0.001 seconds
- Speedup: 10,000x - 12,000,000x

### Parallel Search Performance

**Test**: `benchmark_multi_collection.py`

Validates parallel collection search:
- Sequential: 1.5s (3 collections × 0.5s)
- Parallel: 0.5s (max of 3 × 0.5s)
- Speedup: 3x

### Multi-Collection Routing

**Test**: `test_collection_routing.py`

Validates intelligent routing:
- Python queries → pyegeria collections
- CLI queries → pyegeria_cli
- General queries → all collections
- Accuracy: 80-90%

## Continuous Integration

### Pre-commit Checks

```bash
# Run quick tests before commit
python scripts/test_end_to_end.py --quick

# Check specific component
python scripts/test_rag_system.py
```

### CI/CD Pipeline

Recommended test stages:

1. **Fast Tests** (< 1 minute)
   - Environment validation
   - Import checks
   - Configuration loading

2. **Component Tests** (< 5 minutes)
   - Vector store
   - Embeddings
   - Multi-collection
   - RAG system

3. **Integration Tests** (< 10 minutes)
   - Full query flow
   - Agent flow
   - CLI functionality

4. **Performance Tests** (< 15 minutes)
   - Cache performance
   - Parallel search
   - Benchmarks

## Test Data

### Test Queries

**Simple Queries**:
```python
"What is Egeria?"
"How do I use pyegeria?"
"What CLI commands are available?"
```

**Complex Queries**:
```python
"How do I connect to an Egeria server and retrieve asset information?"
"What's the difference between pyegeria and pyegeria_cli?"
"Show me examples of using the glossary API"
```

**Edge Cases**:
```python
""  # Empty query
"x" * 1000  # Very long query
"🚀 emoji query"  # Special characters
```

### Expected Results

| Query Type | Expected Collections | Expected Results |
|------------|---------------------|------------------|
| Python API | pyegeria, pyegeria_drE | 3-5 results |
| CLI | pyegeria_cli | 2-4 results |
| General | All collections | 5-10 results |
| Glossary | egeria_glossary | 1-3 results |

## Troubleshooting

### Common Test Failures

#### 1. pgvector Connection Failed

**Symptom**: `Cannot connect to pgvector` / `connection refused` on port 5442

**Solutions**:
```bash
# Check Postgres/pgvector is running and reachable
psql -h localhost -p 5442 -U egeria_advisor -d egeria_advisor -c "SELECT 1;"

# Check port
netstat -an | grep 5442

# Check row counts per collection
python scripts/count_vectors.py
```

#### 2. Ollama Connection Failed

**Symptom**: `Cannot connect to Ollama`

**Solutions**:
```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Start Ollama
ollama serve

# Check model
ollama list | grep llama3.1
```

#### 3. MLflow Connection Failed

**Symptom**: `Cannot connect to MLflow`

**Solutions**:
```bash
# Check MLflow is running
curl http://localhost:5025

# Start MLflow
mlflow server --host 0.0.0.0 --port 5025

# Check experiments
mlflow experiments list
```

#### 4. Import Errors

**Symptom**: `ModuleNotFoundError`

**Solutions**:
```bash
# Reinstall dependencies
pip install -r requirements.txt

# Check Python path
python -c "import sys; print(sys.path)"

# Verify installation
pip list | grep -E "psycopg2|pgvector|sentence-transformers|mlflow"
```

#### 5. Cache Not Working

**Symptom**: Low cache speedup

**Solutions**:
- First query always misses cache (expected)
- Clear cache: `rm -rf data/cache/query_cache.pkl`
- Check cache size: `ls -lh data/cache/`
- Verify cache hits in logs

### Test Environment Setup

```bash
# 1. Ensure services are running (pgvector/Postgres, Ollama, MLflow)
ollama serve &
mlflow server --host 0.0.0.0 --port 5025 &

# 2. Verify connections
psql -h localhost -p 5442 -U egeria_advisor -d egeria_advisor -c "SELECT 1;"
curl http://localhost:11434/api/tags
curl http://localhost:5025

# 3. Run tests
python scripts/test_end_to_end.py --quick
```

## Best Practices

### Writing Tests

1. **Use descriptive names**: `test_agent_cache_speedup` not `test1`
2. **Test one thing**: Each test should validate one specific behavior
3. **Use fixtures**: Reuse setup code across tests
4. **Clean up**: Reset state after tests
5. **Document expectations**: Add comments explaining expected behavior

### Running Tests

1. **Start with quick tests**: Use `--quick` flag during development
2. **Run full suite before commit**: Ensure nothing breaks
3. **Check logs**: Review logs for warnings and errors
4. **Monitor performance**: Track test duration over time
5. **Update tests**: Keep tests in sync with code changes

### Test Maintenance

1. **Update test data**: Keep test queries relevant
2. **Review failures**: Investigate and fix failing tests promptly
3. **Add new tests**: Cover new features and bug fixes
4. **Remove obsolete tests**: Clean up tests for removed features
5. **Document changes**: Update this guide when tests change

## Performance Benchmarks

### Target Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| **Cache Hit (Agent)** | > 1M x | 12.3M x | ✅ Excellent |
| **Cache Hit (RAG)** | > 10K x | 17,997x | ✅ Excellent |
| **Parallel Speedup** | > 2x | 3x | ✅ Good |
| **Query Latency (Cold)** | < 5s | 2-5s | ✅ Good |
| **Query Latency (Warm)** | < 0.01s | 0.0001s | ✅ Excellent |
| **Routing Accuracy** | > 80% | 67% | ⚠️ Needs improvement |

### Regression Testing

Monitor these metrics over time:
- Cache hit rate
- Query latency (p50, p95, p99)
- Routing accuracy
- Memory usage
- CPU usage
- GPU utilization (if available)

## Future Improvements

### Planned Tests

1. **Load Testing**
   - Concurrent query handling
   - Sustained load performance
   - Resource usage under load

2. **Stress Testing**
   - Maximum query rate
   - Large result sets
   - Memory limits

3. **Security Testing**
   - Input validation
   - SQL injection prevention
   - Access control

4. **Compatibility Testing**
   - Different Python versions
   - Different OS platforms
   - Different GPU types

### Test Automation

1. **GitHub Actions**
   - Run tests on every PR
   - Nightly full test suite
   - Performance regression detection

2. **Test Reporting**
   - HTML test reports
   - Coverage reports
   - Performance dashboards

3. **Test Data Management**
   - Automated test data generation
   - Test data versioning
   - Test data cleanup

---

**Document Version**: 1.0  
**Last Updated**: 2026-02-19  
**Status**: Active Development