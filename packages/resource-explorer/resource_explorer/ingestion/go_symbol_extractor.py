"""Go symbol extraction via tree-sitter — replaces the old regex-based Go
path in code_symbol_extractor.py (mirrors the Java tree-sitter upgrade from
the AST-ownership-transfer plan Phase 2, extended to Go/JS per the same
"targeted regex was fine until something needed better quality" reasoning).

Fixes, by construction, the confirmed weak spots in the old regex extractor:
multi-line receiver/parameter/return-type clauses (the old regex was
single-line-anchored, e.g. `func (r *Router) Foo(\n  a string,\n) error`
silently dropped), struct-literal false positives inside function bodies
never risk matching `_GO_FUNC` again since real node types are walked, and
receiver-type extraction now handles a non-pointer receiver correctly
(the old regex's `.lstrip("*")` heuristic worked but tree-sitter reads the
grammar's own pointer_type/type_identifier node shape directly).

Reuses RE's existing tree-sitter grammar-loading code (ast_chunker.py's
ASTChunker._get_parser()) rather than duplicating it — that module already
depends on tree-sitter-go for pgvector chunk-boundary splitting (optional
[ast] extra).
"""
from __future__ import annotations

from resource_explorer.ingestion.code_symbol_extractor import CodeSymbol


def _receiver_type(receiver_node) -> str:
    """receiver_node is a parameter_list like '(r *Router)' or '(r Router)' —
    its one parameter_declaration's type field is either a bare
    type_identifier or a pointer_type wrapping one."""
    if receiver_node is None:
        return ""
    for child in receiver_node.children:
        if child.type == "parameter_declaration":
            type_node = child.child_by_field_name("type")
            if type_node is None:
                continue
            if type_node.type == "pointer_type":
                inner = type_node.children[-1] if type_node.children else None
                return inner.text.decode() if inner else ""
            return type_node.text.decode()
    return ""


def _result_text(result_node) -> str:
    if result_node is None:
        return ""
    # A single bare return type (e.g. "error") parses as one type node, not
    # a parameter_list — multiple/named returns (e.g. "(int, error)") parse
    # as a parameter_list. node.text covers both shapes identically.
    return result_node.text.decode()


class GoSymbolExtractor:
    """Parse Go source via tree-sitter and return CodeSymbol objects."""

    def _get_parser(self):
        from resource_explorer.ingestion.ast_chunker import ASTChunker
        return ASTChunker()._get_parser("go")

    def extract(self, file_path: str, content: str, project_slug: str) -> list[CodeSymbol]:
        parser = self._get_parser()
        if parser is None:
            return []  # tree-sitter-go unavailable (optional [ast] extra) — caller falls back to regex

        try:
            tree = parser.parse(bytes(content, "utf-8"))
        except Exception:
            return []

        symbols: list[CodeSymbol] = []
        for node in tree.root_node.children:
            if node.type == "type_declaration":
                symbols.extend(self._extract_type_decl(node, file_path, project_slug))
            elif node.type == "function_declaration":
                sym = self._extract_function(node, file_path, project_slug)
                if sym:
                    symbols.append(sym)
            elif node.type == "method_declaration":
                sym = self._extract_method(node, file_path, project_slug)
                if sym:
                    symbols.append(sym)
        return symbols

    # ── type declarations (struct / interface) — a type_declaration can hold
    # multiple comma/paren-grouped type_specs, so this yields 0..N symbols ──

    def _extract_type_decl(self, node, file_path: str, project_slug: str) -> list[CodeSymbol]:
        out: list[CodeSymbol] = []
        for spec in node.children:
            if spec.type != "type_spec":
                continue
            try:
                name_node = spec.child_by_field_name("name")
                type_node = spec.child_by_field_name("type")
                if name_node is None or type_node is None:
                    continue
                if type_node.type == "struct_type":
                    kind = "class"  # matches the old regex extractor's convention (no dedicated "struct" kind)
                elif type_node.type == "interface_type":
                    kind = "interface"
                else:
                    continue  # type alias (e.g. `type ID = string`) — not a symbol worth indexing
                name = name_node.text.decode()
                out.append(CodeSymbol(
                    project_slug=project_slug, file_path=file_path, language="go",
                    kind=kind, name=name, qualified_name=name, signature="",
                    docstring="", start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                ))
            except Exception:
                continue
        return out

    # ── free function ──────────────────────────────────────────────────────

    def _extract_function(self, node, file_path: str, project_slug: str) -> CodeSymbol | None:
        try:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None
            name = name_node.text.decode()
            params = node.child_by_field_name("parameters")
            params_text = params.text.decode() if params else "()"
            result = _result_text(node.child_by_field_name("result"))
            sig = params_text + (f" -> {result}" if result else "")
            return CodeSymbol(
                project_slug=project_slug, file_path=file_path, language="go",
                kind="function", name=name, qualified_name=name, signature=sig,
                docstring="", start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                return_type=result,
            )
        except Exception:
            return None

    # ── method (has a receiver) ────────────────────────────────────────────

    def _extract_method(self, node, file_path: str, project_slug: str) -> CodeSymbol | None:
        try:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None
            name = name_node.text.decode()
            receiver_type = _receiver_type(node.child_by_field_name("receiver"))
            params = node.child_by_field_name("parameters")
            params_text = params.text.decode() if params else "()"
            result = _result_text(node.child_by_field_name("result"))
            sig = params_text + (f" -> {result}" if result else "")
            qualified_name = f"{receiver_type}.{name}" if receiver_type else name
            return CodeSymbol(
                project_slug=project_slug, file_path=file_path, language="go",
                kind="method", name=name, qualified_name=qualified_name, signature=sig,
                docstring="", start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                parent_class=receiver_type, return_type=result,
            )
        except Exception:
            return None
