"""Tests for JavaSymbolExtractor (tree-sitter) — AST-ownership-transfer plan Phase 2.

These are real regression tests against RE's confirmed prior failures in the
old regex-based Java extractor: cross-class attribution ("last class wins"),
multi-line signatures silently dropped, @Override-adjacent declarations
silently dropped, no inner-class/Javadoc handling.
"""
from __future__ import annotations

import pytest

from resource_explorer.ingestion.java_symbol_extractor import JavaSymbolExtractor

# Skip the whole module gracefully if tree-sitter-java isn't actually
# importable in this environment (mirrors ASTChunker.is_available()'s
# lenient pattern — this extractor already no-ops rather than crashing).
try:
    import tree_sitter_java  # noqa: F401
    _TREE_SITTER_JAVA_AVAILABLE = True
except ImportError:
    _TREE_SITTER_JAVA_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _TREE_SITTER_JAVA_AVAILABLE, reason="tree-sitter-java not installed"
)


def _extract(source: str) -> list:
    return JavaSymbolExtractor().extract("Test.java", source, "myproj")


class TestBasics:
    def test_class_and_method(self):
        source = "public class Foo {\n    public void bar() {}\n}\n"
        syms = _extract(source)
        cls = next(s for s in syms if s.kind == "class")
        method = next(s for s in syms if s.kind == "method")
        assert cls.name == "Foo"
        assert method.name == "bar"
        assert method.parent_class == "Foo"
        assert method.qualified_name == "Foo.bar"

    def test_is_private(self):
        source = "public class Foo {\n    private int helper() { return 1; }\n}\n"
        syms = _extract(source)
        method = next(s for s in syms if s.kind == "method")
        assert method.is_private is True

    def test_is_public_not_private(self):
        source = "public class Foo {\n    public int helper() { return 1; }\n}\n"
        syms = _extract(source)
        method = next(s for s in syms if s.kind == "method")
        assert method.is_private is False


class TestRegressionCrossClassAttribution:
    """The old regex extractor's confirmed 'last class wins' bug: a single
    mutable current_class variable meant every method in a multi-class file
    got attributed to whichever class the regex scan last matched, regardless
    of which class actually contained it."""

    def test_multiple_classes_correct_attribution(self):
        source = (
            "class A {\n"
            "    void methodA() {}\n"
            "}\n\n"
            "class B {\n"
            "    void methodB() {}\n"
            "}\n"
        )
        syms = _extract(source)
        method_a = next(s for s in syms if s.name == "methodA")
        method_b = next(s for s in syms if s.name == "methodB")
        assert method_a.parent_class == "A"
        assert method_b.parent_class == "B"


class TestRegressionMultiLineSignature:
    """The old regex extractor was single-line-anchored — a method signature
    whose parameters wrapped across multiple lines simply never matched and
    was silently dropped."""

    def test_multiline_signature_not_dropped(self):
        source = (
            "public class Foo {\n"
            "    public double calculate(\n"
            "        double baseCost,\n"
            "        double taxRate\n"
            "    ) {\n"
            "        return baseCost * taxRate;\n"
            "    }\n"
            "}\n"
        )
        syms = _extract(source)
        names = [s.name for s in syms]
        assert "calculate" in names


class TestRegressionAnnotatedDeclaration:
    """The old regex extractor's modifier regex didn't account for an
    annotation directly preceding a declaration, so annotated methods could
    fail to match their modifier pattern and be silently dropped."""

    def test_override_annotated_method_not_dropped(self):
        source = (
            "public class Foo extends Base {\n"
            "    @Override\n"
            "    public void bar() {}\n"
            "}\n"
        )
        syms = _extract(source)
        names = [s.name for s in syms]
        assert "bar" in names


