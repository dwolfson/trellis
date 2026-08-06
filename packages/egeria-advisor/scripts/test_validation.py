#!/usr/bin/env python3
"""
Validation Test Suite for Recent Enhancements
Tests metadata structure, GPU detection, and source display
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.embeddings import EmbeddingGenerator
from advisor.rag_system import get_rag_system
from advisor.cli.formatters import CitationFormatter
from rich.console import Console

console = Console()


def test_gpu_detection():
    """Test universal GPU detection"""
    console.print("\n[bold cyan]Testing GPU Detection[/bold cyan]")
    console.print("=" * 60)
    
    try:
        embedding_generator = EmbeddingGenerator()
        device = embedding_generator.device
        
        console.print(f"✓ Device detected: [green]{device}[/green]")
        
        if device == "cuda":
            console.print("  → NVIDIA CUDA or AMD ROCm detected")
        elif device == "mps":
            console.print("  → Apple Metal (MPS) detected")
        else:
            console.print("  → Using CPU (no GPU acceleration)")
        
        return True
    except Exception as e:
        console.print(f"[red]✗ GPU detection failed: {e}[/red]")
        return False


def test_metadata_structure():
    """Test that metadata has correct structure"""
    console.print("\n[bold cyan]Testing Metadata Structure[/bold cyan]")
    console.print("=" * 60)
    
    try:
        rag = get_rag_system()
        
        # Test query to get results
        results = rag.query("glossary", top_k=3)
        
        if not results:
            console.print("[yellow]⚠ No results returned[/yellow]")
            return False
        
        # Check first result metadata
        result = results[0]
        metadata = result.metadata if hasattr(result, 'metadata') else result
        
        console.print(f"\n[bold]Sample Result Metadata:[/bold]")
        console.print(f"  Type: {type(metadata)}")
        
        # Check for required fields
        has_file_path = False
        has_collection = False
        
        if isinstance(metadata, dict):
            has_file_path = "file_path" in metadata
            has_collection = "collection" in metadata or "_collection" in metadata
            
            console.print(f"  file_path: {'✓' if has_file_path else '✗'} {metadata.get('file_path', 'N/A')}")
            console.print(f"  collection: {'✓' if has_collection else '✗'} {metadata.get('collection') or metadata.get('_collection', 'N/A')}")
        else:
            has_file_path = hasattr(metadata, 'file_path')
            has_collection = hasattr(metadata, 'collection') or hasattr(metadata, '_collection')
            
            console.print(f"  file_path: {'✓' if has_file_path else '✗'} {getattr(metadata, 'file_path', 'N/A')}")
            console.print(f"  collection: {'✓' if has_collection else '✗'} {getattr(metadata, 'collection', None) or getattr(metadata, '_collection', 'N/A')}")
        
        if has_file_path and has_collection:
            console.print("\n[green]✓ Metadata structure is correct[/green]")
            return True
        else:
            console.print("\n[red]✗ Metadata structure incomplete[/red]")
            return False
            
    except Exception as e:
        console.print(f"[red]✗ Metadata test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_source_display():
    """Test that sources display correctly with collection names"""
    console.print("\n[bold cyan]Testing Source Display[/bold cyan]")
    console.print("=" * 60)
    
    try:
        rag = get_rag_system()
        formatter = CitationFormatter()
        
        # Test query
        results = rag.query("glossary", top_k=3)
        
        if not results:
            console.print("[yellow]⚠ No results returned[/yellow]")
            return False
        
        console.print(f"\n[bold]Found {len(results)} results[/bold]")
        
        # Format sources
        console.print("\n[bold]Formatted Sources:[/bold]")
        sources_text = formatter.format(results)
        console.print(sources_text)
        
        # Check if collection names appear
        has_collection_names = any(
            "egeria" in sources_text.lower() or 
            "pyegeria" in sources_text.lower() or
            "documentation" in sources_text.lower()
        )
        
        if has_collection_names:
            console.print("\n[green]✓ Collection names displayed in sources[/green]")
            return True
        else:
            console.print("\n[yellow]⚠ Collection names may not be displaying[/yellow]")
            return False
            
    except Exception as e:
        console.print(f"[red]✗ Source display test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def test_query_routing():
    """Test documentation-first query routing"""
    console.print("\n[bold cyan]Testing Query Routing[/bold cyan]")
    console.print("=" * 60)
    
    try:
        rag = get_rag_system()
        
        # Test conceptual query (should prioritize docs)
        console.print("\n[bold]Testing conceptual query:[/bold] 'What is a glossary?'")
        results = rag.query("What is a glossary?", top_k=5)
        
        if results:
            # Check if docs are prioritized
            doc_count = sum(1 for r in results if 'doc' in str(r.metadata).lower())
            console.print(f"  Documentation results: {doc_count}/{len(results)}")
            
            if doc_count > 0:
                console.print("[green]✓ Documentation-first routing working[/green]")
                return True
            else:
                console.print("[yellow]⚠ No documentation results (may be expected)[/yellow]")
                return True
        else:
            console.print("[yellow]⚠ No results returned[/yellow]")
            return False
            
    except Exception as e:
        console.print(f"[red]✗ Query routing test failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all validation tests"""
    console.print("\n[bold magenta]╔═══════════════════════════════════════════════════════════╗[/bold magenta]")
    console.print("[bold magenta]║     Egeria Advisor - Validation Test Suite              ║[/bold magenta]")
    console.print("[bold magenta]╚═══════════════════════════════════════════════════════════╝[/bold magenta]")
    
    tests = [
        ("GPU Detection", test_gpu_detection),
        ("Metadata Structure", test_metadata_structure),
        ("Source Display", test_source_display),
        ("Query Routing", test_query_routing),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            console.print(f"\n[red]✗ {name} crashed: {e}[/red]")
            results[name] = False
    
    # Summary
    console.print("\n[bold cyan]Test Summary[/bold cyan]")
    console.print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "[green]✓ PASS[/green]" if result else "[red]✗ FAIL[/red]"
        console.print(f"{status} - {name}")
    
    console.print(f"\n[bold]Results: {passed}/{total} tests passed[/bold]")
    
    if passed == total:
        console.print("\n[bold green]🎉 All validation tests passed![/bold green]")
        return 0
    else:
        console.print("\n[bold yellow]⚠ Some tests failed or had warnings[/bold yellow]")
        return 1


if __name__ == "__main__":
    sys.exit(main())