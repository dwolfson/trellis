"""
Enhanced analytics module using professional code metrics.

This module provides access to enhanced codebase metrics including:
- Professional code metrics (Radon, Pygount)
- Folder-level breakdowns
- Complexity and maintainability scores
- Halstead metrics
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from loguru import logger

from advisor.config import settings


class EnhancedAnalyticsManager:
    """Manages enhanced codebase analytics and metrics."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize enhanced analytics manager."""
        self.cache_dir = cache_dir or Path(settings.advisor_cache_dir)
        self.metrics: Optional[Dict[str, Any]] = None
        self._load_metrics()
    
    def _load_metrics(self):
        """Load enhanced metrics from cache."""
        metrics_file = self.cache_dir / "enhanced_metrics.json"
        
        if not metrics_file.exists():
            logger.warning(f"Enhanced metrics file not found: {metrics_file}")
            self.metrics = {}
            return
        
        try:
            with open(metrics_file, 'r') as f:
                self.metrics = json.load(f)
            logger.info(f"Loaded enhanced metrics from {metrics_file}")
        except Exception as e:
            logger.error(f"Failed to load enhanced metrics: {e}")
            self.metrics = {}
    
    # Overall metrics
    def get_total_files(self) -> int:
        """Get total number of files analyzed."""
        return self.metrics.get('files_analyzed', 0) if self.metrics else 0
    
    def get_total_lines(self) -> int:
        """Get total lines of code."""
        return self.metrics.get('total_loc', 0) if self.metrics else 0
    
    def get_total_sloc(self) -> int:
        """Get total source lines of code (excluding blank/comments)."""
        return self.metrics.get('total_sloc', 0) if self.metrics else 0
    
    def get_total_code_lines(self) -> int:
        """Get total code lines (Pygount count)."""
        return self.metrics.get('total_code', 0) if self.metrics else 0
    
    def get_total_comments(self) -> int:
        """Get total comment lines."""
        return self.metrics.get('total_comments', 0) if self.metrics else 0
    
    def get_total_blank_lines(self) -> int:
        """Get total blank lines."""
        return self.metrics.get('total_blank', 0) if self.metrics else 0
    
    def get_average_complexity(self) -> float:
        """Get average cyclomatic complexity."""
        return self.metrics.get('avg_complexity', 0.0) if self.metrics else 0.0
    
    def get_average_maintainability(self) -> float:
        """Get average maintainability index."""
        return self.metrics.get('avg_maintainability', 0.0) if self.metrics else 0.0
    
    def get_estimated_bugs(self) -> float:
        """Get estimated bugs from Halstead metrics."""
        return self.metrics.get('total_halstead_bugs', 0.0) if self.metrics else 0.0
    
    def get_complexity_distribution(self) -> Dict[str, int]:
        """Get complexity distribution."""
        return self.metrics.get('complexity_distribution', {}) if self.metrics else {}
    
    def get_maintainability_distribution(self) -> Dict[str, int]:
        """Get maintainability distribution."""
        return self.metrics.get('maintainability_distribution', {}) if self.metrics else {}
    
    # Folder-level metrics
    def get_folder_metrics(self, folder: str) -> Optional[Dict[str, Any]]:
        """Get metrics for a specific folder."""
        if not self.metrics:
            return None
        return self.metrics.get('by_folder', {}).get(folder)
    
    def get_all_folders(self) -> List[str]:
        """Get list of all folders."""
        if not self.metrics:
            return []
        return list(self.metrics.get('by_folder', {}).keys())
    
    def get_top_folders_by_size(self, limit: int = 10) -> List[tuple]:
        """Get top folders by lines of code."""
        if not self.metrics:
            return []
        
        folders = self.metrics.get('by_folder', {})
        sorted_folders = sorted(
            folders.items(),
            key=lambda x: x[1].get('loc', 0),
            reverse=True
        )
        return sorted_folders[:limit]
    
    def get_top_folders_by_complexity(self, limit: int = 10) -> List[tuple]:
        """Get top folders by average complexity."""
        if not self.metrics:
            return []
        
        folders = self.metrics.get('by_folder', {})
        sorted_folders = sorted(
            folders.items(),
            key=lambda x: x[1].get('avg_complexity', 0),
            reverse=True
        )
        return sorted_folders[:limit]
    
    def get_folders_needing_attention(self, maintainability_threshold: float = 50.0) -> List[tuple]:
        """Get folders with low maintainability scores."""
        if not self.metrics:
            return []
        
        folders = self.metrics.get('by_folder', {})
        low_maintainability = [
            (name, metrics)
            for name, metrics in folders.items()
            if metrics.get('avg_maintainability', 100) < maintainability_threshold
        ]
        return sorted(low_maintainability, key=lambda x: x[1].get('avg_maintainability', 0))
    
    # Query answering
    def answer_query(self, query: str) -> str:
        """Answer a natural language query about metrics."""
        if not self.metrics:
            return "Enhanced metrics not loaded. Please run generate_enhanced_metrics.py first."
        
        query_lower = query.lower()
        
        # Overall statistics
        if "how many files" in query_lower:
            return f"The codebase has **{self.get_total_files()} Python files** analyzed."
        
        if "how many lines" in query_lower or "total lines" in query_lower:
            total = self.get_total_lines()
            sloc = self.get_total_sloc()
            code = self.get_total_code_lines()
            comments = self.get_total_comments()
            blank = self.get_total_blank_lines()
            return f"""The codebase has:
- **{total:,} total lines**
- **{sloc:,} source lines of code (SLOC)**
- **{code:,} code lines**
- **{comments:,} comment lines**
- **{blank:,} blank lines**"""
        
        if "average complexity" in query_lower or "complexity score" in query_lower:
            avg_cc = self.get_average_complexity()
            dist = self.get_complexity_distribution()
            return f"""**Average complexity: {avg_cc:.1f}**

Complexity distribution:
- Simple (≤5): {dist.get('simple', 0)} files
- Moderate (6-10): {dist.get('moderate', 0)} files
- Complex (11-20): {dist.get('complex', 0)} files
- Very complex (>20): {dist.get('very_complex', 0)} files"""
        
        if "maintainability" in query_lower:
            avg_mi = self.get_average_maintainability()
            dist = self.get_maintainability_distribution()
            return f"""**Average maintainability: {avg_mi:.1f}**

Maintainability distribution:
- Rank A (highly maintainable): {dist.get('A', 0)} files
- Rank B (moderately maintainable): {dist.get('B', 0)} files
- Rank C (difficult to maintain): {dist.get('C', 0)} files
- Rank F (extremely difficult): {dist.get('F', 0)} files"""
        
        if "estimated bugs" in query_lower or "bug estimate" in query_lower:
            bugs = self.get_estimated_bugs()
            return f"Based on Halstead metrics, the codebase has an estimated **{bugs:.1f} bugs**."
        
        # Folder queries
        if "largest folder" in query_lower or "biggest folder" in query_lower:
            top_folders = self.get_top_folders_by_size(5)
            if top_folders:
                folders_list = "\n".join([
                    f"  {i+1}. **{name}**: {metrics['loc']:,} lines, {metrics['files']} files"
                    for i, (name, metrics) in enumerate(top_folders)
                ])
                return f"**Top 5 largest folders:**\n\n{folders_list}"
            return "No folder data available."
        
        if "most complex folder" in query_lower:
            top_folders = self.get_top_folders_by_complexity(5)
            if top_folders:
                folders_list = "\n".join([
                    f"  {i+1}. **{name}**: complexity {metrics.get('avg_complexity', 0):.1f}"
                    for i, (name, metrics) in enumerate(top_folders)
                ])
                return f"**Top 5 most complex folders:**\n\n{folders_list}"
            return "No folder data available."
        
        if "folders need" in query_lower or "folders needing attention" in query_lower:
            folders = self.get_folders_needing_attention(50.0)
            if folders:
                folders_list = "\n".join([
                    f"  - **{name}**: maintainability {metrics.get('avg_maintainability', 0):.1f}"
                    for name, metrics in folders[:5]
                ])
                return f"**Folders needing attention** (maintainability < 50):\n\n{folders_list}"
            return "✓ All folders have acceptable maintainability scores!"
        
        # Specific folder query
        if "metrics for" in query_lower or "stats for" in query_lower:
            # Extract folder name
            for folder in self.get_all_folders():
                if folder.lower() in query_lower:
                    metrics = self.get_folder_metrics(folder)
                    if metrics:
                        return f"""**Metrics for {folder}:**

- Files: {metrics['files']}
- Lines: {metrics['loc']:,}
- Code: {metrics['code']:,}
- Comments: {metrics['comments']:,}
- Blank: {metrics['blank']:,}
- Avg Complexity: {metrics.get('avg_complexity', 0):.1f}
- Avg Maintainability: {metrics.get('avg_maintainability', 0):.1f}"""
        
        return "I don't understand that query. Try asking:\n- 'How many files/lines?'\n- 'What is the average complexity?'\n- 'What is the maintainability?'\n- 'What are the largest folders?'\n- 'What are the most complex folders?'\n- 'What folders need attention?'"


# Singleton instance
_enhanced_analytics: Optional[EnhancedAnalyticsManager] = None


def get_enhanced_analytics_manager() -> EnhancedAnalyticsManager:
    """Get or create singleton enhanced analytics manager."""
    global _enhanced_analytics
    if _enhanced_analytics is None:
        _enhanced_analytics = EnhancedAnalyticsManager()
    return _enhanced_analytics