"""Shared helpers for D5/D6 target-shape-aware scoped analysis (repo
scope-narrowing funnel plan, docs/repo-scope-narrowing-funnel.md).

Corpus-shaped surveyors (target_shape="corpus" in analysis_catalog.yaml)
can run against the whole resource OR a narrower cataloged sub-resource —
mechanically, that's always a path-prefix filter over an existing per-file
table/query, per the plan's own "Target-shape inventory" audit. These two
small functions are the one place that filter logic lives, so every
corpus-shaped surveyor applies it identically rather than each growing its
own slightly-different path-matching code.
"""
from __future__ import annotations


def path_matches_scope(file_path: str, scope_locator: str) -> bool:
    """True if file_path falls within scope_locator — either an exact
    match (scope_locator names the file itself, the single_leaf-degrades-
    fine-under-corpus case) or scope_locator names a containing folder
    (path-prefix match). scope_locator == "" (whole-resource scope, the
    default everywhere) always matches everything."""
    if not scope_locator:
        return True
    return file_path == scope_locator or file_path.startswith(f"{scope_locator}/")


def sql_scope_filter(scope_locator: str, column: str = "file_path") -> tuple[str, tuple]:
    """SQL WHERE-clause fragment (with a leading " AND ", parameterized —
    never string-interpolates scope_locator into the query) + params for
    filtering a per-file query by scope_locator, matching
    path_matches_scope()'s semantics exactly. Returns ("", ()) for
    whole-resource scope — callers can always append the fragment and
    extend their params tuple unconditionally, no branching needed."""
    if not scope_locator:
        return "", ()
    return f" AND ({column} = ? OR {column} LIKE ?)", (scope_locator, f"{scope_locator}/%")
