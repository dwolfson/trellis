"""Code intelligence agent — answers maintainer-focused queries about codebase structure, inheritance, methods, and stats."""
from __future__ import annotations

import re
from typing import Any, Optional, Dict, List
from loguru import logger

from advisor.agents.base import BaseAdvisorAgent
from advisor.db_consolidated import get_db_manager


def _resolve_symbol_name(words: List[str], kinds: tuple = ("class",)) -> str:
    """
    Resolve regex-split query words to an actual indexed symbol name of the given kind(s).

    Class names are stored CamelCase ("AutomatedCuration"); method/function names are
    snake_case ("create_glossary"). Users naturally type either with spaces
    ("Automated Curation", "create glossary"). Try the full no-separator concatenation
    (covers CamelCase) and the full underscore join (covers snake_case) first, then each
    individual word, checking existence case-insensitively against code_symbols. Falls
    back to the concatenation (as a readable label for a "not found" message) if nothing
    matches.
    """
    if not words:
        return ""
    db = get_db_manager()
    concat = "".join(words)
    snake = "_".join(words)
    candidates = []
    for cand in (concat, snake, *words):
        if cand not in candidates:
            candidates.append(cand)
    kind_clause = " OR ".join(["kind = %s"] * len(kinds))
    for cand in candidates:
        rows = db.execute_query(
            f"SELECT name FROM code_symbols WHERE ({kind_clause}) AND name ILIKE %s LIMIT 1",
            tuple(kinds) + (cand,)
        )
        if rows:
            return rows[0]["name"]
    return concat

def _relative_path(file_path: str) -> str:
    """
    Convert an indexed absolute file path to one relative to its source repo root
    (e.g. ".../data/repos/egeria-python/pyegeria/omvs/x.py" -> "pyegeria/omvs/x.py").

    All indexed source lives under data/repos/<repo-name>/... — strip everything up
    to and including that <repo-name> segment. Falls back to the original path if
    the marker isn't found (e.g. paths outside data/repos/).
    """
    marker = "data/repos/"
    idx = file_path.find(marker)
    if idx == -1:
        return file_path
    rest = file_path[idx + len(marker):]
    parts = rest.split("/", 1)
    return parts[1] if len(parts) == 2 else rest

def _relativize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply _relative_path() to the 'file_path' field of each row, in place."""
    for row in rows:
        if row.get("file_path"):
            row["file_path"] = _relative_path(row["file_path"])
    return rows

# Tools to be exposed to the LLM / direct executor
def get_class_for_method(method_name: str, collection: Optional[str] = None) -> List[Dict[str, Any]]:
    """Find a method or standalone function's definition: parent class (if any), file path, line number, signature, and docstring."""
    db = get_db_manager()
    where_clause = "WHERE kind IN ('method', 'function') AND name ILIKE %s"
    params = [method_name]
    if collection:
        where_clause += " AND collection = %s"
        params.append(collection)
        if collection == "pyegeria":
            where_clause += """
                AND file_path LIKE '%%/pyegeria/%%'
                AND file_path NOT LIKE '%%/tests/%%'
                AND file_path NOT LIKE '%%/my_egeria/%%'
                AND file_path NOT LIKE '%%/md_processing/%%'
                AND file_path NOT LIKE '%%/examples/%%'
                AND file_path NOT LIKE '%%/commands/%%'
            """
    else:
        where_clause += """
            AND (language != 'python' OR (
                file_path LIKE '%%/pyegeria/%%'
                AND file_path NOT LIKE '%%/tests/%%'
                AND file_path NOT LIKE '%%/my_egeria/%%'
                AND file_path NOT LIKE '%%/md_processing/%%'
                AND file_path NOT LIKE '%%/examples/%%'
                AND file_path NOT LIKE '%%/commands/%%'
            ))
        """
    sql = f"""
        SELECT name, parent_class, collection, file_path, start_line, signature, docstring
        FROM code_symbols
        {where_clause}
        ORDER BY parent_class
    """
    return _relativize_rows(db.execute_query(sql, tuple(params)))

