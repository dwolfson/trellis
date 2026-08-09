"""BeeAI @tool functions shared across Egeria Advisor agents."""
from __future__ import annotations
import csv
import re
from functools import lru_cache
from pathlib import Path

from beeai_framework.tools import tool


@lru_cache(maxsize=1)
def _load_perspective_families() -> dict[str, list[str]]:
    """Load perspective→template-family mappings from config/perspective_template_families.csv.

    Returns a dict keyed by lowercase advisor perspective key (e.g. 'developer', 'any')
    with values being dicts of {normalised_family: boost} where boost is 2 for level='both'
    and 1 for level='basic'.  Comment lines (starting with #) are skipped.
    """
    csv_path = Path(__file__).parent.parent / "configdata" / "perspective_template_families.csv"
    result: dict[str, dict[str, int]] = {}
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                perspective = row.get("perspective", "").strip()
                family = row.get("family", "").strip()
                level = row.get("level", "basic").strip().lower()
                if not perspective or not family or perspective.startswith("#"):
                    continue
                boost = 2 if level == "both" else 1
                result.setdefault(perspective.lower(), {})[family.lower()] = boost
    except Exception:
        pass
    return result


@tool(description=(
    "Search indexed Egeria content for text relevant to the query. "
    "collections is a comma-separated list of collection names from: "
    "pyegeria, pyegeria_cli, pyegeria_drE, egeria_concepts, egeria_general, egeria_types, "
    "egeria_workspaces, egeria_java, egeria_templates. "
    "Call multiple times with different queries or collections to broaden coverage. "
    "Returns the most relevant chunks with their source file and score."
))
def search_egeria_content(query: str, collections: str) -> str:
    from advisor.multi_collection_store import get_multi_collection_store
    names = [c.strip() for c in collections.split(",") if c.strip()]
    if not names:
        return "Error: no collection names provided."
    store = get_multi_collection_store()
    result = store.search_specific_collections(query=query, collection_names=names, top_k=6)
    if not result.results:
        return "No relevant content found."
    parts = []
    for r in result.results:
        col = r.metadata.get("_collection", r.metadata.get("collection", "?"))
        fp = r.metadata.get("file_path", r.metadata.get("source", ""))
        parts.append(f"[{col} | {fp} | score={r.score:.2f}]\n{r.text}")
    return "\n\n---\n\n".join(parts)


def _search_egeria_content_raw(query: str, collections: list[str], top_k: int = 8) -> str:
    """Direct call to the search logic without going through the BeeAI tool wrapper."""
    from advisor.multi_collection_store import get_multi_collection_store
    if not collections:
        return "No collections specified."
    store = get_multi_collection_store()
    result = store.search_specific_collections(query=query, collection_names=collections, top_k=top_k)
    if not result.results:
        return "No relevant content found."
    parts = []
    for r in result.results:
        col = r.metadata.get("_collection", r.metadata.get("collection", "?"))
        fp = r.metadata.get("file_path", r.metadata.get("source", ""))
        parts.append(f"[{col} | {fp} | score={r.score:.2f}]\n{r.text}")
    return "\n\n---\n\n".join(parts)


@tool(description=(
    "Look up detailed information about a specific pyegeria class, method, or function by name. "
    "Useful when you know the exact symbol name (e.g. 'ProjectManager', 'create_project', "
    "'get_glossary_terms'). Returns the class/function signature, docstring, and source location."
))
def get_egeria_symbol(name: str) -> str:
    return _get_egeria_symbol_raw(name)


