"""Shared collection→(project_slug, path filter) scope resolution for
Resource Explorer's code-intelligence tables (resource_explorer.
project_code_symbols / project_code_relationships).

Extracted out of advisor/agents/code_intel_agent.py so analytics.py's
Resource-Explorer-backed reader (advisor/re_code_symbol_reader.py) can reuse
the exact same "pyegeria" / "egeria_java" collection-name resolution instead
of duplicating it — both are Phase 6/7 consumers of the same underlying
scoping concept (AST-ownership-transfer plan).
"""
from __future__ import annotations

from typing import Optional

# Logical subsystems within RE's whole-repo project_slugs — replaces EA's old
# per-query-function hardcoded LIKE-block filters. "pyegeria"/"egeria_java"
# are kept as the recognized collection names (matching what callers/prompts
# already use) so only what these names resolve to internally changed.
SCOPES: dict[str, dict] = {
    "pyegeria": {
        "project_slug": "egeria_python_git",
        "include_prefix": "pyegeria/",
        "exclude_fragments": ["/tests/", "/my_egeria/", "/md_processing/", "/examples/", "/commands/"],
    },
    "egeria_java": {
        "project_slug": "egeria_git",
        "include_prefix": None,
        "exclude_fragments": [],
    },
}

# Every code-bearing project in RE's "egeria" group (egeria_docs excluded —
# it's a docs-only repo with no project_code_symbols rows) — the default
# scope when no collection/project is specified.
DEFAULT_PROJECT_SLUGS = ["egeria_git", "egeria_python_git", "egeria_workspaces_git"]


def scope_clause(collection: Optional[str], table_alias: str = "") -> tuple[str, list]:
    """Returns (sql_where_fragment, params) scoping a query to a collection
    name (resolved via SCOPES), an explicit project_slug not in SCOPES, or
    (when collection is None) every code-bearing project in the egeria group."""
    prefix = f"{table_alias}." if table_alias else ""
    if collection and collection in SCOPES:
        scope = SCOPES[collection]
        clauses = [f"{prefix}project_slug = %s"]
        params: list = [scope["project_slug"]]
        if scope["include_prefix"]:
            clauses.append(f"{prefix}file_path LIKE %s")
            params.append(f"{scope['include_prefix']}%")
        for frag in scope["exclude_fragments"]:
            clauses.append(f"{prefix}file_path NOT LIKE %s")
            params.append(f"%{frag}%")
        return " AND ".join(clauses), params
    if collection:
        # Not a recognized subsystem name — treat it as a literal project_slug.
        return f"{prefix}project_slug = %s", [collection]
    placeholders = ", ".join(["%s"] * len(DEFAULT_PROJECT_SLUGS))
    return f"{prefix}project_slug IN ({placeholders})", list(DEFAULT_PROJECT_SLUGS)
