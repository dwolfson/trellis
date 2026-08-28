"""Trees that parsed without failing, and still say nothing useful.

A conversion can succeed, produce a valid tree, and be worthless -- and from the
outside that looks identical to a document that is simply short. Two distinct
shapes matter, and conflating them (an earlier version of this analysis did)
loses the more useful one:

**Near-empty** -- almost no text recovered. For a PDF this is the signature of a
rasterised page: a scanned document, or a diagram exported as an image rather
than as vector text. Nothing downstream can help, because there is nothing there.
The fix is OCR (`PdfAdapter(ocr=True, ocr_engine="easyocr")`), and this is the
only reliable way to learn you needed it -- Docling reports no error.

**Structureless** -- text recovered, no containment. A flat document: an
OmniGraffle diagram whose node labels extract fine but form no hierarchy, or
generic-text fallback output. NOT a failure. But a packer cannot cut it by depth
(`ArtifactTree.cut()` returns everything at once), so a large structureless tree
is all-or-nothing for budgeting, which is worth knowing before it surprises
someone.

**Thresholds come from measurement, not intuition.** Across 18 real PDFs from
egeria-docs the *lowest* content was 15 nodes / 1,196 characters, in a genuinely
terse slide deck. Near-empty is set an order of magnitude below that floor, so it
flags extraction failure rather than brevity. No artifact in that corpus trips it
-- which is the point: a detector tuned on a corpus with no failures should
report none, or it is measuring the wrong thing.
"""
from __future__ import annotations

from dataclasses import dataclass

from trellis_artifact_tree.model import ArtifactTree, Rung

# An order of magnitude below the observed floor (1196 chars).
NEAR_EMPTY_CHARS = 200

# Kinds that carry containment rather than content.
_STRUCTURAL_KINDS = frozenset({"section", "class", "module", "interface", "enum"})


# Fidelities where sparse text may mean a FAILED extraction rather than a short
# document. "inferred" is Docling's -- a PDF states layout, not structure, so a
# rasterised page yields nothing and looks identical to a terse one.
# "generic-text" is the no-adapter fallback. For a structural parse (markdown,
# code, HTML) sparse text means the file is short, which is not a finding.
OCR_RELEVANT_FIDELITIES = frozenset({"inferred", "generic-text"})


@dataclass(frozen=True)
class TreeDiagnosis:
    artifact_id: str
    content_nodes: int
    content_chars: int
    structural_nodes: int
    fidelity: str = "structural"

    @property
    def near_empty(self) -> bool:
        """Characters, not node count.

        Node count looked like a reasonable second signal and is wrong across
        formats: egeria-docs concept pages have a MEDIAN of one content node
        each and are perfectly good documents. A rule of "<= 1 node" flagged
        every one of them. Text volume is the thing that distinguishes a failed
        extraction from a terse document; structure is a separate question,
        answered below.
        """
        return self.content_chars < NEAR_EMPTY_CHARS

    @property
    def structureless(self) -> bool:
        """Content but no containment. Only meaningful when there IS content --
        a near-empty tree is trivially structureless and saying both would bury
        the finding that matters."""
        return not self.near_empty and self.structural_nodes == 0

    @property
    def actionable(self) -> bool:
        """Whether near-emptiness is worth reporting.

        Measured across 15,983 artifacts: 20% are near-empty, and almost all
        are short markdown stubs in egeria-workspaces and egeria-docs -- 49% of
        one corpus. Nothing can be done about a genuinely short file, and
        reporting 3,177 of them would bury the case that matters. Meanwhile 0
        of 18 PDFs tripped it, which is the correct answer for a corpus whose
        PDFs all converted.

        This is the same precision failure the collection-drift check made
        first time round, caught before shipping rather than after.
        """
        return self.fidelity in OCR_RELEVANT_FIDELITIES

    @property
    def finding(self) -> str:
        if self.near_empty and not self.actionable:
            # A short markdown file is short. Nothing to suggest.
            return ""
        if self.near_empty:
            return (
                f"near-empty: {self.content_chars} char(s) in "
                f"{self.content_nodes} node(s) — likely a rasterised or scanned "
                f"source; OCR would be needed to read it"
            )
        if self.structureless:
            return (
                f"structureless: {self.content_chars} char(s) recovered but no "
                f"containment — usable, but a packer cannot cut it by depth"
            )
        return ""


def diagnose(tree: ArtifactTree) -> TreeDiagnosis:
    content_nodes = content_chars = structural = 0
    for node in tree.nodes:
        text = (node.rungs.get(Rung.FULL) or "").strip()
        if text:
            content_nodes += 1
            content_chars += len(text)
        if node.kind in _STRUCTURAL_KINDS:
            structural += 1
    return TreeDiagnosis(
        artifact_id=tree.artifact_id, content_nodes=content_nodes,
        content_chars=content_chars, structural_nodes=structural,
        fidelity=tree.provenance.extraction_fidelity,
    )
