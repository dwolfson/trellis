"""Tests for JsSymbolExtractor (tree-sitter) — replaces the old regex-based
JS/TS path in code_symbol_extractor.py, mirroring the Java tree-sitter
upgrade (AST-ownership-transfer plan Phase 2).

Real regression coverage against the old regex extractor's confirmed weak
spots: multi-line signatures, missing parent-class attribution when a
method appears out of source order relative to its class, export-wrapped
declarations, and bare (no-parens) arrow-function params.
"""
from __future__ import annotations

import pytest

from resource_explorer.ingestion.js_symbol_extractor import JsSymbolExtractor

try:
    import tree_sitter_javascript  # noqa: F401
    _TREE_SITTER_JS_AVAILABLE = True
except ImportError:
    _TREE_SITTER_JS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _TREE_SITTER_JS_AVAILABLE, reason="tree-sitter-javascript not installed"
)


def _extract(source: str, language: str = "javascript") -> list:
    return JsSymbolExtractor().extract("test.js", source, "myproj", language)


class TestClassAndMethods:
    def test_class_and_method(self):
        source = "class Foo {\n  bar(x, y) { return x + y; }\n}\n"
        syms = _extract(source)
        cls = next(s for s in syms if s.kind == "class")
        method = next(s for s in syms if s.kind == "method")
        assert cls.name == "Foo"
        assert method.name == "bar"
        assert method.parent_class == "Foo"
        assert method.qualified_name == "Foo.bar"
        assert method.signature == "(x, y)"

    def test_inheritance_base(self):
        source = "class Foo extends Bar {\n  baz() {}\n}\n"
        syms = _extract(source)
        cls = next(s for s in syms if s.kind == "class")
        assert cls.bases == ["Bar"]

    def test_no_bases_when_no_extends(self):
        source = "class Foo {\n}\n"
        syms = _extract(source)
        cls = next(s for s in syms if s.kind == "class")
        assert cls.bases == []

    def test_static_method(self):
        source = "class Foo {\n  static create() {}\n}\n"
        syms = _extract(source)
        method = next(s for s in syms if s.kind == "method")
        assert method.name == "create"
        assert method.parent_class == "Foo"

    def test_private_method_hash_syntax(self):
        source = "class Foo {\n  #secret() {}\n}\n"
        syms = _extract(source)
        method = next(s for s in syms if s.kind == "method")
        assert method.name == "secret"
        assert method.is_private is True

    def test_async_method(self):
        source = "class Foo {\n  async load() {}\n}\n"
        syms = _extract(source)
        method = next(s for s in syms if s.kind == "method")
        assert method.is_async is True

    def test_multiple_classes_correct_attribution(self):
        """Old regex used one mutable current_class variable — a real bug
        this replaces: two classes, each with its own method, must not
        cross-attribute."""
        source = (
            "class First {\n  a() {}\n}\n"
            "class Second {\n  b() {}\n}\n"
        )
        syms = _extract(source)
        methods = {s.name: s.parent_class for s in syms if s.kind == "method"}
        assert methods == {"a": "First", "b": "Second"}

    def test_export_wrapped_class(self):
        source = "export class Foo {\n  bar() {}\n}\n"
        syms = _extract(source)
        cls = next(s for s in syms if s.kind == "class")
        method = next(s for s in syms if s.kind == "method")
        assert cls.name == "Foo"
        assert method.parent_class == "Foo"


class TestFreeFunctions:
    def test_function_declaration(self):
        source = "function add(a, b) { return a + b; }\n"
        syms = _extract(source)
        fn = next(s for s in syms if s.kind == "function")
        assert fn.name == "add"
        assert fn.signature == "(a, b)"

    def test_async_generator_function(self):
        source = "async function* gen(a) {}\n"
        syms = _extract(source)
        fn = next(s for s in syms if s.kind == "function")
        assert fn.name == "gen"
        assert fn.is_async is True

    def test_multiline_signature(self):
        """The old regex was single-line-anchored — this must not be
        silently dropped."""
        source = "function longSig(\n  a,\n  b,\n  c\n) {\n  return a;\n}\n"
        syms = _extract(source)
        fn = next((s for s in syms if s.kind == "function"), None)
        assert fn is not None
        assert fn.name == "longSig"

    def test_anonymous_default_export_not_indexed(self):
        source = "export default function() { return 1; }\n"
        syms = _extract(source)
        assert not any(s.kind == "function" for s in syms)


class TestArrowFunctions:
    def test_arrow_with_parens(self):
        source = "const add = (x, y) => x + y;\n"
        syms = _extract(source)
        fn = next(s for s in syms if s.kind == "function")
        assert fn.name == "add"
        assert fn.signature == "(x, y)"

    def test_arrow_bare_single_param(self):
        source = "const double = x => x * 2;\n"
        syms = _extract(source)
        fn = next(s for s in syms if s.kind == "function")
        assert fn.name == "double"
        assert fn.signature == "(x)"

    def test_async_arrow(self):
        source = "const load = async (id) => id;\n"
        syms = _extract(source)
        fn = next(s for s in syms if s.kind == "function")
        assert fn.is_async is True

    def test_non_arrow_variable_not_indexed(self):
        source = "const x = 42;\n"
        syms = _extract(source)
        assert syms == []


class TestUnavailableParser:
    def test_unknown_language_returns_empty(self):
        # A language with no grammar module mapping — e.g. calling with a
        # nonsense language string — must degrade gracefully, not crash.
        assert JsSymbolExtractor().extract("x", "class Foo {}", "p", "not-a-real-language") == []
