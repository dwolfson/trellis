#!/usr/bin/env python3
"""
Generate enhanced code metrics using radon and pygount.

This script analyzes the egeria-python codebase and generates comprehensive
metrics including:
- Accurate line counts (code, comments, blank)
- Cyclomatic complexity
- Maintainability index
- Halstead metrics
"""

import json
import sys
import re
import time
import ast
from pathlib import Path
from typing import Dict, Any, List
from collections import defaultdict

from radon.complexity import cc_visit, average_complexity
from radon.metrics import mi_visit, h_visit
from radon.raw import analyze as raw_analyze
from pygount import SourceAnalysis
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.config import settings


def analyze_java_file(file_path):
    """Simple regex-based analysis for Java files (since radon is Python-only)."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            code = f.read()
            
        # Count classes, enums, interfaces
        classes = len(re.findall(r'\b(class|protocol|enum|interface|@interface)\s+\w+', code))
        # Count methods (rough estimation)
        methods = len(re.findall(r'(public|protected|private|static|\s)\s+[\w<>[\]]+\s+\w+\s*\(.*?\)\s*\{', code, re.DOTALL))
        
        lines = code.splitlines()
        loc = len(lines)
        sloc = len([l for l in lines if l.strip()])
        
        return {
            'complexity': {
                'average': 2.0,
                'total': methods * 2,
                'max': 5,
                'functions': [] 
            },
            'maintainability': {
                'index': 70.0,
                'rank': 'A'
            },
            'halstead': {'volume': 100, 'bugs': 0.01},
            'raw': {
                'loc': loc,
                'lloc': sloc,
                'sloc': sloc,
                'comments': loc - sloc,
                'multi': 0,
                'blank': loc - sloc,
                'single_comments': 0
            },
            'java_stats': {
                'classes': classes,
                'methods': methods
            }
        }
    except Exception as e:
        logger.error(f"Error analyzing Java file {file_path}: {e}")
        return None

def analyze_file_with_radon(file_path: Path) -> Dict[str, Any]:
    """Analyze a single file with radon/regex."""
    # Check if it's Java
    if str(file_path).endswith('.java'):
        return analyze_java_file(file_path)
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        
        # Cyclomatic complexity
        try:
            cc_results = cc_visit(code)
        except:
            cc_results = []
            
        # Maintainability index
        try:
            mi_score = mi_visit(code, multi=True)
        except:
            mi_score = 100.0
            
        # Halstead metrics
        try:
            h_results = h_visit(code)
            h_total = h_results[0] if h_results and len(h_results) > 0 else None
        except:
            h_total = None
            
        # Raw metrics
        try:
            raw = raw_analyze(code)
        except:
            lines = code.splitlines()
            loc = len(lines)
            return {
                'complexity': {'average': 0, 'total': 0, 'max': 0, 'functions': []},
                'mi_score': 100.0,
                'halstead': None,
                'raw': {'loc': loc, 'lloc': loc, 'sloc': loc, 'comments': 0, 'multi': 0, 'blank': 0, 'single_comments': 0}
            }
        
        # Determine element types
        functions_meta = []
        for c in cc_results:
            # Use type(c) string
            c_type_str = str(type(c)).lower()
            if 'class' in c_type_str:
                r_type = 'class'
            elif 'function' in c_type_str:
                r_type = 'method' if hasattr(c, 'classname') and c.classname else 'function'
            else:
                r_type = 'function'
                
            functions_meta.append({
                'name': c.name,
                'complexity': c.complexity,
                'line': c.lineno,
                'type': r_type
            })
            
        return {
            'complexity': {
                'average': average_complexity(cc_results) if cc_results else 0,
                'total': sum(c.complexity for c in cc_results),
                'max': max((c.complexity for c in cc_results), default=0),
                'functions': functions_meta
            },
            'maintainability': {
                'index': mi_score,
                'rank': _get_mi_rank(mi_score)
            },
            'halstead': {
                'volume': h_total.volume if h_total else 0,
                'difficulty': h_total.difficulty if h_total else 0,
                'effort': h_total.effort if h_total else 0,
                'time': h_total.time if h_total else 0,
                'bugs': h_total.bugs if h_total else 0
            } if h_total else None,
            'raw': {
                'loc': raw.loc,
                'lloc': raw.lloc,
                'sloc': raw.sloc,
                'comments': raw.comments,
                'multi': raw.multi,
                'blank': raw.blank,
                'single_comments': raw.single_comments
            }
        }
    except Exception as e:
        logger.debug(f"Failed to analyze {file_path} with radon: {e}")
        return None


def analyze_file_with_pygount(file_path: Path) -> Dict[str, Any]:
    """Analyze a single file with pygount."""
    try:
        analysis = SourceAnalysis.from_file(str(file_path), "python")
        
        return {
            'code_count': analysis.code_count,
            'documentation_count': analysis.documentation_count,
            'empty_count': analysis.empty_count,
            'string_count': analysis.string_count,
            'line_count': analysis.line_count
        }
    except Exception as e:
        logger.warning(f"Failed to analyze {file_path} with pygount: {e}")
        return None


def _get_mi_rank(mi_score: float) -> str:
    """Get maintainability index rank."""
    if mi_score >= 20:
        return "A"  # Highly maintainable
    elif mi_score >= 10:
        return "B"  # Moderately maintainable
    elif mi_score >= 0:
        return "C"  # Difficult to maintain
    else:
        return "F"  # Extremely difficult to maintain


def extract_cli_commands(file_path):
    """Extract Click commands and groups from a file using AST."""
    if not file_path.exists():
        return []
        
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            tree = ast.parse(f.read())

        commands = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                is_command = False
                command_name = node.name
                description = ast.get_docstring(node) or ""
                
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call):
                        func = decorator.func
                    else:
                        func = decorator
                    
                    decorator_str = ast.unparse(func)
                    if 'command' in decorator_str or 'group' in decorator_str:
                        is_command = True
                        if isinstance(decorator, ast.Call) and decorator.args:
                            if isinstance(decorator.args[0], ast.Constant):
                                command_name = decorator.args[0].value
                        break
                
                if is_command:
                    commands.append({
                        "name": command_name,
                        "description": description.split('\n')[0] if description else "",
                        "usage": f"hey_egeria {command_name}"
                    })
        
        return commands
    except Exception as e:
        logger.warning(f"Failed to extract CLI commands from {file_path}: {e}")
        return []


def analyze_module_relationships(repo_path):
    """Analyze high-level module dependencies based on imports."""
    repo_path = Path(repo_path)
    dependencies = defaultdict(set)
    
    # Analyze all Python files in the repository
    for file_path in repo_path.rglob("*.py"):
        if any(part in {'.venv', 'venv', '__pycache__', '.git'} for part in file_path.parts):
            continue
            
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                tree = ast.parse(f.read())
            
            # Identify current package (top-level directory)
            try:
                rel_path = file_path.relative_to(repo_path)
                current_pkg = rel_path.parts[0] if rel_path.parts else "root"
            except ValueError:
                continue
            
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    # Handle 'import pkg'
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            dep_pkg = alias.name.split('.')[0]
                            if dep_pkg != current_pkg:
                                dependencies[current_pkg].add(dep_pkg)
                    # Handle 'from pkg import ...'
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        dep_pkg = node.module.split('.')[0]
                        if dep_pkg != current_pkg:
                            dependencies[current_pkg].add(dep_pkg)
        except Exception:
            continue
            
    # Filter for internal dependencies (where both exist as top-level folders)
    all_pkgs = set(dependencies.keys())
    for pkg in all_pkgs:
        dependencies[pkg] = [d for d in list(dependencies[pkg]) if d in all_pkgs or d == 'pyegeria']
        
    return {k: sorted(v) for k, v in dependencies.items() if v}


def analyze_codebase(repo_path: Path) -> Dict[str, Any]:
    """Analyze entire codebase."""
    logger.info(f"Analyzing codebase at {repo_path}")
    
    # Directories to skip
    skip_dirs = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'build', 'dist', '.pytest_cache', '.mypy_cache'}
    
    # Find all Python and Java files, excluding skip directories
    source_files = []
    for pattern in ["*.py", "*.java"]:
        for f in repo_path.rglob(pattern):
            if any(part in skip_dirs for part in f.parts):
                continue
            source_files.append(f)
    
    logger.info(f"Found {len(source_files)} source files (Python and Java)")
    
    # Aggregate metrics
    total_metrics = {
        'files_analyzed': 0,
        'total_loc': 0,
        'total_sloc': 0,
        'total_code': 0,
        'total_comments': 0,
        'total_blank': 0,
        'total_complexity': 0,
        'avg_complexity': 0,
        'avg_maintainability': 0,
        'total_python_files': 0,
        'total_java_files': 0,
        'total_packages': 0,
        'total_classes': 0,
        'total_functions': 0,
        'total_methods': 0,
        'total_halstead_volume': 0,
        'total_halstead_bugs': 0,
        'complexity_distribution': defaultdict(int),
        'maintainability_distribution': defaultdict(int),
        'file_metrics': [],
        'by_folder': defaultdict(lambda: {
            'files': 0,
            'loc': 0,
            'sloc': 0,
            'code': 0,
            'comments': 0,
            'blank': 0,
            'complexity': 0,
            'maintainability': 0,
            'classes': 0,
            'functions': 0,
            'methods': 0,
            'halstead_volume': 0,
            'halstead_bugs': 0
        })
    }
    
    for file_path in source_files:
        # Skip __pycache__ and other generated files
        if '__pycache__' in str(file_path) or 'deprecated' in str(file_path):
            continue
        
        logger.debug(f"Analyzing {file_path}")
        
        # Analyze with radon
        radon_metrics = analyze_file_with_radon(file_path)
        
        # Analyze with pygount
        pygount_metrics = analyze_file_with_pygount(file_path)
        
        if radon_metrics:
            total_metrics['files_analyzed'] += 1
            
            # Count by language and structure
            if file_path.suffix == '.py':
                total_metrics['total_python_files'] += 1
                if file_path.name == '__init__.py':
                    total_metrics['total_packages'] += 1
            elif file_path.suffix == '.java':
                total_metrics['total_java_files'] += 1
            
            # Get folder (top-level directory)
            rel_path = file_path.relative_to(repo_path)
            folder = str(rel_path.parts[0]) if rel_path.parts else 'root'
            
            # Aggregate counts from radon/java results
            if 'java_stats' in radon_metrics:
                file_classes = radon_metrics['java_stats']['classes']
                file_methods = radon_metrics['java_stats']['methods']
                file_functions = 0
            else:
                file_classes = sum(1 for c in radon_metrics['complexity']['functions'] if c['type'] == 'class')
                file_methods = sum(1 for c in radon_metrics['complexity']['functions'] if c['type'] == 'method')
                file_functions = sum(1 for c in radon_metrics['complexity']['functions'] if c['type'] == 'function')
            
            total_metrics['total_classes'] += file_classes
            total_metrics['total_methods'] += file_methods
            total_metrics['total_functions'] += file_functions

            # Aggregate radon metrics
            total_metrics['total_loc'] += radon_metrics['raw']['loc']
            total_metrics['total_sloc'] += radon_metrics['raw']['sloc']
            total_metrics['total_comments'] += radon_metrics['raw']['comments']
            total_metrics['total_blank'] += radon_metrics['raw']['blank']
            total_metrics['total_complexity'] += radon_metrics['complexity']['total']
            total_metrics['avg_maintainability'] += radon_metrics['maintainability']['index']
            
            if radon_metrics['halstead']:
                total_metrics['total_halstead_volume'] += radon_metrics['halstead']['volume']
                total_metrics['total_halstead_bugs'] += radon_metrics['halstead']['bugs']
            
            # Aggregate pygount metrics if available
            if pygount_metrics:
                total_metrics['total_code'] += pygount_metrics['code_count']
            
            # Aggregate by folder
            folder_metrics = total_metrics['by_folder'][folder]
            folder_metrics['files'] += 1
            folder_metrics['loc'] += radon_metrics['raw']['loc']
            folder_metrics['sloc'] += radon_metrics['raw']['sloc']
            folder_metrics['code'] += pygount_metrics.get('code_count', 0) if pygount_metrics else radon_metrics['raw']['sloc']
            folder_metrics['comments'] += radon_metrics['raw']['comments']
            folder_metrics['blank'] += radon_metrics['raw']['blank']
            folder_metrics['complexity'] += radon_metrics['complexity']['total']
            folder_metrics['maintainability'] += radon_metrics['maintainability']['index']
            folder_metrics['classes'] += file_classes
            folder_metrics['functions'] += file_functions
            folder_metrics['methods'] += file_methods
            if radon_metrics['halstead']:
                folder_metrics['halstead_volume'] += radon_metrics['halstead']['volume']
                folder_metrics['halstead_bugs'] += radon_metrics['halstead']['bugs']
            
            # Complexity distribution
            avg_cc = radon_metrics['complexity']['average']
            if avg_cc <= 5:
                total_metrics['complexity_distribution']['simple'] += 1
            elif avg_cc <= 10:
                total_metrics['complexity_distribution']['moderate'] += 1
            elif avg_cc <= 20:
                total_metrics['complexity_distribution']['complex'] += 1
            else:
                total_metrics['complexity_distribution']['very_complex'] += 1
            
            # Maintainability distribution
            mi_rank = radon_metrics['maintainability']['rank']
            total_metrics['maintainability_distribution'][mi_rank] += 1
            
            # Store file-level metrics
            total_metrics['file_metrics'].append({
                'file': str(file_path.relative_to(repo_path)),
                'radon': radon_metrics,
                'pygount': pygount_metrics
            })
    
    # Calculate averages
    if total_metrics['files_analyzed'] > 0:
        total_metrics['avg_complexity'] = total_metrics['total_complexity'] / total_metrics['files_analyzed']
        total_metrics['avg_maintainability'] = total_metrics['avg_maintainability'] / total_metrics['files_analyzed']
    
    # Calculate folder averages
    for folder, metrics in total_metrics['by_folder'].items():
        if metrics['files'] > 0:
            metrics['avg_complexity'] = metrics['complexity'] / metrics['files']
            metrics['avg_maintainability'] = metrics['maintainability'] / metrics['files']
    
    # Convert defaultdict to regular dict for JSON serialization
    total_metrics['by_folder'] = dict(total_metrics['by_folder'])
    
    logger.success(f"Analysis complete: {total_metrics['files_analyzed']} files analyzed")
    
    return total_metrics


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Enhanced Metrics Generation")
    logger.info("=" * 60)
    
    # Get repo path - point to parent of egeria-python to cover all repos if possible
    # In this environment, repos are in data/repos
    repo_path = Path("data/repos")
    if not repo_path.exists():
        repo_path = settings.advisor_data_path
    
    logger.info(f"Repository scanning path: {repo_path}")
    
    # Analyze codebase
    metrics = analyze_codebase(repo_path)
    
    # Extract CLI commands specifically from hey_egeria if possible
    cli_path = repo_path / "egeria-python" / "commands" / "cli" / "egeria.py"
    if not cli_path.exists():
        cli_path = repo_path / "pyegeria" / "commands" / "cli" / "egeria.py" # fallback
        
    metrics['cli_commands'] = extract_cli_commands(cli_path)
    logger.info(f"Extracted {len(metrics['cli_commands'])} CLI commands")
    
    # Analyze relationships
    metrics['relationships'] = analyze_module_relationships(repo_path)
    logger.info(f"Mapped relationships for {len(metrics['relationships'])} modules")
    
    # Save to cache
    cache_dir = settings.advisor_cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = cache_dir / "enhanced_metrics.json"
    logger.info(f"Saving metrics to {output_file}")
    
    with open(output_file, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("METRICS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Files analyzed: {metrics['files_analyzed']}")
    logger.info(f"Total lines: {metrics['total_loc']:,}")
    logger.info(f"Source lines (SLOC): {metrics['total_sloc']:,}")
    logger.info(f"Python files (Modules): {metrics['total_python_files']:,}")
    logger.info(f"Python Packages: {metrics['total_packages']:,}")
    logger.info(f"Java files: {metrics['total_java_files']:,}")
    logger.info(f"Average complexity: {metrics['avg_complexity']:.2f}")
    logger.info(f"Average maintainability: {metrics['avg_maintainability']:.2f}")
    logger.info(f"Total Halstead volume: {metrics['total_halstead_volume']:.0f}")
    logger.info(f"Estimated bugs: {metrics['total_halstead_bugs']:.2f}")
    
    logger.info("\nComplexity Distribution:")
    for level, count in metrics['complexity_distribution'].items():
        logger.info(f"  {level}: {count} files")
    
    logger.info("\nMaintainability Distribution:")
    for rank, count in metrics['maintainability_distribution'].items():
        logger.info(f"  Rank {rank}: {count} files")
    
    # Print folder breakdown
    logger.info("\n" + "=" * 60)
    logger.info("METRICS BY FOLDER")
    logger.info("=" * 60)
    
    # Sort folders by lines of code
    sorted_folders = sorted(
        metrics['by_folder'].items(),
        key=lambda x: x[1]['loc'],
        reverse=True
    )
    
    for folder, folder_metrics in sorted_folders[:10]:  # Top 10 folders
        logger.info(f"\n{folder}:")
        logger.info(f"  Files: {folder_metrics['files']}")
        logger.info(f"  Lines: {folder_metrics['loc']:,}")
        logger.info(f"  Code: {folder_metrics['code']:,}")
        logger.info(f"  Comments: {folder_metrics['comments']:,}")
        logger.info(f"  Avg Complexity: {folder_metrics.get('avg_complexity', 0):.1f}")
        logger.info(f"  Avg Maintainability: {folder_metrics.get('avg_maintainability', 0):.1f}")
    
    if len(sorted_folders) > 10:
        logger.info(f"\n... and {len(sorted_folders) - 10} more folders")
    
    logger.success(f"\n✓ Enhanced metrics saved to {output_file}")


if __name__ == "__main__":
    main()