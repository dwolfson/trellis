#!/usr/bin/env python3
"""
Test script for incremental indexing functionality.

Tests file tracking, change detection, and incremental updates.
"""

import sys
import tempfile
import shutil
from pathlib import Path
from typing import List

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.incremental_indexer import FileTracker, IncrementalIndexer, ChangeSet
from advisor.collection_config import get_collection
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


console = Console()


def test_file_tracker():
    """Test FileTracker functionality."""
    console.print("\n[bold cyan]Testing FileTracker...[/bold cyan]")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        tracker = FileTracker(db_path)
        
        # Create test file
        test_file = Path(tmpdir) / "test.py"
        test_file.write_text("print('hello')")
        
        # Test hash computation
        file_hash = tracker.compute_file_hash(test_file)
        assert file_hash, "Hash should not be empty"
        console.print(f"✓ Hash computation: {file_hash[:16]}...")
        
        # Test tracking
        tracker.track_file(
            test_file,
            "test_collection",
            file_hash,
            5,
            [1, 2, 3, 4, 5]
        )
        console.print("✓ File tracked successfully")
        
        # Test retrieval
        tracked = tracker.get_tracked_file(str(test_file), "test_collection")
        assert tracked is not None, "File should be tracked"
        assert tracked['chunk_count'] == 5, "Chunk count should match"
        console.print(f"✓ File retrieved: {tracked['chunk_count']} chunks")
        
        # Test untracking
        entity_ids = tracker.untrack_file(str(test_file), "test_collection")
        assert entity_ids == [1, 2, 3, 4, 5], "Entity IDs should match"
        console.print(f"✓ File untracked: {len(entity_ids)} entities")
        
        # Verify untracked
        tracked = tracker.get_tracked_file(str(test_file), "test_collection")
        assert tracked is None, "File should not be tracked"
        console.print("✓ File no longer tracked")
    
    console.print("[bold green]✓ FileTracker tests passed![/bold green]")


def test_change_detection():
    """Test change detection."""
    console.print("\n[bold cyan]Testing Change Detection...[/bold cyan]")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup
        db_path = Path(tmpdir) / "test.db"
        source_dir = Path(tmpdir) / "source"
        source_dir.mkdir()
        
        tracker = FileTracker(db_path)
        
        # Create initial files
        file1 = source_dir / "file1.py"
        file2 = source_dir / "file2.py"
        file1.write_text("print('file1')")
        file2.write_text("print('file2')")
        
        # Track initial files
        for f in [file1, file2]:
            tracker.track_file(
                f,
                "test_collection",
                tracker.compute_file_hash(f),
                1,
                []
            )
        
        console.print(f"✓ Tracked 2 initial files")
        
        # Simulate changes
        # 1. Modify file1
        import time
        time.sleep(0.1)  # Ensure mtime changes
        file1.write_text("print('file1 modified')")
        
        # 2. Add file3
        file3 = source_dir / "file3.py"
        file3.write_text("print('file3')")
        
        # 3. Delete file2
        file2.unlink()
        
        # Create indexer and detect changes
        indexer = IncrementalIndexer(
            collection_name="test_collection",
            source_paths=[source_dir],
            file_patterns=["*.py"]
        )
        indexer.tracker = tracker  # Use our test tracker
        
        changeset = indexer.detect_changes()
        
        # Verify changes
        table = Table(title="Detected Changes")
        table.add_column("Type", style="cyan")
        table.add_column("Count", style="magenta")
        table.add_column("Files", style="green")
        
        table.add_row("New", str(len(changeset.new_files)), str([f.name for f in changeset.new_files]))
        table.add_row("Modified", str(len(changeset.modified_files)), str([f.name for f in changeset.modified_files]))
        table.add_row("Deleted", str(len(changeset.deleted_files)), str([f.name for f in changeset.deleted_files]))
        table.add_row("Unchanged", str(len(changeset.unchanged_files)), str([f.name for f in changeset.unchanged_files]))
        
        console.print(table)
        
        assert len(changeset.new_files) == 1, f"Should detect 1 new file, got {len(changeset.new_files)}"
        assert len(changeset.modified_files) == 1, f"Should detect 1 modified file, got {len(changeset.modified_files)}"
        assert len(changeset.deleted_files) == 1, f"Should detect 1 deleted file, got {len(changeset.deleted_files)}"
        
        console.print("[bold green]✓ Change detection tests passed![/bold green]")


def test_dry_run():
    """Test dry run mode."""
    console.print("\n[bold cyan]Testing Dry Run Mode...[/bold cyan]")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        source_dir = Path(tmpdir) / "source"
        source_dir.mkdir()
        
        # Create test file
        test_file = source_dir / "test.py"
        test_file.write_text("print('test')")
        
        # Create indexer
        indexer = IncrementalIndexer(
            collection_name="test_collection",
            source_paths=[source_dir],
            file_patterns=["*.py"]
        )
        indexer.tracker = FileTracker(db_path)
        
        # Detect changes
        changeset = indexer.detect_changes()
        console.print(f"✓ Detected {changeset.total_changes} changes")
        
        # Apply dry run
        result = indexer.apply_updates(changeset, dry_run=True)
        
        assert result.success, "Dry run should succeed"
        assert result.chunks_added == 0, "Dry run should not add chunks"
        assert result.files_added == 1, "Should report 1 file to add"
        
        console.print(f"✓ Dry run completed: {result.files_added} files would be added")
        console.print("[bold green]✓ Dry run tests passed![/bold green]")


def main():
    """Run all tests."""
    console.print(Panel.fit(
        "[bold cyan]Incremental Indexing Test Suite[/bold cyan]\n"
        "Testing file tracking, change detection, and updates",
        border_style="cyan"
    ))
    
    try:
        test_file_tracker()
        test_change_detection()
        test_dry_run()
        
        console.print("\n" + "="*60)
        console.print("[bold green]✓ All tests passed![/bold green]")
        console.print("="*60)
        
        return 0
    
    except AssertionError as e:
        console.print(f"\n[bold red]✗ Test failed: {e}[/bold red]")
        return 1
    except Exception as e:
        console.print(f"\n[bold red]✗ Error: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())