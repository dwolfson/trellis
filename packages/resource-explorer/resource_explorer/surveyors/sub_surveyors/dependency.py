"""Sub-surveyor: Dependencies → DataClassAnnotation."""
from __future__ import annotations

import logging
from collections import defaultdict

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, DataClassAnnotation, ResourceMeasureAnnotation

log = logging.getLogger(__name__)

STEP = "DependencyAnalysis"


class DependencySurveyor(BaseSurveyor):
    """
    Reads project_dependencies and produces:
      - One DataClassAnnotation per ecosystem (PyPI, npm, Maven, …)
        listing the dependency names found.
      - One ResourceMeasureAnnotation with total counts by dep_type and ecosystem.
    """

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            deps = self.registry.query_dependencies(self.project.slug)
            if not deps:
                return results

            by_ecosystem: dict[str, list[dict]] = defaultdict(list)
            for d in deps:
                by_ecosystem[d.get("ecosystem") or "unknown"].append(d)

            for ecosystem, items in sorted(by_ecosystem.items()):
                names = [d["dep_name"] for d in items]
                dep_types = list({d.get("dep_type") or "runtime" for d in items})
                results.append(
                    DataClassAnnotation(
                        summary=f"{len(names)} {ecosystem} dependency(s): {', '.join(names[:8])}"
                        + (" …" if len(names) > 8 else ""),
                        analysis_step=STEP,
                        candidate_data_class_names=names,
                        confidence=95,
                        json_properties={
                            "ecosystem": ecosystem,
                            "dep_types": dep_types,
                            "dependencies": [
                                {"name": d["dep_name"], "version": d.get("dep_version", ""), "type": d.get("dep_type", "")}
                                for d in items
                            ],
                        },
                    )
                )

            # Aggregate counts
            by_type: dict[str, int] = defaultdict(int)
            by_eco_count: dict[str, int] = defaultdict(int)
            for d in deps:
                by_type[d.get("dep_type") or "runtime"] += 1
                by_eco_count[d.get("ecosystem") or "unknown"] += 1

            results.append(
                ResourceMeasureAnnotation(
                    summary=f"{len(deps)} total dependencies across {len(by_ecosystem)} ecosystem(s)",
                    analysis_step=STEP,
                    resource_properties={
                        "total": len(deps),
                        "by_ecosystem": dict(by_eco_count),
                        "by_type": dict(by_type),
                    },
                )
            )

        except Exception as exc:
            log.exception("DependencySurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
