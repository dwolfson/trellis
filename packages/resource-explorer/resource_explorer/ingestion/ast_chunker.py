"""AST-aware code chunker using tree-sitter — optional; falls back to _fixed_window if unavailable."""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Top-level node types that define logical chunk boundaries per language
_TOP_LEVEL: dict[str, set[str]] = {
    "python": {"function_definition", "class_definition", "decorated_definition"},
    "javascript": {
        "function_declaration", "class_declaration", "export_statement",
        "lexical_declaration", "variable_declaration",
    },
    "typescript": {
        "function_declaration", "class_declaration", "export_statement",
        "interface_declaration", "type_alias_declaration",
    },
    "go": {"function_declaration", "method_declaration", "type_declaration"},
    "java": {
        "class_declaration", "interface_declaration", "enum_declaration",
        "method_declaration",
    },
}

# Inner node types used when a top-level chunk is too large to split further
_INNER: dict[str, set[str]] = {
    "python": {"function_definition", "decorated_definition"},
    "javascript": {"method_definition", "function_declaration", "arrow_function"},
    "typescript": {"method_definition", "function_declaration", "arrow_function"},
    "go": {"function_declaration", "method_declaration"},
    "java": {"method_declaration", "constructor_declaration"},
}

_TS_MODULE: dict[str, str] = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_javascript",
    "go": "tree_sitter_go",
    "java": "tree_sitter_java",
}


class ASTChunker:
    """
    Splits source code on function/class boundaries using tree-sitter.

    Install the [ast] extra to use this:
        uv sync --extra ast

    When unavailable, CodeParser will fall back to _fixed_window automatically.
    """

    @classmethod
    def is_available(cls) -> bool:
        try:
            import tree_sitter  # noqa: F401
            return True
        except ImportError:
            return False

    def chunk(
        self,
        text: str,
        language: str,
        max_tokens: int = 512,
        overlap: int = 64,
    ) -> list[str]:
        """Return a list of code chunks split at AST boundaries."""
        parser = self._get_parser(language)
        if parser is None:
            return []  # caller should fall back to _fixed_window

        try:
            tree = parser.parse(bytes(text, "utf-8"))
        except Exception:
            return []

        top_types = _TOP_LEVEL.get(language, set())
        inner_types = _INNER.get(language, set())
        root_children = list(tree.root_node.children)

        segments: list[str] = self._collect_segments(
            root_children, text, top_types, inner_types, max_tokens
        )
        if not segments:
            return []

        return self._merge_small_segments(segments, max_tokens, overlap)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _get_parser(self, language: str):
        module_name = _TS_MODULE.get(language)
        if not module_name:
            return None
        try:
            from tree_sitter import Language, Parser
            lang_mod = importlib.import_module(module_name)
            lang = Language(lang_mod.language())
            return Parser(lang)
        except (ImportError, AttributeError, Exception):
            return None

    def _node_text(self, node, source: str) -> str:
        return source[node.start_byte:node.end_byte]

    def _word_count(self, text: str) -> int:
        return len(text.split())

    def _collect_segments(
        self,
        children,
        source: str,
        top_types: set[str],
        inner_types: set[str],
        max_tokens: int,
    ) -> list[str]:
        """Walk children and collect text segments at semantic boundaries."""
        segments: list[str] = []
        current_buf: list[str] = []

        def flush():
            if current_buf:
                segments.append("\n".join(current_buf).strip())
                current_buf.clear()

        for node in children:
            node_text = self._node_text(node, source).strip()
            if not node_text:
                continue

            if node.type in top_types:
                # Named top-level definition
                if self._word_count(node_text) <= max_tokens:
                    flush()
                    segments.append(node_text)
                else:
                    # Too large — try to split on inner boundaries
                    flush()
                    inner_segs = self._split_on_inner(node, source, inner_types, max_tokens)
                    if inner_segs:
                        segments.extend(inner_segs)
                    else:
                        # Cannot split further — emit as-is (oversized but complete)
                        segments.append(node_text)
            else:
                # Non-definition node (imports, top-level statements, etc.)
                current_buf.append(node_text)
                if self._word_count("\n".join(current_buf)) >= max_tokens:
                    flush()

        flush()
        return segments

    def _split_on_inner(self, node, source: str, inner_types: set[str], max_tokens: int) -> list[str]:
        """Try to split an oversized top-level node on its inner method boundaries."""
        segments: list[str] = []
        preamble_lines: list[str] = []

        for child in node.children:
            child_text = self._node_text(child, source).strip()
            if not child_text:
                continue
            if child.type in inner_types:
                if preamble_lines:
                    segments.append("\n".join(preamble_lines).strip())
                    preamble_lines = []
                segments.append(child_text)
            else:
                preamble_lines.append(child_text)

        if preamble_lines:
            segments.append("\n".join(preamble_lines).strip())

        return [s for s in segments if s]

    def _merge_small_segments(self, segments: list[str], max_tokens: int, overlap: int) -> list[str]:
        """
        Merge consecutive small segments until they fill max_tokens.
        When a merge is emitted, the last `overlap` words of it prefix the next chunk.
        """
        result: list[str] = []
        bucket: list[str] = []
        bucket_words = 0
        overlap_prefix: list[str] = []

        def flush_bucket():
            nonlocal bucket, bucket_words, overlap_prefix
            if bucket:
                text = "\n\n".join(bucket)
                result.append(text)
                words = text.split()
                overlap_prefix = words[-overlap:] if len(words) > overlap else words
                bucket = []
                bucket_words = 0

        for seg in segments:
            words = seg.split()
            wc = len(words)
            if wc >= max_tokens:
                # Oversized individual segment: flush current bucket first, emit as-is
                flush_bucket()
                overlap_prefix = []
                result.append(seg)
            elif bucket_words + wc > max_tokens:
                flush_bucket()
                # Start new bucket with overlap prefix
                if overlap_prefix:
                    bucket = [" ".join(overlap_prefix)]
                    bucket_words = len(overlap_prefix)
                bucket.append(seg)
                bucket_words += wc
            else:
                bucket.append(seg)
                bucket_words += wc

        flush_bucket()
        return result
