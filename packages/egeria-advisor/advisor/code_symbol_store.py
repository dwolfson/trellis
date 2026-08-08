"""DEPRECATED write path — no longer called from the ingestion pipeline
(AST-ownership-transfer plan Phase 8). Resource Explorer now owns code_symbols
/code_relationships-equivalent data (resource_explorer.project_code_symbols /
project_code_relationships) for the repos in RE's "egeria" project group.
Every real consumer of this data (CodeIntelAgent, analytics.py, rag_retrieval.py)
was migrated to read RE's tables directly in Phases 6-7 — this class's own
code_symbols/code_relationships tables are left in place, unwritten, as a
rollback safety net (decision D8), not actively read by anything anymore.

Kept in place, not deleted, for the same reason. The `language` parameter
added to upsert_symbols() (Phase 0) and the ON CONFLICT fix for it are real,
independent bug fixes worth keeping even though this class is otherwise
unused now — if this write path is ever reactivated (rollback), it should
still be correct.

PostgreSQL-backed symbol table for queryable code structure across all ingested collections.

Populated during ingestion alongside pgvector embeddings. Enables direct SQL answers
to structural questions ("what classes does pyegeria have?", "how many methods does
GlossaryManager expose?") without going through vector search.
"""
from __future__ import annotations

from typing import Any
from loguru import logger

from advisor.db_consolidated import get_db_manager


