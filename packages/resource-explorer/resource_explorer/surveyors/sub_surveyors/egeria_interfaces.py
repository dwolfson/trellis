"""Sub-surveyor: which Egeria view services + Dr.Egeria command families this
repository consumes -> ClassificationAnnotation.

Zero-fetch: reads `project_dependencies` (repo_manifest_parse's output, to
gate on pyegeria being declared at all), `project_code_symbols` +
`project_code_relationships` (repo_symbol_extraction's output), and
`project_file_inventory` — all already collected. Discovery tier under
CLAUDE.md rule 17.

See `surveyors/egeria_interfaces.py` for the classifier, the pyegeria
client_class -> view_service mapping, and — importantly — exactly what this
CANNOT tell from stored data alone (no import table exists anywhere in this
codebase, so this is a lower bound, not a count).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from resource_explorer.step_outcome import StepOutcome
from resource_explorer.surveyors import egeria_interfaces as ei
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ClassificationAnnotation

log = logging.getLogger(__name__)

STEP = "EgeriaInterfacesAssessment"
KIND = "egeria_interfaces"

_PYEGERIA_DEP_NAMES = {"pyegeria"}


class EgeriaInterfacesSurveyor(BaseSurveyor):
    """One ClassificationAnnotation per consumed view service, one per
    Dr.Egeria command family (best-effort), plus a coverage annotation."""

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        slug = self.project.slug
        try:
            deps = self.registry.query_dependencies(slug) or []
            pyegeria_declared = any(
                str(d.get("dep_name") or "").strip().lower() in _PYEGERIA_DEP_NAMES for d in deps
            )

            if not pyegeria_declared:
                assessment = ei.assess(
                    pyegeria_declared=False, code_symbol_rows=[], inherits_from_rows=[],
                    file_inventory_paths=[],
                )
                results.append(ClassificationAnnotation(
                    summary=assessment.headline(),
                    analysis_step=STEP, check_name="coverage",
                    candidate_classifications=[], confidence=100,
                    json_properties={"state": ei.NOTHING_FOUND, **StepOutcome(
                        "no_signal", cause="pyegeria_not_declared", known_positive=True,
                        detail={"basis_note": assessment.basis_note}).as_row()},
                ))
                self.registry.upsert_finding(slug, KIND, assessment.as_findings(),
                                             surveyed_at=datetime.now(UTC).isoformat())
                return results

            with self.registry._conn() as conn:
                symbol_rows = [dict(r) for r in conn.execute(
                    "SELECT qualified_name, signature, return_type, file_path "
                    "FROM project_code_symbols WHERE project_slug = ?", (slug,),
                ).fetchall()]
                inherits_rows = [dict(r) for r in conn.execute(
                    "SELECT source_name, target_name FROM project_code_relationships "
                    "WHERE project_slug = ? AND relationship_type = 'inherits_from'", (slug,),
                ).fetchall()]
                inv_rows = conn.execute(
                    "SELECT file_path FROM project_file_inventory WHERE project_slug = ?",
                    (slug,),
                ).fetchall()
            file_paths = [r["file_path"] for r in inv_rows]

            assessment = ei.assess(
                pyegeria_declared=True, code_symbol_rows=symbol_rows,
                inherits_from_rows=inherits_rows, file_inventory_paths=file_paths,
            )

            for vs in assessment.view_services:
                results.append(ClassificationAnnotation(
                    summary=(f"{vs.view_service} — via {', '.join(vs.client_classes)} "
                             f"({vs.symbol_count} symbol reference(s))"),
                    analysis_step=STEP, check_name="view_service",
                    item_key=vs.view_service,
                    candidate_classifications=vs.client_classes,
                    confidence=60,
                    json_properties={
                        "view_service": vs.view_service, "client_classes": vs.client_classes,
                        "symbol_count": vs.symbol_count,
                        **StepOutcome("partial", cause="lower_bound_only",
                                      detail={"basis_note": assessment.basis_note}).as_row(),
                    },
                ))

            for fam in assessment.dr_egeria_families:
                results.append(ClassificationAnnotation(
                    summary=f"{fam.name} — {len(fam.paths)} file(s), name guessed from filename",
                    analysis_step=STEP, check_name="dr_egeria_family",
                    item_key=fam.name,
                    candidate_classifications=[fam.name],
                    confidence=30,
                    json_properties={"paths": fam.paths, "basis": fam.basis,
                                     **StepOutcome("partial", cause="filename_guess_not_heading_text").as_row()},
                ))

            results.append(ClassificationAnnotation(
                summary=assessment.headline(),
                analysis_step=STEP, check_name="coverage",
                candidate_classifications=[], confidence=40,
                json_properties={
                    "view_services": len(assessment.view_services),
                    "unmapped_client_classes": assessment.unmapped_client_classes,
                    "dr_egeria_doc_count": len(assessment.dr_egeria_doc_paths),
                    "dr_egeria_families": len(assessment.dr_egeria_families),
                    "state": assessment.state,
                    "basis_note": assessment.basis_note,
                    **StepOutcome("recovered").as_row(),
                },
            ))

            self.registry.upsert_finding(slug, KIND, assessment.as_findings(),
                                         surveyed_at=datetime.now(UTC).isoformat())
        except Exception as exc:
            log.exception("EgeriaInterfacesSurveyor failed for %s", slug)
            self._warn(results, str(exc))
        return results
