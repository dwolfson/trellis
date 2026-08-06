"""
CreateRouter — classifies a 'create' intent query as plan, report_spec, or ambiguous.
"""
from __future__ import annotations
import re
from typing import Optional


_PLAN_SIGNALS = re.compile(
    r'\b(?:plan|governance|polic|zone|steward|appoint|assign|workflow|certif|survey|project|campaign|task|actor|role|team|community)\b',
    re.IGNORECASE,
)
_SPEC_SIGNALS = re.compile(
    r'\b(?:report|spec|show|list|find|display|glossar|asset|collection|term|categor|data.class|data.field|schema|database|project)\b',
    re.IGNORECASE,
)

# Ambiguous words present in both (project, community etc.) — break ties by order
_AMBIGUOUS = {'project', 'community'}


def route_create(query: str) -> str:
    """Return 'plan', 'report_spec', or 'ambiguous'."""
    plan_hits = set(m.group().lower() for m in _PLAN_SIGNALS.finditer(query))
    spec_hits = set(m.group().lower() for m in _SPEC_SIGNALS.finditer(query))
    # Remove words that appear in both sets — they don't break ties
    plan_only = plan_hits - spec_hits
    spec_only = spec_hits - plan_hits
    if plan_only and not spec_only:
        return 'plan'
    if spec_only and not plan_only:
        return 'report_spec'
    if plan_only and spec_only:
        # more plan-only signals wins
        return 'plan' if len(plan_only) >= len(spec_only) else 'report_spec'

    # Neither keyword set produced a clear signal, or they fully cancelled out (e.g.
    # "Egeria-Project" false-matches the generic "project" keyword, which appears in
    # BOTH sets and so contributes nothing). Before giving up as ambiguous, check
    # whether the query names a specific, known Dr.Egeria command/entity type (e.g.
    # "External Reference", "Digital Product", "Solution Blueprint") — explicitly
    # naming a concrete type to create is an unambiguous 'plan' signal that the small
    # hardcoded keyword lists above don't cover. Only used as a last-resort
    # tie-breaker, never to override an already-decided plan_only/spec_only
    # classification above, so this can't flip existing behaviour for queries the
    # keyword lists already handle (e.g. "glossar" already routes bare "Create a
    # Glossary" to report_spec; this fallback never runs for that case since
    # spec_only is already non-empty).
    #
    # Tries the full command keyword index first (all ~126 known Dr.Egeria commands,
    # with alias/partial matching — e.g. bare "blueprint" resolves to "Create Solution
    # Blueprint" via its alias), then the narrower Egeria type-name registry (built for
    # Act's element-type extraction, has a few industry-terminology aliases like "data
    # product" -> DigitalProduct that the command index doesn't). High confidence
    # (>=0.70) required since this decides the whole downstream flow, not just a
    # low-confidence suggestion.
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", query)
    try:
        from advisor.command_keyword_index import get_command_keyword_index
        idx = get_command_keyword_index()
        for length in range(min(len(words), 4), 0, -1):
            for start in range(len(words) - length + 1):
                phrase = " ".join(words[start:start + length])
                match = idx.lookup(phrase)
                if match and match.confidence >= 0.70:
                    return 'plan'
    except Exception:
        pass

    from advisor.egeria_type_registry import resolve_type_name
    for length in range(min(len(words), 4), 0, -1):
        for start in range(len(words) - length + 1):
            if resolve_type_name(words[start:start + length]):
                return 'plan'

    return 'ambiguous'