def get_class_info(class_name: str, collection: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get a class's own definition: its docstring, file path, line numbers, and signature."""
    db = get_db_manager()
    where_clause = "WHERE kind = 'class' AND name ILIKE %s"
    params = [class_name]
    if collection:
        where_clause += " AND collection = %s"
        params.append(collection)
        if collection == "pyegeria":
            where_clause += """
                AND file_path LIKE '%%/pyegeria/%%'
                AND file_path NOT LIKE '%%/tests/%%'
                AND file_path NOT LIKE '%%/my_egeria/%%'
                AND file_path NOT LIKE '%%/md_processing/%%'
                AND file_path NOT LIKE '%%/examples/%%'
                AND file_path NOT LIKE '%%/commands/%%'
            """
    else:
        where_clause += """
            AND (language != 'python' OR (
                file_path LIKE '%%/pyegeria/%%'
                AND file_path NOT LIKE '%%/tests/%%'
                AND file_path NOT LIKE '%%/my_egeria/%%'
                AND file_path NOT LIKE '%%/md_processing/%%'
                AND file_path NOT LIKE '%%/examples/%%'
                AND file_path NOT LIKE '%%/commands/%%'
            ))
        """
    sql = f"""
        SELECT name, collection, file_path, start_line, end_line, signature, docstring, parent_class
        FROM code_symbols
        {where_clause}
        ORDER BY collection
    """
    return _relativize_rows(db.execute_query(sql, tuple(params)))

def check_inheritance(class_a: str, class_b: str, collection: Optional[str] = None) -> Dict[str, Any]:
    """Check if class_a inherits from class_b (directly or recursively), returning the path if found."""
    db = get_db_manager()
    col_filter = "AND collection = %s" if collection else ""
    anchor_params = [class_a]
    if collection:
        anchor_params.append(collection)
    
    sql = f"""
        WITH RECURSIVE inheritance_path AS (
            SELECT source_name, target_name, 1 AS depth, collection
            FROM code_relationships
            WHERE relationship_type = 'inherits_from' AND source_name ILIKE %s {col_filter}

            UNION ALL

            SELECT r.source_name, r.target_name, ip.depth + 1, r.collection
            FROM code_relationships r
            JOIN inheritance_path ip ON r.source_name = ip.target_name AND r.collection = ip.collection
            WHERE r.relationship_type = 'inherits_from' AND ip.depth < 10
        )
        SELECT source_name, target_name, depth, collection FROM inheritance_path WHERE target_name ILIKE %s
    """
    params = anchor_params + [class_b]
    rows = db.execute_query(sql, tuple(params))
    if rows:
        return {
            "inherits": True,
            "path": rows,
            "message": f"Yes, {class_a} inherits from {class_b}."
        }
    else:
        return {
            "inherits": False,
            "path": [],
            "message": f"No, {class_a} does not inherit from {class_b}."
        }

def list_classes(collection: Optional[str] = None) -> List[str]:
    """List all the class names defined in a specific collection (e.g. 'pyegeria' or 'egeria_java')."""
    db = get_db_manager()
    where_clause = "WHERE kind = 'class'"
    params = []
    if collection:
        where_clause += " AND collection = %s"
        params.append(collection)
        if collection == "pyegeria":
            where_clause += """
                AND file_path LIKE '%%/pyegeria/%%'
                AND file_path NOT LIKE '%%/tests/%%'
                AND file_path NOT LIKE '%%/my_egeria/%%'
                AND file_path NOT LIKE '%%/md_processing/%%'
                AND file_path NOT LIKE '%%/examples/%%'
                AND file_path NOT LIKE '%%/commands/%%'
            """
    else:
        where_clause += """
            AND (language != 'python' OR (
                file_path LIKE '%%/pyegeria/%%'
                AND file_path NOT LIKE '%%/tests/%%'
                AND file_path NOT LIKE '%%/my_egeria/%%'
                AND file_path NOT LIKE '%%/md_processing/%%'
                AND file_path NOT LIKE '%%/examples/%%'
                AND file_path NOT LIKE '%%/commands/%%'
            ))
        """
    sql = f"""
        SELECT name, file_path 
        FROM code_symbols 
        {where_clause}
        ORDER BY name
    """
    rows = db.execute_query(sql, tuple(params))

    results = []
    for r in rows:
        results.append(f"{r['name']} (in {_relative_path(r['file_path'])})")
    return results

def get_class_hierarchy(class_name: str, collection: Optional[str] = None) -> Dict[str, Any]:
    """Get the ancestors (parents) and descendants (children) of a class in the codebase."""
    db = get_db_manager()
    
    # Ancestors
    anc_sql = """
        WITH RECURSIVE ancestors AS (
            SELECT source_name, target_name, 1 AS depth, collection
            FROM code_relationships
            WHERE relationship_type = 'inherits_from' AND source_name ILIKE %s
            UNION ALL
            SELECT r.source_name, r.target_name, a.depth + 1, r.collection
            FROM code_relationships r
            JOIN ancestors a ON r.source_name = a.target_name AND r.collection = a.collection
            WHERE r.relationship_type = 'inherits_from' AND a.depth < 10
        )
        SELECT target_name AS class_name, depth, collection FROM ancestors
    """
    anc_params = [class_name]
    if collection:
        anc_sql = """
            WITH RECURSIVE ancestors AS (
                SELECT source_name, target_name, 1 AS depth, collection
                FROM code_relationships
                WHERE relationship_type = 'inherits_from' AND source_name ILIKE %s AND collection = %s
                UNION ALL
                SELECT r.source_name, r.target_name, a.depth + 1, r.collection
                FROM code_relationships r
                JOIN ancestors a ON r.source_name = a.target_name AND r.collection = a.collection
                WHERE r.relationship_type = 'inherits_from' AND a.depth < 10
            )
            SELECT target_name AS class_name, depth, collection FROM ancestors
        """
        anc_params = [class_name, collection]
        
    ancestors = db.execute_query(anc_sql, tuple(anc_params))
    
    # Descendants
    dec_sql = """
        WITH RECURSIVE descendants AS (
            SELECT source_name, target_name, 1 AS depth, collection
            FROM code_relationships
            WHERE relationship_type = 'inherits_from' AND target_name ILIKE %s
            UNION ALL
            SELECT r.source_name, r.target_name, d.depth + 1, r.collection
            FROM code_relationships r
            JOIN descendants d ON r.target_name = d.source_name AND r.collection = d.collection
            WHERE r.relationship_type = 'inherits_from' AND d.depth < 10
        )
        SELECT source_name AS class_name, depth, collection FROM descendants
    """
    dec_params = [class_name]
    if collection:
        dec_sql = """
            WITH RECURSIVE descendants AS (
                SELECT source_name, target_name, 1 AS depth, collection
                FROM code_relationships
                WHERE relationship_type = 'inherits_from' AND target_name ILIKE %s AND collection = %s
                UNION ALL
                SELECT r.source_name, r.target_name, d.depth + 1, r.collection
                FROM code_relationships r
                JOIN descendants d ON r.target_name = d.source_name AND r.collection = d.collection
                WHERE r.relationship_type = 'inherits_from' AND d.depth < 10
            )
            SELECT source_name AS class_name, depth, collection FROM descendants
        """
        dec_params = [class_name, collection]
        
    descendants = db.execute_query(dec_sql, tuple(dec_params))
    
    return {
        "class_name": class_name,
        "ancestors": ancestors,
        "descendants": descendants
    }

def get_codebase_stats(collection: Optional[str] = None) -> Dict[str, Any]:
    """Get statistics about the codebase (counts of classes, methods, functions, total lines of code)."""
    db = get_db_manager()
    where_clause = ""
    params = []
    
    if collection:
        where_clause = "WHERE collection = %s"
        params.append(collection)
        if collection == "pyegeria":
            where_clause += """
                AND file_path LIKE '%%/pyegeria/%%'
                AND file_path NOT LIKE '%%/tests/%%'
                AND file_path NOT LIKE '%%/my_egeria/%%'
                AND file_path NOT LIKE '%%/md_processing/%%'
                AND file_path NOT LIKE '%%/examples/%%'
                AND file_path NOT LIKE '%%/commands/%%'
            """
    else:
        where_clause = """
            WHERE (language != 'python' OR (
                file_path LIKE '%%/pyegeria/%%'
                AND file_path NOT LIKE '%%/tests/%%'
                AND file_path NOT LIKE '%%/my_egeria/%%'
                AND file_path NOT LIKE '%%/md_processing/%%'
                AND file_path NOT LIKE '%%/examples/%%'
                AND file_path NOT LIKE '%%/commands/%%'
            ))
        """
    
    sql = f"""
        SELECT kind, COUNT(*) AS count, SUM(end_line - start_line + 1) AS total_loc
        FROM code_symbols
        {where_clause}
        GROUP BY kind
    """
    rows = db.execute_query(sql, tuple(params))
    
    stats = {
        "classes": 0,
        "methods": 0,
        "functions": 0,
        "total_loc": 0
    }
    for r in rows:
        kind = r["kind"]
        count = int(r["count"])
        loc = int(r["total_loc"] or 0)
        if kind == "class":
            stats["classes"] = count
        elif kind == "method":
            stats["methods"] = count
        elif kind == "function":
            stats["functions"] = count
        stats["total_loc"] += loc
        
    return stats

def _format_class_info(info: List[Dict[str, Any]]) -> str:
    """Render get_class_info() results as clean text (real newlines, not a dict repr)."""
    blocks = []
    for row in info:
        blocks.append(
            f"Class: {row['name']} (collection: {row['collection']})\n"
            f"File: {row['file_path']} (lines {row['start_line']}-{row['end_line']})\n"
            f"Signature: {row['signature']}\n"
            f"Docstring:\n{row['docstring'] or '(no docstring)'}"
        )
    return "\n\n".join(blocks)

def _format_method_info(rows: List[Dict[str, Any]]) -> str:
    """Render get_class_for_method() results as clean text (real newlines, not a dict repr)."""
    blocks = []
    for row in rows:
        parent = row.get("parent_class") or None
        header = f"Method: {row['name']} (in class {parent})" if parent else f"Function: {row['name']} (module-level, no parent class)"
        blocks.append(
            f"{header}\n"
            f"Collection: {row['collection']}\n"
            f"File: {row['file_path']} (line {row['start_line']})\n"
            f"Signature: {row['signature']}\n"
            f"Docstring:\n{row['docstring'] or '(no docstring)'}"
        )
    return "\n\n".join(blocks)

def _format_class_hierarchy(hierarchy: Dict[str, Any]) -> str:
    """Render get_class_hierarchy() results as clean text (real newlines, not a dict repr)."""
    lines = [f"Class: {hierarchy['class_name']}"]
    if hierarchy["ancestors"]:
        lines.append("Ancestors (parents):")
        for a in sorted(hierarchy["ancestors"], key=lambda x: x["depth"]):
            lines.append(f"  - {a['class_name']} (depth {a['depth']}, collection {a['collection']})")
    if hierarchy["descendants"]:
        lines.append("Descendants (children):")
        for d in sorted(hierarchy["descendants"], key=lambda x: x["depth"]):
            lines.append(f"  - {d['class_name']} (depth {d['depth']}, collection {d['collection']})")
    return "\n".join(lines)

class CodeIntelAgent(BaseAdvisorAgent):
    def system_prompt(self) -> str:
        return (
            "You are an expert Egeria codebase advisor. You answer maintainer queries about the "
            "structural relationships, inheritance, method containment, class listings, and statistics of the codebase.\n\n"
            "Workflow:\n"
            "1. Identify the structural question being asked:\n"
            "   - If the user wants to know what a class is / does (a description or definition), call get_class_info.\n"
            "   - If the user wants to know what a method/function is/does, its signature, docstring, or where "
            "it is defined, call get_class_for_method.\n"
            "   - If the user wants to check if class A inherits from class B, call check_inheritance.\n"
            "   - If the user wants the hierarchy of a class (parents/children), call get_class_hierarchy.\n"
            "   - If the user wants to list all classes in a collection, call list_classes.\n"
            "   - If the user wants overall statistics or line counts, call get_codebase_stats.\n"
            "   - For a general 'what is X' about a class, call BOTH get_class_info and get_class_hierarchy "
            "and combine the docstring with the hierarchy in your answer.\n"
            "2. Use the database results to form a clear, direct, and factual answer.\n\n"
            "Rules:\n"
            "- Ground all your answers strictly in the tool outputs.\n"
            "- Provide the specific file paths and line numbers if returned by the tools.\n"
            "- If a query has no matching elements, state clearly that you could not find those symbols in the indexed codebase.\n\n"
            "CODEBASE ORGANIZATION REFERENCE:\n"
            "- **Egeria** (Java repository): The core Java implementation of the Egeria backend metadata platform, servers, OMAS, OMAG, and OMRS services (collection: 'egeria_java').\n"
            "- **egeria-python** (Python repository): The repository containing Python-based Egeria client code and tooling. It is organized into:\n"
            "  1. `pyegeria` (under `pyegeria/` directory): The Python client SDK API library used to communicate with Egeria backend servers (collection: 'pyegeria').\n"
            "  2. `commands` (under `commands/` directory): Command-line tools (CLI) and interactive commands (like `hey_egeria`) written in Python using the `pyegeria` SDK.\n"
            "  3. `dr_egeria` (under `md_processing/` directory): The Python implementation of the Dr. Egeria markdown processor which is used to parse, draft, and execute governance metadata template plans."
        )

    def tools(self) -> list:
        return [get_class_info, get_class_for_method, check_inheritance, get_class_hierarchy, get_codebase_stats, list_classes]

    def handle(self, query: str) -> dict:
        logger.info(f"CodeIntelAgent handling query: {query}")
        
        from advisor.llm_client import get_ollama_client
        
        # Identify intent from query text
        q_lower = query.lower()
        context = ""
        
        try:
            if "stats" in q_lower or "how many" in q_lower or "statistics" in q_lower or "lines of code" in q_lower:
                stats = get_codebase_stats()
                context = f"Codebase Stats:\n{stats}"
            elif "list classes" in q_lower or "what classes" in q_lower or "classes in" in q_lower or "what are the classes" in q_lower:
                col = None
                if "python" in q_lower or "pyegeria" in q_lower:
                    col = "pyegeria"
                elif "java" in q_lower or ("egeria" in q_lower and "python" not in q_lower and "pyegeria" not in q_lower):
                    col = "egeria_java"
                
                if col is None:
                    response = (
                        "I can list classes for either the **Java Egeria backend** codebase (`egeria_java`) "
                        "or the **egeria-python** client SDK (`pyegeria`).\n\n"
                        "Please clarify which repository codebase you would like to inspect by specifying "
                        "**Java** or **Python** (e.g. 'list classes in python' or 'list classes in java')."
                    )
                    return {
                        "query": query,
                        "response": response,
                        "query_type": "code_intel",
                        "sources": [],
                        "num_sources": 0,
                        "retrieval_time": 0.0,
                        "generation_time": 0.0,
                        "avg_relevance_score": 1.0,
                        "context_length": len(response)
                    }
                
                classes_list = list_classes(col)
                collection_desc = "the 'egeria-python' (pyegeria) Python SDK codebase" if col == "pyegeria" else "the Egeria Java backend codebase"
                if len(classes_list) > 30:
                    truncated = classes_list[:30]
                    context = (
                        f"Found {len(classes_list)} classes defined in {collection_desc}.\n"
                        f"Due to the large number of classes, only the first 30 are listed below. "
                        f"Please inform the user of the total class count ({len(classes_list)}) "
                        f"and list some notable examples from this list:\n"
                        + "\n".join(f"- {c}" for c in truncated)
                    )
                else:
                    context = f"Found {len(classes_list)} classes defined in {collection_desc}:\n" + "\n".join(f"- {c}" for c in classes_list)
            elif "inherit" in q_lower or "extends" in q_lower:
                # Try to extract class names using simple regex
                words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', query)
                # Filter out python keywords/common query words
                ignore = {"does", "inherit", "from", "class", "extends", "a", "b", "is", "an", "inherits", "subclass", "superclass", "parent"}
                classes = [w for w in words if w.lower() not in ignore]
                if len(classes) >= 2:
                    res = check_inheritance(classes[0], classes[1])
                    context = f"Inheritance Check ({classes[0]} -> {classes[1]}):\n{res}"
                else:
                    context = "Could not identify class names for inheritance check."
            elif "method" in q_lower or "function" in q_lower or "defined in" in q_lower or "what class is" in q_lower or "in which class" in q_lower:
                # Find method/function name — questions specifically about a method or
                # function's own definition (signature, docstring, containing class).
                words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', query)
                ignore = {
                    "what", "class", "is", "method", "defined", "in", "function",
                    "defined_in", "where", "find", "locate", "does", "do", "the",
                    "a", "an", "tell", "me", "about", "describe", "explain"
                }
                methods = [w for w in words if w.lower() not in ignore]
                if methods:
                    method_name = _resolve_symbol_name(methods, ("method", "function"))
                    res = get_class_for_method(method_name)
                    if res:
                        context = _format_method_info(res)
                    else:
                        context = f"No method or function named '{method_name}' found in the indexed codebase."
                else:
                    context = "Could not identify method name for definition lookup."
            else:
                # Default: bare-name questions ("what is X", "describe X", "tell me
                # about X", "class hierarchy for X"). X could be a class or a
                # method/function — try class first (plus its hierarchy), and fall
                # back to a method/function lookup if no class matches.
                words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', query)
                ignore = {
                    "hierarchy", "parents", "children", "ancestors", "descendants",
                    "what", "is", "the", "for", "class", "show", "does", "do", "tell",
                    "me", "about", "describe", "explain"
                }
                names = [w for w in words if w.lower() not in ignore]
                if names:
                    class_name = _resolve_symbol_name(names, ("class",))
                    info = get_class_info(class_name)
                    if info:
                        parts = [_format_class_info(info)]
                        hierarchy = get_class_hierarchy(class_name)
                        if hierarchy["ancestors"] or hierarchy["descendants"]:
                            parts.append(_format_class_hierarchy(hierarchy))
                        context = "\n\n".join(parts)
                    else:
                        method_name = _resolve_symbol_name(names, ("method", "function"))
                        method_info = get_class_for_method(method_name)
                        if method_info:
                            context = _format_method_info(method_info)
                        else:
                            context = f"No class, method, or function named '{class_name}' found in the indexed codebase."
                else:
                    context = "Could not identify a class or method/function name for lookup."
        except Exception as e:
            logger.warning(f"CodeIntelAgent direct tool execution failed: {e}")
            context = f"Error querying codebase relationships: {e}"

        system = (
            "You are an expert Egeria codebase advisor. Answer the structural codebase question based ONLY "
            "on the provided query results. If the results are empty or do not contain the answer, say so "
            "explicitly — do not invent information.\n"
            "CRITICAL: Do NOT output or guess external GitHub repository URLs, website links, or directory paths "
            "unless they are explicitly present in the provided query results. Be very clear and output specific "
            "file paths and line numbers.\n"
            "When a 'signature' field is present in the query results, always include it verbatim (e.g. in a "
            "code block). When a 'docstring' field is present, quote it in full — do not paraphrase or "
            "summarize it down to one sentence; the user wants the actual documented description, not a gloss."
        )

        prompt = (
            f"Query Results:\n{context}\n\n"
            f"Question: {query}\n\n"
            "Provide a maintainer-oriented answer. Include the full signature and full docstring text from the "
            "query results verbatim where present, plus file path and line numbers."
        )

        try:
            response = get_ollama_client().generate(prompt, system=system, max_tokens=1500)
        except Exception as exc:
            response = f"Unable to generate response: {exc}"
            
        return {
            "query": query,
            "response": response,
            "query_type": "code_intel",
            "sources": [],
            "num_sources": 0,
            "retrieval_time": 0.0,
            "generation_time": 0.0,
            "avg_relevance_score": 1.0,
            "context_length": len(response)
        }

_agent: CodeIntelAgent | None = None

def get_code_intel_agent() -> CodeIntelAgent:
    global _agent
    if _agent is None:
        _agent = CodeIntelAgent()
    return _agent
