"""What chunk size a slice of corpus actually wants, measured rather than chosen.

Replaces two hand-maintained tunings that cannot re-derive themselves: Egeria
Advisor's four path-bounded egeria-docs collections with hand-picked chunk sizes,
and Resource Explorer's one fixed size per format applied to every repo. See
docs/corpus-profiler-design.md.

**Pick the unit first, then size to it.** This rule is on its third version and
each revision came from measurement, not review:

  v1  size to the p75 UNIT (section). Gives 340/164/356 tokens for egeria-docs
      concepts/types/general against EA's hand-picked 768/1024/1536 -- wrong
      magnitude, and wrong ordering.
  v2  size to the p75 DOCUMENT. Fits egeria-docs within ~20% on all three, and
      fails outright on code: pyegeria's p75 document is 32,467 tokens, which is
      a module, not a chunk size.
  v3  decide WHICH unit is coherent, then size to that. Units-per-document is
      the discriminator, and the tree already carries it.

Around one unit per document means the document IS the unit -- an egeria-docs
concept page is one section. Many means the unit is sub-document: a function, a
template. Sizing a slice to the wrong unit looks principled and optimises for
nothing.

It also explains a disagreement neither app documents. **RE's constants track
p75 unit size** (markdown_docs=384 against a measured 340; python_code=512
against 495 and 480). **EA's track p75 document size** (768 against 905). Neither
is wrong; they chunk different things because they answer different retrieval
questions. A profiler picking one rule for both would silently break whichever
app it did not resemble.

**It reports; it does not enable.** Changing a chunk size means re-embedding a
corpus, so the decision stays with a person.
"""
from __future__ import annotations

from dataclasses import dataclass

from trellis_artifact_tree.model import ArtifactTree, Rung

#: Rough chars-per-token. Deliberately crude: the derived number feeds a human
#: decision and a re-embed, not a hard budget, and a real tokenizer would make
#: this module heavier than the thing it measures. The packer counts characters
#: for the same reason.
CHARS_PER_TOKEN = 4

#: Above this many units per document, the unit is sub-document. One means the
#: document is a single unit; the boundary sits just above it so a document with
#: an occasional second section still counts as document-shaped.
UNIT_IS_SUBDOCUMENT_ABOVE = 2.0

#: EA's three collections all use 19.5% overlap. It is not independently tuned
#: there, so it is not independently derived here.
OVERLAP_RATIO = 0.195


@dataclass(frozen=True)
class SliceProfile:
    """What one (repo, path boundary, format) slice measures."""

    slice_key: str
    documents: int
    median_units_per_doc: float
    p75_unit_tokens: int
    p75_doc_tokens: int

    @property
    def unit_is_document(self) -> bool:
        return self.median_units_per_doc <= UNIT_IS_SUBDOCUMENT_ABOVE

    @property
    def chunk_size(self) -> int:
        """Tokens. The p75 of whichever unit is coherent for this slice."""
        return self.p75_doc_tokens if self.unit_is_document else self.p75_unit_tokens

    @property
    def overlap(self) -> int:
        return int(self.chunk_size * OVERLAP_RATIO)

    @property
    def basis(self) -> str:
        return "document" if self.unit_is_document else "unit"

    @property
    def summary(self) -> str:
        return (
            f"{self.slice_key}: {self.documents} docs, "
            f"{self.median_units_per_doc:.1f} units/doc -> size to the "
            f"{self.basis} -> chunk {self.chunk_size}, overlap {self.overlap}"
        )


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))]


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def profile_trees(slice_key: str, trees: list[ArtifactTree],
                  *, content_kinds: frozenset[str] | None = None) -> SliceProfile:
    """Measure a slice from its containment trees.

    A pure function over trees that already exist: no re-parse, no fetch. That
    is what makes re-profiling cheap enough to run whenever ingestion does.
    """
    unit_sizes: list[int] = []
    doc_sizes: list[int] = []
    units_per_doc: list[float] = []

    for tree in trees:
        sizes = [
            len(text) for node in tree.nodes
            if (text := (node.rungs.get(Rung.FULL) or "").strip())
            and (content_kinds is None or node.kind in content_kinds)
        ]
        if not sizes:
            # A document with nothing to measure contributes nothing rather
            # than a zero. Zeros would drag every percentile toward a size no
            # real document has.
            continue
        unit_sizes.extend(sizes)
        doc_sizes.append(sum(sizes))
        units_per_doc.append(float(len(sizes)))

    return SliceProfile(
        slice_key=slice_key,
        documents=len(doc_sizes),
        median_units_per_doc=_median(units_per_doc),
        p75_unit_tokens=_percentile(unit_sizes, 0.75) // CHARS_PER_TOKEN,
        p75_doc_tokens=_percentile(doc_sizes, 0.75) // CHARS_PER_TOKEN,
    )


def compare_to(profile: SliceProfile, current_chunk_size: int) -> str:
    """How a slice's measured want compares with what it is actually given.

    Phrased as a difference rather than a verdict: the current value may have
    been chosen for a reason this measurement cannot see, and the profiler is
    not entitled to overrule it.
    """
    want = profile.chunk_size
    if not current_chunk_size or not want:
        return "no comparison — one side is unknown"
    ratio = want / current_chunk_size
    if 0.8 <= ratio <= 1.25:
        return f"close: measured {want} against configured {current_chunk_size}"
    direction = "larger" if ratio > 1 else "smaller"
    return (
        f"measured {want} is {ratio:.1f}x {direction} than the configured "
        f"{current_chunk_size} — sized to the {profile.basis}"
    )
