"""OpenAPI / Swagger spec parser — extracts endpoints and schemas as searchable chunks."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class APIChunk:
    text: str
    metadata: dict  # file_path, endpoint, method, project_slug


class APIParser:
    """
    Parses OpenAPI 3.x and Swagger 2.x specs into per-endpoint chunks.
    Each chunk contains: HTTP method, path, summary, description, and parameter names.
    This makes endpoints directly searchable by natural language.
    """

    def parse(self, file_path: str, content: str, project_slug: str) -> list[APIChunk]:
        import yaml, json
        try:
            spec = yaml.safe_load(content) if file_path.endswith((".yaml", ".yml")) else json.loads(content)
        except Exception:
            return []

        chunks = []
        for path, methods in spec.get("paths", {}).items():
            for method, op in methods.items():
                if not isinstance(op, dict):
                    continue
                text = f"{method.upper()} {path}\n{op.get('summary', '')}\n{op.get('description', '')}"
                params = [p.get("name") for p in op.get("parameters", [])]
                if params:
                    text += f"\nParameters: {', '.join(params)}"
                chunks.append(APIChunk(
                    text=text.strip(),
                    metadata={"file_path": file_path, "endpoint": path, "method": method, "project_slug": project_slug},
                ))
        return chunks