def _get_egeria_symbol_raw(name: str) -> str:
    """Direct call to symbol lookup without the BeeAI tool wrapper.

    Reads via ReCodeSymbolReader (resource_explorer.project_code_symbols),
    not the deprecated CodeSymbolStore (code_symbols/code_relationships) —
    nothing has written to those tables since the AST-ownership-transfer
    migration (Phase 8), so the old code path always missed here and fell
    straight through to the vector-search fallback below, silently, for
    every call. analytics.py/re_code_scope.py already made this same switch;
    this was the one remaining call site still on the old store."""
    from advisor.re_code_symbol_reader import get_re_code_symbol_reader
    store = get_re_code_symbol_reader()

    # Try exact match in PostgreSQL first (filter to pyegeria Python SDK symbols)
    symbols = store.search_symbols(name_pattern=name, collection="pyegeria", limit=5)
    
    # Filter for exact name match if possible
    exact_matches = [s for s in symbols if s["name"].lower() == name.lower()]
    targets = exact_matches if exact_matches else symbols
    
    if targets:
        parts = []
        for s in targets:
            desc = f"Name: {s['name']}\nType: {s['kind']}"
            if s['parent_class']:
                desc += f"\nParent Class: {s['parent_class']}"
            if s['signature']:
                desc += f"\nSignature: {s['signature']}"
            if s['docstring']:
                desc += f"\nDocumentation: {s['docstring']}"
            
            # If it's a class, also fetch its methods from DB
            if s['kind'] == 'class':
                methods = store.methods_for_class(s['name'])
                if methods:
                    desc += "\n\nExposed Methods:"
                    for m in methods:
                        m_sig = m['signature'] or "()"
                        desc += f"\n  - {m['name']}{m_sig}"
                        if m['docstring']:
                            desc += f"  # {m['docstring'].strip()}"
                            
            parts.append(f"[{s['collection']} | {s['qualified_name']} ({s['kind']})]\n{desc}")
        return "\n\n---\n\n".join(parts)

    from advisor.multi_collection_store import get_multi_collection_store
    vec_store = get_multi_collection_store()
    # Search pyegeria collection with name as query, filtered to high precision
    result = vec_store.search_specific_collections(
        query=name,
        collection_names=["pyegeria"],
        top_k=5,
    )
    if not result.results:
        return f"No symbol found named '{name}'."
    hits = [r for r in result.results if name.lower() in r.text.lower()]
    targets = hits[:3] if hits else result.results[:3]
    parts = []
    for r in targets:
        fp = r.metadata.get("file_path", r.metadata.get("source", ""))
        parts.append(f"[{fp} | score={r.score:.2f}]\n{r.text}")
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Dr.Egeria markdown command template lookup
# ---------------------------------------------------------------------------

def _templates_root() -> Path | None:
    """
    Return the Dr.Egeria templates root directory, or None if not found.

    Candidate paths tried in order:
      1. {pyegeria_root}/Templates/Dr-Egeria-Templates   (case-sensitive, workspace layout)
      2. {pyegeria_root}/templates                       (lower-case fallback)
      3. {EGERIA_ROOT_PATH|PYEGERIA_ROOT_PATH}/Templates/Dr-Egeria-Templates
      4. {EGERIA_ROOT_PATH|PYEGERIA_ROOT_PATH}/templates
      5. {project_root}/examples/templates               (project-local copy, basic/advanced layout)
    """
    import os

    def _try(root: str | Path) -> Path | None:
        root = Path(root)
        for sub in ("Templates/Dr-Egeria-Templates", "templates"):
            p = root / sub
            if p.is_dir():
                return p
        return None

    try:
        from pyegeria.core.config import get_app_config
        root = get_app_config().Environment.pyegeria_root
        if root:
            found = _try(root)
            if found:
                return found
    except Exception:
        pass

    env_root = os.getenv("EGERIA_ROOT_PATH") or os.getenv("PYEGERIA_ROOT_PATH")
    if env_root:
        found = _try(env_root)
        if found:
            return found

    # Project-local copy: {project_root}/examples/templates (basic/ + advanced/ layout).
    project_root = Path(__file__).parent.parent.parent
    local = project_root / "examples" / "templates"
    if local.is_dir():
        return local

    return None


def _normalise(s: str) -> str:
    """Lower-case, strip punctuation/spaces for fuzzy comparison."""
    return re.sub(r"[\s_\-]+", "", s).lower()


