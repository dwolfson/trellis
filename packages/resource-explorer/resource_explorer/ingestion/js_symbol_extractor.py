"""JavaScript/TypeScript symbol extraction via tree-sitter — replaces the
old regex-based JS/TS path in code_symbol_extractor.py (mirrors the Java
tree-sitter upgrade from the AST-ownership-transfer plan Phase 2, extended
to JS/Go per the same "targeted regex was fine until something needed
better quality" reasoning).

Fixes, by construction, the confirmed weak spots in the old regex extractor:
multi-line class/function/method signatures (the old regexes were
`re.M`-anchored per-line, so a wrapped parameter list or a `class Foo\n
extends Bar {` broke the match), no parent-class attribution for methods
(the old `current_class` was a single mutable variable updated in source
order — a method appearing between two classes, or a file with methods
before any class, attributed wrong), and no distinction between an
`export`-wrapped declaration and a bare one (the old regexes special-cased
`(?:export\\s+)?` per pattern; tree-sitter just unwraps export_statement).

TypeScript-only syntax (interface/type-alias declarations, decorators,
generics-heavy signatures) is NOT captured here — parsed with the plain
JavaScript grammar (tree_sitter_javascript has no separate TS grammar
bundled), matching the same simplification ast_chunker.py already makes
for TypeScript chunking. A .ts file's classes/functions/methods still
extract correctly; only TS-exclusive top-level constructs are missed.

Reuses RE's existing tree-sitter grammar-loading code (ast_chunker.py's
ASTChunker._get_parser()) rather than duplicating it — that module already
depends on tree-sitter-javascript for pgvector chunk-boundary splitting
(optional [ast] extra).
"""
from __future__ import annotations

from resource_explorer.ingestion.code_symbol_extractor import CodeSymbol

_METHOD_NAME_FIELD_TYPES = frozenset({"property_identifier", "private_property_identifier"})


def _is_async(node) -> bool:
    return any(c.type == "async" for c in node.children)


def _superclass_name(class_node) -> str:
    heritage = next((c for c in class_node.children if c.type == "class_heritage"), None)
    if heritage is None:
        return ""
    name_node = next((c for c in heritage.children if c.type == "identifier"), None)
    return name_node.text.decode() if name_node else ""


class JsSymbolExtractor:
    """Parse JS/TS source via tree-sitter and return CodeSymbol objects."""

    def _get_parser(self, language: str):
        from resource_explorer.ingestion.ast_chunker import ASTChunker
        # Both "javascript" and "typescript" resolve to the same grammar
        # module (ast_chunker.py's _TS_MODULE) — see module docstring.
        return ASTChunker()._get_parser(language)

    def extract(self, file_path: str, content: str, resource_slug: str, language: str) -> list[CodeSymbol]:
        parser = self._get_parser(language)
        if parser is None:
            return []  # tree-sitter-javascript unavailable (optional [ast] extra) — caller falls back to regex

        try:
            tree = parser.parse(bytes(content, "utf-8"))
        except Exception:
            return []

        symbols: list[CodeSymbol] = []
        self._walk(tree.root_node, file_path, resource_slug, language, parent_class="", symbols=symbols)
        return symbols

    # ── tree walking ────────────────────────────────────────────────────────

    def _walk(self, node, file_path: str, resource_slug: str, language: str, parent_class: str, symbols: list[CodeSymbol]) -> None:
        if node.type == "class_declaration":
            sym = self._extract_class(node, file_path, resource_slug, language)
            if sym:
                symbols.append(sym)
                body = next((c for c in node.children if c.type == "class_body"), None)
                if body:
                    for child in body.children:
                        self._walk(child, file_path, resource_slug, language, sym.name, symbols)
        elif node.type == "method_definition":
            sym = self._extract_method(node, file_path, resource_slug, language, parent_class)
            if sym:
                symbols.append(sym)
        elif node.type in ("function_declaration", "generator_function_declaration"):
            sym = self._extract_function(node, file_path, resource_slug, language)
            if sym:
                symbols.append(sym)
        elif node.type == "variable_declarator":
            sym = self._extract_arrow_variable(node, file_path, resource_slug, language)
            if sym:
                symbols.append(sym)
            # Don't recurse into the initializer — an arrow function's own
            # body isn't a declaration boundary worth walking further.
        else:
            for child in node.children:
                self._walk(child, file_path, resource_slug, language, parent_class, symbols)

    # ── class ───────────────────────────────────────────────────────────────

    def _extract_class(self, node, file_path: str, resource_slug: str, language: str) -> CodeSymbol | None:
        try:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None  # anonymous class expression (e.g. `export default class { ... }`)
            name = name_node.text.decode()
            superclass = _superclass_name(node)
            return CodeSymbol(
                resource_slug=resource_slug, file_path=file_path, language=language,
                kind="class", name=name, qualified_name=name, signature="",
                docstring="", start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                bases=[superclass] if superclass else [],
            )
        except Exception:
            return None

    # ── class method ────────────────────────────────────────────────────────

    def _extract_method(self, node, file_path: str, resource_slug: str, language: str, parent_class: str) -> CodeSymbol | None:
        try:
            name_node = node.child_by_field_name("name")
            if name_node is None or name_node.type not in _METHOD_NAME_FIELD_TYPES:
                return None
            # private_property_identifier's own text includes the leading
            # '#' (e.g. "#secret") — strip it so `name` is the bare
            # identifier, consistent with every other symbol kind here.
            name = name_node.text.decode().lstrip("#")
            params = node.child_by_field_name("parameters")
            params_text = params.text.decode() if params else "()"
            qualified_name = f"{parent_class}.{name}" if parent_class else name
            return CodeSymbol(
                resource_slug=resource_slug, file_path=file_path, language=language,
                kind="method", name=name, qualified_name=qualified_name, signature=params_text,
                docstring="", start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                parent_class=parent_class, is_async=_is_async(node),
                is_private=name_node.type == "private_property_identifier",
            )
        except Exception:
            return None

    # ── free / generator function ──────────────────────────────────────────

    def _extract_function(self, node, file_path: str, resource_slug: str, language: str) -> CodeSymbol | None:
        try:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None  # anonymous (e.g. `export default function() {...}`)
            name = name_node.text.decode()
            params = node.child_by_field_name("parameters")
            params_text = params.text.decode() if params else "()"
            return CodeSymbol(
                resource_slug=resource_slug, file_path=file_path, language=language,
                kind="function", name=name, qualified_name=name, signature=params_text,
                docstring="", start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                is_async=_is_async(node),
            )
        except Exception:
            return None

    # ── const/let/var foo = (...) => {...} ─────────────────────────────────

    def _extract_arrow_variable(self, node, file_path: str, resource_slug: str, language: str) -> CodeSymbol | None:
        try:
            value = node.child_by_field_name("value")
            if value is None or value.type != "arrow_function":
                return None
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None
            name = name_node.text.decode()
            params = value.child_by_field_name("parameters")
            # A single-identifier arrow param (`x => x*2`, no parens) isn't
            # wrapped in formal_parameters — reconstruct a parenthesized form
            # for a consistent signature string either way.
            if params is None:
                bare = next((c for c in value.children if c.type == "identifier"), None)
                params_text = f"({bare.text.decode()})" if bare else "()"
            else:
                params_text = params.text.decode()
            return CodeSymbol(
                resource_slug=resource_slug, file_path=file_path, language=language,
                kind="function", name=name, qualified_name=name, signature=params_text,
                docstring="", start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                is_async=_is_async(value),
            )
        except Exception:
            return None
