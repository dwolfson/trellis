#!/usr/bin/env python3
"""
Enable the three new specialized collections and disable the old egeria_docs collection.

This script modifies advisor/collection_config.py to:
1. Enable egeria_concepts (line 248)
2. Enable egeria_types (line 272)  
3. Enable egeria_general (line 300)
4. Disable egeria_docs (line 199)

Run this ONCE after all three collections are successfully ingested.
"""

import sys
from pathlib import Path

def enable_collections():
    """Enable new collections and disable old egeria_docs."""
    
    config_path = Path("advisor/collection_config.py")
    
    if not config_path.exists():
        print(f"❌ Error: {config_path} not found")
        sys.exit(1)
    
    # Read the file
    content = config_path.read_text()
    
    # Track changes
    changes = []
    
    # 1. Enable egeria_concepts (around line 248)
    if 'name="egeria_concepts"' in content:
        old_line = '    enabled=False,  # Will be enabled after ingestion'
        new_line = '    enabled=True,  # ENABLED - Phase 2b'
        if old_line in content:
            content = content.replace(old_line, new_line, 1)
            changes.append("✓ Enabled egeria_concepts")
        else:
            print("⚠️  Warning: egeria_concepts already enabled or pattern not found")
    
    # 2. Enable egeria_types (around line 272)
    # Need to be more specific since there are multiple enabled=False
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'name="egeria_types"' in line:
            # Find the enabled line within next 20 lines
            for j in range(i, min(i+20, len(lines))):
                if 'enabled=False,  # Will be enabled after ingestion' in lines[j]:
                    lines[j] = '    enabled=True,  # ENABLED - Phase 2b'
                    changes.append("✓ Enabled egeria_types")
                    break
            break
    content = '\n'.join(lines)
    
    # 3. Enable egeria_general (around line 300)
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'name="egeria_general"' in line:
            # Find the enabled line within next 20 lines
            for j in range(i, min(i+20, len(lines))):
                if 'enabled=False,  # Will be enabled after ingestion' in lines[j]:
                    lines[j] = '    enabled=True,  # ENABLED - Phase 2b'
                    changes.append("✓ Enabled egeria_general")
                    break
            break
    content = '\n'.join(lines)
    
    # 4. Disable egeria_docs (around line 199)
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'name="egeria_docs"' in line:
            # Find the enabled line within next 20 lines
            for j in range(i, min(i+20, len(lines))):
                if 'enabled=True,' in lines[j] and 'Phase 2' in lines[j]:
                    lines[j] = '    enabled=False,  # DISABLED - Replaced by specialized collections'
                    changes.append("✓ Disabled egeria_docs (replaced by specialized collections)")
                    break
            break
    content = '\n'.join(lines)
    
    # Write back
    config_path.write_text(content)
    
    # Report
    print("\n" + "="*70)
    print("Collection Configuration Updated")
    print("="*70)
    for change in changes:
        print(change)
    
    if len(changes) == 4:
        print("\n✅ All collections updated successfully!")
        print("\nNext steps:")
        print("1. Verify collections are working:")
        print("   python scripts/validate_phase3_improvements.py")
        print("\n2. Test queries against new collections:")
        print("   python -m advisor.cli.main")
    else:
        print(f"\n⚠️  Warning: Expected 4 changes, got {len(changes)}")
        print("Please review advisor/collection_config.py manually")

if __name__ == "__main__":
    print("Enabling specialized collections...")
    enable_collections()