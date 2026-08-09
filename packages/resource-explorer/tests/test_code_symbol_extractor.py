"""Tests for CodeSymbolExtractor's Python path — AST-ownership-transfer plan Phase 1.

Covers the fields newly added to bring RE's extraction to parity with what
Egeria Advisor's code_symbols schema needs: parent_class, return_type,
is_private, is_async, complexity, bases (inheritance).
"""
from __future__ import annotations

from unittest.mock import patch

from resource_explorer.ingestion.code_symbol_extractor import CodeSymbolExtractor


def _extract(source: str) -> list:
    return CodeSymbolExtractor().extract("mod.py", source, "myproj", "python")


class TestPythonBasics:
    def test_function_symbol(self):
        syms = _extract("def add(x: int, y: int) -> int:\n    return x + y\n")
        assert len(syms) == 1
        s = syms[0]
        assert s.kind == "function"
        assert s.name == "add"
        assert s.qualified_name == "add"
        assert s.signature == "(x: int, y: int) -> int"
        assert s.parent_class == ""
        assert s.return_type == "int"
        assert s.is_private is False
        assert s.is_async is False

    def test_private_function(self):
        syms = _extract("def _helper():\n    pass\n")
        assert syms[0].is_private is True

    def test_dunder_is_not_private(self):
        syms = _extract("class Foo:\n    def __init__(self):\n        pass\n")
        init = next(s for s in syms if s.name == "__init__")
        assert init.is_private is False

    def test_async_function(self):
        syms = _extract("async def fetch():\n    pass\n")
        assert syms[0].is_async is True


class TestClassAndMethods:
    def test_class_and_method_parent_class(self):
        source = (
            "class Widget:\n"
            "    def price(self, tax: float) -> float:\n"
            "        return 1.0 * tax\n"
        )
        syms = _extract(source)
        cls = next(s for s in syms if s.kind == "class")
        method = next(s for s in syms if s.kind == "method")
        assert cls.name == "Widget"
        assert cls.parent_class == ""
        assert method.name == "price"
        assert method.qualified_name == "Widget.price"
        assert method.parent_class == "Widget"
        assert method.return_type == "float"

    def test_multiple_classes_correct_attribution(self):
        """Regression guard: RE's regex-based extractors (JS/Java) have a
        confirmed 'last class wins' attribution bug. The AST-based Python path
        must NOT have this bug — verify multiple classes in one file each
        attribute their own methods correctly."""
        source = (
            "class A:\n"
            "    def method_a(self):\n"
            "        pass\n\n"
            "class B:\n"
            "    def method_b(self):\n"
            "        pass\n"
        )
        syms = _extract(source)
        method_a = next(s for s in syms if s.name == "method_a")
        method_b = next(s for s in syms if s.name == "method_b")
        assert method_a.parent_class == "A"
        assert method_b.parent_class == "B"

    def test_inheritance_bases(self):
        source = "class Base:\n    pass\n\nclass Child(Base):\n    pass\n"
        syms = _extract(source)
        child = next(s for s in syms if s.name == "Child")
        base = next(s for s in syms if s.name == "Base")
        assert child.bases == ["Base"]
        assert base.bases == []

    def test_multiple_inheritance_bases(self):
        source = "class Mixin1:\n    pass\nclass Mixin2:\n    pass\nclass Combined(Mixin1, Mixin2):\n    pass\n"
        syms = _extract(source)
        combined = next(s for s in syms if s.name == "Combined")
        assert combined.bases == ["Mixin1", "Mixin2"]

    def test_nested_class_parent_class(self):
        source = "class Outer:\n    class Inner:\n        pass\n"
        syms = _extract(source)
        inner = next(s for s in syms if s.name == "Inner")
        assert inner.parent_class == "Outer"
        assert inner.qualified_name == "Outer.Inner"


class TestComplexity:
    def test_trivial_function_complexity_one(self):
        syms = _extract("def f():\n    return 1\n")
        assert syms[0].complexity == 1

    def test_if_for_while_each_add_one(self):
        source = (
            "def f(items):\n"
            "    if items:\n"
            "        pass\n"
            "    for x in items:\n"
            "        pass\n"
            "    while items:\n"
            "        break\n"
        )
        syms = _extract(source)
        # base 1 + if + for + while = 4
        assert syms[0].complexity == 4

    def test_boolean_ops_add_complexity(self):
        source = "def f(a, b, c):\n    if a and b or c:\n        pass\n"
        syms = _extract(source)
        # base 1 + if (1) + BoolOp(and: 2 values -> +1) + BoolOp(or: 2 values -> +1) = 4
        assert syms[0].complexity == 4

    def test_class_has_zero_complexity(self):
        syms = _extract("class Foo:\n    pass\n")
        assert syms[0].complexity == 0


class TestDocstringAndSignature:
    def test_docstring_first_line_only(self):
        source = 'def f():\n    """First line.\n\n    More detail.\n    """\n    pass\n'
        syms = _extract(source)
        assert syms[0].docstring == "First line."

    def test_no_docstring_is_empty_string(self):
        syms = _extract("def f():\n    pass\n")
        assert syms[0].docstring == ""


class TestJsGoRegexFallback:
    """JS/Go now try tree-sitter first (js_symbol_extractor.py /
    go_symbol_extractor.py); when unavailable — e.g. the optional [ast]
    extra isn't installed — extraction must fall back to the original regex
    path rather than silently returning nothing."""

    def test_js_falls_back_to_regex_when_tree_sitter_unavailable(self):
        with patch("resource_explorer.ingestion.ast_chunker.ASTChunker._get_parser", return_value=None):
            syms = CodeSymbolExtractor().extract(
                "foo.js", "class Foo {\n  bar() {}\n}\n", "myproj", "javascript",
            )
        assert {s.name for s in syms} == {"Foo", "bar"}

    def test_go_falls_back_to_regex_when_tree_sitter_unavailable(self):
        with patch("resource_explorer.ingestion.ast_chunker.ASTChunker._get_parser", return_value=None):
            syms = CodeSymbolExtractor().extract(
                "foo.go", "package main\ntype Router struct{}\n", "myproj", "go",
            )
        assert {s.name for s in syms} == {"Router"}
