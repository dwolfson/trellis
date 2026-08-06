# Incremental Indexing Design

## Overview

Implement an incremental indexing system that efficiently updates the vector store with only new or modified content, avoiding full re-indexing.

## Key Components

### 1. Change Detection System

**File Tracking Database** (`data/index_state.db` - SQLite)
- Track file paths, modification times, content hashes
- Store last indexed timestamp per file
- Record entity IDs for each file's chunks

**Schema:**
```sql
CREATE TABLE indexed_files (
    file_path TEXT PRIMARY KEY,
    collection_name TEXT NOT NULL,
    last_modified REAL NOT NULL,
    content_hash TEXT NOT NULL,
    last_indexed REAL NOT NULL,
    chunk_count INTEGER NOT NULL,
    entity_ids TEXT NOT NULL  -- JSON array of Milvus entity IDs
);

CREATE TABLE index_metadata (
    collection_name TEXT PRIMARY KEY,
    last_full_index REAL NOT NULL,
    total_files INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL
);
```

### 2. Incremental Ingestion Strategy

**Detection Phase:**
1. Scan source directories for files
2. Compare modification times with tracking DB
3. Compute content hashes for changed files
4. Identify: new files, modified files, deleted files

**Update Phase:**
1. **New files**: Chunk → Embed → Insert
2. **Modified files**: Delete old entities → Chunk → Embed → Insert
3. **Deleted files**: Delete entities from Milvus

**Optimization:**
- Batch operations for efficiency
- Parallel processing for multiple files
- Skip unchanged files entirely

### 3. Implementation Classes

**`IncrementalIndexer`** (new class in `advisor/incremental_indexer.py`)
- Manages change detection
- Coordinates updates
- Maintains tracking database

**`FileTracker`** (helper class)
- SQLite operations
- File hash computation
- Change detection logic

**Enhanced `CodeIngester`**
- Add methods for incremental updates
- Support entity deletion by file
- Batch update operations

## Usage Patterns

### Full Re-index (Initial or Force)
```bash
python scripts/ingest_collections.py --collections pyegeria --force
```

### Incremental Update (Default)
```bash
python scripts/ingest_collections.py --collections pyegeria --incremental
```

### Scheduled Updates
```bash
# Cron job: Update every 6 hours
0 */6 * * * cd /path/to/egeria-advisor && python scripts/ingest_collections.py --incremental --all
```

## Performance Benefits

### Current (Full Re-index)
- Time: ~5-10 minutes per collection
- Resources: High CPU/GPU for embedding all files
- Downtime: Collection unavailable during re-index

### Incremental (Typical Update)
- Time: ~30 seconds (assuming 5% file changes)
- Resources: Minimal - only changed files
- Downtime: None - updates in place

### Example Metrics
- **100 files, 10 changed**: 90% time savings
- **1000 files, 50 changed**: 95% time savings
- **10000 files, 100 changed**: 99% time savings

## Safety Features

### Consistency Checks
- Verify entity counts match tracking DB
- Detect orphaned entities
- Validate collection integrity

### Rollback Support
- Backup tracking DB before updates
- Log all operations for audit
- Support manual rollback if needed

### Conflict Resolution
- Handle concurrent updates
- Lock collections during updates
- Retry failed operations

## Monitoring & Observability

### MLflow Tracking
- Track incremental update metrics
- Log files added/modified/deleted
- Record update duration and throughput

### Metrics Collected
- Files scanned
- Files changed (new/modified/deleted)
- Chunks added/removed
- Update duration
- Embedding throughput

### Alerts
- Large number of changes detected
- Update failures
- Consistency check failures

## Integration Points

### With Existing System
1. **Collection Config**: Use existing collection metadata
2. **Vector Store**: Use existing Milvus operations
3. **Embeddings**: Use existing embedding generator
4. **MLflow**: Integrate with existing tracking

### With Future Features
1. **Monitoring Dashboard**: Display update status
2. **Airflow DAGs**: Schedule incremental updates
3. **CI/CD**: Trigger updates on repo changes

## Implementation Plan

### Phase 1: Core Infrastructure (This Phase)
- [x] Design document
- [ ] Implement FileTracker with SQLite
- [ ] Implement IncrementalIndexer
- [ ] Add incremental mode to ingest_collections.py
- [ ] Create test suite for incremental updates

### Phase 2: Optimization
- [ ] Parallel file processing
- [ ] Batch embedding operations
- [ ] Optimize hash computation

### Phase 3: Advanced Features
- [ ] Automatic change detection (file watchers)
- [ ] Smart chunking (preserve chunk boundaries)
- [ ] Differential updates (modify chunks in place)

## Testing Strategy

### Unit Tests
- File change detection
- Hash computation
- Database operations
- Entity deletion

### Integration Tests
- Full incremental update cycle
- Concurrent updates
- Failure recovery

### Performance Tests
- Benchmark vs full re-index
- Measure overhead of tracking
- Test with various change percentages

## Configuration

### New Settings (config/advisor.yaml)
```yaml
incremental_indexing:
  enabled: true
  tracking_db: "data/index_state.db"
  hash_algorithm: "sha256"
  batch_size: 100
  parallel_workers: 4
  consistency_check: true
```

## API Examples

### Python API
```python
from advisor.incremental_indexer import IncrementalIndexer

# Create indexer
indexer = IncrementalIndexer(collection_name="pyegeria")

# Detect changes
changes = indexer.detect_changes()
print(f"New: {len(changes.new_files)}")
print(f"Modified: {len(changes.modified_files)}")
print(f"Deleted: {len(changes.deleted_files)}")

# Apply updates
result = indexer.apply_updates(changes)
print(f"Updated {result.chunks_added} chunks")
```

### CLI
```bash
# Check for changes (dry run)
python scripts/ingest_collections.py --incremental --dry-run

# Apply incremental updates
python scripts/ingest_collections.py --incremental --collections pyegeria

# Force full re-index
python scripts/ingest_collections.py --force --collections pyegeria

# Update all collections
python scripts/ingest_collections.py --incremental --all
```

## Success Criteria

1. ✅ Incremental updates 10x faster than full re-index
2. ✅ Zero data loss during updates
3. ✅ Automatic detection of all file changes
4. ✅ Comprehensive test coverage (>90%)
5. ✅ MLflow tracking for all operations
6. ✅ Production-ready error handling

## Future Enhancements

1. **Real-time Updates**: File system watchers for instant updates
2. **Smart Chunking**: Preserve chunk boundaries across updates
3. **Distributed Updates**: Parallel updates across multiple collections
4. **Version Control Integration**: Trigger updates on git commits
5. **Rollback Support**: Snapshot and restore collection states