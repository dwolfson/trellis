"""Extract metadata from files for indexing and search."""
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger
import hashlib


@dataclass
class FileMetadata:
    """Represents metadata extracted from a file."""
    
    file_path: str
    file_name: str
    file_type: str  # python, markdown, text
    file_size: int
    last_modified: datetime
    content_hash: str
    module_path: Optional[str] = None
    package: Optional[str] = None
    category: Optional[str] = None  # core, omvs, commands, tests, examples, docs
    keywords: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    exports: List[str] = field(default_factory=list)
    line_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "last_modified": self.last_modified.isoformat(),
            "content_hash": self.content_hash,
            "module_path": self.module_path,
            "package": self.package,
            "category": self.category,
            "keywords": self.keywords,
            "dependencies": self.dependencies,
            "exports": self.exports,
            "line_count": self.line_count,
        }


class MetadataExtractor:
    """Extract metadata from files for indexing."""
    
    def __init__(self, root_path: Optional[Path] = None):
        """
        Initialize the metadata extractor.
        
        Parameters
        ----------
        root_path : Path, optional
            Root path of the repository for relative path calculation
        """
        self.root_path = root_path
        self.extracted_metadata: List[FileMetadata] = []
        self.errors: List[Dict[str, Any]] = []
    
    def extract_from_file(self, file_path: Path) -> Optional[FileMetadata]:
        """
        Extract metadata from a file.
        
        Parameters
        ----------
        file_path : Path
            Path to the file
        
        Returns
        -------
        FileMetadata, optional
            Extracted metadata or None if extraction fails
        """
        try:
            # Get basic file info
            stat = file_path.stat()
            file_size = stat.st_size
            last_modified = datetime.fromtimestamp(stat.st_mtime)
            
            # Read content for hash and analysis
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                # Binary file, skip content analysis
                content = ""
                logger.debug(f"Skipping binary file: {file_path}")
            
            # Calculate content hash
            content_hash = hashlib.md5(content.encode()).hexdigest()
            
            # Count lines
            line_count = len(content.split('\n')) if content else 0
            
            # Determine file type
            file_type = self._determine_file_type(file_path)
            
            # Extract module path and package
            module_path, package = self._extract_module_info(file_path)
            
            # Determine category
            category = self._determine_category(file_path)
            
            # Extract keywords
            keywords = self._extract_keywords(file_path, content)
            
            # Extract dependencies and exports for Python files
            dependencies = []
            exports = []
            if file_type == "python" and content:
                dependencies = self._extract_dependencies(content)
                exports = self._extract_exports(content)
            
            metadata = FileMetadata(
                file_path=str(file_path),
                file_name=file_path.name,
                file_type=file_type,
                file_size=file_size,
                last_modified=last_modified,
                content_hash=content_hash,
                module_path=module_path,
                package=package,
                category=category,
                keywords=keywords,
                dependencies=dependencies,
                exports=exports,
                line_count=line_count,
            )
            
            self.extracted_metadata.append(metadata)
            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting metadata from {file_path}: {e}")
            self.errors.append({"file": str(file_path), "error": str(e)})
            return None
    
    def _determine_file_type(self, file_path: Path) -> str:
        """Determine file type from extension."""
        suffix = file_path.suffix.lower()
        
        if suffix == '.py':
            return "python"
        elif suffix in ['.md', '.markdown']:
            return "markdown"
        elif suffix in ['.rst']:
            return "restructuredtext"
        elif suffix in ['.txt']:
            return "text"
        elif suffix in ['.yaml', '.yml']:
            return "yaml"
        elif suffix in ['.json']:
            return "json"
        elif suffix in ['.toml']:
            return "toml"
        else:
            return "other"
    
    def _extract_module_info(self, file_path: Path) -> tuple[Optional[str], Optional[str]]:
        """
        Extract module path and package name.
        
        Returns
        -------
        tuple[str, str]
            (module_path, package)
        """
        if not self.root_path:
            return None, None
        
        try:
            # Get relative path from root
            rel_path = file_path.relative_to(self.root_path)
            
            # Convert to module path (e.g., pyegeria/core/client.py -> pyegeria.core.client)
            parts = list(rel_path.parts)
            if parts[-1].endswith('.py'):
                parts[-1] = parts[-1][:-3]  # Remove .py
            
            module_path = '.'.join(parts)
            package = parts[0] if parts else None
            
            return module_path, package
            
        except ValueError:
            # File is not relative to root_path
            return None, None
    
    def _determine_category(self, file_path: Path) -> Optional[str]:
        """Determine file category based on path."""
        path_str = str(file_path).lower()
        
        if '/core/' in path_str or '\\core\\' in path_str:
            return "core"
        elif '/omvs/' in path_str or '\\omvs\\' in path_str:
            return "omvs"
        elif '/commands/' in path_str or '\\commands\\' in path_str:
            return "commands"
        elif '/tests/' in path_str or '\\tests\\' in path_str or 'test_' in file_path.name:
            return "tests"
        elif '/examples/' in path_str or '\\examples\\' in path_str or 'example' in file_path.name.lower():
            return "examples"
        elif '/docs/' in path_str or '\\docs\\' in path_str or file_path.suffix in ['.md', '.rst']:
            return "docs"
        elif '/config/' in path_str or '\\config\\' in path_str:
            return "config"
        else:
            return "other"
    
    def _extract_keywords(self, file_path: Path, content: str) -> List[str]:
        """Extract keywords from file path and content."""
        keywords = set()
        
        # Add keywords from path
        path_parts = file_path.parts
        for part in path_parts:
            if part not in ['.', '..', '']:
                keywords.add(part.lower())
        
        # Add keywords from filename
        name_parts = file_path.stem.split('_')
        keywords.update(p.lower() for p in name_parts if len(p) > 2)
        
        # Add keywords from content (for Python files)
        if file_path.suffix == '.py' and content:
            # Look for class and function names
            import re
            class_matches = re.findall(r'class\s+(\w+)', content)
            func_matches = re.findall(r'def\s+(\w+)', content)
            keywords.update(m.lower() for m in class_matches)
            keywords.update(m.lower() for m in func_matches[:10])  # Limit to first 10
        
        return list(keywords)
    
    def _extract_dependencies(self, content: str) -> List[str]:
        """Extract import dependencies from Python code."""
        dependencies = set()
        
        import re
        # Match import statements
        import_pattern = r'^\s*(?:from\s+([\w.]+)\s+)?import\s+([\w.,\s]+)'
        
        for line in content.split('\n'):
            match = re.match(import_pattern, line)
            if match:
                if match.group(1):  # from X import Y
                    dependencies.add(match.group(1))
                else:  # import X
                    imports = match.group(2).split(',')
                    for imp in imports:
                        dep = imp.strip().split()[0]  # Handle 'import X as Y'
                        dependencies.add(dep)
        
        return list(dependencies)
    
    def _extract_exports(self, content: str) -> List[str]:
        """Extract exported names from Python code (__all__)."""
        exports = []
        
        import re
        # Look for __all__ definition
        all_pattern = r'__all__\s*=\s*\[(.*?)\]'
        match = re.search(all_pattern, content, re.DOTALL)
        
        if match:
            # Extract quoted strings
            items = re.findall(r'["\']([^"\']+)["\']', match.group(1))
            exports.extend(items)
        
        return exports
    
    def extract_from_directory(
        self,
        directory: Path,
        recursive: bool = True,
        file_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None
    ) -> List[FileMetadata]:
        """
        Extract metadata from all files in a directory.
        
        Parameters
        ----------
        directory : Path
            Directory to process
        recursive : bool, default True
            Whether to recursively process subdirectories
        file_patterns : List[str], optional
            File patterns to include (e.g., ['*.py', '*.md'])
        exclude_patterns : List[str], optional
            Patterns to exclude
        
        Returns
        -------
        List[FileMetadata]
            All extracted metadata
        """
        all_metadata = []
        
        if file_patterns is None:
            file_patterns = ['*.py', '*.md']
        
        for pattern in file_patterns:
            if recursive:
                glob_pattern = f"**/{pattern}"
            else:
                glob_pattern = pattern
            
            files = list(directory.glob(glob_pattern))
            logger.info(f"Found {len(files)} files matching {pattern} in {directory}")
            
            for file_path in files:
                # Check exclusions
                if exclude_patterns:
                    if any(file_path.match(excl) for excl in exclude_patterns):
                        logger.debug(f"Skipping excluded file: {file_path}")
                        continue
                
                metadata = self.extract_from_file(file_path)
                if metadata:
                    all_metadata.append(metadata)
        
        logger.info(f"Extracted metadata from {len(all_metadata)} files")
        
        return all_metadata
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get extraction statistics."""
        type_counts = {}
        category_counts = {}
        total_size = 0
        total_lines = 0
        
        for metadata in self.extracted_metadata:
            type_counts[metadata.file_type] = type_counts.get(metadata.file_type, 0) + 1
            if metadata.category:
                category_counts[metadata.category] = category_counts.get(metadata.category, 0) + 1
            total_size += metadata.file_size
            total_lines += metadata.line_count
        
        return {
            "total_files": len(self.extracted_metadata),
            "by_type": type_counts,
            "by_category": category_counts,
            "total_size_bytes": total_size,
            "total_lines": total_lines,
            "errors": len(self.errors),
            "error_details": self.errors,
        }
    
    def find_changed_files(self, previous_metadata: List[FileMetadata]) -> List[str]:
        """
        Find files that have changed since previous extraction.
        
        Parameters
        ----------
        previous_metadata : List[FileMetadata]
            Previous metadata to compare against
        
        Returns
        -------
        List[str]
            List of file paths that have changed
        """
        previous_hashes = {m.file_path: m.content_hash for m in previous_metadata}
        changed_files = []
        
        for metadata in self.extracted_metadata:
            prev_hash = previous_hashes.get(metadata.file_path)
            if prev_hash is None or prev_hash != metadata.content_hash:
                changed_files.append(metadata.file_path)
        
        return changed_files


if __name__ == "__main__":
    # Test the extractor
    import sys
    from advisor.config import settings

    if len(sys.argv) > 1:
        test_path = Path(sys.argv[1])
    else:
        test_path = settings.advisor_data_path
    
    extractor = MetadataExtractor(root_path=test_path)
    
    if test_path.is_file():
        metadata = extractor.extract_from_file(test_path)
        if metadata:
            print(f"\nMetadata for {test_path}:")
            print(f"  Type: {metadata.file_type}")
            print(f"  Category: {metadata.category}")
            print(f"  Size: {metadata.file_size} bytes")
            print(f"  Lines: {metadata.line_count}")
            print(f"  Keywords: {', '.join(metadata.keywords[:10])}")
    else:
        metadata_list = extractor.extract_from_directory(
            test_path,
            recursive=True,
            exclude_patterns=["**/__pycache__/**", "**/deprecated/**", "**/.git/**"]
        )
        print(f"\nExtracted metadata from {len(metadata_list)} files")
        
        # Print first 10
        for metadata in metadata_list[:10]:
            print(f"\n- {metadata.file_name}")
            print(f"  Path: {metadata.file_path}")
            print(f"  Type: {metadata.file_type}, Category: {metadata.category}")
            print(f"  Size: {metadata.file_size} bytes, Lines: {metadata.line_count}")
    
    # Print statistics
    stats = extractor.get_statistics()
    print(f"\nStatistics:")
    print(f"  Total files: {stats['total_files']}")
    print(f"  By type: {stats['by_type']}")
    print(f"  By category: {stats['by_category']}")
    print(f"  Total size: {stats['total_size_bytes']:,} bytes")
    print(f"  Total lines: {stats['total_lines']:,}")
    print(f"  Errors: {stats['errors']}")