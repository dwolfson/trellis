"""Manifests: subclasses of pyegeria's AnalyticFunctionSpec carrying what trellis adds or narrows.

Since pyegeria 6.2.3 (ISSUE-149) the base class carries `kind`, `source`, `version`, `envelope`,
`annotation_type`, `resource_types`, `family` and `tags` itself, all optional. This module no longer redeclares the
ones it would only repeat (`annotation_type`, `resource_types`, `family`, `tags`). It keeps only the overrides
trellis wants stricter than the base:

- `source` is a closed `Literal["ods", "egeria", "resource"]` and required. The base is an open string that warns on
  an unknown value and keeps it ("suggestive"); a trellis manifest is checked at construction instead.
- `version` is required. The base defaults it to "", which would stamp an unversioned result.
- `envelope` defaults to True. Every trellis routine returns an Envelope; the base default is False.
- `kind` is one word per subclass (`Literal["routine"]` / `Literal["step"]`), so a RoutineManifest cannot be
  built as a step. The base allows either on either.

and what the base does not have: `purposes` and `questions` (qualifiers checked at load) and a step's
`credential_tier`, `inputs`, `display_name`, `stage` and `perspectives`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator
from pyegeria.view.analytic_registry import AnalyticFunctionSpec

Source = Literal["ods", "egeria", "resource"]


class _TrellisManifest(AnalyticFunctionSpec):
    source: Source
    version: str
    envelope: bool = True
    #: Which investigation purposes this serves (a qualifier). Checked at load against Egeria's purposes list
    #: (`discovery.discover`); suggestive, so an unknown value warns, naming it, and is kept.
    purposes: list[str] = Field(default_factory=list)
    #: The questions this answers, BY STABLE ID (`Q-0001`, the `id` of an entry in Resource Explorer's question
    #: catalog), never by wording: the wording is edited, the id is not. Checked at load against the catalog
    #: (`discovery.check_questions`); suggestive, so an unknown id warns, naming it, and is kept.
    questions: list[str] = Field(default_factory=list)


def question_warnings(manifest: _TrellisManifest, known: set[str]) -> list[str]:
    """One sentence per declared question id outside `known`, naming the manifest and the id. Never raises."""
    return [f"manifest '{manifest.name}': question '{q}' is not an id in the question catalog; kept as written"
            for q in manifest.questions if q and q.strip() not in known]


def purpose_warnings(manifest: _TrellisManifest, known: list[str]) -> list[str]:
    """One sentence per declared purpose outside `known`, naming the manifest and the value. Never raises."""
    folded = {" ".join(k.split()).casefold() for k in known}
    return [f"manifest '{manifest.name}': purpose '{p}' is not in the investigation-purposes list; kept as written"
            for p in manifest.purposes if p and " ".join(p.split()).casefold() not in folded]


class RoutineManifest(_TrellisManifest):
    kind: Literal["routine"] = "routine"


#: What a step may ask of the resource it measures (owner ruling 2026-10-07): nothing, or read-only. Anything
#: higher is refused, with a sentence naming the tier, until a publication-style profile says otherwise.
CREDENTIAL_TIERS = ("none", "read_only")

#: What the wrapper can hand a step's code. A step gets the inputs it declares and nothing else.
#:   resource   - the resource's type and slug (always handed; declaring it alone hands nothing more)
#:   ods        - a read-only reader of RE's registry (the ODS)
#:   connection - a connection to the resource opened at the declared tier, never a password
STEP_INPUTS = ("resource", "ods", "connection")


def tier_refusal(tier: str) -> str:
    """The sentence for a tier above read-only, or "" for an allowed one."""
    if tier in CREDENTIAL_TIERS:
        return ""
    return (f"credential tier '{tier}' refused: a user step may ask for read-only on the resource and nothing "
            "more (owner ruling 2026-10-07)")


class StepManifest(_TrellisManifest):
    """Level 2's declaration (brief 2c'): what the wrapper needs to run a user's code as a survey step."""
    kind: Literal["step"] = "step"
    annotation_type: str = "ResourceMeasureAnnotation"
    credential_tier: str = "none"
    inputs: list[str] = Field(default_factory=lambda: ["ods"])
    #: Shown as the analysis's name in Resource Explorer and as the Egeria element's display name.
    display_name: str = ""
    #: The stage this step's results belong to (RE's catalog calls it `intent`: scouting, analysis, ...).
    stage: str = "analysis"
    perspectives: list[str] = Field(default_factory=lambda: ["all"])

    @field_validator("credential_tier")
    @classmethod
    def _tier(cls, v: str) -> str:
        if refusal := tier_refusal(v):
            raise ValueError(refusal)
        return v

    @field_validator("inputs")
    @classmethod
    def _inputs(cls, v: list[str]) -> list[str]:
        unknown = [i for i in v if i not in STEP_INPUTS]
        if unknown:
            raise ValueError(f"input {', '.join(repr(u) for u in unknown)} is not one the wrapper hands a step "
                             f"(known: {', '.join(STEP_INPUTS)})")
        return v

    @model_validator(mode="after")
    def _connection_needs_a_tier(self) -> "StepManifest":
        if "connection" in self.inputs and self.credential_tier == "none":
            raise ValueError("a step that declares the 'connection' input must declare credential_tier "
                             "'read_only'; with 'none' there is no connection to hand it")
        return self
