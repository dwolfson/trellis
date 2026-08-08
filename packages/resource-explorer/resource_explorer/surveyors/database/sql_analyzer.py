"""SQL Static Analyzer using sqlglot for view dependency, lineage and complexity metrics."""
from __future__ import annotations

import logging
import sqlglot
from sqlglot import parse_one, transpile
from sqlglot.expressions import Table, Expression
from sqlglot.lineage import lineage

log = logging.getLogger(__name__)


class SqlAnalyzer:
    """Helper for static analysis of SQL views and stored procedures."""

    @staticmethod
    def get_dialect(db_type: str) -> str:
        """Map database type to SQLGlot dialect name."""
        mapping = {
            "postgresql": "postgres",
            "postgres": "postgres",
            "snowflake": "snowflake",
            "bigquery": "bigquery",
            "sqlite": "sqlite",
            "duckdb": "duckdb",
            "mysql": "mysql",
            "oracle": "oracle",
        }
        return mapping.get(db_type.lower(), "postgres")

    @classmethod
    def parse_dependencies(cls, sql: str, db_type: str = "postgres") -> list[str]:
        """Extract all source table names referenced in a query."""
        dialect = cls.get_dialect(db_type)
        try:
            expression = parse_one(sql, read=dialect)
            tables = []
            for table in expression.find_all(Table):
                # Return the qualified name or simple name
                if table.db:
                    tables.append(f"{table.db}.{table.name}")
                else:
                    tables.append(table.name)
            return sorted(list(set(tables)))
        except Exception as e:
            log.warning(f"Failed to parse SQL dependencies: {e}")
            return []

    @classmethod
    def trace_column_lineage(
        cls,
        sql: str,
        target_column: str,
        schema: dict,
        db_type: str = "postgres"
    ) -> dict | None:
        """Trace column-level lineage from a query back to its source columns.
        
        Args:
            sql: The SELECT query or view definition
            target_column: Column name in the query output to trace
            schema: dict of { table_name: { col_name: type } }
            db_type: database type (e.g. 'postgres')
            
        Returns:
            Dict representing column lineage graph node or None
        """
        dialect = cls.get_dialect(db_type)
        try:
            # sqlglot.lineage.lineage returns a Node tree
            node = lineage(
                column=target_column,
                sql=sql,
                schema=schema,
                dialect=dialect
            )
            return cls._serialize_lineage_node(node)
        except Exception as e:
            log.debug(f"Failed to trace lineage for column '{target_column}': {e}")
            return None

    @classmethod
    def _serialize_lineage_node(cls, node) -> dict:
        """Recursively serialize a sqlglot lineage Node to a dict."""
        res = {
            "expression": str(node.expression),
            "source": str(node.source) if hasattr(node, "source") else "",
            "name": node.name,
            "downstream": []
        }
        # Visit downstream source nodes
        for downstream_node in node.downstream:
            res["downstream"].append(cls._serialize_lineage_node(downstream_node))
        return res

    @classmethod
    def compute_complexity_metrics(cls, sql: str, db_type: str = "postgres") -> dict:
        """Compute structural complexity scores of a query using its AST.
        
        Returns:
            Dict containing:
                - node_count: Total AST nodes (rough query size)
                - max_depth: Maximum tree depth
                - join_count: Number of JOIN operations
                - cte_count: Number of CTEs (Common Table Expressions)
                - subquery_count: Number of nested subqueries
                - complexity_score: Computed overall rating (0-100)
                - portability_rating: Score based on transpilation warnings
        """
        dialect = cls.get_dialect(db_type)
        metrics = {
            "node_count": 0,
            "max_depth": 0,
            "join_count": 0,
            "cte_count": 0,
            "subquery_count": 0,
            "complexity_score": 0,
            "portability_rating": 100,
        }

        try:
            expression = parse_one(sql, read=dialect)
            
            # Count AST nodes & calculate max depth
            node_count = 0
            max_depth = 0
            
            def walk(node, depth=1):
                nonlocal node_count, max_depth
                node_count += 1
                max_depth = max(max_depth, depth)
                for child in node.iter_expressions():
                    walk(child, depth + 1)

            walk(expression)
            metrics["node_count"] = node_count
            metrics["max_depth"] = max_depth

            # Find specific operations
            from sqlglot.expressions import Join, CTE, Subquery
            metrics["join_count"] = len(list(expression.find_all(Join)))
            metrics["cte_count"] = len(list(expression.find_all(CTE)))
            metrics["subquery_count"] = len(list(expression.find_all(Subquery)))

            # Overall complexity score logic (simple heuristic 0-100)
            score = (
                (metrics["node_count"] * 0.2) +
                (metrics["max_depth"] * 1.5) +
                (metrics["join_count"] * 10) +
                (metrics["cte_count"] * 5) +
                (metrics["subquery_count"] * 8)
            )
            metrics["complexity_score"] = min(100, int(score))

            # Portability test: try to transpile to standard SQL
            try:
                transpile(sql, read=dialect, write="snowflake")
            except Exception:
                # Transpilation to cloud target failed/warned
                metrics["portability_rating"] = 50

        except Exception as e:
            log.warning(f"Error computing complexity metrics: {e}")
            metrics["complexity_score"] = -1  # Parsing error

        return metrics
