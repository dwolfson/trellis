"""Sub-surveyor: Language → ClassificationAnnotation."""
from __future__ import annotations

import json
import logging

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ClassificationAnnotation

log = logging.getLogger(__name__)

STEP = "LanguageClassification"


class LanguageSurveyor(BaseSurveyor):
    """
    Classifies the project by programming language using GitHub-reported
    language_breakdown from project_stats.

    Produces:
      - One ClassificationAnnotation for the primary language
      - One ClassificationAnnotation listing all secondary languages (>5% share)
      - One ClassificationAnnotation for inferred project type
        (library / CLI / service / data-pipeline / notebook / mixed)
    """

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            slug = self.project.slug
            # D2(c) (docs/repo-survey-catalog-completion-plan.md): named
            # registry accessor instead of a hand-rolled query — a fourth
            # confirmed instance of the same "latest project_stats row"
            # duplicate found in health.py/security_hygiene.py/file_structure.py.
            row = self.registry.get_latest_project_stats(slug)

            if not row:
                self._warn(results, "No stats row found — run 'refresh' to populate stats.")
                return results

            primary = row["primary_language"] or "Unknown"
            breakdown: dict = {}
            try:
                breakdown = json.loads(row["language_breakdown"] or "{}")
            except (json.JSONDecodeError, TypeError):
                pass
            topics: list[str] = []
            try:
                topics = json.loads(row["topics"] or "[]")
            except (json.JSONDecodeError, TypeError):
                pass

            # Primary language
            results.append(
                ClassificationAnnotation(
                    summary=f"Primary language: {primary}",
                    analysis_step=STEP,
                    candidate_classifications=[primary],
                    confidence=95,
                )
            )

            # Secondary languages (>5% share by byte count)
            if breakdown:
                total = sum(breakdown.values()) or 1
                secondary = [
                    lang for lang, count in breakdown.items()
                    if lang != primary and count / total > 0.05
                ]
                if secondary:
                    results.append(
                        ClassificationAnnotation(
                            summary=f"Secondary language(s): {', '.join(secondary)}",
                            analysis_step=STEP,
                            candidate_classifications=secondary,
                            confidence=85,
                            json_properties={"language_breakdown": breakdown},
                        )
                    )

            # Infer project type from topics and collections
            project_type = self._infer_project_type(primary, topics)
            results.append(
                ClassificationAnnotation(
                    summary=f"Inferred project type: {project_type}",
                    analysis_step=STEP,
                    candidate_classifications=[project_type],
                    confidence=60,
                    explanation="Inferred from primary language and GitHub topics; low confidence — review recommended.",
                    json_properties={"topics": topics},
                )
            )

        except Exception as exc:
            log.exception("LanguageSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results

    @staticmethod
    def _infer_project_type(primary: str, topics: list[str]) -> str:
        topic_set = {t.lower() for t in topics}
        if any(t in topic_set for t in ("cli", "command-line", "terminal")):
            return "CLI Tool"
        if any(t in topic_set for t in ("api", "rest-api", "microservice", "service", "web")):
            return "Service / API"
        if any(t in topic_set for t in ("library", "sdk", "framework", "plugin")):
            return "Library / SDK"
        if any(t in topic_set for t in ("notebook", "jupyter", "analysis", "data-science")):
            return "Notebook / Analysis"
        if any(t in topic_set for t in ("pipeline", "etl", "data-pipeline", "workflow")):
            return "Data Pipeline"
        if primary in ("Jupyter Notebook",):
            return "Notebook / Analysis"
        return "Mixed / Unknown"
