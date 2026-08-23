"""Sub-surveyor: Documentation Quality → ClassificationAnnotation."""
from __future__ import annotations

import logging
from datetime import datetime

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.step_outcome import UNVERIFIED, from_upstream_table
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

# File names that indicate good project hygiene. Matched against
# project_file_inventory (every file in the repo — see _store_file_inventory's
# own docstring), not project_code_symbols (only .py/.js/.java/.go files ever
# get symbol rows, so a plain-text/no-symbol file like these can never
# appear there — this whole check was silently a no-op before Assessment
# expansion plan B3 found it while reconciling CODEOWNERS specifically;
# fixed for the whole dict, not just that one entry, since it's the same bug).
_HYGIENE_FILES = {
    "README.md": "README",
    "README.rst": "README",
    "CHANGELOG.md": "Changelog",
    "CHANGELOG.rst": "Changelog",
    "CHANGES.md": "Changelog",
    "CONTRIBUTING.md": "Contributing guide",
    "CONTRIBUTING.rst": "Contributing guide",
    "CODE_OF_CONDUCT.md": "Code of conduct",
    "AUTHORS": "Authors list",
    "AUTHORS.md": "Authors list",
}

# CODEOWNERS is handled separately (not via _HYGIENE_FILES' basename-anywhere
# matching) because GitHub only recognizes it at 3 specific locations —
# registry.file_exists() checks those exact paths via an indexed lookup
# against project_file_inventory's UNIQUE(project_slug, file_path).
_CODEOWNERS_PATHS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")


class DocumentationSurveyor(BaseSurveyor):
    """
    Inspects which documentation collections were indexed and which
    hygiene files appear in the file inventory.

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

            # ── hygiene files from the file inventory ─────────────────────────
            # project_file_inventory (every file in the repo), not
            # project_code_symbols (only .py/.js/.java/.go files ever get
            # rows there — see _HYGIENE_FILES' comment).
            inventory = self.registry.get_file_inventory(slug)
            inventory_filenames = {
                p.replace("\\", "/").rsplit("/", 1)[-1]
                for p in inventory
            }
            found_hygiene: list[str] = []
            for fname, label in _HYGIENE_FILES.items():
                if fname in inventory_filenames and label not in found_hygiene:
                    found_hygiene.append(label)

            # CODEOWNERS folds into the same found_hygiene list/combined
            # annotation as the rest — same shape as the README/CHANGELOG/
            # CONTRIBUTING checks above, just sourced via the exact-path
            # lookup rather than inventory_filenames' basename-anywhere match.
            codeowners_path = self.registry.file_exists(slug, *_CODEOWNERS_PATHS)
            if codeowners_path:
                found_hygiene.append("Code owners")

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
            # Half of `score` comes from the file inventory. With an empty
            # inventory the hygiene half is not zero, it is unmeasured — and the
            # label that came out was "Minimal", a confident verdict about a
            # repository nobody had looked at. That is the exact failure this
            # vocabulary exists to name, on the one step here whose output is a
            # judgement rather than a count.
            outcome = from_upstream_table(
                len(inventory), len(found_hygiene),
                empty_table_cause="empty_file_inventory",
                no_match_cause="no_hygiene_files",
                doc_collections=len(present_doc_types),
            )
            score = len(present_doc_types) + len(found_hygiene)
            if score >= 5:
                quality = "Comprehensive"
            elif score >= 2:
                quality = "Partial"
            else:
                quality = "Minimal"

            unverified = outcome.outcome == UNVERIFIED
            if unverified:
                summary = (
                    f"Documentation quality not established — the file inventory is "
                    f"empty, so only {len(present_doc_types)} collection signal(s) "
                    f"could be counted"
                )
            else:
                summary = f"Documentation quality: {quality} ({score} signal(s) detected)"

            results.append(
                ClassificationAnnotation(
                    summary=summary,
                    analysis_step=STEP,
                    candidate_classifications=[] if unverified else [quality],
                    confidence=70,
                    explanation=(
                        "Hygiene files (README, CHANGELOG, CONTRIBUTING, SECURITY, "
                        "CODEOWNERS) are read from project_file_inventory, which holds "
                        "no rows for this repo. Run repo_file_inventory (or a Profile "
                        "refresh) and re-run before treating this as a quality finding."
                        if unverified else ""
                    ),
                    json_properties={
                        "doc_collection_types": present_doc_types,
                        "hygiene_files": found_hygiene,
                        "signal_count": score,
                        **outcome.as_row(),
                    },
                )
            )
            findings.append({
                # The label the row carries must match what the annotation says.
                # Persisting "Minimal" while the annotation says "not established"
                # would put the wrong answer in the trend, which is the surface
                # that outlives the run.
                "finding_type": "quality_score",
                "label": "Unverified" if unverified else quality,
                "summary": summary,
                "confidence": 70,
                "detail": {
                    "doc_collection_types": present_doc_types,
                    "hygiene_files": found_hygiene,
                    "signal_count": score,
                    **outcome.as_row(),
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
