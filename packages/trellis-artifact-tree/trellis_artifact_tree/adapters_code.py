"""Source code as containment, via tree-sitter. Requires the `[code]` extra.

A code containment tree is NOT a symbol table, and the two should not be
merged even though both come from a tree-sitter parse. A symbol table answers
"what is declared, and where is it referenced"; this answers "what contains
what, so a packer can drop or summarise a whole unit coherently". Resource
Explorer already owns symbol extraction with Egeria Advisor reading the result
cross-schema; that arrangement is unaffected by this module.

Nesting comes from the AST directly, which is the whole reason code is the
easiest format here: unlike markdown headings or PDF layout, containment is not
inferred, it is stated. A method is inside its class because the grammar says so.

tree_sitter is imported inside parse(), not at module scope, so importing this
module without the extra installed fails at the point of use with a readable
message rather than at import with a stack trace.
"""
from __future__ import annotations

from dataclasses import dataclass

from trellis_artifact_tree.model import ArtifactTree, Node, Provenance, Rung


@dataclass(frozen=True)
class LanguageSpec:
    """Per-language node types that carry containment.

    Only declaration-like nodes are tracked. Statements and expressions are
    deliberately excluded: a tree containing every AST node would be an AST, not
    a containment tree, and a packer has no use for a rung boundary at an
    if-statement.
    """

    module: str                     # pip module providing the grammar
    kinds: dict[str, str]           # tree-sitter node type -> our node kind
    name_field: str = "name"


SPECS: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        module="tree_sitter_python",
        kinds={"class_definition": "class", "function_definition": "function"},
    ),
    "java": LanguageSpec(
        module="tree_sitter_java",
        kinds={
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "method_declaration": "method",
            "constructor_declaration": "method",
        },
    ),
    "javascript": LanguageSpec(
        module="tree_sitter_javascript",
        kinds={
            "class_declaration": "class",
            "function_declaration": "function",
            "method_definition": "method",
        },
    ),
}

_ALIASES = {
    "py": "python", ".py": "python", "python": "python", "text/x-python": "python",
    "java": "java", ".java": "java", "text/x-java": "java",
    "js": "javascript", ".js": "javascript", "javascript": "javascript",
    "mjs": "javascript", ".mjs": "javascript",
}


class CodeAdapter:
    """One adapter, many languages -- the containment logic is identical and
    only the node-type table differs."""

    name = "code"
    fidelity = "structural"

    def __init__(self, language: str | None = None) -> None:
        # None => resolve per call from the kind passed to parse(). A caller
        # that knows the language can pin it.
        self.language = language

    def handles(self, kind: str) -> bool:
        return _ALIASES.get(kind.lower()) in SPECS

    def _spec(self, kind: str) -> tuple[str, LanguageSpec]:
        lang = self.language or _ALIASES.get(kind.lower(), "")
        if lang not in SPECS:
            raise ValueError(f"code adapter: unsupported language for kind {kind!r}")
        return lang, SPECS[lang]

    def _parser(self, spec: LanguageSpec):
        try:
            import importlib

            from tree_sitter import Language, Parser
        except ImportError as exc:  # pragma: no cover - depends on install
            raise ImportError(
                "the code adapter needs the [code] extra: "
                "pip install 'trellis-artifact-tree[code]'"
            ) from exc
        grammar = importlib.import_module(spec.module)
        return Parser(Language(grammar.language()))

    def parse(self, artifact_id: str, source, provenance: Provenance,
              kind: str = "python") -> ArtifactTree:
        if isinstance(source, str):
            data = source.encode("utf-8")
        elif isinstance(source, (bytes, bytearray)):
            data = bytes(source)
        else:
            raise TypeError(
                f"code adapter needs str or bytes, got {type(source).__name__}"
            )

        _lang, spec = self._spec(kind if self.language is None else self.language)
        tree = self._parser(spec).parse(data)

        root = Node(
            node_id=f"{artifact_id}:root", artifact_id=artifact_id, kind="module",
            title=provenance.source_id,
            rungs={Rung.IDENTIFIERS: provenance.source_id},
        )
        nodes = [root]
        counter = [0]
        ordinals: dict[str, int] = {}

        def visit(ts_node, parent_id: str) -> None:
            our_kind = spec.kinds.get(ts_node.type)
            next_parent = parent_id
            if our_kind:
                name_node = ts_node.child_by_field_name(spec.name_field)
                title = name_node.text.decode("utf-8", "replace") if name_node else ""
                node_id = f"{artifact_id}:c{counter[0]}"
                counter[0] += 1
                ordinal = ordinals.get(parent_id, 0)
                ordinals[parent_id] = ordinal + 1
                body = data[ts_node.start_byte:ts_node.end_byte].decode("utf-8", "replace")
                nodes.append(Node(
                    node_id=node_id, artifact_id=artifact_id, kind=our_kind,
                    title=title, parent_id=parent_id, ordinal=ordinal,
                    span=(ts_node.start_byte, ts_node.end_byte),
                    # FULL is the declaration's own source. IDENTIFIERS is its
                    # name -- enough for a packer to say "this class exists"
                    # when it cannot afford the body. Both free; SUMMARY is a
                    # summariser's job at ingest.
                    rungs={Rung.FULL: body, Rung.IDENTIFIERS: title or our_kind},
                ))
                next_parent = node_id
            for child in ts_node.children:
                visit(child, next_parent)

        visit(tree.root_node, root.node_id)

        from dataclasses import replace
        return ArtifactTree(
            artifact_id=artifact_id,
            provenance=replace(provenance, extraction_fidelity=self.fidelity),
            nodes=tuple(nodes),
        )
