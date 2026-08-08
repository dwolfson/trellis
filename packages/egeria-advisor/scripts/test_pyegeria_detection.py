#!/usr/bin/env python3
"""
Test PyEgeria agent detection with fresh module import.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Force clean import - remove any cached modules
modules_to_clear = [
    'advisor.agents.pyegeria_agent',
    'advisor.agents.conversation_agent',
]

for mod in modules_to_clear:
    if mod in sys.modules:
        del sys.modules[mod]
        print(f"✓ Cleared {mod} from cache")

# Now import fresh
from advisor.agents.pyegeria_agent import PyEgeriaAgent, get_pyegeria_agent, reset_pyegeria_agent

print("\n" + "="*60)
print("Testing PyEgeria Agent Detection")
print("="*60)

# Reset singleton to ensure fresh instance
reset_pyegeria_agent()
agent = get_pyegeria_agent()

# Test query
test_query = "list all the methods in ProjectManager"
print(f"\nTest Query: '{test_query}'")
print("-" * 60)

# Test detection
is_pyegeria = agent.is_pyegeria_query(test_query)
print(f"\n✓ is_pyegeria_query() returned: {is_pyegeria}")

if is_pyegeria:
    print("\n✓ SUCCESS: Query detected as PyEgeria query")
    
    # Test exhaustive detection
    is_exhaustive = agent.is_exhaustive_query(test_query)
    print(f"✓ is_exhaustive_query() returned: {is_exhaustive}")
    
    if is_exhaustive:
        print("\n✓ SUCCESS: Query detected as exhaustive query")
        print("✓ Should return ALL methods, not just top-k")
    else:
        print("\n✗ FAIL: Query NOT detected as exhaustive")
else:
    print("\n✗ FAIL: Query NOT detected as PyEgeria query")
    print("✗ Will fall back to standard RAG (only top-k results)")

print("\n" + "="*60)