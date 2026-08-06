"""Sub-surveyor: API / Module Structure → SchemaAnalysisAnnotation."""
from __future__ import annotations

import logging
from collections import defaultdict

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ResourceMeasureAnnotation, SchemaAnalysisAnnotation

log = logging.getLogger(__name__)

STEP = "ApiStructureAnalysis"

# Symbol kinds treated as public API surface
_PUBLIC_KINDS = {"function", "class", "method"}


class ApiStructureSurveyor(BaseSurveyor):
    """
    Reads project_code_symbols and produces:
      - One SchemaAnalysisAnnotation per language summarising the module tree
        and counts of public symbols.
      - One ResourceMeasureAnnotation with total symbol counts by kind.
    """

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            slug = self.project.slug

            with self.registry._conn() as conn:
                rows = conn.execute(
                    "SELECT language, kind, name, qualified_name, file_path "
                    "FROM project_code_symbols WHERE project_slug = ? ORDER BY language, kind, name",
                    (slug,),
                ).fetchall()

            if not rows:
                return results

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
                        },
                    )
                )

            results.append(
                ResourceMeasureAnnotation(
                    summary=f"Total indexed symbols: {len(rows)} across {len(by_lang)} language(s)",
                    analysis_step=STEP,
                    resource_properties={"symbol_counts_by_kind": dict(kind_counts)},
                )
            )

        except Exception as exc:
            log.exception("ApiStructureSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
