"""
Survey Definition adapter for Git repositories, and the repo analysis-kind
registry (STEP_REGISTRY / ANALYSIS_KINDS) — the single source of truth for
"what are the repo survey steps, and what analyses do users actually see/
run/schedule from them."

Analysis-kind extensibility redesign: this used to be four independently-
maintained parallel structures (re_analysis_steps' closures,
_RE_ANALYSIS_STEP_INFO, REPO_ANALYSIS_STEP_MAP, REPO_ANALYSIS_RESULTS_MAP),
each requiring its own hand-edit whenever a step or analysis kind changed —
plus SurveyOrchestrator's own separately-hardcoded surveyor-construction
dict. They're now two registries, everything else is a thin derived view:

  STEP_REGISTRY   — step_key -> StepInfo (surveyor class, description,
                     annotation types, any special constructor kwargs).
                     The 10 granular sub-surveyor units SurveyOrchestrator
                     can run individually via steps=[...].
  ANALYSIS_KINDS  — analysis_catalog id -> AnalysisKind (which step_key(s)
                     it runs, its "family" for grouping related kinds e.g.
                     "security", and — for the 5 kinds shown under
                     Analysis/Assessment — how to read/render its results).

Adding a new plain analysis kind (accepts (project, registry, surveyed_at)
like the existing finding/metric-writing surveyors) needs exactly one new
StepInfo entry and one new AnalysisKind entry — SurveyOrchestrator derives
its surveyor-construction dict from STEP_REGISTRY automatically. See
StepInfo.accepts_surveyed_at / .static_kwargs for the few surveyors that
need something other than the generic (project, registry) construction.

Unlike the database case, repo surveys are already composed of independent
sub-surveyor units — each one is exposed as its own re_analysis_step key,
the most granular and natural fit for Survey Definition steps. Publishing
reuses the existing EgeriaPublisher.publish unmodified — it's already
narrow (no native-survey side effect).
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable

from trellis_microflow import ResourceProvider

from resource_explorer.surveyors.file_classifier.file_classifier_surveyor import FileClassifierSurveyor
from resource_explorer.surveyors.sub_surveyors import (
    ApiStructureSurveyor,
    CiQualitySurveyor,
    DataProfilerSurveyor,
    DependencySurveyor,
    DocumentationSurveyor,
    FileSizeSurveyor,
    FileStructureSurveyor,
    HealthSurveyor,
    LanguageSurveyor,
    LicenseClassifierSurveyor,
    MaturitySurveyor,
    RepoConventionsSurveyor,
    SecurityFeaturesSurveyor,
    SecurityHygieneSurveyor,
    SubResourceSurveyor,
    SymbolExtractionSurveyor,
)
from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    register_adapter,
)


# qualified_name of the "Repo Coarse Scout" Survey Definition (a
# GovernanceActionProcess authored in Egeria via Dr.Egeria, chaining just
# repo_health + repo_language — both API-only, no clone needed). Referenced
# explicitly by web/routes/projects.py's scouting-scan endpoint rather than
# relying on technology_type auto-resolution, so it stays unambiguous even
# once a second ("deep") repo Survey Definition also exists — see the
# Scouting/Analysis/Assessment boundary plan. Authored once, out-of-band;
# this constant is the single place code and the Egeria-side element must
# agree on the name.
REPO_COARSE_SCOUT_SURVEY_DEFINITION_QN = "GovActionProcess::RepoCoarseScout"


# ── Step-level registry ──────────────────────────────────────────────────

@dataclass
class StepInfo:
    """One SurveyOrchestrator step — a single sub-surveyor unit."""
    step_key: str
    surveyor_cls: type
    description: str
    annotation_types: list[str]
    # Extra kwargs re_analysis_steps' Survey-Definition-triggered runners
    # pass when running this step in isolation (always safe defaults —
    # a single-step run never has real pyegeria_client/force_refresh/
    # data_path context to forward).
    static_kwargs: dict = field(default_factory=dict)
    # Whether this surveyor's constructor accepts surveyed_at (the shared
    # per-orchestrator-run timestamp, Phase B D1) — only the surveyors that
    # persist structured findings/metrics at survey time need this.
    accepts_surveyed_at: bool = False
    # Whether this surveyor's constructor accepts scope_locator (D5/D6 repo
    # scope-narrowing funnel plan) — only the corpus-shaped surveyors
    # (target_shape="corpus" in analysis_catalog.yaml) implement the
    # path-prefix filter; SurveyOrchestrator.run() only forwards
    # scope_locator to steps flagged True here.
    accepts_scope_locator: bool = False
    # D6 (docs/unified-survey-execution-model-plan.md) — shared resources
    # this step needs, as {resource_name: constructor_kwarg_name}. Resolved
    # once per SurveyOrchestrator.run() call, deduped across every step
    # selected in that run, via trellis_microflow.resolve_resources — see
    # RESOURCE_PROVIDERS below for what "zipball_root" actually does.
    requires_resources: dict[str, str] = field(default_factory=dict)


# ── D6: shared-resource providers ────────────────────────────────────────
# The generic acquire/dedup/cleanup mechanism lives in trellis_microflow
# (packages/trellis-microflow) — this module only supplies the
# repo-specific *instance*: what "zipball_root" actually means and how to
# get one. See that package's README for why the split exists.

@contextmanager
def _acquire_zipball_root(project, registry):
    """Download `project`'s repo zipball into a fresh tempdir and yield the
    extracted root. One real network call + one extraction per invocation —
    trellis_microflow.resolve_resources is what guarantees this only gets
    invoked once per SurveyOrchestrator.run() call no matter how many
    selected steps declare `requires_resources={"zipball_root": ...}`.

    A plain function, not a StepInfo/surveyor. The actual download+tempdir
    logic lives in GitHubClient.zipball_root() (D6.7) — the one
    implementation IngestionPipeline.refresh_profile() also wraps, instead
    of each maintaining its own copy.
    """
    from resource_explorer.github.client import GitHubClient

    client = GitHubClient()
    repo = client.get_repo(project.github_url)
    with client.zipball_root(repo) as root:
        yield root


def _resource_providers_for(project, registry) -> dict[str, ResourceProvider]:
    """Builds this run's RESOURCE_PROVIDERS, binding `project`/`registry`
    into each provider's zero-argument `acquire` via a closure — see
    ResourceProvider's own docstring for why the binding happens here,
    not by threading project/registry through trellis_microflow itself."""
    return {
        "zipball_root": ResourceProvider(
            name="zipball_root",
            acquire=lambda: _acquire_zipball_root(project, registry),
        ),
    }


STEP_REGISTRY: dict[str, StepInfo] = {
    "repo_file_structure": StepInfo(
        "repo_file_structure", FileStructureSurveyor,
        "File counts, per-language breakdown, and top-level directory structure.",
        ["ResourceMeasureAnnotation"],
    ),
    "repo_file_size": StepInfo(
        "repo_file_size", FileSizeSurveyor,
        "Per-file sizes, total footprint, size-by-type, top-10 largest files.",
        ["ResourceMeasureAnnotation", "RequestForActionAnnotation"],
        accepts_scope_locator=True,
    ),
    "repo_language": StepInfo(
        "repo_language", LanguageSurveyor,
        "Primary/secondary language and coarse project-type classification.",
        ["ClassificationAnnotation"],
    ),
    "repo_health": StepInfo(
        "repo_health", HealthSurveyor,
        "Activity, community, release-cadence, and freshness scoring from GitHub stats.",
        ["QualityScoreAnnotation"],
    ),
    "repo_dependency": StepInfo(
        "repo_dependency", DependencySurveyor,
        "Package dependencies per ecosystem (PyPI/npm/Maven).",
        ["DataClassAnnotation", "ResourceMeasureAnnotation"],
    ),
    "repo_documentation": StepInfo(
        "repo_documentation", DocumentationSurveyor,
        "Presence of README/CHANGELOG/CONTRIBUTING/SECURITY and overall doc-quality label.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
    ),
    "repo_security": StepInfo(
        "repo_security", SecurityHygieneSurveyor,
        "Presence of SECURITY.md, CI config, LICENSE — flags gaps as RFAs.",
        ["ClassificationAnnotation", "RequestForActionAnnotation"],
        accepts_surveyed_at=True,
    ),
    "repo_license_classification": StepInfo(
        "repo_license_classification", LicenseClassifierSurveyor,
        "Classifies the repo's SPDX license id into a risk tier (permissive/"
        "weak copyleft/strong copyleft/source-available/unknown).",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
    ),
    "repo_security_features": StepInfo(
        "repo_security_features", SecurityFeaturesSurveyor,
        "GitHub's native security feature toggles (Dependabot, secret "
        "scanning, etc.) — configuration state, not artifact presence.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
    ),
    "repo_ci_quality": StepInfo(
        "repo_ci_quality", CiQualitySurveyor,
        "Whether CI workflows actually run tests/lint/build, via a keyword "
        "scan of workflow content — not just whether a CI config exists.",
        ["ClassificationAnnotation"],
    ),
    "repo_maturity": StepInfo(
        "repo_maturity", MaturitySurveyor,
        "Project age/lifecycle stage (nascent/emerging/established/mature), "
        "from repo_created_at — a CHAOSS-informed Discovery-tier signal.",
        ["ClassificationAnnotation"],
    ),
    "repo_conventions": StepInfo(
        "repo_conventions", RepoConventionsSurveyor,
        "Discovery-tier repo conventions: security policy content, build "
        "automation, deployment/Docker evidence, catalog self-description "
        "(Backstage-style), documentation breadth.",
        ["ClassificationAnnotation"],
    ),
    "repo_api_structure": StepInfo(
        "repo_api_structure", ApiStructureSurveyor,
        "Public API surface (functions/classes/methods) per language.",
        ["SchemaAnalysisAnnotation", "ResourceMeasureAnnotation"],
        accepts_surveyed_at=True,
        accepts_scope_locator=True,
    ),
    "repo_data_profiling": StepInfo(
        "repo_data_profiling", DataProfilerSurveyor,
        "Inventories data files and profiles their schema (rows/columns/dtypes/nulls).",
        ["ResourceMeasureAnnotation", "SchemaAnalysisAnnotation", "RequestForActionAnnotation"],
        static_kwargs={"data_path": None},
        accepts_surveyed_at=True,
        accepts_scope_locator=True,
        # D6's own worked example (docs/unified-survey-execution-model-
        # plan.md) — activates DataProfilerSurveyor's Tier 2 (real
        # per-file column profiling from a real local clone) for the
        # first time via any orchestrator-driven path: previously
        # `local_path` was only ever supplied by an explicit caller
        # override (SurveyOrchestrator(data_path=...), the CLI's
        # `--data-path` flag) and never by anything automatic. A real,
        # flagged behavior change (a real zipball download + real network
        # cost this step didn't previously pay through this path) — not
        # silent.
        requires_resources={"zipball_root": "local_path"},
    ),
    "repo_file_classification": StepInfo(
        "repo_file_classification", FileClassifierSurveyor,
        "Classifies every file by type using filename/extension mapping (Egeria-enrichable).",
        ["ClassificationAnnotation", "ResourceMeasureAnnotation"],
        static_kwargs={"pyegeria_client": None, "force_refresh": False},
        accepts_scope_locator=True,
    ),
    "repo_symbol_extraction": StepInfo(
        "repo_symbol_extraction", SymbolExtractionSurveyor,
        "Extracts class/function/method symbols (tree-sitter/ast) for every "
        "supported language, refreshing project_code_symbols/"
        "project_code_relationships — D5's self-contained microflow closing "
        "the bug where those tables were only ever populated by RAG "
        "ingestion, never by a survey step.",
        ["ResourceMeasureAnnotation"],
        accepts_surveyed_at=True,
        requires_resources={"zipball_root": "local_path"},
    ),
    "repo_sub_resource_survey": StepInfo(
        "repo_sub_resource_survey", SubResourceSurveyor,
        "Surveys file/folder characteristics to recommend which sub-resources "
        "are worthy of cataloging as their own Egeria assets (Assessment "
        "sub-resource cataloging plan) — survey only, does not catalog.",
        ["ClassificationAnnotation"],
        accepts_surveyed_at=True,
    ),
}


def _run_step(step_key: str, **orchestrator_kwargs):
    def runner(project, registry, **_) -> dict:
        from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

        orch = SurveyOrchestrator(registry, **orchestrator_kwargs)
        result = orch.run(project.slug, steps=[step_key])
        return {"annotations": result.annotations}

    return runner


def _build_re_analysis_steps() -> dict:
    """Derived from STEP_REGISTRY — each step key delegates to
    SurveyOrchestrator.run(steps=[key]) rather than instantiating its own
    surveyor closure, so STEP_REGISTRY stays the single source of truth for
    what each key means and how its surveyor is constructed."""
    return {key: _run_step(key, **info.static_kwargs) for key, info in STEP_REGISTRY.items()}


_RE_ANALYSIS_STEP_INFO = {
    key: {"description": info.description, "annotation_types": info.annotation_types}
    for key, info in STEP_REGISTRY.items()
}


# ── Analysis-kind (catalog-id) level registry ────────────────────────────
# analysis_id -> (results_reader, trend_reader). Each results_reader(registry,
# slug) -> dict of latest structured results; each trend_reader(registry,
# slug) -> list[{"surveyed_at": str, "value": number, ...}] for the trend
# chart. Only the 5 analysis-catalog entries actually shown under Analysis/
# Assessment have one — language_file_classification/repository_health are
# scouting-tagged, no results view.

def _file_classification_results(registry, slug: str) -> dict:
    # project_file_type_counts is written by FileClassifierSurveyor
    # (repo_file_classification step) — already has full history/trend
    # support from Phase B (the "Understanding" survey_history chart reads
    # the same table). Surfaced here so the Scouting "Profile" tab's
    # auto-chained refresh->classify has something real to display, closing
    # the gap where classification data was refreshed but never shown.
    rows = registry.query_file_type_counts(slug)
    surveyed_at = rows[0]["surveyed_at"] if rows else ""
    return {
        "by_type": [{"type_label": r["type_label"], "file_count": r["file_count"]} for r in rows],
        "total_files": sum(r["file_count"] for r in rows),
        "surveyed_at": surveyed_at,
    }


def _file_classification_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["total_files"]}
        for r in registry.query_file_type_history(slug)
    ]


def _dependency_results(registry, slug: str) -> dict:
    deps = registry.query_dependencies(slug)
    by_ecosystem: dict[str, list] = {}
    for d in deps:
        by_ecosystem.setdefault(d["ecosystem"] or "other", []).append(d)
    return {"by_ecosystem": by_ecosystem, "total": len(deps)}


def _dependency_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["total_dependencies"]}
        for r in registry.query_dependencies_history(slug)
    ]


def _data_profile_results(registry, slug: str) -> dict:
    profiles = registry.get_data_profiles(slug)
    return {"profiles": profiles, "total": len(profiles)}


def _data_profile_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["metric_value"]}
        for r in registry.query_metrics_history(slug, "data_profile", "total_files")
    ]


def _security_results(registry, slug: str) -> dict:
    # Generic findings table (analysis-kind extensibility redesign) — same
    # uniform {check_name, label, summary, confidence} shape as
    # _documentation_results below, so the frontend's "findings_list" render
    # mode needs zero per-kind logic (D4). "gap_count" stays as an extra,
    # kind-specific top-level key alongside the generic findings list.
    rows = registry.query_findings(slug, "security_hygiene")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    return {"findings": findings, "gap_count": sum(1 for f in findings if f["label"] == "gap")}


def _security_trend(registry, slug: str) -> list[dict]:
    # query_findings_history_raw returns raw rows across all runs — this
    # kind's own trend aggregation (gap-count per run) lives here, not as
    # per-kind SQL in the registry layer.
    by_run: dict[str, dict] = {}
    for r in registry.query_findings_history_raw(slug, "security_hygiene"):
        bucket = by_run.setdefault(r["surveyed_at"], {"gap": 0, "total": 0})
        bucket["total"] += 1
        if r["label"] == "gap":
            bucket["gap"] += 1
    return [
        {"surveyed_at": ts, "value": counts["gap"], "total_checks": counts["total"]}
        for ts, counts in sorted(by_run.items())
    ]


def _documentation_results(registry, slug: str) -> dict:
    # Same uniform finding shape _security_results uses — see its comment.
    rows = registry.query_findings(slug, "documentation")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    return {"findings": findings}


def _license_results(registry, slug: str) -> dict:
    # Same uniform finding shape _security_results/_documentation_results
    # use — license classification produces exactly one finding per run, so
    # this is the smallest possible "findings_list" consumer, not a special
    # case. No trend reader: license rarely changes, so a run-over-run chart
    # would be a flat line with almost no analytical value (Assessment
    # expansion plan B1).
    rows = registry.query_findings(slug, "license_classification")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    return {"findings": findings}


def _security_features_results(registry, slug: str) -> dict:
    # Same uniform finding shape _security_results/_license_results use.
    # Unlike license_classification, this DOES get a trend reader (below) —
    # feature toggles can genuinely change run-to-run (a repo admin flips
    # secret scanning on), unlike a license which almost never changes.
    rows = registry.query_findings(slug, "security_features")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    return {"findings": findings}


def _security_features_trend(registry, slug: str) -> list[dict]:
    # Enabled-count per run — mirrors _security_trend's gap-count-per-run
    # shape, just counting "pass" (enabled) instead of "gap".
    by_run: dict[str, dict] = {}
    for r in registry.query_findings_history_raw(slug, "security_features"):
        bucket = by_run.setdefault(r["surveyed_at"], {"enabled": 0, "total": 0})
        bucket["total"] += 1
        if r["label"] == "pass":
            bucket["enabled"] += 1
    return [
        {"surveyed_at": ts, "value": counts["enabled"], "total_features": counts["total"]}
        for ts, counts in sorted(by_run.items())
    ]


def _ci_quality_results(registry, slug: str) -> dict:
    # Same uniform finding shape as _security_results/_license_results.
    rows = registry.query_findings(slug, "ci_quality")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    return {"findings": findings}


def _ci_quality_trend(registry, slug: str) -> list[dict]:
    # Pass-count per run — mirrors _security_features_trend's shape.
    by_run: dict[str, dict] = {}
    for r in registry.query_findings_history_raw(slug, "ci_quality"):
        bucket = by_run.setdefault(r["surveyed_at"], {"passing": 0, "total": 0})
        bucket["total"] += 1
        if r["label"] == "pass":
            bucket["passing"] += 1
    return [
        {"surveyed_at": ts, "value": counts["passing"], "total_checks": counts["total"]}
        for ts, counts in sorted(by_run.items())
    ]


def _maturity_results(registry, slug: str) -> dict:
    # Same uniform finding shape as _license_results — single
    # current-state classification, no trend (see maturity.py's docstring).
    rows = registry.query_findings(slug, "maturity")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    return {"findings": findings}


def _repo_conventions_results(registry, slug: str) -> dict:
    rows = registry.query_findings(slug, "repo_conventions")
    findings = [
        {"check_name": r["check_name"], "label": r["label"], "summary": r["summary"], "confidence": r["confidence"]}
        for r in rows
    ]
    return {"findings": findings}


def _repo_conventions_trend(registry, slug: str) -> list[dict]:
    # Pass-count per run — mirrors _ci_quality_trend/_security_features_trend.
    # "present"/"pass" both count as a positive signal (catalog_info uses
    # "present"/"absent" rather than "pass"/"gap" — see
    # RepoConventionsParser._catalog_info's docstring for why).
    by_run: dict[str, dict] = {}
    for r in registry.query_findings_history_raw(slug, "repo_conventions"):
        bucket = by_run.setdefault(r["surveyed_at"], {"positive": 0, "total": 0})
        bucket["total"] += 1
        if r["label"] in ("pass", "present"):
            bucket["positive"] += 1
    return [
        {"surveyed_at": ts, "value": counts["positive"], "total_checks": counts["total"]}
        for ts, counts in sorted(by_run.items())
    ]


def _sub_resource_survey_results(registry, slug: str) -> dict:
    # Same uniform finding shape _security_results/_documentation_results
    # use ("worthy"/"not_worthy" are this kind's own label vocabulary) —
    # plus path/kind/owners/dates parsed out of detail_json, since the
    # repo scope-narrowing funnel's selection UI (D3) needs those as real
    # sortable/filterable columns and needs `kind` to build a correct
    # catalog request, not just a display string.
    rows = registry.query_findings(slug, "repo_sub_resource_survey")
    findings = []
    for r in rows:
        detail = {}
        if r.get("detail_json"):
            try:
                detail = json.loads(r["detail_json"])
            except (TypeError, ValueError):
                detail = {}
        findings.append({
            "check_name": r["check_name"], "label": r["label"],
            "summary": r["summary"], "confidence": r["confidence"],
            "path": detail.get("path", ""), "kind": detail.get("kind", "file"),
            "owners": detail.get("owners", []),
            "last_updated_at": detail.get("last_updated_at", ""),
            "first_added_at": detail.get("first_added_at", ""),
        })
    metrics = registry.query_metrics(slug, "repo_sub_resource_survey")
    return {"findings": findings, "metrics": metrics}


def _sub_resource_survey_trend(registry, slug: str) -> list[dict]:
    # Growth over time (D11) — total_size_bytes is the headline trend
    # value; file_count is included per-point for context.
    size_history = {
        r["surveyed_at"]: r["metric_value"]
        for r in registry.query_metrics_history(slug, "repo_sub_resource_survey", "total_size_bytes")
    }
    count_history = {
        r["surveyed_at"]: r["metric_value"]
        for r in registry.query_metrics_history(slug, "repo_sub_resource_survey", "file_count")
    }
    return [
        {"surveyed_at": ts, "value": value, "file_count": count_history.get(ts)}
        for ts, value in sorted(size_history.items())
    ]


_DOC_QUALITY_RANK = {"Minimal": 1, "Partial": 2, "Comprehensive": 3}


def _documentation_trend(registry, slug: str) -> list[dict]:
    quality_rows = [
        r for r in registry.query_findings_history_raw(slug, "documentation")
        if r["check_name"] == "quality_score"
    ]
    return [
        {"surveyed_at": r["surveyed_at"], "value": _DOC_QUALITY_RANK.get(r["label"], 0), "label": r["label"]}
        for r in quality_rows
    ]


def _api_structure_results(registry, slug: str) -> dict:
    # Always-current live read (project_code_symbols/project_code_relationships
    # are repopulated at ingestion, not survey time) — no "latest results"
    # snapshot needed for this one, unlike the others above.
    with registry._conn() as conn:
        rows = conn.execute(
            "SELECT language, kind, COUNT(*) as c FROM project_code_symbols "
            "WHERE project_slug = ? GROUP BY language, kind",
            (slug,),
        ).fetchall()
    by_language: dict[str, dict[str, int]] = {}
    for r in rows:
        by_language.setdefault(r["language"], {})[r["kind"]] = r["c"]
    relationships = registry.get_code_relationships(slug)
    return {"by_language": by_language, "relationship_count": len(relationships)}


def _api_structure_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["metric_value"]}
        for r in registry.query_metrics_history(slug, "api_structure", "symbol_count")
    ]


def _symbol_extraction_results(registry, slug: str) -> dict:
    # D5's own worked example — separate "symbol_extraction" metric kind
    # (SymbolExtractionSurveyor writes it) from ApiStructureSurveyor's
    # "api_structure" kind, so this step's independent run history stays
    # its own trend, not conflated with the reporting step it feeds.
    m = registry.query_metrics(slug, "symbol_extraction")
    return {
        "symbol_count": m.get("symbol_count", 0),
        "relationship_count": m.get("relationship_count", 0),
        "by_language": (m.get("detail") or {}).get("by_language", {}),
        "surveyed_at": m.get("surveyed_at", ""),
    }


def _symbol_extraction_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["metric_value"]}
        for r in registry.query_metrics_history(slug, "symbol_extraction", "symbol_count")
    ]


@dataclass
class AnalysisKindResults:
    results_reader: Callable    # (registry, slug) -> dict
    trend_reader: Callable | None
    # A small fixed render-mode tag the frontend switches on generically —
    # "findings_list" and "metrics" need zero new frontend code for a new
    # kind; "custom" is the escape hatch for shapes that don't fit either
    # (dependency-by-ecosystem, data-profile summary, API structure).
    render: str


@dataclass
class AnalysisKind:
    """One analysis_catalog.yaml entry — what a user actually sees, runs,
    and schedules. May span more than one STEP_REGISTRY step_key (e.g.
    language_file_classification bundles three)."""
    id: str
    step_keys: list[str]
    family: str = ""             # e.g. "security" — groups related kinds on
                                  # the generic findings/metrics tables' `kind`
                                  # column, so future security-family members
                                  # (secret scanning, CVE checks, SAST,
                                  # branch-protection audit) share one query
                                  # surface without a UNION across tables.
    results: AnalysisKindResults | None = None   # None for kinds with no results view (repository_health)


# "language_file_classification" is the one genuinely ambiguous entry — its
# catalog description ("file types, languages, and project structure") and
# annotation_types span what three separate sub-surveyors emit, so all three
# are bundled here rather than guessing at just one. repo_file_size has no
# catalog entry at all (never independently schedulable/runnable today) so
# it isn't listed — it stays bundled only in a full, steps=None survey.
# egeria_publish is intentionally absent — it's an explicit write action,
# not a survey step; both scheduler.py and the analysis-run route special-
# case entries with action=="publish" before ever consulting this registry.
ANALYSIS_KINDS: dict[str, AnalysisKind] = {
    # Gained a results view when Scouting's "Profile" tab was built — that
    # tab's "Refresh profile" auto-chains this survey against the freshly
    # refreshed file inventory and displays project_file_type_counts, closing
    # the gap where classification data was refreshed but never shown
    # anywhere. repository_health (below) still has no results view; it's
    # covered by the Scouting overview's own stat cards instead.
    "language_file_classification": AnalysisKind(
        "language_file_classification",
        ["repo_language", "repo_file_classification", "repo_file_structure"],
        results=AnalysisKindResults(_file_classification_results, _file_classification_trend, "custom"),
    ),
    "repository_health": AnalysisKind("repository_health", ["repo_health"]),
    "dependency_analysis": AnalysisKind(
        "dependency_analysis", ["repo_dependency"],
        results=AnalysisKindResults(_dependency_results, _dependency_trend, "custom"),
    ),
    "security_scan": AnalysisKind(
        "security_scan", ["repo_security"], family="security",
        results=AnalysisKindResults(_security_results, _security_trend, "findings_list"),
    ),
    "documentation_coverage": AnalysisKind(
        "documentation_coverage", ["repo_documentation"],
        results=AnalysisKindResults(_documentation_results, _documentation_trend, "findings_list"),
    ),
    "data_file_profiling": AnalysisKind(
        "data_file_profiling", ["repo_data_profiling"],
        results=AnalysisKindResults(_data_profile_results, _data_profile_trend, "custom"),
    ),
    # D5 note: deliberately NOT bundled with repo_symbol_extraction the way
    # language_file_classification bundles its three step_keys — this kind
    # is also selectable *scoped* (target_shape: corpus,
    # sub-resource-narrowed runs, see the repo scope-narrowing funnel plan),
    # and repo_symbol_extraction can't honor scope_locator (extraction reads
    # the whole zipball, there's no sub-resource-only extraction) — bundling
    # would silently force a full, unscoped, real zipball-download
    # extraction into every scoped "API Structure" request. Symbol
    # Extraction stays its own AnalysisKind (below) instead — independently
    # run/scheduled, and included automatically in any full (steps=None)
    # survey since it's a plain STEP_REGISTRY member either way.
    "api_structure": AnalysisKind(
        "api_structure", ["repo_api_structure"],
        results=AnalysisKindResults(_api_structure_results, _api_structure_trend, "custom"),
    ),
    "sub_resource_survey": AnalysisKind(
        "sub_resource_survey", ["repo_sub_resource_survey"],
        results=AnalysisKindResults(_sub_resource_survey_results, _sub_resource_survey_trend, "custom"),
    ),
    "license_classification": AnalysisKind(
        "license_classification", ["repo_license_classification"],
        results=AnalysisKindResults(_license_results, None, "findings_list"),
    ),
    "security_features": AnalysisKind(
        "security_features", ["repo_security_features"], family="security",
        results=AnalysisKindResults(_security_features_results, _security_features_trend, "findings_list"),
    ),
    "ci_quality": AnalysisKind(
        "ci_quality", ["repo_ci_quality"],
        results=AnalysisKindResults(_ci_quality_results, _ci_quality_trend, "findings_list"),
    ),
    "maturity": AnalysisKind(
        "maturity", ["repo_maturity"],
        results=AnalysisKindResults(_maturity_results, None, "findings_list"),
    ),
    "repo_conventions": AnalysisKind(
        "repo_conventions", ["repo_conventions"],
        results=AnalysisKindResults(_repo_conventions_results, _repo_conventions_trend, "findings_list"),
    ),
    # D5 — independently runnable/schedulable refresh of project_code_symbols
    # (see repo_symbol_extraction's StepInfo docstring for the bug this
    # closes). Kept separate from "api_structure" rather than bundled into
    # it — see that AnalysisKind's own comment for why.
    "code_symbol_extraction": AnalysisKind(
        "code_symbol_extraction", ["repo_symbol_extraction"],
        results=AnalysisKindResults(_symbol_extraction_results, _symbol_extraction_trend, "custom"),
    ),
}

# Derived views — kept as the same names/shapes scheduler.py and
# web/routes/projects.py already import, so this consolidation doesn't
# force churn in every caller; only ANALYSIS_KINDS is hand-maintained now.
REPO_ANALYSIS_STEP_MAP: dict[str, list[str]] = {k: v.step_keys for k, v in ANALYSIS_KINDS.items()}
REPO_ANALYSIS_RESULTS_MAP: dict[str, tuple] = {
    k: (v.results.results_reader, v.results.trend_reader)
    for k, v in ANALYSIS_KINDS.items() if v.results
}


def _get_project_entity(registry, slug: str):
    return registry.get(slug)


def _publish(project, step_outputs: list, surveyed_at: str, registry) -> str:
    from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
    from resource_explorer.surveyors.survey_report import SurveyResult

    result = SurveyResult(
        project_slug=project.slug,
        project_display_name=project.display_name,
        github_url=project.github_url,
    )
    for output in step_outputs:
        for ann in output.get("annotations", []):
            result.add(ann)

    publisher = EgeriaPublisher(registry=registry)
    return publisher.publish(result)


_ADAPTER = ResourceTypeAdapter(
    entity_type="repo",
    technology_type="Git Repository",
    re_analysis_steps=_build_re_analysis_steps(),
    get_entity=_get_project_entity,
    publish=_publish,
    re_analysis_step_info=_RE_ANALYSIS_STEP_INFO,
)

register_adapter(_ADAPTER)
