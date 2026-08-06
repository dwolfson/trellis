"""Defines collection types and their ingestion parameters."""
from dataclasses import dataclass


@dataclass
class CollectionType:
    name: str
    description: str
    file_extensions: list[str]
    chunk_size: int
    chunk_overlap: int
    min_file_count: int  # minimum files needed before creating this collection


COLLECTION_TYPES: dict[str, CollectionType] = {
    "python_code": CollectionType(
        name="python_code",
        description="Python source files",
        file_extensions=[".py"],
        chunk_size=512,
        chunk_overlap=64,
        min_file_count=5,
    ),
    "javascript_code": CollectionType(
        name="javascript_code",
        description="JavaScript and TypeScript source files",
        file_extensions=[".js", ".ts", ".jsx", ".tsx", ".mjs"],
        chunk_size=512,
        chunk_overlap=64,
        min_file_count=5,
    ),
    "java_code": CollectionType(
        name="java_code",
        description="Java source files",
        file_extensions=[".java"],
        chunk_size=512,
        chunk_overlap=64,
        min_file_count=5,
    ),
    "go_code": CollectionType(
        name="go_code",
        description="Go source files",
        file_extensions=[".go"],
        chunk_size=512,
        chunk_overlap=64,
        min_file_count=5,
    ),
    "markdown_docs": CollectionType(
        name="markdown_docs",
        description="README files, guides, and wiki pages",
        file_extensions=[".md", ".mdx"],
        chunk_size=384,
        chunk_overlap=48,
        min_file_count=1,
    ),
    "web_docs": CollectionType(
        name="web_docs",
        description="Documentation sites (MkDocs, Sphinx, Docusaurus)",
        file_extensions=[".html"],
        chunk_size=384,
        chunk_overlap=48,
        min_file_count=1,
    ),
    "api_reference": CollectionType(
        name="api_reference",
        description="OpenAPI specs and structured API documentation",
        file_extensions=[".yaml", ".yml", ".json"],
        chunk_size=256,
        chunk_overlap=32,
        min_file_count=1,
    ),
    "examples": CollectionType(
        name="examples",
        description="Code samples, tutorials, and Jupyter notebooks",
        file_extensions=[".ipynb", ".py", ".js", ".java"],
        chunk_size=1024,
        chunk_overlap=128,
        min_file_count=1,
    ),
    "pdfs": CollectionType(
        name="pdfs",
        description="PDF documents parsed via Docling",
        file_extensions=[".pdf"],
        chunk_size=512,
        chunk_overlap=64,
        min_file_count=1,
    ),
    "release_notes": CollectionType(
        name="release_notes",
        description="Changelogs and GitHub release bodies",
        file_extensions=[".md", ".txt"],
        chunk_size=256,
        chunk_overlap=32,
        min_file_count=1,
    ),
}

# Collections that map to each agent type
AGENT_COLLECTION_MAP: dict[str, list[str]] = {
    "code": ["python_code", "javascript_code", "java_code", "go_code", "examples"],
    "doc": ["markdown_docs", "web_docs", "api_reference", "pdfs"],
    "stats": [],  # stats agent uses SQLite, not Milvus
    "compare": ["markdown_docs", "python_code", "javascript_code", "java_code", "go_code"],
    "health": [],  # health agent uses GitHub API, not Milvus
    "general": list(COLLECTION_TYPES.keys()),
}
