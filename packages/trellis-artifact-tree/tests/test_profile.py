"""The corpus profiler.

The rule under test is on its third version and each revision came from
measurement rather than review, so the tests pin the two real corpora that
falsified the earlier two.
"""
from __future__ import annotations

from trellis_artifact_tree.model import ArtifactTree, Node, Provenance, Rung
from trellis_artifact_tree.profile import (
    SliceProfile,
    compare_to,
    profile_trees,
)

PROV = Provenance(source_kind="repo", source_id="x", fetched_at="t")


def _tree(aid: str, unit_chars: list[int], kind: str = "section") -> ArtifactTree:
    nodes = [Node(f"{aid}:r", aid, "document")]
    nodes += [
        Node(f"{aid}:n{i}", aid, kind, parent_id=f"{aid}:r", ordinal=i,
             rungs={Rung.FULL: "x" * n})
        for i, n in enumerate(unit_chars)
    ]
    return ArtifactTree(aid, PROV, tuple(nodes))


class TestUnitChoice:
    def test_one_unit_per_document_sizes_to_the_document(self):
        """An egeria-docs concept page IS one section. Sizing to the unit here
        gave 340 tokens against a hand-picked 768 — wrong magnitude."""
        trees = [_tree(f"a{i}", [3600]) for i in range(20)]
        p = profile_trees("concepts", trees)
        assert p.unit_is_document and p.basis == "document"
        assert p.chunk_size == p.p75_doc_tokens

    def test_many_units_per_document_sizes_to_the_unit(self):
        """pyegeria's p75 document is 32,467 tokens. That is a module, not a
        chunk size — which is what falsified the second version of the rule."""
        trees = [_tree(f"b{i}", [2000] * 23) for i in range(10)]
        p = profile_trees("pyegeria", trees)
        assert not p.unit_is_document and p.basis == "unit"
        assert p.chunk_size == p.p75_unit_tokens
        assert p.chunk_size < p.p75_doc_tokens

    def test_the_boundary_sits_just_above_one(self):
        """A document with an occasional second section is still
        document-shaped; the discriminator must not flip on it."""
        trees = [_tree("c1", [1000]), _tree("c2", [1000, 900]), _tree("c3", [1000])]
        assert profile_trees("mixed", trees).unit_is_document


class TestDerivation:
    def test_overlap_is_a_ratio_not_a_separate_decision(self):
        """EA's three collections are all 19.5% — it was never independently
        tuned there, so it is not independently derived here."""
        p = SliceProfile("s", 10, 1.0, 300, 1000)
        assert p.overlap == int(p.chunk_size * 0.195)

    def test_empty_documents_do_not_drag_the_percentiles(self):
        """A zero-content document contributes nothing rather than a zero.
        Zeros would pull every percentile toward a size no real document has."""
        trees = [_tree(f"d{i}", [4000]) for i in range(10)] + [_tree("empty", [])]
        p = profile_trees("s", trees)
        assert p.documents == 10
        assert p.p75_doc_tokens == 1000

    def test_a_slice_with_nothing_measures_zero_not_a_crash(self):
        p = profile_trees("s", [])
        assert p.documents == 0 and p.chunk_size == 0


class TestComparison:
    def test_it_reports_a_difference_not_a_verdict(self):
        """The configured value may have been chosen for a reason this
        measurement cannot see. The profiler is not entitled to overrule it."""
        assert "close" in compare_to(SliceProfile("s", 179, 1.0, 340, 931), 768)
        assert "close" in compare_to(SliceProfile("s", 75, 23.0, 495, 32467), 512)

    def test_a_real_divergence_is_named_with_its_basis(self):
        msg = compare_to(SliceProfile("templates", 960, 20.0, 29, 1728), 384)
        assert "smaller" in msg and "unit" in msg

    def test_an_unknown_side_is_not_guessed(self):
        assert "no comparison" in compare_to(SliceProfile("s", 1, 1.0, 0, 0), 384)


class TestReproducesTheMeasuredCorpora:
    """The two runs that drove §7 of the design, as regression cases."""

    def test_egeria_docs_concepts(self):
        p = SliceProfile("concepts", 179, 1.0, 340, 931)
        assert p.chunk_size == 931, "sizes to the document"

    def test_egeria_python_pyegeria(self):
        p = SliceProfile("pyegeria", 75, 23.0, 495, 32467)
        assert p.chunk_size == 495, "sizes to the unit, not the 32k module"

    def test_dr_egeria_templates_are_the_sharpest_case(self):
        """p75 unit of 29 tokens across 20 units per document. Neither RE's 384
        nor EA's 768 fits it — the clearest argument for deriving per slice."""
        p = SliceProfile("sample-data", 960, 20.0, 29, 1728)
        assert p.chunk_size == 29 and p.basis == "unit"
