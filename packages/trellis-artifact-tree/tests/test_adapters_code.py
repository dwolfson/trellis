"""Code adapter — containment is stated by the grammar, not inferred."""
from __future__ import annotations

import pytest

from trellis_artifact_tree.adapters_code import CodeAdapter
from trellis_artifact_tree.model import Provenance, Rung

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_python")

PROV = Provenance(source_kind="repo", source_id="a.py", fetched_at="t")

PY = """class A:
    def m(self):
        pass
    def n(self):
        pass

def top():
    return 1
"""


class TestPythonContainment:
    def _tree(self):
        return CodeAdapter().parse("x", PY, PROV, kind="py")

    def test_methods_nest_under_their_class(self):
        t = self._tree()
        by = {n.title: n for n in t.nodes if n.title}
        assert by["m"].parent_id == by["A"].node_id
        assert by["n"].parent_id == by["A"].node_id

    def test_module_level_function_is_a_sibling_of_the_class(self):
        t = self._tree()
        by = {n.title: n for n in t.nodes if n.title}
        assert by["top"].parent_id == t.root.node_id
        assert by["A"].parent_id == t.root.node_id

    def test_sibling_ordinals_follow_source_order(self):
        t = self._tree()
        by = {n.title: n for n in t.nodes if n.title}
        assert by["m"].ordinal < by["n"].ordinal
        assert by["A"].ordinal < by["top"].ordinal

    def test_only_declarations_are_tracked(self):
        """A tree containing every AST node would be an AST. A packer has no
        use for a rung boundary at an if-statement."""
        t = self._tree()
        assert {n.kind for n in t.nodes} == {"module", "class", "function"}

    def test_free_rungs_only(self):
        t = self._tree()
        cls = next(n for n in t.nodes if n.title == "A")
        assert cls.rungs[Rung.IDENTIFIERS] == "A"
        assert "def m" in cls.rungs[Rung.FULL]
        assert Rung.SUMMARY not in cls.rungs

    def test_spans_point_into_the_source(self):
        t = self._tree()
        cls = next(n for n in t.nodes if n.title == "A")
        assert PY[cls.span[0]:cls.span[1]].startswith("class A")


class TestOtherLanguages:
    def test_java(self):
        t = CodeAdapter().parse("y", "public class Foo { void bar() {} }", PROV, kind="java")
        assert [(n.kind, n.title) for n in t.nodes if n.title != "a.py"] == [
            ("class", "Foo"), ("method", "bar"),
        ]

    def test_javascript(self):
        pytest.importorskip("tree_sitter_javascript")
        t = CodeAdapter().parse("z", "class C { m() {} }\nfunction f() {}", PROV, kind="js")
        kinds = [(n.kind, n.title) for n in t.nodes if n.kind != "module"]
        assert ("class", "C") in kinds and ("function", "f") in kinds


class TestContract:
    def test_handles_known_extensions(self):
        a = CodeAdapter()
        assert a.handles("py") and a.handles(".java") and a.handles("JS")
        assert not a.handles("pdf") and not a.handles("markdown")

    def test_bytes_are_accepted(self):
        t = CodeAdapter().parse("x", PY.encode(), PROV, kind="py")
        assert any(n.title == "A" for n in t.nodes)

    def test_wrong_type_fails_loudly(self):
        with pytest.raises(TypeError):
            CodeAdapter().parse("x", 42, PROV, kind="py")

    def test_unsupported_language_is_explicit(self):
        with pytest.raises(ValueError, match="unsupported language"):
            CodeAdapter().parse("x", "code", PROV, kind="cobol")

    def test_empty_source_still_yields_a_valid_tree(self):
        t = CodeAdapter().parse("x", "", PROV, kind="py")
        assert len(t.nodes) == 1 and t.root.kind == "module"
