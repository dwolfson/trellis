"""How a reader says what a symbol or marker row knows about where it came from:
its file's role and the commit its extraction surveyed (artifacts slice 1,
DESIGN-ARTIFACTS-VIEW-AND-DOC-LINKS.md §3 and §6).

Both columns are NULL on rows written before they existed. NULL is shown as
"not recorded", never filled in with a guess: today's role of the same path, or
the project's current commit, would be a confident claim about a run that did
not record it.
"""
from __future__ import annotations

NOT_RECORDED = "not recorded"


def role_label(role: str | None) -> str:
    return role if role else f"role {NOT_RECORDED}"


def commit_label(sha: str | None) -> str:
    return f"commit {sha[:12]}" if sha else f"commit {NOT_RECORDED}"


def extraction_commit(registry, slug: str) -> str | None:
    """The commit the latest symbol extraction run of this repo surveyed, from
    its own step_runs row (`survey_commit_sha`). None when no extraction run is
    recorded, or the latest one recorded no commit. Never the project's current
    `last_commit_sha`: that is what the NEXT run would survey."""
    try:
        rows = registry.query_step_runs(slug=slug, step_key="repo_symbol_extraction",
                                        entity_type="repo", limit=1)
    except Exception:
        return None
    return (rows[0].get("survey_commit_sha") or None) if rows else None
