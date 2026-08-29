"""Context compilation: a declared spec, and a deterministic packer.

See README.md for why the packer is ordinary code rather than an agent.
"""
from trellis_context.packer import (
    BudgetError,
    Candidate,
    Manifest,
    PackedContext,
    PackedSection,
    pack,
)
from trellis_context.spec import ContextSpec, Section

__all__ = [
    "BudgetError",
    "Candidate",
    "ContextSpec",
    "Manifest",
    "PackedContext",
    "PackedSection",
    "Section",
    "pack",
]
