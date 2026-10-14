"""The Dr.Egeria document that declares a step to Egeria, generated from its manifest (brief 2c, 3a step 4).

Generated only: nothing here talks to Egeria. A person with the right hand runs the document to create the
element; retirement is a status (`Content Status` DEPRECATED), never a delete.

Two blocks:

1. `Create Governance Action Type`: the wrapper's element (level 2), the same governance-action family the Survey
   Definitions use, so a later Egeria dispatch to RE's engine lands on a declared type. PROVISIONAL: whether
   GovernanceActionType is the right element for a step Egeria does not run is an open question for the Egeria
   leads (Mandy note, item 20); the document says so in its first lines.
2. `Create Governance Action Process Step`: what a Survey Definition author adds to a definition document
   (level 3) to include the step, referencing it by `re_analysis_step` exactly as RE's built-in steps are. A
   user step joins a survey by editing that document, not RE's code. The process qualified name is a
   placeholder the author replaces.
"""
from __future__ import annotations

from trellis_analytics.manifest import StepManifest

QN_PREFIX = "GovActionType::trellis-analytics::"


def _table(rows: list[tuple[str, str]]) -> str:
    return "\n".join(["| Parameter Name | Parameter Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows])


def declaration_markdown(manifest: StepManifest, origin: dict[str, str]) -> str:
    """The declaration document for one step manifest. `origin` is `discovery.origin(name)`: the package and
    entry point that provide it."""
    m = manifest
    name = m.display_name or m.name.replace("_", " ").title()
    qn = QN_PREFIX + m.name
    props = [
        ("kind", m.kind), ("source", m.source), ("resource_types", ", ".join(m.resource_types)),
        ("annotation_type", m.annotation_type), ("questions", ", ".join(m.questions)),
        ("purposes", ", ".join(m.purposes)), ("perspectives", ", ".join(m.perspectives)),
        ("credential_tier", m.credential_tier), ("inputs", ", ".join(m.inputs)),
        ("family", m.family), ("executes_at", "resource-explorer"), ("re_analysis_step", m.name),
        ("function", m.function), ("package", origin.get("package", "")),
        ("entry_point", f"trellis.analytics:{origin.get('entry_point', '')}"),
    ]
    step_props = [("executes_at", "resource-explorer"), ("re_analysis_step", m.name)]
    blocks = [
        "\n".join([
            "## Create Governance Action Type",
            "### Display Name", name, "",
            "### Qualified Name", qn, "",
            "### Description", m.description, "",
            "### Version Identifier", m.version, "",
            "### Content Status", "ACTIVE", "",
            "### Category", m.family or "Analytic Library", "",
            "### Additional Properties", _table(props), "",
        ]),
        "\n".join([
            "## Create Governance Action Process Step",
            "### Display Name", f"<Survey Definition> — {name}", "",
            "### Qualified Name", f"GovActionProcessStep::<SurveyDefinition>::{m.name}", "",
            "### Description", m.description, "",
            "### Additional Properties", _table(step_props), "",
        ]),
    ]
    header = "\n".join([
        "<!--",
        f"GENERATED from the manifest of '{m.name}' ({origin.get('package', '')} {m.version}) by",
        "packages/resource-explorer/scripts/generate_external_step_entries.py. Do not hand-edit; regenerate.",
        "",
        "PROVISIONAL: GovernanceActionType is the element type used here for a step that Egeria does not run.",
        "Whether that is the right element is an open question for the Egeria leads (Mandy note, item 20).",
        "",
        "Run this document to declare the step in Egeria; nothing runs it automatically. Retire the step by",
        "setting Content Status to DEPRECATED, never by deleting the element.",
        "",
        "The second block is for a Survey Definition author: paste it into the definition's document, replace",
        "<SurveyDefinition>, and link it with Link Next Process Step. A user step joins a survey that way, not",
        "through Resource Explorer's code.",
        "-->",
    ])
    return header + "\n\n" + "\n___\n\n".join(blocks) + "\n___\n"
