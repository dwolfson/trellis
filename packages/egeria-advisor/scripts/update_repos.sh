#!/bin/bash
# Update all Egeria repositories from GitHub
#
# This script pulls the latest changes from GitHub for all cloned repositories.
# Run this before doing incremental indexing to update the vector store.

# Don't exit on error - we want to try all repos
set +e

REPOS_DIR="data/repos"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=========================================="
echo "Updating Egeria Repositories"
echo "=========================================="
echo ""

# Check if repos directory exists
if [ ! -d "$REPOS_DIR" ]; then
    echo "❌ Repositories directory not found: $REPOS_DIR"
    echo ""
    echo "Run this first to clone repositories:"
    echo "  python scripts/clone_repos.py"
    exit 1
fi

# Repository list (using array instead of associative array for better compatibility)
REPOS=("egeria-python" "egeria" "egeria-docs" "egeria-workspaces")
BRANCH="main"

UPDATED=0
SKIPPED=0
FAILED=0

# Update each repository
for repo in "${REPOS[@]}"; do
    repo_path="$REPOS_DIR/$repo"
    
    if [ -d "$repo_path" ]; then
        echo "Updating $repo..."
        
        # Save current directory
        CURRENT_DIR=$(pwd)
        
        if cd "$repo_path" 2>/dev/null; then
            # Check if it's a git repository
            if [ ! -d ".git" ]; then
                echo "  ⚠ Not a git repository, skipping"
                ((SKIPPED++))
                cd "$CURRENT_DIR"
                echo ""
                continue
            fi
            
            # Fetch latest changes
            if git fetch origin "$BRANCH" 2>/dev/null; then
                # Check if there are updates
                LOCAL=$(git rev-parse HEAD 2>/dev/null)
                REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null)
                
                if [ "$LOCAL" = "$REMOTE" ]; then
                    echo "  ✓ Already up to date"
                    ((SKIPPED++))
                else
                    # Pull changes
                    if git pull origin "$BRANCH" 2>/dev/null; then
                        COMMITS=$(git log --oneline "$LOCAL..$REMOTE" 2>/dev/null | wc -l)
                        echo "  ✓ Updated ($COMMITS new commits)"
                        ((UPDATED++))
                    else
                        echo "  ❌ Failed to pull changes"
                        ((FAILED++))
                    fi
                fi
            else
                echo "  ❌ Failed to fetch from origin"
                ((FAILED++))
            fi
            
            cd "$CURRENT_DIR"
        else
            echo "  ❌ Failed to access directory"
            ((FAILED++))
        fi
    else
        echo "⚠ Repository not found: $repo_path"
        ((SKIPPED++))
    fi
    echo ""
done

# Summary
echo "=========================================="
echo "Update Summary"
echo "=========================================="
echo "Updated:  $UPDATED"
echo "Skipped:  $SKIPPED"
echo "Failed:   $FAILED"
echo ""

if [ $UPDATED -gt 0 ]; then
    echo "✓ Repositories updated successfully"
    echo ""
    echo "Next steps:"
    echo "  1. Run incremental indexing:"
    echo "     python scripts/ingest_collections.py --incremental --all"
    echo ""
    echo "  2. Or check what would be updated (dry run):"
    echo "     python scripts/ingest_collections.py --incremental --dry-run"
    echo ""
elif [ $FAILED -gt 0 ]; then
    echo "❌ Some repositories failed to update"
    exit 1
else
    echo "✓ All repositories are up to date"
    echo ""
    echo "No incremental indexing needed unless you want to force a re-index:"
    echo "  python scripts/ingest_collections.py --force --all"
    echo ""
fi