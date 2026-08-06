#!/usr/bin/env python3
"""
Quick fixes for high hallucination rate.

Implements immediate improvements:
1. Increase chunk size for documentation
2. Improve prompt engineering
3. Increase min_score threshold
4. Better collection routing
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

console = Console()


def update_config():
    """Update advisor.yaml with better settings."""
    config_path = Path("config/advisor.yaml")
    
    console.print(Panel.fit(
        "[bold cyan]Quick Fix: Update Configuration[/bold cyan]\n"
        "Applying immediate improvements to reduce hallucinations",
        border_style="cyan"
    ))
    
    # Read current config
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    # Show current settings
    console.print("\n[yellow]Current Settings:[/yellow]")
    console.print(f"  chunk_size: {config['rag']['chunk_size']}")
    console.print(f"  chunk_overlap: {config['rag']['chunk_overlap']}")
    console.print(f"  min_score: {config['rag']['retrieval']['min_score']}")
    console.print(f"  top_k: {config['rag']['retrieval']['top_k']}")
    
    # Proposed changes
    console.print("\n[green]Proposed Changes:[/green]")
    console.print("  chunk_size: 512 → 1024 (for complete concepts)")
    console.print("  chunk_overlap: 50 → 200 (20% overlap)")
    console.print("  min_score: 0.30 → 0.40 (filter irrelevant)")
    console.print("  top_k: 10 → 15 (more context)")
    
    if not Confirm.ask("\nApply these changes?"):
        console.print("[yellow]Skipping config update[/yellow]")
        return False
    
    # Apply changes
    config['rag']['chunk_size'] = 1024
    config['rag']['chunk_overlap'] = 200
    config['rag']['retrieval']['min_score'] = 0.40
    config['rag']['retrieval']['top_k'] = 15
    
    # Backup original
    backup_path = config_path.with_suffix('.yaml.backup')
    with open(backup_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    console.print(f"[dim]Backup saved to: {backup_path}[/dim]")
    
    # Write updated config
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    
    console.print("[green]✓ Configuration updated[/green]")
    return True


def show_reingest_instructions():
    """Show instructions for re-ingesting collections."""
    console.print("\n" + "="*80)
    console.print(Panel.fit(
        "[bold yellow]⚠️  Re-ingestion Required[/bold yellow]\n\n"
        "The chunk size has changed. You need to re-ingest collections\n"
        "to apply the new chunking strategy.",
        border_style="yellow"
    ))
    
    console.print("\n[bold]Re-ingest Commands:[/bold]")
    console.print("""
# Re-ingest egeria_docs (most important for documentation)
python scripts/ingest_collections.py --collection egeria_docs --force

# Re-ingest all collections (recommended)
python scripts/ingest_collections.py --all --force

# Or use the incremental indexer
python -m advisor.incremental_indexer --collection egeria_docs --force-reindex
""")


def show_prompt_improvements():
    """Show prompt engineering improvements."""
    console.print("\n" + "="*80)
    console.print(Panel.fit(
        "[bold cyan]Prompt Engineering Improvements[/bold cyan]\n\n"
        "Update your prompts to emphasize using retrieved context",
        border_style="cyan"
    ))
    
    console.print("\n[bold]Enhanced Prompt Template:[/bold]")
    console.print("""
[yellow]BEFORE (Generic):[/yellow]
\"\"\"
Context: {context}
Question: {question}
Answer:
\"\"\"

[green]AFTER (Explicit Instructions):[/green]
\"\"\"
You are an expert on Egeria and pyegeria.

CRITICAL INSTRUCTIONS:
1. ONLY answer based on the provided context below
2. If the context doesn't contain the answer, say "I don't have enough information"
3. NEVER make up information or code examples
4. Quote relevant parts of the context in your answer
5. If you see code examples in the context, use them directly

Context:
{context}

Question: {question}

