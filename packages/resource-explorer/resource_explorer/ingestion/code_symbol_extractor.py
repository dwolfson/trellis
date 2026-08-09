"""Extract class/function/method symbols from source files for the code intelligence index."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field


@dataclass
class CodeSymbol:
    project_slug: str
    file_path: str
    language: str
    kind: str            # class | function | method | interface | enum
    name: str            # simple name: "parse"
    qualified_name: str  # Class.method or bare name: "CodeParser.parse"
    signature: str       # typed param list: "(self, x: int) -> str"
    docstring: str       # first line of docstring; "" if none
    start_line: int
    end_line: int
    # Added for AST-ownership-transfer plan Phase 1 — fields Egeria Advisor's
    # code_symbols schema has and RE's didn't, needed for CodeIntelAgent-style
    # queries (inheritance, hierarchy, complexity). Defaulted so JS/Go/interface
    # symbols (not upgraded in this pass) don't need every extractor call site
    # touched.
    parent_class: str = ""      # immediate enclosing class name, for methods and nested classes
    return_type: str = ""       # function/method return type annotation, if any
    is_private: bool = False    # leading underscore, not dunder
    is_async: bool = False
    complexity: int = 0         # cyclomatic complexity; 0 for non-function symbols (classes/interfaces)
    bases: list[str] = field(default_factory=list)  # class-kind only: raw base-class expressions, not FQN-resolved


class CodeSymbolExtractor:
    """
    Extract structured symbol information from source files at ingestion time.

    Python uses the stdlib ast module (zero new dependencies, full type annotation
    support). Java, JS/TS, and Go all use tree-sitter (java_symbol_extractor.py,
    js_symbol_extractor.py, go_symbol_extractor.py) — upgraded from regex
    heuristics starting with Java in the AST-ownership-transfer plan Phase 2,
    since multi-line signatures and nested-scope attribution don't hold up well
    under single-line-anchored regex matching. Java's tree-sitter grammar is a
    required base dependency; JS/Go's stay under the optional [ast] extra (used
    today only for pgvector chunk-boundary splitting, ast_chunker.py), so the
    original regex extractors are kept as the fallback when that extra isn't
    installed rather than silently returning nothing.
    """

    def extract(
        self, file_path: str, content: str, project_slug: str, language: str
    ) -> list[CodeSymbol]:
        try:
            if language == "python":
                return self._extract_python(file_path, content, project_slug)
            if language in ("javascript", "typescript"):
                return self._extract_js(file_path, content, project_slug, language)
            if language == "java":
                return self._extract_java_tree_sitter(file_path, content, project_slug)
            if language == "go":
                return self._extract_go(file_path, content, project_slug)
        except Exception:
            pass
        return []

    # ── Java — tree-sitter (see ingestion/java_symbol_extractor.py) ────────

    def _extract_java_tree_sitter(self, file_path: str, content: str, project_slug: str) -> list[CodeSymbol]:
        from resource_explorer.ingestion.java_symbol_extractor import JavaSymbolExtractor
        return JavaSymbolExtractor().extract(file_path, content, project_slug)

    # ── Python — AST ─────────────────────────────────────────────────────────

    def _extract_python(self, file_path: str, content: str, project_slug: str) -> list[CodeSymbol]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []
        visitor = _PythonVisitor(file_path, project_slug)
        visitor.visit(tree)
        return visitor.symbols

    # ── JavaScript / TypeScript — tree-sitter, regex fallback ──────────────

    def _extract_js(
        self, file_path: str, content: str, project_slug: str, language: str
    ) -> list[CodeSymbol]:
        from resource_explorer.ingestion.js_symbol_extractor import JsSymbolExtractor
        symbols = JsSymbolExtractor().extract(file_path, content, project_slug, language)
        if symbols:
            return symbols
        # Empty from tree-sitter means either a genuinely empty file or the
        # [ast] extra isn't installed (JsSymbolExtractor returns [] when its
        # parser is unavailable) — the regex path below still gives partial
        # coverage in that case rather than nothing.
        return self._extract_js_regex(file_path, content, project_slug, language)

    _JS_CLASS  = re.compile(r'^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)', re.M)
    _JS_IFACE  = re.compile(r'^(?:export\s+)?interface\s+(\w+)', re.M)
    _JS_FUNC   = re.compile(
        r'^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s+(\w+)\s*(\([^)]*\))', re.M
    )
    _JS_ARROW  = re.compile(
        r'^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*(?::\s*\S+\s*)?=>',
        re.M,
    )
    _JS_METHOD = re.compile(
        r'^\s{2,}(?:(?:public|private|protected|static|async|override|readonly)\s+)*'
        r'(\w+)\s*(\([^)]*\))\s*(?::\s*[\w<>\[\]|&,\s.]+)?\s*\{',
        re.M,
    )
    _JS_KEYWORDS = frozenset({"if", "for", "while", "switch", "catch", "do", "else"})

    def _extract_js_regex(
        self, file_path: str, content: str, project_slug: str, language: str
    ) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        current_class: str | None = None

        def ln(m: re.Match) -> int:
            return content[: m.start()].count("\n") + 1

        for m in self._JS_CLASS.finditer(content):
            current_class = m.group(1)
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language=language,
                kind="class", name=m.group(1), qualified_name=m.group(1),
                signature="", docstring="", start_line=ln(m), end_line=ln(m),
            ))

        for m in self._JS_IFACE.finditer(content):
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language=language,
                kind="interface", name=m.group(1), qualified_name=m.group(1),
                signature="", docstring="", start_line=ln(m), end_line=ln(m),
            ))

        for m in self._JS_FUNC.finditer(content):
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language=language,
                kind="function", name=m.group(1), qualified_name=m.group(1),
                signature=f"({m.group(2)})", docstring="", start_line=ln(m), end_line=ln(m),
            ))

        for m in self._JS_ARROW.finditer(content):
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language=language,
                kind="function", name=m.group(1), qualified_name=m.group(1),
                signature=f"({m.group(2)})", docstring="", start_line=ln(m), end_line=ln(m),
            ))

        for m in self._JS_METHOD.finditer(content):
            name = m.group(1)
            if name in self._JS_KEYWORDS:
                continue
            qname = f"{current_class}.{name}" if current_class else name
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language=language,
                kind="method", name=name, qualified_name=qname,
                signature=f"({m.group(2)})", docstring="", start_line=ln(m), end_line=ln(m),
            ))

        return symbols

    # ── Go — tree-sitter, regex fallback ────────────────────────────────────

    def _extract_go(self, file_path: str, content: str, project_slug: str) -> list[CodeSymbol]:
        from resource_explorer.ingestion.go_symbol_extractor import GoSymbolExtractor
        symbols = GoSymbolExtractor().extract(file_path, content, project_slug)
        if symbols:
            return symbols
        # Same fallback reasoning as _extract_js — empty means either a
        # genuinely empty file or the [ast] extra isn't installed.
        return self._extract_go_regex(file_path, content, project_slug)

    _GO_FUNC   = re.compile(
        r'^func\s+(?:\((\w+\s+\*?\w+)\)\s+)?(\w+)\s*(\([^)]*\))\s*(?:\(([^)]*)\)|([\w*\[\]]+))?',
        re.M,
    )
    _GO_STRUCT = re.compile(r'^type\s+(\w+)\s+struct\b', re.M)
    _GO_IFACE  = re.compile(r'^type\s+(\w+)\s+interface\b', re.M)

    def _extract_go_regex(self, file_path: str, content: str, project_slug: str) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []

        def ln(m: re.Match) -> int:
            return content[: m.start()].count("\n") + 1

        for m in self._GO_STRUCT.finditer(content):
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language="go",
                kind="class", name=m.group(1), qualified_name=m.group(1),
                signature="", docstring="", start_line=ln(m), end_line=ln(m),
            ))

        for m in self._GO_IFACE.finditer(content):
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language="go",
                kind="interface", name=m.group(1), qualified_name=m.group(1),
                signature="", docstring="", start_line=ln(m), end_line=ln(m),
            ))

        for m in self._GO_FUNC.finditer(content):
            receiver = m.group(1)  # e.g. "r *Router"
            name = m.group(2)
            params = m.group(3)
            ret = (m.group(4) or m.group(5) or "").strip()
            receiver_type = receiver.split()[-1].lstrip("*") if receiver else None
            kind = "method" if receiver_type else "function"
            qname = f"{receiver_type}.{name}" if receiver_type else name
            sig = params + (f" -> {ret}" if ret else "")
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language="go",
                kind=kind, name=name, qualified_name=qname,
                signature=sig, docstring="", start_line=ln(m), end_line=ln(m),
            ))

        return symbols


# ── Python AST visitor ────────────────────────────────────────────────────────

class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str, project_slug: str) -> None:
        self._file_path = file_path
        self._project_slug = project_slug
        self.symbols: list[CodeSymbol] = []
        self._class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.symbols.append(self._make_class(node))
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = "method" if self._class_stack else "function"
        self.symbols.append(self._make_func(node, kind))
        # Don't recurse — nested functions clutter the index

    @staticmethod
    def _is_private(name: str) -> bool:
        """Leading underscore but not a dunder (__init__, __repr__, ...)."""
        return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))

    @staticmethod
    def _calculate_complexity(node: ast.AST) -> int:
        """Simplified cyclomatic complexity — same formula as Egeria Advisor's
        code_parser.py, ported for consistent complexity scores across both
        apps' Python code: base 1, +1 per If/For/While/ExceptHandler, +1 per
        And/Or boolean operator."""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity

    def _make_class(self, node: ast.ClassDef) -> CodeSymbol:
        doc = (ast.get_docstring(node) or "").strip()
        parent_class = self._class_stack[-2] if len(self._class_stack) > 1 else ""
        bases = [ast.unparse(b) for b in node.bases]
        return CodeSymbol(
            project_slug=self._project_slug,
            file_path=self._file_path,
            language="python",
            kind="class",
            name=node.name,
            qualified_name=".".join(self._class_stack),  # stack already includes this class
            signature="",
            docstring=doc.split("\n")[0][:200] if doc else "",
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            parent_class=parent_class,
            is_private=self._is_private(node.name),
            bases=bases,
        )

    def _make_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef, kind: str) -> CodeSymbol:
        doc = (ast.get_docstring(node) or "").strip()
        parent_class = self._class_stack[-1] if self._class_stack else ""
        return_type = ast.unparse(node.returns) if node.returns else ""
        return CodeSymbol(
            project_slug=self._project_slug,
            file_path=self._file_path,
            language="python",
            kind=kind,
            name=node.name,
            qualified_name=".".join(self._class_stack + [node.name]),
            signature=self._build_sig(node),
            docstring=doc.split("\n")[0][:200] if doc else "",
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            parent_class=parent_class,
            return_type=return_type,
            is_private=self._is_private(node.name),
            is_async=isinstance(node, ast.AsyncFunctionDef),
            complexity=self._calculate_complexity(node),
        )

    def _build_sig(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args = node.args
        parts: list[str] = []

        for arg in getattr(args, "posonlyargs", []):
            s = arg.arg
            if arg.annotation:
                s += f": {ast.unparse(arg.annotation)}"
            parts.append(s)
        if getattr(args, "posonlyargs", []):
            parts.append("/")

        for arg in args.args:
            s = arg.arg
            if arg.annotation:
                s += f": {ast.unparse(arg.annotation)}"
            parts.append(s)

        if args.vararg:
            s = f"*{args.vararg.arg}"
            if args.vararg.annotation:
                s += f": {ast.unparse(args.vararg.annotation)}"
            parts.append(s)
        elif args.kwonlyargs:
            parts.append("*")

        for arg in args.kwonlyargs:
            s = arg.arg
            if arg.annotation:
                s += f": {ast.unparse(arg.annotation)}"
            parts.append(s)

        if args.kwarg:
            s = f"**{args.kwarg.arg}"
            if args.kwarg.annotation:
                s += f": {ast.unparse(args.kwarg.annotation)}"
            parts.append(s)

        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"({', '.join(parts)}){ret}"
