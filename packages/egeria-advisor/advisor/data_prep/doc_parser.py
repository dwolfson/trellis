"""Document parser using Docling for markdown and documentation files."""
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from loguru import logger
import re


@dataclass
class DocumentSection:
    """Represents a section of a document."""
    
    title: str
    level: int  # Heading level (1-6)
    content: str
    file_path: str
    line_number: int
    end_line_number: int
    parent_section: Optional[str] = None
    subsections: List[str] = field(default_factory=list)
    code_blocks: List[Dict[str, str]] = field(default_factory=list)
    links: List[Dict[str, str]] = field(default_factory=list)
    images: List[Dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "title": self.title,
            "level": self.level,
            "content": self.content,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "end_line_number": self.end_line_number,
            "parent_section": self.parent_section,
            "subsections": self.subsections,
            "code_blocks": self.code_blocks,
            "links": self.links,
            "images": self.images,
        }
    
    @property
    def has_code(self) -> bool:
        """Check if section contains code blocks."""
        return len(self.code_blocks) > 0
    
    @property
    def word_count(self) -> int:
        """Get word count of content."""
        return len(self.content.split())


class DocParser:
    """Parse markdown and documentation files."""
    
    def __init__(self):
        """Initialize the document parser."""
        self.parsed_files: List[Path] = []
        self.errors: List[Dict[str, Any]] = []
    
    def parse_file(self, file_path: Path) -> List[DocumentSection]:
        """
        Parse a markdown file and extract sections.
        
        Parameters
        ----------
        file_path : Path
            Path to the markdown file to parse
        
        Returns
        -------
        List[DocumentSection]
            List of extracted document sections
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            self.errors.append({"file": str(file_path), "error": str(e), "stage": "read"})
            return []
        
        sections = self._parse_markdown(content, file_path)
        self.parsed_files.append(file_path)
        logger.info(f"Parsed {file_path}: found {len(sections)} sections")
        
        return sections
    
    def _parse_markdown(self, content: str, file_path: Path) -> List[DocumentSection]:
        """
        Parse markdown content into sections.
        
        Parameters
        ----------
        content : str
            Markdown content to parse
        file_path : Path
            Path to the file being parsed
        
        Returns
        -------
        List[DocumentSection]
            List of document sections
        """
        sections = []
        lines = content.split('\n')
        
        current_section = None
        current_content = []
        current_line = 0
        section_stack = []  # Track section hierarchy
        
        for i, line in enumerate(lines, 1):
            # Check for heading
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            
            if heading_match:
                # Save previous section if exists
                if current_section:
                    current_section.content = '\n'.join(current_content).strip()
                    current_section.end_line_number = i - 1
                    sections.append(current_section)
                
                # Create new section
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # Determine parent section
                parent_section = None
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()
                if section_stack:
                    parent_section = section_stack[-1][1]
                
                current_section = DocumentSection(
                    title=title,
                    level=level,
                    content="",
                    file_path=str(file_path),
                    line_number=i,
                    end_line_number=i,
                    parent_section=parent_section,
                )
                
                section_stack.append((level, title))
                current_content = []
                current_line = i
            else:
                # Add to current section content
                if current_section:
                    current_content.append(line)
        
        # Save last section
        if current_section:
            current_section.content = '\n'.join(current_content).strip()
            current_section.end_line_number = len(lines)
            sections.append(current_section)
        
        # Extract additional elements from sections
        for section in sections:
            section.code_blocks = self._extract_code_blocks(section.content)
            section.links = self._extract_links(section.content)
            section.images = self._extract_images(section.content)
        
        # Build subsection relationships
        self._build_subsection_tree(sections)
        
        return sections
    
    def _extract_code_blocks(self, content: str) -> List[Dict[str, str]]:
        """
        Extract code blocks from markdown content.
        
        Parameters
        ----------
        content : str
            Markdown content
        
        Returns
        -------
        List[Dict[str, str]]
            List of code blocks with language and content
        """
        code_blocks = []
        
        # Match fenced code blocks
        pattern = r'```(\w*)\n(.*?)```'
        matches = re.finditer(pattern, content, re.DOTALL)
        
        for match in matches:
            language = match.group(1) or "text"
            code = match.group(2).strip()
            code_blocks.append({
                "language": language,
                "code": code,
            })
        
        return code_blocks
    
    def _extract_links(self, content: str) -> List[Dict[str, str]]:
        """
        Extract links from markdown content.
        
        Parameters
        ----------
        content : str
            Markdown content
        
        Returns
        -------
        List[Dict[str, str]]
            List of links with text and URL
        """
        links = []
        
        # Match markdown links [text](url)
        pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
        matches = re.finditer(pattern, content)
        
        for match in matches:
            text = match.group(1)
            url = match.group(2)
            links.append({
                "text": text,
                "url": url,
            })
        
        return links
    
    def _extract_images(self, content: str) -> List[Dict[str, str]]:
        """
        Extract images from markdown content.
        
        Parameters
        ----------
        content : str
            Markdown content
        
        Returns
        -------
        List[Dict[str, str]]
            List of images with alt text and URL
        """
        images = []
        
        # Match markdown images ![alt](url)
        pattern = r'!\[([^\]]*)\]\(([^\)]+)\)'
        matches = re.finditer(pattern, content)
        
        for match in matches:
            alt_text = match.group(1)
            url = match.group(2)
            images.append({
                "alt_text": alt_text,
                "url": url,
            })
        
        return images
    
    def _build_subsection_tree(self, sections: List[DocumentSection]) -> None:
        """
        Build subsection relationships between sections.
        
        Parameters
        ----------
        sections : List[DocumentSection]
            List of sections to build relationships for
        """
        for i, section in enumerate(sections):
            # Find direct children (next level down)
            for j in range(i + 1, len(sections)):
                other = sections[j]
                
                # Stop if we reach a section at same or higher level
                if other.level <= section.level:
                    break
                
                # Add as subsection if it's one level down and has this as parent
                if other.level == section.level + 1 and other.parent_section == section.title:
                    section.subsections.append(other.title)
    
    def parse_directory(
        self,
        directory: Path,
        recursive: bool = True,
        file_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None
    ) -> List[DocumentSection]:
        """
        Parse all markdown files in a directory.
        
        Parameters
        ----------
        directory : Path
            Directory to parse
        recursive : bool, default True
            Whether to recursively parse subdirectories
        file_patterns : List[str], optional
            File patterns to include (e.g., ['*.md', '*.rst'])
        exclude_patterns : List[str], optional
            Patterns to exclude
        
        Returns
        -------
        List[DocumentSection]
            All extracted document sections
        """
        all_sections = []
        
        if file_patterns is None:
            file_patterns = ['*.md', '*.MD', '*.markdown']
        
        for pattern in file_patterns:
            if recursive:
                glob_pattern = f"**/{pattern}"
            else:
                glob_pattern = pattern
            
            doc_files = list(directory.glob(glob_pattern))
            logger.info(f"Found {len(doc_files)} files matching {pattern} in {directory}")
            
            for file_path in doc_files:
                # Check exclusions
                if exclude_patterns:
                    if any(file_path.match(excl) for excl in exclude_patterns):
                        logger.debug(f"Skipping excluded file: {file_path}")
                        continue
                
                sections = self.parse_file(file_path)
                all_sections.extend(sections)
        
        logger.info(
            f"Parsed {len(self.parsed_files)} files, "
            f"extracted {len(all_sections)} sections"
        )
        
        return all_sections
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get parsing statistics."""
        return {
            "files_parsed": len(self.parsed_files),
            "errors": len(self.errors),
            "error_details": self.errors,
        }
    
    def extract_table_of_contents(self, sections: List[DocumentSection]) -> str:
        """
        Generate a table of contents from sections.
        
        Parameters
        ----------
        sections : List[DocumentSection]
            List of sections to generate TOC from
        
        Returns
        -------
        str
            Markdown table of contents
        """
        toc_lines = ["# Table of Contents\n"]
        
        for section in sections:
            indent = "  " * (section.level - 1)
            toc_lines.append(f"{indent}- {section.title}")
        
        return "\n".join(toc_lines)


