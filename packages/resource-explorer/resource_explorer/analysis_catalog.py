"""Local analysis catalog — registry of analyses available per resource type.

Each entry describes a specific analysis that can be run on a resource,
including what it does, what Egeria annotation types it produces, who
it's aimed at (perspective), and what intent drives it.

This catalog is the local counterpart to Egeria's find_technology_types /
get_tech_type_detail; the two are merged in the UI once Q1 is answered
(see docs/survey-activity-design.md).
"""
from __future__ import annotations

REPO_ANALYSES: list[dict] = [
    {
        "id": "language_file_classification",
        "name": "Language & File Classification",
        "description": "Identify programming languages, file types, and project structure. Produces file-type counts and language breakdown.",
        "resource_types": ["repo"],
        "intent": "scouting",
        "perspectives": ["all"],
        "annotation_types": ["ResourceMeasureAnnotation", "ClassificationAnnotation"],
        "source": "local",
        "run_time": "fast",
        "action": "survey",
        "recommended": True,
    },
    {
        "id": "repository_health",
        "name": "Repository Health",
        "description": "Stars, forks, contributors, open issues, and activity metrics from GitHub. Produces a quality score annotation.",
        "resource_types": ["repo"],
        "intent": "scouting",
        "perspectives": ["all"],
        "annotation_types": ["QualityScoreAnnotation"],
        "source": "local",
        "run_time": "fast",
        "action": "survey",
        "recommended": True,
    },
    {
        "id": "dependency_analysis",
        "name": "Dependency Analysis",
        "description": "Scan package manifests (pyproject.toml, package.json, pom.xml, etc.) for dependencies by ecosystem.",
        "resource_types": ["repo"],
        "intent": "assessment",
        "perspectives": ["all", "security"],
        "annotation_types": ["DataClassAnnotation"],
        "source": "local",
        "run_time": "fast",
        "action": "survey",
        "recommended": False,
    },
    {
        "id": "security_scan",
        "name": "Security Scan",
        "description": "Detect hardcoded secrets, insecure patterns, and missing security artifacts (SECURITY.md, signed commits).",
        "resource_types": ["repo"],
        "intent": "assessment",
        "perspectives": ["security", "steward"],
        "annotation_types": ["RequestForActionAnnotation"],
        "source": "local",
        "run_time": "fast",
        "action": "survey",
        "recommended": True,
    },
    {
        "id": "documentation_coverage",
        "name": "Documentation Coverage",
        "description": "Assess README completeness, CHANGELOG, API docs, and inline comment coverage.",
        "resource_types": ["repo"],
        "intent": "assessment",
        "perspectives": ["steward", "all"],
        "annotation_types": ["ClassificationAnnotation"],
        "source": "local",
        "run_time": "fast",
        "action": "survey",
        "recommended": False,
    },
    {
        "id": "data_file_profiling",
        "name": "Data File Profiling",
        "description": "Profile CSV, Excel, Parquet, and other tabular data files for schema, row counts, and null statistics.",
        "resource_types": ["repo"],
        "intent": "assessment",
        "perspectives": ["data_scientist", "steward"],
        "annotation_types": ["SchemaAnalysisAnnotation", "DataClassAnnotation"],
        "source": "local",
        "run_time": "minutes",
        "action": "survey",
        "recommended": True,
    },
    {
        "id": "api_structure",
        "name": "API & Symbol Extraction",
        "description": "Extract public functions, classes, and API endpoints from Python, JavaScript, and OpenAPI source.",
        "resource_types": ["repo"],
        "intent": "assessment",
        "perspectives": ["data_scientist", "all"],
        "annotation_types": ["SchemaAnalysisAnnotation"],
        "source": "local",
        "run_time": "fast",
        "action": "survey",
        "recommended": False,
    },
    {
        "id": "egeria_publish",
        "name": "Publish to Egeria Catalog",
        "description": "Register the repository in Egeria and publish all survey annotations as a SurveyReport asset. Requires Egeria connection.",
        "resource_types": ["repo"],
        "intent": "assessment",
        "perspectives": ["steward", "all"],
        "annotation_types": ["SurveyReport"],
        "source": "egeria",
        "run_time": "minutes",
        "action": "publish",
        "recommended": True,
    },
]

