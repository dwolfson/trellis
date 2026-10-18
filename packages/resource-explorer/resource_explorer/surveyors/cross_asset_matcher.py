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


#: Table names common enough that a class of the same name proves little on its own.
_GENERIC_TABLE_NAMES = frozenset({
    "user", "role", "group", "session", "event", "task", "item", "log", "file", "type", "status",
    "state", "config", "setting", "data", "name", "order", "account", "message", "token", "job",
})
_MIN_NAME_LEN = 4
_TABLE_WEIGHT = 0.15
_GENERIC_TABLE_WEIGHT = 0.05

_DB_DRIVER_DEPS = {
    "postgresql": {"psycopg2", "psycopg2-binary", "psycopg", "psycopg-binary", "asyncpg", "org.postgresql:postgresql", "r2dbc-postgresql"},
    "mysql": {"mysql-connector-python", "mysqlclient", "pymysql", "mysql:mysql-connector-java"},
    "sqlite": {"sqlite3", "org.xerial:sqlite-jdbc"},
    "oracle": {"cx-oracle", "oracledb", "com.oracle.database.jdbc:ojdbc8"},
}
_ORM_DEPS = {
    "sqlalchemy", "sqlmodel", "django", "tortoise-orm", "peewee", "hibernate",
    "org.springframework.boot:spring-boot-starter-data-jpa",
    "flyway", "liquibase", "alembic",
}


def _squash(name: str) -> str:
    """Lowercase with separators removed, so table `order_items` meets class `OrderItem`."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "xes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _table_variants(table: str) -> set[str]:
    """Spellings a class for `table` plausibly has: the table itself and its singular, separators dropped."""
    squashed = _squash(table)
    return {v for v in (squashed, _singular(squashed)) if len(v) >= _MIN_NAME_LEN}


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
        dep_names = {d.get("dep_name", "").lower().replace("_", "-") for d in deps} if deps else set()
        has_orm = bool(dep_names & _ORM_DEPS)

        # 2. Class names. An ORM model or entity is a class; matching every symbol, as an earlier
        # version did, let any function called `orders` vouch for a table, and the 500-row LIMIT with
        # no ORDER BY made the answer depend on which rows the database returned first.
        class_names: set[str] = set()
        try:
            with registry._conn() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT name FROM project_code_symbols "
                    "WHERE project_slug = ? AND kind = 'class'",
                    (repo.slug,),
                ).fetchall()
            class_names = {_squash(r["name"]) for r in rows if r["name"]}
        except Exception as exc:
            log.warning("could not read code symbols for %s: %s", repo.slug, exc)

        for db_s, db_info in db_tables_map.items():
            matched_tables: list[str] = []
            matched_evidence: list[str] = []
            score = 0.0

            db_tables = db_info["tables"]
            db_type = db_info["db_type"].lower()
            db_name = db_info["db_name"]

            matched_drivers = dep_names & _DB_DRIVER_DEPS.get(db_type, set())
            if matched_drivers:
                score += 0.3
                matched_evidence.append(f"Matching DB drivers in dependencies: {', '.join(sorted(matched_drivers))}")

            for tbl in db_tables:
                if class_names & _table_variants(tbl):
                    matched_tables.append(tbl)

            # ORM use is evidence only alongside something tying this repo to this database;
            # on its own it says the repo uses *a* database, which is true of every ORM repo.
            if has_orm and (matched_drivers or matched_tables):
                score += 0.1
                matched_evidence.append("ORM / Migration framework detected in dependencies")

            if matched_tables:
                table_score = sum(
                    _GENERIC_TABLE_WEIGHT if _squash(t) in _GENERIC_TABLE_NAMES else _TABLE_WEIGHT
                    for t in matched_tables
                )
                table_score = min(0.6, table_score)
                # Class names alone, with no driver or ORM behind them, are coincidence-prone: cap.
                if not (matched_drivers or has_orm):
                    table_score = min(table_score, 0.3)
                score += table_score
                matched_evidence.append(
                    f"Model classes match {len(matched_tables)} database tables: {', '.join(sorted(matched_tables)[:8])}"
                )

            if len(db_name) >= _MIN_NAME_LEN and db_name in repo.slug.lower():
                score += 0.2
                matched_evidence.append(f"Database name '{db_name}' referenced in repository name")

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
