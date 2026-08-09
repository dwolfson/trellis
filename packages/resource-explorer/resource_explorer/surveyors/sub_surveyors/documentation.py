"""Sub-surveyor: Documentation Quality → ClassificationAnnotation."""
from __future__ import annotations

import logging
from datetime import datetime

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ClassificationAnnotation

log = logging.getLogger(__name__)

STEP = "DocumentationAnalysis"

# Collection types that indicate documentation was indexed
_DOC_COLLECTIONS = {
    "markdown_docs": "Markdown documentation",
    "web_docs": "Web / hosted documentation",
    "api_reference": "API reference (OpenAPI / docstrings)",
    "examples": "Code examples / notebooks",
    "pdfs": "PDF documentation",
    "release_notes": "Release notes / changelog",
}

# File names that indicate good project hygiene
_HYGIENE_FILES = {
    "README.md": "README",
    "README.rst": "README",
    "CHANGELOG.md": "Changelog",
    "CHANGELOG.rst": "Changelog",
    "CHANGES.md": "Changelog",
    "CONTRIBUTING.md": "Contributing guide",
    "CONTRIBUTING.rst": "Contributing guide",
    "CODE_OF_CONDUCT.md": "Code of conduct",
    "CODEOWNERS": "Code owners",
    "AUTHORS": "Authors list",
    "AUTHORS.md": "Authors list",
}


class DocumentationSurveyor(BaseSurveyor):
    """
    Inspects which documentation collections were indexed and which
    hygiene files appear in the symbol file paths.

    Produces ClassificationAnnotations describing:
      - Which doc collection types are present
      - Which hygiene files were found
      - An overall doc quality label (Comprehensive / Partial / Minimal)
    """

    def __init__(self, project: Project, registry: ProjectRegistry, surveyed_at: str | None = None) -> None:
        super().__init__(project, registry)
        # See SecurityHygieneSurveyor's identical constructor comment — shared
        # run-timestamp from SurveyOrchestrator (Phase B, D1).
        self._surveyed_at = surveyed_at or datetime.utcnow().isoformat()

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        findings: list[dict] = []
        try:
            # ── collection presence from registry ─────────────────────────────
            slug = self.project.slug
            project_collections = set(self.project.collections)
            present_doc_types: list[str] = []

            for col_type, label in _DOC_COLLECTIONS.items():
                col_name = f"{slug}_{col_type}"
                if col_name in project_collections:
                    present_doc_types.append(label)
                    results.append(
                        ClassificationAnnotation(
                            summary=f"Collection present: {label}",
                            analysis_step=STEP,
                            candidate_classifications=[col_type],
                            confidence=100,
                        )
                    )
                    findings.append({
                        "finding_type": "collection_present", "label": col_type,
                        "summary": f"Collection present: {label}",
                        "confidence": 100, "detail": {"display_label": label},
                    })

            # ── hygiene files from code symbol paths ──────────────────────────
            with self.registry._conn() as conn:
                path_rows = conn.execute(
                    "SELECT DISTINCT file_path FROM project_code_symbols WHERE project_slug = ?",
                    (slug,),
                ).fetchall()

            indexed_filenames = {
                r["file_path"].replace("\\", "/").rsplit("/", 1)[-1]
                for r in path_rows
            }
            found_hygiene: list[str] = []
            for fname, label in _HYGIENE_FILES.items():
                if fname in indexed_filenames and label not in found_hygiene:
                    found_hygiene.append(label)

            if found_hygiene:
                results.append(
                    ClassificationAnnotation(
                        summary=f"Hygiene files found: {', '.join(found_hygiene)}",
                        analysis_step=STEP,
                        candidate_classifications=found_hygiene,
                        confidence=95,
                    )
                )
                findings.append({
                    "finding_type": "hygiene_files", "label": ", ".join(found_hygiene),
                    "summary": f"Hygiene files found: {', '.join(found_hygiene)}",
                    "confidence": 95, "detail": {"files": found_hygiene},
                })

            # ── overall quality label ─────────────────────────────────────────
            score = len(present_doc_types) + len(found_hygiene)
            if score >= 5:
                quality = "Comprehensive"
            elif score >= 2:
                quality = "Partial"
            else:
                quality = "Minimal"

            results.append(
                ClassificationAnnotation(
                    summary=f"Documentation quality: {quality} ({score} signal(s) detected)",
                    analysis_step=STEP,
                    candidate_classifications=[quality],
                    confidence=70,
                    json_properties={
                        "doc_collection_types": present_doc_types,
                        "hygiene_files": found_hygiene,
                        "signal_count": score,
                    },
                )
            )
            findings.append({
                "finding_type": "quality_score", "label": quality,
                "summary": f"Documentation quality: {quality} ({score} signal(s) detected)",
                "confidence": 70,
                "detail": {
                    "doc_collection_types": present_doc_types,
                    "hygiene_files": found_hygiene,
                    "signal_count": score,
                },
            })

            try:
                # Generic project_analysis_findings table (analysis-kind
                # extensibility redesign) — translate this surveyor's own
                # "finding_type"/"label" vocabulary to the generic
                # check_name/label field names at the call boundary.
                self.registry.upsert_finding(
                    slug, "documentation",
                    [
                        {
                            "check_name": f["finding_type"], "label": f["label"],
                            "summary": f.get("summary", ""),
                            "confidence": f.get("confidence", 100), "detail": f.get("detail"),
                        }
                        for f in findings
                    ],
                    surveyed_at=self._surveyed_at,
                )
            except Exception as exc:
                log.warning("Could not persist documentation findings for %s: %s", slug, exc)

        except Exception as exc:
            log.exception("DocumentationSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
