"""Scalar filter-expression DSL -> SQL translator.

Moved from Egeria Advisor's advisor/vector_store_pg.py (_translate_filter_expr)
unchanged — it's the engine behind query_by_filter()'s filter_expr param, so
it can't stay EA-private once query_by_filter is shared. Resource Explorer
has no scalar columns to filter (its uniform schema has none), so it never
calls this; passing filter_expr against an RE collection raises Postgres
UndefinedColumn rather than returning nothing — a documented footgun, not a
guarded case, since RE genuinely has nothing to filter by definition.

Supported forms (unchanged from the original):
  - field == "value"
  - field == True / field == False
  - field like "%value%"
  - compound: A and B

An unrecognized fragment is silently skipped (with a caller-supplied logger
warning, if given) — this was EA's existing behavior and is preserved
deliberately, not accidentally: a malformed filter degrades to an
unfiltered scan rather than raising.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

_EQ_STR = re.compile(r'^(\w+)\s*==\s*"([^"]*)"$')
_EQ_BOOL = re.compile(r"^(\w+)\s*==\s*(True|False)$")
_LIKE = re.compile(r'^(\w+)\s+like\s+"([^"]*)"$', re.IGNORECASE)


def translate_filter_expr(
    expr: str, warn: Optional[Callable[[str], None]] = None
) -> Optional[dict[str, Any]]:
    """Translate a filter expression into {"clause": <sql fragment>, "params": [...]}.
    Returns None if no recognizable conditions were found (caller should
    then skip the WHERE clause entirely, not fail the query)."""
    conditions: list[str] = []
    params: list[Any] = []

    for part in re.split(r"\s+and\s+", expr.strip(), flags=re.IGNORECASE):
        part = part.strip()

        m = _EQ_STR.match(part)
        if m:
            conditions.append(f'"{m.group(1)}" = %s')
            params.append(m.group(2))
            continue

        m = _EQ_BOOL.match(part)
        if m:
            conditions.append(f'"{m.group(1)}" = %s')
            params.append(m.group(2) == "True")
            continue

        m = _LIKE.match(part)
        if m:
            conditions.append(f'"{m.group(1)}" LIKE %s')
            params.append(m.group(2))
            continue

        if warn:
            warn(f"Unrecognized filter expression fragment (skipped): {part!r}")

    if not conditions:
        return None
    return {"clause": " AND ".join(conditions), "params": params}
