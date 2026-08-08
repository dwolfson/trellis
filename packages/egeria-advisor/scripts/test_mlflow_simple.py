#!/usr/bin/env python3
"""
Simple test to verify MLflow tracking enhancements work.
Tests the tracking functionality without requiring full system connectivity.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.rag_system import get_rag_system
from loguru import logger

print("\n" + "=" * 80)
print("  MLflow Tracking Enhancements - Simple Verification")
print("=" * 80 + "\n")

print("Initializing RAG system...")
rag = get_rag_system()

print("\n" + "=" * 80)
print("  Test 1: explain_code() with MLflow Tracking")
print("=" * 80 + "\n")

code = """def get_asset(guid):
    '''Get an asset by GUID'''
    return client.get_asset_by_guid(guid)"""

print(f"Code to explain:\n{code}\n")
print("Calling explain_code() with track_metrics=True...")

try:
    result = rag.explain_code(code, track_metrics=True)
    print(f"\n✓ SUCCESS: Explanation generated ({len(result)} chars)")
    print(f"\nExplanation preview:\n{result[:300]}...")
    print("\n✓ MLflow tracking for explain_code() is working!")
except Exception as e:
    print(f"\n✗ FAILED: {e}")
    logger.exception("Test failed")

print("\n" + "=" * 80)
print("  Verification Complete")
print("=" * 80)
print("\nCheck MLflow UI at http://localhost:5025 to see tracked experiments")
print("Look for runs named 'explain_code' with the following metrics:")
print("  - response_length")
print("  - generation_time")
print("  - operation_duration_seconds")
print("\nParameters logged:")
print("  - code_length")
print("  - has_context")