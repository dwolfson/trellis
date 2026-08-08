"""Jupyter notebook parser — extracts code and markdown cells via nbconvert."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NotebookChunk:
    text: str
    metadata: dict  # file_path, cell_type, cell_index, project_slug


class NotebookParser:
    """
    Parses .ipynb files by extracting code and markdown cells separately.
    Code cells go into the examples collection; markdown cells go into markdown_docs.
    """

    def parse(self, file_path: str, project_slug: str) -> list[NotebookChunk]:
        import json
        with open(file_path) as f:
            nb = json.load(f)

        chunks = []
        for i, cell in enumerate(nb.get("cells", [])):
            source = "".join(cell.get("source", []))
            if not source.strip():
                continue
            chunks.append(NotebookChunk(
                text=source,
                metadata={
                    "file_path": file_path,
                    "cell_type": cell["cell_type"],
                    "cell_index": i,
                    "project_slug": project_slug,
                },
            ))
        return chunks
