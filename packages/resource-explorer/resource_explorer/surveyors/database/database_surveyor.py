"""Database surveyor for custom database surveys."""
from __future__ import annotations

from datetime import datetime

from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors.survey_report import (
    AnnotationType,
    ResourceMeasureAnnotation,
    SchemaAnalysisAnnotation,
)

from .connection import database_connection


class DatabaseSurveyor:
    """Custom surveyor for databases when Egeria can't access them directly."""

    def __init__(
        self,
        db_entity: DatabaseEntity,
        credentials: dict,
        registry: ProjectRegistry,
    ) -> None:
        """Initialize database surveyor.
        
        Args:
            db_entity: DatabaseEntity with connection details
            credentials: Dict with 'user' and 'password' keys
            registry: ProjectRegistry for storing results
        """
        self.db_entity = db_entity
        self.credentials = credentials
        self.registry = registry

    def survey(self) -> dict:
        """Run comprehensive database survey.
        
        Returns:
            Dict with survey results including annotations and statistics
        """
        results = {
            "database_slug": self.db_entity.slug,
            "surveyed_at": datetime.utcnow().isoformat(),
            "source": "custom",
            "annotations": [],
            "schema_info": {},
            "statistics": {},
            "errors": [],
        }

        try:
            with database_connection(self.db_entity, self.credentials) as conn:
                # Survey schema
                schema_info = self._survey_schema(conn)
                results["schema_info"] = schema_info
                results["annotations"].extend(
                    self._create_schema_annotations(schema_info)
                )

                # Survey statistics — non-fatal; proceed even if stats fail
                try:
                    stats_info = self._survey_statistics(conn)
                    results["statistics"] = stats_info
                    results["annotations"].extend(
                        self._create_statistics_annotations(stats_info)
                    )
                except Exception as stats_err:
                    results["errors"].append(f"Statistics query failed (non-fatal): {stats_err}")

                # SQL views static analysis using SQLGlot (non-fatal)
                try:
                    views_info = self._survey_views(conn, schema_info)
                    results["views"] = views_info
                    results["annotations"].extend(
                        self._create_views_annotations(views_info)
                    )
                except Exception as views_err:
                    results["errors"].append(f"SQL view static analysis failed (non-fatal): {views_err}")

        except Exception as e:
            error_msg = str(e)
            results["errors"].append(error_msg)
            from resource_explorer.registry import ProjectStatus
            self.registry.update_database_status(
                self.db_entity.slug, ProjectStatus.ERROR, error_msg
            )
            # Re-raise so the caller can detect failure and return status="error"
            raise

        # Store results regardless of non-fatal errors (stats failures etc.)
        self._store_results(results)
        return results

    def _survey_schema(self, conn) -> dict:
        """Survey database schema structure."""
        return conn.get_schema_info()

    def _survey_statistics(self, conn) -> dict:
        """Survey database statistics."""
        return conn.get_statistics()

    def _create_schema_annotations(self, schema_info: dict) -> list:
        """Create annotations from schema information."""
        annotations = []

        # Overall schema summary
        total_schemas = len(schema_info.get("schemas", []))
        total_tables = schema_info.get("total_tables", 0)
        total_columns = schema_info.get("total_columns", 0)

        annotations.append(
            SchemaAnalysisAnnotation(
                summary=f"Database contains {total_schemas} schemas, {total_tables} tables, {total_columns} columns",
                analysis_step="DatabaseSchemaSurvey",
                schema_name=self.db_entity.database_name,
                schema_type=self.db_entity.db_type,
                confidence=100,
                explanation=(
                    "Aggregate schema inventory for the whole database, computed by RE's "
                    "local scan of the database's own information_schema/catalog tables."
                ),
            )
        )

        # Per-schema annotations
        for schema in schema_info.get("schemas", []):
            schema_name = schema["name"]
            table_count = len(schema["tables"])

            annotations.append(
                SchemaAnalysisAnnotation(
                    summary=f"Schema '{schema_name}' contains {table_count} tables",
                    analysis_step="DatabaseSchemaSurvey",
                    schema_name=schema_name,
                    schema_type="schema",
                    confidence=100,
                    explanation="Table count for one schema within the database, from the local scan.",
                )
            )

            # Per-table annotations (using SchemaAnalysisAnnotation for tables too)
            for table in schema["tables"]:
                table_name = table["name"]
                column_count = len(table["columns"])

                annotations.append(
                    SchemaAnalysisAnnotation(
                        summary=f"Table '{schema_name}.{table_name}' has {column_count} columns",
                        analysis_step="DatabaseSchemaSurvey",
                        schema_name=f"{schema_name}.{table_name}",
                        schema_type="table",
                        confidence=100,
                        explanation="Column count for one table, read directly from the database's own schema catalog.",
                    )
                )

        return annotations

    def _create_statistics_annotations(self, stats_info: dict) -> list:
        """Create annotations from statistics information."""
        annotations = []

        # Database size annotation
        db_size = stats_info.get("database_size", {})
        if db_size:
            size_bytes = db_size.get("size_bytes", 0)
            size_pretty = db_size.get("size_pretty", "unknown")
            annotations.append(
                ResourceMeasureAnnotation(
                    summary=f"Database size: {size_pretty}",
                    analysis_step="DatabaseStatistics",
                    confidence=100,
                    resource_properties={"size_bytes": size_bytes, "size_pretty": size_pretty},
                    explanation=(
                        "Point-in-time on-disk size of the whole database, queried directly "
                        "from the database engine's own size functions."
                    ),
                )
            )

        # Table statistics
        table_stats = stats_info.get("table_stats", [])
        if table_stats:
            largest_tables = table_stats[:5]  # Top 5 largest
            for table in largest_tables:
                schema = table.get("schemaname", "")
                table_name = table.get("tablename", "")
                size = table.get("total_size", "")
                size_bytes = table.get("total_bytes", 0)
                annotations.append(
                    ResourceMeasureAnnotation(
                        summary=f"Table {schema}.{table_name} size: {size}",
                        analysis_step="DatabaseStatistics",
                        confidence=100,
                        resource_properties={
                            "schema": schema,
                            "table": table_name,
                            "size_bytes": size_bytes,
                            "size_pretty": size,
                        },
                        explanation=(
                            "Point-in-time on-disk size for one of the database's largest tables, "
                            "queried directly from the database engine's own statistics views."
                        ),
                    )
                )

        return annotations

    def _store_results(self, results: dict) -> None:
        """Store survey results in the registry."""
        schema_info = results["schema_info"]
        statistics  = results.get("statistics", {})

        # Enrich each table with row count + activity timestamps from pg_stat_user_tables
        row_lookup: dict[tuple, dict] = {
            (rs["schemaname"], rs["tablename"]): rs
            for rs in statistics.get("row_stats", [])
        }
        for schema in schema_info.get("schemas", []):
            for table in schema["tables"]:
                rs = row_lookup.get((schema["name"], table["name"]), {})
                table["row_count"]      = rs.get("row_count", 0)
                table["last_analyzed"]  = rs.get("last_analyzed", "")
                table["last_vacuumed"]  = rs.get("last_vacuumed", "")
                table["pending_changes"] = rs.get("pending_changes", 0)

        # Also enrich size data from table_stats
        size_lookup: dict[tuple, dict] = {
            (ts["schemaname"], ts["tablename"]): ts
            for ts in statistics.get("table_stats", [])
        }
        for schema in schema_info.get("schemas", []):
            for table in schema["tables"]:
                ts = size_lookup.get((schema["name"], table["name"]), {})
                table["size_bytes"] = ts.get("total_bytes", 0) or 0
                table["size_pretty"] = ts.get("total_size", "")

        self.registry.record_database_survey(
            slug=self.db_entity.slug,
            schema_count=len(schema_info.get("schemas", [])),
            table_count=schema_info.get("total_tables", 0),
            column_count=schema_info.get("total_columns", 0),
            survey_data={
                "schema_info": schema_info,
                "statistics": statistics,
                "annotation_count": len(results["annotations"]),
                "views": results.get("views", []),
            },
        )

    def _survey_views(self, conn, schema_info: dict) -> list[dict]:
        """Fetch view definitions and perform static analysis using SQLGlot."""
        db_type = self.db_entity.db_type
        
        # Query view definitions (excluding catalog schemas)
        query = """
            SELECT table_schema, table_name, view_definition
            FROM information_schema.views
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY table_schema, table_name
        """
        rows = conn.execute_query(query)
        if not rows:
            return []

        # Construct SQLGlot schema structure: { table_name: { col_name: type } }
        sqlglot_schema = {}
        for schema in schema_info.get("schemas", []):
            s_name = schema["name"]
            for table in schema["tables"]:
                t_name = table["name"]
                cols = {c["name"]: c["base_type"] or c["type"] for c in table["columns"]}
                # Support both qualified and unqualified lookups
                sqlglot_schema[t_name] = cols
                sqlglot_schema[f"{s_name}.{t_name}"] = cols

        from resource_explorer.surveyors.database.sql_analyzer import SqlAnalyzer

        analyzed_views = []
        for r in rows:
            schema_name = r["table_schema"]
            view_name = r["table_name"]
            view_def = r["view_definition"]
            if not view_def:
                continue

            qualified_view_name = f"{schema_name}.{view_name}"

            # 1. Parse dependencies
            dependencies = SqlAnalyzer.parse_dependencies(view_def, db_type)

            # 2. Complexity metrics
            complexity = SqlAnalyzer.compute_complexity_metrics(view_def, db_type)

            # 3. Column-level lineage
            # Find columns of this view in schema_info to trace them
            view_cols = []
            for schema in schema_info.get("schemas", []):
                if schema["name"] == schema_name:
                    for table in schema["tables"]:
                        if table["name"] == view_name:
                            view_cols = [c["name"] for c in table["columns"]]
                            break

            col_lineage = {}
            for col in view_cols:
                lineage_res = SqlAnalyzer.trace_column_lineage(
                    sql=view_def,
                    target_column=col,
                    schema=sqlglot_schema,
                    db_type=db_type
                )
                if lineage_res:
                    col_lineage[col] = lineage_res

            analyzed_views.append({
                "schema": schema_name,
                "name": view_name,
                "qualified_name": qualified_view_name,
                "definition": view_def,
                "dependencies": dependencies,
                "complexity": complexity,
                "lineage": col_lineage,
            })

        return analyzed_views

    def _create_views_annotations(self, views_info: list[dict]) -> list:
        """Create annotations for parsed view dependencies, complexity, and lineage."""
        import os
        from resource_explorer.surveyors.survey_report import (
            SchemaAnalysisAnnotation,
            RelationshipAnnotation,
            QualityScoreAnnotation,
            RequestForActionAnnotation,
            DataClassAnnotation,
        )
        annotations = []

        # Default fallback PII classification keywords
        pii_keywords = ["email", "phone", "ssn", "socialsec", "creditcard", "password", "dob", "dateofbirth"]

        # Dynamically load PII keywords from Egeria Valid Value Sets if platform connection is configured
        platform_url = os.getenv("EGERIA_PLATFORM_URL")
        if platform_url:
            try:
                from pyegeria.omvs.reference_data import ReferenceDataManager
                view_server = os.getenv("EGERIA_VIEW_SERVER", "view-server")
                user_id = os.getenv("EGERIA_USER", "steward")
                user_pwd = os.getenv("EGERIA_USER_PASSWORD", "steward")

                ref_manager = ReferenceDataManager(view_server, platform_url, user_id, user_pwd)
                ref_manager.create_egeria_bearer_token(user_id, user_pwd)

                egeria_keywords = []
                for dc_name in ["EmailAddress", "PhoneNumber", "SocialSecurityNumber", "CreditCardNumber", "Password", "DateOfBirth"]:
                    try:
                        # Find all ValidValueDefinitions starting with the data class's keyword prefix
                        results = ref_manager.find_valid_value_definitions(
                            search_string=f"ValidValueDefinition::{dc_name}Keyword::",
                            starts_with=True,
                            output_format="JSON"
                        )
                        if isinstance(results, list):
                            for item in results:
                                if isinstance(item, dict):
                                    props = item.get("properties", {})
                                    val = props.get("preferredValue") or props.get("displayName")
                                    if val:
                                        egeria_keywords.append(val.strip().lower())
                    except Exception:
                        pass

                if egeria_keywords:
                    pii_keywords = list(set(egeria_keywords))
            except Exception:
                pass

        def is_pii_column(col_name: str) -> bool:
            name_clean = col_name.lower().replace("_", "").replace("-", "")
            for kw in pii_keywords:
                kw_clean = kw.lower().replace("_", "").replace("-", "")
                if kw_clean in name_clean:
                    return True
            return False

        def extract_leafs(node: dict) -> list[dict]:
            if not node:
                return []
            downstream = node.get("downstream", [])
            if not downstream:
                if node.get("name") and node.get("source"):
                    return [{"source": node["source"], "name": node["name"]}]
                return []
            res = []
            for child in downstream:
                res.extend(extract_leafs(child))
            return res

        for view in views_info:
            view_name = view["name"]
            qualified_name = view["qualified_name"]
            complexity = view["complexity"]
            dependencies = view["dependencies"]

            # 1. Schema Analysis Annotation for the View structural definition
            annotations.append(
                SchemaAnalysisAnnotation(
                    summary=f"View '{qualified_name}' references dependencies: {', '.join(dependencies)}",
                    analysis_step="SQLViewAnalysis",
                    schema_name=qualified_name,
                    schema_type="view",
                    confidence=100,
                    explanation=(
                        f"Static AST dependency check parsed via SQLGlot. "
                        f"Identified {len(dependencies)} source table dependencies."
                    ),
                    json_properties={"dependencies": dependencies}
                )
            )

            # 2. Relationship Advice Annotations (Table to View dependencies)
            for dep in dependencies:
                annotations.append(
                    RelationshipAnnotation(
                        summary=f"View '{qualified_name}' reads from source table '{dep}'",
                        analysis_step="SQLViewAnalysis",
                        confidence=100,
                        related_entity_name=dep,
                        relationship_type_name="LineageMapping",
                        explanation="Design lineage link mapping table dependency extracted from view SQL.",
                    )
                )

            # 3. Quality Score Annotation for Complexity
            annotations.append(
                QualityScoreAnnotation(
                    summary=f"Query complexity metrics for view '{qualified_name}'",
                    analysis_step="SQLViewAnalysis",
                    confidence=100,
                    quality_scores={
                        "complexity_score": float(complexity["complexity_score"]),
                        "portability_rating": float(complexity["portability_rating"]),
                        "node_count": float(complexity["node_count"]),
                        "join_count": float(complexity["join_count"]),
                        "cte_count": float(complexity["cte_count"]),
                        "subquery_count": float(complexity["subquery_count"]),
                    },
                    explanation="Static query complexity rating calculated from AST node size, depth, and joins.",
                )
            )

            # 4. Request for Action Annotation (High Complexity Warning)
            if complexity["complexity_score"] > 40:
                annotations.append(
                    RequestForActionAnnotation(
                        summary=f"High complexity view '{qualified_name}' (Score: {complexity['complexity_score']})",
                        analysis_step="SQLViewAnalysis",
                        confidence=90,
                        action_requested="Refactor view to simplify JOIN logic or use materialized caching.",
                        action_target_name=qualified_name,
                        explanation="Automated warning: view query structure exceeds maintainability thresholds.",
                    )
                )

            # 5. Request for Action Annotation (Portability issues)
            if complexity["portability_rating"] < 80:
                annotations.append(
                    RequestForActionAnnotation(
                        summary=f"Portability warning for view '{qualified_name}'",
                        analysis_step="SQLViewAnalysis",
                        confidence=85,
                        action_requested="Review Snowflake non-portable syntax elements used in view.",
                        action_target_name=qualified_name,
                        explanation="Transpilation test failed to convert Postgres dialect constructs to Snowflake.",
                    )
                )

            # 6. Data Class Annotation for PII propagation
            pii_propagations = []
            for col_name, lin_tree in view.get("lineage", {}).items():
                is_pii = False
                reasons = []

                if is_pii_column(col_name):
                    is_pii = True
                    reasons.append(f"derived column name '{col_name}' matches PII keywords")

                leafs = extract_leafs(lin_tree)
                for leaf in leafs:
                    src_col = leaf["name"]
                    src_tbl = leaf["source"]
                    if is_pii_column(src_col):
                        is_pii = True
                        reasons.append(f"propagates PII from source column '{src_tbl}.{src_col}'")

                if is_pii:
                    pii_propagations.append({
                        "column": col_name,
                        "reasons": sorted(list(set(reasons)))
                    })

            if pii_propagations:
                col_summaries = [f"'{p['column']}' ({', '.join(p['reasons'])})" for p in pii_propagations]
                annotations.append(
                    DataClassAnnotation(
                        summary=f"PII propagation detected in view '{qualified_name}' for columns: {'; '.join(col_summaries)}",
                        analysis_step="SQLViewAnalysis",
                        confidence=95,
                        candidate_data_class_names=["PII", "SensitiveData"],
                        explanation=(
                            f"Static analysis of column-level lineage traced PII/sensitive attributes "
                            f"flowing from physical tables to the view's output attributes."
                        ),
                        json_properties={"pii_propagations": pii_propagations}
                    )
                )

        return annotations


def run_database_survey(
    db_slug: str,
    credentials: dict,
    registry: ProjectRegistry | None = None,
) -> dict:
    """Convenience function to run a database survey.
    
    Args:
        db_slug: Database slug to survey
        credentials: Dict with 'user' and 'password' keys
        registry: Optional ProjectRegistry (creates new one if not provided)
        
    Returns:
        Survey results dict
        
    Example:
        results = run_database_survey(
            "my-postgres",
            {"user": "admin", "password": "secret"}
        )
    """
    if registry is None:
        registry = ProjectRegistry()

    db_entity = registry.get_database(db_slug)
    if not db_entity:
        raise ValueError(f"Database '{db_slug}' not found in registry")

    surveyor = DatabaseSurveyor(db_entity, credentials, registry)
    return surveyor.survey()

# Made with Bob
