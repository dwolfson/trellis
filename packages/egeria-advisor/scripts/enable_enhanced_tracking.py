#!/usr/bin/env python3
"""
Quick script to enable enhanced MLflow tracking in production.

This script modifies the RAG system to enable resource monitoring
and accuracy tracking so metrics appear in the MLflow dashboard.

Usage:
    python scripts/enable_enhanced_tracking.py
"""

import sys
from pathlib import Path

def enable_tracking():
    """Enable enhanced tracking in rag_system.py"""
    
    # Path to rag_system.py
    rag_system_path = Path(__file__).parent.parent / "advisor" / "rag_system.py"
    
    if not rag_system_path.exists():
        print(f"❌ Error: {rag_system_path} not found")
        return False
    
    # Read current content
    with open(rag_system_path, 'r') as f:
        content = f.read()
    
    # Check if already enabled
    if "enable_resource_monitoring=True" in content:
        print("✅ Enhanced tracking already enabled!")
        return True
    
    # Find the line to modify
    old_line = "        self.mlflow_tracker = get_mlflow_tracker()"
    new_lines = """        self.mlflow_tracker = get_mlflow_tracker(
            enable_resource_monitoring=True,
            enable_accuracy_tracking=True
        )"""
    
    if old_line not in content:
        print("❌ Error: Could not find line to modify")
        print("Expected:", old_line)
        return False
    
    # Replace the line
    new_content = content.replace(old_line, new_lines)
    
    # Backup original
    backup_path = rag_system_path.with_suffix('.py.backup')
    with open(backup_path, 'w') as f:
        f.write(content)
    print(f"📦 Backup created: {backup_path}")
    
    # Write modified content
    with open(rag_system_path, 'w') as f:
        f.write(new_content)
    
    print("✅ Enhanced tracking enabled!")
    print("\nChanges made:")
    print("  - Resource monitoring: ENABLED")
    print("  - Accuracy tracking: ENABLED")
    print("\nMetrics now tracked:")
    print("  - CPU usage (cpu_percent)")
    print("  - Memory usage (memory_mb, memory_delta_mb)")
    print("  - Query duration (duration_seconds)")
    print("  - Relevance scores (avg_relevance)")
    print("  - Confidence scores (avg_confidence)")
    print("  - User feedback (avg_feedback)")
    print("\nView metrics at: http://localhost:5025")
    
    return True


def verify_mlflow_running():
    """Check if MLflow server is running"""
    import subprocess
    
    try:
        result = subprocess.run(
            ["pgrep", "-f", "mlflow"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ MLflow server is running")
            return True
        else:
            print("⚠️  MLflow server not detected")
            print("Start it with: mlflow server --host 0.0.0.0 --port 5025")
            return False
    except Exception as e:
        print(f"⚠️  Could not check MLflow status: {e}")
        return False


def main():
    """Main function"""
    print("=" * 60)
    print("Enhanced MLflow Tracking Enabler")
    print("=" * 60)
    print()
    
    # Enable tracking
    if not enable_tracking():
        sys.exit(1)
    
    print()
    print("=" * 60)
    print("Verification")
    print("=" * 60)
    print()
    
    # Verify MLflow
    verify_mlflow_running()
    
    print()
    print("=" * 60)
    print("Next Steps")
    print("=" * 60)
    print()
    print("1. Restart your application if it's running")
    print("2. Run a test query:")
    print("   egeria-advisor query 'How many classes?'")
    print("3. Check MLflow UI at http://localhost:5025")
    print("4. Look for new metrics in the latest run")
    print()
    print("To revert changes:")
    print("   cp advisor/rag_system.py.backup advisor/rag_system.py")
    print()


if __name__ == "__main__":
    main()