if __name__ == "__main__":
    # Test the parser
    import sys
    from advisor.config import settings

    if len(sys.argv) > 1:
        test_path = Path(sys.argv[1])
    else:
        test_path = settings.advisor_data_path
    
    parser = DocParser()
    
    if test_path.is_file():
        sections = parser.parse_file(test_path)
        print(f"\nFound {len(sections)} sections in {test_path}")
    else:
        sections = parser.parse_directory(
            test_path,
            recursive=True,
            exclude_patterns=["**/node_modules/**", "**/.git/**"]
        )
        print(f"\nFound {len(sections)} sections in {test_path}")
    
    # Print first 10 sections
    for section in sections[:10]:
        indent = "  " * (section.level - 1)
        print(f"{indent}- {section.title} (Level {section.level}, Line {section.line_number})")
        if section.code_blocks:
            print(f"{indent}  Code blocks: {len(section.code_blocks)}")
        if section.links:
            print(f"{indent}  Links: {len(section.links)}")
    
    # Print statistics
    stats = parser.get_statistics()
    print(f"\nStatistics:")
    print(f"  Files parsed: {stats['files_parsed']}")
    print(f"  Errors: {stats['errors']}")
    
    # Generate TOC
    if sections:
        toc = parser.extract_table_of_contents(sections[:20])
        print(f"\nSample Table of Contents:")
        print(toc)