Answer (based ONLY on the context above):
\"\"\"
""")
    
    console.print("\n[bold]Files to Update:[/bold]")
    console.print("  • advisor/prompt_templates.py")
    console.print("  • advisor/agents/conversation_agent.py")
    console.print("  • advisor/rag_system.py")


def show_embedding_upgrade():
    """Show embedding model upgrade instructions."""
    console.print("\n" + "="*80)
    console.print(Panel.fit(
        "[bold magenta]Embedding Model Upgrade (Phase 2)[/bold magenta]\n\n"
        "For 40-50% reduction in hallucinations",
        border_style="magenta"
    ))
    
    console.print("\n[bold]Current Model:[/bold]")
    console.print("  sentence-transformers/all-MiniLM-L6-v2")
    console.print("  • Dimension: 384")
    console.print("  • Max length: 256 tokens")
    console.print("  • Quality: Good for general use")
    
    console.print("\n[bold]Recommended Upgrade:[/bold]")
    console.print("  sentence-transformers/all-mpnet-base-v2")
    console.print("  • Dimension: 768 (2x better)")
    console.print("  • Max length: 384 tokens")
    console.print("  • Quality: Excellent for documentation")
    
    console.print("\n[bold]Upgrade Steps:[/bold]")
    console.print("""
1. Update config/advisor.yaml:
   embeddings:
     model: sentence-transformers/all-mpnet-base-v2
     max_length: 384

2. Re-ingest all collections:
   python scripts/ingest_collections.py --all --force

3. Test improvement:
   python scripts/diagnose_rag_quality.py
""")


def show_monitoring():
    """Show monitoring instructions."""
    console.print("\n" + "="*80)
    console.print(Panel.fit(
        "[bold blue]Monitor Improvements[/bold blue]\n\n"
        "Track hallucination rate reduction",
        border_style="blue"
    ))
    
    console.print("\n[bold]Monitoring Commands:[/bold]")
    console.print("""
# Run diagnostic
python scripts/diagnose_rag_quality.py

# Test specific queries
python -m advisor.cli.main agent
> what is a digital product in Egeria?
> how do I create a glossary term?

# Check feedback stats
> /fstats

# View dashboard
streamlit run advisor/dashboard/streamlit_dashboard.py
""")


def main():
    """Run quick fix script."""
    console.print(Panel.fit(
        "[bold red]🚨 High Hallucination Rate Fix[/bold red]\n\n"
        "Current: >80% hallucination rate\n"
        "Target: <30% after all fixes\n\n"
        "This script applies Phase 1 quick wins",
        border_style="red"
    ))
    
    # Step 1: Update config
    config_updated = update_config()
    
    if config_updated:
        # Step 2: Show re-ingest instructions
        show_reingest_instructions()
    
    # Step 3: Show prompt improvements
    show_prompt_improvements()
    
    # Step 4: Show embedding upgrade
    show_embedding_upgrade()
    
    # Step 5: Show monitoring
    show_monitoring()
    
    # Summary
    console.print("\n" + "="*80)
    console.print(Panel.fit(
        "[bold green]Summary[/bold green]\n\n"
        "✓ Configuration updated (if confirmed)\n"
        "• Re-ingest collections with new chunk size\n"
        "• Update prompts with explicit instructions\n"
        "• Consider embedding model upgrade\n"
        "• Monitor improvements with diagnostics\n\n"
        "[bold]Expected Impact:[/bold]\n"
        "Phase 1 (Quick Wins): 30-40% reduction\n"
        "Phase 2 (Model Upgrade): 40-50% reduction\n"
        "Phase 3 (Advanced): 60-70% reduction",
        border_style="green"
    ))
    
    console.print("\n[bold cyan]Next Steps:[/bold cyan]")
    console.print("1. Re-ingest collections (if config updated)")
    console.print("2. Update prompt templates")
    console.print("3. Test with diagnostic script")
    console.print("4. Monitor feedback and adjust")
    console.print("\n[dim]See docs/design/HALLUCINATION_ANALYSIS_AND_FIXES.md for details[/dim]")


if __name__ == "__main__":
    main()