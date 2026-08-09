"""Tests for GoSymbolExtractor (tree-sitter) — replaces the old regex-based
Go path in code_symbol_extractor.py, mirroring the Java tree-sitter upgrade
(AST-ownership-transfer plan Phase 2).

Real regression coverage against the old regex extractor's confirmed weak
spots: multi-line receiver/parameter/return clauses, and correct receiver-
type extraction for both pointer and value receivers.
"""
from __future__ import annotations

import pytest

from resource_explorer.ingestion.go_symbol_extractor import GoSymbolExtractor

try:
    import tree_sitter_go  # noqa: F401
    _TREE_SITTER_GO_AVAILABLE = True
except ImportError:
    _TREE_SITTER_GO_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _TREE_SITTER_GO_AVAILABLE, reason="tree-sitter-go not installed"
)


def _extract(source: str) -> list:
    return GoSymbolExtractor().extract("test.go", source, "myproj")


class TestTypeDeclarations:
    def test_struct_becomes_class_kind(self):
        source = "package main\n\ntype Router struct {\n\troutes map[string]string\n}\n"
        syms = _extract(source)
        struct = next(s for s in syms if s.name == "Router")
        assert struct.kind == "class"

    def test_interface(self):
        source = "package main\n\ntype Handler interface {\n\tHandle(s string) string\n}\n"
        syms = _extract(source)
        iface = next(s for s in syms if s.name == "Handler")
        assert iface.kind == "interface"

    def test_type_alias_not_indexed(self):
        source = "package main\n\ntype ID = string\n"
        syms = _extract(source)
        assert syms == []


class TestFunctions:
    def test_free_function(self):
        source = "package main\n\nfunc NewRouter() *Router {\n\treturn &Router{}\n}\n"
        syms = _extract(source)
        fn = next(s for s in syms if s.kind == "function")
        assert fn.name == "NewRouter"
        assert fn.return_type == "*Router"

    def test_multiline_signature(self):
        """The old regex was single-line-anchored — this must not be
        silently dropped."""
        source = (
            "package main\n\n"
            "func LongSig(\n\ta string,\n\tb int,\n) error {\n\treturn nil\n}\n"
        )
        syms = _extract(source)
        fn = next((s for s in syms if s.kind == "function"), None)
        assert fn is not None
        assert fn.name == "LongSig"

    def test_multiple_return_values(self):
        source = "package main\n\nfunc Parse(s string) (int, error) {\n\treturn 0, nil\n}\n"
        syms = _extract(source)
        fn = next(s for s in syms if s.kind == "function")
        assert "int" in fn.return_type and "error" in fn.return_type


class TestMethods:
    def test_pointer_receiver(self):
        source = (
            "package main\n\n"
            "func (r *Router) AddRoute(path string) error {\n\treturn nil\n}\n"
        )
        syms = _extract(source)
        m = next(s for s in syms if s.kind == "method")
        assert m.name == "AddRoute"
        assert m.parent_class == "Router"
        assert m.qualified_name == "Router.AddRoute"

    def test_value_receiver(self):
        """A non-pointer receiver — the old regex's .lstrip('*') heuristic
        happened to work here too, but tree-sitter reads the grammar's own
        pointer_type/type_identifier node shape directly instead."""
        source = "package main\n\nfunc (r Router) Name() string {\n\treturn \"\"\n}\n"
        syms = _extract(source)
        m = next(s for s in syms if s.kind == "method")
        assert m.parent_class == "Router"


class TestUnavailableParser:
    def test_extract_never_raises_on_bad_source(self):
        # Malformed Go source shouldn't crash — tree-sitter is resilient to
        # parse errors, and any exception is caught internally.
        result = GoSymbolExtractor().extract("x.go", "not even close to go {{{", "p")
        assert isinstance(result, list)
