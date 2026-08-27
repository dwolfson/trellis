"""DEPRECATED — no longer called from anywhere in the ingestion pipeline
(AST-ownership-transfer plan Phase 8). Resource Explorer now owns Java
symbol extraction for the repos in RE's "egeria" project group (see
resource_explorer/ingestion/java_symbol_extractor.py — a genuine upgrade:
fixes a real bug this module had, where node.child_by_field_name("modifiers")
silently returned None against the installed tree-sitter-java grammar,
making is_private always False and @-annotation capture always empty).

Kept in place, not deleted, as a rollback safety net (decision D8) — not
wired into CodeIngester.ingest_file() anymore (see advisor/ingest.py).

Java symbol extractor using tree-sitter.

Extracts classes, interfaces, enums, methods, and constructors from Java source
files. Produces the same shape as CodeElement from code_parser.py so they can
be stored in the same CodeSymbolStore table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger


# ── lazy-load tree-sitter so the module is importable even if the package
#    is not installed (other code paths will just not call this extractor)
_PARSER = None
_LANG = None


def _get_parser():
    global _PARSER, _LANG
    if _PARSER is None:
        import tree_sitter_java as tsjava
        from tree_sitter import Language, Parser
        _LANG = Language(tsjava.language())
        _PARSER = Parser(_LANG)
    return _PARSER


# ── data class matching CodeElement interface expected by CodeSymbolStore ──

@dataclass
class JavaSymbol:
    """A Java code symbol — same public interface as CodeElement."""

    type: str               # class | interface | enum | method | constructor
    name: str
    file_path: str
    line_number: int
    end_line_number: int
    docstring: Optional[str]
    signature: str
    body: str = ""          # not stored in symbol table, kept for parity
    parent_class: Optional[str] = None
    decorators: list = field(default_factory=list)   # annotations
    parameters: list = field(default_factory=list)
    return_type: Optional[str] = None
    is_async: bool = False
    is_private: bool = False
    complexity: int = 1
    bases: list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.parent_class}.{self.name}" if self.parent_class else self.name

    @property
    def is_public(self) -> bool:
        return not self.is_private


# ── helpers ────────────────────────────────────────────────────────────────

_JAVADOC_STRIP = re.compile(r"^\s*/?\*+/?", re.MULTILINE)


def _clean_javadoc(text: str) -> str:
    """Extract readable text from a Javadoc block comment."""
    lines = []
    for line in text.splitlines():
        line = _JAVADOC_STRIP.sub("", line).strip()
        if line:
            lines.append(line)
    # Return first meaningful line as the summary docstring
    return " ".join(lines[:3]) if lines else ""


def _preceding_javadoc(node) -> Optional[str]:
    """Return the Javadoc comment immediately before node, if present."""
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
    return None


def _modifiers_node(node):
    # NOT node.child_by_field_name("modifiers") — broken against the installed
    # tree-sitter-java grammar (0.23.x): `modifiers` is a real positional
    # child of method_declaration/class_declaration but isn't exposed as a
    # named field, so field-name lookup always silently returns None. This
    # made is_private always False and _annotations() always [] for every
    # symbol ever extracted — found live while porting this extractor to
    # Resource Explorer (AST-ownership-transfer plan Phase 2). Fixed here by
    # looking the child up by type instead, which actually works.
    return next((c for c in node.children if c.type == "modifiers"), None)


def _modifiers(node) -> list[str]:
    mods = _modifiers_node(node)
    if mods is None:
        return []
    return [c.text.decode() for c in mods.children if c.type not in ("marker_annotation", "annotation")]


def _annotations(node) -> list[str]:
    mods = _modifiers_node(node)
    if mods is None:
        return []
    return [c.text.decode() for c in mods.children if c.type in ("marker_annotation", "annotation")]


def _is_private_node(node) -> bool:
    return "private" in _modifiers(node)


def _complexity(node) -> int:
    """Rough cyclomatic complexity: count decision keywords in the subtree."""
    _DECISION_TYPES = {
        "if_statement", "for_statement", "enhanced_for_statement",
        "while_statement", "do_statement", "catch_clause",
        "switch_expression", "switch_statement",
        "conditional_expression",  # ternary
    }
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


# ── main extractor class ───────────────────────────────────────────────────

class JavaSymbolExtractor:
    """Parse a Java source file and return a list of JavaSymbol objects."""

    def __init__(self):
        self.errors: list[dict] = []

    def extract_file(self, file_path: Path) -> list[JavaSymbol]:
        try:
            content = file_path.read_bytes()
        except Exception as exc:
            self.errors.append({"file": str(file_path), "error": str(exc)})
            return []
        return self.extract(content, str(file_path))

    def extract(self, source: bytes, file_path: str = "<unknown>") -> list[JavaSymbol]:
        try:
            parser = _get_parser()
        except ImportError as exc:
            logger.warning(f"tree-sitter-java not available: {exc}")
            return []

        try:
            tree = parser.parse(source)
        except Exception as exc:
            self.errors.append({"file": file_path, "error": str(exc)})
            return []

        symbols: list[JavaSymbol] = []
        self._walk_node(tree.root_node, file_path, source, parent_class=None, symbols=symbols)
        return symbols

    # ── tree walking ──────────────────────────────────────────────────────

    def _walk_node(self, node, file_path: str, source: bytes,
                   parent_class: Optional[str], symbols: list[JavaSymbol]) -> None:
        if node.type in ("class_declaration", "interface_declaration",
                          "enum_declaration", "record_declaration",
                          "annotation_type_declaration"):
            sym = self._extract_type(node, file_path, parent_class)
            if sym:
                symbols.append(sym)
                # Recurse into nested types and methods
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        self._walk_node(child, file_path, source, sym.name, symbols)
        elif node.type in ("method_declaration", "interface_method_declaration"):
            sym = self._extract_method(node, file_path, parent_class)
            if sym:
                symbols.append(sym)
        elif node.type == "constructor_declaration":
            sym = self._extract_constructor(node, file_path, parent_class)
            if sym:
                symbols.append(sym)
        else:
            for child in node.children:
                self._walk_node(child, file_path, source, parent_class, symbols)

    # ── type (class / interface / enum) ───────────────────────────────────

    def _extract_type(self, node, file_path: str,
                      parent_class: Optional[str]) -> Optional[JavaSymbol]:
        try:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None
            name = name_node.text.decode()

            kind_map = {
                "class_declaration": "class",
                "interface_declaration": "interface",
                "enum_declaration": "enum",
                "record_declaration": "class",
                "annotation_type_declaration": "interface",
            }
            kind = kind_map.get(node.type, "class")

            mods = _modifiers(node)
            sig_parts = mods + [kind, name]

            bases = []

            # superclass
            superclass = node.child_by_field_name("superclass")
            if superclass:
                sc_text = superclass.text.decode()
                # Parse base class name, stripping "extends"
                m = re.match(r"^\s*extends\s+(.+)$", sc_text, re.IGNORECASE)
                sc_name = m.group(1).strip() if m else sc_text.replace("extends", "").strip()
                bases.append(sc_name.split(".")[-1])
                sig_parts.append(sc_text)

            # interfaces
            interfaces = node.child_by_field_name("interfaces")
            if interfaces:
                int_text = interfaces.text.decode()
                # Parse interface names, stripping "implements"
                m = re.match(r"^\s*implements\s+(.+)$", int_text, re.IGNORECASE)
                names_part = m.group(1).strip() if m else int_text.replace("implements", "").strip()
                for name_item in names_part.split(","):
                    name_item = name_item.strip()
                    if name_item:
                        bases.append(name_item.split(".")[-1])
                sig_parts.append(int_text)

            return JavaSymbol(
                type=kind,
                name=name,
                file_path=file_path,
                line_number=node.start_point[0] + 1,
                end_line_number=node.end_point[0] + 1,
                docstring=_preceding_javadoc(node),
                signature=" ".join(sig_parts),
                parent_class=parent_class,
                decorators=_annotations(node),
                is_private=_is_private_node(node),
                complexity=1,
                bases=bases,
            )
        except Exception as exc:
            logger.debug(f"JavaSymbolExtractor: type extraction failed in {file_path}: {exc}")
            return None

    # ── method ────────────────────────────────────────────────────────────

    def _extract_method(self, node, file_path: str,
                        parent_class: Optional[str]) -> Optional[JavaSymbol]:
        try:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None
            name = name_node.text.decode()

            ret_node = node.child_by_field_name("type")
            return_type = ret_node.text.decode() if ret_node else "void"

            params_node = node.child_by_field_name("parameters")
            params_text = params_node.text.decode() if params_node else "()"
            params = self._parse_param_names(params_node)

            mods = _modifiers(node)
            sig = f"{' '.join(mods + [return_type])} {name}{params_text}".strip()

            return JavaSymbol(
                type="method",
                name=name,
                file_path=file_path,
                line_number=node.start_point[0] + 1,
                end_line_number=node.end_point[0] + 1,
                docstring=_preceding_javadoc(node),
                signature=sig,
                parent_class=parent_class,
                decorators=_annotations(node),
                parameters=params,
                return_type=return_type,
                is_private=_is_private_node(node),
                complexity=_complexity(node),
            )
        except Exception as exc:
            logger.debug(f"JavaSymbolExtractor: method extraction failed in {file_path}: {exc}")
            return None

    # ── constructor ───────────────────────────────────────────────────────

    def _extract_constructor(self, node, file_path: str,
                              parent_class: Optional[str]) -> Optional[JavaSymbol]:
        try:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                return None
            name = name_node.text.decode()

            params_node = node.child_by_field_name("parameters")
            params_text = params_node.text.decode() if params_node else "()"
            params = self._parse_param_names(params_node)

            mods = _modifiers(node)
            sig = f"{' '.join(mods)} {name}{params_text}".strip()

            return JavaSymbol(
                type="method",   # treat constructors as methods for query simplicity
                name=name,
                file_path=file_path,
                line_number=node.start_point[0] + 1,
                end_line_number=node.end_point[0] + 1,
                docstring=_preceding_javadoc(node),
                signature=sig,
                parent_class=parent_class,
                decorators=_annotations(node),
                parameters=params,
                return_type=None,
                is_private=_is_private_node(node),
                complexity=_complexity(node),
            )
        except Exception as exc:
            logger.debug(f"JavaSymbolExtractor: constructor extraction failed in {file_path}: {exc}")
            return None

    # ── parameter helpers ─────────────────────────────────────────────────

    @staticmethod
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


def extract_java_symbols(file_path: Path) -> list[JavaSymbol]:
    """Convenience wrapper used by advisor.ingest."""
    return JavaSymbolExtractor().extract_file(file_path)
