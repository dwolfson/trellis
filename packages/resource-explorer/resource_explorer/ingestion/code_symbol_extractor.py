"""Extract class/function/method symbols from source files for the code intelligence index."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass


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


class CodeSymbolExtractor:
    """
    Extract structured symbol information from source files at ingestion time.

    Python uses the stdlib ast module (zero new dependencies, full type annotation
    support). JS/TS, Java, and Go use targeted regex — reliable for the common
    patterns without requiring tree-sitter.
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
                return self._extract_java(file_path, content, project_slug)
            if language == "go":
                return self._extract_go(file_path, content, project_slug)
        except Exception:
            pass
        return []

    # ── Python — AST ─────────────────────────────────────────────────────────

    def _extract_python(self, file_path: str, content: str, project_slug: str) -> list[CodeSymbol]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []
        visitor = _PythonVisitor(file_path, project_slug)
        visitor.visit(tree)
        return visitor.symbols

    # ── JavaScript / TypeScript — regex ──────────────────────────────────────

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

    def _extract_js(
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

    # ── Java — regex ─────────────────────────────────────────────────────────

    _JAVA_CLASS = re.compile(
        r'(?:^|\s)(?:public\s+|private\s+|protected\s+|abstract\s+|final\s+)*class\s+(\w+)',
        re.M,
    )
    _JAVA_IFACE = re.compile(
        r'(?:^|\s)(?:public\s+|private\s+|protected\s+)*interface\s+(\w+)', re.M
    )
    _JAVA_ENUM = re.compile(
        r'(?:^|\s)(?:public\s+|private\s+|protected\s+)*enum\s+(\w+)', re.M
    )
    _JAVA_METHOD = re.compile(
        r'(?:public|private|protected|static|final|abstract|synchronized|\s)+'
        r'(?:<[^>]+>\s+)?'
        r'([\w][\w<>\[\],.\s?]*?)\s+(\w+)\s*(\([^)]*\))\s*(?:throws\s+[\w,\s]+)?\s*[{;]',
        re.M,
    )
    _JAVA_SKIP = frozenset({
        "if", "for", "while", "switch", "catch", "return", "new",
        "class", "interface", "enum", "import", "package",
    })

    def _extract_java(self, file_path: str, content: str, project_slug: str) -> list[CodeSymbol]:
        symbols: list[CodeSymbol] = []
        current_class: str | None = None

        def ln(m: re.Match) -> int:
            return content[: m.start()].count("\n") + 1

        for m in self._JAVA_CLASS.finditer(content):
            current_class = m.group(1)
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language="java",
                kind="class", name=m.group(1), qualified_name=m.group(1),
                signature="", docstring="", start_line=ln(m), end_line=ln(m),
            ))

        for m in self._JAVA_IFACE.finditer(content):
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language="java",
                kind="interface", name=m.group(1), qualified_name=m.group(1),
                signature="", docstring="", start_line=ln(m), end_line=ln(m),
            ))

        for m in self._JAVA_ENUM.finditer(content):
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language="java",
                kind="enum", name=m.group(1), qualified_name=m.group(1),
                signature="", docstring="", start_line=ln(m), end_line=ln(m),
            ))

        for m in self._JAVA_METHOD.finditer(content):
            ret_type = m.group(1).strip()
            name = m.group(2)
            if name in self._JAVA_SKIP or ret_type in self._JAVA_SKIP:
                continue
            qname = f"{current_class}.{name}" if current_class else name
            symbols.append(CodeSymbol(
                project_slug=project_slug, file_path=file_path, language="java",
                kind="method", name=name, qualified_name=qname,
                signature=f"({m.group(3).strip()}) -> {ret_type}",
                docstring="", start_line=ln(m), end_line=ln(m),
            ))

        return symbols

    # ── Go — regex ───────────────────────────────────────────────────────────

    _GO_FUNC   = re.compile(
        r'^func\s+(?:\((\w+\s+\*?\w+)\)\s+)?(\w+)\s*(\([^)]*\))\s*(?:\(([^)]*)\)|([\w*\[\]]+))?',
        re.M,
    )
    _GO_STRUCT = re.compile(r'^type\s+(\w+)\s+struct\b', re.M)
    _GO_IFACE  = re.compile(r'^type\s+(\w+)\s+interface\b', re.M)

    def _extract_go(self, file_path: str, content: str, project_slug: str) -> list[CodeSymbol]:
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

    def _make_class(self, node: ast.ClassDef) -> CodeSymbol:
        doc = (ast.get_docstring(node) or "").strip()
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
        )

    def _make_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef, kind: str) -> CodeSymbol:
        doc = (ast.get_docstring(node) or "").strip()
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
