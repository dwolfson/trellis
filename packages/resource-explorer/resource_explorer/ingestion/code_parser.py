"""Source code parser — Python, JavaScript/TypeScript, Java, Go."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath


@dataclass
class CodeChunk:
    text: str
    metadata: dict  # file_path, language, start_line, end_line, project_slug


class CodeParser:
    """
    Splits source files into chunks suitable for embedding.

    Strategy: split on top-level function/class boundaries where possible,
    falling back to fixed-size token windows with overlap.
    Preserves file path and line range in metadata for citation.
    """

    LANGUAGE_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".mjs": "javascript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
    }

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def parse(self, file_path: str, content: str, resource_slug: str) -> list[CodeChunk]:
        ext = PurePath(file_path).suffix.lower()
        language = self.LANGUAGE_MAP.get(ext, "text")

        chunk_texts = self._split(content, language)
        return [
            CodeChunk(
                text=chunk,
                metadata={
                    "file_path": file_path,
                    "language": language,
                    "project_slug": resource_slug,
                    "chunk_index": i,
                },
            )
            for i, chunk in enumerate(chunk_texts)
        ]

    def _split(self, content: str, language: str) -> list[str]:
        """Attempt AST-aware splitting; fall back to fixed-window if unavailable."""
        try:
            from resource_explorer.ingestion.ast_chunker import ASTChunker
            if ASTChunker.is_available() and language in ("python", "javascript", "typescript", "go", "java"):
                chunks = ASTChunker().chunk(content, language, self.chunk_size, self.chunk_overlap)
                if chunks:
                    return chunks
        except Exception:
            pass
        return self._fixed_window(content)

    def _fixed_window(self, text: str) -> list[str]:
        words = text.split()
        chunks = []
        step = self.chunk_size - self.chunk_overlap
        for i in range(0, len(words), step):
            chunk = " ".join(words[i : i + self.chunk_size])
            if chunk:
                chunks.append(chunk)
        return chunks
