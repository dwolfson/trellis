"""Read the Dr.Egeria documents that DEFINE RE's Survey Definitions.

`repo_survey_types.csv` is a specification of what surveys are needed. These
documents are the definitions: they carry step order, guards, request
parameters and descriptions, none of which the CSV has a column for. Anything
that needs to know what a definition actually says has to read them, and there
is one parser for that here rather than one per caller — the same reason
`annotation_props.py` exists.

**The Link section is parsed separately from the Create section, and neither
is derived from the other.** Every step name appears once in its
`Create Governance Action Process Step` block and twice more in the
`Link ... Process Step` commands. Reading steps from the links would triple
them and would make the step list depend on the link structure — which is the
thing that goes wrong (Dr.Egeria's Link commands are not idempotent) and needs
detecting. Reading links from the step order would assume the chain is linear,
which is the assumption this module exists to stop making.

**Guards are read, not assumed.** `NextGovernanceActionProcessStep` is
MULTI_LINK by design: several next-steps under different guards is how Egeria
expresses branching. `Any` means unconditional and is the only guard RE's
generator emits today, but a hand-authored branch is legitimate and must
survive everything that reads these files.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

#: Command headings, matched on the whole stripped line. `## Create Governance
#: Action Process` is a prefix of the step heading, so a loose match would
#: register every step as the process.
CREATE_STEP = "## Create Governance Action Process Step"
CREATE_PROCESS = "## Create Governance Action Process"
LINK_FIRST = "## Link First Process Step"
LINK_NEXT = "## Link Next Process Step"

_STEP_PREFIX = "GovActionProcessStep::"
_PROCESS_PREFIX = "GovActionProcess::"

#: The guard meaning "always follow this edge".
UNCONDITIONAL_GUARD = "Any"


@dataclass
class DefinitionDoc:
    """One document's declaration of a Survey Definition."""
    process: str = ""
    #: Step keys in declaration order, which is the run order the generator
    #: writes. Verified 2026-08-26 to match live Egeria exactly across all
    #: eight definitions.
    steps: list = field(default_factory=list)
    descriptions: dict = field(default_factory=dict)
    #: (previous_step_key, next_step_key, guard) as authored. Not derived
    #: from `steps` — a branch has edges the step order cannot express.
    links: list = field(default_factory=list)
    #: Which resource type this survey runs against — "repo" | "database" |
    #: "filesystem". Inferred by documented_definitions() from the source
    #: filename's `{resource_type}-survey-definition-*.md` convention
    #: (docs/dr-egeria/survey-definitions/), not from anything in the
    #: document body itself, which carries no resource-type field. Defaults
    #: to "repo" here only as the dataclass default for direct construction
    #: (e.g. in tests) — every document actually read through
    #: documented_definitions() gets a real inferred value.
    resource_type: str = "repo"

    @property
    def branches(self) -> bool:
        """Whether any step has more than one outgoing edge."""
        seen: dict = {}
        for prev, _, _ in self.links:
            seen[prev] = seen.get(prev, 0) + 1
        return any(n > 1 for n in seen.values())

    @property
    def real_guards(self) -> list:
        return sorted({g for _, _, g in self.links if g and g != UNCONDITIONAL_GUARD})


def _section_value(lines: list, start: int, heading: str) -> str:
    """The first non-blank line under `heading`, within this command's block.

    Bounded by the next command heading and by the `___` separator, so a block
    missing a section reports nothing rather than borrowing the following
    command's value — which would attribute one step's description, or one
    edge's guard, to another.
    """
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("## ") or stripped == "___":
            return ""
        if stripped != heading:
            continue
        for k in range(j + 1, len(lines)):
            candidate = lines[k].strip()
            if candidate.startswith(("###", "## ")) or candidate == "___":
                return ""
            if candidate:
                return candidate
        return ""
    return ""


def _key(qualified_name: str) -> str:
    return qualified_name.rsplit("::", 1)[-1] if qualified_name else ""


def parse_document(path) -> DefinitionDoc:
    """Parse one Dr.Egeria definition document.

    An unreadable file yields an empty DefinitionDoc rather than raising:
    callers use this to decide whether to repair, and a parse failure must not
    look like a definition with no steps — `process` being empty is what says
    "nothing was read here".
    """
    doc = DefinitionDoc()
    try:
        lines = Path(path).read_text().splitlines()
    except OSError as exc:
        log.debug("could not read definition document %s: %s", path, exc)
        return doc

    for i, raw in enumerate(lines):
        heading = raw.strip()

        if heading == CREATE_STEP:
            qualified = _section_value(lines, i, "### Qualified Name")
            if qualified.startswith(_STEP_PREFIX):
                key = _key(qualified)
                doc.steps.append(key)
                doc.descriptions[key] = _section_value(lines, i, "### Description")

        elif heading == CREATE_PROCESS:
            qualified = _section_value(lines, i, "### Qualified Name")
            if qualified.startswith(_PROCESS_PREFIX):
                doc.process = _key(qualified)

        elif heading == LINK_NEXT:
            prev = _section_value(lines, i, "### Governance Action Process Step")
            nxt = _section_value(lines, i, "### Next Governance Action Process Step")
            if prev.startswith(_STEP_PREFIX) and nxt.startswith(_STEP_PREFIX):
                guard = _section_value(lines, i, "### Guard") or UNCONDITIONAL_GUARD
                doc.links.append((_key(prev), _key(nxt), guard))

        # LINK_FIRST is deliberately not collected. It attaches the process to
        # its entry step (a GovernanceActionProcessFlow relationship), not one
        # step to another, so it is not part of the step-to-step edge set the
        # reconciler diffs.

    return doc


def definition_docs_dir() -> Path:
    return (Path(__file__).resolve().parent.parent.parent / "docs" / "dr-egeria"
            / "survey-definitions")


#: Every resource type a Survey Definition doc can be authored for — see
#: repo_survey_definition_adapter.py / database / filesystem's own
#: survey_definition_adapter.py registrations. A filename prefix outside
#: this set is not a resource type this codebase knows about, and
#: _resource_type_from_filename falls back to "repo" for it (the codebase's
#: only resource type before this field existed at all) rather than
#: inventing a new value silently.
_KNOWN_RESOURCE_TYPES = {"repo", "database", "filesystem"}


def _resource_type_from_filename(path: Path) -> str:
    """Infer resource_type from the `{resource_type}-survey-definition-*.md`
    filename convention every doc in this directory follows (all eight
    current documents are `repo-survey-definition-*.md`). Falls back to
    "repo" for anything that doesn't match — matches this field's dataclass
    default and every pre-existing document."""
    prefix = path.stem.split("-survey-definition")[0]
    return prefix if prefix in _KNOWN_RESOURCE_TYPES else "repo"


def documented_definitions(directory=None) -> dict:
    """{definition name: DefinitionDoc} across every authored document."""
    directory = Path(directory) if directory else definition_docs_dir()
    out: dict = {}
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.md")):
        doc = parse_document(path)
        if doc.process and doc.steps:
            doc.resource_type = _resource_type_from_filename(path)
            out[doc.process] = doc
    return out


def document_for(survey_group: str, directory=None) -> DefinitionDoc | None:
    return documented_definitions(directory).get(survey_group)
