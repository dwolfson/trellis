"""Cross-asset static dependency matcher.

Deterministically links code repositories to registered databases by cross-referencing
extracted code symbols, ORM models, SQL migration patterns, and dependencies against
database schemas and table inventories stored in ProjectRegistry.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from resource_explorer.registry import _survey_schema_info

if TYPE_CHECKING:
    from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)


def find_cross_asset_links(
    registry: ProjectRegistry,
    repo_slug: str | None = None,
    database_slug: str | None = None,
) -> list[dict]:
    """Find deterministic linkages between code repositories and cataloged databases.

    Cross-references:
      - ORM model/entity class names with database table names (e.g. Order -> orders/order)
      - Database driver & ORM dependencies (psycopg2, sqlalchemy, spring-boot-starter-data-jpa)
      - SQL / database references found in symbols and schemas
    """
    databases = registry.list_databases()
    if not databases:
        return []

    # Map database slug -> set of table names (lowercased) + db properties
    db_tables_map: dict[str, dict] = {}
    for db in databases:
        if database_slug and db.slug != registry._normalize_slug(database_slug):
            continue
        survey = registry.get_latest_database_survey(db.slug)
        tables = set()
        schemas = set()
        info = _survey_schema_info(survey) if survey else {}
        for sch in info.get("schemas", []):
            sname = sch.get("name", "")
            if sname:
                schemas.add(sname.lower())
            for tbl in sch.get("tables", []):
                tname = tbl.get("name", "")
                if tname:
                    tables.add(tname.lower())
        db_tables_map[db.slug] = {
            "entity": db,
            "schemas": schemas,
            "tables": tables,
            "db_type": db.db_type,
            "db_name": (db.database_name or "").lower(),
        }

    repos = registry.list_all()
    if repo_slug:
        norm_repo = registry._normalize_slug(repo_slug)
        repos = [r for r in repos if r.slug == norm_repo]

    links: list[dict] = []

    for repo in repos:
        # 1. Inspect repository dependencies
        deps = registry.query_dependencies(repo.slug)
        dep_names = {d.get("dep_name", "").lower() for d in deps} if deps else set()

        db_driver_deps = {
            "postgresql": {"psycopg2", "psycopg2-binary", "asyncpg", "org.postgresql:postgresql", "r2dbc-postgresql"},
            "mysql": {"mysql-connector-python", "mysqlclient", "pymysql", "mysql:mysql-connector-java"},
            "sqlite": {"sqlite3", "org.xerial:sqlite-jdbc"},
            "oracle": {"cx_oracle", "oracledb", "com.oracle.database.jdbc:ojdbc8"},
        }
        orm_deps = {
            "sqlalchemy", "django", "tortoise-orm", "peewee", "hibernate",
            "org.springframework.boot:spring-boot-starter-data-jpa",
            "flyway", "liquibase", "alembic"
        }

        has_orm = bool(dep_names & orm_deps)

        # 2. Inspect repository code symbols
        symbol_names = set()
        try:
            with registry._conn() as conn:
                rows = conn.execute(
                    "SELECT name, qualified_name FROM project_code_symbols WHERE project_slug = ? LIMIT 500",
                    (repo.slug,),
                ).fetchall()
                for r in rows:
                    if r["name"]:
                        symbol_names.add(r["name"].lower())
                    if r["qualified_name"]:
                        symbol_names.add(r["qualified_name"].lower())
        except Exception:
            pass

        for db_s, db_info in db_tables_map.items():
            matched_tables: list[str] = []
            matched_evidence: list[str] = []
            score = 0.0

            db_tables = db_info["tables"]
            db_type = db_info["db_type"].lower()
            db_name = db_info["db_name"]

            # Check driver dependency match
            driver_set = db_driver_deps.get(db_type, set())
            matched_drivers = dep_names & driver_set
            if matched_drivers:
                score += 0.3
                matched_evidence.append(f"Matching DB drivers in dependencies: {', '.join(matched_drivers)}")

            if has_orm:
                score += 0.1
                matched_evidence.append("ORM / Migration framework detected in dependencies")

            # Check table name matches in code symbols / classes
            for tbl in db_tables:
                # Direct match (e.g. table 'users', symbol 'users')
                # Singular/plural variations (e.g. table 'orders' vs class 'order')
                singular = tbl[:-1] if tbl.endswith("s") else tbl
                plural = tbl + "s" if not tbl.endswith("s") else tbl

                if tbl in symbol_names or singular in symbol_names or plural in symbol_names:
                    matched_tables.append(tbl)

            if matched_tables:
                score += min(0.6, len(matched_tables) * 0.15)
                matched_evidence.append(
                    f"Code symbols match {len(matched_tables)} database tables: {', '.join(sorted(matched_tables)[:8])}"
                )

            # Check database name match in repo or symbols
            if db_name and (db_name in repo.slug.lower() or db_name in symbol_names):
                score += 0.2
                matched_evidence.append(f"Database name '{db_name}' referenced in repository context")

            if score >= 0.25:
                confidence = "high" if score >= 0.6 else "medium" if score >= 0.4 else "low"
                links.append({
                    "repo_slug": repo.slug,
                    "repo_name": repo.display_name or repo.slug,
                    "database_slug": db_s,
                    "database_name": db_info["entity"].display_name or db_s,
                    "database_type": db_info["db_type"],
                    "confidence": confidence,
                    "score": round(score, 2),
                    "matched_tables": sorted(matched_tables),
                    "evidence": matched_evidence,
                })

    return sorted(links, key=lambda l: -l["score"])


def query_cross_asset_links_raw(resource_slug: str = "") -> str:
    """Format cross-asset linkages between repos and databases as structured markdown."""
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    slug = registry._normalize_slug(resource_slug) if resource_slug else ""

    # Check if slug is repo or database
    is_repo = bool(registry.get(slug)) if slug else False
    is_db = bool(registry.get_database(slug, allow_unreadable=True)) if slug else False

    repo_arg = slug if is_repo else None
    db_arg = slug if is_db else None

    links = find_cross_asset_links(registry, repo_slug=repo_arg, database_slug=db_arg)

    if not links:
        scope_str = f" for resource '{resource_slug}'" if resource_slug else ""
        return (
            f"No cross-asset dependencies or linkages found{scope_str}. "
            "Ensure both repositories and databases have been surveyed to discover table and ORM linkages."
        )

    lines: list[str] = [
        "### Discovered Cross-Asset Dependencies (Code Repositories ↔ Databases)\n",
        "| Repository | Database | DB Type | Confidence | Matched Tables | Evidence Summary |",
        "|---|---|---|---|---|---|",
    ]

    for l in links:
        tbl_str = ", ".join(l["matched_tables"][:4])
        if len(l["matched_tables"]) > 4:
            tbl_str += f" (+{len(l['matched_tables']) - 4} more)"
        if not tbl_str:
            tbl_str = "(Driver / Config match)"

        ev_str = "; ".join(l["evidence"][:2])
        lines.append(
            f"| `{l['repo_slug']}` | `{l['database_slug']}` | {l['database_type']} | "
            f"**{l['confidence'].upper()}** ({l['score']}) | {tbl_str} | {ev_str} |"
        )

    lines.append("\n#### Detailed Linkage Breakdown:")
    for l in links:
        lines.append(f"- **{l['repo_name']}** (`{l['repo_slug']}`) ↔ **{l['database_name']}** (`{l['database_slug']}`):")
        for ev in l["evidence"]:
            lines.append(f"  - {ev}")

    return "\n".join(lines).strip()