DATABASE_ANALYSES: list[dict] = [
    {
        "id": "schema_inventory",
        "name": "Schema Inventory",
        "description": "List all schemas, tables, columns with types, constraints, primary keys, foreign keys, and comments.",
        "resource_types": ["database"],
        "intent": "scouting",
        "perspectives": ["all", "dba"],
        "annotation_types": ["SchemaAnalysisAnnotation", "ResourceMeasureAnnotation"],
        "source": "local",
        "run_time": "fast",
        "action": "survey",
        "recommended": True,
    },
    {
        "id": "row_count_snapshot",
        "name": "Row Count Snapshot",
        "description": "Count rows in all tables using pg_stat_user_tables. Records a time-series data point for trend analysis.",
        "resource_types": ["database"],
        "intent": "scouting",
        "perspectives": ["all", "dba"],
        "annotation_types": ["ResourceMeasureAnnotation"],
        "source": "local",
        "run_time": "fast",
        "action": "survey",
        "recommended": True,
    },
    {
        "id": "index_health",
        "name": "Index Health",
        "description": "Identify unused indexes, missing indexes on foreign keys, and bloated indexes.",
        "resource_types": ["database"],
        "intent": "assessment",
        "perspectives": ["dba"],
        "annotation_types": ["RequestForActionAnnotation", "DataClassAnnotation"],
        "source": "local",
        "run_time": "fast",
        "action": "survey",
        "recommended": True,
    },
    {
        "id": "privilege_audit",
        "name": "Privilege Audit",
        "description": "Review database roles, grants, and superuser accounts for security hygiene.",
        "resource_types": ["database"],
        "intent": "assessment",
        "perspectives": ["security", "dba"],
        "annotation_types": ["DataClassAnnotation", "RequestForActionAnnotation"],
        "source": "local",
        "run_time": "fast",
        "action": "survey",
        "recommended": True,
    },
    {
        "id": "egeria_db_survey",
        "name": "Egeria Native DB Survey",
        "description": "Trigger Egeria's native PostgreSQL survey for deep annotation of schema, data quality, and lineage. Runs asynchronously.",
        "resource_types": ["database"],
        "intent": "assessment",
        "perspectives": ["all", "dba"],
        "annotation_types": ["SchemaAnalysisAnnotation", "ClassificationAnnotation", "RequestForActionAnnotation"],
        "source": "egeria",
        "run_time": "async",
        "action": "publish",
        "recommended": True,
    },
]

FILESYSTEM_ANALYSES: list[dict] = [
    {
        "id": "filesystem_inventory",
        "name": "File System Inventory",
        "description": "Walks the filesystem, collects file sizes, formats, timestamps, and classifications. Profiles tabular data file schemas.",
        "resource_types": ["filesystem"],
        "intent": "scouting",
        "perspectives": ["all", "steward"],
        "annotation_types": [
            "ResourceMeasureAnnotation",
            "ClassificationAnnotation",
            "RequestForActionAnnotation",
            "SchemaAnalysisAnnotation",
        ],
        "source": "local",
        "run_time": "minutes",
        "action": "survey",
        "recommended": True,
    }
]

_CATALOG: dict[str, list[dict]] = {
    "repo": REPO_ANALYSES,
    "database": DATABASE_ANALYSES,
    "filesystem": FILESYSTEM_ANALYSES,
}


def get_analyses(
    resource_type: str,
    intent: str | None = None,
    perspective: str | None = None,
) -> list[dict]:
    """Return analyses for a resource type, optionally filtered by intent and perspective."""
    analyses = list(_CATALOG.get(resource_type, []))
    if intent and intent != "all":
        analyses = [a for a in analyses if a["intent"] == intent]
    if perspective and perspective != "all":
        analyses = [a for a in analyses if "all" in a["perspectives"] or perspective in a["perspectives"]]
    return analyses


def list_perspectives() -> list[str]:
    """Return the distinct, real (non-"all") perspective values actually used
    across the catalog, sorted. Backs the UI's perspective selector so it's
    data-driven rather than a hardcoded list that silently drifts out of sync
    with what the catalog actually contains — see GET /api/analyses/perspectives.

    NOTE: this is a stopgap sourced from RE's own local catalog only. It does
    NOT yet reflect Egeria's native Perspective type, nor Egeria Advisor's own
    perspective set (developer/data_engineer/data_steward/governance_officer)
    — those are a real, larger unification the Trellis design work has already
    flagged as its own thread. Re-implement this in
    resource_explorer/surveyors/analysis_catalog_reader.py when Step 3
    externalizes this file, and revisit the source once that unification
    happens rather than assuming this stopgap is the final answer.
    """
    values: set[str] = set()
    for entries in _CATALOG.values():
        for entry in entries:
            values.update(p for p in entry["perspectives"] if p != "all")
    return sorted(values)
