"""Sub-surveyor: File Structure → ResourceMeasureAnnotation."""
from __future__ import annotations

import logging
from collections import Counter

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ResourceMeasureAnnotation

log = logging.getLogger(__name__)

STEP = "FileStructure"


class FileStructureSurveyor(BaseSurveyor):
    """
    Produces ResourceMeasureAnnotations describing the physical shape of the repo:
      - Total file count and size from project_stats
      - Per-language file count from project_code_symbols
      - Top-level directory breakdown from indexed file paths
    """

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            slug = self.project.slug

            # ── aggregate stats from project_stats ───────────────────────────
            # D2(c) (docs/repo-survey-catalog-completion-plan.md): named
            # registry accessor instead of a hand-rolled query — a third
            # confirmed instance of the same "latest project_stats row"
            # duplicate found in health.py/security_hygiene.py/language.py.
            stats = self.registry.get_latest_project_stats(slug) or {}
            file_count = stats.get("ingestion_file_count") or stats.get("file_count") or 0
            size_kb = stats.get("repo_size_kb") or 0
            loc = stats.get("ingestion_lines_of_code") or 0

            results.append(
                ResourceMeasureAnnotation(
                    summary=f"Repository contains ~{file_count:,} files, {size_kb:,} KB",
                    analysis_step=STEP,
                    resource_properties={
                        "file_count": file_count,
                        "repo_size_kb": size_kb,
                        "lines_of_code": loc,
                    },
                    json_properties={"source": "project_stats"},
                )
            )

            # ── per-language breakdown from code symbols ──────────────────────
            with self.registry._conn() as conn:
                rows = conn.execute(
                    "SELECT language, COUNT(DISTINCT file_path) as file_count "
                    "FROM project_code_symbols WHERE project_slug = ? GROUP BY language ORDER BY file_count DESC",
                    (slug,),
                ).fetchall()

            if rows:
                lang_breakdown = {r["language"]: r["file_count"] for r in rows}
                results.append(
                    ResourceMeasureAnnotation(
                        summary=f"Indexed source files span {len(lang_breakdown)} language(s)",
                        analysis_step=STEP,
                        resource_properties={"by_language": lang_breakdown},
                        json_properties={"source": "project_code_symbols"},
                    )
                )

            # ── top-level directory breakdown ─────────────────────────────────
            # D2(c): confirmed duplicate of security_hygiene.py's identical
            # query, now the named registry accessor.
            paths = self.registry.get_code_symbol_file_paths(slug)

            if paths:
                top_dirs: Counter = Counter()
                for file_path in paths:
                    parts = file_path.replace("\\", "/").split("/")
                    top_dirs[parts[0] if len(parts) > 1 else "(root)"] += 1

                results.append(
                    ResourceMeasureAnnotation(
                        summary=f"Source files distributed across {len(top_dirs)} top-level directories",
                        analysis_step=STEP,
                        resource_properties={"top_level_dirs": dict(top_dirs.most_common(20))},
                    )
                )

        except Exception as exc:
            log.exception("FileStructureSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
