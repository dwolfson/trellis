"""Manifests: subclasses of pyegeria's AnalyticFunctionSpec carrying the five additive fields.

The egeria-python change that would add these fields to the base class is NOT made
(brief section 7), so the subclasses carry them. Defaults on the base keep every
existing spec valid; here `kind`, `source` and `version` are required.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field
from pyegeria.view.analytic_registry import AnalyticFunctionSpec

Kind = Literal["routine", "step"]
Source = Literal["ods", "egeria", "resource"]


class _TrellisManifest(AnalyticFunctionSpec):
    kind: Kind
    source: Source
    version: str
    envelope: bool = True
    annotation_type: str = ""           # a step's result type; empty for a routine
    resource_types: list[str] = Field(default_factory=list)
    family: str = ""
    tags: list[str] = Field(default_factory=list)
    #: Which investigation purposes this serves (a qualifier). Checked at load against Egeria's purposes list
    #: (`discovery.discover`); suggestive, so an unknown value warns, naming it, and is kept.
    purposes: list[str] = Field(default_factory=list)


def purpose_warnings(manifest: _TrellisManifest, known: list[str]) -> list[str]:
    """One sentence per declared purpose outside `known`, naming the manifest and the value. Never raises."""
    folded = {" ".join(k.split()).casefold() for k in known}
    return [f"manifest '{manifest.name}': purpose '{p}' is not in the investigation-purposes list; kept as written"
            for p in manifest.purposes if p and " ".join(p.split()).casefold() not in folded]


class RoutineManifest(_TrellisManifest):
    kind: Kind = "routine"


class StepManifest(_TrellisManifest):
    kind: Kind = "step"
    annotation_type: str = "ResourceMeasureAnnotation"
    # Owner ruling 2026-10-07: a user step may ask for read-only on the resource, nothing higher.
    credential_tier: Literal["read_only"] = "read_only"
