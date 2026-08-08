"""Java symbol extraction via tree-sitter — replaces the old regex-based Java
path in code_symbol_extractor.py (AST-ownership-transfer plan Phase 2).

Structurally ported from Egeria Advisor's advisor/data_prep/java_symbol_extractor.py
(same tree-sitter node-type walking, same Javadoc/modifier/complexity logic),
adapted to emit CodeSymbol (RE's unified symbol shape) instead of EA's separate
JavaSymbol dataclass — RE doesn't persist decorators/parameters/body (see
migration plan decision D2: EA extracts these but never persists them either).

Fixes, by construction, the confirmed bugs in RE's old regex-based Java
extractor: cross-class attribution ("last class wins" — a single mutable
variable, not a real parent-class stack), multi-line signatures silently
dropped (regexes were single-line-anchored), @Override-adjacent declarations
silently dropped (annotations weren't stripped before the modifier match),
and no inner-class/Javadoc/generics handling at all.

Reuses RE's existing tree-sitter grammar-loading code (ast_chunker.py's
ASTChunker._get_parser()) rather than duplicating it — that module already
depends on tree-sitter-java for pgvector chunk-boundary splitting.
"""
from __future__ import annotations

import re

from resource_explorer.ingestion.code_symbol_extractor import CodeSymbol

_JAVADOC_STRIP = re.compile(r"^\s*/?\*+/?", re.MULTILINE)

_TYPE_NODE_KINDS: dict[str, str] = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "class",
    "annotation_type_declaration": "interface",
}

_METHOD_NODE_TYPES = frozenset({"method_declaration", "interface_method_declaration"})

_DECISION_TYPES = frozenset({
    "if_statement", "for_statement", "enhanced_for_statement",
    "while_statement", "do_statement", "catch_clause",
    "switch_expression", "switch_statement",
    "conditional_expression",  # ternary
})


def _clean_javadoc(text: str) -> str:
    lines = []
    for line in text.splitlines():
        line = _JAVADOC_STRIP.sub("", line).strip()
        if line:
            lines.append(line)
    return " ".join(lines[:3]) if lines else ""


def _preceding_javadoc(node) -> str:
    """Return the Javadoc comment immediately before node, if present."""
    if node.parent is None:
        return ""
    siblings = node.parent.children
    idx = siblings.index(node)
    for i in range(idx - 1, -1, -1):
        sib = siblings[i]
        if sib.type in ("block_comment", "line_comment"):
            text = sib.text.decode("utf-8", errors="replace")
            if text.startswith("/**"):
                return _clean_javadoc(text)
            break
        if sib.type not in ("line_comment",):
            break
    return ""


def _modifiers(node) -> list[str]:
    # NOT node.child_by_field_name("modifiers") — that's what EA's own
    # java_symbol_extractor.py uses, and it's broken against the installed
    # tree-sitter-java grammar (0.23.x): the `modifiers` node is a real
    # positional child but isn't exposed as a named field on
    # method_declaration/class_declaration, so field lookup always returns
    # None. Confirmed live: EA's is_private/annotation extraction has been
    # silently broken this whole time as a result (is_private always False).
    # Look the child up by type instead, which actually works.
    mods = next((c for c in node.children if c.type == "modifiers"), None)
    if mods is None:
        return []
    return [c.text.decode() for c in mods.children if c.type not in ("marker_annotation", "annotation")]


def _is_private_node(node) -> bool:
    return "private" in _modifiers(node)


def _complexity(node) -> int:
    """Cyclomatic complexity via a manual tree-cursor walk — same formula and
    node-type set as Egeria Advisor's own Java extractor, for consistent
    complexity scores across both apps' code intelligence."""
    count = 1
    cursor = node.walk()
    while True:
        if cursor.node.type in _DECISION_TYPES:
            count += 1
        if not cursor.goto_first_child():
            while not cursor.goto_next_sibling():
                if not cursor.goto_parent():
                    return count
    return count


def _parse_param_names(params_node) -> list[str]:
    if params_node is None:
        return []
    names = []
    for child in params_node.children:
        if child.type in ("formal_parameter", "spread_parameter"):
            name = child.child_by_field_name("name")
            if name:
                names.append(name.text.decode())
    return names


