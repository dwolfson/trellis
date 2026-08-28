"""Turning source material into trees.

The package boundary matters here. This module defines **the contract** a parse
must satisfy, the **registry** that resolves a source kind to an adapter, and
the two adapters that need nothing beyond the standard library. Adapters that
need tree-sitter, a PDF library, or an office-format reader live in the apps
that already depend on them -- this package never grows a parser dependency.

**Absence of an adapter degrades, it never blocks.** An unrecognised kind falls
back to GenericTextAdapter: one rung, flat blocks, no structure. The artifact is
ingested and usable immediately, and a later adapter improves fidelity without a
migration. Adapters are an optimisation over a working default, not a gate in
front of one. Which path ran is recorded in Provenance.extraction_fidelity, so a
low-confidence extraction stays visible rather than being indistinguishable from
a clean structural parse.

**Two rungs are free; one is not.** An adapter can emit FULL (the span's own
text) and IDENTIFIERS (titles, names -- structure it already computed) without
any model at all. SUMMARY needs a summariser, runs at ingest rather than on the
hot path, and is deliberately not an adapter's job.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Protocol, runtime_checkable

from trellis_artifact_tree.model import ArtifactTree, Node, Provenance, Rung


@runtime_checkable
class Adapter(Protocol):
    name: str
    fidelity: str

    def handles(self, kind: str) -> bool: ...

    def parse(self, artifact_id: str, text: str, provenance: Provenance) -> ArtifactTree: ...


def _finish(
    artifact_id: str, provenance: Provenance, fidelity: str, nodes: list[Node]
) -> ArtifactTree:
    """Stamp fidelity from the adapter that actually ran, not from the caller.

    The caller supplies provenance describing the SOURCE; only the adapter knows
    whether structure was recovered or fallen back on.
    """
    return ArtifactTree(
        artifact_id=artifact_id,
        provenance=replace(provenance, extraction_fidelity=fidelity),
        nodes=tuple(nodes),
    )


class GenericTextAdapter:
    """The floor. Never fails on content, and every other adapter is measured
    against it.

    Blank-line-separated blocks under a single root. No nesting is claimed,
    because none was recovered -- a flat tree is an honest representation of
    "we could not read the structure", where a fabricated hierarchy would not be.
    """

    name = "generic-text"
    fidelity = "generic-text"

    def handles(self, kind: str) -> bool:
        return True  # the fallback handles everything

    def parse(self, artifact_id: str, text: str, provenance: Provenance) -> ArtifactTree:
        root = Node(f"{artifact_id}:root", artifact_id, "document",
                    title=provenance.source_id)
        nodes = [root]
        cursor, ordinal = 0, 0
        for block in re.split(r"\n\s*\n", text):
            start = text.find(block, cursor)
            if not block.strip():
                cursor = start + len(block) if start >= 0 else cursor
                continue
            cursor = start + len(block)
            nodes.append(Node(
                node_id=f"{artifact_id}:b{ordinal}", artifact_id=artifact_id,
                kind="block", parent_id=root.node_id, ordinal=ordinal,
                span=(start, cursor), rungs={Rung.FULL: block},
            ))
            ordinal += 1
        return _finish(artifact_id, provenance, self.fidelity, nodes)


class MarkdownAdapter:
    """ATX headings as containment. Stdlib only -- no markdown library needed to
    recover the one thing the tree cares about.

    Heading LEVELS, not document order, define nesting, and levels skip in real
    documents (an `##` followed by `####`). A stack keyed on level handles that
    without inventing intermediate nodes: the `####` simply becomes a child of
    the `##`, which is what the author meant.

    Content before the first heading is a preamble node, not dropped. Losing it
    silently is the classic markdown-parsing bug, and it is usually the abstract.
    """

    name = "markdown"
    fidelity = "structural"
    _HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)

    def handles(self, kind: str) -> bool:
        return kind.lower() in {"markdown", "md", "text/markdown", ".md"}

    def parse(self, artifact_id: str, text: str, provenance: Provenance) -> ArtifactTree:
        root = Node(f"{artifact_id}:root", artifact_id, "document",
                    title=provenance.source_id,
                    rungs={Rung.IDENTIFIERS: provenance.source_id})
        nodes = [root]
        matches = list(self._HEADING.finditer(text))

        preamble_end = matches[0].start() if matches else len(text)
        preamble = text[:preamble_end]
        counter = 0
        if preamble.strip():
            nodes.append(Node(
                node_id=f"{artifact_id}:n{counter}", artifact_id=artifact_id,
                kind="preamble", parent_id=root.node_id, ordinal=0,
                span=(0, preamble_end), rungs={Rung.FULL: preamble.strip()},
            ))
            counter += 1

        # level -> node_id of the most recent heading at that level
        stack: dict[int, str] = {}
        # Seeded past the preamble when there is one: otherwise the preamble and
        # the first top-level heading both claim ordinal 0 under the root, and
        # sibling order is then decided by node_id tiebreak rather than by the
        # document. Correct today by accident, wrong the moment ids change.
        sibling_ordinals: dict[str, int] = {root.node_id: counter}
        for i, m in enumerate(matches):
            level, title = len(m.group(1)), m.group(2).strip()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.start():end]

            parent = root.node_id
            for lvl in sorted((l for l in stack if l < level), reverse=True):
                parent = stack[lvl]
                break

            ordinal = sibling_ordinals.get(parent, 0)
            sibling_ordinals[parent] = ordinal + 1

            node_id = f"{artifact_id}:n{counter}"
            counter += 1
            nodes.append(Node(
                node_id=node_id, artifact_id=artifact_id, kind="section",
                title=title, parent_id=parent, ordinal=ordinal,
                span=(m.start(), end),
                # FULL from the span, IDENTIFIERS from the title. Both free.
                # SUMMARY is a summariser's job, at ingest, not here.
                rungs={Rung.FULL: body.strip(), Rung.IDENTIFIERS: title},
            ))
            stack[level] = node_id
            # A deeper heading later cannot nest under a sibling that has closed.
            for deeper in [l for l in stack if l > level]:
                del stack[deeper]

        return _finish(artifact_id, provenance, self.fidelity, nodes)


class AdapterRegistry:
    """Resolves a source kind to an adapter, falling back rather than failing.

    resolve() never raises and never returns None: an unknown kind is a normal
    condition, not an error, and the caller should not have to write the
    fallback branch every time.
    """

    def __init__(self, adapters: list[Adapter] | None = None,
                 fallback: Adapter | None = None) -> None:
        self._adapters = list(adapters) if adapters is not None else [MarkdownAdapter()]
        self._fallback = fallback or GenericTextAdapter()

    def register(self, adapter: Adapter) -> None:
        """Later registrations win: an app registering a richer markdown adapter
        should not have to unregister the built-in one first."""
        self._adapters.insert(0, adapter)

    def resolve(self, kind: str) -> Adapter:
        for adapter in self._adapters:
            if adapter.handles(kind):
                return adapter
        return self._fallback

    def parse(self, artifact_id: str, kind: str, text: str,
              provenance: Provenance) -> ArtifactTree:
        return self.resolve(kind).parse(artifact_id, text, provenance)