class CodeSymbolStore:
    """Stores and queries code symbols extracted during ingestion in consolidated PostgreSQL."""

    def __init__(self, db_path: Any | None = None) -> None:
        # db_path parameter is ignored but kept for compatibility
        self.db_manager = get_db_manager()
        self.db_manager.connect()
        logger.info("CodeSymbolStore initialized with consolidated PostgreSQL")

    # ── write ──────────────────────────────────────────────────────────────

    def clear_collection(self, collection: str) -> None:
        self.db_manager.execute_update("DELETE FROM code_symbols WHERE collection = %s", (collection,))
        self.db_manager.execute_update("DELETE FROM code_relationships WHERE collection = %s", (collection,))
        logger.info(f"CodeSymbolStore: cleared symbols and relationships for '{collection}'")

    def upsert_symbols(self, collection: str, elements: list[Any], language: str = "python") -> int:
        """Accept a list of CodeElement (advisor/data_prep/code_parser.py, Python) or
        JavaSymbol (advisor/data_prep/java_symbol_extractor.py, Java) objects.

        language must be passed explicitly by the caller — it used to be hardcoded
        to "python" here regardless of what was actually being upserted, so every
        Java symbol landed in the table tagged language='python'. That silently
        broke every `language != 'python'` branch in code_intel_agent.py's query
        filters for Java data. Default stays "python" only for source compatibility
        with any other caller that doesn't pass it explicitly.
        """
        rows = []
        relationships = []
        for el in elements:
            qname = f"{el.parent_class}.{el.name}" if el.parent_class else el.name
            rows.append((
                collection,
                str(el.file_path),
                language,
                el.type,            # class | function | method
                el.name,
                qname,
                el.signature or "",
                (el.docstring or "")[:4000],  # generous cap — guards against pathological outliers, not real docstrings
                el.parent_class or "",
                el.return_type or "",
                el.line_number,
                el.end_line_number,
                bool(el.is_private),
                bool(el.is_async),
                el.complexity,
            ))

            if el.type == 'class':
                for base in getattr(el, 'bases', []):
                    relationships.append((
                        collection,
                        'inherits_from',
                        qname,  # child class qualified name
                        base    # parent class name
                    ))
            elif el.type == 'method' and el.parent_class:
                relationships.append((
                    collection,
                    'contains_method',
                    el.parent_class,  # parent class name
                    el.name           # method name
                ))

        if not rows:
            return 0

        sql = """
            INSERT INTO code_symbols
                (collection, file_path, language, kind, name, qualified_name,
                 signature, docstring, parent_class, return_type,
                 start_line, end_line, is_private, is_async, complexity)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(collection, file_path, qualified_name)
            DO UPDATE SET
                language=EXCLUDED.language,
                kind=EXCLUDED.kind, signature=EXCLUDED.signature,
                docstring=EXCLUDED.docstring, parent_class=EXCLUDED.parent_class,
                return_type=EXCLUDED.return_type, start_line=EXCLUDED.start_line,
                end_line=EXCLUDED.end_line, is_private=EXCLUDED.is_private,
                is_async=EXCLUDED.is_async, complexity=EXCLUDED.complexity
        """

        rel_sql = """
            INSERT INTO code_relationships
                (collection, relationship_type, source_name, target_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (collection, relationship_type, source_name, target_name) DO NOTHING
        """

        conn = self.db_manager.get_connection()
        try:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
                if relationships:
                    cur.executemany(rel_sql, relationships)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to upsert symbols or relationships: {e}")
            raise
        finally:
            self.db_manager.put_connection(conn)

        logger.debug(f"CodeSymbolStore: upserted {len(rows)} symbols and {len(relationships)} relationships into '{collection}'")
        return len(rows)

    # ── aggregate queries ──────────────────────────────────────────────────

    def collection_summary(self, collection: str | None = None) -> dict[str, Any]:
        """Per-collection counts of classes / functions / methods / LOC."""
        where = "WHERE collection = %s" if collection else ""
        params = (collection,) if collection else ()
        sql = f"""
            SELECT collection, kind, COUNT(*) AS n,
            SUM(end_line - start_line + 1) AS loc
            FROM code_symbols {where}
            GROUP BY collection, kind
        """
        rows = self.db_manager.execute_query(sql, params)

        _kind_key = {"class": "classes", "function": "functions", "method": "methods"}
        summary: dict[str, Any] = {}
        for r in rows:
            col = r["collection"]
            if col not in summary:
                summary[col] = {"classes": 0, "functions": 0, "methods": 0, "loc": 0}
            key = _kind_key.get(r["kind"], r["kind"] + "s")
            summary[col][key] = int(r["n"])
            summary[col]["loc"] = summary[col].get("loc", 0) + int(r["loc"] or 0)
        return summary

    def count_by_kind(
        self,
        kind: str,
        collection: str | None = None,
        include_private: bool = True,
    ) -> int:
        parts = ["SELECT COUNT(*) AS count FROM code_symbols WHERE kind = %s"]
        params: list = [kind]
        if collection:
            parts.append("AND collection = %s")
            params.append(collection)
        if not include_private:
            parts.append("AND is_private = FALSE")
        sql = " ".join(parts)
        rows = self.db_manager.execute_query(sql, tuple(params))
        return rows[0]["count"] if rows else 0

    # ── structural queries ─────────────────────────────────────────────────

    def list_classes(
        self,
        collection: str | None = None,
        include_private: bool = False,
    ) -> list[dict]:
        where = ["kind = 'class'"]
        params: list = []
        if collection:
            where.append("collection = %s")
            params.append(collection)
        if not include_private:
            where.append("is_private = FALSE")
        sql = f"""
            SELECT name, collection, file_path, start_line,
            end_line - start_line + 1 AS loc, docstring
            FROM code_symbols
            WHERE {' AND '.join(where)}
            ORDER BY name
        """
        return self.db_manager.execute_query(sql, tuple(params))

    def methods_for_class(
        self,
        class_name: str,
        collection: str | None = None,
        include_private: bool = False,
    ) -> list[dict]:
        where = ["kind = 'method'", "parent_class = %s"]
        params: list = [class_name]
        if collection:
            where.append("collection = %s")
            params.append(collection)
        if not include_private:
            where.append("is_private = FALSE")
        sql = f"""
            SELECT name, signature, return_type, is_async, complexity, docstring
            FROM code_symbols
            WHERE {' AND '.join(where)}
            ORDER BY name
        """
        return self.db_manager.execute_query(sql, tuple(params))

    def search_symbols(
        self,
        name_pattern: str,
        collection: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        where = ["name LIKE %s"]
        params: list = [f"%{name_pattern}%"]
        if collection:
            where.append("collection = %s")
            params.append(collection)
        if kind:
            where.append("kind = %s")
            params.append(kind)
        params.append(limit)
        sql = f"""
            SELECT collection, kind, name, qualified_name, signature,
            parent_class, start_line, docstring
            FROM code_symbols
            WHERE {' AND '.join(where)}
            ORDER BY collection, kind, name
            LIMIT %s
        """
        return self.db_manager.execute_query(sql, tuple(params))

    def most_complex(
        self,
        collection: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        where = ["kind IN ('function','method')"]
        params: list = []
        if collection:
            where.append("collection = %s")
            params.append(collection)
        params.append(limit)
        sql = f"""
            SELECT collection, kind, name, parent_class, complexity,
            start_line, end_line - start_line + 1 AS loc
            FROM code_symbols
            WHERE {' AND '.join(where)}
            ORDER BY complexity DESC LIMIT %s
        """
        return self.db_manager.execute_query(sql, tuple(params))

    def largest_classes(
        self,
        collection: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        where = ["kind = 'class'"]
        params: list = []
        if collection:
            where.append("collection = %s")
            params.append(collection)
        params.append(limit)
        sql = f"""
            SELECT collection, name,
            end_line - start_line + 1 AS loc,
            (SELECT COUNT(*) FROM code_symbols m
             WHERE m.parent_class = code_symbols.name
             AND m.collection = code_symbols.collection
             AND m.kind = 'method') AS method_count
            FROM code_symbols
            WHERE {' AND '.join(where)}
            ORDER BY method_count DESC LIMIT %s
        """
        return self.db_manager.execute_query(sql, tuple(params))

    def file_summary(
        self,
        collection: str,
        file_path: str,
    ) -> dict[str, Any]:
        sql = """
            SELECT kind, COUNT(*) AS n FROM code_symbols
            WHERE collection=%s AND file_path=%s GROUP BY kind
        """
        rows = self.db_manager.execute_query(sql, (collection, file_path))
        return {r["kind"] + "s": int(r["n"]) for r in rows}


# ── singleton ──────────────────────────────────────────────────────────────

_store: CodeSymbolStore | None = None


def get_symbol_store() -> CodeSymbolStore:
    global _store
    if _store is None:
        _store = CodeSymbolStore()
    return _store
