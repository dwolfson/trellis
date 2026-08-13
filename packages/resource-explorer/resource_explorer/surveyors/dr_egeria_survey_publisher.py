"""Generates Dr.Egeria markdown that publishes RE's local analysis steps as
real Egeria `GovernanceActionProcessStep`/`GovernanceActionProcess` elements,
and chains them into a runnable Survey Definition.

Closes design-doc question A12 (`docs/egeria-collaboration-and-survey-model.md`
§6.1) and the tracked `docs/Backlog.md` item: "publishing RE's own
sub-surveyors as catalogable GovernanceActionType elements — nothing does
this today." See `docs/analysis-step-egeria-registration-plan.md` for the
full plan (D1-D3).

Deliberately generates markdown for the existing, proven "Action Author"
Dr.Egeria command family (`Create Governance Action Process Step`,
`Create Governance Action Process`, `Link First/Next Process Step`) — no new
Egeria types or Dr.Egeria commands needed (confirmed: §6.1's own finding,
and this is the exact recipe already used live for the original "Repo Coarse
Scout" process). Producing markdown to be executed through the same
mcp__egeria tooling already proven this session, rather than reimplementing
pyegeria's GovernanceOfficer.create_governance_definition() body-construction
natively in RE — that generic body shape has real footguns (see
egeria-python CLAUDE.md's "Creating a type with no dedicated OMVS wrapper"
note) not worth re-deriving here for what is fundamentally a one-time/
per-addition publishing action, not a hot path.

Resource-type-agnostic by design: everything here operates on a plain list
of PublishableStep descriptors, not on repo_survey_definition_adapter.py's
STEP_REGISTRY/StepInfo shape specifically — a database or filesystem adapter
(neither of which has repo's StepInfo-dataclass registry today) can build
its own PublishableStep list and reuse every function in this module
unchanged. See scripts/generate_repo_survey_definition.py for the one
resource-type-specific piece (extracting steps from repo's STEP_REGISTRY).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublishableStep:
    """One analysis step to publish as a GovernanceActionProcessStep.

    step_key doubles as the `re_analysis_step` Additional Properties value —
    RE's own convention (documented in egeria-collaboration-and-survey-model.md
    §6.2) for "which local RE sub-surveyor a step maps to" is that the two
    are the same identifier, so a Survey Definition reader never needs a
    separate lookup table to go from Egeria element back to RE dispatch key.
    """
    step_key: str
    description: str
    technology_type: str


def _step_qualified_name(survey_group: str, step_key: str) -> str:
    return f"GovActionProcessStep::{survey_group}::{step_key}"


def _process_qualified_name(survey_group: str) -> str:
    return f"GovActionProcess::{survey_group}"


def _step_display_name(survey_display_name: str, step_key: str) -> str:
    readable = step_key.replace("_", " ").title()
    return f"{survey_display_name} — {readable}"


def render_step_block(survey_group: str, survey_display_name: str, step: PublishableStep) -> str:
    """One "Create Governance Action Process Step" command block. Additional
    Properties follow the documented executes_at/supported_technology_type/
    re_analysis_step convention (§6.2) — executes_at is always
    "resource-explorer" here since every PublishableStep this module handles
    is, by definition, an RE-local sub-surveyor."""
    qn = _step_qualified_name(survey_group, step.step_key)
    return (
        "## Create Governance Action Process Step\n"
        f"### Display Name\n{_step_display_name(survey_display_name, step.step_key)}\n\n"
        f"### Qualified Name\n{qn}\n\n"
        f"### Description\n{step.description}\n\n"
        "### Additional Properties\n"
        "| Parameter Name | Parameter Value |\n"
        "|---|---|\n"
        "| executes_at | resource-explorer |\n"
        f"| supported_technology_type | {step.technology_type} |\n"
        f"| re_analysis_step | {step.step_key} |\n"
    )


def render_process_block(
    survey_group: str, survey_display_name: str, technology_type: str, description: str,
) -> str:
    """The "Create Governance Action Process" command block — the survey
    container all steps get linked into."""
    return (
        "## Create Governance Action Process\n"
        f"### Display Name\n{survey_display_name}\n\n"
        f"### Qualified Name\n{_process_qualified_name(survey_group)}\n\n"
        f"### Description\n{description}\n\n"
        "### Additional Properties\n"
        "| Parameter Name | Parameter Value |\n"
        "|---|---|\n"
        f"| supported_technology_type | {technology_type} |\n"
    )


def render_link_first_block(survey_group: str, first_step_key: str) -> str:
    return (
        "## Link First Process Step\n"
        f"### Governance Action Process\n{_process_qualified_name(survey_group)}\n\n"
        f"### Governance Action Process Step\n{_step_qualified_name(survey_group, first_step_key)}\n"
    )


def render_link_next_block(survey_group: str, prev_step_key: str, next_step_key: str, guard: str = "Any") -> str:
    """Unconditional linear chaining (guard="Any") — matches the proven,
    live-verified convention in docs/egeria-database-survey-definition.md.
    Guard-based branching between steps (a real Egeria mechanism, confirmed
    in §6.4) is deliberately not used here — v1 keeps every Survey
    Definition this module generates a plain linear sequence, per the
    design doc's A9 decision ("keep it simple initially")."""
    return (
        "## Link Next Process Step\n"
        f"### Governance Action Process Step\n{_step_qualified_name(survey_group, prev_step_key)}\n\n"
        f"### Next Governance Action Process Step\n{_step_qualified_name(survey_group, next_step_key)}\n\n"
        f"### Guard\n{guard}\n"
    )


def generate_survey_definition_markdown(
    survey_group: str,
    survey_display_name: str,
    technology_type: str,
    description: str,
    steps: list[PublishableStep],
) -> str:
    """Full Dr.Egeria markdown document: one 'Create Governance Action
    Process Step' per step (in the given order), one 'Create Governance
    Action Process', 'Link First Process Step', then 'Link Next Process
    Step' for every consecutive pair. Command order in the file matches
    the block ordering `dr_egeria`'s dispatcher expects (steps created
    before they're referenced by the process/links) — the exact structure
    proven live in docs/egeria-database-survey-definition.md, generalized.

    Raises ValueError on an empty steps list — a Survey Definition with no
    steps isn't a meaningful thing to author."""
    if not steps:
        raise ValueError("generate_survey_definition_markdown() needs at least one step")

    blocks = [render_step_block(survey_group, survey_display_name, s) for s in steps]
    blocks.append(render_process_block(survey_group, survey_display_name, technology_type, description))
    blocks.append(render_link_first_block(survey_group, steps[0].step_key))
    for prev, nxt in zip(steps, steps[1:]):
        blocks.append(render_link_next_block(survey_group, prev.step_key, nxt.step_key))

    return "\n___\n\n".join(blocks) + "\n"
