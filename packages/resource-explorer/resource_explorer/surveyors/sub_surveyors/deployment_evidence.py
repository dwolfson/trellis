"""Sub-surveyor: per-distribution deployment evidence -> ClassificationAnnotation.

Zero-fetch: reads `project_analysis_findings` kind="distribution" (written by
repo_manifest_parse's DistributionParser) and kind="repo_conventions"
check_name="deployment_docker" (Dockerfile/compose/Helm PRESENCE), plus
`project_dependencies` and `project_file_inventory` — all already collected.
Discovery tier under CLAUDE.md rule 17: reasons over what earlier steps wrote,
fetches nothing from the repository itself.

Layer 1 of "Cataloguing in layers" (project owner, 2026-09-14): before a
distribution is proposed to Egeria as a `SoftwareCapability` classified
`Application`, this is the evidence that verdict rests on. See
`surveyors/deployment_evidence.py` for the classifier and what it can and
cannot tell from stored data alone.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from resource_explorer.step_outcome import StepOutcome
from resource_explorer.surveyors import deployment_evidence as de
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ClassificationAnnotation

log = logging.getLogger(__name__)

STEP = "DeploymentEvidenceAssessment"
KIND = "deployment_evidence"


def _parse_detail(row: dict) -> dict:
    d = row.get("detail")
    if isinstance(d, dict):
        return d
    import json
    raw = row.get("detail_json")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class DeploymentEvidenceSurveyor(BaseSurveyor):
    """One ClassificationAnnotation per declared distribution (application /
    library / unknown), plus a coverage annotation."""

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        slug = self.project.slug
        try:
            dist_rows = self.registry.query_findings(slug, "distribution") or []
            if not dist_rows:
                outcome = StepOutcome("unverified", cause="no_distribution_findings",
                                      detail={"hint": "run repo_manifest_parse first"})
                results.append(ClassificationAnnotation(
                    summary="No declared-distribution rows held for this repository — nothing "
                            "to judge (manifest parsing may not have run)",
                    analysis_step=STEP, check_name="nothing_to_assess",
                    candidate_classifications=[], confidence=0,
                    json_properties={"distribution_count": 0, **outcome.as_row()},
                ))
                self.registry.upsert_finding(slug, KIND, [{
                    "check_name": "coverage", "label": "no_manifest_read",
                    "summary": "No declared distributions to judge — repo_manifest_parse has not run",
                    "confidence": 0,
                    "detail": {"application": 0, "library": 0, "unknown": 0, "distribution_count": 0},
                }], surveyed_at=datetime.now(UTC).isoformat())
                return results

            conventions_rows = self.registry.query_findings(slug, "repo_conventions") or []
            docker_paths: list[str] = []
            for r in conventions_rows:
                if r.get("check_name") == "deployment_docker":
                    docker_paths = list(_parse_detail(r).get("files") or [])
                    break

            deps = self.registry.query_dependencies(slug) or []

            with self.registry._conn() as conn:
                inv_rows = conn.execute(
                    "SELECT file_path FROM project_file_inventory WHERE project_slug = ?",
                    (slug,),
                ).fetchall()
            file_paths = [r["file_path"] for r in inv_rows]

            distribution_findings = [{"detail": _parse_detail(r)} for r in dist_rows]
            assessment = de.assess(
                distribution_findings,
                file_inventory_paths=file_paths,
                docker_evidence_paths=docker_paths,
                dependency_rows=deps,
            )

            for d in assessment.distributions:
                results.append(ClassificationAnnotation(
                    summary=d.summary(),
                    analysis_step=STEP, check_name="distribution",
                    # list-shaped — one per distribution — so item_key is
                    # required, exactly the lesson dependency_support's #46
                    # regression taught (surveyors/sub_surveyors/
                    # dependency_support.py's own comment on this).
                    item_key=d.name,
                    candidate_classifications=[d.verdict],
                    confidence=90 if d.verdict != de.UNKNOWN else 0,
                    json_properties={
                        "distribution": d.name,
                        "ecosystem": d.ecosystem,
                        "verdict": d.verdict,
                        "evidence": [e.as_dict() for e in d.evidence],
                        "consumers_in_repo": d.consumers_in_repo,
                        "could_not_check": d.could_not_check,
                        **StepOutcome("recovered").as_row(),
                    },
                ))

            c = assessment.counts
            results.append(ClassificationAnnotation(
                summary=(f"{c[de.APPLICATION]} application(s), {c[de.LIBRARY]} librar"
                         f"{'y' if c[de.LIBRARY] == 1 else 'ies'}; {c[de.UNKNOWN]} unknown"),
                analysis_step=STEP, check_name="coverage",
                candidate_classifications=[], confidence=100,
                json_properties={**c, "distribution_count": len(assessment.distributions),
                                 **StepOutcome("recovered").as_row()},
            ))

            self.registry.upsert_finding(slug, KIND, assessment.as_findings(),
                                         surveyed_at=datetime.now(UTC).isoformat())
        except Exception as exc:
            log.exception("DeploymentEvidenceSurveyor failed for %s", slug)
            self._warn(results, str(exc))
        return results