class JavaSymbolExtractor:
    """Parse Java source via tree-sitter and return CodeSymbol objects."""

    def _get_parser(self):
        from resource_explorer.ingestion.ast_chunker import ASTChunker
        return ASTChunker()._get_parser("java")

    def extract(self, file_path: str, content: str, project_slug: str) -> list[CodeSymbol]:
        parser = self._get_parser()
        if parser is None:
            return []  # tree-sitter-java unavailable — caller gets no Java symbols, not a crash

        try:
            tree = parser.parse(bytes(content, "utf-8"))
        except Exception:
            return []

        symbols: list[CodeSymbol] = []
        self._walk_node(tree.root_node, file_path, project_slug, parent_class="", symbols=symbols)
        return symbols

    # ── tree walking ────────────────────────────────────────────────────────

    def _walk_node(self, node, file_path: str, project_slug: str, parent_class: str, symbols: list[CodeSymbol]) -> None:
        if node.type in _TYPE_NODE_KINDS:
            sym = self._extract_type(node, file_path, project_slug, parent_class)
            if sym:
                symbols.append(sym)
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        self._walk_node(child, file_path, project_slug, sym.name, symbols)
        elif node.type in _METHOD_NODE_TYPES:
            sym = self._extract_method(node, file_path, project_slug, parent_class)
            if sym:
                symbols.append(sym)
        elif node.type == "constructor_declaration":
            sym = self._extract_constructor(node, file_path, project_slug, parent_class)
            if sym:
                symbols.append(sym)
        else:
            for child in node.children:
                self._walk_node(child, file_path, project_slug, parent_class, symbols)

    # ── type (class / interface / enum / record / annotation type) ────────

    def _extract_type(self, node, file_path: str, project_slug: str, parent_class: str) -> CodeSymbol | None:
        try:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None
            name = name_node.text.decode()
            kind = _TYPE_NODE_KINDS.get(node.type, "class")

            bases: list[str] = []
            superclass = node.child_by_field_name("superclass")
            if superclass:
                sc_text = superclass.text.decode()
                m = re.match(r"^\s*extends\s+(.+)$", sc_text, re.IGNORECASE)
                sc_name = m.group(1).strip() if m else sc_text.replace("extends", "").strip()
                bases.append(sc_name.split(".")[-1])

            interfaces = node.child_by_field_name("interfaces")
            if interfaces:
                int_text = interfaces.text.decode()
                m = re.match(r"^\s*implements\s+(.+)$", int_text, re.IGNORECASE)
                names_part = m.group(1).strip() if m else int_text.replace("implements", "").strip()
                for name_item in names_part.split(","):
                    name_item = name_item.strip()
                    if name_item:
                        bases.append(name_item.split(".")[-1])

            qualified_name = f"{parent_class}.{name}" if parent_class else name
            return CodeSymbol(
                project_slug=project_slug,
                file_path=file_path,
                language="java",
                kind=kind,
                name=name,
                qualified_name=qualified_name,
                signature="",
                docstring=_preceding_javadoc(node),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent_class=parent_class,
                is_private=_is_private_node(node),
                bases=bases,
            )
        except Exception:
            return None

    # ── method ──────────────────────────────────────────────────────────────

    def _extract_method(self, node, file_path: str, project_slug: str, parent_class: str) -> CodeSymbol | None:
        try:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None
            name = name_node.text.decode()

            ret_node = node.child_by_field_name("type")
            return_type = ret_node.text.decode() if ret_node else "void"

            params_node = node.child_by_field_name("parameters")
            params_text = params_node.text.decode() if params_node else "()"

            mods = _modifiers(node)
            sig = f"{' '.join(mods + [return_type])} {name}{params_text}".strip()
            qualified_name = f"{parent_class}.{name}" if parent_class else name

            return CodeSymbol(
                project_slug=project_slug,
                file_path=file_path,
                language="java",
                kind="method",
                name=name,
                qualified_name=qualified_name,
                signature=sig,
                docstring=_preceding_javadoc(node),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent_class=parent_class,
                return_type=return_type,
                is_private=_is_private_node(node),
                complexity=_complexity(node),
            )
        except Exception:
            return None

    # ── constructor (treated as a method, matching EA's convention) ────────

    def _extract_constructor(self, node, file_path: str, project_slug: str, parent_class: str) -> CodeSymbol | None:
        try:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None
            name = name_node.text.decode()

            params_node = node.child_by_field_name("parameters")
            params_text = params_node.text.decode() if params_node else "()"

            mods = _modifiers(node)
            sig = f"{' '.join(mods)} {name}{params_text}".strip()
            qualified_name = f"{parent_class}.{name}" if parent_class else name

            return CodeSymbol(
                project_slug=project_slug,
                file_path=file_path,
                language="java",
                kind="method",
                name=name,
                qualified_name=qualified_name,
                signature=sig,
                docstring=_preceding_javadoc(node),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent_class=parent_class,
                is_private=_is_private_node(node),
                complexity=_complexity(node),
            )
        except Exception:
            return None