class TestRegressionNestedClass:
    """The old regex extractor had no real class-nesting model (a single
    flat current_class variable) — an inner class's methods would wrongly
    attribute to whichever class regex matched most recently."""

    def test_nested_class_correct_parent_linkage(self):
        source = (
            "public class Outer {\n"
            "    class Inner {\n"
            "        int compute() { return 1; }\n"
            "    }\n"
            "}\n"
        )
        syms = _extract(source)
        inner = next(s for s in syms if s.name == "Inner")
        compute = next(s for s in syms if s.name == "compute")
        assert inner.parent_class == "Outer"
        assert inner.qualified_name == "Outer.Inner"
        assert compute.parent_class == "Inner"
        assert compute.qualified_name == "Inner.compute"


class TestInheritance:
    def test_extends_captured(self):
        source = "public class Child extends Base {\n}\n"
        syms = _extract(source)
        child = next(s for s in syms if s.name == "Child")
        assert child.bases == ["Base"]

    def test_implements_multiple_interfaces(self):
        source = "public class Widget implements Priceable, Serializable {\n}\n"
        syms = _extract(source)
        widget = next(s for s in syms if s.name == "Widget")
        assert widget.bases == ["Priceable", "Serializable"]

    def test_extends_and_implements_combined(self):
        source = "public class Widget extends Base implements Priceable {\n}\n"
        syms = _extract(source)
        widget = next(s for s in syms if s.name == "Widget")
        assert widget.bases == ["Base", "Priceable"]


class TestJavadoc:
    def test_javadoc_captured(self):
        source = (
            "public class Foo {\n"
            "    /**\n"
            "     * Computes the answer.\n"
            "     */\n"
            "    public int compute() { return 42; }\n"
            "}\n"
        )
        syms = _extract(source)
        method = next(s for s in syms if s.name == "compute")
        assert "Computes the answer." in method.docstring

    def test_no_javadoc_is_empty(self):
        source = "public class Foo {\n    public int compute() { return 42; }\n}\n"
        syms = _extract(source)
        method = next(s for s in syms if s.name == "compute")
        assert method.docstring == ""


class TestConstructorsAndComplexity:
    def test_constructor_treated_as_method(self):
        source = "public class Foo {\n    public Foo(int x) {}\n}\n"
        syms = _extract(source)
        ctor = next(s for s in syms if s.name == "Foo" and s.kind == "method")
        assert ctor.parent_class == "Foo"

    def test_complexity_counts_decision_points(self):
        source = (
            "public class Foo {\n"
            "    public int classify(int x) {\n"
            "        if (x > 0) {\n"
            "            return 1;\n"
            "        }\n"
            "        for (int i = 0; i < x; i++) {\n"
            "            x--;\n"
            "        }\n"
            "        return x;\n"
            "    }\n"
            "}\n"
        )
        syms = _extract(source)
        method = next(s for s in syms if s.name == "classify")
        # base 1 + if + for = 3
        assert method.complexity == 3


class TestInterfaceAndEnum:
    def test_interface_kind(self):
        source = "public interface Priceable {\n    double getPrice();\n}\n"
        syms = _extract(source)
        iface = next(s for s in syms if s.kind == "interface")
        assert iface.name == "Priceable"

    def test_enum_kind(self):
        source = "public enum Status {\n    ACTIVE, INACTIVE\n}\n"
        syms = _extract(source)
        enum_sym = next(s for s in syms if s.kind == "enum")
        assert enum_sym.name == "Status"


class TestGracefulDegradation:
    def test_dispatch_via_code_symbol_extractor(self):
        """Confirm the public CodeSymbolExtractor.extract() dispatch actually
        routes language='java' to the tree-sitter path end to end."""
        from resource_explorer.ingestion.code_symbol_extractor import CodeSymbolExtractor
        source = "public class Foo {\n    public void bar() {}\n}\n"
        syms = CodeSymbolExtractor().extract("Foo.java", source, "myproj", "java")
        assert any(s.name == "Foo" for s in syms)
        assert any(s.name == "bar" for s in syms)

    def test_invalid_java_does_not_raise(self):
        syms = _extract("this is not valid java {{{ at all")
        assert isinstance(syms, list)
