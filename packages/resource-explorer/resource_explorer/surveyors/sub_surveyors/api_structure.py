"""Sub-surveyor: API / Module Structure → SchemaAnalysisAnnotation."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.scoping import sql_scope_filter
from resource_explorer.surveyors.survey_report import (
    Annotation,
    ResourceMeasureAnnotation,
    SchemaAnalysisAnnotation,
)

log = logging.getLogger(__name__)

STEP = "ApiStructureAnalysis"

# Symbol kinds treated as public API surface
_PUBLIC_KINDS = {"function", "class", "method"}


class ApiStructureSurveyor(BaseSurveyor):
    """
    Reads project_code_symbols (and, since AST-ownership-transfer plan
    Phase 4, project_code_relationships) and produces:
      - One SchemaAnalysisAnnotation per language summarising the module tree,
        counts of public symbols, complexity, and inheritance depth.
      - One ResourceMeasureAnnotation with total symbol/relationship counts.

    This surveyor doesn't itself extract symbols — extraction happens earlier,
    inline during ingestion (IngestionPipeline._ingest_code(), which already
    re-runs on every full add and incremental refresh — see
    ingestion/code_symbol_extractor.py / java_symbol_extractor.py). Since this
    surveyor is already in SurveyOrchestrator.run()'s fixed sub-surveyor list,
    it runs — and its annotations reflect current data — on every repo survey
    without any separate opt-in scheduling (migration plan decision D7).
    """

    def __init__(
        self, project: Project, registry: ProjectRegistry, surveyed_at: str | None = None,
        scope_locator: str = "",
    ) -> None:
        super().__init__(project, registry)
        # See SecurityHygieneSurveyor's identical constructor comment — shared
        # run-timestamp from SurveyOrchestrator (Phase B, D1).
        self._surveyed_at = surveyed_at or datetime.utcnow().isoformat()
        # Repo scope-narrowing funnel plan (docs/repo-scope-narrowing-funnel.md),
        # D5/D6 — "" (default) = whole-repo, unchanged from every existing
        # caller; a non-empty locator narrows to one cataloged sub-resource
        # (this kind is target_shape="corpus" — a path-prefix filter).
        self._scope_locator = scope_locator

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            slug = self.project.slug

            scope_sql, scope_params = sql_scope_filter(self._scope_locator)
            with self.registry._conn() as conn:
                rows = conn.execute(
                    "SELECT language, kind, name, qualified_name, file_path, complexity "
                    "FROM project_code_symbols WHERE project_slug = ?" + scope_sql +
                    " ORDER BY language, kind, name",
                    (slug, *scope_params),
                ).fetchall()

            if not rows:
                return results

            # Inheritance/relationship edges are a cross-cutting graph, not
            # cleanly per-file — left whole-repo-scoped even for a scoped
            # run rather than guessing a filtering rule; the symbol-level
            # data above (this method's primary output) is correctly scoped.
            relationships = self.registry.get_code_relationships(slug)

            by_lang: dict[str, list] = defaultdict(list)
            kind_counts: dict[str, int] = defaultdict(int)
            for r in rows:
                by_lang[r["language"]].append(r)
                kind_counts[r["kind"]] += 1

            for language, symbols in sorted(by_lang.items()):
                public = [s for s in symbols if s["kind"] in _PUBLIC_KINDS]
                module_files = list({s["file_path"] for s in symbols})
                top_names = [s["name"] for s in public if s["kind"] == "class"][:10]
                top_names += [s["name"] for s in public if s["kind"] == "function"][:10]

                complexities = [s["complexity"] or 0 for s in symbols if s["kind"] in ("function", "method")]
                complexity_summary = {
                    "max": max(complexities) if complexities else 0,
                    "avg": round(sum(complexities) / len(complexities), 1) if complexities else 0,
                }
                lang_class_names = {s["qualified_name"] for s in symbols if s["kind"] == "class"}
                lang_relationship_count = sum(
                    1 for r in relationships if r["source_name"] in lang_class_names
                )

                results.append(
                    SchemaAnalysisAnnotation(
                        summary=(
                            f"{language}: {len(public)} public symbol(s) across "
                            f"{len(module_files)} file(s)"
                        ),
                        analysis_step=STEP,
                        schema_name=f"{slug}:{language}",
                        schema_type=language,
                        confidence=90,
                        json_properties={
                            "file_count": len(module_files),
                            "symbol_counts": {
                                k: sum(1 for s in symbols if s["kind"] == k)
                                for k in _PUBLIC_KINDS
                            },
                            "top_symbols": top_names[:15],
                            "complexity": complexity_summary,
                            "inheritance_edges": lang_relationship_count,
                        },
                    )
                )

            results.append(
                ResourceMeasureAnnotation(
                    summary=(
                        f"Total indexed symbols: {len(rows)} across {len(by_lang)} language(s), "
                        f"{len(relationships)} inheritance relationship(s)"
                    ),
                    analysis_step=STEP,
                    resource_properties={
                        "symbol_counts_by_kind": dict(kind_counts),
                        "relationship_count": len(relationships),
                    },
                )
            )

            try:
                # Generic project_analysis_metrics table (analysis-kind
                # extensibility redesign) — symbol/relationship counts as
                # the two trendable metrics; by_language breakdown attaches
                # as this run's detail blob.
                self.registry.upsert_metric(
                    slug, "api_structure",
                    {"symbol_count": len(rows), "relationship_count": len(relationships)},
                    detail={"by_language": {lang: len(syms) for lang, syms in by_lang.items()}},
                    surveyed_at=self._surveyed_at,
                    scope_locator=self._scope_locator,
                )
            except Exception as exc:
                log.warning("Could not persist API structure snapshot for %s: %s", slug, exc)

        except Exception as exc:
            log.exception("ApiStructureSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