def _find_dre_template_raw(query: str, level: str = "basic", perspective: str | None = None) -> str:
    """
    Search the Dr.Egeria template files for commands matching *query*.

    Templates live at {EGERIA_ROOT_PATH}/templates/{level}/{family}/{command}.md.
    When *perspective* is provided the CSV mapping in config/perspective_template_families.csv
    boosts families that are relevant to that role (+1 score), ensuring perspective-appropriate
    templates surface first.  Falls back gracefully if the CSV is missing.
    Returns up to 3 matching template bodies concatenated, or a "not found" message.
    """
    root = _templates_root()
    if root is None:
        return (
            "Dr.Egeria template directory not found. "
            "Run `generate_md_cmd_templates.py` to generate templates, "
            "or set EGERIA_ROOT_PATH / PYEGERIA_ROOT_PATH to the pyegeria workspace root."
        )

    level_dir = root / level
    if not level_dir.is_dir():
        level_dir = root / "basic"
    if not level_dir.is_dir():
        return f"No templates found at {root}."

    query_norm = _normalise(query)

    # Build perspective-relevant family → boost map (+2 for both, +1 for basic).
    priority_families: dict[str, int] = {}
    if perspective:
        mappings = _load_perspective_families()
        for key in (perspective.lower(), "any"):
            for fam, boost in mappings.get(key, {}).items():
                norm = _normalise(fam)
                # Take the higher boost if the same family appears in both "any" and perspective
                priority_families[norm] = max(priority_families.get(norm, 0), boost)

    # Score every template file.
    # Tier 4: exact substring match between full normalised query and stem (or vice-versa).
    # Tier 3: ALL meaningful query words (len > 3) appear in the stem.
    # Tier 2: SOME meaningful query words appear in the stem (count = score within tier).
    # Tier 1: meaningful query words appear in the family name only.
    # Perspective-relevant families get an extra +1 so they surface first within a tier.
    words = [_normalise(w) for w in query.split() if len(w) > 3]
    scored: list[tuple[int, Path]] = []
    for md_file in sorted(level_dir.rglob("*.md")):
        stem_norm = _normalise(md_file.stem)
        family_norm = _normalise(md_file.parent.name)
        score = 0
        if query_norm in stem_norm or stem_norm in query_norm:
            score = 40  # tier 4: exact
        elif words:
            stem_hits = sum(1 for w in words if w in stem_norm)
            if stem_hits == len(words):
                score = 30  # tier 3: all words match stem
            elif stem_hits > 0:
                score = 20 + stem_hits  # tier 2: partial stem match; more hits = higher
            elif any(w in family_norm for w in words):
                score = 10  # tier 1: family match only
        if score > 0:
            score += priority_families.get(family_norm, 0)
            scored.append((score, md_file))

    if not scored:
        # List available families to help the user
        families = sorted({p.parent.name for p in level_dir.rglob("*.md")})
        return (
            f"No Dr.Egeria template found matching '{query}' at {level} level.\n\n"
            f"Available families: {', '.join(families)}\n\n"
            "Try a more specific term (e.g. 'create glossary', 'create term', 'link term')."
        )

    scored.sort(key=lambda x: (-x[0], x[1].stem))
    top = scored[:3]

    parts = []
    for _, md_file in top:
        family = md_file.parent.name
        try:
            content = md_file.read_text(encoding="utf-8")
            parts.append(f"**Family: {family} | Template: {md_file.stem}**\n\n{content}")
        except Exception as exc:
            parts.append(f"[Could not read {md_file}: {exc}]")

    return "\n\n---\n\n".join(parts)


@tool(description=(
    "Find and return Dr.Egeria markdown command samples/examples/templates matching the user's topic. "
    "Use this when the user asks for a Dr.Egeria example, sample, or command — even if they say "
    "'show me how' or 'give me an example' in a Dr.Egeria context. "
    "Templates cover Create, Update, Link, Set, and View operations for Egeria metadata objects "
    "(glossaries, terms, collections, governance definitions, projects, people, reports, etc.). "
    "level should be 'basic' (most users) or 'advanced' (full attribute set). "
    "Returns the raw markdown the user can copy into a Dr.Egeria notebook or file."
))
def find_dre_template(query: str, level: str = "basic") -> str:
    return _find_dre_template_raw(query, level=level)
