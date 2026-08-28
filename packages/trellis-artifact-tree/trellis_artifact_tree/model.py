"""The containment tree — one parse, two consumers.

Chunk size and rung boundaries are DIFFERENT AXES, and conflating them is the
mistake this model exists to prevent. Chunk size is a tuned parameter driven by
artifact category and content profile, because retrieval quality improves when
chunk size matches content style. Rung boundaries are a containment question: a
structural unit can contain several retrieval chunks. Neither derives from the
other.

So: parse once, emit a tree. Retrieval chunks are its leaves, sized by profile.
Compression rungs are cuts across it at different depths. One parse generates
both, and the tree is the format-independence boundary -- a PDF, a docx, a
markdown file and a source file all arrive here as the same shape, so everything
downstream is written against the tree and never against a format.

See docs/context-compilation-design.md sections 15 and 21.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Rung(IntEnum):
    """The compression ladder, ordered coarsest-last.

    IntEnum so a packer can compare and step: FULL < SUMMARY < IDENTIFIERS
    reads as increasing compression, and `min(available)` is the richest rung
    on hand. Values are spaced so a rung can be inserted between two existing
    ones without renumbering anything already stored.
    """

    FULL = 0
    SUMMARY = 10
    IDENTIFIERS = 20

    @property
    def is_lossy(self) -> bool:
        return self is not Rung.FULL


class TreeError(ValueError):
    """A tree that cannot be trusted downstream. Raised at build time rather
    than discovered by a packer mid-compile."""


@dataclass(frozen=True)
class Provenance:
    """The envelope, captured at ingest.

    Retrofitting provenance onto already-embedded material is painful and often
    impossible, which is why this is required rather than optional.

    `source_timestamp` and `fetched_at` are deliberately separate: when the fact
    was true (Egeria's own timestamp, where there is one) versus when we read it
    (staleness). Collapsing them loses the ability to tell an old fact from a
    stale read, which is the distinction RE's stale-but-labelled policy rests on.
    """

    source_kind: str                    # "repo" | "egeria" | "pdf" | ...
    source_id: str                      # repo slug, Egeria GUID, path
    fetched_at: str                     # ISO-8601, when WE read it
    source_version: str = ""            # Egeria element version, git sha, etag
    source_timestamp: str = ""          # ISO-8601, when the fact was true
    # "structural" when an adapter understood the format; "generic-text" when
    # it fell back. Absence of an adapter must degrade, never block -- so this
    # records which happened, and it reaches the manifest and the answer's
    # citations. A low-confidence extraction should be visible rather than
    # indistinguishable from a clean structural parse.
    extraction_fidelity: str = "structural"


@dataclass(frozen=True)
class Node:
    """One containment unit. Not a chunk, and not necessarily a rung boundary.

    `span` is a byte or character range into the artifact's source text, or None
    for synthetic nodes (an artifact root that no single span covers).
    """

    node_id: str
    artifact_id: str
    kind: str                           # "document" | "section" | "class" | ...
    title: str = ""
    parent_id: str | None = None
    ordinal: int = 0                    # sibling order, stable across reparses
    span: tuple[int, int] | None = None
    # rung -> rendered text at that resolution. FULL is usually derived from
    # `span` rather than stored; coarser rungs are PRECOMPUTED AT INGEST because
    # summarising on the hot path is too slow and too expensive at the volume a
    # packer needs.
    rungs: dict[Rung, str] = field(default_factory=dict)
    # Leaves reference retrieval chunks by id. This package deliberately does
    # not own the chunks or their vectors -- they live in trellis-vectorstore,
    # in the same Postgres, joined at read.
    chunk_refs: tuple[str, ...] = ()

    @property
    def is_leaf_candidate(self) -> bool:
        return bool(self.chunk_refs)


@dataclass(frozen=True)
class ArtifactTree:
    artifact_id: str
    provenance: Provenance
    nodes: tuple[Node, ...]

    def __post_init__(self) -> None:
        validate(self.nodes, self.artifact_id)

    @property
    def root(self) -> Node:
        return next(n for n in self.nodes if n.parent_id is None)

    def by_id(self) -> dict[str, Node]:
        return {n.node_id: n for n in self.nodes}

    def children(self, node_id: str) -> list[Node]:
        return sorted(
            (n for n in self.nodes if n.parent_id == node_id),
            key=lambda n: (n.ordinal, n.node_id),
        )

    def cut(self, depth: int) -> list[Node]:
        """The rung boundary at a given depth: every node at exactly `depth`,
        plus any shallower leaf that has no children to descend into.

        A cut is what a packer degrades to -- not a filter over nodes, which is
        why shallow leaves are included. Dropping them would silently lose
        content that simply has no deeper structure.
        """
        index = self.by_id()

        def depth_of(node: Node) -> int:
            d, cur = 0, node
            while cur.parent_id is not None:
                cur = index[cur.parent_id]
                d += 1
            return d

        has_child = {n.parent_id for n in self.nodes if n.parent_id is not None}
        out = [
            n for n in self.nodes
            if depth_of(n) == depth
            or (depth_of(n) < depth and n.node_id not in has_child)
        ]
        return sorted(out, key=lambda n: (depth_of(n), n.ordinal, n.node_id))

    def best_rung(self, node_id: str, budget_rung: Rung) -> tuple[Rung, str] | None:
        """The richest rung that is still compressed enough for `budget_rung`.

        "Richest" and "compressed enough" pull in opposite directions, so
        precisely: of the rungs at least as coarse as the budget, return the
        least coarse. A node holding FULL and SUMMARY, asked for a SUMMARY
        budget, gives SUMMARY -- not FULL, which would blow the budget.

        Returns None when the node has nothing coarse enough. A packer that
        silently exceeds its budget defeats every other guarantee, so the
        caller must decide whether to drop the node or descend into children
        that may have coarser rungs of their own.
        """
        node = self.by_id()[node_id]
        candidates = sorted(r for r in node.rungs if r >= budget_rung)
        if not candidates:
            return None
        return candidates[0], node.rungs[candidates[0]]


def validate(nodes: tuple[Node, ...] | list[Node], artifact_id: str) -> None:
    """Raise TreeError on a tree a packer could not walk safely.

    Checked at construction because every one of these failures surfaces
    downstream as something far harder to read: a cut that silently omits a
    subtree, or a walk that does not terminate.
    """
    if not nodes:
        raise TreeError(f"{artifact_id}: tree has no nodes")

    ids = [n.node_id for n in nodes]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise TreeError(f"{artifact_id}: duplicate node_id(s) {sorted(dupes)}")

    id_set = set(ids)
    foreign = {n.artifact_id for n in nodes} - {artifact_id}
    if foreign:
        raise TreeError(f"{artifact_id}: nodes from other artifact(s) {sorted(foreign)}")

    orphans = sorted(
        n.node_id for n in nodes
        if n.parent_id is not None and n.parent_id not in id_set
    )
    if orphans:
        raise TreeError(f"{artifact_id}: node(s) {orphans} reference a missing parent")

    # Cycles before the root count, deliberately. A pure cycle has no root, so
    # checking root count first reports "expected exactly one root, found 0" --
    # true, useless, and pointing at the wrong thing. Same for orphans above.
    index = {n.node_id: n for n in nodes}
    limit = len(nodes) + 1
    for node in nodes:
        seen, cur, steps = {node.node_id}, node, 0
        while cur.parent_id is not None:
            steps += 1
            if steps > limit or cur.parent_id in seen:
                raise TreeError(f"{artifact_id}: cycle through node {node.node_id!r}")
            seen.add(cur.parent_id)
            cur = index[cur.parent_id]

    roots = [n for n in nodes if n.parent_id is None]
    if len(roots) != 1:
        raise TreeError(
            f"{artifact_id}: expected exactly one root, found {len(roots)}"
        )
