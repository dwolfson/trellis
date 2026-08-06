"""Document parser — Markdown (native) + Docling (PDF, web pages, DOCX)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath


@dataclass
class DocChunk:
    text: str
    metadata: dict  # source_url, file_path, page_number (PDFs), project_slug


class DocParser:
    """
    Parses documentation into chunks for embedding.

    - Markdown: split on heading boundaries, then fixed-size windows
    - PDF / DOCX / HTML: delegate to Docling for layout-aware extraction
    - Web pages: Docling WebLoader with configurable crawl depth
    """

    def __init__(self, chunk_size: int = 384, chunk_overlap: int = 48) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def parse_markdown(self, content: str, file_path: str, project_slug: str) -> list[DocChunk]:
        sections = self._split_on_headings(content)
        chunks = []
        for section in sections:
            for chunk in self._fixed_window(section):
                chunks.append(DocChunk(
                    text=chunk,
                    metadata={"file_path": file_path, "project_slug": project_slug, "type": "markdown"},
                ))
        return chunks

    def parse_pdf(self, file_path: str, project_slug: str) -> list[DocChunk]:
        """Use Docling for layout-aware PDF parsing."""
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        result = converter.convert(file_path)
        text = result.document.export_to_markdown()
        return [
            DocChunk(
                text=chunk,
                metadata={"file_path": file_path, "project_slug": project_slug, "type": "pdf"},
            )
            for chunk in self._fixed_window(text)
        ]

    def parse_url(self, url: str, project_slug: str) -> list[DocChunk]:
        """Use Docling to fetch and parse a web page."""
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        result = converter.convert(url)
        text = result.document.export_to_markdown()
        return [
            DocChunk(
                text=chunk,
                metadata={"source_url": url, "project_slug": project_slug, "type": "web"},
            )
            for chunk in self._fixed_window(text)
        ]

    def _split_on_headings(self, markdown: str) -> list[str]:
        import re
        sections = re.split(r"\n(?=#{1,3} )", markdown)
        return [s.strip() for s in sections if s.strip()]

    def _fixed_window(self, text: str) -> list[str]:
        words = text.split()
        step = self.chunk_size - self.chunk_overlap
        chunks = []
        for i in range(0, len(words), step):
            chunk = " ".join(words[i : i + self.chunk_size])
            if chunk:
                chunks.append(chunk)
        return chunks
