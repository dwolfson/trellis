#!/bin/bash
# Script to sync local repository with GitHub when GitHub was initialized with files

set -e  # Exit on error

PROJECT_DIR="/home/dwolfson/localGit/egeria-v6/egeria-advisor"

echo "=========================================="
echo "Syncing with GitHub Repository"
echo "=========================================="

cd "$PROJECT_DIR"

# Check if git is initialized
if [ ! -d ".git" ]; then
    echo "❌ Git repository not initialized!"
    echo "Run ./scripts/setup_git_repo.sh first"
    exit 1
fi

# Get GitHub organization/username and repo name
echo ""
echo "Enter GitHub organization or username (default: pdr-associates):"
read -r GITHUB_ORG
GITHUB_ORG=${GITHUB_ORG:-pdr-associates}

echo ""
echo "Enter repository name (default: egeria-advisor):"
read -r REPO_NAME
REPO_NAME=${REPO_NAME:-egeria-advisor}

# Ask for HTTPS or SSH
echo ""
echo "Use HTTPS or SSH? (https/ssh, default: https):"
read -r PROTOCOL
PROTOCOL=${PROTOCOL:-https}

# Set remote URL
if [ "$PROTOCOL" = "ssh" ]; then
    REMOTE_URL="git@github.com:${GITHUB_ORG}/${REPO_NAME}.git"
else
    REMOTE_URL="https://github.com/${GITHUB_ORG}/${REPO_NAME}.git"
fi

echo ""
echo "Remote URL: $REMOTE_URL"

# Check if remote already exists
if git remote | grep -q "^origin$"; then
    echo ""
    echo "Remote 'origin' already exists. Updating URL..."
    git remote set-url origin "$REMOTE_URL"
else
    echo ""
    echo "Adding remote 'origin'..."
    git remote add origin "$REMOTE_URL"
fi

echo "✓ Remote configured"

# Fetch from GitHub
echo ""
echo "Fetching from GitHub..."
git fetch origin

# Check if there are commits on GitHub
if git rev-parse origin/main >/dev/null 2>&1; then
    echo "✓ Found commits on GitHub"
    
    # Pull with rebase to integrate GitHub's files
    echo ""
    echo "Pulling GitHub files (LICENSE, .gitignore)..."
    echo "This will merge GitHub's initial commit with your local work..."
    
    # Allow unrelated histories since GitHub created initial commit
    git pull origin main --allow-unrelated-histories --no-edit
    
    echo "✓ GitHub files merged"
    
    # Check for conflicts
    if git diff --name-only --diff-filter=U | grep -q .; then
        echo ""
        echo "⚠️  Merge conflicts detected!"
        echo ""
        echo "Conflicting files:"
        git diff --name-only --diff-filter=U
        echo ""
        echo "To resolve:"
        echo "1. Edit the conflicting files"
        echo "2. Choose which version to keep (or merge them)"
        echo "3. Run: git add <file>"
        echo "4. Run: git commit"
        echo "5. Run: git push -u origin main"
        exit 1
    fi
else
    echo "✓ No commits on GitHub yet"
fi

# Push to GitHub
echo ""
echo "Pushing to GitHub..."
git push -u origin main

echo ""
echo "=========================================="
echo "✓ Successfully Synced with GitHub!"
echo "=========================================="
echo ""
echo "Your repository is now available at:"
echo "https://github.com/${GITHUB_ORG}/${REPO_NAME}"
echo ""
echo "To push future changes:"
echo "  git add ."
echo "  git commit -m 'Your commit message'"
echo "  git push"
echo ""