#!/bin/bash
# Script to set up egeria-advisor as an independent Git repository

set -e  # Exit on error

PROJECT_DIR="/home/dwolfson/localGit/egeria-v6/egeria-advisor"

echo "=========================================="
echo "Setting up Independent Git Repository"
echo "=========================================="

cd "$PROJECT_DIR"

# Check if already a git repo
if [ -d ".git" ]; then
    echo "⚠️  .git directory already exists!"
    echo ""
    read -p "Do you want to remove it and start fresh? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Removing existing .git directory..."
        rm -rf .git
        echo "✓ Removed"
    else
        echo "Keeping existing .git directory"
        exit 0
    fi
fi

# Initialize new git repository
echo ""
echo "Initializing new Git repository..."
git init
echo "✓ Git repository initialized"

# Set default branch to main
echo ""
echo "Setting default branch to 'main'..."
git branch -M main
echo "✓ Default branch set to 'main'"

# Add all files
echo ""
echo "Adding files to Git..."
git add .
echo "✓ Files staged"

# Show what will be committed
echo ""
echo "Files to be committed:"
git status --short | head -20
TOTAL_FILES=$(git status --short | wc -l)
if [ $TOTAL_FILES -gt 20 ]; then
    echo "... and $((TOTAL_FILES - 20)) more files"
fi

# Create initial commit
echo ""
echo "Creating initial commit..."
git commit -m "Initial commit: Egeria Advisor Phase 1 & 2 complete

- Project architecture and design
- Data preparation pipeline implementation
- Configuration management
- Documentation and guides
- AMD optimization support
- Testing infrastructure"
echo "✓ Initial commit created"

# Show commit
echo ""
echo "Commit details:"
git log --oneline -1
echo ""
git show --stat HEAD

echo ""
echo "=========================================="
echo "✓ Git Repository Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps to push to GitHub:"
echo ""
echo "1. Create a new repository on GitHub:"
echo "   - Go to https://github.com/new"
echo "   - Repository name: egeria-advisor"
echo "   - Description: AI-powered advisor for Egeria Python development"
echo "   - Choose Public or Private"
echo "   - DO NOT initialize with README, .gitignore, or license"
echo "   - Click 'Create repository'"
echo ""
echo "2. Add GitHub remote and push:"
echo "   cd $PROJECT_DIR"
echo "   git remote add origin https://github.com/YOUR_USERNAME/egeria-advisor.git"
echo "   git push -u origin main"
echo ""
echo "Or use SSH:"
echo "   git remote add origin git@github.com:YOUR_USERNAME/egeria-advisor.git"
echo "   git push -u origin main"
echo ""
echo "3. Verify on GitHub:"
echo "   https://github.com/YOUR_USERNAME/egeria-advisor"
echo ""