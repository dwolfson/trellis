#!/usr/bin/env python3
"""
Test script for query processor improvements.

Tests:
1. Confidence scoring for query type detection
2. Path extraction from queries
3. Context-aware detection with indicators
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.query_processor import QueryProcessor, QueryType


def test_confidence_scoring():
    """Test confidence scoring for query type detection."""
    print("\n" + "="*80)
    print("TESTING CONFIDENCE SCORING")
    print("="*80)
    
    processor = QueryProcessor()
    
    test_cases = [
        # High confidence cases
        ("How many classes are in the project?", QueryType.QUANTITATIVE, 0.85),
        ("What does GlossaryManager import?", QueryType.RELATIONSHIP, 0.85),
        ("Why isn't this working?", QueryType.DEBUGGING, 0.85),
        
        # Medium confidence cases
        ("Show me examples", QueryType.EXAMPLE, 0.65),
        ("What is a collection?", QueryType.EXPLANATION, 0.65),
        
        # Ambiguous cases (should have lower confidence)
        ("Tell me about Egeria", QueryType.GENERAL, 0.50),
    ]
    
    passed = 0
    failed = 0
    
    for query, expected_type, min_confidence in test_cases:
        detected_type, confidence = processor.detect_query_type_with_confidence(query)
        
        type_match = detected_type == expected_type
        confidence_ok = confidence >= min_confidence
        
        status = "✓" if (type_match and confidence_ok) else "✗"
        
        print(f"\n{status} Query: '{query}'")
        print(f"  Expected: {expected_type.value} (confidence >= {min_confidence})")
        print(f"  Got:      {detected_type.value} (confidence = {confidence:.2f})")
        
        if type_match and confidence_ok:
            passed += 1
        else:
            failed += 1
            if not type_match:
                print(f"  ERROR: Type mismatch!")
            if not confidence_ok:
                print(f"  ERROR: Confidence too low!")
    
    print(f"\n{'='*80}")
    print(f"Confidence Scoring Results: {passed} passed, {failed} failed")
    print(f"Pass rate: {passed}/{passed+failed} ({100*passed/(passed+failed):.1f}%)")
    
    return passed, failed


def test_path_extraction():
    """Test path extraction from queries."""
    print("\n" + "="*80)
    print("TESTING PATH EXTRACTION")
    print("="*80)
    
    processor = QueryProcessor()
    
    test_cases = [
        # Pattern 1: "in [the] X folder/directory"
        ("How many classes in the pyegeria folder?", "pyegeria"),
        ("Count files in the src directory", "src"),
        ("What's in the tests package?", "tests"),
        
        # Pattern 2: "under X" or "within X"
        ("Show classes under src/utils", "src/utils"),
        ("Files within the admin module", "admin"),
        
        # Pattern 3: "from X" (path-like)
        ("Import statements from pyegeria/admin", "pyegeria/admin"),
        ("Classes from src", "src"),
        
        # Pattern 4: Direct path reference
        ("Analyze pyegeria/glossary.py", "pyegeria/glossary.py"),
        
        # No path cases
        ("How many classes are there?", None),
        ("What is a glossary?", None),
    ]
    
    passed = 0
    failed = 0
    
    for query, expected_path in test_cases:
        extracted_path = processor.extract_path(query)
        
        match = extracted_path == expected_path
        status = "✓" if match else "✗"
        
        print(f"\n{status} Query: '{query}'")
        print(f"  Expected: {expected_path}")
        print(f"  Got:      {extracted_path}")
        
        if match:
            passed += 1
        else:
            failed += 1
    
    print(f"\n{'='*80}")
    print(f"Path Extraction Results: {passed} passed, {failed} failed")
    print(f"Pass rate: {passed}/{passed+failed} ({100*passed/(passed+failed):.1f}%)")
    
    return passed, failed


def test_context_aware_detection():
    """Test context-aware query type detection."""
    print("\n" + "="*80)
    print("TESTING CONTEXT-AWARE DETECTION")
    print("="*80)
    
    processor = QueryProcessor()
    
    test_cases = [
        # Quantitative indicators should override EXPLANATION
        ("What is the average complexity?", QueryType.QUANTITATIVE),
        ("How many files are there?", QueryType.QUANTITATIVE),
        ("What's the total SLOC?", QueryType.QUANTITATIVE),
        
        # Relationship indicators should override EXPLANATION
        ("What does this import?", QueryType.RELATIONSHIP),
        ("Show me what calls this function", QueryType.RELATIONSHIP),
        ("What inherits from BaseClass?", QueryType.RELATIONSHIP),
        
        # Debugging indicators should override EXPLANATION
        ("Why isn't this working?", QueryType.DEBUGGING),
        ("I'm getting an error", QueryType.DEBUGGING),
        ("This is broken", QueryType.DEBUGGING),
    ]
    
    passed = 0
    failed = 0
    
    for query, expected_type in test_cases:
        detected_type, confidence = processor.detect_query_type_with_confidence(query)
        
        match = detected_type == expected_type
        status = "✓" if match else "✗"
        
        print(f"\n{status} Query: '{query}'")
        print(f"  Expected: {expected_type.value}")
        print(f"  Got:      {detected_type.value} (confidence = {confidence:.2f})")
        
        if match:
            passed += 1
        else:
            failed += 1
    
    print(f"\n{'='*80}")
    print(f"Context-Aware Detection Results: {passed} passed, {failed} failed")
    print(f"Pass rate: {passed}/{passed+failed} ({100*passed/(passed+failed):.1f}%)")
    
    return passed, failed


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("QUERY PROCESSOR IMPROVEMENTS TEST SUITE")
    print("="*80)
    
    # Run all test suites
    conf_pass, conf_fail = test_confidence_scoring()
    path_pass, path_fail = test_path_extraction()
    ctx_pass, ctx_fail = test_context_aware_detection()
    
    # Overall results
    total_pass = conf_pass + path_pass + ctx_pass
    total_fail = conf_fail + path_fail + ctx_fail
    total_tests = total_pass + total_fail
    
    print("\n" + "="*80)
    print("OVERALL RESULTS")
    print("="*80)
    print(f"Total tests: {total_tests}")
    print(f"Passed: {total_pass}")
    print(f"Failed: {total_fail}")
    print(f"Pass rate: {100*total_pass/total_tests:.1f}%")
    print("="*80)
    
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())